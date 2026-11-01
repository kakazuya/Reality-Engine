"""Prompt-time job watch: running, stalled, failed and unreviewed dsh jobs.

``status`` reads only the dsh runtime records and the worker review log, so it
makes no network call and no model call and is safe to run from a hook on every
prompt.  It prints nothing when every recent job is healthy; otherwise at most
12 lines, one per job that needs attention.  ``add`` registers a long-running
process that is not a dsh worker (a log path plus optional ``--pid``) in
``.tmp/job_watch.json``.

``try``/``except`` in ``main`` keeps a broken record from raising into a hook:
the command always exits 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
# Same override the supervisor uses, so the watch can read the live runtime
# from a worktree whose own runtime directory is empty.
RUNTIME_DIR = Path(
    os.environ.get("DSH_WORKER_RUNTIME_DIR") or REPO_ROOT / "plugins" / "dsh-worker" / "runtime"
).expanduser()
JOBS_DIR = RUNTIME_DIR / "jobs"
REVIEWS_PATH = REPO_ROOT / "tasks" / "efficiency" / "worker_reviews.jsonl"
STATE_PATH = REPO_ROOT / ".tmp" / "job_watch.json"

ACTIVE_PHASES = frozenset({"starting", "running", "cancelling"})
BAD_PHASES = frozenset({"failed", "lost", "cancelled"})
BAD_OUTCOMES = frozenset({"failed", "lost", "cancelled", "expired", "start_failed"})

RECENT_HOURS = 48
STALL_MINUTES = 10
REGISTERED_STALL_MINUTES = 5
MAX_LINES = 12


def _iso(value: Any) -> datetime | None:
    """Parse an ISO timestamp as UTC; 2026-11-02T01:53:27+05:30 and ``...Z`` both."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _minutes(since: datetime, now: datetime) -> int:
    return max(0, int((now - since).total_seconds() // 60))


def _epoch(moment: datetime | None) -> float:
    return moment.timestamp() if moment is not None else 0.0


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _review_ids(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return set()
    ids: set[str] = set()
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.add(row["id"])
    return ids


def _tool_calls(job_dir: Path, status: dict[str, Any]) -> int | None:
    """The last progress row's total, else the status record's own event count."""
    path = job_dir / "progress.jsonl"
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 200_000))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        tail = ""
    for line in reversed(tail.splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("tool_calls") is not None:
            try:
                return int(row["tool_calls"])
            except (TypeError, ValueError):
                return None
    progress = status.get("progress")
    events = progress.get("events") if isinstance(progress, dict) else None
    if isinstance(events, dict):
        value = events.get("tool_calls")
        if isinstance(value, (int, float, str)):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _recent_job_dirs(jobs_dir: Path, now: datetime) -> list[Path]:
    """Job folders whose status record changed inside the review window."""
    cutoff = now.timestamp() - RECENT_HOURS * 3600
    try:
        entries = list(os.scandir(jobs_dir))
    except OSError:
        return []
    recent: list[Path] = []
    for entry in entries:
        try:
            if not entry.is_dir():
                continue
            status_path = Path(entry.path) / "status.json"
            if status_path.stat().st_mtime >= cutoff:
                recent.append(Path(entry.path))
        except OSError:
            continue
    return recent


def _lease_expired(status: dict[str, Any], now: datetime) -> bool:
    lease = status.get("controller_lease")
    if not isinstance(lease, dict):
        return False
    if lease.get("expired") is True:
        return True
    deadline = _iso(lease.get("deadline"))
    return deadline is not None and deadline < now - timedelta(seconds=60)


def _branch(job_dir: Path) -> str | None:
    job = _read_json(job_dir / "job.json")
    if not isinstance(job, dict):
        return None
    git = job.get("git")
    branch = git.get("branch") if isinstance(git, dict) else None
    return branch if isinstance(branch, str) and branch else None


def _git(repo_root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _merge_snapshot(repo_root: Path) -> tuple[set[str], str]:
    """Branches merged into HEAD plus merge-commit subjects, in two local git calls."""
    merged = set(
        _git(repo_root, "for-each-ref", "--merged=HEAD", "--format=%(refname:short)", "refs/heads").split()
    )
    return merged, _git(repo_root, "log", "--merges", "--format=%s", "-n", "500")


def _merged(snapshot: tuple[set[str], str], branch: str, job_id: str) -> bool:
    merged, subjects = snapshot
    return branch in merged or job_id in subjects


def _merged_snapshot(repo_root: Path, holder: list[Any]) -> tuple[set[str], str]:
    """The merge evidence, computed at most once per status run."""
    if holder[0] is None:
        holder[0] = _merge_snapshot(repo_root)
    return holder[0]


def _job_line(
    job_dir: Path,
    status: dict[str, Any],
    now: datetime,
    reviewed: set[str],
    repo_root: Path,
    snapshot: list[Any],
) -> tuple[int, float, str] | None:
    job_id = str(status.get("job_id") or job_dir.name)
    phase = str(status.get("phase") or "")
    outcome = str(status.get("outcome") or "")
    started = _iso(status.get("started_at"))
    activity = _iso(status.get("worker_activity_at")) or _iso(status.get("updated_at"))
    finished = _iso(status.get("finished_at")) or _iso(status.get("updated_at"))
    recent = _epoch(started)

    if phase in ACTIVE_PHASES:
        if _lease_expired(status, now):
            return 0, recent, f"ENDED BADLY {job_id} lease expired with no renewal"
        idle_since = activity or started
        if idle_since is not None and now - idle_since > timedelta(minutes=STALL_MINUTES):
            tools = _tool_calls(job_dir, status)
            tool_text = f"{tools} tool calls" if tools is not None else "tool calls unknown"
            return 1, _epoch(idle_since), f"STALLED {job_id} no activity for {_minutes(idle_since, now)}m, {tool_text}"
        tools = _tool_calls(job_dir, status)
        tool_text = f"{tools} tool calls" if tools is not None else "tool calls unknown"
        minutes = _minutes(started, now) if started is not None else 0
        return 3, recent, f"RUNNING {job_id} {minutes}m, {tool_text}"

    if phase in BAD_PHASES or outcome in BAD_OUTCOMES:
        detail = status.get("error") or outcome or phase
        when = _epoch(finished) or recent
        return 0, when, f"ENDED BADLY {job_id} {phase or outcome}: {str(detail)[:100]}"

    if phase != "finished":
        return None
    if job_id in reviewed:
        return None
    if finished is not None and now - finished > timedelta(hours=RECENT_HOURS):
        return None
    branch = _branch(job_dir)
    if branch is not None and _merged(_merged_snapshot(repo_root, snapshot), branch, job_id):
        return None
    return 2, _epoch(finished) or recent, f"FINISHED, NEEDS REVIEW {job_id} {branch or 'branch unknown'}"


def _load_state(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def _pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OverflowError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def _registered_lines(state: dict[str, Any], now: datetime) -> list[tuple[int, float, str]]:
    lines: list[tuple[int, float, str]] = []
    for name in sorted(state):
        record = state[name]
        if not isinstance(record, dict):
            continue
        pid = record.get("pid")
        added = _iso(record.get("added_at")) or now
        if pid is not None and not _pid_alive(pid):
            lines.append((0, _epoch(added), f"ENDED {name} pid {pid} is gone"))
            continue
        log = record.get("log")
        try:
            changed = datetime.fromtimestamp(Path(str(log)).stat().st_mtime, timezone.utc)
        except (OSError, ValueError):
            changed = added
        if now - changed > timedelta(minutes=REGISTERED_STALL_MINUTES):
            lines.append((1, _epoch(changed), f"STALLED {name} log quiet for {_minutes(changed, now)}m"))
    return lines


def status(
    jobs_dir: Path | None = None,
    reviews_path: Path | None = None,
    state_path: Path | None = None,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """The lines a hook should print; an empty list means nothing needs attention."""
    now = now or datetime.now(timezone.utc)
    jobs_dir = Path(jobs_dir or JOBS_DIR)
    repo_root = Path(repo_root or REPO_ROOT)
    reviewed = _review_ids(Path(reviews_path or REVIEWS_PATH))
    snapshot: list[Any] = [None]
    lines: list[tuple[int, float, str]] = []
    for job_dir in _recent_job_dirs(jobs_dir, now):
        record = _read_json(job_dir / "status.json")
        if not isinstance(record, dict) or not record.get("phase"):
            continue
        try:
            line = _job_line(job_dir, record, now, reviewed, repo_root, snapshot)
        except Exception:  # one corrupt record must never hide the other jobs
            continue
        if line is not None:
            lines.append(line)
    lines.extend(_registered_lines(_load_state(Path(state_path or STATE_PATH)), now))
    # Newest state first, so a fresh failure or a just-finished job beats the
    # historical tail; the severity only breaks ties at the same timestamp.
    lines.sort(key=lambda item: (-item[1], item[0], item[2]))
    return [text for _priority, _when, text in lines[:MAX_LINES]]


def add(name: str, logfile: str, pid: int | None = None, state_path: Path | None = None) -> None:
    """Record a long-running non-worker process by name, log path and optional pid."""
    path = Path(state_path or STATE_PATH)
    state = _load_state(path)
    state[name] = {
        "log": str(Path(logfile).expanduser().resolve()),
        "pid": pid,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"jobs": state}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args or args[0] == "status":
            for line in status():
                print(line)
            return 0
        if args[0] == "add" and len(args) >= 3:
            pid = None
            if "--pid" in args[3:]:
                index = args.index("--pid", 3)
                try:
                    pid = int(args[index + 1])
                except (IndexError, ValueError):
                    pid = None
            add(args[1], args[2], pid)
            print(f"watching {args[1]}")
            return 0
        print("usage: job_watch status | job_watch add <name> <logfile> [--pid N]", file=sys.stderr)
    except Exception as exc:  # a hook must never see this command raise
        print(f"job_watch: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
