"""T-044/T-050: list_workers ordering and the prompt-time job watch.

Fixtures live under the repository ``.tmp`` (the sandbox temp folder has an ACL
fault) and are removed by the ``root`` fixture.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "dsh-worker" / "server"))

import core  # noqa: E402

from reality_engine.scripts import job_watch  # noqa: E402

TEST_TMP = REPO_ROOT / ".tmp" / "job_watch_tests"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


def _ago(minutes: float = 0, hours: float = 0) -> datetime:
    return NOW - timedelta(minutes=minutes, hours=hours)


@pytest.fixture()
def root() -> Iterator[Path]:
    # A default-mode mkdir: tempfile.mkdtemp uses 0o700, and under this
    # sandbox's ACLs a 0o700 directory refuses its own child directories.
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    path = TEST_TMP / uuid.uuid4().hex[:12]
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_watch_files(root: Path, monkeypatch) -> None:
    """Keep the real acks, waiter and watch-list files out of every test."""
    monkeypatch.setattr(job_watch, "ACKS_PATH", root / "acks.jsonl")
    monkeypatch.setattr(job_watch, "WAIT_DIR", root / "waiters")
    monkeypatch.setattr(job_watch, "STATE_PATH", root / "state_default.json")


# ---------------------------------------------------------------- list_workers
def _list_manager(root: Path, rows: dict[str, dict]):
    """A real Manager whose status read is replaced by the given rows."""
    env = {
        "DSH_WORKER_REPO_ROOT": str(root),
        "DSH_WORKER_RUNTIME_DIR": str(root / "runtime"),
        "DSH_WORKTREES_ROOT": str(root / "worktrees"),
        "DSH_WORKER_TESTING": "1",
    }
    (root / "reality_engine").mkdir(parents=True, exist_ok=True)
    config = core.load_config(env)
    manager = core.Manager(config)
    for job_id in rows:
        job_dir = config.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "progress.jsonl").write_text("", encoding="utf-8")

    def fake_status(job_id: str) -> dict:
        row = rows[job_id]
        job_dir = config.jobs_dir / job_id
        return {
            "job_id": job_id,
            "host": row.get("host", "msi"),
            "phase": row["phase"],
            "running": row.get("running", row["phase"] in core.ACTIVE_PHASES),
            "stale": False,
            "workspace": row["workspace"],
            "permission": "workspace-write",
            "started_at": row["started_at"],
            "updated_at": row["started_at"],
            "final": row["phase"] in core.FINAL_PHASES,
            "result_ready": False,
            "progress": {},
            "paths": {
                "result": str(job_dir / "result.md"),
                "status": str(job_dir / "status.json"),
            },
        }

    manager.get_status = fake_status
    return manager


def _row(workspace: Path, phase: str, started: datetime, host: str = "msi") -> dict:
    return {"workspace": str(workspace), "phase": phase, "started_at": started.isoformat(), "host": host}


def test_running_job_sorts_before_a_newer_finished_job(root: Path):
    manager = _list_manager(
        root,
        {
            "20261102T030000Z-aaaaaaaa": _row(root, "finished", _ago(minutes=30)),
            "20261102T010000Z-bbbbbbbb": _row(root, "running", _ago(hours=2)),
        },
    )
    listed = [row["job_id"] for row in manager.list_workers(limit=10)["jobs"]]
    assert listed == ["20261102T010000Z-bbbbbbbb", "20261102T030000Z-aaaaaaaa"]


def test_newest_first_across_hosts(root: Path):
    manager = _list_manager(
        root,
        {
            "hp-20261102T050000-cccccc": _row(root, "finished", _ago(minutes=10), host="hp"),
            "20261102T040000Z-dddddddd": _row(root, "finished", _ago(hours=1)),
            "20261102T010000Z-eeeeeeee": _row(root, "running", _ago(hours=3)),
            "hp-20261101T000000-ffffff": _row(root, "finished", _ago(hours=6), host="hp"),
        },
    )
    listed = [row["job_id"] for row in manager.list_workers(limit=10)["jobs"]]
    assert listed == [
        "20261102T010000Z-eeeeeeee",  # running first
        "hp-20261102T050000-cccccc",  # then newest started, hp or local
        "20261102T040000Z-dddddddd",
        "hp-20261101T000000-ffffff",
    ]


def test_workspace_filter_keeps_the_running_first_order(root: Path):
    manager = _list_manager(
        root,
        {
            "20261102T030000Z-aaaaaaaa": _row(root, "finished", _ago(minutes=30)),
            "20261102T010000Z-bbbbbbbb": _row(root, "running", _ago(hours=2)),
            "20261102T040000Z-cccccccc": _row(root / "other", "running", _ago(minutes=5)),
        },
    )
    listed = [row["job_id"] for row in manager.list_workers(workspace=str(root), limit=10)["jobs"]]
    assert listed == ["20261102T010000Z-bbbbbbbb", "20261102T030000Z-aaaaaaaa"]


def test_limit_is_applied_after_ordering(root: Path):
    manager = _list_manager(
        root,
        {
            "20261102T030000Z-aaaaaaaa": _row(root, "finished", _ago(minutes=10)),
            "20261102T020000Z-bbbbbbbb": _row(root, "finished", _ago(minutes=20)),
            "20261102T010000Z-cccccccc": _row(root, "running", _ago(hours=3)),
        },
    )
    listed = [row["job_id"] for row in manager.list_workers(limit=2)["jobs"]]
    assert listed == ["20261102T010000Z-cccccccc", "20261102T030000Z-aaaaaaaa"]


# ------------------------------------------------------------------- job_watch
def _write_job(
    jobs_dir: Path,
    job_id: str,
    *,
    phase: str,
    started: datetime,
    activity: datetime | None = None,
    finished: datetime | None = None,
    outcome: str | None = None,
    tool_calls: int = 17,
    branch: str | None = None,
    host: str = "msi",
) -> Path:
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    status = {
        "job_id": job_id,
        "host": host,
        "phase": phase,
        "outcome": outcome,
        "started_at": started.isoformat(),
        "updated_at": (activity or started).isoformat(),
        "worker_activity_at": activity.isoformat() if activity is not None else None,
        "finished_at": finished.isoformat() if finished is not None else None,
        "controller_lease": {"deadline": (started + timedelta(hours=2)).isoformat()},
    }
    (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    if branch is not None:
        (job_dir / "job.json").write_text(json.dumps({"git": {"branch": branch}}), encoding="utf-8")
    (job_dir / "progress.jsonl").write_text(
        json.dumps({"at": started.isoformat(), "tool_calls": tool_calls}) + "\n", encoding="utf-8"
    )
    return job_dir


def _empty_reviews(root: Path) -> Path:
    path = root / "reviews.jsonl"
    path.write_text("", encoding="utf-8")
    return path


def test_status_reports_running_with_minutes_and_tool_calls(root: Path):
    jobs_dir = root / "jobs"
    _write_job(jobs_dir, "20261102T095500Z-aaaaaaaa", phase="running", started=_ago(minutes=5), activity=_ago(minutes=1))
    lines = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)
    assert len(lines) == 1
    assert lines[0].startswith("RUNNING 20261102T095500Z-aaaaaaaa 5m,")
    assert "17 tool calls" in lines[0]


def test_status_reports_a_stalled_worker(root: Path):
    jobs_dir = root / "jobs"
    _write_job(jobs_dir, "20261102T093000Z-bbbbbbbb", phase="running", started=_ago(hours=1), activity=_ago(minutes=12))
    lines = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)
    assert len(lines) == 1
    assert lines[0].startswith("STALLED 20261102T093000Z-bbbbbbbb no activity for 12m")


def test_status_reports_failed_and_lost_jobs_as_ended_badly(root: Path):
    jobs_dir = root / "jobs"
    _write_job(jobs_dir, "20261102T090000Z-cccccccc", phase="failed", started=_ago(hours=1), outcome="error")
    _write_job(jobs_dir, "20261102T091000Z-dddddddd", phase="lost", started=_ago(minutes=50))
    _write_job(jobs_dir, "20261102T092000Z-eeeeeeee", phase="cancelled", started=_ago(minutes=40), outcome="cancelled")
    lines = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)
    assert len(lines) == 3
    assert all(line.startswith("ENDED BADLY") for line in lines)
    assert {line.split()[2] for line in lines} == {
        "20261102T090000Z-cccccccc",
        "20261102T091000Z-dddddddd",
        "20261102T092000Z-eeeeeeee",
    }


def test_status_reports_an_expired_lease_as_ended_badly(root: Path):
    jobs_dir = root / "jobs"
    job_dir = _write_job(jobs_dir, "20261102T080000Z-ffffffff", phase="running", started=_ago(hours=3), activity=_ago(minutes=90))
    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    status["controller_lease"] = {"deadline": _ago(minutes=70).isoformat()}
    (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    lines = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)
    assert lines == ["ENDED BADLY 20261102T080000Z-ffffffff lease expired with no renewal"]


def test_finished_job_without_a_review_row_needs_review(root: Path, monkeypatch):
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), "", set()))
    jobs_dir = root / "jobs"
    job_id = "20261102T070000Z-aaaaaaaa"
    _write_job(
        jobs_dir,
        job_id,
        phase="finished",
        started=_ago(hours=3),
        finished=_ago(hours=2),
        outcome="completed",
        branch=f"dsh/{job_id}",
    )
    lines = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)
    assert lines == [f"FINISHED, NEEDS REVIEW {job_id} dsh/{job_id}"]


def test_finished_job_with_a_review_row_is_silent(root: Path, monkeypatch):
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), "", set()))
    jobs_dir = root / "jobs"
    job_id = "20261102T060000Z-bbbbbbbb"
    _write_job(
        jobs_dir,
        job_id,
        phase="finished",
        started=_ago(hours=4),
        finished=_ago(hours=3),
        outcome="completed",
        branch=f"dsh/{job_id}",
    )
    reviews = root / "reviews.jsonl"
    reviews.write_text(json.dumps({"id": job_id}) + "\n", encoding="utf-8")
    assert job_watch.status(jobs_dir, reviews, root / "state.json", root, now=NOW) == []


def test_finished_job_whose_branch_is_merged_is_silent(root: Path, monkeypatch):
    jobs_dir = root / "jobs"
    job_id = "20261102T050000Z-cccccccc"
    _write_job(
        jobs_dir,
        job_id,
        phase="finished",
        started=_ago(hours=5),
        finished=_ago(hours=4),
        outcome="completed",
        branch=f"dsh/{job_id}",
    )
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: ({f"dsh/{job_id}"}, "", {f"dsh/{job_id}"}))
    assert job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW) == []


def test_corrupt_status_json_is_skipped_not_raised(root: Path):
    jobs_dir = root / "jobs"
    bad = jobs_dir / "20261102T040000Z-dddddddd"
    bad.mkdir(parents=True)
    (bad / "status.json").write_text("{not json", encoding="utf-8")
    assert job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW) == []


def test_quiet_folders_older_than_48_hours_are_not_read(root: Path):
    jobs_dir = root / "jobs"
    job_dir = _write_job(
        jobs_dir,
        "20261031T010000Z-eeeeeeee",
        phase="failed",
        started=NOW - timedelta(days=3),
        outcome="error",
    )
    old = (NOW - timedelta(days=3)).timestamp()
    os.utime(job_dir / "status.json", (old, old))
    os.utime(job_dir, (old, old))
    assert job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW) == []


def test_output_never_exceeds_twelve_lines(root: Path):
    jobs_dir = root / "jobs"
    for index in range(15):
        _write_job(
            jobs_dir,
            f"20261102T09{index:02d}00Z-aaaaaaaa",
            phase="failed",
            started=_ago(minutes=60 - index),
            outcome="error",
        )
    lines = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)
    assert len(lines) == job_watch.MAX_LINES == 12


def test_old_live_jobs_stay_above_the_cap_ahead_of_newer_failures(root: Path):
    jobs_dir = root / "jobs"
    for index in range(15):
        _write_job(
            jobs_dir,
            f"20261102T09{index:02d}00Z-aaaaaaaa",
            phase="failed",
            started=_ago(minutes=60 - index),
            outcome="error",
        )
    _write_job(jobs_dir, "20261102T010000Z-bbbbbbbb", phase="running", started=_ago(minutes=100), activity=_ago(minutes=1))
    _write_job(jobs_dir, "20261102T020000Z-cccccccc", phase="running", started=_ago(minutes=90), activity=_ago(minutes=30))
    lines = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)
    assert len(lines) == 12
    assert lines[0].startswith("STALLED 20261102T020000Z-cccccccc")
    assert lines[1].startswith("RUNNING 20261102T010000Z-bbbbbbbb")


def test_failed_job_with_a_review_row_is_silent(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T090000Z-dddddddd"
    _write_job(jobs_dir, job_id, phase="failed", started=_ago(hours=1), outcome="error")
    reviews = root / "reviews.jsonl"
    reviews.write_text(json.dumps({"id": job_id}) + "\n", encoding="utf-8")
    assert job_watch.status(jobs_dir, reviews, root / "state.json", root, now=NOW) == []


def test_merge_subject_naming_the_job_or_its_branch_silences_it(root: Path, monkeypatch):
    jobs_dir = root / "jobs"
    hp_job = "hp-20261101T172002-15e0f2"
    _write_job(jobs_dir, hp_job, phase="finished", started=_ago(hours=4), finished=_ago(hours=3), outcome="ok", host="hp")
    continued = "20261102T070000Z-aaaaaaaa"
    first = "dsh/20261102T060000Z-bbbbbbbb"
    _write_job(jobs_dir, continued, phase="finished", started=_ago(hours=3), finished=_ago(hours=2), outcome="completed", branch=first)
    subjects = f"merge: dsh-hp/{hp_job} reviewed\nMerge {first} [dsh 20261102T060000Z-bbbbbbbb]\n"
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), subjects, set()))
    assert job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW) == []


def test_registered_log_that_went_quiet_is_stalled(root: Path):
    jobs_dir = root / "jobs"
    log = root / "backfill.log"
    log.write_text("started\n", encoding="utf-8")
    old = _ago(minutes=20).timestamp()
    os.utime(log, (old, old))
    state = root / "state.json"
    state.write_text(
        json.dumps({"jobs": {"backfill": {"log": str(log), "added_at": _ago(hours=1).isoformat()}}}),
        encoding="utf-8",
    )
    lines = job_watch.status(jobs_dir, _empty_reviews(root), state, root, now=NOW)
    assert lines == ["STALLED backfill log quiet for 20m"]


def test_registered_pid_that_is_gone_is_ended(root: Path):
    jobs_dir = root / "jobs"
    log = root / "fresh.log"
    log.write_text("running\n", encoding="utf-8")
    state = root / "state.json"
    state.write_text(
        json.dumps(
            {"jobs": {"extract": {"log": str(log), "pid": 2**31 - 1, "added_at": _ago(minutes=1).isoformat()}}}
        ),
        encoding="utf-8",
    )
    lines = job_watch.status(jobs_dir, _empty_reviews(root), state, root, now=NOW)
    assert lines == [f"ENDED extract pid {2**31 - 1} is gone"]


def test_add_records_a_process_and_main_never_raises(root: Path):
    state = root / "state.json"
    log = root / "job.log"
    log.write_text("x\n", encoding="utf-8")
    job_watch.add("nightly", str(log), 424242, state)
    recorded = json.loads(state.read_text(encoding="utf-8"))["jobs"]["nightly"]
    assert recorded["pid"] == 424242
    assert Path(recorded["log"]) == log.resolve()
    assert job_watch.main(["nonsense"]) == 0


def _registered_state(root: Path, name: str, log: Path, **extra) -> Path:
    state = root / "state.json"
    record = {"log": str(log), "added_at": _ago(hours=1).isoformat(), **extra}
    state.write_text(json.dumps({"jobs": {name: record}}), encoding="utf-8")
    return state


def test_record_stall_window_overrides_the_five_minute_default(root: Path):
    """T-053: an OCR run commits every ~20 pages, so it registers its own window."""
    log = root / "ocr.log"
    log.write_text("page 20\n", encoding="utf-8")
    old = _ago(minutes=20).timestamp()
    os.utime(log, (old, old))
    state = _registered_state(root, "ocr", log, stall_seconds=3600)
    assert job_watch.status(root / "jobs", _empty_reviews(root), state, root, now=NOW) == []


def test_record_stall_window_still_stalls_past_its_own_window(root: Path):
    log = root / "backfill.log"
    log.write_text("started\n", encoding="utf-8")
    old = _ago(minutes=20).timestamp()
    os.utime(log, (old, old))
    state = _registered_state(root, "backfill", log, stall_seconds=600)
    lines = job_watch.status(root / "jobs", _empty_reviews(root), state, root, now=NOW)
    assert lines == ["STALLED backfill log quiet for 20m"]


def test_registered_record_without_a_usable_window_uses_the_env(root: Path, monkeypatch):
    monkeypatch.setenv("JOB_WATCH_REGISTERED_STALL_SECONDS", "3600")
    log = root / "ocr.log"
    log.write_text("page 20\n", encoding="utf-8")
    old = _ago(minutes=20).timestamp()
    os.utime(log, (old, old))
    state = root / "state.json"
    state.write_text(
        json.dumps(
            {
                "jobs": {
                    "no_window": {"log": str(log), "added_at": _ago(hours=1).isoformat()},
                    "bad_window": {"log": str(log), "added_at": _ago(hours=1).isoformat(), "stall_seconds": "junk"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert job_watch.status(root / "jobs", _empty_reviews(root), state, root, now=NOW) == []


def test_live_registered_uses_the_record_window(root: Path, monkeypatch):
    monkeypatch.delenv("JOB_WATCH_REGISTERED_STALL_SECONDS", raising=False)
    log = root / "ocr.log"
    log.write_text("page 20\n", encoding="utf-8")
    aged = datetime.now(timezone.utc).timestamp() - 20 * 60
    os.utime(log, (aged, aged))
    state = _registered_state(root, "ocr", log, stall_seconds=3600)
    assert job_watch.live_registered(state) is True
    state = _registered_state(root, "ocr", log)
    assert job_watch.live_registered(state) is False


def test_add_stores_a_stall_window_and_main_parses_it(root: Path):
    log = root / "job.log"
    log.write_text("x\n", encoding="utf-8")
    assert job_watch.main(["add", "ocr", str(log), "--stall-seconds", "420"]) == 0
    recorded = json.loads(job_watch.STATE_PATH.read_text(encoding="utf-8"))["jobs"]["ocr"]
    assert recorded["stall_seconds"] == 420.0
    job_watch.add("plain", str(log), None, root / "plain.json")
    plain = json.loads((root / "plain.json").read_text(encoding="utf-8"))["jobs"]["plain"]
    assert "stall_seconds" not in plain


# ------------------------------------------------------------- wait and ack (T-050)
def _live_job(jobs_dir: Path, job_id: str) -> datetime:
    """A job started and active now, so the real clock in ``wait`` sees it live."""
    started = datetime.now(timezone.utc)
    _write_job(jobs_dir, job_id, phase="running", started=started, activity=started)
    return started


def _waiter_files(wait_dir: Path) -> list[Path]:
    return sorted(wait_dir.glob("*.json")) if wait_dir.exists() else []


def test_wait_reports_a_finish_that_landed_before_its_baseline(root: Path, monkeypatch):
    """T-053: the baseline must not swallow a finish that landed while Claude was busy."""
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), "", set()))
    jobs_dir = root / "jobs"
    finished_id = "20261103T100000Z-aaaaaaaa"
    started = datetime.now(timezone.utc)
    _write_job(jobs_dir, finished_id, phase="finished", started=started, finished=started, outcome="completed")
    _live_job(jobs_dir, "20261103T100100Z-bbbbbbbb")
    began = time.monotonic()
    lines = job_watch.wait(
        timeout_seconds=30,
        poll_seconds=0.05,
        jobs_dir=jobs_dir,
        reviews_path=_empty_reviews(root),
        state_path=root / "state.json",
        repo_root=root,
        wait_dir=root / "waiters",
    )
    assert lines == [f"FINISHED, NEEDS REVIEW {finished_id} branch unknown"]
    assert time.monotonic() - began < 5
    assert _waiter_files(root / "waiters") == []


def test_wait_ignore_existing_keeps_the_old_baseline(root: Path, monkeypatch):
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), "", set()))
    jobs_dir = root / "jobs"
    started = datetime.now(timezone.utc)
    _write_job(jobs_dir, "20261103T100200Z-cccccccc", phase="finished", started=started, finished=started)
    _live_job(jobs_dir, "20261103T100300Z-dddddddd")
    lines = job_watch.wait(
        timeout_seconds=0.3,
        poll_seconds=0.05,
        jobs_dir=jobs_dir,
        reviews_path=_empty_reviews(root),
        state_path=root / "state.json",
        repo_root=root,
        wait_dir=root / "waiters",
        ignore_existing=True,
    )
    assert lines[0].startswith("TIMEOUT still running: ")


def test_wait_returns_when_a_job_turns_finished(root: Path, monkeypatch):
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), "", set()))
    jobs_dir = root / "jobs"
    job_id = "20261103T100000Z-aaaaaaaa"
    started = _live_job(jobs_dir, job_id)
    wait_dir = root / "waiters"
    seen: dict = {}

    def finish() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not _waiter_files(wait_dir):
            time.sleep(0.01)
        seen.update(json.loads(_waiter_files(wait_dir)[0].read_text(encoding="utf-8")))
        time.sleep(0.1)  # let the baseline settle on RUNNING
        _write_job(
            jobs_dir,
            job_id,
            phase="finished",
            started=started,
            finished=datetime.now(timezone.utc),
            outcome="completed",
        )

    thread = threading.Thread(target=finish)
    thread.start()
    try:
        lines = job_watch.wait(
            timeout_seconds=10,
            poll_seconds=0.05,
            jobs_dir=jobs_dir,
            reviews_path=_empty_reviews(root),
            state_path=root / "state.json",
            repo_root=root,
            wait_dir=wait_dir,
        )
    finally:
        thread.join()
    assert lines == [f"FINISHED, NEEDS REVIEW {job_id} branch unknown"]
    assert seen.get("pid") == os.getpid()
    assert seen.get("started_at")
    assert seen.get("created_at") is not None or job_watch._process_started(os.getpid()) is None
    assert _waiter_files(wait_dir) == []


def test_wait_times_out_and_removes_its_waiter_file(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261103T090000Z-bbbbbbbb"
    _live_job(jobs_dir, job_id)
    wait_dir = root / "waiters"
    lines = job_watch.wait(
        timeout_seconds=0.3,
        poll_seconds=0.05,
        jobs_dir=jobs_dir,
        reviews_path=_empty_reviews(root),
        state_path=root / "state.json",
        repo_root=root,
        wait_dir=wait_dir,
    )
    assert len(lines) == 1
    assert lines[0].startswith(f"TIMEOUT still running: RUNNING {job_id} ")
    assert _waiter_files(wait_dir) == []


def test_wait_returns_at_once_when_nothing_is_live(root: Path):
    wait_dir = root / "waiters"
    lines = job_watch.wait(
        timeout_seconds=5,
        poll_seconds=0.05,
        jobs_dir=root / "jobs",
        reviews_path=_empty_reviews(root),
        state_path=root / "state.json",
        repo_root=root,
        wait_dir=wait_dir,
    )
    assert lines == []
    assert _waiter_files(wait_dir) == []


def test_waiter_file_is_removed_when_polling_raises(root: Path, monkeypatch):
    real_status = job_watch.status
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:  # the first call is the baseline
            raise RuntimeError("status broke")
        return real_status(*args, **kwargs)

    monkeypatch.setattr(job_watch, "status", flaky)
    wait_dir = root / "waiters"
    with pytest.raises(RuntimeError):
        job_watch.wait(
            timeout_seconds=5,
            poll_seconds=0.01,
            jobs_dir=root / "jobs",
            reviews_path=_empty_reviews(root),
            state_path=root / "state.json",
            repo_root=root,
            wait_dir=wait_dir,
        )
    assert _waiter_files(wait_dir) == []


def test_waiter_alive_needs_a_live_pid_and_matching_creation_time(root: Path):
    wait_dir = root / "waiters"
    wait_dir.mkdir()
    live = wait_dir / f"{os.getpid()}.json"
    dead = wait_dir / f"{2**31 - 1}.json"
    dead.write_text(json.dumps({"pid": 2**31 - 1}), encoding="utf-8")
    assert job_watch.waiter_alive(wait_dir) is False
    live.write_text(json.dumps({"pid": os.getpid(), "started_at": "now"}), encoding="utf-8")
    assert job_watch.waiter_alive(wait_dir) is True
    created = job_watch._process_started(os.getpid())
    if created is not None:
        live.write_text(json.dumps({"pid": os.getpid(), "created_at": created - 600}), encoding="utf-8")
        assert job_watch.waiter_alive(wait_dir) is False, "a reused pid with another creation time is dead"
        live.write_text(json.dumps({"pid": os.getpid(), "created_at": created}), encoding="utf-8")
        assert job_watch.waiter_alive(wait_dir) is True


def test_ack_hides_a_failed_job_and_removes_a_registered_name(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261103T080000Z-cccccccc"
    started = datetime.now(timezone.utc)
    _write_job(jobs_dir, job_id, phase="failed", started=started, outcome="error")
    log = root / "backfill.log"
    log.write_text("running\n", encoding="utf-8")
    state = root / "state.json"
    state.write_text(
        json.dumps({"jobs": {"backfill": {"log": str(log), "added_at": started.isoformat()}}}),
        encoding="utf-8",
    )
    reviews = _empty_reviews(root)
    assert job_watch.status(jobs_dir, reviews, state, root) == [f"ENDED BADLY {job_id} failed: error"]
    assert job_watch.ack(job_id, "read the diff", state) is False
    assert job_watch.status(jobs_dir, reviews, state, root) == []
    assert job_watch.ack("backfill", state_path=state) is True
    assert "backfill" not in json.loads(state.read_text(encoding="utf-8"))["jobs"]
    acked = json.loads((root / "acks.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert acked["id"] == job_id
    assert acked["note"] == "read the diff"
    assert acked["acked_at"]


# --------------------------------------------- T-096: reply waits, acks, live counts
def _reply_wait(job_dir: Path, since: datetime, deadline: datetime | None) -> None:
    """heartbeat.json as the launcher writes it, flags nested under ``heartbeat``."""
    (job_dir / "heartbeat.json").write_text(
        json.dumps(
            {
                "awaiting_input": True,
                "heartbeat": {
                    "awaiting_input": True,
                    "awaiting_since": since.isoformat(),
                    "awaiting_deadline": deadline.isoformat().replace("+00:00", "Z") if deadline else None,
                    "last_activity_at": since.isoformat(),
                },
            }
        ),
        encoding="utf-8",
    )


def _ack_at(root: Path, job_id: str, moment: datetime) -> None:
    with (root / "acks.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": job_id, "acked_at": moment.isoformat()}) + "\n")


def _lines(root: Path, jobs_dir: Path) -> list[str]:
    return job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW)


def test_a_reply_wait_reads_waiting_at_once_with_the_deadline(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T090000Z-aaaaaaaa"
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=1))
    _reply_wait(job_dir, _ago(minutes=1), NOW + timedelta(minutes=59))
    assert _lines(root, jobs_dir) == [f"WAITING {job_id} for a reply 1m, 17 tool calls, wait ends in 59m"]


def test_a_long_reply_wait_is_waiting_not_stalled(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T080000Z-aaaaaaaa"
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=34))
    _reply_wait(job_dir, _ago(minutes=34), NOW + timedelta(minutes=26))
    assert _lines(root, jobs_dir)[0].startswith(f"WAITING {job_id} for a reply 34m")


@pytest.mark.parametrize("deadline", [None, NOW - timedelta(minutes=5), NOW + timedelta(hours=3)])
def test_a_reply_wait_without_a_valid_deadline_falls_back_to_the_stall_rule(root: Path, deadline):
    """A wedged launcher can leave the flag set; core._awaiting_input_valid refuses it the same way."""
    jobs_dir = root / "jobs"
    job_id = "20261102T080000Z-bbbbbbbb"
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=34))
    _reply_wait(job_dir, _ago(minutes=34), deadline)
    assert _lines(root, jobs_dir)[0].startswith(f"STALLED {job_id} no activity for 34m")


def test_reply_wait_reads_the_supervisor_copy_when_the_heartbeat_file_is_half_written(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T080000Z-cccccccc"
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=2))
    (job_dir / "heartbeat.json").write_text('{"awaiting_in', encoding="utf-8")
    record = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    record["heartbeat_live"] = {
        "awaiting_input": True,
        "awaiting_since": _ago(minutes=2).isoformat(),
        "awaiting_deadline": (NOW + timedelta(minutes=58)).isoformat(),
    }
    (job_dir / "status.json").write_text(json.dumps(record), encoding="utf-8")
    assert _lines(root, jobs_dir)[0].startswith(f"WAITING {job_id}")


def test_ack_clears_a_stall_until_the_worker_acts_again(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T080000Z-dddddddd"
    _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=30))
    assert _lines(root, jobs_dir)[0].startswith("STALLED")
    _ack_at(root, job_id, _ago(minutes=25))
    assert _lines(root, jobs_dir) == [f"ACKED {job_id} stalled 30m, 17 tool calls"]
    assert job_watch.live_jobs(jobs_dir, NOW, skip_acked=True, acks_path=root / "acks.jsonl") is False
    # The worker acts after the ack and is healthy.
    _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=3))
    assert _lines(root, jobs_dir)[0].startswith("RUNNING")
    # It acted after the ack and then went quiet: a new stall, raised afresh.
    _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=15))
    assert _lines(root, jobs_dir)[0].startswith("STALLED")


def test_ack_before_a_stall_began_does_not_hide_it(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T080000Z-eeeeeeee"
    _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=30))
    _ack_at(root, job_id, _ago(minutes=40))
    assert _lines(root, jobs_dir)[0].startswith("STALLED")


def test_ack_clears_a_reply_wait_and_the_next_wait_is_raised_afresh(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T080000Z-ffffffff"
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=30))
    _reply_wait(job_dir, _ago(minutes=30), NOW + timedelta(minutes=30))
    _ack_at(root, job_id, _ago(minutes=20))
    assert _lines(root, jobs_dir) == [f"ACKED {job_id} waiting for a reply 30m, 17 tool calls"]
    assert job_watch.live_jobs(jobs_dir, NOW) is True
    assert job_watch.live_jobs(jobs_dir, NOW, skip_acked=True, acks_path=root / "acks.jsonl") is False
    _reply_wait(job_dir, _ago(minutes=2), NOW + timedelta(minutes=58))
    assert _lines(root, jobs_dir)[0].startswith(f"WAITING {job_id}")
    assert job_watch.live_jobs(jobs_dir, NOW, skip_acked=True, acks_path=root / "acks.jsonl") is True


def test_ack_of_a_live_job_does_not_hide_its_later_finish_or_failure(root: Path, monkeypatch):
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), "", set()))
    jobs_dir = root / "jobs"
    done_id, bad_id = "20261102T060000Z-aaaaaaaa", "20261102T060000Z-bbbbbbbb"
    _ack_at(root, done_id, _ago(minutes=30))
    _ack_at(root, bad_id, _ago(minutes=30))
    _write_job(jobs_dir, done_id, phase="finished", started=_ago(hours=2), finished=_ago(minutes=5), outcome="completed")
    _write_job(jobs_dir, bad_id, phase="failed", started=_ago(hours=2), finished=_ago(minutes=5), outcome="error")
    lines = _lines(root, jobs_dir)
    assert any(line.startswith(f"FINISHED, NEEDS REVIEW {done_id}") for line in lines)
    assert any(line.startswith(f"ENDED BADLY {bad_id}") for line in lines)
    _ack_at(root, done_id, _ago(minutes=1))
    _ack_at(root, bad_id, _ago(minutes=1))
    assert _lines(root, jobs_dir) == []


def test_a_reply_restarts_the_stall_window(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T080000Z-abababab"
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=_ago(hours=1), activity=_ago(minutes=30))
    steering = job_dir / "steering.jsonl"
    steering.write_text("{}\n", encoding="utf-8")
    os.utime(steering, (_ago(minutes=1).timestamp(), _ago(minutes=1).timestamp()))
    assert _lines(root, jobs_dir)[0].startswith("RUNNING")


def test_tool_count_is_the_events_count_not_the_lagging_digest(root: Path):
    server = str(REPO_ROOT / "plugins" / "dsh-worker" / "server")
    sys.path.insert(0, server)
    import progress

    jobs_dir = root / "jobs"
    job_id = "20261102T090000Z-cdcdcdcd"
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=_ago(minutes=30), activity=_ago(minutes=1), tool_calls=270)
    events = [
        {"type": "tool_call", "tool": "read", "input": {"file_path": "a.py"}},
        {"type": "tool_result", "tool": "read", "output": "the word tool_call in a result"},
        {"type": "text", "text": '{"type": "tool_call"}'},
        {"type": "tool_call", "tool": "pwsh", "input": {"nested": {"type": "tool_call"}}},
        {"type": "status", "phase": "step_end"},
    ]
    path = job_dir / job_watch.EVENTS_FILE
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    assert _lines(root, jobs_dir) == [f"RUNNING {job_id} 30m, 2 tool calls"]
    assert progress.EventScanner().scan(path)["tool_calls"] == 2
    assert progress.MAX_LINE_BYTES == job_watch.MAX_EVENT_LINE_BYTES
    # A half-written last line is not counted until the launcher finishes it, as in the scanner.
    with path.open("ab") as handle:
        handle.write(b'{"type": "tool_call", "tool": "rea')
    assert _lines(root, jobs_dir) == [f"RUNNING {job_id} 30m, 2 tool calls"]
    assert progress.EventScanner().scan(path)["tool_calls"] == 2


def test_wait_wakes_when_a_running_worker_starts_waiting(root: Path):
    jobs_dir = root / "jobs"
    job_id = "20261102T090000Z-efefefef"
    now = datetime.now(timezone.utc)
    job_dir = _write_job(jobs_dir, job_id, phase="running", started=now, activity=now)
    timer = threading.Timer(0.2, _reply_wait, (job_dir, now, now + timedelta(minutes=59)))
    timer.start()
    try:
        lines = job_watch.wait(
            timeout_seconds=20,
            poll_seconds=0.05,
            jobs_dir=jobs_dir,
            reviews_path=_empty_reviews(root),
            state_path=root / "state.json",
            repo_root=root,
            acks_path=root / "acks.jsonl",
            wait_dir=root / "waiters",
        )
    finally:
        timer.join()
    assert len(lines) == 1 and lines[0].startswith(f"WAITING {job_id}")


def test_wait_raises_a_second_stall_after_the_baseline_one_cleared(root: Path, monkeypatch):
    """--ignore-existing: a stall in the baseline that clears and returns is a new event."""
    frames = iter(
        [
            ["STALLED job no activity for 12m, 1 tool calls"],  # baseline
            ["RUNNING job 20m, 2 tool calls"],
            ["STALLED job no activity for 11m, 3 tool calls"],
        ]
    )
    monkeypatch.setattr(job_watch, "status", lambda *args, **kwargs: next(frames))
    monkeypatch.setattr(job_watch, "live_jobs", lambda *args, **kwargs: True)
    lines = job_watch.wait(
        timeout_seconds=20, poll_seconds=0.01, jobs_dir=root / "jobs", state_path=root / "state.json",
        wait_dir=root / "waiters", ignore_existing=True,
    )
    assert lines == ["STALLED job no activity for 11m, 3 tool calls"]


def test_finished_job_whose_branch_was_deleted_is_hidden(root: Path, monkeypatch):
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), "", {"main", "T-049"}))
    jobs_dir = root / "jobs"
    job_id = "20261102T050000Z-dddddddd"
    _write_job(
        jobs_dir,
        job_id,
        phase="finished",
        started=_ago(hours=5),
        finished=_ago(hours=4),
        outcome="completed",
        branch=f"dsh/{job_id}",
    )
    assert job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root, now=NOW) == []


def test_main_ack_all_ended_clears_the_ended_lines_only(root: Path, monkeypatch, capsys):
    monkeypatch.setattr(
        job_watch,
        "status",
        lambda: [
            "ENDED BADLY a failed: x",
            "ENDED b pid 42 is gone",
            "FINISHED, NEEDS REVIEW c dsh/c",
            "STALLED d log quiet for 6m",
        ],
    )
    assert job_watch.main(["ack", "--all-ended"]) == 0
    assert "acked 2 ended line(s)" in capsys.readouterr().out
    ids = {
        json.loads(line)["id"]
        for line in (root / "acks.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert ids == {"a", "b"}


def test_live_jobs_sees_past_the_twelve_line_cap(root: Path):
    jobs_dir = root / "jobs"
    for index in range(15):
        _live_job(jobs_dir, f"20261103T09{index:02d}00Z-aaaaaaaa")
    shown = job_watch.status(jobs_dir, _empty_reviews(root), root / "state.json", root)
    assert len(shown) == job_watch.MAX_LINES
    assert job_watch.live_jobs(jobs_dir) is True


def test_main_wait_accepts_its_flags(monkeypatch):
    seen: dict = {}

    def fake_wait(**kwargs):
        seen.update(kwargs)
        return [f"TIMEOUT still running: {kwargs['timeout_seconds']}/{kwargs['poll_seconds']}"]

    monkeypatch.setattr(job_watch, "wait", fake_wait)
    assert job_watch.main(["wait", "--timeout-seconds", "2", "--poll-seconds", "0.05", "--ignore-existing"]) == 0
    assert seen == {"timeout_seconds": 2.0, "poll_seconds": 0.05, "ignore_existing": True}
