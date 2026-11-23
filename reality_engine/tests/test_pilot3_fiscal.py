"""Tests for reality_engine.pilot3.fiscal and non-March fiscal year routing (T-223, phases 1 & 2)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from reality_engine.pilot3 import (
    ar_notes,
    ar_statements,
    comparatives,
    fiscal,
    guidance,
    kpi,
    notes,
    profile,
    ratios,
    row_checks,
    schema,
    statements,
    stores,
    transcripts,
)


# --- Reference March-year functions (must match fiscal(..., fy_end=3) identically) ----------------------
def _ref_march_quarter(period_end: str) -> str | None:
    try:
        y, m = int(period_end[:4]), int(period_end[5:7])
    except (TypeError, ValueError):
        return None
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    if q is None:
        return None
    fy = y + 1 if m >= 4 else y
    return f"Q{q}FY{str(fy)[2:]}"


def _ref_march_fy(end: str) -> str:
    y, m = int(end[:4]), int(end[5:7])
    return f"FY{str(y + 1 if m >= 4 else y)[2:]}"


def _ref_march_last_fy_end(end: str) -> str:
    y, m = int(end[:4]), int(end[5:7])
    return f"{y - 1}-03-31" if m == 3 else f"{y}-03-31"


def _ref_march_cmp_quarter(period_end: str, ptype: str) -> tuple[str, str, str] | None:
    y, m = int(period_end[:4]), int(period_end[5:7])
    fy = y + 1 if m >= 4 else y
    if ptype == "fy":
        return f"FY{str(fy)[2:]}", f"{fy - 1}-04-01", "fy"
    if ptype == "ytd":
        if m not in (9, 12):
            return None
        label = "H1" if m == 9 else "9M"
        return f"{label}FY{str(fy)[2:]}", f"{fy - 1}-04-01", "ytd"
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    start = {6: f"{y}-04-01", 9: f"{y}-07-01", 12: f"{y}-10-01", 3: f"{y}-01-01"}.get(m, f"{y}-01-01")
    return f"Q{q or '?'}FY{str(fy)[2:]}", start, "quarter"


def _ref_march_role_set(end: str, count: int) -> list[str | None]:
    m = int(end[5:7])
    if m == 6:
        if count <= 3:
            return list(comparatives.ROLE_ORDER[:count])
        if count == 4 or count >= 7:
            return ["current", "preceding", "year_ago", "last_fy"]
        if count == 5:
            return ["current", "preceding", "year_ago", None, "last_fy"]
        return ["current", "preceding", "year_ago", None, None, "last_fy"]
    if count == 6:
        return ["current", "preceding", "year_ago", "ytd", "prior_ytd", "last_fy"]
    if count == 5:
        if m == 3:
            return ["current", "preceding", "year_ago", "ytd", "prior_ytd"]
        if m in (9, 12):
            return ["current", "year_ago", "ytd", "prior_ytd", "last_fy"]
        return list(comparatives.ROLE_ORDER[:5])
    if count == 4:
        if m == 3:
            return ["current", "preceding", "ytd", "prior_ytd"]
        if m in (9, 12):
            return ["current", "year_ago", "ytd", "prior_ytd"]
        return ["current", "preceding", "year_ago", "last_fy"]
    return list(comparatives.ROLE_ORDER[:count])


def _ref_march_expected_date(role: str, end: str) -> tuple[int, int]:
    y, m = int(end[:4]), int(end[5:7])
    if role in ("current", "ytd"):
        return m, y
    if role == "preceding":
        return (m - 3, y) if m > 3 else (m + 9, y - 1)
    if role in ("year_ago", "prior_ytd"):
        return m, y - 1
    if role == "last_fy":
        return 3, y
    return m, y


QUARTER_DATES = [
    f"{y}-{m:02d}-{d:02d}"
    for y in range(2019, 2028)
    for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
]


def test_fy_end_3_matches_original_march_functions():
    assert fiscal.current() == 3
    for m in range(1, 13):
        assert fiscal.march_equivalent_month(m, 3) == m

    for d in QUARTER_DATES:
        assert fiscal.fiscal_quarter(d, 3) == _ref_march_quarter(d)
        assert stores.fiscal_period(d) == _ref_march_quarter(d)
        assert ratios._fiscal_q(d) == _ref_march_quarter(d)

        assert fiscal.fy_label(d, 3) == _ref_march_fy(d)
        assert comparatives._fy_of(d) == _ref_march_fy(d)
        assert ratios._fy_of(d) == _ref_march_fy(d)

        assert fiscal.last_fy_end(d, 3) == _ref_march_last_fy_end(d)
        assert comparatives._last_fy_end(d) == _ref_march_last_fy_end(d)
        assert ratios._last_fy_end(d) == _ref_march_last_fy_end(d)

        for ptype in ("quarter", "ytd", "fy"):
            assert comparatives._quarter(d, ptype) == _ref_march_cmp_quarter(d, ptype)

        for count in range(1, 9):
            assert comparatives._role_set(d, count) == _ref_march_role_set(d, count)

        for role in ("current", "preceding", "year_ago", "ytd", "prior_ytd", "last_fy"):
            if role == "last_fy" and d.endswith("-03-31"):
                continue  # Q4 tables have no last_fy role; _last_fy_end itself is already verified above
            assert comparatives._expected_date(role, d) == _ref_march_expected_date(role, d)

    for bad in ("2025-05-31", "2026-01-31", "", None, "bad"):
        assert fiscal.fiscal_quarter(bad, 3) is None
        assert stores.fiscal_period(bad) is None


def test_fy_end_12_rsystems_examples():
    # Quarter labels & starts
    assert fiscal.fiscal_quarter("2026-03-31", 12) == "Q1FY26"
    assert fiscal.fiscal_quarter("2026-06-30", 12) == "Q2FY26"
    assert fiscal.fiscal_quarter("2026-09-30", 12) == "Q3FY26"
    assert fiscal.fiscal_quarter("2025-12-31", 12) == "Q4FY25"
    assert fiscal.fiscal_quarter("2025-03-31", 12) == "Q1FY25"

    # FY labels and starts
    assert fiscal.fy_label("2025-12-31", 12) == "FY25"
    assert fiscal.fy_label("2026-03-31", 12) == "FY26"
    assert fiscal.fy_label("2026-09-30", 12) == "FY26"
    assert fiscal.fy_start("2025-12-31", 12) == "2025-01-01"
    assert fiscal.fy_start("2026-03-31", 12) == "2026-01-01"
    assert fiscal.fy_start("2026-09-30", 12) == "2026-01-01"

    # YTD labels
    assert fiscal.ytd_label("2026-06-30", 6, 12) == "H1FY26"
    assert fiscal.ytd_label("2026-09-30", 9, 12) == "9MFY26"
    assert fiscal.ytd_label("2025-12-31", 12, 12) == "FY25"

    # Last completed FY end
    assert fiscal.last_fy_end("2026-03-31", 12) == "2025-12-31"
    assert fiscal.last_fy_end("2026-06-30", 12) == "2025-12-31"
    assert fiscal.last_fy_end("2026-09-30", 12) == "2025-12-31"
    assert fiscal.last_fy_end("2025-12-31", 12) == "2024-12-31"

    # March-equivalent month mapping
    assert fiscal.march_equivalent_month(3, 12) == 6
    assert fiscal.march_equivalent_month(6, 12) == 9
    assert fiscal.march_equivalent_month(9, 12) == 12
    assert fiscal.march_equivalent_month(12, 12) == 3


def test_context_manager_nesting_and_exception_safety():
    assert fiscal.current() == 3
    with fiscal.use(12):
        assert fiscal.current() == 12
        with fiscal.use(6):
            assert fiscal.current() == 6
        assert fiscal.current() == 12
    assert fiscal.current() == 3

    with pytest.raises(RuntimeError):
        with fiscal.use(12):
            assert fiscal.current() == 12
            raise RuntimeError("boom")
    assert fiscal.current() == 3


def test_comparatives_under_fy_end_12():
    with fiscal.use(12):
        assert comparatives._fy_of("2025-12-31") == "FY25"
        assert comparatives._fy_of("2026-03-31") == "FY26"

        assert comparatives._quarter("2026-03-31", "quarter") == ("Q1FY26", "2026-01-01", "quarter")
        assert comparatives._quarter("2026-03-31", "ytd") is None
        assert comparatives._quarter("2026-06-30", "quarter") == ("Q2FY26", "2026-04-01", "quarter")
        assert comparatives._quarter("2026-06-30", "ytd") == ("H1FY26", "2026-01-01", "ytd")
        assert comparatives._quarter("2026-09-30", "quarter") == ("Q3FY26", "2026-07-01", "quarter")
        assert comparatives._quarter("2026-09-30", "ytd") == ("9MFY26", "2026-01-01", "ytd")
        assert comparatives._quarter("2025-12-31", "quarter") == ("Q4FY25", "2025-10-01", "quarter")
        assert comparatives._quarter("2025-12-31", "fy") == ("FY25", "2025-01-01", "fy")
        assert comparatives._quarter("2025-12-31", "ytd") is None

        # Q1 (March end) must get the Q1 role pool (no YTD) and last_fy expected in Dec 2025
        assert comparatives._role_set("2026-03-31", 4) == ["current", "preceding", "year_ago", "last_fy"]
        assert comparatives._role_set("2026-03-31", 5) == ["current", "preceding", "year_ago", None, "last_fy"]
        assert comparatives._role_set("2026-06-30", 5) == ["current", "year_ago", "ytd", "prior_ytd", "last_fy"]
        assert comparatives._role_set("2025-12-31", 4) == ["current", "preceding", "ytd", "prior_ytd"]

        assert comparatives._expected_date("last_fy", "2026-03-31") == (12, 2025)
        assert comparatives._expected_date("last_fy", "2026-06-30") == (12, 2025)
        assert comparatives._role_period("ytd", "2025-12-31") == ("2025-12-31", "fy")
        assert comparatives._role_period("ytd", "2026-06-30") == ("2026-06-30", "ytd")


def test_comparatives_table_rows_rsystems_q1():
    cols = (200.0, 260.0, 320.0, 380.0)
    dates = ("31.03.2026", "31.12.2025", "31.03.2025", "31.12.2025")

    def w(x1: float, text: str, y: float) -> tuple:
        return (x1 - 7.0 * len(text), y - 3.0, x1, y + 3.0, text, 0, 0, 0)

    rows_data = [
        ("1 Revenue from operations", ("500", "480", "450", "1,850")),
        ("2 Other income", ("20", "15", "18", "65")),
        ("3 Total income", ("520", "495", "468", "1,915")),
        ("4 Total expenses", ("400", "380", "360", "1,480")),
        ("5 Profit before exceptional items and tax", ("120", "115", "108", "435")),
        ("6 Total tax expense", ("30", "28", "27", "108")),
        ("7 Profit for the period", ("90", "87", "81", "327")),
        ("8 Basic EPS", ("7.5", "7.3", "6.8", "27.4")),
    ]
    words = [(40.0, 5.0, 220.0, 13.0, "Statement of Consolidated Financial Results", 0, 0, 0),
             (40.0, 15.0, 110.0, 23.0, "Rs. in Crore", 0, 0, 0)]
    words += [w(cols[i], text, 30.0) for i, text in enumerate(dates)]
    for i, (label, values) in enumerate(rows_data):
        y, x = 50.0 + 10.0 * i, 20.0
        for word in label.split():
            width = 7.0 * len(word)
            words.append((x, y - 3.0, x + width, y + 3.0, word, 0, 0, 0))
            x += width + 3.0
        words += [w(cols[j], text, y) for j, text in enumerate(values)]

    table = comparatives.read_page(comparatives.rows_from_words(words))
    assert table is not None
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    conn.execute("INSERT INTO company (symbol, isin) VALUES ('RSYSTEMS', 'INE411H01032')")
    with fiscal.use(12):
        stored = comparatives._table_rows(
            conn, "RSYSTEMS", "INE411H01032", "doc_q1", 1, "2026-05-10T12:00:00", table, {}, []
        )
    periods = {(r[6], r[2], r[3], r[4], r[5]) for r in stored}
    assert ("current", "2026-01-01", "2026-03-31", "Q1FY26", "quarter") in periods
    assert ("preceding", "2025-10-01", "2025-12-31", "Q4FY25", "quarter") in periods
    assert ("year_ago", "2025-01-01", "2025-03-31", "Q1FY25", "quarter") in periods
    assert ("last_fy", "2025-01-01", "2025-12-31", "FY25", "fy") in periods
    assert not any(r[5] == "ytd" for r in stored)
    assert not any(r[4] == "FY26" for r in stored)


def test_kpi_under_fy_end_12():
    with fiscal.use(12):
        p_q1 = kpi.doc_default_period(["Financial results for the quarter ended March 31, 2026"])
        assert len(p_q1) == 1
        assert (p_q1[0].canon, p_q1[0].ptype, p_q1[0].as_of) == ("Q1FY26", "Q", "2026-03-31")

        p_h1 = kpi.doc_default_period(["Results for the six months ended June 30, 2026"])
        assert (p_h1[0].canon, p_h1[0].ptype, p_h1[0].as_of) == ("H1FY26", "H", "2026-06-30")

        p_9m = kpi.doc_default_period(["Results for the nine months ended September 30, 2026"])
        assert (p_9m[0].canon, p_9m[0].ptype, p_9m[0].as_of) == ("9MFY26", "9M", "2026-09-30")

        p_q4 = kpi.doc_default_period(["Results for the quarter ended December 31, 2025"])
        assert (p_q4[0].canon, p_q4[0].ptype, p_q4[0].as_of) == ("Q4FY25", "Q", "2025-12-31")

        p_fy = kpi.doc_default_period(["Annual Report for the year ended on December 31, 2025"], ytd=False)
        assert (p_fy[0].canon, p_fy[0].ptype, p_fy[0].as_of) == ("FY25", "FY", "2025-12-31")

        assert kpi.period_start("Q", "Q1FY26") == "2026-01-01"
        assert kpi.period_end("Q", "Q1FY26") == "2026-03-31"
        assert kpi.period_start("H", "H1FY26") == "2026-01-01"
        assert kpi.period_end("H", "H1FY26") == "2026-06-30"
        assert kpi.period_start("FY", "FY25") == "2025-01-01"
        assert kpi.period_end("FY", "FY25") == "2025-12-31"


def test_ratios_under_fy_end_12(monkeypatch):
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    conn.execute("INSERT INTO company (symbol, isin) VALUES ('RSYSTEMS', 'INE411H01032')")
    conn.execute("INSERT INTO doc (doc_key, symbol, doc_type) VALUES ('d1', 'RSYSTEMS', 'annual_report')")
    conn.executemany(
        "INSERT INTO doc_page (doc_key, symbol, page, text) VALUES (?, 'RSYSTEMS', ?, ?)",
        [
            ("d1", 1, "YEAR ENDED ON DECEMBER 31, 2025"),
            ("d1", 2, "For the year ended December 31, 2025"),
            ("d1", 3, "Year ended 31st December 2025"),
        ],
    )
    quarters = [
        ("2025-01-01", "2025-03-31", "Q1FY25", 100.0, "2025-05-10"),
        ("2025-04-01", "2025-06-30", "Q2FY25", 110.0, "2025-08-10"),
        ("2025-07-01", "2025-09-30", "Q3FY25", 120.0, "2025-11-10"),
        ("2025-10-01", "2025-12-31", "Q4FY25", 130.0, "2026-02-15"),
    ]
    for s, e, fp, val, ka in quarters:
        conn.execute(
            "INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, "
            "audited, statement, line_item, xbrl_tag, value, unit, scale, known_at) "
            "VALUES ('RSYSTEMS', 'INE411H01032', ?, ?, ?, 'consolidated', 'audited', 'P&L', "
            "'revenue_from_operations', 'RevenueFromOperations', ?, 'inr', 1.0, ?)",
            (s, e, fp, val, ka),
        )
        conn.execute(
            "INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, "
            "audited, statement, line_item, xbrl_tag, value, unit, scale, known_at) "
            "VALUES ('RSYSTEMS', 'INE411H01032', ?, ?, ?, 'consolidated', 'audited', 'P&L', "
            "'pat', 'ProfitLossForPeriod', ?, 'inr', 1.0, ?)",
            (s, e, fp, val * 0.1, ka),
        )
    monkeypatch.setattr(profile, "symbols", lambda: ["RSYSTEMS"])
    monkeypatch.setattr(profile, "under_profile", lambda: False)
    monkeypatch.setattr(profile, "price_start", lambda: "2024-01-01")
    monkeypatch.setattr(profile, "is_lender", lambda _s: False)
    ratios.build_ratios(conn)
    row = conn.execute(
        "SELECT period_start, period_end, value FROM ratio_panel "
        "WHERE symbol='RSYSTEMS' AND fiscal_period='FY25' AND period_type='FY' AND metric='revenue_from_operations'"
    ).fetchone()
    assert row == ("2025-01-01", "2025-12-31", 460.0)


def _make_doc_db(path: str | Path, pages: list[tuple[str, str, str, int, str]]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT)")
    conn.execute("CREATE TABLE doc_page (doc_key TEXT, symbol TEXT, page INTEGER, text TEXT)")
    seen = set()
    for dk, sym, dt, pg, txt in pages:
        if dk not in seen:
            conn.execute("INSERT INTO doc VALUES (?, ?, ?)", (dk, sym, dt))
            seen.add(dk)
        conn.execute("INSERT INTO doc_page VALUES (?, ?, ?, ?)", (dk, sym, pg, txt))
    conn.commit()
    return conn


def test_fy_end_month_rules_and_cache(tmp_path):
    fiscal.clear_cache()

    # Fewer than 3 hits -> falls back to 3
    c1 = _make_doc_db(":memory:", [
        ("d1", "CO", "annual_report", 1, "YEAR ENDED ON DECEMBER 31, 2025"),
        ("d1", "CO", "results", 2, "year ended December 31 2024"),
        # page 4 and transcript must be ignored
        ("d1", "CO", "annual_report", 4, "year ended December 31, 2025"),
        ("d2", "CO", "transcript", 1, "year ended December 31, 2025"),
    ])
    assert fiscal.fy_end_month(c1, "CO") == 3

    # 3 hits out of 6 (50% < 60%) -> falls back to 3
    c2 = _make_doc_db(":memory:", [
        ("d1", "CO", "annual_report", 1, "year ended December 31, 2025; year ended 31 December 2024"),
        ("d2", "CO", "results", 1, "year ended on December 31, 2025"),
        ("d2", "CO", "results", 2, "year ended March 31, 2025; year ended 31st March 2024; year ended March 31 2023"),
    ])
    assert fiscal.fy_end_month(c2, "CO") == 3

    # 3 hits out of 5 (60% >= 60%) -> 12
    c3 = _make_doc_db(":memory:", [
        ("d1", "CO", "annual_report", 1, "YEAR ENDED ON DECEMBER 31, 2025 and year ended 31st December 2024"),
        ("d2", "CO", "results", 3, "year ended on the December 31, 2025"),
        ("d2", "CO", "results", 2, "year ended 31 March 2025; year ended March 31, 2024"),
    ])
    assert fiscal.fy_end_month(c3, "CO") == 12

    # File-backed cache per (database file, symbol)
    db_file = tmp_path / "cached.db"
    c4 = _make_doc_db(db_file, [
        ("d1", "CO", "annual_report", 1, "year ended December 31, 2025"),
        ("d1", "CO", "annual_report", 2, "year ended December 31, 2024"),
        ("d2", "CO", "results", 1, "year ended 31 December 2025"),
    ])
    assert fiscal.fy_end_month(c4, "CO") == 12
    c4.execute("DELETE FROM doc_page")
    c4.commit()
    assert fiscal.fy_end_month(c4, "CO") == 12  # cached for (db_file, 'CO')
    assert fiscal.fy_end_month(c4, "OTHER") == 3
    fiscal.clear_cache()
    assert fiscal.fy_end_month(c4, "CO") == 3
    c4.close()


def test_fy_end_month_ignores_half_year_and_quarter_and_prefixes():
    fiscal.clear_cache()

    # 5x "quarter and half year ended September 30, 2025" + 2x "year ended March 31, 2025" -> 3
    c_sep = _make_doc_db(":memory:", [
        ("d1", "OCCLLTD", "results", 1, "Results for the quarter and half year ended September 30, 2025"),
        ("d1", "OCCLLTD", "results", 2, "Unaudited quarter and half year ended September 30, 2025"),
        ("d2", "OCCLLTD", "results", 1, "Quarter and half-year ended September 30, 2025"),
        ("d2", "OCCLLTD", "results", 2, "Quarter and ha1f year ended September 30, 2025"),
        ("d3", "OCCLLTD", "results", 1, "Quarter and half year ended September 30, 2025; nine months year ended September 30, 2025; quarter and year ended September 30, 2025"),
        ("d4", "OCCLLTD", "annual_report", 1, "For the year ended March 31, 2025"),
        ("d4", "OCCLLTD", "annual_report", 2, "Financial year ended March 31, 2025"),
    ])
    assert fiscal.fy_end_month(c_sep, "OCCLLTD") == 3

    # RSYSTEMS texts still give 12 (including "financial year ended" and "year ending")
    c_rsys = _make_doc_db(":memory:", [
        ("d1", "RSYSTEMS", "annual_report", 1, "ANNUAL REPORT FOR THE FINANCIAL YEAR ENDED ON DECEMBER 31, 2025"),
        ("d2", "RSYSTEMS", "results", 1, "For the year ending on December 31, 2025"),
        ("d2", "RSYSTEMS", "results", 2, "Financial Results for the year ended December 31, 2025"),
    ])
    assert fiscal.fy_end_month(c_rsys, "RSYSTEMS") == 12


def test_c75_and_c08_stores_readonly():
    c75_path = Path("D:/RealityEngine/tg_build/measure10/c75/c75.db")
    if not c75_path.is_file():
        pytest.skip(f"{c75_path} not present")
    c75 = sqlite3.connect(f"file:{c75_path.as_posix()}?mode=ro", uri=True)
    try:
        assert fiscal.fy_end_month(c75, "RSYSTEMS") == 12
        rows = c75.execute(
            "SELECT DISTINCT period_start, period_end FROM fin_quarter_xbrl "
            "WHERE symbol='RSYSTEMS' AND (julianday(period_end) - julianday(period_start)) BETWEEN 80 AND 100 "
            "ORDER BY period_end"
        ).fetchall()
        assert rows
        with fiscal.use(12):
            by_span = {}
            for p_start, p_end in rows:
                q = fiscal.fiscal_quarter(p_end)
                assert q is not None
                q_start = kpi.period_start("Q", q)
                assert q_start is not None
                assert int(q_start[5:7]) == int(p_start[5:7])
                by_span[(p_start, p_end)] = q
            assert by_span[("2026-01-01", "2026-03-31")] == "Q1FY26"
            assert by_span[("2025-10-01", "2025-12-31")] == "Q4FY25"
    finally:
        c75.close()

    c08_path = Path("D:/RealityEngine/tg_build/measure10/c08/c08.db")
    if not c08_path.is_file():
        pytest.skip(f"{c08_path} not present")
    c08 = sqlite3.connect(f"file:{c08_path.as_posix()}?mode=ro", uri=True)
    try:
        sym = c08.execute("SELECT DISTINCT symbol FROM company").fetchone()[0]
        assert fiscal.fy_end_month(c08, sym) == 3
    finally:
        c08.close()


# --- Phase 2: transcripts, guidance, statements, stores, ar_statements, ar_notes, notes ---------------
def test_phase2_fiscal_helpers_march_and_december():
    # Default March matches historical logic identically
    assert fiscal.quarter_end_date("Q1FY26") == "2025-06-30"
    assert fiscal.quarter_end_date("Q2FY26") == "2025-09-30"
    assert fiscal.quarter_end_date("Q3FY26") == "2025-12-31"
    assert fiscal.quarter_end_date("Q4FY26") == "2026-03-31"
    assert fiscal.quarter_end_date("FY26") is None
    assert fiscal.filing_quarter("2026-05-06T18:00:00") == "Q4FY26"
    assert fiscal.filing_quarter("2026-08-11") == "Q1FY27"
    assert fiscal.filing_quarter("2026-11-10") == "Q2FY27"
    assert fiscal.filing_quarter("2026-02-18") == "Q3FY26"

    with fiscal.use(12):
        assert fiscal.quarter_end_date("Q1FY26") == "2026-03-31"
        assert fiscal.quarter_end_date("Q2FY26") == "2026-06-30"
        assert fiscal.quarter_end_date("Q3FY26") == "2026-09-30"
        assert fiscal.quarter_end_date("Q4FY25") == "2025-12-31"
        assert fiscal.filing_quarter("2026-05-06T18:00:00") == "Q1FY26"
        assert fiscal.filing_quarter("2026-08-11") == "Q2FY26"
        assert fiscal.filing_quarter("2026-11-10") == "Q3FY26"
        assert fiscal.filing_quarter("2026-02-18") == "Q4FY25"


def test_transcripts_under_fy_end_12(tmp_path):
    # March default unchanged
    assert transcripts.filing_quarter("2026-05-06T12:00:00") == "Q4FY26"
    assert transcripts.quarter_end_of("Q1FY26") == "2025-06-30"

    with fiscal.use(12):
        assert transcripts.filing_quarter("2026-05-06T12:00:00") == "Q1FY26"
        assert transcripts.quarter_end_of("Q1FY26") == "2026-03-31"
        # Explicit company-titled Q1FY26 stays Q1FY26; undated Q2 call in Aug infers Q2FY26; future Q1FY27 rejected
        assert transcripts.call_period_ok("Q1FY26", "2026-05-06") == "Q1FY26"
        assert transcripts.call_period_ok(None, "2026-08-11") == "Q2FY26"
        assert transcripts.call_period_ok("Q1FY27", "2026-05-06") == "Q1FY26"

    db = tmp_path / "tr.db"
    con = sqlite3.connect(db)
    schema.create(con, ["company", "doc", "doc_page"])
    con.execute("INSERT INTO company (symbol, isin, name) VALUES ('RSYSTEMS', 'INE411H01032', 'R Systems')")
    con.execute("INSERT INTO doc (doc_key, symbol, doc_type, title, known_at) "
                "VALUES ('ar1', 'RSYSTEMS', 'annual_report', 'AR', '2026-04-01')")
    for pg in (1, 2, 3):
        con.execute("INSERT INTO doc_page (doc_key, symbol, page, text) "
                    "VALUES ('ar1', 'RSYSTEMS', ?, 'For the year ended December 31, 2025')", (pg,))
    con.execute("INSERT INTO doc (doc_key, symbol, doc_type, title, known_at) "
                "VALUES ('tr1', 'RSYSTEMS', 'transcript', 'Earnings Call', '2026-08-11T18:00:00')")
    con.execute(
        "INSERT INTO doc_page (doc_key, symbol, page, text) VALUES ('tr1', 'RSYSTEMS', 1, ?)",
        ("CORPORATE PARTICIPANTS:\n\nNitesh Bansal\nChief Executive Officer\n\n"
         "ANALYSTS\n\nAmit Jain\nAxis Capital\n",),
    )
    con.execute(
        "INSERT INTO doc_page (doc_key, symbol, page, text) VALUES ('tr1', 'RSYSTEMS', 2, ?)",
        ("Moderator: Good evening everyone.\n"
         "Nitesh Bansal: Revenue grew strongly in the quarter.\n"
         "Amit Jain: How are deal wins trending?\n"
         "Nitesh Bansal: Deal pipeline remains healthy across geographies.\n",),
    )
    con.commit()
    con.close()
    transcripts.run(str(db), ["RSYSTEMS"], None)
    con = sqlite3.connect(db)
    try:
        ts_periods = {r[0] for r in con.execute("SELECT call_period FROM transcript_statement WHERE symbol='RSYSTEMS'")}
        tq_periods = {r[0] for r in con.execute("SELECT call_period FROM transcript_question WHERE symbol='RSYSTEMS'")}
        assert ts_periods == {"Q2FY26"}
        assert tq_periods == {"Q2FY26"}
    finally:
        con.close()


def test_guidance_under_fy_end_12():
    assert guidance.doc_period("2026-05-07", None) == (26, "Q4")
    with fiscal.use(12):
        assert guidance.doc_period("2026-05-07", None) == (26, "Q1")
        assert guidance.doc_period("2026-02-18", None) == (25, "Q4")
        # Q1 call in May 2026 guiding "for this year" targets FY26 (under March it looked like Q4 -> FY27)
        assert guidance.target_period(
            "We expect revenue growth of 12% for this year.", "", "", "Q1FY26", (26, "Q1"), 25
        ) == "FY26"
        assert guidance.target_period(
            "Margins will be 18% in the next quarter.", "", "", "Q1FY26", (26, "Q1"), 16
        ) == "Q2FY26"


def test_statements_and_dividends_under_fy_end_12(monkeypatch):
    # March default unchanged
    assert statements._fy("2026-03-31") == "FY26"
    assert statements._dividend_fy(date(2025, 11, 19), "interim") == "FY26"
    assert statements._dividend_fy(date(2025, 6, 15), "final") == "FY25"

    with fiscal.use(12):
        assert statements._fy("2025-12-31") == "FY25"
        assert statements._quarter_end("Q1FY26") == "2026-03-31"
        assert statements._period_of(statements._PERIOD.search("31 Mar 2026")) == ("Q", "Q1FY26")
        assert statements._dividend_fy(date(2025, 11, 19), "interim") == "FY25"
        assert statements._dividend_fy(date(2025, 5, 14), "final") == "FY24"
        assert statements._dividend_fy(date(2025, 5, 14), "interim") == "FY25"

    conn = sqlite3.connect(":memory:")
    schema.create(conn, ["company", "doc", "doc_page", "fin_annual_line"])
    conn.execute("INSERT INTO company (symbol, isin) VALUES ('RSYSTEMS', 'INE411H01032')")
    conn.execute("INSERT INTO doc (doc_key, symbol, doc_type) VALUES ('ar1', 'RSYSTEMS', 'annual_report')")
    for pg in (1, 2, 3):
        conn.execute("INSERT INTO doc_page (doc_key, symbol, page, text) "
                     "VALUES ('ar1', 'RSYSTEMS', ?, 'Year ended December 31, 2025')", (pg,))
    monkeypatch.setattr(statements, "profile", SimpleNamespace(
        symbols=lambda: ["RSYSTEMS"], under_profile=lambda: False, is_lender=lambda _s: False,
    ))
    monkeypatch.setattr(statements, "_duck", lambda *_a, **_k: (
        [(101, "INE411H01032", "Interim Dividend - Rs 6 Per Share", date(2025, 5, 14),
          None, 1.0, date(2025, 5, 1))],
        ["id", "isin", "subject", "ex_date", "rec_date", "face_value", "broadcast_date"],
    ))
    statements.build_dividends(conn)
    assert conn.execute("SELECT fiscal_year FROM dividend_event WHERE symbol='RSYSTEMS'").fetchone() == ("FY25",)
    assert conn.execute(
        "SELECT fiscal_year, period_end FROM fin_annual_line WHERE symbol='RSYSTEMS' AND line_item='dividend_per_share'"
    ).fetchone() == ("FY25", "2025-12-31")

    monkeypatch.setattr(statements, "fetch", lambda _s, _t: [
        {"file": "x_fy25.xml", "isin": "INE411H01032", "period_end": "2025-12-31",
         "reporting_quarter": "Fourth quarter", "consolidated": "Consolidated", "known_at": "2026-02-15", "status": "ok"},
        {"file": "x_h126.xml", "isin": "INE411H01032", "period_end": "2026-06-30",
         "reporting_quarter": "Half yearly", "consolidated": "Consolidated", "known_at": "2026-08-10", "status": "ok"},
    ])
    monkeypatch.setattr(statements.prepare, "_read_sqlite", lambda _db, _tbl, _sql, params: (
        [("Assets", "OneI", None, None, "2025-12-31" if "fy25" in params[0] else "2026-06-30", 500.0, "INR", 1)],
        ["concept", "context", "period_start", "period_end", "instant", "value", "unit", "rowid"],
    ))
    statements.build_xbrl_statements(conn)
    xbrl_rows = conn.execute(
        "SELECT fiscal_year, period_end, period_type FROM fin_annual_line "
        "WHERE symbol='RSYSTEMS' AND definition='xbrl_reported' ORDER BY period_end"
    ).fetchall()
    assert xbrl_rows == [("FY25", "2025-12-31", "FY"), ("H1FY26", "2026-06-30", "H1")]
    conn.close()


def test_stores_annual_under_fy_end_12():
    assert stores._fy_label(None, "2025-03-31") == "FY25"
    with fiscal.use(12):
        assert stores._fy_label(None, "2025-12-31") == "FY25"
        assert stores._fy_label(None, "2025-03-31") is None
        rows = stores._annual_rows(
            "RSYSTEMS",
            [{"src_rowid": 1, "isin": "INE411H01032", "item": "Total assets", "value": 100.0,
              "value_raw": "", "value_check": "found", "unit": "inr_million", "quote": "", "period": None,
              "fiscal_year": "2025-12-31", "basis": "consolidated", "doc_id": 74160, "page": 10,
              "known_at": "2026-03-01"}],
            lambda _doc, _page: None,
            "ar_facts.db",
        )
        assert len(rows) == 1
        assert (rows[0][2], rows[0][3]) == ("FY25", "2025-12-31")


def test_ar_statements_and_ar_notes_under_fy_end_12():
    assert ar_statements.fiscal_label("2025-03-31") == "FY25"
    assert ar_statements.fiscal_label("2023-12-31") == "FY23"

    words = [
        (50.0, 10.0, 90.0, 20.0, "As"), (95.0, 10.0, 115.0, 20.0, "At"),
        (200.0, 25.0, 220.0, 35.0, "31,"), (225.0, 25.0, 260.0, 35.0, "2025"),
        (300.0, 25.0, 320.0, 35.0, "31,"), (325.0, 25.0, 360.0, 35.0, "2024"),
    ]
    lines = [[0, 1], [2, 3, 4, 5]]
    fy_words = [(200.0, 10.0, 260.0, 20.0, "2024-25"), (300.0, 10.0, 360.0, 20.0, "2023-24")]

    with fiscal.use(12):
        assert ar_statements.fiscal_label("2025-12-31") == "FY25"
        assert ar_statements.fiscal_label("2026-03-31") == "FY26"
        assert ar_statements._columns(words, lines)[1] == ["2025-12-31", "2024-12-31"]
        assert ar_statements._columns(fy_words, [[0, 1]])[1] == ["2025-12-31", "2024-12-31"]
        assert ar_notes._columns(words, lines)[1] == ["2025-12-31", "2024-12-31"]
        assert ar_notes._columns(fy_words, [[0, 1]])[1] == ["2025-12-31", "2024-12-31"]


def test_notes_and_rpt_under_fy_end_12():
    march_ar = {"doc_type": "annual_report", "filing_date": "2026-07-07", "known_at": None}
    assert notes._doc_fy(march_ar) == "FY26"
    assert notes._fy_period("FY26") == "2026-03-31"
    assert notes.header_columns(["Particulars", "2026 2025"], 1)[0] == [("FY26", "2026-03-31"), ("FY25", "2025-03-31")]

    dec_ar = {"doc_key": "d1", "doc_type": "annual_report", "filing_date": "2026-04-15", "known_at": "2026-04-15"}
    dec_ann = {"doc_key": "d2", "doc_type": "announcement", "filing_date": "2025-11-10", "known_at": "2025-11-10"}
    lex = notes.lexicon()
    with fiscal.use(12):
        assert notes._doc_fy(dec_ar) == "FY25"
        assert notes._doc_fy(dec_ann) == "FY25"
        assert notes._fy_period("FY25") == "2025-12-31"
        assert notes.header_columns(["Particulars", "2025 2024"], 1)[0] == [("FY25", "2025-12-31"), ("FY24", "2024-12-31")]
        assert notes._category_columns(["Parent Subsidiaries", "2025 2024"], 0, lex)[1] == [
            ("FY25", "2025-12-31"), ("FY24", "2024-12-31")
        ]
        rpt_page = (
            "Notes to the Consolidated Financial Statements\n"
            "Related party disclosures\n"
            "(In Rs. million)\n"
            "Particulars\n"
            "2025 2024\n"
            "Remuneration to KMP\n"
            "Salaries and other employee benefits\n"
            "120 110\n"
            "Directors sitting fees\n"
            "15 12\n"
            "Holding Company Services\n"
            "Parent Management fees\n"
            "50 40"
        )
        out = notes.related_party_rows("RSYSTEMS", "INE411H01032", "R Systems", dec_ar, 1, rpt_page, lex)
        assert out
        assert {(r["fiscal_year"], r["period_end"]) for r in out} == {("FY25", "2025-12-31"), ("FY24", "2024-12-31")}


def test_fiscal_quarter_end_and_half_end():
    assert fiscal.quarter_end("Q1FY26") == "2025-06-30"
    assert fiscal.quarter_end("Q4FY26") == "2026-03-31"
    assert fiscal.half_end("H1FY26") == "2025-09-30"
    assert fiscal.half_end("H2FY26") == "2026-03-31"
    assert fiscal.half_end("Q1FY26") is None

    with fiscal.use(12):
        assert fiscal.quarter_end("Q1FY26") == "2026-03-31"
        assert fiscal.quarter_end("Q4FY25") == "2025-12-31"
        assert fiscal.half_end("H1FY26") == "2026-06-30"
        assert fiscal.half_end("H2FY25") == "2025-12-31"


def test_row_checks_under_fy_end_12(tmp_path):
    # March default unchanged
    for lbl, expected in (
        ("Q1FY26", "2025-06-30"), ("Q2FY26", "2025-09-30"), ("Q3FY26", "2025-12-31"),
        ("Q4FY26", "2026-03-31"), ("H1FY26", "2025-09-30"), ("H2FY26", "2026-03-31"),
        ("9MFY26", "2025-12-31"), ("FY26", "2026-03-31"),
    ):
        assert row_checks.period_end(lbl) == expected
    assert row_checks.fiscal_ending_year("2026-05-01") == 2027
    assert row_checks.fiscal_ending_year("2026-02-01") == 2026

    with fiscal.use(12):
        for lbl, expected in (
            ("Q1FY26", "2026-03-31"), ("Q2FY26", "2026-06-30"), ("Q3FY26", "2026-09-30"),
            ("Q4FY26", "2026-12-31"), ("H1FY26", "2026-06-30"), ("H2FY26", "2026-12-31"),
            ("9MFY26", "2026-09-30"), ("FY26", "2026-12-31"),
        ):
            assert row_checks.period_end(lbl) == expected
        assert row_checks.fiscal_ending_year("2026-05-01") == 2026
        assert row_checks.fiscal_ending_year("2026-02-01") == 2026
        assert row_checks.fiscal_ending_year("1999-12-01") == 1999

    db = tmp_path / "rc.db"
    out_db = tmp_path / "rc_out.db"
    con = sqlite3.connect(db)
    schema.create(con, ["company", "doc", "doc_page", "guidance"])
    con.executescript(kpi.SCHEMA)
    con.execute("INSERT INTO company (symbol, isin, name) VALUES ('RSYSTEMS', 'INE411H01032', 'R Systems')")
    con.execute("INSERT INTO doc (doc_key, symbol, doc_type, known_at) "
                "VALUES ('ar1', 'RSYSTEMS', 'annual_report', '2026-04-01')")
    for pg in (1, 2, 3):
        con.execute("INSERT INTO doc_page (doc_key, symbol, page, text) "
                    "VALUES ('ar1', 'RSYSTEMS', ?, 'For the year ended December 31, 2025')", (pg,))
    g_quote = "We expect Q2FY26 EBITDA margin of 18%."
    k_quote = "EBITDA margin stood at 17% for Q1FY26."
    con.execute("INSERT INTO doc (doc_key, symbol, doc_type, known_at) "
                "VALUES ('tr1', 'RSYSTEMS', 'transcript', '2026-05-07T18:00:00')")
    con.execute("INSERT INTO doc_page (doc_key, symbol, page, text) VALUES ('tr1', 'RSYSTEMS', 1, ?)",
                (f"{g_quote} {k_quote}",))
    con.execute(
        "INSERT INTO guidance (id, symbol, metric, target_period, low, high, unit, direction, said_on, doc_key, page, quote, known_at, extractor_rule) "
        "VALUES (1, 'RSYSTEMS', 'ebitda_margin', 'Q2FY26', 18.0, 18.0, 'pct', 'flat', '2026-05-07', 'tr1', 1, ?, '2026-05-07', 'guidance_cue_v1')",
        (g_quote,),
    )
    con.execute(
        "INSERT INTO kpi_series (id, symbol, metric, dimension, period_type, fiscal_period, basis, value, unit, scale, doc_key, page, quote, known_at, extractor_rule) "
        "VALUES (1, 'RSYSTEMS', 'ebitda_margin', 'total', 'Q', 'Q1FY26', 'consolidated', 17.0, 'pct', 1.0, 'tr1', 1, ?, '2026-05-07', 'prose_v1')",
        (k_quote,),
    )
    con.execute(
        "INSERT INTO kpi_series (id, symbol, metric, dimension, period_type, fiscal_period, basis, value, unit, scale, doc_key, page, quote, known_at, extractor_rule) "
        "VALUES (2, 'RSYSTEMS', 'ebitda_margin', 'total', 'Q', 'Q2FY26', 'consolidated', 18.0, 'pct', 1.0, 'tr1', 1, ?, '2026-05-07', 'prose_v1')",
        (g_quote,),
    )
    con.commit()
    con.close()

    prof = tmp_path / "prof.json"
    prof.write_text('{"companies": [{"symbol": "RSYSTEMS", "sector": "it_services"}]}', encoding="utf-8")
    row_checks.run(str(db), str(out_db), profile=str(prof))
    out = sqlite3.connect(out_db)
    try:
        fails = out.execute("SELECT tbl, row_id, check_name FROM row_check_fail").fetchall()
        assert ("guidance", 1, "past_target") not in fails
        assert ("kpi_series", 1, "future_period") not in fails
        assert ("kpi_series", 2, "future_period") in fails
    finally:
        out.close()
