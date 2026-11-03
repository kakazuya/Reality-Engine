"""T-050: the Stop hook blocks a turn while work is unreviewed or unwatched.

Fixtures live under the repository ``.tmp`` (the sandbox temp folder has an ACL
fault) and are removed by the ``root`` fixture.  No live runtime record is read:
``job_watch`` is patched in the one test that goes through ``main``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from reality_engine.scripts import session_hooks

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reality_engine" / "scripts"))

import job_watch  # noqa: E402  (the same module session_hooks imports)

TEST_TMP = Path(__file__).resolve().parents[2] / ".tmp" / "session_hook_tests"


@pytest.fixture()
def root() -> Iterator[Path]:
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    path = TEST_TMP / uuid.uuid4().hex[:12]
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _reason(output: str) -> str:
    return json.loads(output)["reason"]


def test_stop_blocks_on_a_finished_job_that_needs_review():
    output = session_hooks.stop_output({}, ["FINISHED, NEEDS REVIEW job dsh/job"])
    assert json.loads(output)["decision"] == "block"
    assert "review or ack" in _reason(output)


def test_stop_blocks_on_an_ended_badly_line():
    assert "review or ack" in _reason(session_hooks.stop_output({}, ["ENDED BADLY job failed: x"]))


def test_stop_blocks_a_running_job_with_no_waiter_armed():
    output = session_hooks.stop_output({}, ["RUNNING job 3m, 17 tool calls"], live_work=True)
    assert "arm a wait" in _reason(output)


def test_stop_passes_a_running_job_behind_a_live_waiter(root: Path):
    wait_dir = root / "waiters"
    wait_dir.mkdir()
    waiter = wait_dir / f"{os.getpid()}.json"
    waiter.write_text(json.dumps({"pid": os.getpid(), "started_at": "now"}), encoding="utf-8")
    assert job_watch.waiter_alive(wait_dir) is True
    assert (
        session_hooks.stop_output(
            {}, ["RUNNING job 3m, 17 tool calls"], live_work=True, waiter=job_watch.waiter_alive(wait_dir)
        )
        == ""
    )
    waiter.unlink()
    (wait_dir / f"{2**31 - 1}.json").write_text(json.dumps({"pid": 2**31 - 1}), encoding="utf-8")
    assert job_watch.waiter_alive(wait_dir) is False


def test_stop_never_blocks_twice_or_inside_the_doc_loop(monkeypatch):
    lines = ["FINISHED, NEEDS REVIEW job dsh/job"]
    assert session_hooks.stop_output({"stop_hook_active": True}, lines, live_work=True) == ""
    monkeypatch.setenv("DOC_REVIEW_LOOP", "1")
    assert session_hooks.stop_output({}, lines, live_work=True) == ""


def test_stop_main_arms_a_wait_then_passes_behind_the_recorded_pid(root: Path, monkeypatch):
    monkeypatch.setattr(job_watch, "status", lambda *args, **kwargs: ["RUNNING job 3m, 17 tool calls"])
    monkeypatch.setattr(job_watch, "live_jobs", lambda: True)
    monkeypatch.setattr(job_watch, "live_registered", lambda: False)
    monkeypatch.setattr(job_watch, "WAIT_DIR", root / "waiters")
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert session_hooks.main(["stop"]) == 0
    assert "arm a wait" in _reason(output.getvalue())

    (root / "waiters").mkdir()
    (root / "waiters" / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert session_hooks.main(["stop"]) == 0
    assert output.getvalue() == ""


def test_stop_main_blocks_before_arming_on_an_unreviewed_finish(monkeypatch):
    monkeypatch.setattr(job_watch, "status", lambda *args, **kwargs: ["FINISHED, NEEDS REVIEW job dsh/job"])
    monkeypatch.setattr(job_watch, "live_jobs", lambda: False)
    monkeypatch.setattr(job_watch, "live_registered", lambda: False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert session_hooks.main(["stop"]) == 0
    assert "review or ack" in _reason(output.getvalue())


def test_stop_main_never_raises_on_broken_input(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("{"))
    assert session_hooks.main(["stop"]) == 0
