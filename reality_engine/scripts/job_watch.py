"""Prompt-time job watch: running, stalled, failed and unreviewed dsh jobs.

``status`` reads only the dsh runtime records and the worker review log, so it
makes no network call and no model call and is safe to run from a hook on every
prompt.  It prints nothing when every recent job is healthy; otherwise at most
12 lines, one per job that needs attention.  ``add`` registers a long-running
process that is not a dsh worker (a log path plus optional ``--pid``) in
``.tmp/job_watch.json``.

``wait`` blocks until a job ends or stalls, or until no running job and no live
registered pid remain, so a session runs it as a background command and the
harness wakes that session when it exits.  It records its pid and start time in
``.tmp/job_watch_wait.json`` while it runs and removes the file on every exit
path.  ``ack`` marks a job reviewed in ``.tmp/job_watch_acks.jsonl`` and drops a
registered name from the watch list.  The Stop hook refuses one stop while a
finish or failure is unreviewed, or while a job runs with no live waiter.

``try``/``except`` in ``main`` keeps a broken record from raising into a hook:
the command always exits 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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
ACKS_PATH = REPO_ROOT / ".tmp" / "job_watch_acks.jsonl"
WAIT_PATH = REPO_ROOT / ".tmp" / "job_watch_wait.json"

FINISHED_PREFIX = "FINISHED, NEEDS REVIEW "
ENDED_BADLY_PREFIX = "ENDED BADLY "
WAIT_STATES = frozenset({"STALLED", "ENDED", "FINISHED"})

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


def _merge_snapshot(repo_root: Path) -> tuple[set[str], str, set[str]]:
    """Merged branches, merge-commit subjects and every local branch, in three local git calls."""
    merged = set(
        _git(repo_root, "for-each-ref", "--merged=HEAD", "--format=%(refname:short)", "refs/heads").split()
    )
    existing = set(_git(repo_root, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())
    return merged, _git(repo_root, "log", "--merges", "--format=%s", "-n", "500"), existing


def _reviewed_finish(snapshot: tuple[set[str], str, set[str]], branch: str | None, job_id: str) -> bool:
    """A finish needs no review once merged, or once its branch is gone.

    HP jobs have no branch record, and a continued job reuses its first job's branch.
    An empty branch list means git did not answer, so a missing branch proves nothing.
    """
    merged, subjects, existing = snapshot
    if job_id in subjects:
        return True
    if branch is None:
        return False
    return branch in merged or branch in subjects or (bool(existing) and branch not in existing)


def _merged_snapshot(repo_root: Path, holder: list[Any]) -> tuple[set[str], str, set[str]]:
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
            if job_id in reviewed:
                return None
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
        if job_id in reviewed:
            return None
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
    if _reviewed_finish(_merged_snapshot(repo_root, snapshot), branch, job_id):
        return None
    return 2, _epoch(finished) or recent, f"FINISHED, NEEDS REVIEW {job_id} {branch or 'branch unknown'}"


def _load_state(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"jobs": state}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


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


def live_jobs(jobs_dir: Path | None = None, now: datetime | None = None) -> bool:
    """True while any job is active, read from the records rather than the capped lines."""
    now = now or datetime.now(timezone.utc)
    for job_dir in _recent_job_dirs(Path(jobs_dir or JOBS_DIR), now):
        record = _read_json(job_dir / "status.json")
        if isinstance(record, dict) and str(record.get("phase") or "") in ACTIVE_PHASES:
            return True
    return False


def live_registered(state_path: Path | None = None) -> bool:
    """True while a registered non-worker process still holds its pid."""
    state = _load_state(Path(state_path or STATE_PATH))
    return any(isinstance(row, dict) and _pid_alive(row.get("pid")) for row in state.values())


def _line_key(line: str) -> tuple[str, str]:
    """(state, job id or registered name) from one status line.

    The minutes and tool counts never enter the key, so a running job that only
    ages is not a change.
    """
    words = line.split()
    if line.startswith(ENDED_BADLY_PREFIX):
        return "ENDED", words[2] if len(words) > 2 else ""
    if line.startswith(FINISHED_PREFIX):
        return "FINISHED", words[3] if len(words) > 3 else ""
    return (words[0] if words else ""), (words[1] if len(words) > 1 else "")


def _write_waiter(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)


def _remove_waiter(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def waiter_alive(wait_path: Path | None = None) -> bool:
    """True while a ``wait`` process holds ``.tmp/job_watch_wait.json``."""
    data = _read_json(Path(wait_path or WAIT_PATH))
    # ponytail: pid alone; a crashed waiter's reused pid reads live until the next wait rewrites it.
    return isinstance(data, dict) and _pid_alive(data.get("pid"))


def wait(
    timeout_seconds: float = 3300,
    poll_seconds: float = 20,
    jobs_dir: Path | None = None,
    reviews_path: Path | None = None,
    state_path: Path | None = None,
    repo_root: Path | None = None,
    acks_path: Path | None = None,
    wait_path: Path | None = None,
) -> list[str]:
    """Poll until a job ends or stalls, or no running job and no live pid are left.

    Returns the lines to print: the newly ended or stalled ones, or a single
    ``TIMEOUT still running: ...`` line. Run from ``main`` as a background command:
    the harness wakes the session when this returns.
    """
    jobs_dir = Path(jobs_dir or JOBS_DIR)
    reviews_path = Path(reviews_path or REVIEWS_PATH)
    state_path = Path(state_path or STATE_PATH)
    repo_root = Path(repo_root or REPO_ROOT)
    acks_path = Path(acks_path or ACKS_PATH)
    wait_path = Path(wait_path or WAIT_PATH)

    def snapshot() -> list[str]:
        return status(jobs_dir, reviews_path, state_path, repo_root, acks_path=acks_path)

    baseline = {_line_key(line) for line in snapshot()}
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    _write_waiter(wait_path)
    try:
        while True:
            lines = snapshot()
            changed = [
                line
                for line in lines
                if _line_key(line) not in baseline and _line_key(line)[0] in WAIT_STATES
            ]
            if changed:
                return changed
            if not live_jobs(jobs_dir) and not live_registered(state_path):
                return []
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return [f"TIMEOUT still running: {' | '.join(lines)}"]
            time.sleep(max(0.01, min(float(poll_seconds), remaining)))
    finally:
        _remove_waiter(wait_path)


def ack(
    target: str,
    note: str | None = None,
    state_path: Path | None = None,
    acks_path: Path | None = None,
) -> bool:
    """Mark a job reviewed, and drop a registered name from the watch list.

    Returns True when the target was a registered name that has been removed.
    """
    path = Path(acks_path or ACKS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"id": target, "acked_at": datetime.now(timezone.utc).isoformat()}
    if note:
        record["note"] = note
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    state = _load_state(Path(state_path or STATE_PATH))
    if target not in state:
        return False
    del state[target]
    _save_state(Path(state_path or STATE_PATH), state)
    return True


def status(
    jobs_dir: Path | None = None,
    reviews_path: Path | None = None,
    state_path: Path | None = None,
    repo_root: Path | None = None,
    now: datetime | None = None,
    acks_path: Path | None = None,
) -> list[str]:
    """The lines a hook should print; an empty list means nothing needs attention."""
    now = now or datetime.now(timezone.utc)
    jobs_dir = Path(jobs_dir or JOBS_DIR)
    repo_root = Path(repo_root or REPO_ROOT)
    reviewed = _review_ids(Path(reviews_path or REVIEWS_PATH))
    reviewed |= _review_ids(Path(acks_path or ACKS_PATH))
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
    # Stalled, then running, whatever their age: a live job must never fall off
    # the cap behind old failures. The rest sort newest first.
    live_rank = {1: 0, 3: 1}
    lines.sort(key=lambda item: (live_rank.get(item[0], 2), -item[1], item[0], item[2]))
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
    _save_state(path, state)


def _option(args: list[str], name: str, default: str) -> str:
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return default


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    usage = (
        "usage: job_watch status | wait [--timeout-seconds N] [--poll-seconds N]"
        " | add <name> <logfile> [--pid N] | ack <job_id_or_name> [--note TEXT] | ack --all-ended"
    )
    try:
        if not args or args[0] == "status":
            for line in status():
                print(line)
            return 0
        if args[0] == "wait":
            try:
                timeout = float(_option(args, "--timeout-seconds", "3300"))
                poll = float(_option(args, "--poll-seconds", "20"))
            except ValueError:
                print("wait: --timeout-seconds and --poll-seconds take a number", file=sys.stderr)
                return 0
            for line in wait(timeout_seconds=timeout, poll_seconds=poll):
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
        if args[0] == "ack" and len(args) >= 2:
            note = _option(args, "--note", "") or None
            if args[1] == "--all-ended":
                targets = [_line_key(line)[1] for line in status() if line.startswith("ENDED")]
                for target in targets:
                    ack(target, note)
                print(f"acked {len(targets)} ended line(s)")
            elif ack(args[1], note):
                print(f"acked {args[1]} and removed it from the watch list")
            else:
                print(f"acked {args[1]}")
            return 0
        print(usage, file=sys.stderr)
    except Exception as exc:  # a hook must never see this command raise
        print(f"job_watch: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
