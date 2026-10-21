"""Job manager for the local dsh-worker Codex plugin.

This module deliberately uses ordinary files and OS process inspection instead
of an in-memory job registry.  A Codex restart therefore does not lose the
location of a running worker, and no model call is made to decide whether a
process is alive.
"""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import gitutil
import heartbeat
import procutil
from store import (
    LEASE_FILE,
    LEASE_SCHEMA,
    MUTATION_LOCK_NAME,
    atomic_write_json,
    atomic_write_text,
    iso,
    new_job_id,
    parse_iso,
    read_json_bounded,
    read_lease,
    read_text_bounded,
    utc_now,
    valid_job_id,
)

MODEL = "deepseek-v4.1-flash"
EFFORT = "max"
ACCOUNT = "2"
KEY_ENV = "OPENCODE_GO_API_KEY_2"
MODEL_LAUNCHER_MODULE = "reality_engine.scripts.run_deepseek_harness"
PERMISSIONS = ("read-only", "workspace-write", "danger-full-access")
FINAL_PHASES = frozenset({"finished", "failed", "cancelled", "lost"})
ACTIVE_PHASES = frozenset({"starting", "running", "cancelling"})
IST = timezone(timedelta(hours=5, minutes=30))
MAX_BRIEF_BYTES = 262_144
MAX_MESSAGE_BYTES = 32_768
MAX_RESULT_BYTES = 1_048_576
DEFAULT_RESULT_BYTES = 65_536
MAX_OUTPUT_TOKENS = 200_000
SERVER_SHUTDOWN_SEMANTICS = (
    "The MCP server owns a detached supervisor and a Windows job object around "
    "the worker. Closing the stdio session ends the server; a host such as the "
    "MCP client used by Codex may terminate the server's process tree, which "
    "also stops the supervisor and worker. If the supervisor dies alone, its "
    "KILL_ON_JOB_CLOSE job object terminates the worker. Persisted job records "
    "remain for inspection. Use cancel_worker(confirm=true) for deliberate "
    "cancellation; no writer is left uncontrolled."
)


class PluginError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


def is_peak(now: datetime | None = None) -> bool:
    """Peak is Mon-Fri 06:30-09:30 and 11:30-15:30 IST."""
    local = (now or datetime.now(timezone.utc)).astimezone(IST)
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    return (6 * 60 + 30 <= minutes < 9 * 60 + 30) or (11 * 60 + 30 <= minutes < 15 * 60 + 30)


def _within(root: Path, candidate: Path) -> bool:
    root_s = os.path.normcase(str(root))
    cand_s = os.path.normcase(str(candidate))
    try:
        return os.path.commonpath([root_s, cand_s]) == root_s
    except ValueError:
        return False


def _awaiting_input_valid(record: dict[str, Any] | None) -> bool:
    """Trust a persisted awaiting flag only while its absolute lease is valid.

    A wedged launcher can leave ``heartbeat.json`` unchanged with
    ``awaiting_input=true``.  The wait must therefore carry an absolute
    deadline; a missing, expired, or implausibly distant deadline fails closed
    and lets normal stale/heartbeat supervision resume.
    """
    if not isinstance(record, dict) or not record.get("awaiting_input"):
        return False
    deadline = record.get("awaiting_deadline")
    if not isinstance(deadline, str) or not deadline:
        return False
    try:
        parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    remaining = (parsed - datetime.now(timezone.utc)).total_seconds()
    return -5.0 <= remaining <= 3605.0


@dataclass(frozen=True)
class PluginConfig:
    repo_root: Path
    plugin_root: Path
    runtime_dir: Path
    launcher_path: Path | None
    launcher_module: str
    fake_now: datetime | None = None
    stale_after_seconds: int | None = None
    environ: dict[str, str] | None = None

    @property
    def jobs_dir(self) -> Path:
        return self.runtime_dir / "jobs"

    @property
    def locks_dir(self) -> Path:
        return self.runtime_dir / "locks"

    def now(self) -> datetime:
        return self.fake_now or datetime.now(timezone.utc)


def load_config(environ: dict[str, str] | None = None) -> PluginConfig:
    env = dict(os.environ if environ is None else environ)
    plugin_root = Path(__file__).resolve().parents[1]
    raw_repo = env.get("DSH_WORKER_REPO_ROOT")
    if raw_repo:
        repo_root = Path(raw_repo).expanduser().resolve()
    else:
        candidate = plugin_root.parents[1] if len(plugin_root.parents) > 1 else plugin_root
        if (candidate / "reality_engine").is_dir():
            repo_root = candidate.resolve()
        elif (Path.cwd() / "reality_engine").is_dir():
            repo_root = Path.cwd().resolve()
        else:
            raise PluginError(
                "repo_root_missing",
                "DSH_WORKER_REPO_ROOT is not set and the repository root cannot be inferred",
            )
    if not (repo_root / "reality_engine").is_dir():
        raise PluginError(
            "repo_root_invalid",
            "DSH_WORKER_REPO_ROOT does not point at the Reality Engine repository",
        )
    raw_runtime = env.get("DSH_WORKER_RUNTIME_DIR")
    runtime_dir = (
        Path(raw_runtime).expanduser().resolve()
        if raw_runtime
        else (repo_root / "plugins" / "dsh-worker" / "runtime").resolve()
    )
    raw_launcher = env.get("DSH_WORKER_LAUNCHER")
    launcher_path = Path(raw_launcher).expanduser().resolve() if raw_launcher else None
    if launcher_path is not None and not launcher_path.is_file():
        raise PluginError(
            "launcher_missing", "DSH_WORKER_LAUNCHER does not point at a file"
        )
    fake_now = None
    if env.get("DSH_WORKER_TESTING") == "1":
        raw_now = env.get("DSH_WORKER_FAKE_NOW")
        if raw_now:
            fake_now = parse_iso(raw_now)
            if fake_now is None:
                raise PluginError(
                    "test_clock_invalid", "DSH_WORKER_FAKE_NOW must be an ISO-8601 timestamp"
                )
    stale_override = None
    if env.get("DSH_WORKER_STALE_AFTER_SECONDS"):
        try:
            stale_override = int(env["DSH_WORKER_STALE_AFTER_SECONDS"])
        except ValueError as exc:
            raise PluginError("config_invalid", "DSH_WORKER_STALE_AFTER_SECONDS must be an integer") from exc
        if not 30 <= stale_override <= 86_400:
            raise PluginError("config_invalid", "stale threshold must be 30..86400 seconds")
    return PluginConfig(
        repo_root=repo_root,
        plugin_root=plugin_root,
        runtime_dir=runtime_dir,
        launcher_path=launcher_path,
        launcher_module=MODEL_LAUNCHER_MODULE,
        fake_now=fake_now,
        stale_after_seconds=stale_override,
        environ=env,
    )


class Manager:
    def __init__(self, config: PluginConfig) -> None:
        self.config = config
        self._capabilities: heartbeat.LauncherCapabilities | None = None
        self._children: list[subprocess.Popen[bytes]] = []
        # Per-job control tokens are deliberately memory-only.  A restarted MCP
        # server cannot authenticate a job it did not launch; it says so instead
        # of reading a token from a file.
        self._control_tokens: dict[str, str] = {}
        # Controller lease ownership is memory-only: a restarted MCP server
        # cannot renew a job it did not launch, so the persisted deadline stays
        # a hard upper bound across restarts.
        self._lease_owners: dict[str, str] = {}

    # ------------------------------------------------------------------ paths
    def _job_dir(self, job_id: str) -> Path:
        if not valid_job_id(job_id):
            raise PluginError("job_id_invalid", "job_id is not a plugin job identifier")
        path = self.config.jobs_dir / job_id
        if not _within(self.config.jobs_dir.resolve(), path.resolve()):
            raise PluginError("job_id_invalid", "job path escapes the runtime directory")
        return path

    def _job_paths(self, job_id: str) -> dict[str, str]:
        job_dir = self._job_dir(job_id)
        return {
            "job_dir": str(job_dir),
            "job_record": str(job_dir / "job.json"),
            "status": str(job_dir / "status.json"),
            "brief": str(job_dir / "brief.md"),
            "result": str(job_dir / "result.md"),
            "launcher_log": str(job_dir / "result.md.log"),
            "events": str(job_dir / "result.md.events.jsonl"),
            "stdout_log": str(job_dir / "stdout.log"),
            "stderr_log": str(job_dir / "stderr.log"),
            "supervisor_log": str(job_dir / "supervisor.log"),
            "heartbeat": str(job_dir / "heartbeat.json"),
            "control": str(job_dir / "result.md.control.json"),
        }

    # ---------------------------------------------------------- validation
    def _workspace(self, candidate: str) -> Path:
        try:
            path = Path(candidate or ".").expanduser()
            if not path.is_absolute():
                path = self.config.repo_root / path
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PluginError("workspace_invalid", f"workspace cannot be resolved: {exc}") from exc
        if not _within(self.config.repo_root, resolved):
            raise PluginError(
                "workspace_outside_repo",
                "workspace must be inside the configured repository root",
            )
        if not resolved.is_dir():
            raise PluginError("workspace_invalid", "workspace is not a directory")
        return resolved

    def _task_file(self, candidate: str) -> tuple[Path, str]:
        try:
            path = Path(candidate).expanduser()
            if not path.is_absolute():
                path = self.config.repo_root / path
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PluginError("task_file_invalid", f"task file cannot be resolved: {exc}") from exc
        if not _within(self.config.repo_root, resolved):
            raise PluginError("task_file_outside_repo", "task file must be inside the repository root")
        if not resolved.is_file():
            raise PluginError("task_file_invalid", "task file is not a regular file")
        return resolved, str(resolved.relative_to(self.config.repo_root))

    def _read_brief(self, brief: str | None, task_file: str | None) -> tuple[str, str | None]:
        if (brief is None) == (task_file is None):
            raise PluginError(
                "brief_required",
                "provide exactly one of brief or task_file",
            )
        if task_file is not None:
            path, relative = self._task_file(task_file)
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise PluginError("task_file_invalid", f"task file cannot be read: {exc}") from exc
            if size > MAX_BRIEF_BYTES:
                raise PluginError(
                    "brief_too_large", f"task file exceeds {MAX_BRIEF_BYTES} bytes"
                )
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise PluginError("task_file_invalid", f"task file is not UTF-8 text: {exc}") from exc
            if "\x00" in text:
                raise PluginError("task_file_invalid", "task file must not contain NUL bytes")
            if not text.strip():
                raise PluginError("brief_empty", "task file is empty")
            return text, relative
        assert brief is not None
        if len(brief.encode("utf-8", errors="replace")) > MAX_BRIEF_BYTES:
            raise PluginError("brief_too_large", f"brief exceeds {MAX_BRIEF_BYTES} UTF-8 bytes")
        if "\x00" in brief:
            raise PluginError("brief_invalid", "brief must not contain NUL bytes")
        if not brief.strip():
            raise PluginError("brief_empty", "brief is empty")
        return brief, None

    def _launcher_command(self) -> list[str]:
        if self.config.launcher_path is not None:
            return [sys.executable, str(self.config.launcher_path)]
        return [sys.executable, "-m", self.config.launcher_module]

    def _launcher_env(self) -> dict[str, str]:
        env = dict(self.config.environ or os.environ)
        repo = str(self.config.repo_root)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = repo + (os.pathsep + existing if existing else "")
        env["PYTHONUTF8"] = "1"
        return env

    def _capability(self) -> heartbeat.LauncherCapabilities:
        if self._capabilities is None:
            self._capabilities = heartbeat.probe_launcher(
                self._launcher_command(), self.config.repo_root, self._launcher_env()
            )
        return self._capabilities

    # ------------------------------------------------------------- provider
    def _provider_session(self) -> str | None:
        path = self.config.repo_root / "reality_engine" / "scripts" / "go_session.py"
        try:
            spec = importlib.util.spec_from_file_location("_dsh_worker_go_session", path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.session_id("dsh", MODEL, KEY_ENV)
        except Exception:
            return None

    # ---------------------------------------------------------------- locks
    def _lock_path(self, workspace: Path | None = None) -> Path:
        """One mutation lock for the whole repository.

        Keying by workspace allowed a parent checkout and a subdirectory
        workspace to take different locks and become concurrent writers.  Every
        mutating job now contends for this single file.
        """
        return self.config.locks_dir / MUTATION_LOCK_NAME

    def _recorded_worker_alive(self, job_id: str) -> bool:
        """Return True unless every recorded worker is proven gone.

        A missing kernel creation time means ownership cannot be verified; that
        is deliberately treated as alive so the lock is not released under a
        possibly running writer.
        """
        try:
            status, _ = read_json_bounded(self._job_dir(job_id) / "status.json")
        except PluginError:
            return False
        if not isinstance(status, dict):
            return False
        worker_pid = status.get("worker_pid")
        if not worker_pid:
            return False
        worker_ticks = status.get("worker_creation_time")
        if not worker_ticks:
            return True
        return procutil.process_alive(int(worker_pid), int(worker_ticks))

    def _lock_active(self, lock: dict[str, Any]) -> bool:
        """Fail closed: only proven-dead ownership frees a mutation lock.

        Timestamps and age are not ownership evidence.  If the supervisor is
        gone but its recorded worker is still alive, or a recorded PID lacks a
        verifiable creation time, the lock stays active and a second writer is
        refused.
        """
        job_id = lock.get("job_id")
        if not valid_job_id(str(job_id or "")):
            return True
        try:
            status, _ = read_json_bounded(self._job_dir(str(job_id)) / "status.json")
        except PluginError:
            status = None
        if not isinstance(status, dict):
            # No readable status: the job record may still own live processes.
            return True
        supervisor_pid = status.get("supervisor_pid")
        supervisor_ticks = status.get("supervisor_creation_time")
        if supervisor_pid:
            if not supervisor_ticks:
                return True
            if procutil.process_alive(int(supervisor_pid), int(supervisor_ticks)):
                return True
        worker_pid = status.get("worker_pid")
        worker_ticks = status.get("worker_creation_time")
        if worker_pid:
            if not worker_ticks:
                return True
            if procutil.process_alive(int(worker_pid), int(worker_ticks)):
                return True
        # Both recorded processes are absent or proven dead.  Only a final
        # status is positive proof that this job has stopped owning the tree.
        return status.get("phase") not in FINAL_PHASES

    def _acquire_lock(self, workspace: Path, job_id: str) -> Path:
        self.config.locks_dir.mkdir(parents=True, exist_ok=True)
        path = self._lock_path(workspace)
        payload = {
            "job_id": job_id,
            "workspace": str(workspace),
            "repo_root": str(self.config.repo_root),
            "created_at": iso(),
            "supervisor_pid": None,
            "supervisor_creation_time": None,
        }
        for _ in range(3):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                existing, error = read_json_bounded(path, 65_536)
                if not isinstance(existing, dict):
                    raise PluginError(
                        "workspace_lock_unreadable",
                        "the repository mutation lock exists but cannot be validated; "
                        "inspect it before starting another writer",
                        lock_path=str(path),
                        record_error=error,
                        recovery=(
                            "Verify no recorded worker is alive, then remove the corrupt "
                            f"lock file {path} manually or repair it with a valid job_id."
                        ),
                    )
                if self._lock_active(existing):
                    raise PluginError(
                        "workspace_busy",
                        "another mutating dsh worker is active in this repository "
                        "(one writer covers the root and all subdirectories)",
                        existing_job_id=existing.get("job_id"),
                        lock_path=str(path),
                        recovery=(
                            "Use worker_status on existing_job_id. If that job is stale "
                            "or lost, cancel_worker(confirm=true) releases the lock only "
                            "after its recorded worker is proven dead; otherwise wait for "
                            "the active writer. If the job record is missing, verify no "
                            "owned process is alive and remove the lock file manually."
                        ),
                    )
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            try:
                os.write(fd, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            return path
        raise PluginError("workspace_lock_failed", "could not acquire the repository mutation lock")

    def _update_lock(self, workspace: Path, job_id: str, supervisor_pid: int | None, ticks: int | None) -> None:
        path = self._lock_path(workspace)
        existing, _ = read_json_bounded(path, 65_536)
        if not isinstance(existing, dict) or existing.get("job_id") != job_id:
            return
        existing["supervisor_pid"] = supervisor_pid
        existing["supervisor_creation_time"] = ticks
        atomic_write_json(path, existing)

    def _release_lock(self, workspace: Path, job_id: str, force: bool = False) -> bool:
        """Release the repository lock, never while a recorded worker lives.

        ``force`` is only for failures that occur before a supervisor/worker is
        spawned.  It is not a general bypass.
        """
        if not force:
            status, _ = read_json_bounded(self._job_dir(job_id) / "status.json")
            if not isinstance(status, dict):
                # A spawned supervisor may have died before its first status
                # write.  Without ownership evidence, retain the lock.
                return False
            if self._recorded_worker_alive(job_id):
                return False
        path = self._lock_path(workspace)
        existing, _ = read_json_bounded(path, 65_536)
        if isinstance(existing, dict) and existing.get("job_id") == job_id:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return True
        return False

    # ---------------------------------------------------------------- start
    def start_worker(
        self,
        *,
        brief: str | None = None,
        task_file: str | None = None,
        workspace: str = ".",
        permission: str = "read-only",
        heartbeat_interval_seconds: int = 900,
        missed_replies: int = 2,
        max_output_tokens: int | None = None,
        max_result_bytes: int = DEFAULT_RESULT_BYTES,
        hard_timeout_seconds: int | None = None,
        followup_wait_seconds: int = 0,
        controller_lease_seconds: int = 1800,
        refresh_context: bool = True,
    ) -> dict[str, Any]:
        now = self.config.now()
        if is_peak(now):
            raise PluginError(
                "peak_hours",
                "DeepSeek worker starts are refused during peak hours "
                "(Mon-Fri 06:30-09:30 and 11:30-15:30 IST)",
            )
        ws = self._workspace(workspace)
        text, task_relative = self._read_brief(brief, task_file)
        if permission not in PERMISSIONS:
            raise PluginError("permission_invalid", f"permission must be one of {PERMISSIONS}")
        if not isinstance(heartbeat_interval_seconds, int) or not 30 <= heartbeat_interval_seconds <= 86_400:
            raise PluginError("heartbeat_invalid", "heartbeat interval must be 30..86400 seconds")
        if not isinstance(missed_replies, int) or not 2 <= missed_replies <= 10:
            raise PluginError("heartbeat_invalid", "missed replies must be 2..10 (dsh limit)")
        if max_output_tokens is not None and (
            not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS
        ):
            raise PluginError(
                "output_cap_invalid", f"max_output_tokens must be 1..{MAX_OUTPUT_TOKENS}"
            )
        if not isinstance(max_result_bytes, int) or not 256 <= max_result_bytes <= MAX_RESULT_BYTES:
            raise PluginError(
                "result_limit_invalid", f"max_result_bytes must be 256..{MAX_RESULT_BYTES}"
            )
        if hard_timeout_seconds is not None and (
            not isinstance(hard_timeout_seconds, int)
            or not 60 <= hard_timeout_seconds <= 604_800
        ):
            raise PluginError("timeout_invalid", "hard timeout must be 60..604800 seconds")
        if not isinstance(followup_wait_seconds, int) or not 0 <= followup_wait_seconds <= 3600:
            raise PluginError(
                "followup_wait_invalid",
                "followup_wait_seconds must be 0 (disabled) or 1..3600 seconds",
            )
        testing = (self.config.environ or {}).get("DSH_WORKER_TESTING") == "1"
        test_lease = (self.config.environ or {}).get("DSH_WORKER_TEST_LEASE_SECONDS")
        if testing and test_lease:
            try:
                controller_lease_seconds = int(test_lease)
            except ValueError as exc:
                raise PluginError("lease_invalid", "DSH_WORKER_TEST_LEASE_SECONDS must be an integer") from exc
        minimum_lease = 1 if testing else 60
        if not isinstance(controller_lease_seconds, int) or not minimum_lease <= controller_lease_seconds <= 7200:
            raise PluginError(
                "lease_invalid",
                f"controller lease must be {minimum_lease}..7200 seconds",
            )

        capability = self._capability()
        if not capability.heartbeat_supported:
            missing = [
                flag for flag in heartbeat.HEARTBEAT_FLAGS if flag not in capability.flags
            ]
            raise PluginError(
                "heartbeat_unavailable",
                "the dsh launcher does not advertise the required heartbeat flags "
                f"({', '.join(missing)}); refusing to start because the automatic "
                "hard-timeout fallback was removed. Point DSH_WORKER_LAUNCHER at a "
                "heartbeat-capable run_deepseek_harness.py or update the installed "
                "launcher. A hard timeout is only an explicit troubleshooting cutoff, "
                "not a substitute for worker supervision.",
                missing_flags=missing,
                capabilities=capability.as_dict(),
                help_error=capability.help_error,
            )
        if not capability.control_token_supported:
            raise PluginError(
                "control_token_unavailable",
                "the dsh launcher advertises heartbeat flags but not "
                "--control-token-env, so message_worker cannot authenticate follow-ups. "
                "Refusing to start a job that cannot be supervised and steered; update "
                "run_deepseek_harness.py to the control-token-capable revision.",
                capabilities=capability.as_dict(),
                help_error=capability.help_error,
            )
        job_id = new_job_id()
        job_dir = self.config.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        paths = self._job_paths(job_id)
        mutating = permission != "read-only"
        lock_path: Path | None = None
        supervisor_spawned = False
        try:
            if mutating:
                lock_path = self._acquire_lock(ws, job_id)
            atomic_write_text(job_dir / "brief.md", text)
            baseline = gitutil.snapshot(ws) if mutating else {"available": False, "reason": "read_only"}
            atomic_write_json(job_dir / "baseline.json", baseline)

            heartbeat_args, heartbeat_record = heartbeat.heartbeat_launch_args(
                capability, job_dir, heartbeat_interval_seconds, missed_replies
            )
            control_token = secrets.token_hex(32)
            heartbeat_record["control_path"] = paths["control"]
            heartbeat_record["control_token_env"] = heartbeat.CONTROL_TOKEN_ENV
            launcher = self._launcher_command()
            argv = [
                *launcher,
                "--model",
                MODEL,
                "--task-file",
                paths["brief"],
                "--out-file",
                paths["result"],
                "--cwd",
                str(ws),
                "--account",
                ACCOUNT,
                "--permission",
                permission,
                "--allow-paid",
            ]
            if max_output_tokens is not None:
                argv += ["--max-output-tokens", str(max_output_tokens)]
            if not refresh_context:
                argv.append("--no-refresh")
            argv += heartbeat_args
            argv += ["--control-token-env", heartbeat.CONTROL_TOKEN_ENV]
            if followup_wait_seconds:
                argv += ["--followup-wait", str(followup_wait_seconds)]
            if hard_timeout_seconds is not None:
                # Explicit troubleshooting cutoff only; omission means no
                # wall-clock kill at all, while heartbeat supervision remains.
                argv += ["--timeout", str(hard_timeout_seconds)]

            provider_session = self._provider_session()
            warnings: list[str] = []
            owner_id = secrets.token_hex(16)
            if provider_session is None:
                warnings.append("provider_session_unavailable: could not import go_session.py")
            warnings.append(
                "provider_session is the stable OpenCode routing/cache identity; the actual "
                "dsh conversation ID is a different identity and is unknown until the "
                "heartbeat adapter publishes it."
            )
            if not mutating:
                warnings.append(
                    "read-only worker: it does not take the workspace mutation lock, so it "
                    "must not be started alongside a mutating worker in the same checkout"
                )
            job = {
                "schema": 1,
                "job_id": job_id,
                "created_at": iso(now),
                "repo_root": str(self.config.repo_root),
                "plugin_root": str(self.config.plugin_root),
                "workspace": str(ws),
                "task_file": task_relative,
                "permission": permission,
                "model": MODEL,
                "effort": EFFORT,
                "account": ACCOUNT,
                "key_env": KEY_ENV,
                "provider_session": provider_session,
                "provider_session_kind": "opencode_routing_cache",
                "conversation_id": None,
                "controller_lease_owner_id": owner_id,
                "heartbeat": heartbeat_record,
                "launcher": {
                    "command": launcher,
                    "cwd": str(self.config.repo_root),
                    "argv": argv,
                    "capabilities": capability.as_dict(),
                },
                "paths": paths,
                "limits": {
                    "max_output_tokens": max_output_tokens,
                    "max_result_bytes": max_result_bytes,
                    "hard_timeout_seconds": hard_timeout_seconds,
                    "hard_timeout_kind": "explicit_only"
                    if hard_timeout_seconds is not None
                    else "none",
                    "followup_wait_seconds": followup_wait_seconds,
                    "controller_lease_seconds": controller_lease_seconds,
                    "brief_bytes": len(text.encode("utf-8")),
                },
                "warnings": warnings,
            }
            atomic_write_json(job_dir / "job.json", job)
            lease_now = utc_now()
            lease = {
                "schema": LEASE_SCHEMA,
                "job_id": job_id,
                "owner_id": owner_id,
                "owner_pid": os.getpid(),
                "created_at": iso(lease_now),
                "renewed_at": iso(lease_now),
                "deadline": iso(lease_now + timedelta(seconds=controller_lease_seconds)),
                "lease_seconds": controller_lease_seconds,
                "renewals": 0,
            }
            atomic_write_json(job_dir / LEASE_FILE, lease)
            self._lease_owners[job_id] = owner_id
            initial_status = {
                "schema": 1,
                "job_id": job_id,
                "phase": "starting",
                "started_at": iso(now),
                "updated_at": iso(now),
                "supervisor_pid": None,
                "supervisor_creation_time": None,
                "worker_pid": None,
                "worker_creation_time": None,
                "worker_activity_at": None,
                "exit_code": None,
                "outcome": None,
                "error": None,
                "artifacts": None,
                "heartbeat": heartbeat_record,
                "controller_lease": read_lease(job_dir / LEASE_FILE)[0],
                "warnings": [],
            }
            atomic_write_json(job_dir / "status.json", initial_status)

            supervisor_pid = self._spawn_supervisor(job_dir, control_token)
            supervisor_spawned = True
            self._control_tokens[job_id] = control_token
            ticks = procutil.process_creation_time(supervisor_pid)
            if mutating:
                self._update_lock(ws, job_id, supervisor_pid, ticks)
            status = self._wait_for_start(job_dir, supervisor_pid)
            return {
                "ok": True,
                "job_id": job_id,
                "phase": status.get("phase", "starting"),
                "workspace": str(ws),
                "permission": permission,
                "model": MODEL,
                "effort": EFFORT,
                "account": ACCOUNT,
                "provider_session": provider_session,
                "conversation_id": status.get("conversation_id"),
                "status_path": paths["status"],
                "result_path": paths["result"],
                "launcher_log_path": paths["launcher_log"],
                "supervisor_log_path": paths["supervisor_log"],
                "heartbeat": status.get("heartbeat") or heartbeat_record,
                "warnings": warnings + list(status.get("warnings") or []),
                "server_shutdown": SERVER_SHUTDOWN_SEMANTICS,
            }
        except Exception:
            if lock_path is not None:
                # Never release under a recorded worker.  Before the supervisor
                # exists there is no worker, so the half-created job may release
                # safely; afterwards cancellation/ownership checks decide.
                self._release_lock(ws, job_id, force=not supervisor_spawned)
            self._control_tokens.pop(job_id, None)
            self._lease_owners.pop(job_id, None)
            if not (job_dir / "job.json").exists():
                try:
                    atomic_write_json(
                        job_dir / "job.json",
                        {
                            "schema": 1,
                            "job_id": job_id,
                            "created_at": iso(now),
                            "workspace": str(ws),
                            "start_failed": True,
                        },
                    )
                except OSError:
                    pass
            raise

    def _spawn_supervisor(self, job_dir: Path, control_token: str | None = None) -> int:
        supervisor = Path(__file__).resolve().parent / "supervisor.py"
        env = self._launcher_env()
        env["DSH_WORKER_JOB_DIR"] = str(job_dir)
        if control_token is not None:
            # Environment only: never argv, never a manifest/config/status file.
            env[heartbeat.CONTROL_TOKEN_ENV] = control_token
        log_path = job_dir / "supervisor.log"
        flags = procutil.hidden_creationflags()
        kwargs: dict[str, Any] = {}
        if os.name != "nt":
            kwargs["start_new_session"] = True
        with open(log_path, "ab", buffering=0) as log:
            try:
                process = subprocess.Popen(
                    [sys.executable, str(supervisor), str(job_dir)],
                    cwd=str(self.config.repo_root),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    creationflags=flags,
                    close_fds=True,
                    **kwargs,
                )
            except OSError as exc:
                raise PluginError("supervisor_spawn_failed", f"could not start supervisor: {exc}") from exc
        self._children = [child for child in self._children if child.poll() is None]
        self._children.append(process)
        return int(process.pid)

    def _wait_for_start(self, job_dir: Path, supervisor_pid: int) -> dict[str, Any]:
        status_path = job_dir / "status.json"
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            status, _ = read_json_bounded(status_path)
            if isinstance(status, dict) and status.get("supervisor_pid"):
                return status
            if not procutil.process_alive(supervisor_pid):
                break
            time.sleep(0.05)
        status, _ = read_json_bounded(status_path)
        if not isinstance(status, dict):
            status = {"phase": "starting", "warnings": []}
        if not procutil.process_alive(supervisor_pid, status.get("supervisor_creation_time")):
            if status.get("phase") not in FINAL_PHASES:
                tail, _, _ = read_text_bounded(job_dir / "supervisor.log", 4096)
                raise PluginError(
                    "supervisor_failed",
                    "the supervisor exited before publishing status",
                    supervisor_log_tail=tail,
                )
        return status

    def _reap_child(self, pid: int | None, timeout: float = 0.0) -> None:
        for child in list(self._children):
            if pid is not None and int(child.pid) != int(pid):
                continue
            if child.poll() is not None:
                continue
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass

    # --------------------------------------------------------------- status
    def _load_job(self, job_id: str) -> tuple[dict[str, Any], Path]:
        job_dir = self._job_dir(job_id)
        job, error = read_json_bounded(job_dir / "job.json")
        if not isinstance(job, dict):
            raise PluginError(
                "job_not_found",
                "no persisted job record for this job_id",
                job_id=job_id,
                record_error=error,
            )
        return job, job_dir

    def _read_status(self, job_dir: Path) -> dict[str, Any]:
        status, error = read_json_bounded(job_dir / "status.json")
        if not isinstance(status, dict):
            return {
                "phase": "starting",
                "warnings": [f"status record unreadable: {error}"],
            }
        return status

    def _process_view(self, status: dict[str, Any], heartbeat_live: dict[str, Any] | None) -> dict[str, Any]:
        supervisor_pid = status.get("supervisor_pid")
        supervisor_ticks = status.get("supervisor_creation_time")
        worker_pid = status.get("worker_pid")
        worker_ticks = status.get("worker_creation_time")
        supervisor_alive = bool(
            supervisor_pid
            and procutil.process_alive(
                int(supervisor_pid), int(supervisor_ticks) if supervisor_ticks else None
            )
        )
        worker_alive = bool(
            worker_pid
            and procutil.process_alive(int(worker_pid), int(worker_ticks) if worker_ticks else None)
        )
        return {
            "supervisor_pid": supervisor_pid,
            "supervisor_creation_time": supervisor_ticks,
            "supervisor_alive": supervisor_alive,
            "worker_pid": worker_pid,
            "worker_creation_time": worker_ticks,
            "worker_alive": worker_alive,
            "pid_alone_is_not_progress": True,
        }

    def _last_activity(
        self,
        job_dir: Path,
        status: dict[str, Any],
        heartbeat_live: dict[str, Any] | None,
    ) -> datetime | None:
        """Return committed worker activity, never file/status write times.

        ``heartbeat.last_activity_at`` in ``dsh-heartbeat-status/1`` is updated
        only by real model/tool events.  Supervisor polls, status rewrites, log
        growth, and heartbeat.json mtimes are supervision health, not worker
        progress.  ``started_at`` is only the initial anchor for a job that has
        not published a heartbeat yet.
        """
        candidates: list[datetime] = []
        parsed = parse_iso(status.get("worker_activity_at"))
        if parsed:
            candidates.append(parsed)
        if isinstance(heartbeat_live, dict):
            parsed = parse_iso(
                heartbeat_live.get("last_worker_activity_at")
                or heartbeat_live.get("last_activity_at")
            )
            if parsed:
                candidates.append(parsed)
        if not candidates:
            parsed = parse_iso(status.get("started_at"))
            if parsed:
                candidates.append(parsed)
        return max(candidates) if candidates else None

    def get_status(self, job_id: str) -> dict[str, Any]:
        job, job_dir = self._load_job(job_id)
        status = self._read_status(job_dir)
        heartbeat_live, heartbeat_error = heartbeat.read_heartbeat(job_dir)
        heartbeat_record = dict(job.get("heartbeat") or status.get("heartbeat") or {})
        token_available = job_id in self._control_tokens
        descriptor_available = heartbeat.control_available(
            Path(self._job_paths(job_id)["control"]), heartbeat_live
        )
        heartbeat_record.update(
            {
                "present": heartbeat_live is not None,
                "read_error": heartbeat_error,
                "adapter": heartbeat_live,
                # A bound descriptor is not enough after an MCP restart: the
                # per-job token is memory-only, so control is unavailable unless
                # this server process still holds it.
                "control_available": descriptor_available and token_available,
                "control_descriptor_available": descriptor_available,
                "control_token_available": token_available,
                "control_unavailable_reason": (
                    None
                    if descriptor_available and token_available
                    else "control_token_not_in_this_mcp_server"
                    if descriptor_available
                    else "control_descriptor_unavailable"
                ),
            }
        )
        if isinstance(heartbeat_live, dict):
            for key in (
                "run_id",
                "state",
                "interval_seconds",
                "response_window_seconds",
                "unanswered_pings",
                "misses_allowed",
                "conversation_id",
            ):
                if heartbeat_live.get(key) is not None:
                    heartbeat_record[key] = heartbeat_live[key]
        process = self._process_view(status, heartbeat_live)
        phase = str(status.get("phase") or "starting")
        warnings = list(job.get("warnings") or []) + list(status.get("warnings") or [])
        if phase in ACTIVE_PHASES:
            if not process["supervisor_alive"]:
                if process["worker_alive"]:
                    phase = "orphaned"
                    warnings.append(
                        "supervisor is gone but the worker process is still alive; "
                        "ownership is uncertain, inspect before cancelling"
                    )
                else:
                    phase = "lost"
                    warnings.append(
                        "supervisor and worker are both gone and no final status was written"
                    )
        if phase == "orphaned":
            final = False
            running = True
        else:
            final = phase in FINAL_PHASES or phase in {"orphaned"} and not process["supervisor_alive"]
            running = phase in ACTIVE_PHASES and not final
        last_activity = self._last_activity(job_dir, status, heartbeat_live)
        awaiting_input = _awaiting_input_valid(heartbeat_live)
        interval = int(heartbeat_record.get("interval_seconds") or 900)
        window = int(heartbeat_record.get("response_window_seconds") or 900)
        misses = int(heartbeat_record.get("missed_replies_allowed") or 2)
        stale_after = self.config.stale_after_seconds or max(
            interval + window * max(1, misses), 300
        )
        stale = False
        if running and last_activity is not None and not awaiting_input:
            stale = (utc_now() - last_activity).total_seconds() > stale_after
            if stale:
                warnings.append(
                    f"no committed worker activity for more than {stale_after}s; "
                    "heartbeat/status writes and process liveness alone are not progress"
                )
        if not process["supervisor_alive"] and not process["worker_alive"] and phase not in FINAL_PHASES:
            phase = "lost"
            final = True
            running = False
        result_path = job_dir / "result.md"
        try:
            result_bytes = result_path.stat().st_size
        except OSError:
            result_bytes = 0
        conversation_id = (
            (heartbeat_live or {}).get("conversation_id")
            or (heartbeat_live or {}).get("dsh_conversation_id")
            or job.get("conversation_id")
        )
        if final:
            # Give a just-finished supervisor a bounded moment to exit so its
            # Popen handle does not outlive the test/session as a live child.
            self._reap_child(status.get("supervisor_pid"), timeout=1.0)
            self._control_tokens.pop(job_id, None)
            self._lease_owners.pop(job_id, None)
        controller_lease, lease_error = read_lease(
            job_dir / LEASE_FILE,
            expected_job_id=job_id,
            expected_owner_id=job.get("controller_lease_owner_id"),
            max_seconds=7200,
        )
        if controller_lease is not None and controller_lease.get("expired") and running:
            warnings.append(
                "controller lease is past its absolute deadline; the supervisor "
                "should terminate the owned process tree (controller_lease_expired)"
            )
        return {
            "ok": True,
            "job_id": job_id,
            "phase": phase,
            "running": running,
            "final": final,
            "failed": phase in {"failed", "lost"},
            "stale": stale,
            "started_at": status.get("started_at") or job.get("created_at"),
            "updated_at": status.get("updated_at"),
            "finished_at": status.get("finished_at"),
            "last_activity_at": iso(last_activity) if last_activity else None,
            "stale_after_seconds": stale_after,
            "awaiting_input": awaiting_input,
            "awaiting_since": (heartbeat_live or {}).get("awaiting_since") if awaiting_input else None,
            "awaiting_deadline": (heartbeat_live or {}).get("awaiting_deadline") if awaiting_input else None,
            "process": process,
            "exit_code": status.get("exit_code"),
            "outcome": status.get("outcome"),
            "error": status.get("error"),
            "workspace": job.get("workspace"),
            "permission": job.get("permission"),
            "model": job.get("model"),
            "effort": job.get("effort"),
            "account": job.get("account"),
            "session": {
                "provider_session": job.get("provider_session"),
                "provider_session_kind": "opencode_routing_cache",
                "conversation_id": conversation_id,
                "conversation_id_known": conversation_id is not None,
                "distinct_identities": True,
            },
            "heartbeat": heartbeat_record,
            "controller_lease": controller_lease,
            "controller_lease_error": lease_error,
            "controller_lease_expired": bool(controller_lease and controller_lease.get("expired")),
            "result_ready": result_bytes > 0,
            "result_bytes": result_bytes,
            "result_kind": status.get("result_kind") or ("final" if final else "live"),
            "interim": bool(status.get("interim_result")),
            "partial": bool(status.get("partial")),
            "paths": self._job_paths(job_id),
            "limits": job.get("limits"),
            "warnings": warnings,
            "server_shutdown": SERVER_SHUTDOWN_SEMANTICS,
        }

    # --------------------------------------------------------------- result
    def worker_result(self, job_id: str, max_bytes: int | None = None) -> dict[str, Any]:
        job, job_dir = self._load_job(job_id)
        if max_bytes is None:
            max_bytes = int((job.get("limits") or {}).get("max_result_bytes") or DEFAULT_RESULT_BYTES)
        if not isinstance(max_bytes, int) or not 256 <= max_bytes <= MAX_RESULT_BYTES:
            raise PluginError(
                "result_limit_invalid", f"max_bytes must be 256..{MAX_RESULT_BYTES}"
            )
        status = self.get_status(job_id)
        result_path = job_dir / "result.md"
        text, truncated, total = read_text_bounded(result_path, max_bytes)
        warnings = list(status.get("warnings") or [])
        if not result_path.exists():
            warnings.append("result file does not exist yet")
        artifacts = status.get("artifacts")
        if artifacts is None:
            status_raw = self._read_status(job_dir)
            artifacts = status_raw.get("artifacts")
        return {
            "ok": True,
            "job_id": job_id,
            "phase": status["phase"],
            "final": status["final"],
            "interim": status.get("interim", False),
            "partial": status.get("partial", False),
            "result_kind": status.get("result_kind"),
            "awaiting_input": status.get("awaiting_input", False),
            "outcome": status.get("outcome"),
            "exit_code": status.get("exit_code"),
            "content": text,
            "truncated": truncated,
            "result_bytes": total,
            "max_bytes": max_bytes,
            "paths": status["paths"],
            "artifacts": artifacts,
            "heartbeat": status["heartbeat"],
            "limits": status.get("limits"),
            "error": status.get("error"),
            "warnings": warnings,
        }

    # -------------------------------------------------------------- message
    def message_worker(
        self,
        job_id: str,
        message: str,
        kind: str = "status",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip():
            raise PluginError("message_invalid", "message must be non-empty text")
        length_error = heartbeat.message_length_error(message)
        if length_error is not None:
            raise PluginError(
                "message_too_long",
                length_error,
                characters=heartbeat.adapter_message_length(message),
                limit=heartbeat.MAX_ADAPTER_MESSAGE_CHARS,
            )
        if len(message.encode("utf-8", errors="replace")) > MAX_MESSAGE_BYTES:
            raise PluginError("message_too_large", "message exceeds 32 KiB")
        if kind not in ("followup", "status"):
            raise PluginError("message_invalid", "kind must be followup or status")
        status = self.get_status(job_id)
        if not status["running"]:
            raise PluginError(
                "job_not_running",
                "the worker is not running; start a new job instead of messaging a finished one",
                phase=status["phase"],
            )
        job, job_dir = self._load_job(job_id)
        heartbeat_live, _ = heartbeat.read_heartbeat(job_dir)
        response = heartbeat.send_nudge(
            Path(status["paths"]["control"]),
            heartbeat_live,
            job_id,
            message,
            kind,
            conversation_id,
            self._control_tokens.get(job_id),
        )
        response["job_id"] = job_id
        response["phase"] = status["phase"]
        response["conversation_id_known"] = bool(
            response.get("conversation_id")
            or conversation_id
            or (heartbeat_live or {}).get("conversation_id")
            or job.get("conversation_id")
        )
        return response

    # --------------------------------------------------------------- lease
    def renew_worker_lease(
        self,
        job_id: str,
        extend_seconds: int = 1800,
    ) -> dict[str, Any]:
        """Explicitly renew the controller lease; never called by status reads.

        Only the MCP server process that launched this job holds the in-memory
        owner id.  A restarted server, a malformed/expired lease, or a different
        job cannot extend the deadline.  Each call may extend at most the normal
        30-minute window, so indefinite work requires repeated human/controller
        review rather than a background loop.
        """
        testing = (self.config.environ or {}).get("DSH_WORKER_TESTING") == "1"
        minimum = 1 if testing else 60
        maximum = 3600 if testing else 1800
        if not isinstance(extend_seconds, int) or not minimum <= extend_seconds <= maximum:
            raise PluginError(
                "lease_extension_invalid",
                f"extend_seconds must be {minimum}..{maximum}",
            )
        job, job_dir = self._load_job(job_id)
        status = self.get_status(job_id)
        if not status["running"] or status["final"]:
            raise PluginError(
                "job_not_running",
                "the worker is not running; a lease cannot resurrect a finished job",
                phase=status["phase"],
            )
        owner = self._lease_owners.get(job_id)
        if not owner:
            raise PluginError(
                "controller_unavailable",
                "this MCP server does not own the job's controller lease (restart or "
                "wrong process); it cannot extend the persisted deadline",
            )
        lease_path = job_dir / LEASE_FILE
        lease, error = read_lease(
            lease_path,
            expected_job_id=job_id,
            expected_owner_id=owner,
            max_seconds=maximum,
        )
        if lease is None:
            raise PluginError(
                "lease_invalid",
                "the persisted controller lease is missing or malformed; refusing to extend",
                detail=error,
            )
        if lease.get("expired"):
            raise PluginError(
                "controller_lease_expired",
                "the controller lease already expired; the supervisor must stop this job",
                deadline=lease.get("deadline"),
            )
        now = utc_now()
        updated = dict(lease)
        updated.pop("expired", None)
        updated.pop("remaining_seconds", None)
        updated["renewed_at"] = iso(now)
        updated["deadline"] = iso(now + timedelta(seconds=extend_seconds))
        updated["lease_seconds"] = extend_seconds
        updated["renewals"] = int(lease.get("renewals") or 0) + 1
        atomic_write_json(lease_path, updated)
        current, _ = read_lease(
            lease_path,
            expected_job_id=job_id,
            expected_owner_id=owner,
            max_seconds=maximum,
        )
        return {
            "ok": True,
            "job_id": job_id,
            "controller_lease": current,
            "renewed": True,
            "automatic_renewal": False,
            "note": (
                "Renewal is explicit controller action only. Worker activity, "
                "status/result/list reads and model calls never renew this lease."
            ),
        }

    # --------------------------------------------------------------- cancel
    def cancel_worker(self, job_id: str, confirm: bool = False, reason: str = "cancelled by Codex") -> dict[str, Any]:
        if confirm is not True:
            return {
                "ok": False,
                "error": {
                    "code": "confirmation_required",
                    "message": "cancel_worker is destructive; pass confirm=true to stop this job",
                },
                "destructive_hint": True,
                "job_id": job_id,
            }
        job, job_dir = self._load_job(job_id)
        status = self.get_status(job_id)
        if status["final"]:
            lock_released = self._release_lock(Path(job["workspace"]), job_id)
            self._control_tokens.pop(job_id, None)
            response = {
                "ok": True,
                "job_id": job_id,
                "phase": status["phase"],
                "already_final": True,
                "cancelled": status["phase"] == "cancelled",
                "lock_released": lock_released,
            }
            if not lock_released and self._recorded_worker_alive(job_id):
                response["warning"] = (
                    "the job is final but its recorded worker is still alive; the "
                    "repository mutation lock was retained deliberately. Inspect the "
                    "process before starting another writer."
                )
            return response
        atomic_write_json(
            job_dir / "cancel.request",
            {"requested_at": iso(), "reason": str(reason)[:500], "job_id": job_id},
        )
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            current = self._read_status(job_dir)
            if current.get("phase") in FINAL_PHASES:
                lock_released = self._release_lock(Path(job["workspace"]), job_id)
                self._control_tokens.pop(job_id, None)
                return {
                    "ok": True,
                    "job_id": job_id,
                    "phase": current.get("phase"),
                    "cancelled": current.get("phase") == "cancelled",
                    "forced": False,
                    "forced_kill": False,
                    "lock_released": lock_released,
                }
            time.sleep(0.2)
        process = status["process"]
        killed_supervisor = False
        killed_worker = False
        if process.get("supervisor_pid") and process.get("supervisor_alive"):
            supervisor_ticks = process.get("supervisor_creation_time")
            if not supervisor_ticks and os.name == "nt":
                return {
                    "ok": False,
                    "error": {
                        "code": "ownership_unverified",
                        "message": "recorded supervisor has no kernel creation time; refusing to kill",
                    },
                }
            if not procutil.process_alive(
                int(process["supervisor_pid"]),
                int(supervisor_ticks) if supervisor_ticks else None,
            ):
                return {
                    "ok": False,
                    "error": {
                        "code": "ownership_mismatch",
                        "message": "recorded supervisor PID no longer matches its creation time",
                    },
                }
            killed_supervisor = procutil.kill_tree(int(process["supervisor_pid"]))
        if process.get("worker_pid") and process.get("worker_alive"):
            worker_ticks = process.get("worker_creation_time")
            if not worker_ticks and os.name == "nt":
                return {
                    "ok": False,
                    "error": {
                        "code": "ownership_unverified",
                        "message": "recorded worker has no kernel creation time; refusing to kill",
                    },
                }
            if worker_ticks and procutil.process_alive(
                int(process["worker_pid"]), int(worker_ticks)
            ):
                killed_worker = procutil.kill_tree(int(process["worker_pid"]))
        time.sleep(1.0)
        current = self._read_status(job_dir)
        supervisor_gone = not (
            process.get("supervisor_pid")
            and procutil.process_alive(
                int(process["supervisor_pid"]),
                int(process["supervisor_creation_time"])
                if process.get("supervisor_creation_time")
                else None,
            )
        )
        worker_still_alive = bool(
            process.get("worker_pid")
            and process.get("worker_creation_time")
            and procutil.process_alive(
                int(process["worker_pid"]), int(process["worker_creation_time"])
            )
        )
        if (
            current.get("phase") not in FINAL_PHASES
            and supervisor_gone
            and not worker_still_alive
        ):
            current = {
                **current,
                "phase": "cancelled",
                "outcome": "cancelled",
                "exit_code": None,
                "error": "supervisor did not finalize; the owned process tree was killed",
                "finished_at": iso(),
                "updated_at": iso(),
            }
            atomic_write_json(job_dir / "status.json", current)
        lock_released = self._release_lock(Path(job["workspace"]), job_id)
        self._control_tokens.pop(job_id, None)
        if current.get("phase") not in FINAL_PHASES:
            return {
                "ok": False,
                "error": {
                    "code": "cancel_failed",
                    "message": "the owned process tree did not stop within the cancellation window",
                },
                "job_id": job_id,
                "phase": current.get("phase"),
                "forced_kill": killed_supervisor or killed_worker,
                "lock_released": lock_released,
            }
        return {
            "ok": True,
            "job_id": job_id,
            "phase": current.get("phase"),
            "cancelled": True,
            "forced": True,
            "forced_kill": killed_supervisor or killed_worker,
            "killed_supervisor": killed_supervisor,
            "killed_worker": killed_worker,
            "lock_released": lock_released,
        }

    # ----------------------------------------------------------------- list
    def list_workers(self, workspace: str | None = None, limit: int = 20) -> dict[str, Any]:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise PluginError("limit_invalid", "limit must be 1..100")
        wanted: str | None = None
        if workspace:
            wanted = os.path.normcase(str(self._workspace(workspace)))
        jobs: list[dict[str, Any]] = []
        try:
            entries = sorted(self.config.jobs_dir.iterdir(), key=lambda p: p.name, reverse=True)
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_dir() or not valid_job_id(entry.name):
                continue
            try:
                job = self.get_status(entry.name)
            except PluginError:
                continue
            if wanted and os.path.normcase(str(Path(job["workspace"]).resolve())) != wanted:
                continue
            jobs.append(
                {
                    "job_id": job["job_id"],
                    "phase": job["phase"],
                    "running": job["running"],
                    "stale": job["stale"],
                    "workspace": job["workspace"],
                    "permission": job["permission"],
                    "started_at": job["started_at"],
                    "updated_at": job["updated_at"],
                    "result_ready": job["result_ready"],
                    "result_path": job["paths"]["result"],
                    "status_path": job["paths"]["status"],
                }
            )
            if len(jobs) >= limit:
                break
        return {"ok": True, "jobs": jobs, "count": len(jobs), "limit": limit}
