"""Detached supervisor for one dsh job.

Started hidden by the MCP server and intentionally independent of it: the
supervisor owns the launcher process, writes the persisted status, and keeps a
Windows job object with ``KILL_ON_JOB_CLOSE`` so a dead supervisor cannot leave
an unowned writer behind.  It never calls a model and never copies reasoning
stderr into the result.
"""
from __future__ import annotations

import os
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
    exclusive_lock,
    iso,
    parse_iso,
    read_json_bounded,
    read_lease,
    read_text_bounded,
    resource_lock_path,
    workspace_lock_name,
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
        )
    except Exception as exc:  # noqa: BLE001 - a digest bug must never kill a run
        _log(f"progress digest failed ({type(exc).__name__}: {exc}); will retry")


def _create_status(job: dict[str, Any], job_dir: Path) -> dict[str, Any]:
    return {
        "schema": 1,
        "job_id": job.get("job_id"),
        "kind": job.get("kind") or "worker",
        "phase": "starting",
        "started_at": job.get("created_at") or iso(),
        "updated_at": iso(),
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
            final_snapshot = gitutil.snapshot(Path(str(job.get("workspace"))))
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
    held_resource_locks: list[Any] = []
    for lock_name in job.get("resource_locks") or []:
        handle = acquire_lock_file(
            resource_lock_path(runtime_dir / "locks", str(lock_name)), timeout=2.0
        )
        if handle is None:
            for held in held_resource_locks:
                held.release()
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
    env["PYTHONPATH"] = str(repo) + (os.pathsep + existing if existing else "")
    env["PYTHONUTF8"] = "1"
    # A worktree has no gitignored data (DBs, indexes): the main checkout's
    # data root is injected by the MCP server; this default covers old records.
    env.setdefault("REALITY_DATA_ROOT", str(repo / "reality_engine" / "data"))
    for key, value in (job.get("env") or {}).items():
        env[str(key)] = str(value)
    env["DSH_WORKER_JOB_ID"] = job_id
    env["DSH_WORKER_JOB_DIR"] = str(job_dir)
    # The brief's standing instruction points at this path; the worker appends
    # one line per milestone and the supervisor folds the latest into a digest.
    env["DSH_WORKER_PROGRESS_NOTES"] = str(job_dir / progress.PROGRESS_NOTES_FILE)

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
                    job_dir, job_id, status.get("started_at"), interval
                )
                if interval
                else None
            )
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
                if digest is not None:
                    _emit_digest(digest, job_dir, job, status)
                if now - last_write >= 1.0:
                    _write_status_soft(job_dir, status)
                    last_write = now
                time.sleep(0.25)
        rc = process.returncode if process is not None else None
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
