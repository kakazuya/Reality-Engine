"""Acceptance tests for the analyst-agent test."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from tasks.arch_v4.analyst_test import select_questions
from tasks.arch_v4.analyst_test.number_check import check_answer
from tasks.arch_v4.analyst_test.tools import ToolError, ToolSession, safe_eval

HERE = Path(__file__).resolve().parent
TMP_ROOT = HERE.parents[2] / ".tmp"


def _fact_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        create table fact(entity_id text, atom text, dims text, period_start text,
                          period_end text, value, unit text, known_at text, source_ref text);
        create table pilot_universe(isin text primary key, symbol text);
        create table atom_status(atom_id text primary key, status text, rows integer,
                                 entities integer, isin_coverage_pct real, store text, note text);
    """)
    con.execute("insert into pilot_universe values('INE000000001','TESTCO')")
    con.execute("insert into atom_status values('fin.revenue','filled',2,1,100.0,'fact','')")
    con.executemany("insert into fact values(?,?,?,?,?,?,?,?,?)", [
        ("INE000000001", "fin.revenue", "basis=consolidated", "2026-06-01", "2026-06-30",
         100.0, "INR_CRORE", "2026-08-01T19:00:00", "test"),
        ("INE000000001", "fin.revenue", "basis=consolidated", "2026-09-01", "2026-09-30",
         999.0, "INR_CRORE", "2026-10-25T19:00:00", "test"),
    ])
    con.commit()
    con.close()


def _empty_v4(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        create table claim(claim_id integer primary key, entity_id text, topic text,
          direction text, direction_raw text, magnitude real, unit text, horizon text,
          certainty text, guidance_vs_fact text, quote text, page_no integer, doc_id integer,
          doctype text, surface_id integer, surface_raw text, list_name text, basis text,
          known_at text, pit_conf real);
    """)
    con.commit()
    con.close()


def _empty_chunks(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        create table doc(doc_id text primary key, title text);
        create table chunk(chunk_id integer primary key, doc_id text, doc_type text,
          header text, body text, section text, speaker text, known_at text, event_date text,
          fiscal_period text, page_from integer, page_to integer, char_len integer,
          quality_grade text, isin text);
        create virtual table chunk_fts using fts5(header, body, content='chunk',
                                                 content_rowid='chunk_id');
    """)
    con.commit()
    con.close()


@pytest.fixture()
def session():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    # tempfile.mkdtemp() creates a directory SQLite cannot open under this sandbox;
    # a plain mkdir in the workspace works.
    d = TMP_ROOT / ("analyst_test_" + uuid.uuid4().hex[:10])
    d.mkdir()
    fact = d / "fact.db"
    v4 = d / "v4.db"
    chunks = d / "chunks.db"
    _fact_db(fact)
    _empty_v4(v4)
    _empty_chunks(chunks)
    q = {"qid": "Q99", "mid": "MB9999#L", "as_of": "2026-10-19",
         "entity_isin": "INE000000001", "symbol": "TESTCO", "question": "revenue?"}
    s = ToolSession(q, fact_db=fact, v4_db=v4, chunks_db=chunks)
    try:
        yield s
    finally:
        s.close()
        shutil.rmtree(d, ignore_errors=True)


def test_pit_wrapper_drops_a_later_row(session):
    out = session.call("fact_query", {"atom": "fin.revenue"})
    assert out["n_returned"] == 1, out
    assert out["rows"][0]["value"] == 100.0
    assert all(r["known_at"][:10] <= "2026-10-19" for r in out["rows"])


def test_pit_wrapper_refuses_a_later_as_of(session):
    out = session.call("fact_query", {"atom": "fin.revenue", "as_of": "2026-10-25"})
    assert out["error"]["code"] == "as_of_refused", out
    assert session.calls == 1


def test_pit_wrapper_refuses_a_later_claim_date(session):
    out = session.call("claim_search", {"date_to": "2026-10-31"})
    assert out["error"]["code"] == "as_of_refused", out


def test_limit_accepts_the_float_string_the_model_sends(session):
    out = session.call("fact_query", {"atom": "fin.revenue", "limit": "5.0"})
    assert "error" not in out, out
    assert out["n_returned"] == 1


def test_number_absent_from_tool_results_is_flagged():
    chk = check_answer("Revenue was 999 crore and margin 12.5%",
                       [{"value": 123, "text": "margin 12.5 percent"}], [])
    assert "999" in chk["unsupported"]
    assert "12.5" in chk["supported"]
    assert not chk["ok"]


def test_calculator_result_supports_a_derived_number():
    chk = check_answer("The ratio is 1.25", [{"value": 100}], [{"value": 1.25}])
    assert chk["ok"], chk


def test_percent_form_of_a_calculator_result_is_supported():
    chk = check_answer("That is 53.10% of the move", [{"value": 20.02}, {"value": 10.63}],
                       [{"value": 0.530969}])
    assert "53.10" in chk["supported"], chk


def test_question_only_number_is_separate():
    chk = check_answer("It fell 20.02%", [{"value": 1}], [], "SAIL fell 20.02% on the day")
    assert chk["question_only"] == ["20.02"]
    assert "20.02" in chk["flagged"]


def test_calculator_is_arithmetic_only():
    assert safe_eval("(389.15/242.80)**(1/3)-1") == pytest.approx(0.1702, abs=1e-3)
    with pytest.raises(ToolError):
        safe_eval("__import__('os').system('echo hi')")


def test_frozen_questions_match_manifest():
    raw = (HERE / "questions.jsonl").read_bytes()
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == manifest["sha256_questions_jsonl"]
    qs = select_questions.check()
    assert len(qs) == 40 == manifest["n"]
    assert len({q["mid"] for q in qs}) == 40
    assert sum(1 for q in qs if q["judgement_or_study"]) >= 10


@pytest.mark.skipif(not Path(r"C:\RE\data\pilot\v4\fact_v4_pilot.db").exists(),
                    reason="pilot store not mounted")
def test_real_store_refuses_a_later_as_of_and_hides_later_rows():
    q = next(q for q in select_questions.check() if q["qid"] == "Q02")  # as_of 2026-09-30
    s = ToolSession(q)
    try:
        refused = s.call("fact_query", {"atom": "price.close", "as_of": "2026-10-02"})
        assert refused["error"]["code"] == "as_of_refused"
        hidden = s.call("fact_query", {"atom": "price.close",
                                       "period_from": "2026-10-01", "period_to": "2026-10-31"})
        assert hidden["rows"] == [], hidden
        shown = s.call("fact_query", {"atom": "price.close",
                                      "period_from": "2026-09-29", "period_to": "2026-09-30"})
        assert shown["rows"], shown
        assert all(r["known_at"][:10] <= "2026-09-30" for r in shown["rows"])
    finally:
        s.close()
