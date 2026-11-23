"""T-053: job_watch wait and the Stop hook under real child processes.

Every scenario runs the real ``job_watch.py wait`` (or ``session_hooks.py stop``)
as a child process against a fixture ``DSH_WORKER_RUNTIME_DIR``, a fixture
``JOB_WATCH_REPO_ROOT`` (a fresh git repository) and a fixture ``.tmp``.  Nothing
here reads or writes the live runtime folder, the main checkout's
``.tmp/job_watch*`` files or a real job.

The complaint behind the ticket: workers finish and Claude does not notice.  The
scenarios below are the ways ``wait`` used to sleep through a finish.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JOB_WATCH = REPO_ROOT / "reality_engine" / "scripts" / "job_watch.py"
SESSION_HOOKS = REPO_ROOT / "reality_engine" / "scripts" / "session_hooks.py"
TEST_TMP = REPO_ROOT / ".tmp" / "job_watch_stress"
sys.path.insert(0, str(REPO_ROOT / "reality_engine" / "scripts"))

import job_watch  # noqa: E402  (path-independent checks only: pid alive and waiter records)

POLL = 1.0
SLOP = 2.5  # process start, a snapshot, and filesystem time on a loaded laptop


def _now() -> datetime:
    return datetime.now(timezone.utc)


class World:
    """One isolated runtime, repo root and ``.tmp`` for one scenario."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.runtime = root / "runtime"
        self.jobs = self.runtime / "jobs"
        self.repo = root / "repo"
        self.tmp = self.repo / ".tmp"
        self.wait_dir = self.tmp / "job_watch_wait"
        self.procs: list[subprocess.Popen] = []
        for path in (self.jobs, self.repo, self.tmp):
            path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)

    @property
    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("DOC_REVIEW_LOOP", None)
        env.update(
            {
                "DSH_WORKER_RUNTIME_DIR": str(self.runtime),
                "JOB_WATCH_REPO_ROOT": str(self.repo),
                "JOB_WATCH_ACKS": str(self.tmp / "acks.jsonl"),
                "JOB_WATCH_STATE": str(self.tmp / "state.json"),
                "JOB_WATCH_WAIT_DIR": str(self.wait_dir),
                "JOB_WATCH_REGISTERED_STALL_SECONDS": "5",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        return env


@pytest.fixture()
def world():
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    root = TEST_TMP / uuid.uuid4().hex[:12]
    root.mkdir()
    place = World(root)
    try:
        yield place
    finally:
        for proc in place.procs:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------- fixtures
def _write_job(
    world: World,
    job_id: str,
    *,
    phase: str = "running",
    started: datetime | None = None,
    activity: datetime | None = None,
    finished: datetime | None = None,
    outcome: str | None = None,
    branch: str | None = None,
) -> datetime:
    started = started or _now()
    job_dir = world.jobs / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "job_id": job_id,
        "host": "msi",
        "phase": phase,
        "outcome": outcome,
        "started_at": started.isoformat(),
        "updated_at": (finished or activity or started).isoformat(),
        "worker_activity_at": (activity or started).isoformat(),
        "finished_at": finished.isoformat() if finished is not None else None,
        "controller_lease": {"deadline": (started + timedelta(hours=2)).isoformat()},
    }
    (job_dir / "status.json").write_text(json.dumps(record), encoding="utf-8")
    if branch is not None:
        (job_dir / "job.json").write_text(json.dumps({"git": {"branch": branch}}), encoding="utf-8")
    (job_dir / "progress.jsonl").write_text(
        json.dumps({"at": started.isoformat(), "tool_calls": 17}) + "\n", encoding="utf-8"
    )
    return started


def _finish(world: World, job_id: str, started: datetime) -> None:
    _write_job(world, job_id, phase="finished", started=started, finished=_now(), outcome="completed")


def _hide_jobs(world: World, job_ids: list[str]) -> None:
    path = world.tmp / "acks.jsonl"
    path.write_text("".join(json.dumps({"id": job_id, "acked_at": _now().isoformat()}) + "\n" for job_id in job_ids),
                    encoding="utf-8")


def _waiters(world: World) -> list[Path]:
    return sorted(world.wait_dir.glob("*.json")) if world.wait_dir.exists() else []


def _await_waiters(world: World, count: int, timeout: float = 20) -> list[Path]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _waiters(world)
        if len(found) >= count:
            return found
        time.sleep(0.02)
    pytest.fail(f"waiter file(s) never appeared: wanted {count}, saw {len(_waiters(world))}")


def _run(world: World, script: Path, *args: str, input_text: str = "", timeout: float = 90,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(world.repo),
        env={**world.env, **(env or {})},
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _start(world: World, script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(script), *args],
        cwd=str(world.repo),
        env={**world.env, **(env or {})},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    world.procs.append(proc)
    return proc


def _communicate(proc: subprocess.Popen, timeout: float = 60) -> tuple[int, str, str]:
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out or "", err or ""


def _stop_hook(world: World, timeout: float = 30) -> subprocess.CompletedProcess:
    return _run(world, SESSION_HOOKS, "stop", input_text="{}", timeout=timeout)


def _reason(output: str) -> str:
    return json.loads(output)["reason"]


# ------------------------------------------------- 1. finish before the baseline
def test_race_before_baseline_reports_the_finish_at_once(world: World):
    """A finish that landed before `wait` took its baseline must not be swallowed."""
    finished_id = "20261103T100000Z-aaaaaaaa"
    _write_job(world, finished_id, phase="finished", finished=_now(), outcome="completed")
    _write_job(world, "20261103T100100Z-bbbbbbbb")
    began = time.monotonic()
    done = _run(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "30", timeout=40)
    elapsed = time.monotonic() - began
    assert done.returncode == 0, done.stderr
    assert f"FINISHED, NEEDS REVIEW {finished_id}" in done.stdout
    assert "TIMEOUT" not in done.stdout
    assert elapsed < 10, "wait slept on the still-running job instead of reporting the finish"


def test_ignore_existing_keeps_the_old_baseline(world: World):
    """--ignore-existing restores the old behaviour: the baseline hides the finish."""
    finished_id = "20261103T100200Z-cccccccc"
    _write_job(world, finished_id, phase="finished", finished=_now(), outcome="completed")
    _write_job(world, "20261103T100300Z-dddddddd")
    done = _run(
        world,
        JOB_WATCH,
        "wait",
        "--poll-seconds", str(POLL),
        "--timeout-seconds", "3",
        "--ignore-existing",
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("TIMEOUT still running:")


# ------------------------------------------------------- 2. running -> finished
def test_running_to_finished_is_reported_within_two_polls(world: World):
    job_id = "20261103T110000Z-aaaaaaaa"
    started = _write_job(world, job_id)
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "60")
    _await_waiters(world, 1)
    flipped = time.monotonic()
    _finish(world, job_id, started)
    code, out, err = _communicate(proc)
    elapsed = time.monotonic() - flipped
    assert code == 0, err
    assert f"FINISHED, NEEDS REVIEW {job_id}" in out
    assert elapsed < 2 * POLL + SLOP, f"took {elapsed:.1f}s, more than two poll intervals"
    assert _waiters(world) == []


# ------------------------------------------------------ 3. corrupt status.json
def test_half_written_status_json_does_not_stop_the_wait(world: World):
    """Garbage during a poll must not crash the waiter nor let it exit silently."""
    job_id = "20261103T120000Z-bbbbbbbb"
    started = _write_job(world, job_id)
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "60")
    _await_waiters(world, 1)
    (world.jobs / job_id / "status.json").write_text("{not json", encoding="utf-8")
    time.sleep(POLL + 0.6)
    assert proc.poll() is None, "wait exited silently while status.json was half-written"
    _finish(world, job_id, started)
    code, out, err = _communicate(proc)
    assert code == 0, err
    assert f"FINISHED, NEEDS REVIEW {job_id}" in out


# ---------------------------------------------------------------- 4. many jobs
def test_forty_jobs_one_finish_is_reported(world: World):
    """30 old finished+acked jobs must not hide the 40th folder's finish."""
    old = [_now() - timedelta(hours=3) for _ in range(30)]
    finished_ids = [f"20261103T08{index:02d}00Z-aaaaaaaa" for index in range(30)]
    for index, job_id in enumerate(finished_ids):
        _write_job(world, job_id, phase="finished", started=old[index] + timedelta(hours=1),
                   finished=old[index], outcome="completed")
    _hide_jobs(world, finished_ids)
    running = {}
    for index in range(10):
        job_id = f"20261103T09{index:02d}00Z-bbbbbbbb"
        running[job_id] = _write_job(world, job_id)
    target = next(iter(running))
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "60")
    _await_waiters(world, 1)
    flipped = time.monotonic()
    _finish(world, target, running[target])
    code, out, err = _communicate(proc)
    elapsed = time.monotonic() - flipped
    assert code == 0, err
    assert f"FINISHED, NEEDS REVIEW {target}" in out
    assert elapsed < 2 * POLL + SLOP
    assert len(_waiters(world)) == 0


def test_finish_below_the_twelve_line_cap_is_still_reported(world: World):
    """More than 12 live lines: the finish ranked off the cap must still wake the wait."""
    running = {}
    for index in range(15):
        job_id = f"20261103T10{index:02d}00Z-cccccccc"
        running[job_id] = _write_job(world, job_id, started=_now() - timedelta(minutes=index), activity=_now())
    target = list(running)[-1]  # the oldest started: last of the 15 RUNNING lines, past the cap
    shown = job_watch.status(
        world.jobs,
        world.tmp / "reviews.jsonl",
        world.tmp / "state.json",
        world.repo,
        acks_path=world.tmp / "acks.jsonl",
    )
    assert len(shown) == job_watch.MAX_LINES, "the fixture must put the cap under pressure"
    assert not any(target in line for line in shown), "the target must fall past the printed cap"
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "60")
    _await_waiters(world, 1)
    flipped = time.monotonic()
    _finish(world, target, running[target])
    code, out, err = _communicate(proc)
    elapsed = time.monotonic() - flipped
    assert code == 0, err
    assert f"FINISHED, NEEDS REVIEW {target}" in out
    assert elapsed < 2 * POLL + SLOP


# --------------------------------------------------- 5. registered, no pid, quiet
def test_registered_job_without_a_pid_stalls_after_the_window(world: World):
    log = world.repo / "backfill.log"
    log.write_text("started\n", encoding="utf-8")
    (world.tmp / "state.json").write_text(
        json.dumps({"jobs": {"backfill": {"log": str(log), "added_at": _now().isoformat()}}}),
        encoding="utf-8",
    )
    proc = _start(
        world,
        JOB_WATCH,
        "wait",
        "--poll-seconds", "0.5",
        "--timeout-seconds", "60",
        env={"JOB_WATCH_REGISTERED_STALL_SECONDS": "30"},
    )
    _await_waiters(world, 1)
    time.sleep(1.0)
    assert proc.poll() is None, "wait must keep watching a registered job whose log is still fresh"
    old = (_now() - timedelta(minutes=2)).timestamp()
    os.utime(log, (old, old))
    flipped = time.monotonic()
    code, out, err = _communicate(proc)
    elapsed = time.monotonic() - flipped
    assert code == 0, err
    assert out.startswith("STALLED backfill log quiet for")
    assert elapsed < 2 * 1 + SLOP


# --------------------------------------------------- 6. registered pid goes away
def test_registered_pid_exit_is_reported(world: World):
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    world.procs.append(sleeper)
    log = world.repo / "extract.log"
    log.write_text("running\n", encoding="utf-8")
    (world.tmp / "state.json").write_text(
        json.dumps(
            {"jobs": {"extract": {"log": str(log), "pid": sleeper.pid, "added_at": _now().isoformat()}}}
        ),
        encoding="utf-8",
    )
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "60")
    _await_waiters(world, 1)
    time.sleep(0.5)
    assert proc.poll() is None, "wait must hold while the registered pid lives"
    sleeper.kill()
    sleeper.wait(timeout=10)
    flipped = time.monotonic()
    code, out, err = _communicate(proc)
    elapsed = time.monotonic() - flipped
    assert code == 0, err
    assert f"ENDED extract pid {sleeper.pid} is gone" in out
    assert elapsed < 2 * POLL + SLOP


# ------------------------------------------------- 7. killed waiter, pid reuse guard
def test_hard_killed_waiter_leaves_a_dead_record_and_the_stop_hook_blocks(world: World):
    job_id = "20261103T130000Z-dddddddd"
    _write_job(world, job_id)
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "120")
    (record,) = _await_waiters(world, 1)
    proc.kill()
    proc.wait(timeout=10)
    assert record.exists(), "a hard-killed waiter cannot clean its record; the file stays"
    assert job_watch.waiter_alive(world.wait_dir) is False

    blocked = _stop_hook(world)
    assert blocked.returncode == 0
    assert json.loads(blocked.stdout)["decision"] == "block"
    assert "arm a wait" in _reason(blocked.stdout)

    created = job_watch._process_started(os.getpid())
    if created is not None:  # pid reuse: same pid, a different process, same answer
        live = world.wait_dir / f"{os.getpid()}.json"
        live.write_text(json.dumps({"pid": os.getpid(), "created_at": created - 600}), encoding="utf-8")
        reused = _stop_hook(world)
        assert "arm a wait" in _reason(reused.stdout), "a reused pid with another creation time is dead"
        live.write_text(json.dumps({"pid": os.getpid(), "created_at": created}), encoding="utf-8")
        passed = _stop_hook(world)
        assert passed.stdout == "", "a real live waiter must let the stop through"
        live.unlink()


# ------------------------------------------------------------ 8. two waiters
def test_two_waiters_one_dying_leaves_the_other_alive(world: World):
    _write_job(world, "20261103T140000Z-eeeeeeee")
    first = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "120")
    _await_waiters(world, 1)
    second = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "120")
    records = _await_waiters(world, 2)
    assert len(records) == 2
    assert {record.stem for record in records} == {str(first.pid), str(second.pid)}
    first.kill()
    first.wait(timeout=10)
    assert job_watch.waiter_alive(world.wait_dir) is True, "one dead waiter must not kill the other's record"
    passed = _stop_hook(world)
    assert passed.stdout == "", "the surviving waiter still proves the job is watched"
    second.kill()
    second.wait(timeout=10)
    assert job_watch.waiter_alive(world.wait_dir) is False
    blocked = _stop_hook(world)
    assert "arm a wait" in _reason(blocked.stdout)


# ------------------------------------------------------- 9. Stop hook latency
def test_stop_hook_under_forty_jobs_is_fast(world: World):
    old = _now() - timedelta(hours=2)
    acked = [f"20261103T07{index:02d}00Z-ffffffff" for index in range(29)]
    for index, job_id in enumerate(acked):
        _write_job(world, job_id, phase="finished", started=old, finished=old + timedelta(minutes=1))
    _hide_jobs(world, acked)
    # One unreviewed finish forces the git merge checks; ten running jobs keep it live.
    _write_job(world, "20261103T150000Z-99999999", phase="finished", started=old, finished=_now(),
               outcome="completed")
    for index in range(10):
        _write_job(world, f"20261103T16{index:02d}00Z-88888888")
    began = time.monotonic()
    hook = _stop_hook(world)
    elapsed = time.monotonic() - began
    assert hook.returncode == 0, hook.stderr
    assert "FINISHED, NEEDS REVIEW" in _reason(hook.stdout)
    assert elapsed < 3.0, f"Stop hook took {elapsed:.2f}s over 40 jobs"


# ------------------------------------------------------------- 10. timeout line
def test_timeout_still_running_exits_zero(world: World):
    job_id = "20261103T170000Z-77777777"
    _write_job(world, job_id)
    began = time.monotonic()
    done = _run(world, JOB_WATCH, "wait", "--timeout-seconds", "3", "--poll-seconds", str(POLL), timeout=30)
    elapsed = time.monotonic() - began
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("TIMEOUT still running:")
    assert job_id in done.stdout
    assert 2.5 <= elapsed < 15
    assert _waiters(world) == []


# ------------------------------------------------- 11. T-096: a worker waits for a reply
def _open_reply_wait(world: World, job_id: str) -> None:
    now = _now()
    hb = {
        "awaiting_input": True,
        "awaiting_since": now.isoformat(),
        "awaiting_deadline": (now + timedelta(minutes=59)).isoformat().replace("+00:00", "Z"),
        "last_activity_at": now.isoformat(),
    }
    path = world.jobs / job_id / "heartbeat.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"awaiting_input": True, "heartbeat": hb}), encoding="utf-8")
    os.replace(tmp, path)


def test_wait_wakes_within_two_polls_when_a_worker_starts_waiting(world: World):
    job_id = "20261106T100000Z-aaaaaaaa"
    _write_job(world, job_id)
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "60")
    _await_waiters(world, 1)
    _open_reply_wait(world, job_id)
    began = time.monotonic()
    code, out, err = _communicate(proc)
    elapsed = time.monotonic() - began
    assert code == 0, err
    assert out.startswith(f"WAITING {job_id} for a reply")
    assert elapsed < 2 * POLL + SLOP, "a worker waiting for a reply must not sit until the 10-minute stall"
    assert _waiters(world) == []


def test_ack_stops_the_wait_and_the_stop_hook_firing_until_the_worker_acts(world: World):
    job_id = "20261106T100100Z-bbbbbbbb"
    _write_job(world, job_id)
    _open_reply_wait(world, job_id)
    assert "answer or ack" in _reason(_stop_hook(world).stdout)
    done = _run(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "30", timeout=40)
    assert done.stdout.startswith(f"WAITING {job_id}"), "an unacked wait is reported at once"

    _run(world, JOB_WATCH, "ack", job_id, "--note", "answer next session")
    assert _run(world, JOB_WATCH, "status").stdout.startswith(f"ACKED {job_id} waiting for a reply")
    hook = _stop_hook(world)
    assert hook.returncode == 0 and hook.stdout == "", "an acked wait must not block a stop or ask for a waiter"

    # Replied to, worked, and waiting again: a new event, seen by a wait armed before it.
    proc = _start(world, JOB_WATCH, "wait", "--poll-seconds", str(POLL), "--timeout-seconds", "60")
    _await_waiters(world, 1)
    time.sleep(1.1)  # whole-second separation from the ack
    _open_reply_wait(world, job_id)
    code, out, err = _communicate(proc)
    assert code == 0, err
    assert out.startswith(f"WAITING {job_id}")
