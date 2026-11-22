"""Tests for the T-233 fast fix loop: golden-set regression check and scoped selectors.

Run from the repo root:
    python -m pytest reality_engine/tests/test_regress.py -q

Every fixture is a tiny sqlite DB under ``.tmp`` (pytest's ``tmp_path`` cannot be listed in the dsh
sandbox).  No test reads the live stores or the shipped golden files: a golden line is written here
with the same fields the real files use, so the matching rules are what is under test.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest

from reality_engine.research.selector import Selector, copy_db
from reality_engine.scripts import regress

ROOT = Path(__file__).resolve().parents[2]

OBSERVATION_DDL = """
CREATE TABLE observation (
    observation_id INTEGER PRIMARY KEY, symbol TEXT, doc_key TEXT, page INTEGER, measure TEXT,
    printed_label TEXT, printed_axis TEXT, value_text TEXT, unit TEXT, scale REAL, period TEXT,
    period_kind TEXT, series_title TEXT, entity_scope TEXT, stage TEXT, basis TEXT, adjusted INTEGER,
    geography TEXT, status TEXT);
"""

DOC = "D:/raw/AAA/investor_presentation/11111111-aaaa.pdf"


@pytest.fixture()
def tmp_path():
    """A writable scratch directory under the repo's .tmp (the sandbox denies pytest's own tmp_path)."""
    base = ROOT / ".tmp" / f"regress_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def build_observations(tmp_path: Path, rows: list[dict], name: str = "obs.db") -> Path:
    db = tmp_path / name
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(OBSERVATION_DDL)
    for row in rows:
        con.execute(
            "INSERT INTO observation (symbol, doc_key, page, measure, printed_label, value_text, unit, scale,"
            " period, period_kind, series_title, entity_scope, stage, basis, adjusted, geography, status)"
            " VALUES (:symbol, :doc_key, :page, :measure, :printed_label, :value_text, :unit, :scale,"
            " :period, :period_kind, :series_title, :entity_scope, :stage, :basis, :adjusted, :geography,"
            " :status)", row)
    con.commit()
    con.close()
    return db


def golden_line(grade: str, **updates) -> dict:
    entry = {
        "pipeline": "observations", "kind": "row", "grade": grade, "source": "test#1",
        "key": {"symbol": "AAA", "doc_key": DOC, "page": 7, "measure": "ebitda",
                "printed_label": "EBITDA", "value_text": "132"},
        "identity": {"symbol": "AAA", "doc_key": DOC, "page": 7, "printed_label": "EBITDA"},
        "status": "verified",
    }
    if grade == "RIGHT":
        entry["expect"] = {"measure": "ebitda", "unit": "₹ Cr", "scale": 10000000.0,
                           "period": "H1 FY25", "period_kind": "actual", "entity_scope": "company"}
    else:
        entry["wrong"] = {"measure": "ebitda", "unit": "₹ Cr", "scale": 10000000.0,
                          "period": "H1 FY25", "period_kind": "actual", "entity_scope": "company"}
    entry.update(updates)
    return entry


def write_golden(tmp_path: Path, entries: list[dict], name: str = "observations.jsonl") -> Path:
    directory = tmp_path / "golden"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
    return directory


ROW = {"symbol": "AAA", "doc_key": DOC, "page": 7, "measure": "ebitda", "printed_label": "EBITDA",
       "value_text": "132", "unit": "₹ Cr", "scale": 10000000.0, "period": "H1 FY25",
       "period_kind": "actual", "series_title": "", "entity_scope": "company", "stage": "", "basis": "",
       "adjusted": 0, "geography": "", "status": "verified"}


def counts(tmp_path: Path, rows: list[dict], entries: list[dict], **kwargs) -> dict:
    db = build_observations(tmp_path, rows)
    golden = write_golden(tmp_path, entries)
    return regress.run("observations", db, golden_dir=golden, **kwargs)


def test_a_right_row_matches_by_content_not_by_id(tmp_path):
    # The golden line carries no id at all; a rebuild that moves the row to another id still matches.
    report = counts(tmp_path, [ROW], [golden_line("RIGHT")])
    assert report["counts"] == {"still_right": 1}
    assert report["newly_broken"] == 0


def test_a_golden_line_for_another_company_is_skipped_not_broken(tmp_path):
    # One golden file serves two disjoint DBs: a line about a company this DB does not hold is not "missing".
    other = golden_line("RIGHT")
    other["key"] = {**other["key"], "symbol": "BBB"}
    other["identity"] = {**other["identity"], "symbol": "BBB"}
    report = counts(tmp_path, [ROW], [golden_line("RIGHT"), other])
    assert report["counts"] == {"still_right": 1}
    assert report["skipped_other_db"] == 1
    assert report["newly_broken"] == 0


def test_a_golden_line_for_another_document_is_skipped_not_broken(tmp_path):
    # The deck and annual-report reads share the company symbol; a line about the other document is skipped too.
    other = golden_line("RIGHT")
    other["key"] = {**other["key"], "doc_key": "D:/elsewhere/annual_report/other.pdf"}
    other["identity"] = {**other["identity"], "doc_key": "D:/elsewhere/annual_report/other.pdf"}
    report = counts(tmp_path, [ROW], [golden_line("RIGHT"), other])
    assert report["counts"] == {"still_right": 1}
    assert report["skipped_other_db"] == 1
    assert report["newly_broken"] == 0


def test_a_changed_right_row_is_newly_broken(tmp_path):
    report = counts(tmp_path, [{**ROW, "unit": "USD mn"}], [golden_line("RIGHT")])
    assert report["counts"]["newly_broken"] == 1
    assert "unit" in report["verdicts"][0]["detail"][0]


def test_a_vanished_right_row_is_newly_broken(tmp_path):
    report = counts(tmp_path, [], [golden_line("RIGHT")])
    assert report["counts"]["newly_broken"] == 1
    assert report["newly_broken"] == 1


def test_a_right_row_that_lost_verified_fails_the_gate(tmp_path):
    report = counts(tmp_path, [{**ROW, "status": "unverified"}], [golden_line("RIGHT")])
    assert report["counts"]["newly_broken"] == 1
    assert "status" in "; ".join(report["verdicts"][0]["detail"])


def test_a_wrong_row_meeting_the_stated_fix_is_fixed(tmp_path):
    fixed = golden_line("WRONG", expect={"unit": "<nonempty>"})
    report = counts(tmp_path, [ROW], [fixed])
    assert report["counts"] == {"fixed": 1}


def test_a_wrong_row_that_did_not_move_is_still_wrong(tmp_path):
    report = counts(tmp_path, [ROW], [golden_line("WRONG")])
    assert report["counts"] == {"still_wrong": 1}


def test_a_wrong_row_that_moved_is_reported_for_review(tmp_path):
    # No stated fix, but the row changed: report it as "changed", never as a pass or a failure.
    report = counts(tmp_path, [{**ROW, "period": "FY26"}], [golden_line("WRONG")])
    assert report["counts"] == {"changed": 1}
    assert report["newly_broken"] == 0


def test_a_page_defect_may_shrink_but_not_grow(tmp_path):
    rows = [{**ROW, "measure": "capacity.total", "printed_label": "", "value_text": str(value)}
            for value in (1, 2, 3)]
    page = {"pipeline": "observations", "kind": "page", "grade": "WRONG", "source": "test#page",
            "key": {"symbol": "AAA", "doc_key": DOC, "page": 7},
            "forbid": {"measure": "capacity.total", "printed_label": ""}, "max": 3, "defect": "stacked parts"}
    assert counts(tmp_path, rows, [page])["counts"] == {"still_wrong": 1}
    page["max"] = 2
    assert counts(tmp_path, rows, [page])["newly_broken"] == 1
    page["max"] = 0
    assert counts(tmp_path, [], [page])["counts"] == {"fixed": 1}


def test_the_baseline_diff_counts_added_removed_and_status(tmp_path):
    baseline_db = build_observations(tmp_path, [
        ROW,
        {**ROW, "measure": "revenue.value", "printed_label": "Revenue", "value_text": "1000"},
        {**ROW, "measure": "pat", "printed_label": "PAT", "value_text": "50", "status": "unverified"},
    ], name="base.db")
    now = [
        {**ROW, "measure": "pat", "printed_label": "PAT", "value_text": "50", "status": "verified"},
        {**ROW, "measure": "borrowings", "printed_label": "Debt", "value_text": "20"},
    ]
    report = counts(tmp_path, now, [golden_line("WRONG")], baseline=baseline_db)
    assert report["diff"]["added"] == 1
    assert report["diff"]["removed"] == 2
    assert report["diff"]["status_changed"] == 1


def test_main_exits_nonzero_only_for_newly_broken(tmp_path):
    db = build_observations(tmp_path, [{**ROW, "unit": "USD mn"}])
    golden = write_golden(tmp_path, [golden_line("RIGHT")])
    assert regress.main(["observations", "--db", str(db), "--golden", str(golden), "--json"]) == 1
    golden_ok = write_golden(tmp_path, [golden_line("WRONG")])
    assert regress.main(["observations", "--db", str(db), "--golden", str(golden_ok)]) == 0


def test_the_shipped_golden_sets_parse():
    for name in ("observations", "claims", "events"):
        entries = regress._load_golden(name)
        assert entries, name
        assert all(entry.get("grade") in ("RIGHT", "MINOR", "WRONG") for entry in entries), name
        assert all(entry.get("source") for entry in entries), name


# ------------------------------------------------------------------ selector
def write_selector(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "selector.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_selector_matches_stores_documents_and_pages(tmp_path):
    only = Selector.load(write_selector(tmp_path, {"stores": ["c32.db"], "doc_keys": ["2a8d0712"],
                                                   "pages": [14, 28]}))
    assert only.page("c32.db", "D:/raw/AAA/8ca607e9-2bd1-2a8d0712.pdf", 14) is True
    assert only.page("c32", "D:/raw/AAA/2a8d0712.pdf", 28) is True
    assert only.page("c32", "D:/raw/AAA/2a8d0712.pdf", 9) is False
    assert only.page("c99.db", "D:/raw/AAA/2a8d0712.pdf", 14) is False
    assert only.page("c32.db", "D:/raw/AAA/other.pdf", 14) is False
    assert only.doc("c32.db", "D:/raw/AAA/2a8d0712.pdf") is True   # pages are page-level only
    assert only.row({"store": "c32.db", "doc_key": "D:/raw/AAA/2a8d0712.pdf", "page": 28}) is True
    assert only.row({"store": "c99.db", "doc_key": "D:/raw/AAA/2a8d0712.pdf", "page": 28}) is False


def test_selector_carries_a_sql_predicate(tmp_path):
    only = Selector.load(write_selector(tmp_path, {"where": "measure = 'loans'"}))
    assert only.where_sql() == "(measure = 'loans')"
    assert Selector.load(write_selector(tmp_path, {"pages": [3]})).where_sql() == "1=1"
    assert only.row({"measure": "loans"}) is True     # lists are Python-side, the where is SQL-side


def test_an_empty_selector_is_refused(tmp_path):
    with pytest.raises(ValueError):
        Selector.load(write_selector(tmp_path, {}))
    with pytest.raises(ValueError):
        Selector.load(write_selector(tmp_path, {"where": "1=1; DROP TABLE claim"}))


def test_copy_db_refuses_the_baseline_path(tmp_path):
    db = build_observations(tmp_path, [ROW])
    with pytest.raises(ValueError):
        copy_db(db, db)
    copy_db(db, tmp_path / "copy.db")
    assert (tmp_path / "copy.db").is_file()


# ------------------------------------------------------------------ the pipeline hook
def test_recheck_with_only_touches_the_selected_pages(tmp_path):
    """The observations hook: a scoped --recheck filters pages before any check runs."""
    from reality_engine.v2 import observations as obs

    store = tmp_path / "c01.db"
    con = sqlite3.connect(store)
    con.executescript(
        "CREATE TABLE company (symbol TEXT, name TEXT);"
        "CREATE TABLE doc (doc_key TEXT);"
        "CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT);")
    con.execute("INSERT INTO company VALUES ('AAA', 'AAA Ltd')")
    for page, text in ((7, "EBITDA 132\nH1 FY25\n"), (9, "EBITDA 200\nH1 FY25\n")):
        con.execute("INSERT INTO doc VALUES ('D:/raw/AAA/deck.pdf')")
        con.execute("INSERT INTO doc_page VALUES ('D:/raw/AAA/deck.pdf', ?, ?)", (page, text))
    con.commit()
    con.close()

    db = obs.create_db(tmp_path / "obs.db")
    for page, value in ((7, "132"), (9, "200")):
        db.execute(
            "INSERT INTO observation (symbol, doc_key, page, known_at, measure, printed_label, value_text, unit,"
            " scale, period, period_kind, entity_scope, status, adjusted) VALUES"
            " ('AAA', 'D:/raw/AAA/deck.pdf', ?, '2025-05-13T15:27:33', 'ebitda', 'EBITDA', ?, 'Rs Cr', 1,"
            " 'H1 FY25', 'actual', 'company', 'unverified', 0)", (page, value))
    db.commit()
    only = Selector.load(write_selector(tmp_path, {"doc_keys": ["deck"], "pages": [7]}))
    stats = obs.recheck_db(db, [str(store)], only=only)
    db.close()
    assert stats["pages"] == 1
    assert stats["rows"] == 1


def test_a_scoped_event_merge_replaces_only_the_re_read_filings(tmp_path):
    """The filing-events hook: baseline copy + only this run's filings replaced."""
    from reality_engine.research import filing_events as fe

    def event(doc, amount, seq=1):
        row: dict[str, Any] = {column: None for column in fe.COLUMNS}
        row.update({"store": "c01", "symbol": "AAA", "doc_key": doc, "kind": "order_win",
                    "method": "script", "status": "verified", "entity_scope": "company",
                    "amount_inr_cr": amount, "seq": seq, "filing_date": "2026-01-01"})
        return row

    baseline = tmp_path / "events_base.db"
    fe.write_db(baseline, [event("docA", 100.0), event("docB", 50.0)], [], {"docs": 2})
    out = tmp_path / "events_out.db"
    fe.merge_db(out, baseline, [event("docA", 110.0)], [], {}, ["docA"])
    con = sqlite3.connect(out)
    rows = sorted(con.execute("SELECT doc_key, amount_inr_cr FROM event").fetchall())
    meta = dict(con.execute("SELECT key, value FROM run_meta").fetchall())
    con.close()
    assert rows == [("docA", 110.0), ("docB", 50.0)]      # A replaced, B untouched, no duplicate A
    assert json.loads(meta["scoped_merge"])["documents"] == 1
