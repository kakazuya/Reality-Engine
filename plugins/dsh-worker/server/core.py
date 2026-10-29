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
import re
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import gitutil
import heartbeat
import jobs
import procutil
import progress
from context_pack import attach_brief as attach_context_pack, lint_brief as lint_worker_brief
from store import (
    JOB_LOCK_NAME,
    LEASE_FILE,
    LEASE_SCHEMA,
    MUTATION_LOCK_NAME,
    RESOURCE_GUARD_NAME,
    RESOURCE_LOCK_DIR,
    STEERING_FILE,
    TOKEN_FILE,
    append_jsonl_locked,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_json_locked,
    atomic_write_text,
    dpapi_protect,
    dpapi_unprotect,
    exclusive_lock,
    iso,
    new_job_id,
    parse_iso,
    read_bytes_bounded,
    read_json_bounded,
    read_lease,
    read_text_bounded,
    read_text_bounded_tail,
    resource_lock_path,
    resource_reservation_path,
    try_lock_file,
    utc_now,
    valid_job_id,
    workspace_lock_name,
)

SERVER_VERSION = "0.4.0"
SERVER_STARTED_AT = datetime.now(timezone.utc)
MODEL = "deepseek-v4.1-flash"
EFFORT = "max"
ACCOUNT = "2"
KEY_ENV = "OPENCODE_GO_API_KEY_2"
MODEL_LAUNCHER_MODULE = "reality_engine.scripts.run_deepseek_harness"
PERMISSIONS = ("read-only", "workspace-write", "danger-full-access")
# Additional write authority on top of the dsh sandbox mode.  dsh 0.2.1 has one
# writable root per session (the workspace cwd) and no extra-roots config, so
# "data" and "full" both run the dsh danger-full-access mode; the difference is
# that "data" is scoped by instructions + per-DB locks and "full" needs its own
# confirmation.  Recorded per job so status/list/progress show the real scope.
WRITE_SCOPES = ("workspace", "data", "full")
D_REALITY_ENGINE = "D:\\RealityEngine"
MAX_WRITE_DBS = 20
MAX_APPROVED_BY_CHARS = 200
FINAL_PHASES = frozenset({"finished", "failed", "cancelled", "lost"})
ACTIVE_PHASES = frozenset({"starting", "running", "cancelling"})
IST = timezone(timedelta(hours=5, minutes=30))
MAX_BRIEF_BYTES = 262_144
MAX_MESSAGE_BYTES = 32_768
MAX_RESULT_BYTES = 1_048_576
DEFAULT_RESULT_BYTES = 65_536
PEAK_START_MARGIN_SECONDS = 120
MAX_OUTPUT_TOKENS = 200_000
MAX_SESSION_LABEL = 120
MAX_STEERING_TEXT = 200
SESSION_LABEL_ENV = "DSH_SESSION_LABEL"
WORKTREES_ROOT_ENV = "DSH_WORKTREES_ROOT"
JOBS_FILE_ENV = "DSH_WORKER_JOBS_FILE"
REALITY_DATA_ROOT_ENV = "REALITY_DATA_ROOT"
MERGE_LOCK_NAME = "merge-queue.lock"
MAX_TEST_CMD_CHARS = 4000
MAX_JOB_LOG_LINES = 2000
MAX_JOB_LOG_BYTES = 262_144
JOBS_CHECK_DEADLINE_SECONDS = 12.0
# The one-line worker preamble for worktree jobs: gitignored data (databases,
# indexes) lives only in the main checkout, so a worktree worker must read it
# there by absolute path and never write to it.
WORKTREE_PREAMBLE = (
    "Note: gitignored data (databases, indexes) is read from REALITY_DATA_ROOT "
    "by absolute path and must be treated as read-only."
)
# Appended to every worker brief.  It is a standing instruction, never a
# question: the worker must not answer it or stop, only append a progress line.
PROGRESS_NOTES_INSTRUCTION = (
    "Standing progress instruction: every ~20 minutes of work, or at each "
    "milestone, append one line to PROGRESS_NOTES.md in your job directory "
    "(its absolute path is in the DSH_WORKER_PROGRESS_NOTES environment "
    "variable): what's done, what's next, blockers. Do not stop or wait after "
    "writing it."
)
# Appended to every worker brief (Shivam, 2026-10-30: all dsh workers use
# code-intel).  The headless dsh profile loads code-intel as an MCP server;
# run_deepseek_harness points it at the worker's own workspace.
CODE_INTEL_INSTRUCTION = (
    "Standing code-navigation instruction: you have code-intel tools "
    "(mcp__code-intel__definition, __references, __callers, __symbols, "
    "__module_map, __hover, __diagnostics), indexed on YOUR workspace and "
    "fresh against on-disk edits. Use them before grep or whole-file reads: "
    "definition/references for where a symbol (or a table/column name) is "
    "defined and used, symbols(file=...) for a module outline instead of "
    "reading it whole, module_map for a directory, diagnostics on every file "
    "you changed before reporting done. If the MCP tools are unavailable, the "
    "same commands run as `python plugins/code-intel/ci.py <cmd>` (JSON). In "
    "your final report state how many code-intel calls you made and your "
    "tool-call count before the first edit."
)
DEFAULT_PROGRESS_INTERVAL_SECONDS = 1200
MAX_PROGRESS_INTERVAL_SECONDS = 86_400
# The supervisor's own status ping must never read as the end of the task.
STATUS_CHECK_PREFIX = (
    "Status check — answer in one line, then continue your task; "
    "this is not the end of your task."
)
SERVER_SHUTDOWN_SEMANTICS = (
    "The supervisor is spawned outside the MCP host's job object when Windows "
    "allows it (survives_server_exit=true), so closing or restarting this MCP "
    "server does not stop a running worker. The worker stays inside the "
    "supervisor's own KILL_ON_JOB_CLOSE job object, so if the supervisor dies "
    "the worker dies too. The controller lease deadline remains the hard upper "
    "bound: a restarted server sees the job via worker_status/list_workers and "
    "must call claim_worker or renew_worker_lease(adopt=true) to own it. The "
    "per-job control token is persisted DPAPI-encrypted (CurrentUser), so any "
    "dsh-worker MCP server of this Windows user can message/cancel the job; "
    "the plaintext token is never returned or logged."
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


def _as_pid(value: Any) -> int | None:
    """Coerce a persisted PID/creation-time field; ``None`` when unusable.

    Hand-edited or corrupt records can carry strings, floats or booleans.  A
    bare ``int()`` raised ValueError and turned every status/list call into an
    internal error, so callers decide fail-closed policy from ``None`` instead.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _num(value: Any) -> Any:
    """Round a float-ish heartbeat number so ``_as_pid`` accepts ``900.0``."""
    if isinstance(value, float):
        return round(value)
    return value


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
    session_label: str
    worktrees_root: Path
    data_root: Path
    jobs_file: Path
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


def session_label(environ: dict[str, str] | None = None) -> str:
    """Stable identity of this MCP server process.

    ``DSH_SESSION_LABEL`` wins (tests and multi-session demos use it); otherwise
    hostname + pid + process start time.  It is recorded, never authenticated.
    """
    env = os.environ if environ is None else environ
    label = str(env.get(SESSION_LABEL_ENV) or "").strip()
    if not label:
        label = (
            f"{socket.gethostname()}-{os.getpid()}-"
            f"{SERVER_STARTED_AT.strftime('%Y%m%dT%H%M%SZ')}"
        )
    return label[:MAX_SESSION_LABEL]


def _first_line(text: str, limit: int = 200) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return "dsh worker"


def _normalize_writes(writes: Any) -> list[str]:
    """Validate the ``writes`` DB list and return basenames without ``db:``.

    Each entry names one SQLite file (with or without the ``db:`` prefix) that
    the brief is approved to write.  The supervisor takes the matching
    ``db:<file>`` resource lock for the job's lifetime, so two data writers
    never share a DB.
    """
    if writes is None:
        return []
    if not isinstance(writes, list) or len(writes) > MAX_WRITE_DBS:
        raise PluginError(
            "writes_invalid", f"writes must be a list of at most {MAX_WRITE_DBS} DB file names"
        )
    names: list[str] = []
    for value in writes:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise PluginError("writes_invalid", "every writes entry must be a non-empty string")
        name = value.strip()
        if name.startswith("db:"):
            name = name[3:]
        if (
            not name.endswith(".db")
            or Path(name).name != name
            or len(name) > 120
            or "/" in name
            or "\\" in name
        ):
            raise PluginError(
                "writes_invalid",
                f"writes entry {value!r} must be a bare SQLite file name ending in .db",
            )
        if name not in names:
            names.append(name)
    return names


def _progress_interval(value: Any) -> int:
    """0 disables supervisor progress digests; otherwise 1..86400 seconds."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_PROGRESS_INTERVAL_SECONDS
    ):
        raise PluginError(
            "progress_interval_invalid",
            "progress_interval_seconds must be 0 (off) or "
            f"1..{MAX_PROGRESS_INTERVAL_SECONDS} seconds",
        )
    return value


_SINCE_RE = re.compile(r"^(\d+)([smh])$")


def _since_datetime(value: str | None, now: datetime | None = None) -> datetime | None:
    """Parse ``since``: an ISO-8601 timestamp or a short duration (30m, 2h)."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PluginError("since_invalid", "since must be an ISO-8601 timestamp or 30m/2h")
    text = value.strip()
    parsed = parse_iso(text)
    if parsed is not None:
        return parsed
    match = _SINCE_RE.fullmatch(text)
    if match is not None:
        seconds = int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2)]
        return (now or utc_now()) - timedelta(seconds=seconds)
    raise PluginError(
        "since_invalid", "since must be an ISO-8601 timestamp or a duration like 30m or 2h"
    )


def load_config(environ: dict[str, str] | None = None) -> PluginConfig:
    env = dict(os.environ if environ is None else environ)
    plugin_root = Path(__file__).resolve().parents[1]
    raw_repo = env.get("DSH_WORKER_REPO_ROOT")
    if raw_repo:
        expanded = Path(raw_repo).expanduser()
        if not expanded.is_absolute():
            # A relative root resolves against whatever cwd the MCP host used,
            # so the same config breaks when the client launches from a
            # different directory.  Require an absolute path instead.
            raise PluginError(
                "repo_root_relative",
                "DSH_WORKER_REPO_ROOT must be an absolute path (it was relative, so it "
                "would depend on the MCP host's working directory)",
            )
        repo_root = expanded.resolve()
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
    raw_worktrees = env.get(WORKTREES_ROOT_ENV)
    try:
        worktrees_root = (
            Path(raw_worktrees).expanduser().resolve()
            if raw_worktrees
            else (repo_root.parent / "IDM-worktrees").resolve()
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginError(
            "worktrees_root_invalid", f"DSH_WORKTREES_ROOT cannot be resolved: {exc}"
        ) from exc
    raw_data_root = env.get(REALITY_DATA_ROOT_ENV)
    try:
        data_root = (
            Path(raw_data_root).expanduser().resolve()
            if raw_data_root
            else (repo_root / "reality_engine" / "data").resolve()
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginError(
            "data_root_invalid", f"REALITY_DATA_ROOT cannot be resolved: {exc}"
        ) from exc
    raw_jobs_file = env.get(JOBS_FILE_ENV)
    try:
        jobs_file = (
            Path(raw_jobs_file).expanduser().resolve()
            if raw_jobs_file
            else (plugin_root / "jobs.yaml").resolve()
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PluginError(
            "jobs_file_invalid", f"{JOBS_FILE_ENV} cannot be resolved: {exc}"
        ) from exc
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
        session_label=session_label(env),
        worktrees_root=worktrees_root,
        data_root=data_root,
        jobs_file=jobs_file,
        fake_now=fake_now,
        stale_after_seconds=stale_override,
        environ=env,
    )


class Manager:
    def __init__(self, config: PluginConfig) -> None:
        self.config = config
        self._capabilities: heartbeat.LauncherCapabilities | None = None
        self._children: list[subprocess.Popen[bytes]] = []
        # Plaintext control tokens are never written to disk.  The encrypted
        # copy in the job dir is the source of truth; this dict is only a
        # process-local decryption cache so any dsh-worker server of this
        # Windows user can message a job it did not launch.
        self._control_tokens: dict[str, str] = {}
        # Controller lease ownership is a memory cache too; the authoritative
        # owner session is persisted in job.json (claim_worker) and the lease.
        self._lease_owners: dict[str, str] = {}
        self._scanner = progress.EventScanner()
        self._last_breakaway = False

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
            "steering": str(job_dir / STEERING_FILE),
            "progress": str(job_dir / progress.PROGRESS_FILE),
            "progress_md": str(job_dir / progress.PROGRESS_MD_FILE),
            "progress_notes": str(job_dir / progress.PROGRESS_NOTES_FILE),
        }

    def _job_lock(self, job_dir: Path) -> Path:
        return job_dir / JOB_LOCK_NAME

    def _status_paths(self, job_id: str, job: dict[str, Any]) -> dict[str, str]:
        """Job paths with the live progress-notes path inside the workspace.

        The worker writes ``<workspace>/.tmp/PROGRESS_NOTES.md`` because the
        job directory is outside its sandbox; the legacy job-dir path is still
        reported (and still read by the digest) for jobs started before that.
        """
        paths = self._job_paths(job_id)
        workspace = job.get("workspace")
        if isinstance(workspace, str) and workspace:
            paths["progress_notes"] = str(
                Path(workspace) / ".tmp" / progress.PROGRESS_NOTES_FILE
            )
        paths["progress_notes_legacy"] = str(
            self._job_dir(job_id) / progress.PROGRESS_NOTES_FILE
        )
        return paths

    # ------------------------------------------------------------ validation
    def _workspace(self, candidate: str) -> Path:
        """Accept the repository root or a registered git worktree of it.

        Arbitrary subdirectories are refused: a distinct lock per workspace
        path is only safe when a workspace is a whole checkout.  The registered
        worktree list (``git worktree list --porcelain``) is the allow-list.
        """
        try:
            path = Path(candidate or ".").expanduser()
            if not path.is_absolute():
                path = self.config.repo_root / path
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PluginError("workspace_invalid", f"workspace cannot be resolved: {exc}") from exc
        if not resolved.is_dir():
            raise PluginError("workspace_invalid", "workspace is not a directory")
        normalized = os.path.normcase(str(resolved))
        repo_root = os.path.normcase(str(self.config.repo_root.resolve()))
        if normalized == repo_root:
            return resolved
        registered = {
            os.path.normcase(str(Path(entry["path"]).resolve()))
            for entry in gitutil.worktrees(self.config.repo_root)
            if isinstance(entry.get("path"), str)
        }
        if normalized in registered:
            return resolved
        if _within(self.config.repo_root, resolved):
            raise PluginError(
                "workspace_not_registered",
                "workspace must be the repository root or a registered git worktree "
                "of it; a subdirectory is not its own workspace",
                recovery="Create one with start_worker(use_worktree=true) and use its path.",
            )
        raise PluginError(
            "workspace_outside_repo",
            "workspace must be the repository root or a registered worktree of it",
        )

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
        # Worktrees cannot see gitignored data (DBs, indexes); the worker gets
        # the main checkout's data root by absolute path and the one-line
        # preamble tells it to read it read-only.
        env[REALITY_DATA_ROOT_ENV] = str(self.config.data_root)
        return env

    def _capability(self) -> heartbeat.LauncherCapabilities:
        if self._capabilities is None:
            self._capabilities = heartbeat.probe_launcher(
                self._launcher_command(), self.config.repo_root, self._launcher_env()
            )
        return self._capabilities

    # ------------------------------------------------------------ preflight
    def _key_present(self, name: str) -> bool:
        """Presence only; the value is never read into a result or log."""
        env = self.config.environ or {}
        if env.get(name):
            return True
        if (env.get("DSH_WORKER_TESTING") == "1") or os.name != "nt":
            return False
        try:
            import winreg

            for hive, sub in (
                (winreg.HKEY_CURRENT_USER, "Environment"),
                (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            ):
                try:
                    with winreg.OpenKey(hive, sub) as key:
                        value, _ = winreg.QueryValueEx(key, name)
                        if value:
                            return True
                except OSError:
                    continue
        except ImportError:
            return False
        return False

    def _preflight(self) -> None:
        """Refuse a start that the real launcher would fail seconds later.

        Without this, a missing dsh binary or key env produced a job that went
        straight to ``failed/launcher_error`` with a generic message.  Only the
        real launcher (no DSH_WORKER_LAUNCHER override) is checked, unless a
        test opts in with DSH_WORKER_PREFLIGHT=1.
        """
        env = self.config.environ or {}
        if self.config.launcher_path is not None and env.get("DSH_WORKER_PREFLIGHT") != "1":
            return
        dsh = Path(env.get("DSH_WORKER_DSH_PATH") or (Path.home() / ".bun" / "bin" / "dsh.exe"))
        if not dsh.is_file():
            raise PluginError(
                "dsh_missing",
                f"dsh binary not found at {dsh}; install with: bun add -g @deepseek-ai/dsh (never npm)",
            )
        if not self._key_present(KEY_ENV):
            raise PluginError(
                "api_key_missing",
                f"{KEY_ENV} is not set in the process or Windows user/machine environment",
            )

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
        """One mutation lock per workspace path.

        The main checkout keeps the historical filename; each registered
        worktree gets its own hashed lock, so parallel worktree writers are
        independent while two writers in one checkout still exclude each other.
        """
        ws = workspace or self.config.repo_root
        return self.config.locks_dir / workspace_lock_name(ws, self.config.repo_root)

    def _locks_guard(self) -> Path:
        return self.config.locks_dir / ".mutation.guard"

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
        raw_pid = status.get("worker_pid")
        if not raw_pid:
            return False
        worker_pid = _as_pid(raw_pid)
        worker_ticks = _as_pid(status.get("worker_creation_time"))
        if worker_pid is None or worker_ticks is None:
            return True
        return procutil.process_alive(worker_pid, worker_ticks)

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
        for pid_key, ticks_key in (
            ("supervisor_pid", "supervisor_creation_time"),
            ("worker_pid", "worker_creation_time"),
        ):
            if not status.get(pid_key):
                continue
            pid = _as_pid(status.get(pid_key))
            ticks = _as_pid(status.get(ticks_key))
            if pid is None or ticks is None:
                return True  # unverifiable ownership: fail closed
            if procutil.process_alive(pid, ticks):
                return True
        # Both recorded processes are absent or proven dead.  Only a final
        # status is positive proof that this job has stopped owning the tree.
        return status.get("phase") not in FINAL_PHASES

    def _repo_root_writer_active(self) -> bool:
        """Whether a mutating worker currently holds the repo-root lock.

        Only mutating jobs take a workspace lock, so an active repo-root lock is
        exactly "a mutating repo-root job may be rewriting code the manager is
        about to execute".  A missing lock means no writer; a lock that exists
        but cannot be read or validated (partial write, bad JSON, permissions,
        a directory) fails closed instead of being treated as absent.
        """
        path = self._lock_path(self.config.repo_root)
        try:
            path.lstat()
        except FileNotFoundError:
            return False
        except OSError:
            return True
        existing, _ = read_json_bounded(path, 65_536)
        if not isinstance(existing, dict):
            return True
        return self._lock_active(existing)

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
        with exclusive_lock(self._locks_guard()):
            for _ in range(3):
                try:
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    existing, error = read_json_bounded(path, 65_536)
                    if not isinstance(existing, dict):
                        raise PluginError(
                            "workspace_lock_unreadable",
                            "the workspace mutation lock exists but cannot be validated; "
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
                            "another mutating dsh worker is active in this workspace "
                            "(one writer per checkout/worktree; other worktrees stay free)",
                            existing_job_id=existing.get("job_id"),
                            workspace=str(workspace),
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
        raise PluginError("workspace_lock_failed", "could not acquire the workspace mutation lock")

    def _update_lock(self, workspace: Path, job_id: str, supervisor_pid: int | None, ticks: int | None) -> None:
        path = self._lock_path(workspace)
        with exclusive_lock(self._locks_guard()):
            existing, _ = read_json_bounded(path, 65_536)
            if not isinstance(existing, dict) or existing.get("job_id") != job_id:
                return
            existing["supervisor_pid"] = supervisor_pid
            existing["supervisor_creation_time"] = ticks
            atomic_write_json(path, existing)

    def _release_lock(self, workspace: Path, job_id: str, force: bool = False) -> bool:
        """Release the workspace lock, never while a recorded worker lives.

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
        with exclusive_lock(self._locks_guard()):
            path = self._lock_path(workspace)
            existing, _ = read_json_bounded(path, 65_536)
            if isinstance(existing, dict) and existing.get("job_id") == job_id:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                return True
            return False

    # ------------------------------------------------- shared control state
    def _steer(self, job_dir: Path, kind: str, text: str, session: str | None = None) -> dict[str, Any]:
        """Append one audit line (who/when/kind/first 200 chars).  No token."""
        record = {
            "at": iso(),
            "session": (session or self.config.session_label)[:MAX_SESSION_LABEL],
            "kind": kind,
            "text": str(text or "")[:MAX_STEERING_TEXT],
        }
        append_jsonl_locked(job_dir / STEERING_FILE, record, self._job_lock(job_dir))
        return record

    def _last_steering(self, job_dir: Path) -> dict[str, Any] | None:
        tail = read_text_bounded_tail(job_dir / STEERING_FILE, 32_768)
        for line in reversed(tail.splitlines()):
            try:
                value = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict):
                return value
        return None

    def _persist_control_token(self, job_dir: Path, token: str) -> bool:
        protected = dpapi_protect(token.encode("utf-8"))
        if protected is None:
            return False
        with exclusive_lock(self._job_lock(job_dir)):
            atomic_write_bytes(job_dir / TOKEN_FILE, protected)
        return True

    def _control_token(self, job_id: str, job_dir: Path | None = None) -> str | None:
        """Decrypt this Windows user's persisted job token; never log it.

        A legacy/partial job without ``control_token.bin`` reports no token
        (backward compatible), it does not fall back to a default.
        """
        cached = self._control_tokens.get(job_id)
        if cached:
            return cached
        directory = job_dir or self._job_dir(job_id)
        raw, _error = read_bytes_bounded(directory / TOKEN_FILE, 16_384)
        if not raw:
            return None
        plain = dpapi_unprotect(raw)
        if not plain:
            return None
        try:
            token = plain.decode("utf-8").strip()
        except UnicodeError:
            return None
        if len(token) < 32:
            return None
        self._control_tokens[job_id] = token
        return token

    def _create_worktree(self, job_id: str, base: str | None) -> dict[str, Any]:
        path = self.config.worktrees_root / job_id
        branch = f"dsh/{job_id}"
        info = gitutil.worktree_add(
            self.config.repo_root, path, branch, base or "HEAD"
        )
        return {
            "enabled": True,
            "path": info["path"],
            "branch": info["branch"],
            "base": base or "HEAD",
            "base_commit": info["base_commit"],
            "created_at": iso(),
        }

    def _owner_view(self, job: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        job_id = str(job.get("job_id") or "")
        owner_session = job.get("owner_session")
        last = self._last_steering(self._job_dir(job_id)) if valid_job_id(job_id) else None
        claim = job.get("owner_claim") if isinstance(job.get("owner_claim"), dict) else None
        return {
            "session_label": self.config.session_label,
            "owner_session": owner_session,
            "is_owner": bool(
                owner_session == self.config.session_label or job_id in self._lease_owners
            ),
            "claim": claim,
            "last_steerer": (last or {}).get("session"),
            "last_steering_at": (last or {}).get("at"),
            "last_steering_kind": (last or {}).get("kind"),
        }

    def _worktree_view(self, job: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        worktree = job.get("worktree")
        if not isinstance(worktree, dict) or not worktree.get("enabled"):
            return {"enabled": False}
        commit = status.get("worktree_commit")
        if not isinstance(commit, dict):
            commit = {}
        return {
            "enabled": True,
            "path": worktree.get("path"),
            "branch": worktree.get("branch"),
            "base": worktree.get("base"),
            "base_commit": worktree.get("base_commit"),
            "head": commit.get("head") or worktree.get("base_commit"),
            "commits": commit.get("commits"),
            "files_changed": commit.get("files_changed"),
            "files_changed_paths": commit.get("files_changed_paths") or [],
            "committed": bool(commit.get("committed")),
            "commit": commit.get("commit") or (commit.get("head") if commit.get("committed") else None),
            "commit_message": commit.get("message"),
            "commit_reason": commit.get("reason"),
            "commit_error": commit.get("error"),
        }

    # ---------------------------------------------------------------- start
    def start_worker(
        self,
        *,
        brief: str | None = None,
        task_file: str | None = None,
        workspace: str = ".",
        permission: str = "read-only",
        write_scope: str = "workspace",
        confirm_data_write: bool = False,
        confirm_full_access: bool = False,
        confirm_repo_root_write: bool = False,
        writes: list[str] | None = None,
        approved_by: str | None = None,
        heartbeat_interval_seconds: int = 900,
        missed_replies: int = 2,
        max_output_tokens: int | None = None,
        max_result_bytes: int = DEFAULT_RESULT_BYTES,
        hard_timeout_seconds: int | None = None,
        followup_wait_seconds: int = 0,
        controller_lease_seconds: int = 1800,
        refresh_context: bool = True,
        context_pack: bool = False,
        use_worktree: bool = False,
        base: str | None = None,
        test_cmd: str | None = None,
        progress_interval_seconds: int = DEFAULT_PROGRESS_INTERVAL_SECONDS,
    ) -> dict[str, Any]:
        if not isinstance(use_worktree, bool):
            raise PluginError("worktree_flag_invalid", "use_worktree must be true or false")
        if not isinstance(context_pack, bool):
            raise PluginError("context_pack_flag_invalid", "context_pack must be true or false")
        if base is not None and (not isinstance(base, str) or not base.strip()):
            raise PluginError("base_invalid", "base must be a non-empty git ref or omitted")
        if test_cmd is not None and (
            not isinstance(test_cmd, str)
            or not test_cmd.strip()
            or len(test_cmd) > MAX_TEST_CMD_CHARS
            or "\x00" in test_cmd
        ):
            raise PluginError(
                "test_cmd_invalid",
                f"test_cmd must be a non-empty command of at most {MAX_TEST_CMD_CHARS} chars",
            )
        now = self.config.now()
        if is_peak(now):
            raise PluginError(
                "peak_hours",
                "DeepSeek worker starts are refused during peak hours "
                "(Mon-Fri 06:30-09:30 and 11:30-15:30 IST)",
            )
        if is_peak(now + timedelta(seconds=PEAK_START_MARGIN_SECONDS)):
            # The harness re-checks the real clock when it starts; a start at
            # 06:29:59 could be refused by the launcher a moment later and
            # surface as a launcher failure instead of a clear refusal.
            raise PluginError(
                "peak_hours_imminent",
                f"a DeepSeek peak window starts within {PEAK_START_MARGIN_SECONDS}s; "
                "the launcher would refuse this run. Start after the window ends.",
            )
        if use_worktree:
            # The worktree derives its own workspace; the repository root is
            # the only meaningful value for the (ignored) workspace argument.
            raw_ws = str(workspace or ".").strip()
            if raw_ws in ("", "."):
                provided = self.config.repo_root
            else:
                provided = Path(raw_ws).expanduser()
                if not provided.is_absolute():
                    provided = self.config.repo_root / provided
            try:
                provided_resolved = provided.resolve(strict=False)
            except (OSError, RuntimeError, ValueError) as exc:
                raise PluginError("workspace_invalid", f"workspace cannot be resolved: {exc}") from exc
            if os.path.normcase(str(provided_resolved)) != os.path.normcase(
                str(self.config.repo_root)
            ):
                raise PluginError(
                    "workspace_invalid",
                    "use_worktree creates the workspace itself; omit workspace (the "
                    "repository root is used only for git commands)",
                )
            ws = self.config.repo_root
        else:
            ws = self._workspace(workspace)
        text, task_relative = self._read_brief(brief, task_file)
        brief_first_line = _first_line(text)
        brief_warnings = lint_worker_brief(text)
        if permission not in PERMISSIONS:
            raise PluginError("permission_invalid", f"permission must be one of {PERMISSIONS}")
        if write_scope not in WRITE_SCOPES:
            raise PluginError(
                "write_scope_invalid", f"write_scope must be one of {WRITE_SCOPES}"
            )
        if not isinstance(confirm_data_write, bool):
            raise PluginError("confirm_invalid", "confirm_data_write must be true or false")
        if not isinstance(confirm_full_access, bool):
            raise PluginError("confirm_invalid", "confirm_full_access must be true or false")
        if not isinstance(confirm_repo_root_write, bool):
            raise PluginError(
                "confirm_invalid", "confirm_repo_root_write must be true or false"
            )
        if approved_by is not None:
            if (
                not isinstance(approved_by, str)
                or not approved_by.strip()
                or len(approved_by) > MAX_APPROVED_BY_CHARS
                or "\x00" in approved_by
            ):
                raise PluginError(
                    "approved_by_invalid",
                    f"approved_by must be 1..{MAX_APPROVED_BY_CHARS} characters naming who approved",
                )
            approved_by = approved_by.strip()
        if write_scope == "data" and not confirm_data_write:
            raise PluginError(
                "confirm_data_write_required",
                "write_scope='data' can write REALITY_DATA_ROOT and D:\\RealityEngine; "
                "pass confirm_data_write=true only for a brief approved to write there",
            )
        if write_scope == "full" and not confirm_full_access:
            raise PluginError(
                "confirm_full_access_required",
                "write_scope='full' removes the file sandbox entirely; ask Shivam first, "
                "then pass confirm_full_access=true",
            )
        write_dbs = _normalize_writes(writes)
        if write_dbs and write_scope != "data":
            raise PluginError(
                "writes_requires_data_scope",
                "writes=[...] names the DBs a data-scope job may write; pass "
                "write_scope='data' (with confirm_data_write=true) to use it",
            )
        if write_scope == "data" and not write_dbs:
            # A data job without named DBs holds no db: lock, so nothing stops
            # it writing any database -- data scope would be full access with a
            # friendlier name.
            raise PluginError(
                "writes_required",
                "write_scope='data' must name the DBs the brief is approved to write "
                "via writes=[...]; without them the job would hold no db: lock",
            )
        # dsh 0.2.1 has one writable root per session (the workspace cwd) and no
        # extra-roots config.  Data/full scope therefore runs the dsh
        # danger-full-access mode; "data" is narrowed by the brief's write
        # roots, the per-DB locks, and the confirmation, not by the sandbox.
        effective_permission = (
            "danger-full-access" if write_scope in ("data", "full") else permission
        )
        mutating = effective_permission != "read-only"
        repo_root_workspace = (
            not use_worktree
            and os.path.normcase(str(ws.resolve()))
            == os.path.normcase(str(self.config.repo_root.resolve()))
        )
        if mutating and repo_root_workspace and not confirm_repo_root_write:
            # A mutating worker in the main checkout root can rewrite code that
            # later runs unconfined (the context-pack builder, supervisor.py,
            # .git/config, other jobs' records).  Worktree and read-only jobs
            # cannot reach those, so only this case needs the explicit flag.
            raise PluginError(
                "repo_root_write_requires_confirmation",
                "this mutating job would write the main checkout root, where code "
                "that runs unsandboxed lives (the context-pack builder, supervisor.py, "
                ".git/config and other jobs' records). Pass confirm_repo_root_write="
                "true only after Shivam approved a worker that may rewrite the repo root.",
            )
        data_locks = [f"db:{name}" for name in write_dbs]
        if not isinstance(heartbeat_interval_seconds, int) or not 30 <= heartbeat_interval_seconds <= 86_400:
            raise PluginError("heartbeat_invalid", "heartbeat interval must be 30..86400 seconds")
        progress_interval_seconds = _progress_interval(progress_interval_seconds)
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

        self._preflight()
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
        busy = self._reserve_resource_locks(data_locks, job_id)
        if busy:
            raise PluginError(
                "resource_busy",
                "the DBs named in writes are already held by another job; two "
                "writers must never share a SQLite DB",
                resource_locks=busy,
            )
        job_dir = self.config.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        paths = self._job_paths(job_id)
        lock_path: Path | None = None
        supervisor_spawned = False
        worktree_record: dict[str, Any] | None = None
        try:
            if use_worktree:
                try:
                    worktree_record = self._create_worktree(job_id, base)
                except gitutil.GitError as exc:
                    raise PluginError("worktree_failed", str(exc)) from exc
                ws = Path(worktree_record["path"])
                text = f"{WORKTREE_PREAMBLE}\n\n{text}"
            # The git identity is captured HERE, outside the sandbox, before
            # the worker can rewrite <workspace>/.git.  The supervisor commits
            # only against these stored paths (never the worker-writable file).
            git_identity = gitutil.checkout_identity(ws) if mutating else None
            write_roots = [str(ws)]
            if write_scope in ("data", "full"):
                write_roots += [str(self.config.data_root), D_REALITY_ENGINE]
            # The generated repo/data map (tasks/worker_context/CONTEXT.md) is
            # attached before the task brief only when the caller opts in
            # (context_pack=true; the default is false).  A stale pack is
            # regenerated with a 60 s bound; failure is a warning, never a
            # refused start.
            warnings: list[str] = list(brief_warnings)
            context_info: dict[str, Any] = {
                "enabled": False,
                "path": None,
                "regenerated": False,
            }
            # Take the mutation lock BEFORE attaching the pack: the pack guard
            # reads this lock, and a starting repo-root writer must never let
            # the unsandboxed manager run the builder.  The lock's status is
            # not published yet, so the guard fails closed for this start.
            if mutating:
                lock_path = self._acquire_lock(ws, job_id)
            if context_pack:
                text, pack_warnings, context_info = attach_context_pack(
                    text,
                    repo_root=self.config.repo_root,
                    data_root=self.config.data_root,
                    now=now,
                    # A mutating repo-root worker can rewrite the builder that
                    # this unsandboxed manager would execute; never run it
                    # while such a writer holds the repo-root lock.
                    allow_regeneration=not self._repo_root_writer_active(),
                )
                warnings.extend(pack_warnings)
            # Standing instruction, not a question: the worker must never stop
            # or answer it, only append a progress line.
            text = (f"{text.rstrip()}\n\n{CODE_INTEL_INSTRUCTION}\n\n"
                    f"{PROGRESS_NOTES_INSTRUCTION}\n")
            atomic_write_text(job_dir / "brief.md", text)
            baseline = (
                gitutil.snapshot(
                    ws,
                    identity=git_identity,
                    repo_root=self.config.repo_root,
                )
                if mutating
                else {"available": False, "reason": "read_only"}
            )
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
                effective_permission,
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
            if write_scope in ("data", "full") and permission != "danger-full-access":
                warnings.append(
                    "write_scope_uses_full_access: dsh 0.2.1 has one writable root per "
                    "session and no extra-roots config, so write_scope="
                    f"{write_scope!r} runs the dsh danger-full-access mode; the brief's "
                    "write roots and (for data) the per-DB locks are the real scope"
                )
            if write_scope == "data":
                warnings.append(
                    "data_scope: write only inside "
                    + ", ".join(write_roots)
                    + "; the supervisor holds "
                    + ", ".join(data_locks)
                    + " (dsh 0.2.1 runs full access at the OS level; the locks and this "
                    "brief are the only scope)"
                )
            if write_scope == "full":
                warnings.append(
                    "full_access: the file sandbox is disabled for this job; Shivam must "
                    "approve it before Claude passes confirm_full_access=true"
                )
            if write_scope in ("data", "full") and not approved_by:
                warnings.append(
                    "approval_not_recorded: pass approved_by with who approved this write "
                    "scope; confirm_* is only the caller's own flag"
                )
            token_persisted = self._persist_control_token(job_dir, control_token)
            if not token_persisted:
                warnings.append(
                    "control_token_not_persisted: DPAPI is unavailable, so only this MCP "
                    "server process can steer the job"
                )
            job = {
                "schema": 1,
                "job_id": job_id,
                "created_at": iso(now),
                "repo_root": str(self.config.repo_root),
                "plugin_root": str(self.config.plugin_root),
                "workspace": str(ws),
                "task_file": task_relative,
                "permission": effective_permission,
                "permission_requested": permission,
                "write_scope": write_scope,
                "writes": write_dbs,
                "write_roots": write_roots,
                "resource_locks": data_locks,
                "model": MODEL,
                "effort": EFFORT,
                "account": ACCOUNT,
                "key_env": KEY_ENV,
                "provider_session": provider_session,
                "provider_session_kind": "opencode_routing_cache",
                "conversation_id": None,
                "controller_lease_owner_id": owner_id,
                "owner_session": self.config.session_label,
                "brief_first_line": brief_first_line,
                "worktree": worktree_record,
                "git": git_identity,
                "approved_by": approved_by,
                "confirm_repo_root_write": confirm_repo_root_write,
                "data_root": str(self.config.data_root),
                "context_pack": context_info,
                "test_cmd": test_cmd,
                "progress_interval_seconds": progress_interval_seconds,
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
            atomic_write_json_locked(job_dir / "job.json", job, self._job_lock(job_dir))
            lease_now = utc_now()
            lease = {
                "schema": LEASE_SCHEMA,
                "job_id": job_id,
                "owner_id": owner_id,
                "owner_pid": os.getpid(),
                "owner_session": self.config.session_label,
                "created_at": iso(lease_now),
                "renewed_at": iso(lease_now),
                "deadline": iso(lease_now + timedelta(seconds=controller_lease_seconds)),
                "lease_seconds": controller_lease_seconds,
                "renewals": 0,
            }
            atomic_write_json_locked(job_dir / LEASE_FILE, lease, self._job_lock(job_dir))
            self._lease_owners[job_id] = owner_id
            initial_status = {
                "schema": 1,
                "job_id": job_id,
                "phase": "starting",
                "started_at": iso(now),
                "updated_at": iso(now),
                "write_scope": write_scope,
                "writes": write_dbs,
                "write_roots": write_roots,
                "approved_by": approved_by,
                "confirm_repo_root_write": confirm_repo_root_write,
                "tmp_dir": None,
                "tool_calls_before_first_edit": None,
                "first_edit_at": None,
                "orientation_seconds": None,
                "worker_commits": [],
                "detached": [],
                "resource_locks": data_locks,
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
            atomic_write_json_locked(
                job_dir / "status.json", initial_status, self._job_lock(job_dir)
            )
            self._steer(
                job_dir,
                "start",
                f"permission={effective_permission} write_scope={write_scope} "
                f"workspace={ws}"
                + (f" base={base or 'HEAD'}" if use_worktree else ""),
            )

            supervisor_pid = self._spawn_supervisor(job_dir, control_token)
            supervisor_spawned = True
            if os.name == "nt" and not self._last_breakaway:
                warnings.append(
                    "supervisor could not break away from the MCP host's job object: if this "
                    "MCP server is closed or restarted, the host may kill this worker too"
                )
            self._control_tokens[job_id] = control_token
            ticks = procutil.process_creation_time(supervisor_pid)
            if mutating:
                self._update_lock(ws, job_id, supervisor_pid, ticks)
            status = self._wait_for_start(job_dir, supervisor_pid)
            # A supervisor that failed before acquiring the named locks leaves
            # its reservations behind; one that is starting removes them itself
            # as soon as it holds the real OS lock.  Releasing a live job's
            # reservations here would reopen the start-window race.
            if str(status.get("phase") or "") in FINAL_PHASES:
                self._release_resource_reservations(job_id)
            return {
                "ok": True,
                "job_id": job_id,
                "phase": status.get("phase", "starting"),
                "workspace": str(ws),
                "permission": effective_permission,
                "permission_requested": permission,
                "write_scope": write_scope,
                "writes": write_dbs,
                "write_roots": write_roots,
                "approved_by": approved_by,
                "confirm_repo_root_write": confirm_repo_root_write,
                "resource_locks": data_locks,
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
                "session_label": self.config.session_label,
                "owner_session": self.config.session_label,
                "control_token_persisted": token_persisted,
                "worktree": worktree_record,
                "context_pack": context_info,
                "progress_interval_seconds": progress_interval_seconds,
                "progress_path": paths["progress"],
                "progress_md_path": paths["progress_md"],
                "progress_notes_path": str(ws / ".tmp" / progress.PROGRESS_NOTES_FILE),
                "warnings": warnings + list(status.get("warnings") or []),
                "survives_server_exit": bool(self._last_breakaway) or os.name != "nt",
                "server_shutdown": SERVER_SHUTDOWN_SEMANTICS,
            }
        except Exception:
            self._release_resource_reservations(job_id)
            if worktree_record is not None and not supervisor_spawned:
                # No worker ever ran in this worktree: remove it and its branch
                # so a refused start does not leave a dangling checkout.
                try:
                    gitutil.worktree_remove(
                        self.config.repo_root,
                        Path(worktree_record["path"]),
                        worktree_record.get("branch"),
                    )
                except Exception:
                    pass
            if lock_path is not None:
                # Never release under a recorded worker.  Before the supervisor
                # exists there is no worker, so the half-created job may release
                # safely; afterwards cancellation/ownership checks decide.
                self._release_lock(ws, job_id, force=not supervisor_spawned)
            self._control_tokens.pop(job_id, None)
            self._lease_owners.pop(job_id, None)
            try:
                (job_dir / TOKEN_FILE).unlink(missing_ok=True)
            except OSError:
                pass
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
        # Break the supervisor out of the MCP host's job object when allowed.
        # Hosts (the Python MCP stdio client; possibly Claude/Codex) put the
        # server in a KILL_ON_JOB_CLOSE job, so a server that vanished
        # mid-session ("MCP server removed from the configuration") used to
        # take every running worker down with it, with no final status.  The
        # breakaway supervisor still owns its worker through its own job
        # object, and the controller lease remains the hard upper bound.
        want_breakaway = (
            os.name == "nt" and (self.config.environ or {}).get("DSH_WORKER_BREAKAWAY", "1") != "0"
        )
        attempts = [flags | procutil.CREATE_BREAKAWAY_FROM_JOB, flags] if want_breakaway else [flags]
        self._last_breakaway = False
        with open(log_path, "ab", buffering=0) as log:
            last_exc: OSError | None = None
            process = None
            for attempt_flags in attempts:
                try:
                    process = subprocess.Popen(
                        [sys.executable, str(supervisor), str(job_dir)],
                        cwd=str(self.config.repo_root),
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        creationflags=attempt_flags,
                        close_fds=True,
                        **kwargs,
                    )
                except OSError as exc:  # breakaway not permitted by the host job
                    last_exc = exc
                    continue
                self._last_breakaway = bool(attempt_flags & procutil.CREATE_BREAKAWAY_FROM_JOB)
                break
            if process is None:
                raise PluginError(
                    "supervisor_spawn_failed", f"could not start supervisor: {last_exc}"
                ) from last_exc
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

    def _read_status(self, job_dir: Path, attempts: int = 4) -> dict[str, Any]:
        """Read status.json, retrying a transient lock/garbled read.

        An unreadable record is phase ``unknown``, never ``starting``: the old
        fallback let a momentary antivirus/indexer lock on a *live* job's
        status file classify it as ``lost``/final.
        """
        error: str | None = None
        for attempt in range(max(1, attempts)):
            status, error = read_json_bounded(job_dir / "status.json")
            if isinstance(status, dict):
                return status
            if error == "missing" and attempt == 0 and not (job_dir / "status.json").exists():
                break
            time.sleep(0.05 * (attempt + 1))
        return {
            "phase": "unknown",
            "status_unreadable": error or "invalid",
            "warnings": [f"status record unreadable: {error}"],
        }

    def _process_view(self, status: dict[str, Any], heartbeat_live: dict[str, Any] | None) -> dict[str, Any]:
        supervisor_pid = _as_pid(status.get("supervisor_pid"))
        supervisor_ticks = _as_pid(status.get("supervisor_creation_time"))
        worker_pid = _as_pid(status.get("worker_pid"))
        worker_ticks = _as_pid(status.get("worker_creation_time"))
        invalid = [
            key
            for key in (
                "supervisor_pid",
                "supervisor_creation_time",
                "worker_pid",
                "worker_creation_time",
            )
            if status.get(key) not in (None, "", 0) and _as_pid(status.get(key)) is None
        ]
        supervisor_alive = bool(
            supervisor_pid and procutil.process_alive(supervisor_pid, supervisor_ticks)
        )
        worker_alive = bool(worker_pid and procutil.process_alive(worker_pid, worker_ticks))
        return {
            "record_invalid_fields": invalid,
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

    def _persist_lost(self, job_dir: Path, status: dict[str, Any]) -> dict[str, Any]:
        """Write the derived 'lost' phase to disk so file readers stop seeing a live job.

        Only called once both the supervisor and the worker are verified gone, so no
        other writer can race this one. Idempotent: a final phase on disk is kept.
        """
        current = self._read_status(job_dir)
        if current.get("phase") in FINAL_PHASES:
            return current
        lost = {
            **current,
            "phase": "lost",
            "outcome": "lost",
            "error": current.get("error")
            or "supervisor and worker are both gone and no final status was written",
            "finished_at": current.get("updated_at") or iso(),
            "updated_at": iso(),
        }
        try:
            atomic_write_json_locked(job_dir / "status.json", lost, self._job_lock(job_dir))
        except OSError:
            return status
        return lost

    def get_status(self, job_id: str) -> dict[str, Any]:
        job, job_dir = self._load_job(job_id)
        status = self._read_status(job_dir)
        heartbeat_live, heartbeat_error = heartbeat.read_heartbeat(job_dir)
        heartbeat_record = dict(job.get("heartbeat") or status.get("heartbeat") or {})
        token_available = self._control_token(job_id, job_dir) is not None
        descriptor_available = heartbeat.control_available(
            Path(self._job_paths(job_id)["control"]), heartbeat_live
        )
        heartbeat_record.update(
            {
                "present": heartbeat_live is not None,
                "read_error": heartbeat_error,
                "adapter": heartbeat_live,
                # The token is persisted DPAPI-encrypted (CurrentUser), so any
                # dsh-worker server process of this Windows user can decrypt it.
                # A legacy job with no persisted token reports unavailable.
                "control_available": descriptor_available and token_available,
                "control_descriptor_available": descriptor_available,
                "control_token_available": token_available,
                "control_unavailable_reason": (
                    None
                    if descriptor_available and token_available
                    else "control_token_missing"
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
        if job.get("start_failed") and phase == "unknown":
            # start_worker failed before a supervisor/status existed.
            phase = "failed"
            status = {**status, "outcome": "start_failed", "error": "start_worker failed before launch"}
        elif phase in ACTIVE_PHASES and process["record_invalid_fields"]:
            phase = "unknown"
            warnings.append(
                "status record has unusable process fields "
                f"({', '.join(process['record_invalid_fields'])}); liveness cannot be verified"
            )
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
        interval = _as_pid(_num(heartbeat_record.get("interval_seconds"))) or 900
        window = _as_pid(_num(heartbeat_record.get("response_window_seconds"))) or 900
        misses = _as_pid(_num(heartbeat_record.get("missed_replies_allowed"))) or 2
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
        if (
            not process["supervisor_alive"]
            and not process["worker_alive"]
            and phase not in FINAL_PHASES
            and phase != "unknown"
        ):
            phase = "lost"
            final = True
            running = False
        if phase == "lost" and status.get("phase") not in FINAL_PHASES:
            status = self._persist_lost(job_dir, status)
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
            self._reap_child(_as_pid(status.get("supervisor_pid")), timeout=1.0)
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
        failure_reason = (
            self._failure_reason(job_dir, status, heartbeat_live)
            if phase in {"failed", "lost", "cancelled"}
            else None
        )
        if phase == "finished" and result_bytes == 0 and job.get("kind") != "data_job":
            warnings.append(
                "worker finished (exit 0) but wrote an empty answer; treat this as a "
                "failed run, not a result"
            )
        progress_view = self._progress(
            job_id,
            job_dir,
            phase=phase,
            running=running,
            final=final,
            stale=stale,
            awaiting_input=awaiting_input,
            started_at=status.get("started_at") or job.get("created_at"),
            finished_at=status.get("finished_at"),
            last_activity=last_activity,
            heartbeat_live=heartbeat_live,
            controller_lease=controller_lease,
            result_bytes=result_bytes,
            limits=job.get("limits") or {},
            failure_reason=failure_reason,
            data_job=job.get("kind") == "data_job",
        )
        owner_view = self._owner_view(job, status)
        worktree_view = self._worktree_view(job, status)
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
            "permission_requested": job.get("permission_requested"),
            # status.json is written by the supervisor; job.json sits in the
            # same directory and a worker whose workspace is the main checkout
            # can rewrite it.  The launch-time status record wins for scope.
            "write_scope": status.get("write_scope") or job.get("write_scope") or "workspace",
            "writes": status.get("writes") or job.get("writes") or [],
            "write_roots": status.get("write_roots") or job.get("write_roots") or [],
            "approved_by": status.get("approved_by") or job.get("approved_by"),
            "confirm_repo_root_write": bool(
                status.get(
                    "confirm_repo_root_write",
                    job.get("confirm_repo_root_write", False),
                )
            ),
            "resource_locks": status.get("resource_locks") or job.get("resource_locks") or [],
            "tmp_dir": status.get("tmp_dir"),
            "tmp_reparse_point": bool(status.get("tmp_reparse_point")),
            "tool_calls_before_first_edit": (
                status.get("tool_calls_before_first_edit")
                if status.get("tool_calls_before_first_edit") is not None
                else (progress_view.get("events") or {}).get("tool_calls_before_first_edit")
            ),
            "orientation_seconds": status.get("orientation_seconds"),
            "first_edit_at": status.get("first_edit_at"),
            "worker_commits": status.get("worker_commits") or [],
            "detached": status.get("detached") or [],
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
            "owner_session": job.get("owner_session"),
            "last_steerer": owner_view.get("last_steerer"),
            "steering": owner_view,
            "worktree": worktree_view,
            "heartbeat": heartbeat_record,
            "controller_lease": controller_lease,
            "controller_lease_error": lease_error,
            "controller_lease_expired": bool(controller_lease and controller_lease.get("expired")),
            # result.md is streamed incrementally by the harness, so a non-empty
            # file is NOT completion.  result_ready means "final and non-empty";
            # use progress.done / final for the finished flag.
            "result_ready": final and result_bytes > 0,
            "result_final": phase == "finished" and result_bytes > 0,
            "result_bytes": result_bytes,
            "result_is_streaming": running and result_bytes > 0,
            "failure_reason": failure_reason,
            "progress": progress_view,
            "result_kind": status.get("result_kind") or ("final" if final else "live"),
            "interim": bool(status.get("interim_result")),
            "partial": bool(status.get("partial")),
            "paths": self._status_paths(job_id, job),
            "limits": job.get("limits"),
            "warnings": warnings,
            "server_shutdown": SERVER_SHUTDOWN_SEMANTICS,
        }

    # ------------------------------------------------------------- progress
    _SECRETISH = re.compile(r"[A-Za-z0-9_\-]{32,}")

    def _failure_reason(
        self,
        job_dir: Path,
        status: dict[str, Any],
        heartbeat_live: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Why a job failed, from bounded non-reasoning sources only.

        The supervisor's generic "launcher exited nonzero" hid the real cause
        (missing dsh binary, missing key env, peak refusal, provider error).
        The launcher's own stderr (``stderr.log``) holds only harness/argparse
        messages; dsh reasoning goes to ``result.md.log`` and is never read
        here.  Lines starting ``dsh: reasoning`` are dropped and long
        token-like strings are redacted defensively.
        """
        reason: dict[str, Any] = {
            "outcome": status.get("outcome"),
            "exit_code": status.get("exit_code"),
            "heartbeat_failure": (heartbeat_live or {}).get("failure"),
            "heartbeat_failure_detail": None,
            "launcher_stderr_tail": [],
        }
        detail = (heartbeat_live or {}).get("failure_detail")
        if isinstance(detail, str):
            reason["heartbeat_failure_detail"] = self._SECRETISH.sub("[redacted]", detail)[:400]
        tail = read_text_bounded_tail(job_dir / "stderr.log", 4096)
        lines = [
            self._SECRETISH.sub("[redacted]", line.strip())[:300]
            for line in tail.splitlines()
            if line.strip() and not line.lstrip().startswith("dsh: reasoning")
        ]
        reason["launcher_stderr_tail"] = lines[-4:]
        text = " ".join(lines[-4:] + [str(reason["heartbeat_failure_detail"] or "")])
        hint = None
        for needle, label in (
            ("dsh not found", "dsh_binary_missing"),
            ("is not set", "api_key_env_missing"),
            ("peak hours", "peak_hours_refused"),
            ("MissingSessionID", "provider_session_missing"),
            ("timed out", "provider_timeout"),
            ("HTTP", "provider_http_error"),
        ):
            if needle in text:
                hint = label
                break
        reason["likely_cause"] = hint or reason["heartbeat_failure"] or status.get("outcome")
        return reason

    def _progress(
        self,
        job_id: str,
        job_dir: Path,
        *,
        phase: str,
        running: bool,
        final: bool,
        stale: bool,
        awaiting_input: bool,
        started_at: Any,
        finished_at: Any,
        last_activity: datetime | None,
        heartbeat_live: dict[str, Any] | None,
        controller_lease: dict[str, Any] | None,
        result_bytes: int,
        limits: dict[str, Any],
        failure_reason: dict[str, Any] | None,
        events_path: Path | None = None,
        data_job: bool = False,
    ) -> dict[str, Any]:
        """One orchestrator-facing answer to "is it done, is it moving, by when"."""
        now = utc_now()
        started = parse_iso(started_at)
        finished = parse_iso(finished_at)
        end = finished if final and finished else now
        elapsed = (end - started).total_seconds() if started else None
        idle = (now - last_activity).total_seconds() if last_activity and running else None
        events = self._scanner.scan(events_path or job_dir / "result.md.events.jsonl")
        lease_deadline = parse_iso((controller_lease or {}).get("deadline"))
        lease_remaining = (
            (lease_deadline - now).total_seconds() if lease_deadline and running else None
        )
        renewable_here = bool(job_id) and job_id in self._lease_owners
        hard_timeout = limits.get("hard_timeout_seconds") if isinstance(limits, dict) else None
        upper_bounds: list[tuple[datetime, str]] = []
        if lease_deadline and running:
            upper_bounds.append((lease_deadline, "controller_lease_deadline"))
        if isinstance(hard_timeout, int) and started and running:
            upper_bounds.append((started + timedelta(seconds=hard_timeout), "hard_timeout"))
        bound = min(upper_bounds) if upper_bounds else None
        notes: list[str] = []
        if running and lease_remaining is not None and lease_remaining < 600:
            notes.append(
                f"controller lease ends in {progress.fmt_duration(lease_remaining)}; the job will "
                "be stopped then unless renew_worker_lease is called"
                + ("" if renewable_here else " (this MCP server cannot renew it: restart lost ownership)")
            )
        last_kind = (heartbeat_live or {}).get("last_activity_kind")
        if final:
            if phase == "finished":
                if data_job:
                    headline = "done: finished"
                else:
                    headline = "done: finished" + ("" if result_bytes else " with an EMPTY answer")
            else:
                cause = (failure_reason or {}).get("likely_cause")
                headline = f"done: {phase}" + (f" ({cause})" if cause else "")
        elif phase == "unknown":
            headline = "unknown: status record unreadable; retry worker_status"
        elif awaiting_input:
            headline = "waiting for a follow-up (awaiting_input)"
        elif stale:
            headline = "running but STALE (no committed model/tool activity)"
        elif running:
            headline = "running"
        else:
            headline = phase
        parts = [headline, f"elapsed {progress.fmt_duration(elapsed)}"]
        if running and idle is not None:
            parts.append(
                f"last activity {progress.fmt_duration(idle)} ago"
                + (f" ({last_kind})" if last_kind else "")
            )
        if events.get("available"):
            parts.append(f"{events['tool_calls']} tool calls, {events['model_steps']} model steps")
            if events.get("tool_calls_before_first_edit") is not None:
                parts.append(
                    f"first edit after {events['tool_calls_before_first_edit']} calls"
                )
            if events.get("last_tool"):
                target = events.get("last_tool_target")
                parts.append(f"last tool {events['last_tool']}" + (f" on {target}" if target else ""))
        if running:
            parts.append(f"result.md {result_bytes} B so far (streaming, not final)")
        if bound:
            parts.append(f"hard stop by {iso(bound[0])} ({bound[1]})")
        return {
            "done": final,
            "succeeded": phase == "finished" and (data_job or result_bytes > 0),
            "answer_empty": phase == "finished" and not data_job and result_bytes == 0,
            "phase": phase,
            "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
            "seconds_since_activity": round(idle, 1) if idle is not None else None,
            "last_activity_kind": last_kind,
            "activity_count": (heartbeat_live or {}).get("activity_count"),
            "events": events,
            "tool_calls_before_first_edit": (
                events.get("tool_calls_before_first_edit") if events.get("available") else None
            ),
            "controller_lease_remaining_seconds": (
                round(lease_remaining, 1) if lease_remaining is not None else None
            ),
            "controller_lease_renewable_here": renewable_here,
            "eta": None,
            "eta_note": (
                "dsh publishes no completion estimate; judge progress by activity "
                "recency and counts. latest_finish_by is a hard upper bound, not a prediction."
            ),
            "latest_finish_by": iso(bound[0]) if bound else None,
            "latest_finish_reason": bound[1] if bound else None,
            "notes": notes,
            "summary": "; ".join(parts),
        }

    # ---------------------------------------------------------- server_info
    def server_info(self) -> dict[str, Any]:
        capability = self._capability()
        now = utc_now()
        active = sorted(self._control_tokens)
        return {
            "ok": True,
            "server": "dsh-worker",
            "version": SERVER_VERSION,
            "pid": os.getpid(),
            "started_at": iso(SERVER_STARTED_AT),
            "uptime_seconds": round((now - SERVER_STARTED_AT).total_seconds(), 1),
            "cwd": os.getcwd(),
            "repo_root": str(self.config.repo_root),
            "runtime_dir": str(self.config.runtime_dir),
            "worktrees_root": str(self.config.worktrees_root),
            "reality_data_root": str(self.config.data_root),
            "jobs_file": str(self.config.jobs_file),
            "session_label": self.config.session_label,
            "launcher": self._launcher_command()[1:],
            "launcher_capabilities": capability.as_dict(),
            "peak_now": is_peak(now),
            "jobs_owned_by_this_server": active,
            "note": (
                "Jobs started by an earlier server process are still visible through "
                "worker_status/list_workers. Their DPAPI-encrypted control token is "
                "readable by any dsh-worker server of this Windows user, so message/"
                "cancel work across processes; renew requires the recorded owner "
                "session, claim_worker, or adopt=true."
            ),
        }

    # ---------------------------------------------------------- inspect_run
    _RUN_SUFFIXES = (".status.json", ".events.jsonl", ".control.json", ".log")

    def inspect_run(self, out_file: str) -> dict[str, Any]:
        """Read-only view of a run started with the raw harness, not this server.

        ``run_deepseek_harness.py --out-file X`` writes ``X.status.json``
        (dsh-heartbeat-status/1), ``X.events.jsonl`` and ``X.control.json``.
        This reads those files and returns the same progress summary
        worker_status gives for plugin jobs.  It cannot message, renew or
        cancel such a run: the harness generates its control token in memory
        (or reads it from an env var this server never sees) and there is no
        plugin supervisor/lease.  Liveness is checked against the recorded
        dsh PID *and* its kernel creation time versus the run's start, so a
        recycled PID is not reported alive.
        """
        if not isinstance(out_file, str) or not out_file.strip():
            raise PluginError("out_file_invalid", "out_file must be the harness --out-file path")
        raw = Path(out_file).expanduser()
        if not raw.is_absolute():
            raw = self.config.repo_root / raw
        try:
            candidate = raw.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PluginError("out_file_invalid", f"out_file cannot be resolved: {exc}") from exc
        if not _within(self.config.repo_root, candidate):
            raise PluginError("out_file_outside_repo", "out_file must be inside the repository root")
        name = candidate.name
        for suffix in self._RUN_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                candidate = candidate.with_name(name[: -len(suffix)])
                break
        status_path = candidate.with_name(candidate.name + ".status.json")
        record, error = read_json_bounded(status_path, 1_048_576)
        if not isinstance(record, dict):
            raise PluginError(
                "run_not_found",
                f"no readable harness status file at {status_path}",
                record_error=error,
            )
        if record.get("schema") != heartbeat.STATUS_SCHEMA:
            raise PluginError("run_schema_mismatch", "status file is not dsh-heartbeat-status/1")
        hb = record.get("heartbeat") if isinstance(record.get("heartbeat"), dict) else {}
        pid = _as_pid(record.get("pid"))
        started = parse_iso(record.get("started_at"))
        state = str(record.get("state") or "unknown")
        alive = False
        pid_check = "no_pid"
        if pid is not None:
            ticks = procutil.process_creation_time(pid)
            if ticks is None:
                pid_check = "not_running"
            else:
                created = datetime.fromtimestamp((ticks - 116_444_736_000_000_000) / 1e7, timezone.utc)
                if started is not None and not (-30 <= (created - started).total_seconds() <= 300):
                    pid_check = "pid_reused"
                else:
                    alive = procutil.process_alive(pid, ticks)
                    pid_check = "alive" if alive else "not_running"
        ended = state in {"completed", "failed"} or record.get("exit_code") is not None
        if ended:
            phase = "finished" if state == "completed" and record.get("exit_code") in (0, None) else "failed"
        elif alive:
            phase = "running"
        else:
            phase = "lost"
        final = phase != "running"
        running = phase == "running"
        last_activity = parse_iso(hb.get("last_activity_at"))
        result_path = candidate
        try:
            result_bytes = result_path.stat().st_size
        except OSError:
            result_bytes = 0
        live = {
            "last_activity_kind": hb.get("last_activity_kind"),
            "activity_count": hb.get("activity_count"),
            "failure": record.get("failure"),
            "failure_detail": record.get("failure_detail"),
        }
        hard_timeout = hb.get("hard_timeout_seconds")
        failure = None
        if phase in {"failed", "lost"}:
            failure = {
                "outcome": phase,
                "exit_code": record.get("exit_code"),
                "heartbeat_failure": record.get("failure"),
                "heartbeat_failure_detail": (
                    self._SECRETISH.sub("[redacted]", str(record.get("failure_detail")))[:400]
                    if record.get("failure_detail")
                    else None
                ),
                "likely_cause": record.get("failure") or phase,
            }
        view = self._progress(
            "",
            candidate.parent,
            phase=phase,
            running=running,
            final=final,
            stale=False,
            awaiting_input=bool(hb.get("awaiting_input")),
            started_at=record.get("started_at"),
            finished_at=record.get("ended_at"),
            last_activity=last_activity,
            heartbeat_live=live,
            controller_lease=None,
            result_bytes=result_bytes,
            limits={"hard_timeout_seconds": hard_timeout if isinstance(hard_timeout, int) else None},
            failure_reason=failure,
            events_path=candidate.with_name(candidate.name + ".events.jsonl"),
        )
        control, _ = heartbeat.read_control(candidate.with_name(candidate.name + ".control.json"))
        return {
            "ok": True,
            "source": "raw_harness_run",
            "out_file": str(candidate),
            "run_id": record.get("run_id"),
            "phase": phase,
            "running": running,
            "final": final,
            "state": state,
            "exit_code": record.get("exit_code"),
            "pid": pid,
            "pid_check": pid_check,
            "started_at": record.get("started_at"),
            "ended_at": record.get("ended_at"),
            "updated_at": record.get("updated_at"),
            "last_activity_at": iso(last_activity) if last_activity else None,
            "unanswered_pings": hb.get("consecutive_unanswered"),
            "result_bytes": result_bytes,
            "result_ready": final and phase == "finished" and result_bytes > 0,
            "result_is_streaming": running and result_bytes > 0,
            "model": record.get("model"),
            "reasoning_effort": record.get("reasoning_effort"),
            "failure_reason": failure,
            "progress": view,
            "control_descriptor_state": (control or {}).get("state"),
            "messaging": {
                "available": False,
                "reason": (
                    "raw-harness runs keep their control token in the launching process; "
                    "this MCP server cannot authenticate to them. Start work through "
                    "start_worker when you need message_worker/renew/cancel."
                ),
            },
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
            "worktree": status.get("worktree"),
            "owner_session": status.get("owner_session"),
            "last_steerer": status.get("last_steerer"),
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
        if kind not in ("followup", "status"):
            raise PluginError("message_invalid", "kind must be followup or status")
        if kind == "status":
            # The delivered text must not read as the end of the task: a bare
            # ping used to make a worker answer it as its final result.
            message = f"{STATUS_CHECK_PREFIX}\n{message}"
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
            self._control_token(job_id, job_dir),
        )
        if response.get("ok"):
            # Auditable cross-session steering: who/when/kind/first 200 chars.
            # The token and full steering text are never written here.
            self._steer(job_dir, "message", f"{kind}: {message}")
        response["job_id"] = job_id
        response["phase"] = status["phase"]
        response["session_label"] = self.config.session_label
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
        adopt: bool = False,
    ) -> dict[str, Any]:
        """Explicitly renew the controller lease; never called by status reads.

        Allowed for the recorded owner session (``start_worker`` or
        ``claim_worker``), for this process's in-memory ownership, or for any
        caller passing ``adopt=true``.  Each call may extend by at most the
        7200-second cap (Shivam, 2026-10-24), so indefinite work still needs
        repeated explicit review rather than a background loop.
        """
        testing = (self.config.environ or {}).get("DSH_WORKER_TESTING") == "1"
        minimum = 1 if testing else 60
        maximum = 7200
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
        owner_session = job.get("owner_session")
        adopted = False
        if not owner and owner_session == self.config.session_label:
            # The persisted owner session (this process started or claimed it,
            # possibly in an earlier process incarnation with the same label).
            recorded = job.get("controller_lease_owner_id")
            if isinstance(recorded, str) and recorded:
                owner = recorded
        if not owner and adopt is True:
            # Explicit takeover after a restart.  The job keeps its original
            # owner id (the supervisor validates against it); adoption is a
            # deliberate controller act, never automatic, and cannot revive an
            # expired lease (checked below).
            recorded = job.get("controller_lease_owner_id")
            if isinstance(recorded, str) and recorded:
                owner = recorded
                adopted = True
        if not owner:
            raise PluginError(
                "controller_unavailable",
                "this MCP server does not own the job's controller lease; call "
                "claim_worker(job_id) to take ownership or renew with adopt=true",
            )
        lease_path = job_dir / LEASE_FILE
        with exclusive_lock(self._job_lock(job_dir)):
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
            updated["owner_session"] = owner_session or self.config.session_label
            updated["last_renewed_by"] = self.config.session_label
            if adopted:
                updated["adoptions"] = int(lease.get("adoptions") or 0) + 1
                updated["adopted_by_pid"] = os.getpid()
                updated["adopted_at"] = iso(now)
            atomic_write_json(lease_path, updated)
            self._steer(
                job_dir,
                "renew",
                f"extend_seconds={extend_seconds} adopt={adopted}",
            )
            if adopted:
                self._lease_owners[job_id] = owner
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
            "adopted": adopted,
            "owner_session": updated.get("owner_session"),
            "session_label": self.config.session_label,
            "automatic_renewal": False,
            "note": (
                "Renewal is explicit controller action only. Worker activity, "
                "status/result/list reads and model calls never renew this lease."
            ),
        }

    # --------------------------------------------------------------- claim
    def claim_worker(self, job_id: str, reason: str = "manual claim") -> dict[str, Any]:
        """Take over lease ownership of a running job; records who and why.

        The lease's stable owner id is deliberately unchanged: the supervisor
        validates every lease against it.  Ownership is the *session* recorded
        in job.json and in the steering audit, and it authorises future renewals
        without adopt=true.
        """
        job, job_dir = self._load_job(job_id)
        status = self.get_status(job_id)
        if not status["running"] or status["final"]:
            raise PluginError(
                "job_not_running",
                "only a running job's controller lease can be claimed",
                phase=status["phase"],
            )
        reason_text = str(reason or "").strip()[:MAX_STEERING_TEXT] or "manual claim"
        now = utc_now()
        with exclusive_lock(self._job_lock(job_dir)):
            current, error = read_json_bounded(job_dir / "job.json")
            if not isinstance(current, dict):
                raise PluginError(
                    "job_not_found",
                    "no persisted job record for this job_id",
                    job_id=job_id,
                    record_error=error,
                )
            previous = current.get("owner_session")
            claim = {
                "session": self.config.session_label,
                "at": iso(now),
                "reason": reason_text,
            }
            current["owner_session"] = self.config.session_label
            current["owner_claim"] = claim
            atomic_write_json(job_dir / "job.json", current)
            lease_path = job_dir / LEASE_FILE
            lease, _lease_error = read_lease(
                lease_path,
                expected_job_id=job_id,
                expected_owner_id=current.get("controller_lease_owner_id"),
                max_seconds=7200,
            )
            if lease is not None:
                updated = dict(lease)
                updated.pop("expired", None)
                updated.pop("remaining_seconds", None)
                updated["owner_session"] = self.config.session_label
                updated["claimed_by"] = self.config.session_label
                updated["claimed_at"] = iso(now)
                atomic_write_json(lease_path, updated)
            self._steer(job_dir, "claim", f"reason={reason_text}")
        owner_id = str(current.get("controller_lease_owner_id") or "")
        if owner_id:
            self._lease_owners[job_id] = owner_id
        return {
            "ok": True,
            "job_id": job_id,
            "claimed": True,
            "owner_session": self.config.session_label,
            "previous_owner_session": previous,
            "claim": claim,
            "session_label": self.config.session_label,
            "lease_deadline": (read_lease(
                job_dir / LEASE_FILE,
                expected_job_id=job_id,
                expected_owner_id=owner_id,
                max_seconds=7200,
            )[0] or {}).get("deadline"),
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
        self._steer(job_dir, "cancel", f"reason={reason}")
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
                    "workspace mutation lock was retained deliberately. Inspect the "
                    "process before starting another writer."
                )
            return response
        atomic_write_json_locked(
            job_dir / "cancel.request",
            {"requested_at": iso(), "reason": str(reason)[:500], "job_id": job_id},
            self._job_lock(job_dir),
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
            atomic_write_json_locked(
                job_dir / "status.json", current, self._job_lock(job_dir)
            )
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
        unreadable: list[dict[str, Any]] = []
        try:
            entries = sorted(self.config.jobs_dir.iterdir(), key=lambda p: p.name, reverse=True)
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_dir() or not valid_job_id(entry.name):
                continue
            try:
                job = self.get_status(entry.name)
            except Exception as exc:  # one corrupt record must not hide every other job
                unreadable.append(
                    {"job_id": entry.name, "error": exc.code if isinstance(exc, PluginError) else type(exc).__name__}
                )
                continue
            job_ws = job.get("workspace")
            if wanted and (
                not isinstance(job_ws, str)
                or os.path.normcase(str(Path(job_ws).resolve())) != wanted
            ):
                continue
            digests = progress.read_digests(entry, limit=1, max_bytes=65_536)
            latest_digest = digests[0] if digests else None
            jobs.append(
                {
                    "job_id": job["job_id"],
                    "phase": job["phase"],
                    "running": job["running"],
                    "stale": job["stale"],
                    "workspace": job["workspace"],
                    "permission": job["permission"],
                    "write_scope": job.get("write_scope") or "workspace",
                    "writes": job.get("writes") or [],
                    "confirm_repo_root_write": bool(
                        job.get("confirm_repo_root_write")
                    ),
                    "resource_locks": job.get("resource_locks") or [],
                    "tool_calls_before_first_edit": (
                        job.get("tool_calls_before_first_edit")
                        if job.get("tool_calls_before_first_edit") is not None
                        else (latest_digest or {}).get("tool_calls_before_first_edit")
                    ),
                    "orientation_seconds": (
                        job.get("orientation_seconds")
                        if job.get("orientation_seconds") is not None
                        else (latest_digest or {}).get("orientation_seconds")
                    ),
                    "owner_session": job.get("owner_session"),
                    "last_steerer": job.get("last_steerer"),
                    "worktree_branch": (job.get("worktree") or {}).get("branch"),
                    "started_at": job["started_at"],
                    "updated_at": job["updated_at"],
                    "final": job["final"],
                    "result_ready": job["result_ready"],
                    "summary": (job.get("progress") or {}).get("summary"),
                    "last_digest_at": (latest_digest or {}).get("at"),
                    "digest_summary": progress.digest_line(latest_digest),
                    "result_path": job["paths"]["result"],
                    "status_path": job["paths"]["status"],
                }
            )
            if len(jobs) >= limit:
                break
        return {
            "ok": True,
            "jobs": jobs,
            "count": len(jobs),
            "limit": limit,
            "unreadable": unreadable[:limit],
        }

    # ----------------------------------------------------- progress digests
    def worker_progress(
        self, job_id: str | None = None, since: str | None = None
    ) -> dict[str, Any]:
        """Model-free supervisor digests, newest first.

        With no job_id, every *running* job is included.  These records are
        written by the supervisor on its own timer; nothing here asks the
        worker anything or touches its conversation.
        """
        since_at = _since_datetime(since)
        if job_id is not None:
            _job, job_dir = self._load_job(job_id)
            targets = [(job_id, job_dir)]
        else:
            targets = []
            try:
                entries = sorted(
                    self.config.jobs_dir.iterdir(), key=lambda p: p.name, reverse=True
                )
            except OSError:
                entries = []
            for entry in entries:
                if not entry.is_dir() or not valid_job_id(entry.name):
                    continue
                status, _error = read_json_bounded(entry / "status.json")
                if isinstance(status, dict) and status.get("phase") in ACTIVE_PHASES:
                    targets.append((entry.name, entry))
        digests: list[dict[str, Any]] = []
        for jid, jdir in targets:
            for record in progress.read_digests(jdir, limit=progress.MAX_DIGESTS):
                at = parse_iso(record.get("at"))
                if since_at is not None and (at is None or at < since_at):
                    continue
                digests.append(record)
        digests.sort(key=lambda record: str(record.get("at") or ""), reverse=True)
        return {
            "ok": True,
            "job_id": job_id,
            "since": iso(since_at) if since_at is not None else None,
            "count": len(digests),
            "digests": digests,
            "jobs_scanned": [jid for jid, _jdir in targets],
            "note": (
                "digests are written by the supervisor every "
                "progress_interval_seconds (0 disables them); they are computed "
                "from the event stream and never delivered to the worker"
            ),
        }

    # ------------------------------------------------------------ merge queue
    def _merge_lock(self) -> Path:
        return self.config.locks_dir / MERGE_LOCK_NAME

    def _job_branch(self, job: dict[str, Any]) -> str:
        worktree = job.get("worktree")
        if not isinstance(worktree, dict) or not worktree.get("enabled") or not worktree.get("branch"):
            raise PluginError(
                "not_a_worktree_job",
                "merge_worker only merges jobs started with use_worktree=true",
            )
        return str(worktree["branch"])

    def _merge_test_cmd(self, value: Any) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > MAX_TEST_CMD_CHARS
            or "\x00" in value
        ):
            raise PluginError(
                "test_cmd_invalid",
                f"test_cmd must be a non-empty command of at most {MAX_TEST_CMD_CHARS} chars",
            )
        return value.strip()

    def _default_test_command(self, repo: Path) -> list[str]:
        directories = [name for name in ("reality_engine", "plugins") if (repo / name).is_dir()]
        if not directories:
            return [sys.executable, "-c", "print('no source directories to compile')"]
        return [sys.executable, "-m", "compileall", "-q", *directories]

    def _run_merge_tests(self, repo: Path, command: str | list[str] | None) -> dict[str, Any]:
        shell = isinstance(command, str)
        args: Any = command if shell else (command or self._default_test_command(repo))
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                args,
                cwd=str(repo),
                shell=shell,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=1800,
                creationflags=procutil.hidden_creationflags(),
            )
            exit_code: int | None = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = None
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        except OSError as exc:
            return {
                "passed": False,
                "exit_code": None,
                "timed_out": False,
                "command": args if isinstance(args, str) else " ".join(args),
                "duration_seconds": round(time.monotonic() - started, 2),
                "stdout_tail": "",
                "stderr_tail": f"{type(exc).__name__}: {exc}"[:4000],
            }
        return {
            "passed": exit_code == 0 and not timed_out,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "command": args if isinstance(args, str) else " ".join(args),
            "duration_seconds": round(time.monotonic() - started, 2),
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
        }

    def merge_worker(
        self,
        job_id: str,
        target: str = "main",
        run_tests: bool = True,
        test_cmd: str | None = None,
    ) -> dict[str, Any]:
        """Merge one finished worktree branch into ``target`` under a queue lock."""
        if not isinstance(target, str) or not target.strip() or len(target) > 200 or "\x00" in target:
            raise PluginError("target_invalid", "target must be a local branch name")
        if not isinstance(run_tests, bool):
            raise PluginError("run_tests_invalid", "run_tests must be true or false")
        command = self._merge_test_cmd(test_cmd)
        job, _job_dir = self._load_job(job_id)
        branch = self._job_branch(job)
        status = self.get_status(job_id)
        if status["running"]:
            raise PluginError(
                "job_running",
                "the job is still running; merge only after it finishes",
                phase=status["phase"],
            )
        try:
            with exclusive_lock(self._merge_lock(), timeout=5.0):
                return self._merge_locked(
                    job, job_id, branch, target.strip(), run_tests, command
                )
        except TimeoutError as exc:
            raise PluginError(
                "merge_busy",
                "another merge is in progress under the repo-wide merge lock",
                lock_path=str(self._merge_lock()),
            ) from exc

    def _merge_locked(
        self,
        job: dict[str, Any],
        job_id: str,
        branch: str,
        target: str,
        run_tests: bool,
        test_cmd: str | None,
    ) -> dict[str, Any]:
        repo = self.config.repo_root
        target_head = gitutil.rev_parse(repo, target)
        if target_head is None:
            raise PluginError("target_not_found", f"target {target!r} is not a commit", target=target)
        branch_head = gitutil.rev_parse(repo, branch)
        if branch_head is None:
            raise PluginError("branch_not_found", f"branch {branch!r} does not exist", branch=branch)
        current = gitutil.current_branch(repo)
        if current != target:
            raise PluginError(
                "target_not_checked_out",
                f"the main checkout is on {current!r}; check out {target!r} before merging",
                current_branch=current,
                target=target,
            )
        if gitutil.merge_in_progress(repo):
            raise PluginError(
                "merge_in_progress",
                "the main checkout already has an unfinished merge",
            )
        base = gitutil.merge_base(repo, target, branch)
        if base is None:
            raise PluginError(
                "unrelated_histories", "the branch and target share no merge base"
            )
        common = {
            "job_id": job_id,
            "target": target,
            "branch": branch,
            "pre_head": target_head,
            "branch_head": branch_head,
            "mergiraf_available": gitutil.mergiraf_path(self.config.environ) is not None,
        }
        if gitutil.is_ancestor(repo, branch_head, target_head) or branch_head == target_head:
            return {
                **common,
                "ok": True,
                "merged": False,
                "outcome": "already_merged",
                "head": target_head,
                "tests": None,
                "pushed": False,
            }
        touched = set(gitutil.changed_paths(repo, f"{base}..{branch_head}"))
        try:
            tracked_dirty, untracked = gitutil.status_paths(repo)
        except gitutil.GitError as exc:
            raise PluginError("target_status_failed", str(exc)) from exc
        overlap = sorted(touched & (tracked_dirty | untracked))
        if overlap:
            raise PluginError(
                "target_dirty",
                "the target checkout has local changes to files this branch touches",
                files=overlap,
                dirty_paths=sorted(tracked_dirty | untracked)[:200],
            )
        if tracked_dirty:
            # A rollback uses ``reset --hard``; refuse unrelated tracked changes
            # rather than destroy work that is not ours.
            raise PluginError(
                "target_dirty",
                "the target checkout has unrelated local tracked changes; commit or "
                "move them before merging (the queue will never stash or reset them)",
                files=sorted(tracked_dirty)[:200],
            )
        mergiraf = gitutil.mergiraf_path(self.config.environ)
        attributes_file: Path | None = None
        if mergiraf:
            attributes_file = self.config.locks_dir / "mergiraf.attributes"
            atomic_write_text(attributes_file, "* merge=mergiraf\n")
        message = f"Merge {branch} [dsh {job_id}]\n\nDSH-Job: {job_id}"
        code, out, err = gitutil.merge_no_ff(
            repo, branch, message, mergiraf=mergiraf, attributes_file=attributes_file
        )
        common["mergiraf_available"] = mergiraf is not None
        if code != 0:
            conflicted = gitutil.conflicted_paths(repo)
            if conflicted:
                hunks = {
                    path: gitutil.conflict_hunks(repo, path) for path in conflicted[:50]
                }
                aborted = gitutil.abort_merge(repo)
                post_head = gitutil.rev_parse(repo, "HEAD")
                try:
                    clean = not gitutil.status_paths(repo)[0]
                except gitutil.GitError:
                    clean = False
                return {
                    **common,
                    "ok": True,
                    "merged": False,
                    "outcome": "conflict",
                    "conflicted_files": conflicted,
                    "hunks": hunks,
                    "aborted": aborted,
                    "head": post_head,
                    "target_clean": bool(aborted and clean and post_head == target_head),
                    "tests": None,
                    "pushed": False,
                }
            return {
                **common,
                "ok": True,
                "merged": False,
                "outcome": "merge_failed",
                "detail": (err or out).strip()[-2000:],
                "head": gitutil.rev_parse(repo, "HEAD"),
                "tests": None,
                "pushed": False,
            }
        merge_head = gitutil.rev_parse(repo, "HEAD")
        tests = self._run_merge_tests(repo, test_cmd or job.get("test_cmd")) if run_tests else None
        if tests is not None and not tests["passed"]:
            rolled_back = gitutil.reset_hard(repo, target_head)
            post_head = gitutil.rev_parse(repo, "HEAD")
            try:
                clean = not gitutil.status_paths(repo)[0]
            except gitutil.GitError:
                clean = False
            return {
                **common,
                "ok": True,
                "merged": False,
                "outcome": "tests_failed",
                "head": post_head,
                "merge_commit": merge_head,
                "rolled_back": rolled_back,
                "target_clean": bool(rolled_back and clean and post_head == target_head),
                "tests": tests,
                "pushed": False,
            }
        changed = gitutil.changed_paths(repo, f"{target_head}..HEAD")
        return {
            **common,
            "ok": True,
            "merged": True,
            "outcome": "merged",
            "head": merge_head,
            "commits": gitutil.count_commits(repo, f"{target_head}..HEAD"),
            "files_changed": len(changed),
            "files_changed_paths": sorted(changed)[:200],
            "tests": tests,
            "pushed": False,
        }

    def remove_worktree(self, job_id: str, delete_branch: bool = False) -> dict[str, Any]:
        if not isinstance(delete_branch, bool):
            raise PluginError("delete_branch_invalid", "delete_branch must be true or false")
        job, _job_dir = self._load_job(job_id)
        worktree = job.get("worktree")
        if not isinstance(worktree, dict) or not worktree.get("enabled"):
            raise PluginError("not_a_worktree_job", "this job has no worktree to remove")
        status = self.get_status(job_id)
        if status["running"]:
            raise PluginError(
                "job_running", "refusing to remove a worktree while its worker runs",
                phase=status["phase"],
            )
        repo = self.config.repo_root
        path = Path(str(worktree.get("path")))
        branch = str(worktree.get("branch"))
        removed = True
        detail = "already_absent"
        if path.exists():
            removed, detail = gitutil.remove_worktree_path(repo, path)
            if not removed:
                raise PluginError(
                    "worktree_remove_failed",
                    "git refused to remove the worktree; commit or discard its changes first",
                    path=str(path),
                    detail=detail,
                )
        gitutil.remove_worktree_registration(repo)
        branch_deleted = False
        branch_error: str | None = None
        if delete_branch:
            if gitutil.rev_parse(repo, branch) is None:
                branch_deleted = True
            else:
                branch_deleted, branch_error = gitutil.delete_branch(repo, branch)
        return {
            "ok": True,
            "job_id": job_id,
            "worktree_removed": removed,
            "path": str(path),
            "branch": branch,
            "delete_branch": delete_branch,
            "branch_deleted": branch_deleted,
            "branch_error": branch_error,
        }

    def push(self, target: str = "main", confirm: bool = False) -> dict[str, Any]:
        if confirm is not True:
            return {
                "ok": False,
                "error": {
                    "code": "confirmation_required",
                    "message": (
                        "push is outward-facing; pass confirm=true only after Shivam's "
                        "explicit go-ahead"
                    ),
                },
                "destructive_hint": True,
                "target": target,
            }
        if not isinstance(target, str) or not target.strip() or len(target) > 200 or "\x00" in target:
            raise PluginError("target_invalid", "target must be a local branch name")
        repo = self.config.repo_root
        head = gitutil.rev_parse(repo, target)
        if head is None:
            raise PluginError("target_not_found", f"target {target!r} is not a commit")
        remote = gitutil.remote_url(repo, "origin")
        if remote is None:
            raise PluginError(
                "no_remote",
                "no 'origin' remote is configured for this repository; nothing was pushed",
            )
        code, out, err = gitutil.push_ref(repo, "origin", target)
        return {
            "ok": code == 0,
            "target": target,
            "head": head,
            "remote": remote,
            "pushed": code == 0,
            "output": (out or err).strip()[-2000:],
            "error": None
            if code == 0
            else {"code": "push_failed", "message": (err or out).strip()[-1000:]},
        }

    # ------------------------------------------------------------ data jobs
    def _jobs_registry(self) -> dict[str, Any]:
        path = self.config.jobs_file
        if not path.is_file():
            raise PluginError(
                "jobs_registry_missing",
                f"no data-job registry at {path}",
                recovery="Point DSH_WORKER_JOBS_FILE at a jobs.yaml file.",
            )
        try:
            return jobs.load_registry(path)
        except jobs.RegistryError as exc:
            raise PluginError("jobs_registry_invalid", str(exc), path=str(path)) from exc

    def _job_entry(self, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        registry = self._jobs_registry()
        if not isinstance(name, str) or name not in registry["jobs"]:
            raise PluginError(
                "job_unknown",
                f"no data job named {name!r}",
                available=sorted(registry["jobs"])[:100],
            )
        return registry, registry["jobs"][name]

    def _reservation_stale(self, reservation: dict[str, Any]) -> bool:
        """A reservation whose job already reached a final phase is replaceable.

        The supervisor drops its own reservation right after acquiring the real
        lock; one left by a job that failed before that point (or was cancelled)
        must not block the resource for this manager's lifetime.
        """
        job_id = reservation.get("job_id")
        if not isinstance(job_id, str) or not valid_job_id(job_id):
            return False
        try:
            status = self._read_status(self._job_dir(job_id))
        except PluginError:
            return False
        return str(status.get("phase") or "") in FINAL_PHASES

    def _reserve_resource_locks(self, names: list[str], job_id: str) -> list[str]:
        """Reserve ``names`` for ``job_id`` and return the ones already busy.

        The old pre-check took and instantly released each OS lock, so two
        simultaneous starts both passed and the loser only failed after its
        supervisor launched.  A reservation record closes that window: it is
        written before the supervisor is spawned and removed by the supervisor
        after it holds the real kernel lock.  A stale reservation (dead owner or
        a job that already finished) is replaced; an unverifiable one fails
        closed.
        """
        if not names:
            return []
        self.config.locks_dir.mkdir(parents=True, exist_ok=True)
        owner = {
            "job_id": job_id,
            "pid": os.getpid(),
            "creation_time": procutil.process_creation_time(os.getpid()),
            "created_at": iso(),
        }
        busy: list[str] = []
        with exclusive_lock(self.config.locks_dir / RESOURCE_GUARD_NAME):
            for name in names:
                reservation = resource_reservation_path(self.config.locks_dir, name)
                existing, _error = read_json_bounded(reservation, 65_536)
                if isinstance(existing, dict):
                    pid = _as_pid(existing.get("pid"))
                    ticks = _as_pid(existing.get("creation_time"))
                    alive = pid is not None and (
                        ticks is None or procutil.process_alive(pid, ticks)
                    )
                    if alive and not self._reservation_stale(existing):
                        busy.append(name)
                        continue
                handle = try_lock_file(resource_lock_path(self.config.locks_dir, name))
                if handle is None:
                    busy.append(name)
                    continue
                handle.release()
                try:
                    atomic_write_json(reservation, {**owner, "name": name})
                except OSError:
                    # No reservation written: treat the name as busy instead of
                    # leaving a start that nobody reserved.
                    busy.append(name)
        if busy:
            self._release_resource_reservations(job_id)
        return busy

    def _release_resource_reservations(self, job_id: str) -> None:
        """Drop every start-window reservation this job still owns."""
        directory = self.config.locks_dir / RESOURCE_LOCK_DIR
        try:
            with exclusive_lock(self.config.locks_dir / RESOURCE_GUARD_NAME):
                for path in directory.glob("*.reserve"):
                    value, _error = read_json_bounded(path, 65_536)
                    if isinstance(value, dict) and value.get("job_id") == job_id:
                        try:
                            path.unlink()
                        except OSError:
                            pass
        except OSError:
            pass

    def _data_job_cwd(self, cwd: str, name: str) -> Path:
        path = Path(cwd).expanduser()
        if not path.is_absolute():
            path = self.config.repo_root / path
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PluginError(
                "job_cwd_invalid", f"data job {name!r} cwd cannot be resolved: {exc}"
            ) from exc
        if not _within(self.config.repo_root, resolved) or not resolved.is_dir():
            raise PluginError(
                "job_cwd_invalid", f"data job {name!r} cwd must be a directory inside the repo"
            )
        return resolved

    def _resolve_job_argv(
        self,
        entry: dict[str, Any],
        extra: list[str],
        now: datetime,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> list[str]:
        argv = jobs.expand_argv(
            entry,
            extra,
            self.config.repo_root,
            self.config.data_root,
            now,
            start=window_start,
            end=window_end,
        )
        if argv and argv[0].lower() in ("python", "python.exe"):
            argv[0] = sys.executable
        return argv

    def list_jobs(self) -> dict[str, Any]:
        registry = self._jobs_registry()
        history = jobs.run_history(self.config.jobs_dir)
        deadline = time.monotonic() + JOBS_CHECK_DEADLINE_SECONDS
        items: list[dict[str, Any]] = []
        for name in registry["order"]:
            entry = registry["jobs"][name]
            history_entry = history.get(name) or {}
            latest = history_entry.get("latest")
            last_success = history_entry.get("last_success")
            check = entry.get("success_check")
            freshness: dict[str, Any] | None = None
            if check is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0.05:
                    freshness = {
                        "available": False,
                        "ok": False,
                        "error": "freshness_check_deadline_exceeded",
                    }
                else:
                    freshness = jobs.run_success_check(
                        check,
                        self.config.data_root,
                        timeout=min(2.0, remaining),
                        repo_root=self.config.repo_root,
                    )
            max_age = jobs.cadence_max_age_days(entry)
            success_age = jobs.last_success_age_days(last_success)
            reasons: list[str] = []
            if latest is None:
                reasons.append("never_ran")
            if max_age is not None and success_age is not None and success_age > max_age:
                reasons.append(
                    f"last_success_{success_age:.1f}d_old (cadence {entry['cadence']})"
                )
            if freshness is not None and not freshness.get("ok"):
                reasons.append("freshness_check_failed")
            items.append(
                {
                    "name": name,
                    "description": entry["description"],
                    "enabled": entry["enabled"],
                    "cadence": entry["cadence"],
                    "needs_paid_api": entry["needs_paid_api"],
                    "needs_gpu": entry["needs_gpu"],
                    "resource_locks": entry["resource_locks"],
                    "writes": entry["writes"],
                    "off_peak_only": entry["off_peak_only"],
                    "market_hours": entry.get("market_hours", "any"),
                    "argv": entry["argv"],
                    "cwd": entry["cwd"],
                    "success_check": check,
                    "last_run": latest,
                    "last_success": last_success,
                    "last_success_age_days": round(success_age, 1) if success_age is not None else None,
                    "run_count_seen": history_entry.get("runs", 0),
                    "never_ran": latest is None,
                    "running": bool(latest and not latest.get("final")),
                    "freshness": freshness,
                    "stale": bool(reasons),
                    "stale_reasons": reasons,
                }
            )
        return {
            "ok": True,
            "schema": registry["schema"],
            "registry": registry["path"],
            "generated_at": iso(),
            "count": len(items),
            "jobs": items,
        }

    def start_job(
        self,
        name: str,
        args: list[str] | None = None,
        confirm: bool = False,
        progress_interval_seconds: int = DEFAULT_PROGRESS_INTERVAL_SECONDS,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(confirm, bool):
            raise PluginError("confirm_invalid", "confirm must be true or false")
        progress_interval_seconds = _progress_interval(progress_interval_seconds)
        for label, value in (("window_start", window_start), ("window_end", window_end)):
            if value is None:
                continue
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise PluginError("window_invalid", f"{label} must be a YYYY-MM-DD date")
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise PluginError(
                    "window_invalid", f"{label} must be a real YYYY-MM-DD date"
                ) from exc
        _registry, entry = self._job_entry(name)
        if not entry["enabled"] and not confirm:
            raise PluginError(
                "job_disabled",
                f"data job {name!r} is disabled; re-enable only on Shivam's word, or "
                "pass confirm=true for an explicit one-off run",
                name=name,
            )
        now = self.config.now()
        if not confirm:
            if entry["off_peak_only"] and is_peak(now):
                raise PluginError(
                    "off_peak_hours",
                    f"data job {name!r} is off-peak-only (Mon-Fri 06:30-09:30 and "
                    "11:30-15:30 IST); pass confirm=true to override deliberately",
                    name=name,
                )
            if entry.get("market_hours") == "avoid_market" and _market_session(now):
                raise PluginError(
                    "market_hours",
                    f"data job {name!r} does not start between 09:15 and 15:30 IST on weekdays",
                    name=name,
                )
        extra: list[str] = []
        if args is not None:
            if (
                not isinstance(args, list)
                or len(args) > 100
                or not all(
                    isinstance(arg, str) and arg and "\x00" not in arg and len(arg) <= 2000
                    for arg in args
                )
            ):
                raise PluginError(
                    "args_invalid", "args must be a list of at most 100 non-empty strings"
                )
            extra = list(args)
        cwd = self._data_job_cwd(entry["cwd"], name)
        argv = self._resolve_job_argv(entry, extra, now, window_start, window_end)
        locks = list(entry.get("resource_locks") or [])
        job_id = new_job_id()
        busy = self._reserve_resource_locks(locks, job_id)
        if busy:
            raise PluginError(
                "resource_busy",
                f"data job {name!r} needs resource locks that are already held",
                name=name,
                resource_locks=busy,
            )
        job_dir = self.config.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        paths = self._job_paths(job_id)
        owner_id = secrets.token_hex(16)
        try:
            job = {
                "schema": 1,
                "job_id": job_id,
                "kind": "data_job",
                "created_at": iso(now),
                "repo_root": str(self.config.repo_root),
                "plugin_root": str(self.config.plugin_root),
                "workspace": str(self.config.repo_root),
                "permission": "workspace-write",
                "owner_session": self.config.session_label,
                "controller_lease_owner_id": owner_id,
                "data_job": {
                    "name": name,
                    "description": entry["description"],
                    "cadence": entry["cadence"],
                    "resource_locks": locks,
                    "writes": entry["writes"],
                    "success_check": entry.get("success_check"),
                    "needs_paid_api": entry["needs_paid_api"],
                    "needs_gpu": entry["needs_gpu"],
                    "enabled": entry["enabled"],
                    "confirm_override": bool(confirm and not entry["enabled"]),
                },
                "env": dict(entry.get("env") or {}),
                "resource_locks": locks,
                "progress_interval_seconds": progress_interval_seconds,
                "heartbeat": {},
                "launcher": {
                    "command": argv,
                    "cwd": str(cwd),
                    "argv": argv,
                    "capabilities": {},
                },
                "paths": paths,
                "limits": {
                    "max_output_tokens": None,
                    "max_result_bytes": DEFAULT_RESULT_BYTES,
                    "hard_timeout_seconds": None,
                    "hard_timeout_kind": "none",
                    "followup_wait_seconds": 0,
                    "controller_lease_seconds": 7200,
                    "brief_bytes": 0,
                },
                "warnings": [],
            }
            atomic_write_json_locked(job_dir / "job.json", job, self._job_lock(job_dir))
            lease_now = utc_now()
            lease = {
                "schema": LEASE_SCHEMA,
                "job_id": job_id,
                "owner_id": owner_id,
                "owner_pid": os.getpid(),
                "owner_session": self.config.session_label,
                "created_at": iso(lease_now),
                "renewed_at": iso(lease_now),
                "deadline": iso(lease_now + timedelta(seconds=7200)),
                "lease_seconds": 7200,
                "renewals": 0,
            }
            atomic_write_json_locked(job_dir / LEASE_FILE, lease, self._job_lock(job_dir))
            self._lease_owners[job_id] = owner_id
            initial_status = {
                "schema": 1,
                "job_id": job_id,
                "kind": "data_job",
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
                "heartbeat": {},
                "controller_lease": read_lease(job_dir / LEASE_FILE)[0],
                "resource_locks": locks,
                "warnings": [],
            }
            atomic_write_json_locked(
                job_dir / "status.json", initial_status, self._job_lock(job_dir)
            )
            self._steer(
                job_dir,
                "start",
                f"data_job={name} locks={','.join(locks) or '-'} "
                f"{'confirm=true' if confirm else ''}",
            )
            supervisor_pid = self._spawn_supervisor(job_dir, None)
            status = self._wait_for_start(job_dir, supervisor_pid)
            if str(status.get("phase") or "") in FINAL_PHASES:
                self._release_resource_reservations(job_id)
            return {
                "ok": True,
                "job_id": job_id,
                "run_id": job_id,
                "name": name,
                "phase": status.get("phase", "starting"),
                "argv": argv,
                "cwd": str(cwd),
                "resource_locks": locks,
                "status_path": paths["status"],
                "result_path": paths["result"],
                "stdout_path": paths["stdout_log"],
                "stderr_path": paths["stderr_log"],
                "supervisor_log_path": paths["supervisor_log"],
                "session_label": self.config.session_label,
                "owner_session": self.config.session_label,
                "progress_interval_seconds": progress_interval_seconds,
                "progress_path": paths["progress"],
                "progress_md_path": paths["progress_md"],
                "warnings": list(status.get("warnings") or []),
            }
        except Exception:
            self._release_resource_reservations(job_id)
            self._lease_owners.pop(job_id, None)
            if not (job_dir / "job.json").exists():
                try:
                    atomic_write_json(
                        job_dir / "job.json",
                        {
                            "schema": 1,
                            "job_id": job_id,
                            "kind": "data_job",
                            "created_at": iso(now),
                            "workspace": str(self.config.repo_root),
                            "start_failed": True,
                        },
                    )
                except OSError:
                    pass
            raise

    def job_log(self, run_id: str, tail: int = 200) -> dict[str, Any]:
        if not isinstance(tail, int) or not 1 <= tail <= MAX_JOB_LOG_LINES:
            raise PluginError("tail_invalid", f"tail must be 1..{MAX_JOB_LOG_LINES}")
        if not isinstance(run_id, str) or not run_id.strip():
            raise PluginError("run_id_invalid", "run_id must be a job id or data-job name")
        found = jobs.find_run(self.config.jobs_dir, run_id.strip())
        if found is None:
            raise PluginError("run_not_found", f"no run matched {run_id!r}")
        job_dir, job = found

        def last_lines(path: Path) -> list[str]:
            text = read_text_bounded_tail(path, MAX_JOB_LOG_BYTES)
            return text.splitlines()[-tail:]

        status = self._read_status(job_dir)
        data_job = job.get("data_job") if isinstance(job.get("data_job"), dict) else {}
        return {
            "ok": True,
            "run_id": str(job.get("job_id") or job_dir.name),
            "name": data_job.get("name"),
            "phase": status.get("phase"),
            "final": status.get("phase") in FINAL_PHASES,
            "exit_code": status.get("exit_code"),
            "outcome": status.get("outcome"),
            "stdout": last_lines(job_dir / "stdout.log"),
            "stderr": last_lines(job_dir / "stderr.log"),
            "supervisor": last_lines(job_dir / "supervisor.log"),
            "tail": tail,
            "paths": {
                "job_dir": str(job_dir),
                "stdout": str(job_dir / "stdout.log"),
                "stderr": str(job_dir / "stderr.log"),
                "status": str(job_dir / "status.json"),
            },
        }


def _market_session(now: datetime | None = None) -> bool:
    """True on weekdays 09:15-15:30 IST (the cash-market session)."""
    local = (now or datetime.now(timezone.utc)).astimezone(IST)
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    return 9 * 60 + 15 <= minutes < 15 * 60 + 30
