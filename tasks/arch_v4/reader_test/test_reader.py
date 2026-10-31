"""Tests for the quote-verified reader test.

Covers the two checks the brief names (verbatim quote, known_at PIT filter) plus the
number rule, term extraction and the frozen-sample bookkeeping.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from tasks.arch_v4.reader_test import db, retrieve, verify  # noqa: E402


# ---------------------------------------------------------------- fixtures
SCHEMA = """
create table chunk (
    chunk_id integer primary key,
    doc_id text, chunk_index integer, header text not null, body text not null,
    section text, speaker text, speaker_role text, unit_kind text,
    isin text, doc_type text not null, known_at text not null,
    event_date text, fiscal_period text, page_from integer, page_to integer,
    char_len integer not null default 0, quality_grade text not null default 'A'
);
create virtual table chunk_fts using fts5(header, body, content='chunk', content_rowid='chunk_id');
"""


@pytest.fixture()
def pit_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    rows = [
        (1, "before", "A", "concall", "2026-07-31T18:00:00", "margin improved to 10.46 percent"),
        (2, "same-day", "A", "concall", "2026-08-01T10:00:00", "margin improved again"),
        (3, "after", "A", "concall", "2026-08-02T10:00:00", "margin future leak"),
        (4, "other-entity", "B", "concall", "2026-07-01T10:00:00", "margin other company"),
        (5, "wrong-type", "A", "annual_report", "2026-07-01T10:00:00", "margin annual report"),
    ]
    for cid, tag, isin, dtype, known, body in rows:
        con.execute(
            "insert into chunk(chunk_id,doc_id,chunk_index,header,body,isin,doc_type,known_at,char_len) "
            "values (?,?,?,?,?,?,?,?,?)",
            (cid, tag, 0, f"{tag} header", body, isin, dtype, known, 200))
        con.execute("insert into chunk_fts(rowid,header,body) values (?,?,?)",
                    (cid, f"{tag} header", body))
    con.commit()
    yield con
    con.close()


# ---------------------------------------------------------------- known_at
def test_as_of_date_is_inclusive_of_the_whole_day():
    assert db.as_of_ceiling("2026-08-01") == "2026-08-01T23:59:59"
    assert db.as_of_ceiling("2026-08-01T12:00:00") == "2026-08-01T12:00:00"


def test_known_at_filter_runs_in_sql_before_fts(pit_db):
    got = db.search(pit_db, isin="A", doc_types=["concall"], as_of="2026-08-01",
                    fts_query='"margin"', limit=20)
    ids = [r["chunk_id"] for r in got]
    assert 1 in ids, "chunk before as_of must pass"
    assert 2 in ids, "chunk filed during the as_of day must pass"
    assert 3 not in ids, "chunk after as_of must be excluded"
    assert 4 not in ids, "other entity must be excluded"
    assert 5 not in ids, "other doc type must be excluded"


def test_entity_and_type_filters_cannot_be_bypassed_by_fts(pit_db):
    assert db.search(pit_db, isin="B", doc_types=["concall"], as_of="2026-08-01",
                     fts_query='"margin"') != []
    assert db.search(pit_db, isin="A", doc_types=["annual_report"], as_of="2026-08-01",
                     fts_query='"margin"')[0]["chunk_id"] == 5


# ---------------------------------------------------------------- quotes
CHUNKS = [
    {"chunk_id": 11, "header": "SAIL concall", "body":
     "Ashok Panda: SAIL decided actually to advance some of its major capital repairs during quarter 1, "
     "so that it will be free after that and will start producing better in the next quarters."},
    {"chunk_id": 12, "header": "Hindalco concall", "body":
     "At the end of this year, our renewable energy capacity stands at 470 megawatts powered by solar and wind."},
]


def test_quote_exact_match():
    v = verify.find_quote("SAIL decided actually to advance some of its major capital repairs", CHUNKS)
    assert v["ok"] and v["kind"] == "exact" and v["chunk_id"] == 11


def test_quote_is_case_and_whitespace_folded():
    v = verify.find_quote("  sail   DECIDED actually to advance some of its major capital repairs ", CHUNKS)
    assert v["ok"] and v["kind"] == "exact"


def test_quote_word_match_ignores_punctuation_but_not_words():
    v = verify.find_quote("capital repairs during quarter 1 so that it will be free", CHUNKS)
    assert v["ok"] and v["kind"] in {"exact", "words"}


def test_fabricated_quote_is_rejected():
    v = verify.find_quote("SAIL cancelled all capital repairs in quarter one", CHUNKS)
    assert not v["ok"] and v["kind"] == "not_found"


def test_too_short_quote_is_rejected():
    v = verify.find_quote("capital repairs", CHUNKS)
    assert not v["ok"] and v["kind"] == "too_short"


# ---------------------------------------------------------------- numbers
def test_number_must_come_from_quote():
    ok = verify.number_check("capacity is 470 MW", "capacity stands at 470 megawatts")
    assert ok["ok"]
    bad = verify.number_check("capacity is 523 MW", "capacity stands at 470 megawatts")
    assert not bad["ok"] and bad["missing_numbers"] == ["523"]


def test_number_may_restate_the_question_premise():
    ok = verify.number_check("the 4.5 GW converts later", "commissioning is gated", "Suzlon says 4.5 GW")
    assert ok["ok"]


def test_period_labels_and_page_citations_are_not_company_numbers():
    ok = verify.number_check(
        "FY25-26 margin was 10.46% (page 230)", "operating margin improved to 10.46%")
    assert ok["ok"], ok["missing_numbers"]


# ---------------------------------------------------------------- statuses
def test_not_stated_without_quote():
    v = verify.verify_answer("not stated", "", CHUNKS)
    assert v["status"] == "not_stated"


def test_not_stated_with_a_quote_is_a_contradiction():
    v = verify.verify_answer("not stated", "SAIL decided actually to advance some of its major capital repairs", CHUNKS)
    assert v["status"] == "rejected_contradiction"


def test_answer_with_number_outside_quote_is_rejected():
    v = verify.verify_answer(
        "capacity is 523 MW",
        "At the end of this year, our renewable energy capacity stands at 470 megawatts powered by solar and wind.",
        CHUNKS)
    assert v["status"] == "rejected_number"
    assert v["quote_ok"] is True


def test_verified_answer():
    v = verify.verify_answer(
        "capacity is 470 MW",
        "our renewable energy capacity stands at 470 megawatts powered by solar and wind",
        CHUNKS)
    assert v["status"] == "verified" and v["quote_ok"] and v["number_ok"]


# ---------------------------------------------------------------- terms
def test_month_name_does_not_eat_margins():
    t = retrieve.terms_for_question({
        "question": "What did HDFC Bank say about margins in May 2025?",
        "symbol": "HDFCBANK", "name": "HDFC Bank Limited"})
    assert "margins" in t.words and "margin" in t.words
    assert "may" not in t.words


def test_unit_and_number_terms():
    t = retrieve.terms_for_question({
        "question": "APLAPOLLO 8 MT by FY28 — slipped or on track?",
        "symbol": "APLAPOLLO", "name": "APL Apollo Tubes Limited"})
    assert "capacity" in t.words
    assert "8" in t.numbers
    assert any("on track" == p for p in t.phrases)


def test_hinglish_stopwords_are_dropped():
    t = retrieve.terms_for_question({
        "question": "BEL ka QRSAM order kis approval ka wait kar raha hai?",
        "symbol": "BEL", "name": "Bharat Electronics Limited"})
    assert "qrsam" in t.words and "approval" in t.words
    assert "kis" not in t.words and "kar" not in t.words


# ---------------------------------------------------------------- frozen sample
def test_frozen_question_list_matches_manifest():
    manifest = json.loads((HERE / "questions.manifest.json").read_text(encoding="utf-8"))
    raw = (HERE / "questions.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["sha256_questions_jsonl"]
    qs = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    assert len(qs) == 40
    assert {"MB0337", "MB0345", "MB0355", "MB0415", "MB0540"} <= {q["mid"] for q in qs}


def test_every_parent_row_has_a_written_eligibility_reason():
    rows = [json.loads(l) for l in (HERE / "eligibility_parents.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1073
    assert all(r.get("reason") for r in rows)
    assert sum(1 for r in rows if r["eligible"]) == 45


def test_all_40_rows_are_graded_once():
    grades = [json.loads(l) for l in (HERE / "grades.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(grades) == 40
    assert len({g["qid"] for g in grades}) == 40
    assert {g["verdict"] for g in grades} <= {"RIGHT", "PARTIAL", "WRONG", "CORRECT_NOT_STATED"}
    results = [json.loads(l) for l in (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {g["qid"] for g in grades} == {r["qid"] for r in results}
