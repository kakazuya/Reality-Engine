"""T-044: list_workers ordering and the prompt-time job watch.

Fixtures live under the repository ``.tmp`` (the sandbox temp folder has an ACL
fault) and are removed by the ``root`` fixture.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
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
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), ""))
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
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: (set(), ""))
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
    monkeypatch.setattr(job_watch, "_merge_snapshot", lambda repo: ({f"dsh/{job_id}"}, ""))
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
