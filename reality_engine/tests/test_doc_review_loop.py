"""T-045: the Haiku doc loop's queue, batching and guards, and the session hooks. No model call."""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts import doc_review_loop as loop
from reality_engine.scripts import session_hooks

REPO = Path(__file__).resolve().parents[2]
TMP = REPO / ".tmp" / "doc_review_tests"


def run(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture()
def repo():
    TMP.mkdir(parents=True, exist_ok=True)
    root = TMP / uuid.uuid4().hex[:10]
    root.mkdir()
    run(root, "init", "-q")
    run(root, "config", "user.email", "t@t")
    run(root, "config", "user.name", "t")
    run(root, "config", "core.hooksPath", "NUL")
    (root / "tasks/handoff").mkdir(parents=True)
    (root / "tasks/ar_study/text").mkdir(parents=True)
    (root / "tasks/master_bank").mkdir(parents=True)
    (root / loop.PROGRESS).write_text(",".join(loop.FIELDS) + "\ndone.md,1,1,kept,,\nhalf.md,30,10,changed-partial,,\n", encoding="utf-8")
    (root / "done.md").write_text("x\n", encoding="utf-8")
    (root / "half.md").write_text("line\n" * 30, encoding="utf-8")
    (root / "big.md").write_text("word word word\n" * 100, encoding="utf-8")
    (root / "small.md").write_text("a\nb\n", encoding="utf-8")
    (root / "code.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tasks/ar_study/text/AR.txt").write_text("page\n", encoding="utf-8")
    (root / "tasks/master_bank/BANK.md").write_text("bank\n", encoding="utf-8")
    run(root, "add", "-A")
    run(root, "commit", "-q", "-m", "base")
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_queue_skips_finished_and_resumes_partial(repo):
    rows = loop.read_progress(repo)
    assert loop.settle_unsent(repo, rows) == 2
    queue = loop.build_queue(repo, rows)
    assert [i.file for i in queue] == ["small.md", "half.md", "big.md"]
    assert next(i for i in queue if i.file == "half.md").start == 11


def test_protected_and_generated_are_recorded_not_queued(repo):
    rows = loop.read_progress(repo)
    loop.settle_unsent(repo, rows)
    state = {r["file"]: r["outcome"] for r in rows}
    assert state["tasks/master_bank/BANK.md"] == "skipped-protected"
    assert state["tasks/ar_study/text/AR.txt"] == "pending-generated"


def test_batch_cuts_a_large_file_at_the_budget(repo):
    rows = loop.read_progress(repo)
    queue = [i for i in loop.build_queue(repo, rows) if i.file == "big.md"]
    batch = loop.next_batch(repo, queue, max_chars=230)
    assert len(batch) == 1 and batch[0].start == 1 and batch[0].end == 10 and not batch[0].complete


def test_guard_restores_outside_edits_deletions_and_large_cuts(repo):
    batch = [loop.Item("big.md", 100, 1, 100), loop.Item("small.md", 2, 1, 2), loop.Item("half.md", 30, 11, 30)]
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "new.md").write_text("new\n", encoding="utf-8")
    (repo / "small.md").unlink()
    (repo / "big.md").write_text("word\n" * 10, encoding="utf-8")
    (repo / "half.md").write_text("line\n" * 29 + "fixed\n", encoding="utf-8")
    reverted = loop.guard_changes(repo, batch, None)
    assert set(reverted) == {"code.py", "new.md", "small.md", "big.md"}
    assert (repo / "code.py").read_text(encoding="utf-8").strip() == "x = 1"
    assert not (repo / "new.md").exists() and (repo / "small.md").exists()
    assert "fixed" in (repo / "half.md").read_text(encoding="utf-8")


def test_record_marks_partial_and_reverted(repo):
    rows = loop.read_progress(repo)
    batch = [loop.Item("big.md", 100, 1, 40), loop.Item("small.md", 2, 1, 2)]
    result = loop.Result(rows=[{"file": "big.md", "outcome": "changed", "reason": "r"}, {"file": "small.md", "outcome": "kept", "reason": ""}])
    loop.record(rows, batch, result, {"small.md": "new file"})
    state = {r["file"]: r for r in rows}
    assert state["big.md"]["outcome"] == "changed-partial" and state["big.md"]["lines_read"] == 40
    assert state["small.md"]["outcome"] == "needs-review"


def test_parse_rows_takes_the_last_block():
    text = 'x\n```json\n[{"file":"a","outcome":"kept"}]\n```\ny\n```json\n[{"file":"b","outcome":"changed"}]\n```'
    assert [r["file"] for r in loop.parse_rows(text)] == ["b"]
    assert loop.parse_rows("no block") == []


def test_refuses_main(repo):
    run(repo, "branch", "-M", "main")
    assert loop.loop(repo, None, False, None) == 2


def test_stop_hook_blocks_once_on_a_stalled_job_only(monkeypatch):
    monkeypatch.delenv("DOC_REVIEW_LOOP", raising=False)
    stalled = ["STALLED job no activity for 12m"]
    assert json.loads(session_hooks.stop_output({}, stalled))["decision"] == "block"
    assert session_hooks.stop_output({"stop_hook_active": True}, stalled) == ""
    assert session_hooks.stop_output({}, ["RUNNING job 5m", "ENDED BADLY old"]) == ""
    monkeypatch.setenv("DOC_REVIEW_LOOP", "1")
    assert session_hooks.stop_output({}, stalled) == ""
