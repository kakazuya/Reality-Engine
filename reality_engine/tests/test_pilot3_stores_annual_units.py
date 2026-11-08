"""T-115: annual-report lines keep the rupee scale their unit text names and the year their quote prints.

The two defects on the unseen6 / pilot10 builds: a stored unit text such as "rs mn", "rs lakh" or "₹ in mn" left
``scale`` at 1 (104 rows), and a history table's five columns all landed under the report's own year (one page of
a five-year table gave one line item five values under one FY).
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from reality_engine.pilot3 import stores


# --- the unit's own scale ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,unit,scale", [
    ("mn", "inr_million", 1e6), ("million", "inr_million", 1e6), ("₹ in mn", "inr_million", 1e6),
    ("` mn", "inr_million", 1e6), ("rs mn", "inr_million", 1e6), ("Rs million", "inr_million", 1e6),
    ("inr_million", "inr_million", 1e6),
    ("lakh", "inr_lakh", 1e5), ("lacs", "inr_lakh", 1e5), ("rs lakh", "inr_lakh", 1e5),
    ("rs lacs", "inr_lakh", 1e5), ("rs. lacs", "inr_lakh", 1e5), ("rs. in lacs", "inr_lakh", 1e5),
    ("rs.in lacs", "inr_lakh", 1e5), ("inr_lakh", "inr_lakh", 1e5),
    ("crore", "inr_crore", 1e7), ("cr", "inr_crore", 1e7), ("Rs crore", "inr_crore", 1e7),
    ("inr_crore", "inr_crore", 1e7),
    ("billion", "inr_billion", 1e9), ("bn", "inr_billion", 1e9), ("rs billion", "inr_billion", 1e9),
    ("₹ billion", "inr_billion", 1e9), ("inr_billion", "inr_billion", 1e9),
    ("thousand", "inr_thousand", 1e3), ("'000", "inr_thousand", 1e3), ("in '000s", "inr_thousand", 1e3),
    ("paise", "inr", 0.01),
    ("%", "pct", 1.0), ("pct", "pct", 1.0), ("percent", "pct", 1.0), ("percentage", "pct", 1.0),
    ("times", "ratio", 1.0), ("x", "ratio", 1.0), ("ratio", "ratio", 1.0),
    ("rs", "inr", 1.0), ("inr", "inr", 1.0), ("Rs.", "inr", 1.0),
    ("inr_per_share", "inr_per_share", 1.0), ("Rs per share", "inr_per_share", 1.0),
])
def test_a_unit_text_names_its_scale(text, unit, scale):
    assert stores._unit(text) == (unit, scale)


@pytest.mark.parametrize("text", ["h", "unknown", "kg", None, ""])
def test_an_unknown_unit_is_never_scaled(text):
    assert stores._unit(text)[1] == 1.0


def test_a_unit_that_names_two_scales_is_unknown():
    assert stores._unit("rs lakh crore") == ("unknown", 1.0)
    assert stores._unit("mn crore") == ("unknown", 1.0)


# --- the quote's own year ---------------------------------------------------------------------------
@pytest.mark.parametrize("quote,value,fy", [
    ("FY 2021-22 106,342", 106342.0, "FY22"),
    ("FY 2022-23 1,15,993", 115993.0, "FY23"),
    ("FY 2025-26 1,47,123", 147123.0, "FY26"),
    ("Revenue From Operations (₹ in Mn) 1,26,676 FY2024", 126676.0, "FY24"),
    ("Profit After Tax (₹ in Mn) 25,270 FY2025", 25270.0, "FY25"),
    ("NET WORTH (Rs. Crores) FY 25 3,915", 3915.0, "FY25"),
    ("NET WORTH (` in Crore) 2023-24 4,096", 4096.0, "FY24"),
    ("EBITDA margin in FY 2020\u201121 was better at 14%", 14.0, "FY21"),
    ("Net Debt to EBITDA at 1.36x in FY2021-22", 1.36, "FY22"),
    ("FY'20 28.1", 28.1, "FY20"),
    ("Finance Cost decreased by 11% at `3,738 crore in FY 2020\u201121", 3738.0, "FY21"),
])
def test_the_quote_year_is_the_value_s_own_column(quote, value, fy):
    assert stores._quote_fy(quote, value) == fy


@pytest.mark.parametrize("quote,value", [
    ("1,593 FY22 2,973 FY23", 1593.0),                              # two years: a comparative sentence
    ("Revenue from Operations (Increased by 2.3% y-o-y)", 129645.0),  # no year at all
    ("standalone revenue grew from H1,57,582 Mn in FY24", 216386.0),  # the value is not printed here
    ("EBITDA (` Mn) FY 2023-24 7,701 and FY 2024-25 9,287", 7701.0),
    ("Financial year 2024", 100.0),
])
def test_a_quote_that_cannot_tell_the_column_returns_nothing(quote, value):
    assert stores._quote_fy(quote, value) is None


# --- the row builder --------------------------------------------------------------------------------
def _fact(**over):
    row = {"src_rowid": 1, "isin": "INE000A01000", "item": "Revenue from operations", "value": 106342.0,
           "value_raw": "", "value_check": "found", "unit": "₹ in Mn", "quote": "", "period": "FY26",
           "fiscal_year": "2026-03-31", "basis": "consolidated", "doc_id": 11, "page": 15,
           "known_at": "2026-06-01"}
    row.update(over)
    return row


def _rows(facts):
    return stores._annual_rows("TESTCO", facts, lambda _doc, _page: None, "ar_facts.db")


def test_a_history_table_keeps_each_columns_own_year_and_scale():
    facts = [_fact(value=v, quote=q) for q, v in (
        ("FY 2021-22 106,342", 106342.0), ("FY 2022-23 1,15,993", 115993.0),
        ("FY 2023-24 1,26,676", 126676.0), ("FY 2024-25 1,29,645", 129645.0),
        ("FY 2025-26 1,47,123", 147123.0))]
    rows = _rows(facts)
    assert [r[2] for r in rows] == ["FY22", "FY23", "FY24", "FY25", "FY26"]
    assert [r[3] for r in rows] == ["2022-03-31", "2023-03-31", "2024-03-31", "2025-03-31", "2026-03-31"]
    assert {r[9] for r in rows} == {"inr_million"} and {r[10] for r in rows} == {1e6}


def test_a_rupee_lakh_line_is_stored_at_its_own_scale():
    row = _rows([_fact(value=979846.22, unit="rs lakh", quote="Revenue 9,79,846.22")])[0]
    assert (row[9], row[10]) == ("inr_lakh", 1e5)


def test_one_figure_printed_twice_in_one_document_keeps_one_row():
    rows = _rows([
        _fact(value=129645.0, period="FY25", quote="Revenue From Operations (₹ in Mn) 1,29,645 FY2025"),
        _fact(value=129645.0, period="FY25", page=9, quote="Revenue from Operations (Increased by 2.3% y-o-y)"),
    ])
    assert len(rows) == 1 and rows[0][2] == "FY25"


def test_the_same_figure_in_two_documents_stays_two_rows():
    assert len(_rows([_fact(doc_id=1), _fact(doc_id=2, page=20)])) == 2


def test_a_quote_that_cannot_tell_the_column_keeps_the_stored_period():
    rows = _rows([
        _fact(value=1593.0, unit="Rs crore", period="FY22", quote="1,593 FY22 2,973 FY23"),
        _fact(value=216386.0, unit="Rs million", period="FY25",
              quote="standalone revenue grew from H1,57,582 Mn in FY24"),
    ])
    assert [r[2] for r in rows] == ["FY22", "FY25"]


# --- the build path ---------------------------------------------------------------------------------
def test_build_annual_writes_the_year_and_the_scale(monkeypatch):
    cols = ["src_rowid", "doc_id", "piece", "isin", "symbol", "fiscal_year", "filed_at", "page", "category",
            "item", "value_raw", "value", "unit", "period", "basis", "quote", "model", "value_check",
            "prompt_version", "known_at"]
    raw = [tuple({"src_rowid": 7, "doc_id": 42, "piece": 1, "isin": "INE000A01000", "symbol": "TESTCO",
                  "fiscal_year": "2026-03-31", "filed_at": "2026-06-01", "page": 15, "category": "financials",
                  "item": "Revenue from operations", "value_raw": "", "value": 126676.0, "unit": "₹ in Mn",
                  "period": "FY26", "basis": "consolidated", "quote": "FY 2023-24 1,26,676", "model": "m",
                  "value_check": "found", "prompt_version": "p", "known_at": "2026-06-01"}[c] for c in cols)]
    monkeypatch.setattr(stores, "profile", SimpleNamespace(symbols=lambda: ["TESTCO"]))
    monkeypatch.setattr(stores, "_spec", lambda _symbol, _table: {
        "db": "ar_facts.db", "source": "ar_facts",
        "sql": "SELECT *, filed_at AS known_at FROM ar_facts WHERE 1", "params": ()})
    monkeypatch.setattr(stores.prepare, "_read_sqlite", lambda *_a, **_k: (raw, dict.fromkeys(cols, "TEXT")))
    monkeypatch.setattr(stores, "_ar_page_bases",
                        lambda _spec, _symbol: ((lambda _doc, _page: None), (lambda: None)))
    conn = sqlite3.connect(":memory:")
    try:
        assert stores.build_annual(conn) == {"TESTCO": 1}
        row = conn.execute("SELECT fiscal_year, period_end, value, unit, scale, source_rowid "
                           "FROM fin_annual_line").fetchone()
    finally:
        conn.close()
    assert row == ("FY24", "2024-03-31", 126676.0, "inr_million", 1e6, "7")
