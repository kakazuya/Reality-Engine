"""T-048: the gap loop's checks, escalation, halving, round stop, sandbox guard and dry-run plan.

No model call: every tier is a fake or not reached.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from reality_engine.gap_loop import checks, loop, store, tiers
from reality_engine.scripts import job_watch
from reality_engine.scripts.session_runner import MODEL

REPO = Path(__file__).resolve().parents[2]
PAGE = ("Consolidated revenue from operations for FY26 was Rs 1,23,456 crore. "
        "EBITDA margin for FY26 was 8.7%.")
QUOTE = "Consolidated revenue from operations for FY26 was Rs 1,23,456 crore."


def sandbox() -> Path:
    # The harness's .tmp folder denies nested mkdir in this sandbox; its private TEMP folder does not.
    base = Path(os.environ.get("TEMP") or tempfile.gettempdir())
    root = base / f"kec_gap_{uuid.uuid4().hex[:8]}"
    (root / "questions").mkdir(parents=True)
    questions = [{"id": f"KEC{i:03d}", "question": f"question {i}?", "as_of": "2026-10-19"}
                 for i in range(1, 101)]
    (root / "questions" / "KEC_QUESTIONS.jsonl").write_text(
        "\n".join(json.dumps(row) for row in questions) + "\n", encoding="utf-8")
    return root


@pytest.fixture()
def root():
    path = sandbox()
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def conn(root):
    connection = store.connect(root)
    yield connection
    connection.close()


def unit(root: Path, size: int = 10, stage: str = "answer") -> loop.Unit:
    items = ([{"id": f"KEC{i:03d}"} for i in range(1, size + 1)] if stage != "fix"
             else [f"KEC{i:03d}" for i in range(1, size + 1)])
    return loop.Unit(id="answer-01", stage=stage, sandbox=root, items=items)


# --- the five checks ---------------------------------------------------------------------------

def test_quote_not_on_page_is_rejected():
    ok, reason = checks.check_quote("Revenue was 999 crore for FY26.", PAGE)
    assert not ok and "not on" in reason


def test_number_not_in_quote_is_rejected():
    ok, reason = checks.check_number(9999, "inr_cr", QUOTE)
    assert not ok and "does not occur" in reason
    assert checks.check_number(123456, "inr_cr", QUOTE)[0]          # Indian grouping + crore word
    assert checks.check_number(123000, "inr_cr", "order book of 1.23 lakh crore")[0]


def test_margin_stored_as_money_is_rejected():
    ok, reason = checks.check_unit("EBITDA margin", "inr_cr")
    assert not ok and "does not suit" in reason
    assert checks.check_unit("EBITDA margin", "pct")[0]
    assert checks.check_unit("order book", "inr_cr")[0]
    assert checks.check_unit("order intake growth", "pct")[0]


def test_known_at_after_as_of_is_rejected():
    ok, reason = checks.check_known_at("2026-11-01", "2026-10-19")
    assert not ok and "after the as-of" in reason
    ok, reason = checks.check_known_at("2026-05-15", "2026-10-19", "2026-06-30")
    assert not ok and "filing date" in reason


def test_period_must_be_stated():
    assert not checks.check_period("")[0]
    assert not checks.check_period("sometime")[0]
    for period in ("FY26", "Q1 FY27", "2026-06-30", "quarter ended 30 June 2026"):
        assert checks.check_period(period)[0], period


def test_a_checked_answer_row_needs_the_doc_text_page(root, conn):
    store.put_doc_text(conn, "bse:1", 4, PAGE, "text", "2026-05-15")
    lookup = store.page_lookup(conn)
    row = {"qid": "KEC001", "status": "answered", "answer": "FY26 revenue was 1,23,456 crore.",
           "numbers": [{"measure": "revenue", "value": 123456, "unit": "inr_cr", "period": "FY26",
                        "basis": "consolidated", "doc_key": "bse:1", "page": 4,
                        "known_at": "2026-05-15", "quote": QUOTE}]}
    assert checks.check_answer_row(row, lookup, "2026-10-19")[0]
    row["numbers"][0]["value"] = 9999
    ok, reason = checks.check_answer_row(row, lookup, "2026-10-19")
    assert not ok and "number" in reason
    missing = {**row, "numbers": [{**row["numbers"][0], "page": 99}]}
    ok, reason = checks.check_answer_row(missing, lookup, "2026-10-19")
    assert not ok and "page not in doc_text" in reason


# --- tiers -------------------------------------------------------------------------------------

def tier1_fail(*_, **__):
    return {"tier": 1, "model": MODEL, "ok": False, "payload": None, "error": "no valid JSON",
            "over_limit": False, "limited": False, "session": None, "started": None, "ended": None}


def tier2_fail(*_, **__):
    return {"tier": 2, "model": "deepseek", "ok": False, "payload": None, "error": "unit failed",
            "session": None, "started": None, "ended": None, "tokens": None,
            "tokens_note": "dsh job record has no token counts"}


def test_three_haiku_failures_escalate_to_deepseek_then_opus(root, conn):
    outcome = loop.run_unit(unit(root), lambda payload, tier=1: (True, None, {}), root, conn, None,
                            round_no=1, tier1=tier1_fail, tier2=tier2_fail, sleep=lambda s: None)
    assert outcome["escalated"] and not outcome["ok"]
    haiku = [row for row in outcome["attempts"] if row["tier"] == 1]
    assert len(haiku) == 3 and haiku[0]["unit"] == "answer-01"
    assert [row["tier"] for row in outcome["attempts"]][-2:] == [2, 3]
    rows = [json.loads(line) for line in (root / "escalations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["stage"] == "answer" and rows[0]["questions"] == [f"KEC{i:03d}" for i in range(1, 11)]
    assert len(rows[0]["tried"]) >= 4


def over_limit(*_, **__):
    return {"tier": 1, "model": MODEL, "ok": False, "payload": None, "error": "", "over_limit": True,
            "limited": False, "session": None, "started": None, "ended": None}


def test_over_limit_kill_halves_the_unit(root, conn):
    outcome = loop.run_unit(unit(root, size=10), lambda payload, tier=1: (True, None, {}), root, conn,
                            None, round_no=1, tier1=over_limit, tier2=tier2_fail, sleep=lambda s: None)
    sizes = [row["size"] for row in outcome["attempts"] if row["tier"] == 1]
    assert sizes == [10, 5, 2]
    assert [leftover.size for leftover in outcome["leftovers"]] == [5, 3, 1]
    assert outcome["leftovers"][-1].id.endswith("b")


def test_a_fix_proposal_is_checked_then_stored(root, conn):
    store.put_doc_text(conn, "bse:1", 4, PAGE, "text", "2026-05-15")
    proposals = root / "state" / "proposals"
    proposals.mkdir(parents=True)
    fact = {"measure": "revenue", "value": 123456, "unit": "inr_cr", "period": "FY26",
            "basis": "consolidated", "doc_key": "bse:1", "page": 4,
            "known_at": "2026-05-15", "quote": QUOTE}
    unit_ = loop.Unit(id="fix-not_extracted", stage="fix", sandbox=root, items=["KEC001"],
                      gap="not_extracted")
    (proposals / "fix-not_extracted.jsonl").write_text(json.dumps(fact) + "\n", encoding="utf-8")
    ok, reason, added = loop.accept_fix(unit_, {"outcome": "fixed"}, root, conn, "2026-10-19")
    assert ok and added["facts"] == 1, reason
    bad = {**fact, "quote": "a sentence that is nowhere on the cited page"}
    (proposals / "fix-not_extracted.jsonl").write_text(json.dumps(bad) + "\n", encoding="utf-8")
    ok, reason, added = loop.accept_fix(unit_, {"outcome": "fixed"}, root, conn, "2026-10-19")
    assert not ok and "quote" in reason
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


# --- the round stop rule -----------------------------------------------------------------------

def fake_tier1(unit_: loop.Unit, logfile):
    if unit_.stage == "fix":
        payload = {"outcome": "no_change", "summary": "nothing to do"}
    else:
        payload = [{"qid": item["id"], "status": "not_found", "answer": "", "numbers": [],
                    "sources": [], "gap_type": "absent", "gap_detail": ""} for item in unit_.items]
    return {"tier": 1, "model": MODEL, "ok": True, "payload": payload, "error": "",
            "over_limit": False, "limited": False, "session": None, "started": None, "ended": None}


def test_two_rounds_with_no_gap_closed_stop_with_done(root, monkeypatch):
    monkeypatch.setattr(job_watch, "add", lambda *args, **kwargs: None)
    rc = loop.run_loop(root, tier1=fake_tier1, tier2=tier2_fail, sleep=lambda s: None)
    assert rc == 0
    text = (root / "logs" / "loop.log").read_text(encoding="utf-8")
    assert "ROUND 1" in text and "ROUND 2" in text and "DONE two rounds closed no gap" in text


# --- sandbox guard and dry run -----------------------------------------------------------------

def test_refuses_to_write_outside_the_sandbox(root):
    with pytest.raises(store.SandboxViolation):
        store.write_text_inside(root, "../outside.txt", "x")
    with pytest.raises(store.SandboxViolation):
        store.inside(root, Path(tempfile.gettempdir()) / "elsewhere.db")
    assert not (root.parent / "outside.txt").exists()


def test_refuses_the_repository_as_a_sandbox():
    with pytest.raises(SystemExit):
        loop.ensure_sandbox(REPO)


def test_dry_run_prints_the_round_one_plan_and_calls_no_model(root, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("dry run must not call a model")

    monkeypatch.setattr(tiers, "run_tier1", boom)
    monkeypatch.setattr(tiers, "run_tier2", boom)
    assert loop.main(["--sandbox", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "round 1 plan: 100 questions in 10 answer units" in out
    assert "answer-01: 10 questions, tier 1" in out
    assert "answer-10: 10 questions, tier 1" in out
    assert "tier 2" in out and "tier 3" in out
    assert not (root / store.DB_NAME).exists()
