"""T-048: the gap loop's checks, kec.db row sources, prepare stage, escalation, halving, round stop,
sandbox guard, plan and the estimated cost of a killed session.

No model call: every tier is a fake or not reached.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from reality_engine.gap_loop import checks, company, loop, prepare, store, tiers
from reality_engine.scripts import job_watch, session_runner
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
    # A real transcript writes "Rs.11,000 crores": the period is an abbreviation, not a decimal.
    assert checks.check_number(11000, "inr_cr", "revenues have crossed Rs.11,000 crores")[0]
    assert checks.check_number(123456, "inr_cr", "Rs.1,23,456 crore was the revenue")[0]
    assert not checks.check_number(0.56, "pct", "margin of 1.56 percent")[0]


def test_margin_stored_as_money_is_rejected():
    ok, reason = checks.check_unit("EBITDA margin", "inr_cr")
    assert not ok and "does not suit" in reason
    assert checks.check_unit("EBITDA margin", "pct")[0]
    assert checks.check_unit("order book", "inr_cr")[0]
    assert checks.check_unit("order intake growth", "pct")[0]


def test_hindalco_and_bajaj_units_that_were_rejected_are_known_now():
    # Verbatim rejections of 2 Nov (T-048): "is not a known unit".
    price, capex = "LME aluminium spot price", "project capex"
    for unit in ("usd_per_tonne", "usd_per_t", "usd_per_ton", "cents per lb", "inr_per_tonne",
                 "inr_per_share"):
        assert checks.check_unit(price, unit)[0], unit
    for unit in ("INR_crore", "inr_crore", "usd_million", "usd_mn", "usd_bn", "inr_lakh"):
        assert checks.check_unit(capex, unit)[0], unit
    for unit in ("kt_per_year", "ktpa", "mtpa", "million_tonnes", "tonnes_per_year"):
        assert checks.check_unit("installed capacity", unit)[0], unit
    assert checks.check_unit("active customers", "million customers")[0]
    assert checks.check_unit("branch network", "branches")[0]
    assert checks.check_unit("date of commissioning", "date")[0]
    assert not checks.check_unit("active customers", "furlongs")[0]


def test_rate_measures_are_percentages_and_money_words_do_not_decide_them():
    # "does not suit ... (a money measure)" and "(a pct measure, because of the word share)" (2 Nov).
    assert checks.check_unit("cost of funds", "pct")[0]
    assert checks.check_unit("credit cost (loan loss to average AUF)", "pct")[0]
    assert checks.check_unit("loan loss to average AUF (credit cost)", "pct")[0]
    assert not checks.check_unit("cost of funds", "inr_cr")[0]
    assert checks.check_unit("face value per share before sub-division", "inr")[0]
    assert checks.check_unit("BHFL share of consolidated profit after tax", "inr_cr")[0]
    assert checks.check_unit("market share", "pct")[0]
    # The two that must still fail: a margin stored as money, and a revenue stored as a percentage.
    ok, reason = checks.check_unit("EBITDA margin", "inr_cr")
    assert not ok and "does not suit" in reason
    ok, reason = checks.check_unit("revenue", "pct")
    assert not ok and "typed contract" in reason
    # A USD number is not a rupee revenue: the contract's money unit must be the same currency.
    assert not checks.check_unit("revenue", "usd_million")[0]


def test_hindalco_and_bajaj_periods_are_accepted():
    # Verbatim rejections of 2 Nov (T-048): "is not a period".
    for period in ("Dec-2025", "Dec 2025", "12-month trailing", "trailing twelve months", "LTM"):
        assert checks.check_period(period)[0], period


def test_a_usd_number_is_read_in_its_own_scale():
    quote = "Novelis revenue of US$1.2 billion in Q2"
    assert checks.check_number(1200, "usd_million", quote)[0]
    assert checks.check_number(1.2, "usd_bn", quote)[0]
    assert checks.check_number(1200, "usd_mn", "revenue US$ 1,200 million")[0]
    assert not checks.check_number(9999, "usd_million", quote)[0]


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
    assert checks.check_answer_row(row, lookup, "2026-10-19") == (None, [])
    row["numbers"][0]["value"] = 9999
    malformed, reasons = checks.check_answer_row(row, lookup, "2026-10-19")
    assert malformed is None and reasons and "number" in reasons[0]
    missing = {**row, "numbers": [{**row["numbers"][0], "page": 99}]}
    malformed, reasons = checks.check_answer_row(missing, lookup, "2026-10-19")
    assert malformed is None and "page not in doc_text" in reasons[0]
    bad_status = {**row, "status": "probably"}
    assert "status" in checks.check_answer_row(bad_status, lookup, "2026-10-19")[0]


def test_a_number_citing_a_kec_db_row_is_read_back(root, conn):
    conn.execute("CREATE TABLE shp_index(quarter_end TEXT, promoter_pct REAL, known_at TEXT)")
    conn.execute("INSERT INTO shp_index VALUES('2026-06-30', 51.7, '2026-07-15')")
    rowid = conn.execute("SELECT rowid FROM shp_index").fetchone()[0]
    lookup = store.page_lookup(conn)  # doc_text is empty: a row number never needs a page
    rows = store.row_lookup(conn)
    number = {"measure": "promoter holding", "value": 51.7, "unit": "pct", "period": "Q2FY26",
              "table": "shp_index", "rowid": rowid, "known_at": "2026-07-15"}
    row = {"qid": "KEC001", "status": "answered", "answer": "Promoter holding was 51.7%.",
           "numbers": [number]}
    assert checks.check_answer_row(row, lookup, "2026-10-19", rows) == (None, [])
    wrong = {**row, "numbers": [{**number, "value": 42.0}]}
    malformed, reasons = checks.check_answer_row(wrong, lookup, "2026-10-19", rows)
    assert malformed is None and reasons and "not in the shp_index row" in reasons[0]
    late = {**row, "numbers": [{**number, "known_at": "2026-11-01"}]}
    assert "after the as-of" in checks.check_answer_row(late, lookup, "2026-10-19", rows)[1][0]
    off_date = {**row, "numbers": [{**number, "known_at": "2026-07-16"}]}
    assert "own date" in checks.check_answer_row(off_date, lookup, "2026-10-19", rows)[1][0]
    missing = {**row, "numbers": [{**number, "rowid": 99}]}
    assert "no shp_index row" in checks.check_answer_row(missing, lookup, "2026-10-19", rows)[1][0]
    assert checks.check_row_fact({**number, "table": "nope"}, "2026-10-19", rows)[1].startswith("table:")
    quoted = {**row, "numbers": [{**number, "quote": "promoter holding was 51.7 percent"}]}
    assert "not in the shp_index row" in checks.check_answer_row(quoted, lookup, "2026-10-19", rows)[1][0]


# --- tiers -------------------------------------------------------------------------------------

def tier1_fail(*_, **__):
    return {"tier": 1, "model": MODEL, "ok": False, "payload": None, "error": "no valid JSON",
            "over_limit": False, "limited": False, "session": None, "started": None, "ended": None}


def tier2_fail(*_, **__):
    return {"tier": 2, "model": "deepseek", "ok": False, "payload": None, "error": "unit failed",
            "session": None, "started": None, "ended": None, "tokens": None,
            "tokens_note": "dsh job record has no token counts"}


def test_two_haiku_failures_escalate_to_tier2_then_opus(root, conn):
    outcome = loop.run_unit(unit(root), lambda payload, tier=1, u=None: (True, None, {}), root, conn, None,
                            round_no=1, tier1=tier1_fail, tier2=tier2_fail, sleep=lambda s: None)
    assert outcome["escalated"] and not outcome["ok"]
    haiku = [row for row in outcome["attempts"] if row["tier"] == 1]
    assert len(haiku) == 2 and haiku[0]["unit"] == "answer-01"
    assert [row["tier"] for row in outcome["attempts"]][-2:] == [2, 3]
    escalations = [json.loads(line) for line in
                   (root / "escalations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["question"] for row in escalations] == [f"KEC{i:03d}" for i in range(1, 11)]
    assert all(row["reason"] and row["stage"] == "answer" for row in escalations)
    assert outcome["escalated_qids"] == [f"KEC{i:03d}" for i in range(1, 11)]
    assert len(escalations[0]["tried"]) >= 3


# --- usage-limit replies (T-048, 2 Nov: "You've hit your 5-hour limit · resets 10:50pm") -------------

LIMIT_MESSAGE = "You've hit your 5-hour limit · resets 10:50pm (Asia/Kolkata)"


def limited_reply(*_, **__):
    return {"tier": 1, "model": MODEL, "ok": False, "payload": None, "error": LIMIT_MESSAGE,
            "over_limit": False, "limited": True, "session": None, "started": None, "ended": None}


def tier1_ok(*_, **__):
    return {**tier1_fail(), "ok": True, "payload": []}


def test_the_exact_five_hour_limit_reply_sets_limited(root):
    event = {"type": "result", "is_error": True, "result": LIMIT_MESSAGE, "total_cost_usd": 0.0}
    result = session_runner.run_session([sys.executable, "-c", f"print({json.dumps(json.dumps(event))})"],
                                        root, model=MODEL)
    assert result.limited
    for text in ("You've hit your weekly limit", "Usage limit reached", "Rate limit exceeded",
                 "API Error: 429", "Claude is Overloaded", "Limit reached for today", "Plan · resets 9pm"):
        assert session_runner.LIMIT_PATTERN.search(text), text
    assert not session_runner.LIMIT_PATTERN.search("Sales rose 12% to Rs 4,500 crore in Q2 FY26")


def test_a_limited_tier1_reply_sleeps_then_succeeds_without_escalating(root, conn):
    replies = iter([limited_reply, tier1_ok])
    sleeps = []
    outcome = loop.run_unit(unit(root), lambda payload, tier=1, u=None: (True, None, {}), root, conn, None,
                            round_no=1, tier1=lambda *a, **k: next(replies)(*a, **k), tier2=tier2_fail,
                            sleep=sleeps.append)
    assert outcome["ok"] and outcome["tier"] == 1
    assert sleeps == [session_runner.LIMIT_SLEEP]
    assert not (root / "escalations.jsonl").exists()


def test_a_limited_tier2_reply_sleeps_and_retries_sonnet(root, conn):
    calls = []

    def tier2(unit_, logfile):
        calls.append(unit_.id)
        if len(calls) == 1:
            return limited_reply()
        return {"tier": 2, "model": tiers.SONNET, "ok": True, "payload": [], "error": "", "over_limit": False,
                "session": None, "started": None, "ended": None, "tokens": None}

    sleeps = []
    outcome = loop.run_unit(unit(root), lambda payload, tier=1, u=None: (True, None, {}), root, conn, None,
                            round_no=1, tier1=tier1_fail, tier2=tier2, sleep=sleeps.append)
    assert outcome["ok"] and outcome["tier"] == 2
    assert len(calls) == 2 and sleeps == [session_runner.LIMIT_SLEEP]
    assert not (root / "escalations.jsonl").exists()


def test_eight_limited_replies_in_a_row_pause_the_unit_without_escalating(root, conn):
    logfile = root / "logs" / "loop.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    calls, sleeps = [], []

    def tier2(*_, **__):
        calls.append(1)
        return tier2_fail()

    outcome = loop.run_unit(unit(root), lambda payload, tier=1, u=None: (True, None, {}), root, conn, logfile,
                            round_no=1, tier1=limited_reply, tier2=tier2, sleep=sleeps.append)
    assert outcome["paused"] and not outcome["ok"] and not outcome.get("escalated")
    assert sum(1 for row in outcome["attempts"] if row["error"] == LIMIT_MESSAGE) == loop.MAX_LIMITED_REPLIES
    assert len(sleeps) == loop.MAX_LIMITED_REPLIES - 1 and not calls
    assert not (root / "escalations.jsonl").exists()
    text = logfile.read_text(encoding="utf-8")
    assert "PAUSED usage limit" in text and "escalat" not in text


def test_a_paused_unit_stops_the_run_with_rc_5_and_no_escalation(root, monkeypatch):
    monkeypatch.setattr(job_watch, "add", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.prepare, "prepare", lambda *args, **kwargs: {
        "files": 0, "docs": 0, "pages": 0, "script_text": 0, "needs_ocr": 0, "known_at": 0,
        "undated": 0, "history": 0, "history_undated": 0, "tables": {}, "seconds": 0.0})
    rc = loop.run_loop(root, tier1=limited_reply, tier2=tier2_fail, sleep=lambda s: None)
    assert rc == 5
    text = (root / "logs" / "loop.log").read_text(encoding="utf-8")
    assert "PAUSED usage limit" in text and "ROUND" not in text and "escalat" not in text


def test_tier2_default_is_sonnet_at_medium(root, monkeypatch):
    seen = {}

    def fake_run_session(cmd, cwd, env=None, model=None, **_):
        seen["cmd"], seen["model"] = cmd, model
        return session_runner.SessionResult(final='```json\n[]\n```', model=model)

    monkeypatch.setattr(tiers, "run_session", fake_run_session)
    monkeypatch.setattr(tiers, "answer_prompt", lambda u: "prompt")
    result = tiers.run_tier2_sonnet(unit(root, size=1), None)
    assert result["tier"] == 2 and seen["model"] == "claude-sonnet-5-5"
    assert seen["cmd"][seen["cmd"].index("--effort") + 1] == "medium"
    import inspect
    assert "run_tier2_sonnet" in inspect.getsource(loop.run_unit)
    usage = {"input_tokens": 1_000_000}
    assert session_runner.estimate_cost(usage, "claude-sonnet-5-5") == pytest.approx(2.0)
    assert session_runner.estimate_cost(usage) == pytest.approx(0.1)


def over_limit(*_, **__):
    return {"tier": 1, "model": MODEL, "ok": False, "payload": None, "error": "", "over_limit": True,
            "limited": False, "session": None, "started": None, "ended": None}


def test_after_a_halving_the_check_sees_the_halved_unit(root, conn):
    calls = iter([over_limit, lambda *_, **__: {**tier1_fail(), "ok": True, "payload": []}])
    seen = []

    def accept(payload, tier=1, u=None):
        seen.append(len(u.items))
        return True, None, {}

    outcome = loop.run_unit(unit(root, size=4), accept, root, conn, None, round_no=1,
                            tier1=lambda *a, **k: next(calls)(*a, **k), tier2=tier2_fail,
                            sleep=lambda s: None)
    assert outcome["ok"] and seen == [2]


def test_over_limit_kill_halves_the_unit(root, conn):
    outcome = loop.run_unit(unit(root, size=10), lambda payload, tier=1, u=None: (True, None, {}), root, conn,
                            None, round_no=1, tier1=over_limit, tier2=tier2_fail, sleep=lambda s: None)
    sizes = [row["size"] for row in outcome["attempts"] if row["tier"] == 1]
    assert sizes == [10, 5]
    assert [leftover.size for leftover in outcome["leftovers"]] == [5, 3]
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


def _results_row(conn, finance_costs: float = 7540000000.0) -> int:
    # A row of the copied results table, as the Hindalco proposal cited it (table + rowid, no page).
    conn.execute("CREATE TABLE IF NOT EXISTS results_quarterly(period TEXT, FinanceCosts REAL, known_at TEXT)")
    cursor = conn.execute("INSERT INTO results_quarterly(period, FinanceCosts, known_at) VALUES(?,?,?)",
                          ("Q1FY26", finance_costs, "2025-08-12"))
    conn.commit()
    return int(cursor.lastrowid)


def _row_proposal(rowid: int, value: float = 7540000000.0) -> dict:
    return {"measure": "FinanceCosts", "value": value, "unit": "inr", "period": "Q1FY26",
            "basis": "consolidated", "doc_key": "hindalco.db:results_quarterly", "page": None,
            "quote": "7540000000.0", "known_at": "2025-08-12", "table": "results_quarterly",
            "rowid": rowid}


def test_a_row_cited_fix_proposal_that_matches_its_row_is_stored(root, conn):
    rowid = _results_row(conn)
    proposals = root / "state" / "proposals"
    proposals.mkdir(parents=True)
    unit_ = loop.Unit(id="fix-not_extracted", stage="fix", sandbox=root, items=["KEC001"],
                      gap="not_extracted")
    (proposals / "fix-not_extracted.jsonl").write_text(json.dumps(_row_proposal(rowid)) + "\n",
                                                       encoding="utf-8")
    ok, reason, added = loop.accept_fix(unit_, {"outcome": "fixed"}, root, conn, "2026-10-19")
    assert ok and added["row_facts"] == 1 and added["rejected"] == 0, reason
    stored = conn.execute("SELECT cited_table, cited_rowid, known_at FROM row_facts").fetchall()
    assert stored == [("results_quarterly", rowid, "2025-08-12")]
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


def test_a_row_cited_fix_proposal_whose_value_is_not_in_the_row_is_rejected(root, conn):
    rowid = _results_row(conn)
    proposals = root / "state" / "proposals"
    proposals.mkdir(parents=True)
    unit_ = loop.Unit(id="fix-not_extracted", stage="fix", sandbox=root, items=["KEC001"],
                      gap="not_extracted")
    (proposals / "fix-not_extracted.jsonl").write_text(
        json.dumps(_row_proposal(rowid, value=9999.0)) + "\n", encoding="utf-8")
    ok, reason, added = loop.accept_fix(unit_, {"outcome": "fixed"}, root, conn, "2026-10-19")
    assert not ok and "page not in doc_text" not in reason
    assert "number: 9999 is not in the results_quarterly row" in reason
    assert conn.execute("SELECT COUNT(*) FROM row_facts").fetchone()[0] == 0


def test_formulas_are_stored_when_every_fact_fails(root, conn):
    store.put_doc_text(conn, "bse:1", 4, PAGE, "text", "2026-05-15")
    proposals = root / "state" / "proposals"
    proposals.mkdir(parents=True)
    unit_ = loop.Unit(id="fix-needs_formula", stage="fix", sandbox=root, items=["KEC001"],
                      gap="needs_formula")
    missing_page = {"measure": "revenue", "value": 123456, "unit": "inr_cr", "period": "FY26",
                    "basis": "consolidated", "doc_key": "bse:1", "page": 99,
                    "known_at": "2026-05-15", "quote": QUOTE}
    (proposals / "fix-needs_formula.jsonl").write_text(json.dumps(missing_page) + "\n", encoding="utf-8")
    # Facts all fail and no formulas file: nothing stored, so the unit still fails.
    ok, reason, _ = loop.accept_fix(unit_, {"outcome": "fixed"}, root, conn, "2026-10-19")
    assert not ok and "page not in doc_text" in reason
    formula = {"name": "EBITDA_margin", "expression": "ebitda / revenue", "inputs": ["ebitda", "revenue"],
               "description": "EBITDA over revenue"}
    (proposals / "fix-needs_formula.formulas.json").write_text(json.dumps([formula]), encoding="utf-8")
    ok, reason, added = loop.accept_fix(unit_, {"outcome": "fixed"}, root, conn, "2026-10-19")
    assert ok and added["formulas"] == 1 and added["facts"] == 0 and added["rejected"] == 1, reason
    assert conn.execute("SELECT name FROM formulas").fetchall() == [("EBITDA_margin",)]


def test_25_questions_of_one_gap_type_become_three_fix_units(root):
    statuses = {f"KEC{i:03d}": {"status": "not_found", "gap_type": "not_extracted"}
                for i in range(1, 26)}
    units = loop.fix_units(statuses, root)
    assert [unit.size for unit in units] == [10, 10, 5]
    assert len({unit.id for unit in units}) == 3
    assert units[0].items == [f"KEC{i:03d}" for i in range(1, 11)]


def test_one_unverified_row_does_not_fail_nine_good_rows(root, conn):
    store.put_doc_text(conn, "bse:1", 4, PAGE, "text", "2026-05-15")
    questions = loop.load_questions(root)[:10]
    unit_ = loop.Unit(id="answer-01", stage="answer", sandbox=root, items=questions)
    payload = [{"qid": q["id"], "status": "answered", "answer": "FY26 revenue was 1,23,456 crore.",
                "numbers": [{"measure": "revenue", "value": 123456, "unit": "inr_cr",
                             "period": "FY26", "basis": "consolidated", "doc_key": "bse:1",
                             "page": 4, "known_at": "2026-05-15", "quote": QUOTE}]}
               for q in questions]
    payload[-1]["numbers"][0]["value"] = 9999  # not in the quote: one failed number, not a bad report

    def tier1(unit_in, logfile):
        return {"tier": 1, "model": MODEL, "ok": True, "payload": payload, "error": "",
                "over_limit": False, "limited": False, "session": None, "started": None,
                "ended": None}

    state = {"spent": 0.0, "budget": 15.0, "as_of": "2026-10-19", "escalated": set()}
    loop.drain(deque([unit_]), 1, root, conn, None, state, tier1=tier1, tier2=tier2_fail,
               sleep=lambda s: None)
    stored = store.latest_answers(conn)
    assert stored["KEC010"]["status"] == "unverified"
    assert stored["KEC010"]["gap_type"] == "unverified"
    assert "does not occur" in stored["KEC010"]["answer"]["reason"]
    assert all(stored[q["id"]]["status"] == "answered" for q in questions[:9])
    assert not state["escalated"] and not (root / "escalations.jsonl").exists()


def test_tier2_start_carries_approved_by(root, monkeypatch):
    class Manager:
        def __init__(self):
            self.start: dict = {}

        def start_worker(self, **kwargs):
            self.start = kwargs
            return {"job_id": "job-1"}

        def get_status(self, job_id):
            return {"done": True}

    manager = Manager()
    fake_core = SimpleNamespace(is_peak=lambda: False, load_config=lambda: {}, PluginError=Exception)
    monkeypatch.setattr(tiers, "worker_core", lambda: fake_core)
    work = loop.Unit(id="answer-01", stage="answer", sandbox=root,
                     items=loop.load_questions(root)[:2])
    tiers.run_tier2(work, None, manager_factory=lambda: manager, sleep=lambda s: None, timeout=1)
    assert manager.start["approved_by"] == tiers.APPROVED_BY
    assert manager.start["permission"] == "danger-full-access"
    assert manager.start["write_scope"] == "data"
    assert manager.start["confirm_repo_root_write"] is True


# --- prepare stage (code only, no model) -------------------------------------------------------

def make_pdf(path: Path, pages: list[str]) -> None:
    """A small real PDF: one page per string, the text written when it is not empty."""
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def test_prepare_fills_doc_text_flags_needs_ocr_and_builds_docs(root, monkeypatch):
    monkeypatch.setattr(prepare, "store_copies", lambda company: ())   # no read-only store in a test
    monkeypatch.setattr(prepare, "duck_copies", lambda company: ())
    folder = root / "raw" / "history" / "quarterly_results"
    folder.mkdir(parents=True)
    make_pdf(folder / "dated.pdf", [PAGE, ""])          # page 1 has text, page 2 has none
    (root / "raw" / "history" / "material_filing").mkdir(parents=True)
    make_pdf(root / "raw" / "history" / "material_filing" / "blank.pdf", [""])

    counts = prepare.prepare(root, as_of="2026-10-19")
    assert counts["files"] == 2 and counts["docs"] == 2
    assert counts["pages"] == 3 and counts["script_text"] == 1 and counts["needs_ocr"] == 2
    assert counts["undated"] == 2 and counts["history_undated"] == 2
    conn = store.connect(root)
    try:
        methods = dict(conn.execute("SELECT doc_key || ':' || page, method FROM doc_text").fetchall())
        assert methods == {"history/quarterly_results/dated.pdf:1": "script_text",
                           "history/quarterly_results/dated.pdf:2": "needs_ocr",
                           "history/material_filing/blank.pdf:1": "needs_ocr"}
        empty = conn.execute("SELECT text FROM doc_text WHERE method='needs_ocr'").fetchall()
        assert [row[0] for row in empty] == ["", ""]
        docs = dict(conn.execute("SELECT doc_key, pages FROM docs").fetchall())
        assert docs == {"history/quarterly_results/dated.pdf": 2,
                        "history/material_filing/blank.pdf": 1}
        known = conn.execute("SELECT known_at FROM docs WHERE doc_key LIKE '%dated.pdf'").fetchone()[0]
        assert known is None                              # undated: excluded from as-of answers
        assert conn.execute("SELECT COUNT(*) FROM doc_text_fts WHERE doc_text_fts MATCH 'revenue'"
                            ).fetchone()[0] == 1
    finally:
        conn.close()
    rows = [json.loads(line) for line in
            (root / "state" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["tier"] == 0 and rows[-1]["unit"] == "prepare"
    assert rows[-1]["rows_added"]["doc_text"] == 3 and rows[-1]["methods"] == ["script_text"]
    again = prepare.prepare(root, as_of="2026-10-19")     # idempotent: nothing extracted twice
    assert again["pages"] == 0 and again["script_text"] == 0
    assert again["docs"] == 2


def test_prepare_names_a_store_it_cannot_read(root, monkeypatch):
    monkeypatch.setattr(prepare, "duck_copies", lambda company: ())
    monkeypatch.setattr(prepare, "store_copies", lambda company: (
        {"table": "ar_facts", "db": "missing.db", "source": "ar_facts", "key": "isin=X",
         "sql": "select 1", "params": ()},))
    with pytest.raises(RuntimeError, match="cannot read missing.db for KEC"):
        prepare.prepare(root)


def test_a_killed_session_gets_an_estimated_cost(root):
    killed = [{"type": "assistant", "message": {"content": [],
                                                "usage": {"input_tokens": 1000, "output_tokens": 200,
                                                          "cache_read_input_tokens": 0,
                                                          "cache_creation_input_tokens": 0}}}]
    script = ";".join([f"print({json.dumps(json.dumps(event))})" for event in killed])
    result = session_runner.run_session([sys.executable, "-c", script], root, model=MODEL)
    assert result.cost_estimated and not result.error
    assert result.cost == pytest.approx(session_runner.estimate_cost(result.usage))
    assert result.cost == pytest.approx((1000 * 0.1 + 200 * 0.5) / 1e6)
    finished = [{"type": "result", "total_cost_usd": 0.5, "result": "ok"}]
    script = ";".join([f"print({json.dumps(json.dumps(event))})" for event in finished])
    result = session_runner.run_session([sys.executable, "-c", script], root, model=MODEL)
    assert result.cost == 0.5 and not result.cost_estimated


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
    monkeypatch.setattr(loop.prepare, "prepare", lambda *args, **kwargs: {
        "files": 0, "docs": 0, "pages": 0, "script_text": 0, "needs_ocr": 0, "known_at": 0,
        "undated": 0, "history": 0, "history_undated": 0, "tables": {}, "seconds": 0.0})
    rc = loop.run_loop(root, tier1=fake_tier1, tier2=tier2_fail, sleep=lambda s: None)
    assert rc == 0
    text = (root / "logs" / "loop.log").read_text(encoding="utf-8")
    assert "ROUND 1" in text and "ROUND 2" in text and "DONE two rounds closed no gap" in text


def test_the_run_stops_before_answering_when_the_documents_cannot_be_dated(root, monkeypatch):
    monkeypatch.setattr(job_watch, "add", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.prepare, "prepare", lambda *args, **kwargs: {
        "files": 9, "docs": 9, "pages": 0, "script_text": 0, "needs_ocr": 0, "known_at": 3,
        "undated": 6, "history": 9, "history_undated": 6, "tables": {}, "seconds": 0.0})

    def boom(*args, **kwargs):
        raise AssertionError("no model call when the prepare stop rule fires")

    monkeypatch.setattr(tiers, "run_tier1", boom)
    assert loop.run_loop(root, tier1=boom, tier2=boom, sleep=lambda s: None) == 4
    text = (root / "logs" / "loop.log").read_text(encoding="utf-8")
    assert "STOPPED prepare: 6 of 9 PDFs" in text


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
    assert "round 1 plan: 100 questions in 20 answer units" in out
    assert "answer-01: 5 questions, tier 1" in out
    assert "answer-20: 5 questions, tier 1" in out
    assert "prepare (code only, no model)" in out
    assert "tier 2" in out and "tier 3" in out
    assert not (root / company.current().db_name).exists()
