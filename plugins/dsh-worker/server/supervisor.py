"""Detached supervisor for one dsh job.

Started hidden by the MCP server and intentionally independent of it: the
supervisor owns the launcher process, writes the persisted status, and keeps a
Windows job object with ``KILL_ON_JOB_CLOSE`` so a dead supervisor cannot leave
an unowned writer behind.  It never calls a model and never copies reasoning
stderr into the result.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gitutil
import heartbeat
import procutil
import progress
from store import (
    JOB_LOCK_NAME,
    LEASE_FILE,
    acquire_lock_file,
    atomic_write_json,
    drop_resource_reservation,
    exclusive_lock,
    iso,
    parse_iso,
    read_json_bounded,
    read_lease,
    read_text_bounded,
    resource_lock_path,
    workspace_lock_name,
    utc_now,
)

_CANCEL = False


def _on_signal(_signum, _frame) -> None:
    global _CANCEL
    _CANCEL = True


def _log(message: str) -> None:
    print(f"{iso()} supervisor: {message}", flush=True)


def _status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def _write_status(job_dir: Path, status: dict[str, Any]) -> None:
    status["updated_at"] = iso()
    # Every job-record write is serialised with other server/supervisor
    # processes by the per-job OS lock; the file replace itself stays atomic.
    with exclusive_lock(job_dir / JOB_LOCK_NAME):
        atomic_write_json(_status_path(job_dir), status)


def _write_status_soft(job_dir: Path, status: dict[str, Any]) -> bool:
    """Periodic status write that never kills a healthy worker.

    A status file locked by antivirus/indexer for longer than the atomic
    write's retry window, or a momentarily full disk, used to raise out of the
    poll loop into the generic handler, which killed the worker.  A stale
    status record is far cheaper than a lost multi-hour run: log and retry on
    the next poll.
    """
    try:
        _write_status(job_dir, status)
        return True
    except (OSError, TimeoutError) as exc:
        _log(f"status write failed ({type(exc).__name__}: {exc}); will retry")
        return False


def _write_status_final(job_dir: Path, status: dict[str, Any], attempts: int = 30) -> None:
    """Final status must land; retry for up to ~30 s before giving up."""
    for attempt in range(attempts):
        if _write_status_soft(job_dir, status):
            return
        time.sleep(1.0)
    _write_status(job_dir, status)


def _release_lock(
    job_dir: Path,
    job: dict[str, Any],
    status: dict[str, Any],
) -> bool:
    """Release the repository mutation lock only when no worker is alive.

    A supervisor crash can leave the worker in the job object briefly, and a
    cancelled run can survive taskkill.  Releasing the lock in either case would
    admit a second writer into the same checkout, so hold it until the recorded
    worker is proven dead (or its creation time proves the PID was recycled).
    """
    worker_pid = status.get("worker_pid")
    worker_ticks = status.get("worker_creation_time")
    if worker_pid:
        if not worker_ticks:
            _log("retaining workspace lock: recorded worker has no verifiable creation time")
            return False
        if procutil.process_alive(int(worker_pid), int(worker_ticks)):
            _log(f"retaining workspace lock: worker pid={worker_pid} is still alive")
            return False
    runtime = job_dir.parents[1]
    repo_root = Path(str(job.get("repo_root") or job_dir))
    workspace = Path(str(job.get("workspace") or repo_root))
    path = runtime / "locks" / workspace_lock_name(workspace, repo_root)
    with exclusive_lock(runtime / "locks" / ".mutation.guard"):
        lock, _ = read_json_bounded(path, 65_536)
        if isinstance(lock, dict) and lock.get("job_id") == job.get("job_id"):
            try:
                path.unlink()
            except FileNotFoundError:
                return True
            except OSError:
                return False
            return True
    # Not held by this job (read-only jobs never take it, or it was already
    # released): nothing is retained.  Returning False here used to append a
    # false "lock retained" warning to every read-only job.
    return True


def _containment_error(job: dict[str, Any]) -> str | None:
    """Return why a mutating job must not run on Windows, if any.

    Read-only work may proceed without containment.  Mutating work fails closed:
    an uncontrolled orphan writer is worse than a refused start.
    """
    if os.name != "nt":
        return None
    if job.get("permission") == "read-only":
        return None
    return (
        "Windows job-object containment is unavailable; refusing to run a mutating "
        "job that could leave an unowned writer behind. Check job_object status and "
        "restart the supervisor on a supported Windows host."
    )


def _progress_interval(job: dict[str, Any]) -> int:
    """Supervisor digest cadence; 0 (or a legacy/invalid record) disables it."""
    try:
        value = int(job.get("progress_interval_seconds"))
    except (TypeError, ValueError):
        return 0
    return value if 0 <= value <= 86_400 else 0


def _last_activity(
    job_dir: Path, job: dict[str, Any], status: dict[str, Any]
) -> datetime | None:
    """Committed worker activity only; log/status mtimes are supervision health.

    A data job publishes no heartbeat, so its stdout/stderr mtime is the only
    activity signal it has (the pane makes the same allowance).
    """
    candidates: list[datetime] = []
    parsed = parse_iso(status.get("worker_activity_at"))
    if parsed:
        candidates.append(parsed)
    if job.get("kind") == "data_job":
        for name in ("stdout.log", "stderr.log"):
            try:
                mtime = (job_dir / name).stat().st_mtime
            except OSError:
                continue
            candidates.append(datetime.fromtimestamp(mtime, timezone.utc))
    if not candidates:
        parsed = parse_iso(status.get("started_at"))
        if parsed:
            candidates.append(parsed)
    return max(candidates) if candidates else None


def _lease_remaining(status: dict[str, Any]) -> float | None:
    lease = status.get("controller_lease")
    value = lease.get("remaining_seconds") if isinstance(lease, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def _emit_digest(
    writer: progress.DigestWriter,
    job_dir: Path,
    job: dict[str, Any],
    status: dict[str, Any],
    *,
    final: bool = False,
) -> None:
    """A digest failure is logged, never fatal: a lost update beats a lost run."""
    try:
        writer.tick(
            phase=str(status.get("phase") or "running"),
            last_activity=_last_activity(job_dir, job, status),
            lease_remaining=_lease_remaining(status),
            final=final,
            first_edit={
                "tool_calls_before_first_edit": status.get("tool_calls_before_first_edit"),
                "orientation_seconds": status.get("orientation_seconds"),
            },
        )
    except Exception as exc:  # noqa: BLE001 - a digest bug must never kill a run
        _log(f"progress digest failed ({type(exc).__name__}: {exc}); will retry")


AUX_POLL_SECONDS = 2.0
MAX_REQUEST_BYTES = 65_536
MAX_DETACHED_ENV = 20
# Request history is bounded so a worker hammering the channels cannot grow
# status.json without limit; the newest entries are the useful ones.
MAX_REQUEST_HISTORY = 50
_SAFE_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _append_history(status: dict[str, Any], key: str, entry: dict[str, Any]) -> None:
    history = status.get(key)
    history = list(history) if isinstance(history, list) else []
    history.append(entry)
    status[key] = history[-MAX_REQUEST_HISTORY:]


def _workspace(job: dict[str, Any], job_dir: Path) -> Path:
    return Path(str(job.get("workspace") or job.get("repo_root") or job_dir))


def _tmp_dir(job: dict[str, Any], job_dir: Path) -> Path:
    return _workspace(job, job_dir) / ".tmp"


class _Orientation:
    """First-edit metric from the event stream.

    The dsh event stream carries no timestamps, so the first poll that sees a
    write/edit tool call stamps the wall clock.  Accuracy is the poll gap
    (``AUX_POLL_SECONDS``), which is the best a replay-free supervisor can do.
    """

    def __init__(self, events_path: Path, started_at: Any) -> None:
        self._scanner = progress.EventScanner()
        self._events_path = events_path
        self.started_at = parse_iso(started_at)
        self.calls_before_first_edit: int | None = None
        self.first_edit_at: datetime | None = None

    def poll(self) -> None:
        if self.first_edit_at is not None:
            return
        summary = self._scanner.scan(self._events_path)
        before = (
            summary.get("tool_calls_before_first_edit")
            if summary.get("available")
            else None
        )
        if before is None:
            return
        self.calls_before_first_edit = int(before)
        self.first_edit_at = utc_now()

    def apply(self, status: dict[str, Any]) -> None:
        if self.calls_before_first_edit is not None:
            status["tool_calls_before_first_edit"] = self.calls_before_first_edit
        if self.first_edit_at is not None:
            status["first_edit_at"] = iso(self.first_edit_at)
            if self.started_at is not None:
                status["orientation_seconds"] = round(
                    max(0.0, (self.first_edit_at - self.started_at).total_seconds()), 1
                )


def _read_request(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")[:MAX_REQUEST_BYTES]
    except FileNotFoundError:
        return None
    except OSError as exc:
        return {"_error": f"request_unreadable:{type(exc).__name__}"}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {"_error": "request_not_json"}
    return value if isinstance(value, dict) else {"_error": "request_not_object"}


def _finish_request(request: Path, result_path: Path, result: dict[str, Any]) -> None:
    result["at"] = iso()
    try:
        atomic_write_json(result_path, result)
    except OSError:
        pass
    try:
        request.unlink(missing_ok=True)
    except OSError:
        pass


def _handle_commit_request(
    job: dict[str, Any], job_dir: Path, status: dict[str, Any], tmp: Path
) -> None:
    """Worker-requested ``git commit`` (the worktree index is outside the sandbox).

    The worker writes ``.tmp/commit.request.json`` (``{"message": "..."}``); the
    supervisor, which is not sandboxed, runs the commit and writes
    ``.tmp/commit.result.json``.  The commit target comes ONLY from the git
    identity the manager captured in the job record before the worker started:
    the worker-writable ``<workspace>/.git`` is never consulted for the git
    dir, hooks are disabled, and only the job's own ``dsh/...`` branch is
    accepted.  The main checkout is never a commit target.
    """
    request = _read_request(tmp / "commit.request.json")
    if request is None:
        return
    result_path = tmp / "commit.result.json"
    error = request.get("_error")
    worktree = job.get("worktree") if isinstance(job.get("worktree"), dict) else {}
    workspace = _workspace(job, job_dir)
    identity = job.get("git") if isinstance(job.get("git"), dict) else None
    base_commit: str | None = None
    result: dict[str, Any]
    if error:
        result = {"ok": False, "error": error}
    elif identity is None:
        result = {
            "ok": False,
            "error": "commit_request_requires_worktree",
            "workspace": str(workspace),
        }
    else:
        if worktree.get("enabled"):
            target = Path(str(worktree.get("path")))
            base_commit = worktree.get("base_commit")
        else:
            # A job may point its workspace at an EXISTING worktree (not created
            # by use_worktree); the stored identity proves it is one and the
            # identity/tamper checks in commit_worktree run for both cases.
            target = workspace
        message = request.get("message")
        subject = (
            message.strip()[:200]
            if isinstance(message, str) and message.strip()
            else str(job.get("brief_first_line") or "dsh worker")[:200]
        )
        job_id = str(job.get("job_id") or job_dir.name)
        try:
            commit = gitutil.commit_worktree(
                target,
                job_id=job_id,
                subject=f"{subject} [dsh {job_id}]",
                base_commit=base_commit,
                git=identity,
                repo_root=job.get("repo_root"),
            )
            result = {
                "ok": bool(commit.get("committed")),
                "commit": commit,
                "reason": commit.get("reason"),
                "error": commit.get("error"),
            }
        except Exception as exc:  # noqa: BLE001 - report, never fail the run
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
    _finish_request(tmp / "commit.request.json", result_path, result)
    _append_history(
        status,
        "worker_commits",
        {"at": result["at"], "ok": bool(result.get("ok")), "error": result.get("error")},
    )
    _log(f"worker commit request: ok={result.get('ok')} error={result.get('error')}")


def _within_any(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _launch_detached(
    job: dict[str, Any], job_dir: Path, tmp: Path, request: dict[str, Any]
) -> dict[str, Any]:
    """Create a process outside the supervisor's job object via WMI.

    A normal child would die with the supervisor's KILL_ON_JOB_CLOSE job, so the
    only supported escape is ``Win32_Process.Create``: WmiPrvSE is the parent,
    not this process.  The request supplies ``cmd`` (string or argv list),
    optional ``log`` and optional ``env``.
    """
    cmd = request.get("cmd")
    if isinstance(cmd, list) and cmd and all(
        isinstance(part, str) and part and "\x00" not in part for part in cmd
    ):
        command_line = subprocess.list2cmdline(cmd)
    elif isinstance(cmd, str) and cmd.strip() and "\x00" not in cmd:
        command_line = cmd.strip()
    else:
        return {"ok": False, "error": "cmd_must_be_a_string_or_argv_list"}
    if len(command_line) > 4000:
        return {"ok": False, "error": "cmd_too_long"}

    workspace = _workspace(job, job_dir)
    data_root = Path(str(job.get("data_root") or workspace))
    roots = [tmp, workspace, data_root, Path("D:/RealityEngine")]
    log_value = request.get("log")
    log_path = Path(str(log_value)) if isinstance(log_value, str) and log_value.strip() else (
        tmp / f"detached-{int(time.time() * 1000)}.log"
    )
    if not log_path.is_absolute():
        log_path = tmp / log_path
    try:
        log_path = log_path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"ok": False, "error": f"log_invalid:{type(exc).__name__}"}
    if not _within_any(log_path, [root.resolve(strict=False) for root in roots]):
        return {"ok": False, "error": "log_outside_allowed_roots"}

    cwd_value = request.get("cwd")
    cwd = Path(str(cwd_value)) if isinstance(cwd_value, str) and cwd_value.strip() else workspace
    if not cwd.is_absolute():
        cwd = workspace / cwd
    try:
        cwd = cwd.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return {"ok": False, "error": "cwd_missing"}
    if not cwd.is_dir() or not _within_any(cwd, [root.resolve(strict=False) for root in roots]):
        return {"ok": False, "error": "cwd_outside_allowed_roots"}

    env_lines: list[str] = []
    extra_env = request.get("env")
    if isinstance(extra_env, dict):
        if len(extra_env) > MAX_DETACHED_ENV:
            return {"ok": False, "error": "env_too_many_keys"}
        for key, value in extra_env.items():
            if (
                not isinstance(key, str)
                or not _SAFE_ENV_KEY.match(key)
                or not isinstance(value, str)
                or "\x00" in value
                or "\r" in value
                or "\n" in value
                or len(value) > 2000
            ):
                return {"ok": False, "error": "env_invalid"}
            env_lines.append(f'set "{key}={value}"')

    log_path.parent.mkdir(parents=True, exist_ok=True)
    script = tmp / f"launch-{int(time.time() * 1000)}.cmd"
    body = "\r\n".join(
        [
            "@echo off",
            *env_lines,
            f'cd /d "{cwd}"',
            f'({command_line}) >> "{log_path}" 2>&1',
            "",
        ]
    )
    try:
        script.write_text(body, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"script_write_failed:{type(exc).__name__}"}

    shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
    ps = (
        "$ErrorActionPreference='Stop';"
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine=$env:DSH_DETACH_CMD; CurrentDirectory=$env:DSH_DETACH_CWD};"
        "[Console]::Out.Write(('{0}|{1}' -f $r.ReturnValue, $r.ProcessId))"
    )
    env = dict(os.environ)
    env["DSH_DETACH_CMD"] = f'cmd.exe /d /c "{script}"'
    env["DSH_DETACH_CWD"] = str(cwd)
    try:
        completed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", ps],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=procutil.hidden_creationflags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"wmi_unavailable:{type(exc).__name__}"}
    output = (completed.stdout or "").strip()
    parts = output.rsplit("|", 1)
    if completed.returncode != 0 or len(parts) != 2 or parts[0].strip() != "0":
        return {
            "ok": False,
            "error": f"wmi_create_failed:{(completed.stderr or output)[-300:]}",
        }
    return {
        "ok": True,
        "pid": int(parts[1]) if parts[1].isdigit() else None,
        "command": command_line[:2000],
        "log": str(log_path),
        "script": str(script),
    }


def _handle_launch_request(
    job: dict[str, Any], job_dir: Path, status: dict[str, Any], tmp: Path
) -> None:
    request = _read_request(tmp / "launch.request.json")
    if request is None:
        return
    result_path = tmp / "launch.result.json"
    if request.get("_error"):
        result: dict[str, Any] = {"ok": False, "error": request["_error"]}
    elif str(job.get("write_scope") or "workspace") not in ("data", "full"):
        result = {
            "ok": False,
            "error": "launch_detached_requires_write_scope_data_or_full",
        }
    else:
        result = _launch_detached(job, job_dir, tmp, request)
    _finish_request(tmp / "launch.request.json", result_path, result)
    _append_history(
        status,
        "detached",
        {
            "at": result["at"],
            "ok": bool(result.get("ok")),
            "pid": result.get("pid"),
            "log": result.get("log"),
            "error": result.get("error"),
        },
    )
    _log(f"worker launch request: ok={result.get('ok')} pid={result.get('pid')}")


def _poll_aux(job: dict[str, Any], job_dir: Path, status: dict[str, Any]) -> None:
    tmp = _tmp_dir(job, job_dir)
    try:
        _handle_commit_request(job, job_dir, status, tmp)
        _handle_launch_request(job, job_dir, status, tmp)
    except Exception as exc:  # noqa: BLE001 - a request bug must never kill a run
        _log(f"worker request failed ({type(exc).__name__}: {exc})")


def _create_status(job: dict[str, Any], job_dir: Path) -> dict[str, Any]:
    return {
        "schema": 1,
        "job_id": job.get("job_id"),
        "kind": job.get("kind") or "worker",
        "phase": "starting",
        "started_at": job.get("created_at") or iso(),
        "updated_at": iso(),
        "write_scope": job.get("write_scope") or "workspace",
        "writes": list(job.get("writes") or []),
        "write_roots": list(job.get("write_roots") or []),
        "approved_by": job.get("approved_by"),
        "confirm_repo_root_write": bool(job.get("confirm_repo_root_write")),
        "tmp_dir": None,
        "tool_calls_before_first_edit": None,
        "first_edit_at": None,
        "orientation_seconds": None,
        "worker_commits": [],
        "detached": [],
        "supervisor_pid": os.getpid(),
        "supervisor_creation_time": procutil.process_creation_time(os.getpid()),
        "worker_pid": None,
        "worker_creation_time": None,
        "worker_activity_at": None,
        "exit_code": None,
        "outcome": None,
        "error": None,
        "artifacts": None,
        "heartbeat": job.get("heartbeat") or {},
        "heartbeat_live": None,
        "job_object": None,
        "resource_locks": list(job.get("resource_locks") or []),
        "warnings": [],
    }


def _finalize(
    job: dict[str, Any],
    job_dir: Path,
    status: dict[str, Any],
    rc: int | None,
    cancel_requested: bool,
    extra_warnings: list[str] | None = None,
    lease_expired: bool = False,
) -> dict[str, Any]:
    warnings = list(status.get("warnings") or []) + list(extra_warnings or [])
    if cancel_requested:
        phase, outcome = "cancelled", "cancelled"
    elif lease_expired:
        phase, outcome = "failed", "controller_lease_expired"
    elif rc == 0:
        phase, outcome = "finished", "completed"
    elif rc == 124:
        phase, outcome = "failed", "timeout"
    elif rc == 125:
        phase, outcome = "failed", "heartbeat_stopped"
    elif rc == 126:
        phase, outcome = "failed", "control_unavailable"
    else:
        phase, outcome = "failed", "launcher_error"
    status.update(
        {
            "phase": phase,
            "outcome": outcome,
            "exit_code": rc,
            "finished_at": iso(),
            "updated_at": iso(),
            "cancel_requested": cancel_requested,
            "warnings": warnings,
        }
    )
    if phase == "failed":
        if lease_expired:
            status["error"] = (
                "controller lease expired or was missing/invalid; the supervisor "
                "terminated the owned process tree (controller_lease_expired)"
            )
        elif rc == 124:
            status["error"] = "launcher exited with hard-timeout code 124"
        elif rc == 125:
            status["error"] = (
                "launcher heartbeat stopped after the configured unanswered requests (exit 125)"
            )
        elif rc == 126:
            status["error"] = "launcher could not establish the heartbeat control channel (exit 126)"
        else:
            status["error"] = (
                "launcher exited nonzero; inspect the local launcher log for diagnostics"
            )
    elif phase == "finished":
        status["error"] = None
    try:
        if job.get("kind") == "data_job":
            # A data job is not attributed to working-tree edits.
            status["artifacts"] = {"available": False, "reason": "data_job"}
        else:
            baseline, _ = read_json_bounded(job_dir / "baseline.json", 1_048_576)
            # The snapshot runs only against the manager-captured identity; a
            # worker that rewrote .git cannot redirect it (and no git process
            # runs when the pointer no longer matches the stored git dir).
            final_snapshot = gitutil.snapshot(
                Path(str(job.get("workspace"))),
                identity=job.get("git"),
                repo_root=job.get("repo_root"),
            )
            status["artifacts"] = gitutil.changed_since(baseline, final_snapshot)
    except Exception as exc:  # artifact hints must never fail a job
        status["artifacts"] = {
            "available": False,
            "reason": f"artifact_snapshot_error:{type(exc).__name__}",
            "paths": [],
        }
    # Worktree auto-commit: the worker could not write .git/worktrees/<name>
    # (outside its sandbox), so the supervisor commits only after a successful
    # end.  Empty diffs create no commit; a failed commit is reported, never a
    # phase change.
    worktree = job.get("worktree")
    if isinstance(worktree, dict) and worktree.get("enabled"):
        if phase == "finished":
            subject = str(job.get("brief_first_line") or "").strip()
            if not subject:
                brief, _, _ = read_text_bounded(job_dir / "brief.md", 8192)
                subject = next((line.strip() for line in brief.splitlines() if line.strip()), "dsh worker")
            job_id = str(job.get("job_id") or job_dir.name)
            try:
                status["worktree_commit"] = gitutil.commit_worktree(
                    Path(str(worktree.get("path"))),
                    job_id=job_id,
                    subject=f"{subject[:200]} [dsh {job_id}]",
                    base_commit=worktree.get("base_commit"),
                    # The manager-captured identity is the only commit target;
                    # see _handle_commit_request.
                    git=job.get("git"),
                    repo_root=job.get("repo_root"),
                )
            except Exception as exc:
                status["worktree_commit"] = {
                    "committed": False,
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                }
            commit_error = (status.get("worktree_commit") or {}).get("error")
            if commit_error:
                warnings.append(f"worktree auto-commit failed: {commit_error}")
        else:
            status["worktree_commit"] = {
                "committed": False,
                "reason": f"worker ended {phase}; changes left uncommitted",
            }
    if phase != "finished":
        try:
            status["partial"] = (job_dir / "result.md").stat().st_size > 0
        except OSError:
            status["partial"] = False
    # A short job can finish between two aux polls; the final scan still gives
    # the call count (the wall-clock first-edit time is then unknowable).
    if (
        status.get("tool_calls_before_first_edit") is None
        and job.get("kind") != "data_job"
    ):
        try:
            summary = progress.EventScanner().scan(job_dir / "result.md.events.jsonl")
            if summary.get("available"):
                status["tool_calls_before_first_edit"] = summary.get(
                    "tool_calls_before_first_edit"
                )
        except Exception as exc:  # noqa: BLE001 - metric failure never fails a job
            status.setdefault("warnings", []).append(
                f"orientation_scan_failed:{type(exc).__name__}"
            )
    _write_status_final(job_dir, status)
    return status


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: supervisor.py <job_dir>", file=sys.stderr)
        return 2
    job_dir = Path(args[0]).resolve()
    job, error = read_json_bounded(job_dir / "job.json")
    if not isinstance(job, dict):
        _log(f"cannot read job record: {error}")
        return 2
    job_id = str(job.get("job_id") or "")
    if not job_id or job_dir.name != job_id:
        _log("job id does not match job directory")
        return 2
    status = _create_status(job, job_dir)
    lease_path = job_dir / LEASE_FILE
    lease_owner = job.get("controller_lease_owner_id")
    lease, lease_error = read_lease(
        lease_path,
        expected_job_id=job_id,
        expected_owner_id=lease_owner,
        max_seconds=7200,
    )
    if lease is None:
        status.update({
            "phase": "failed",
            "outcome": "controller_lease_invalid",
            "error": f"controller lease is missing or invalid ({lease_error}); refusing to run unsupervised",
            "finished_at": iso(),
        })
        _write_status(job_dir, status)
        _release_lock(job_dir, job, status)
        _log(f"refused job={job_id}: controller lease invalid ({lease_error})")
        return 1
    status["controller_lease"] = lease
    _write_status(job_dir, status)
    _log(f"start job={job_id}")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    args_argv = job.get("launcher", {}).get("argv")
    if not isinstance(args_argv, list) or not args_argv or not all(isinstance(x, str) for x in args_argv):
        status["phase"] = "failed"
        status["error"] = "job record has no valid launcher argv"
        _write_status(job_dir, status)
        _release_lock(job_dir, job, status)
        return 1

    # Named resource locks (db:<file>, gpu, net:<host>) are held for this
    # supervisor's whole lifetime by open OS byte-range locks, so they cannot go
    # stale: if this process dies, the kernel releases them.
    runtime_dir = job_dir.parents[1]
    locks_dir = runtime_dir / "locks"
    held_resource_locks: list[Any] = []
    for lock_name in job.get("resource_locks") or []:
        handle = acquire_lock_file(
            resource_lock_path(locks_dir, str(lock_name)), timeout=2.0
        )
        if handle is None:
            for held in held_resource_locks:
                held.release()
            # Drop this job's own reservation (the manager also cleans up if
            # the supervisor exits before the start call returns).
            drop_resource_reservation(locks_dir, str(lock_name), job_id)
            status.update(
                {
                    "phase": "failed",
                    "outcome": "resource_busy",
                    "error": (
                        f"resource lock {lock_name!r} is held by another job; "
                        "the worker was not started"
                    ),
                    "finished_at": iso(),
                }
            )
            _write_status(job_dir, status)
            _log(f"refused job={job_id}: resource lock {lock_name!r} is busy")
            return 1
        # The real kernel lock is held now: the manager's start-window
        # reservation for this name may go.
        drop_resource_reservation(locks_dir, str(lock_name), job_id)
        handle.write_record(
            {
                "name": str(lock_name),
                "job_id": job_id,
                "supervisor_pid": os.getpid(),
                "acquired_at": iso(),
            }
        )
        held_resource_locks.append(handle)
    status["resource_locks"] = list(job.get("resource_locks") or [])
    if held_resource_locks:
        _write_status_soft(job_dir, status)

    repo = Path(str(job.get("repo_root") or job_dir))
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    # sitecustomize in worker_bootstrap keeps Python 3.14's 0o700 temp-dir DACL
    # from cutting off the sandbox capability (see SANDBOX.md).
    bootstrap = Path(str(job.get("plugin_root") or repo)) / "worker_bootstrap"
    pythonpath = [str(repo)]
    if bootstrap.is_dir():
        pythonpath.insert(0, str(bootstrap))
    if existing:
        pythonpath.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env["PYTHONUTF8"] = "1"
    # A worktree has no gitignored data (DBs, indexes): the main checkout's
    # data root is injected by the MCP server; this default covers old records.
    env.setdefault("REALITY_DATA_ROOT", str(repo / "reality_engine" / "data"))
    for key, value in (job.get("env") or {}).items():
        env[str(key)] = str(value)
    env["DSH_WORKER_JOB_ID"] = job_id
    env["DSH_WORKER_JOB_DIR"] = str(job_dir)
    # Per-job scratch: tempfile, pip/npm/uv caches and bytecode all land under
    # <workspace>/.tmp (gitignored) instead of the ambient temp root the
    # sandboxed token cannot write.  The confined pwsh runner additionally
    # rewrites TMP/TEMP to its own private temp for each command.
    tmp = _tmp_dir(job, job_dir)
    # The brief's standing instruction points at DSH_WORKER_PROGRESS_NOTES; it
    # must be inside the workspace, or the worker's own write is denied by the
    # sandbox (the old job-dir path is outside it).
    notes_path = job_dir / progress.PROGRESS_NOTES_FILE
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        status["tmp_dir"] = str(tmp)
        notes_path = tmp / progress.PROGRESS_NOTES_FILE
    except OSError as exc:
        _log(f"cannot create {tmp} ({type(exc).__name__}: {exc}); worker keeps ambient temp")
    env["DSH_WORKER_PROGRESS_NOTES"] = str(notes_path)
    if tmp.is_dir():
        env["TMP"] = str(tmp)
        env["TEMP"] = str(tmp)
        env["TMPDIR"] = str(tmp)
        env["npm_config_cache"] = str(tmp / "npm-cache")
        env["PIP_CACHE_DIR"] = str(tmp / "pip-cache")
        env["UV_CACHE_DIR"] = str(tmp / "uv-cache")
        env["PYTHONPYCACHEPREFIX"] = str(tmp / "pycache")
    # This network's default 15 s pip/uv read timeout fails on large wheels;
    # the workers inherit the raised values without installing a config file.
    env["PIP_DEFAULT_TIMEOUT"] = "120"
    env["PIP_RETRIES"] = "5"
    env["UV_HTTP_TIMEOUT"] = "120"
    # Mark file-sandboxed workers only: worker_bootstrap/sitecustomize.py then
    # drops Python's explicit 0o700 temp-dir DACL (which cuts off the sandbox
    # capability).  A danger-full-access job needs no patch, and an inherited
    # marker from the manager's own environment must never leak in.
    env.pop("DSH_WORKER_SANDBOXED", None)
    if job.get("permission") != "danger-full-access":
        env["DSH_WORKER_SANDBOXED"] = "1"

    job_object = procutil.WinJob()
    mutating = job.get("permission") != "read-only"
    status["job_object"] = "created" if job_object.handle else (job_object.error or "unavailable")
    if job_object.handle is None and os.name == "nt":
        status["warnings"].append(f"Windows job object unavailable: {job_object.error}")
    if os.name == "nt" and mutating and job_object.handle:
        # Contain the supervisor before spawning the worker.  The worker
        # inherits job membership, closing the brief uncontrolled window that
        # exists when assignment happens only after Popen returns.
        if not job_object.assign_current_process():
            status.update(
                {
                    "phase": "failed",
                    "outcome": "containment_unavailable",
                    "error": (
                        "Windows job-object self-assignment failed; refusing to run a "
                        "mutating job without owned cleanup"
                    ),
                    "finished_at": iso(),
                }
            )
            _write_status(job_dir, status)
            _release_lock(job_dir, job, status)
            _log(f"refused mutating job={job_id}: supervisor containment assignment failed")
            return 1
        status["job_object"] = "supervisor_contained"
    containment_error = _containment_error(job) if job_object.handle is None else None
    if containment_error is not None:
        status.update(
            {
                "phase": "failed",
                "outcome": "containment_unavailable",
                "error": containment_error,
                "finished_at": iso(),
            }
        )
        _write_status(job_dir, status)
        _release_lock(job_dir, job, status)
        _log(f"refused mutating job={job_id}: job object containment unavailable")
        return 1

    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"
    run_cwd = Path(str((job.get("launcher") or {}).get("cwd") or repo))
    if not run_cwd.is_dir():
        status.update(
            {
                "phase": "failed",
                "outcome": "cwd_missing",
                "error": f"job working directory does not exist: {run_cwd}",
                "finished_at": iso(),
            }
        )
        _write_status(job_dir, status)
        _release_lock(job_dir, job, status)
        return 1
    process: subprocess.Popen[bytes] | None = None
    try:
        with open(stdout_path, "ab", buffering=0) as out, open(stderr_path, "ab", buffering=0) as err:
            kwargs: dict[str, Any] = {}
            if os.name != "nt":
                kwargs["start_new_session"] = True
            process = subprocess.Popen(
                args_argv,
                cwd=str(run_cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                creationflags=procutil.hidden_creationflags(),
                close_fds=True,
                **kwargs,
            )
            worker_pid = int(process.pid)
            worker_ticks = procutil.process_creation_time(worker_pid)
            status.update(
                {
                    "phase": "running",
                    "worker_pid": worker_pid,
                    "worker_creation_time": worker_ticks,
                    "updated_at": iso(),
                }
            )
            assigned = True
            if job_object.handle:
                if job_object.self_assigned:
                    assigned = job_object.contains(int(process._handle))
                    if assigned:
                        status["job_object"] = "supervisor_and_worker"
                    else:
                        status["warnings"].append(
                            f"worker is not inside the containment job: {job_object.error}"
                        )
                else:
                    assigned = job_object.assign(int(process._handle))
                    if assigned:
                        status["job_object"] = "assigned"
                    else:
                        status["warnings"].append(
                            f"job object assignment failed: {job_object.error}"
                        )
            if not assigned and job.get("permission") != "read-only":
                # Fail closed for mutating work.  Letting an uncontained writer
                # run because job-object assignment failed would allow orphaned
                # edits after a supervisor crash.
                status.update(
                    {
                        "phase": "failed",
                        "outcome": "containment_unavailable",
                        "error": (
                            "Windows job-object assignment failed for a mutating job; "
                            "the worker was killed before it could write without owned "
                            "cleanup"
                        ),
                    }
                )
                procutil.kill_tree(worker_pid)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _log("worker did not exit after containment-failure kill")
                _write_status(job_dir, status)
                _release_lock(job_dir, job, status)
                _log(f"refused mutating job={job_id}: job object assignment failed")
                return 1
            _write_status_soft(job_dir, status)
            _log(f"launched worker pid={worker_pid}")

            last_write = 0.0
            cancel_requested = False
            lease_expired = False
            # Model-free progress digests: one JSON line + progress.md every
            # progress_interval_seconds.  Independent of any Claude/Codex
            # session and never a message into the worker's conversation.
            interval = _progress_interval(job)
            digest = (
                progress.DigestWriter(
                    job_dir,
                    job_id,
                    status.get("started_at"),
                    interval,
                    write_scope=str(job.get("write_scope") or "workspace"),
                    notes_path=notes_path,
                )
                if interval
                else None
            )
            orientation = _Orientation(
                job_dir / "result.md.events.jsonl", status.get("started_at")
            )
            last_aux = 0.0
            while True:
                if _CANCEL:
                    cancel_requested = True
                cancel_marker = job_dir / "cancel.request"
                if cancel_marker.exists() and not cancel_requested:
                    cancel_requested = True
                if cancel_requested:
                    status["phase"] = "cancelling"
                    _write_status_soft(job_dir, status)
                    _log("cancel requested; terminating owned process tree")
                    procutil.kill_tree(worker_pid)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        _log("worker did not exit after taskkill")
                    break
                lease_now, lease_now_error = read_lease(
                    lease_path,
                    expected_job_id=job_id,
                    expected_owner_id=lease_owner,
                    max_seconds=7200,
                )
                if lease_now is None or lease_now.get("expired"):
                    # Independent of model activity: an unrenewed/missing/
                    # malformed controller lease fails closed and stops the
                    # verified owned tree.  A responsive worker cannot outlive
                    # its controller.
                    lease_expired = True
                    status["phase"] = "cancelling"
                    status["controller_lease"] = lease_now
                    status["controller_lease_error"] = lease_now_error or "expired"
                    _write_status_soft(job_dir, status)
                    _log(
                        "controller lease expired or invalid "
                        f"({lease_now_error or 'deadline'}); terminating owned process tree"
                    )
                    procutil.kill_tree(worker_pid)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        _log("worker did not exit after controller-lease kill")
                    break
                status["controller_lease"] = lease_now
                rc = process.poll()
                if rc is not None:
                    status["exit_code"] = int(rc)
                    break
                live, _ = heartbeat.read_heartbeat(job_dir)
                if live is not None:
                    status["heartbeat_live"] = live
                    conversation = live.get("conversation_id") or live.get("dsh_conversation_id")
                    if conversation:
                        status["conversation_id"] = conversation
                    # Only the nested committed-activity timestamp counts.
                    # Status/log/heartbeat.json mtimes are supervision health,
                    # not model/tool progress.
                    worker_activity = live.get("last_worker_activity_at")
                    if worker_activity:
                        current = parse_iso(worker_activity)
                        previous = parse_iso(status.get("worker_activity_at"))
                        if current and (previous is None or current > previous):
                            status["worker_activity_at"] = iso(current)
                now = time.monotonic()
                if now - last_aux >= AUX_POLL_SECONDS:
                    last_aux = now
                    orientation.poll()
                    orientation.apply(status)
                    _poll_aux(job, job_dir, status)
                if digest is not None:
                    _emit_digest(digest, job_dir, job, status)
                if now - last_write >= 1.0:
                    _write_status_soft(job_dir, status)
                    last_write = now
                time.sleep(0.25)
        rc = process.returncode if process is not None else None
        orientation.poll()
        orientation.apply(status)
        status = _finalize(job, job_dir, status, rc, cancel_requested, lease_expired=lease_expired)
        if digest is not None:
            # The final digest always lands, even if the worker ended between
            # two intervals, so progress.md ends with the real outcome.
            _emit_digest(digest, job_dir, job, status, final=True)
        try:
            with exclusive_lock(job_dir / JOB_LOCK_NAME):
                lease_path.unlink(missing_ok=True)
        except OSError:
            pass
        _log(f"finish job={job_id} phase={status.get('phase')} rc={rc}")
        if not _release_lock(job_dir, job, status):
            status.setdefault("warnings", []).append(
                "repository mutation lock retained because the recorded worker could "
                "not be proven dead; inspect before starting another writer"
            )
            _write_status_soft(job_dir, status)
        return 0 if status.get("phase") == "finished" else 1
    except Exception as exc:
        status["warnings"].append(f"supervisor_error:{type(exc).__name__}")
        status["error"] = f"supervisor failed: {type(exc).__name__}"
        if process is not None and process.poll() is None:
            procutil.kill_tree(int(process.pid))
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        status["phase"] = "failed"
        status["outcome"] = "supervisor_error"
        status["finished_at"] = iso()
        _write_status_final(job_dir, status, attempts=10)
        _release_lock(job_dir, job, status)
        _log(f"failed job={job_id}: {type(exc).__name__}")
        return 1
    finally:
        job_object.close()


if __name__ == "__main__":
    raise SystemExit(main())
