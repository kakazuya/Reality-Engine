"""Tests for the rule ledger: gate events, report sheets and the budget parser (T-042)."""
import json
import shutil
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts import doc_gate, rule_ledger


@pytest.fixture()
def workdir():
    """A fresh writable dir in the checkout; the machine's temp base is not writable here."""
    path = Path.cwd() / f"_rule_ledger_test_{uuid.uuid4().hex[:12]}"
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _fake_git(tmp_path, branch="main", staged=""):
    def git(*args):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return branch
        if args == ("diff", "--cached", "--name-only"):
            return staged
        if args[:2] == ("rev-parse", "--git-path"):
            return str(tmp_path / "NO_MERGE")
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        return ""
    return git


def test_doc_gate_block_and_pass_each_write_one_event(workdir, monkeypatch):
    log = workdir / "rule_events.jsonl"
    monkeypatch.setenv(rule_ledger.ENV_EVENTS, str(log))
    monkeypatch.setattr(doc_gate, "_git", _fake_git(workdir, staged="reality_engine/x.py"))
    assert doc_gate.main([]) == 1
    monkeypatch.setattr(doc_gate, "_git", _fake_git(workdir, staged="a.md"))
    assert doc_gate.main([]) == 0
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [event["outcome"] for event in events] == ["block", "pass"]
    assert {event["rule"] for event in events} == {"doc_gate"}


def test_unwritable_log_does_not_change_the_gate_result(workdir, monkeypatch):
    blocker = workdir / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(rule_ledger.ENV_EVENTS, str(blocker / "rule_events.jsonl"))
    monkeypatch.setattr(doc_gate, "_git", _fake_git(workdir, staged="reality_engine/x.py"))
    assert doc_gate.main([]) == 1
    monkeypatch.setattr(doc_gate, "_git", _fake_git(workdir, staged="a.md"))
    assert doc_gate.main([]) == 0
    assert not (blocker / "rule_events.jsonl").exists()


def test_rule_with_no_events_is_not_measured(workdir):
    rulings = workdir / "RULINGS.md"
    rulings.write_text("# rulings\n\n- Something nobody checks.\n", encoding="utf-8")
    rows = rule_ledger.rules_rows(rulings, [], measured_days=0)
    assert rows[0]["state"] == "not measured"
    assert rows[0]["how_enforced"] == "text only"


def _job(workdir, job, budget_line, before=3, calls=4):
    directory = workdir / "jobs" / job
    directory.mkdir(parents=True)
    (directory / "status.json").write_text(json.dumps({
        "job_id": job, "started_at": "2026-11-01T20:00:00+00:00",
        "finished_at": "2026-11-01T21:00:00+00:00", "outcome": "completed",
        "tool_calls_before_first_edit": before,
        "worktree_commit": {"branch": f"dsh/{job}"},
    }), encoding="utf-8")
    (directory / "brief.md").write_text(f"Goal: x\n{budget_line}\nTicket: T-001\n",
                                       encoding="utf-8")
    (directory / "result.md").write_text(
        "## 5) Tool calls\n- **3 before the first edit**\n- **4 total**\n", encoding="utf-8")
    with (directory / "result.md.events.jsonl").open("w", encoding="utf-8") as fh:
        for _ in range(calls):
            fh.write(json.dumps({"type": "tool_call", "tool": "read"}) + "\n")
    return directory


def test_budget_overrun_is_flagged_and_missing_budget_is_not_invented(workdir):
    over = "20261101T210210Z-521b20a9"
    _job(workdir, over, "Budget: 2 tool calls in total, 1 before the first edit.")
    _job(workdir, "20261101T205730Z-172d7dec", "No budget labelled here.")
    rows = rule_ledger.worker_rows(workdir / "jobs", {}, None)
    by_job = {row["job"]: row for row in rows}
    assert (by_job[over]["budget_total"], by_job[over]["budget_before_edit"]) == (2, 1)
    assert by_job[over]["over_total"] is True
    assert by_job[over]["over_before_edit"] is True
    assert by_job[over]["actual_total_calls"] == 4
    assert by_job[over]["actual_before_edit"] == 3
    assert by_job[over]["reported_total_calls"] == 4
    assert by_job[over]["reported_before_edit"] == 3
    missing = by_job["20261101T205730Z-172d7dec"]
    assert missing["budget_total"] is None and missing["budget_before_edit"] is None
    assert missing["over_total"] is None and missing["over_before_edit"] is None


def test_brief_context_pack_hint_does_not_shadow_the_real_budget():
    brief = ("## Worker context pack\n"
             "Budget: reach your first useful edit within <= 25 tool calls.\n"
             "Goal: x\n"
             "Budget: 90 tool calls in total, 20 before the first edit.\n"
             "Ticket: T-038\n")
    assert rule_ledger.parse_budget(brief) == (90, 20)
    assert rule_ledger.parse_budget(
        "Budget: reach your first useful edit within <= 25 tool calls.\nGoal: x\n") == (
        None, None)
    assert rule_ledger.parse_budget("Goal: x\n") == (None, None)


def _commits():
    return [
        {"hash": "m", "parents": ["a", "b"], "ct": 1793500000,
         "subject": "merge: dsh/20261101T210210Z-521b20a9 work (T-038, reviewed)",
         "files": [("reality_engine/x.py", 10, 2)]},
        {"hash": "d", "parents": ["c"], "ct": 1793500100,
         "subject": "fix the thing T-042",
         "files": [("reality_engine/y.py", 3, 1), ("tasks/STATE.md", 1, 0)]},
    ]


def test_direct_code_commit_is_direct_and_worker_merge_is_not():
    rows, summary = rule_ledger.chain_rows(_commits(), [], log_start=None)
    assert len(rows) == 1
    day = rows[0]
    assert day["worker_merges"] == 1
    assert day["worker_merge_py_lines"] == 12
    assert day["direct_commits"] == 1
    assert day["direct_py_lines"] == 4
    assert day["direct_other_lines"] == 1
    assert day["direct_code_commits"] == 1
    assert "T-042" in day["direct_code_examples"]
    assert len(summary["direct_code"]) == 1


def test_unmatched_commit_after_log_start_counts_as_possible_bypass():
    events = [{"rule": "ticket", "outcome": "pass",
               "detail": json.dumps({"subject": "fix the thing T-042"})}]
    rows, summary = rule_ledger.chain_rows(_commits(), events, log_start="2026-10-31")
    assert rows[0]["gate_bypasses"] == 1
    assert len(summary["bypasses"]) == 1


def test_known_budget_facts_are_reproduced():
    rows = [{"job": job, "budget_total": total, "budget_before_edit": before}
            for job, (total, before) in rule_ledger.KNOWN_BUDGETS.items()]
    assert all(ok for _, ok, _ in rule_ledger.known_fact_checks(rows))


def test_real_jobs_reproduce_the_known_budgets():
    jobs = rule_ledger.default_jobs_root(Path.cwd())
    if not jobs.is_dir():
        pytest.skip("no dsh job records on this machine")
    checks = rule_ledger.known_fact_checks(rule_ledger.worker_rows(jobs, {}, None))
    assert all(ok for _, ok, _ in checks), checks
