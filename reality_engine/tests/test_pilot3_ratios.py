"""pilot3 ratio_panel: the lender's annual opex / net total income row (T-049, 4 Nov 2026).

Fixture only: the rows are Bajaj Finance's FY26 consolidated XBRL annual lines, in an in-memory sqlite built
from the real DDL. No store, no network, no model.
"""
from __future__ import annotations

import json
import sqlite3

from reality_engine.pilot3 import ratios, schema

ISIN = "INE296A01024"
FY26 = {  # xbrl_reported, consolidated, INR
    "employee_cost": 89_785_300_000.0,
    "fee_commission_expense": 36_581_000_000.0,
    "other_expenses": 41_306_800_000.0,
    "depreciation": 10_089_800_000.0,
    "total_income": 819_895_000_000.0,
    "finance_cost": 286_659_500_000.0,
}
ROW = ("BAJFINANCE", ISIN, "FY26", "2026-03-31", "consolidated", "PL", None, None, None, "inr", 1.0, None, None,
       None, "results_xbrl.db", "facts", "x", "2026-05-22T18:50:00", "t", 1, 0, "xbrl_reported", "FY")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    conn.execute("INSERT INTO company VALUES ('BAJFINANCE',?,NULL,NULL,'t','500034','Bajaj Finance Limited')", (ISIN,))
    conn.executemany("INSERT INTO fin_annual_line VALUES (" + ",".join("?" * 23) + ")", [
        (*ROW[:6], item, item, value, *ROW[9:]) for item, value in FY26.items()])
    conn.commit()
    return conn


def test_bajfinance_fy26_opex_to_net_total_income_is_annual_and_shows_inputs():
    conn = _conn()
    ratios.build_ratios(conn)
    row = conn.execute(
        "SELECT basis, value, unit, formula_id, input_refs FROM ratio_panel WHERE symbol='BAJFINANCE' "
        "AND metric='opex_to_net_total_income_pct' AND fiscal_period='FY26'").fetchone()
    assert row is not None, "no FY26 opex/NTI row in ratio_panel"
    basis, value, unit, formula_id, refs = row
    assert (basis, unit) == ("consolidated", "pct")
    # opex 17,776.29 cr over NTI 53,323.55 cr (total income - finance cost)
    assert round(value, 2) == 33.34
    expression = conn.execute("SELECT expression FROM formula WHERE formula_id=?", (formula_id,)).fetchone()[0]
    assert "total_income - finance_cost" in expression
    inputs = json.loads(refs)
    assert len(inputs) == 6 and all(ref.startswith("fa:BAJFINANCE:FY26:consolidated:") for ref in inputs), inputs


def test_quarterly_only_lines_make_no_annual_row():
    """The row needs all six annual inputs: a company without them gets nothing, never a partial ratio."""
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    conn.execute("INSERT INTO company VALUES ('KEC','I',NULL,NULL,'t','532714','KEC International Limited')")
    ratios.build_ratios(conn)
    assert conn.execute("SELECT COUNT(*) FROM ratio_panel WHERE metric='opex_to_net_total_income_pct'").fetchone()[0] == 0


# --- T-056 loop 2: compute-only history, bank and insurer lines, quarter-labelled half-year ratios -----------------
import pytest  # noqa: E402

from reality_engine.pilot3 import profile, stores  # noqa: E402

SYM, SISIN = "T", "INE000A01010"


def _profile(tmp_path, compute_start: str | None = "2025-01-01", window_start="2026-01-01", lender=False):
    data = {"name": "fixture", "pages_db": str(tmp_path / "p.db"), "raw_root": str(tmp_path), "manifest": str(tmp_path / "m.csv"),
            "out": str(tmp_path / "o.db"), "window_start": window_start,
            "companies": [{"symbol": SYM, "name": "T Ltd", "bse_code": "1", "isins": [SISIN], "lender": lender}]}
    if compute_start:
        data["compute_start"] = compute_start
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return profile.activate(profile.load(path))


def _quarter_rows(conn, rows):
    for period, end, known, items in rows:
        for item, value in items.items():
            conn.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, "
                         "audited, statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, "
                         "source_table, source_rowid, known_at, known_at_source, is_reported) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (SYM, SISIN, end[:7] + "-01", end, period, "consolidated", "A", "P&L", item, item, value, "inr", 1.0,
                          "f", "d", "t", "r", known, "src", 1))


def _four_quarters(conn):
    _quarter_rows(conn, [
        ("Q1FY26", "2025-06-30", "2025-08-01T10:00:00", {"eps_basic": 1.0, "pat": 100.0, "revenue_from_operations": 1000.0}),
        ("Q2FY26", "2025-09-30", "2025-11-01T10:00:00", {"eps_basic": 1.1, "pat": 110.0, "revenue_from_operations": 1100.0}),
        ("Q3FY26", "2025-12-31", "2026-02-01T10:00:00", {"eps_basic": 1.2, "pat": 120.0, "revenue_from_operations": 1200.0}),
        ("Q4FY26", "2026-03-31", "2026-05-01T10:00:00", {"eps_basic": 1.3, "pat": 130.0, "revenue_from_operations": 1300.0})])
    conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','1','T Ltd')", (SYM, SISIN))
    conn.execute("INSERT INTO share_capital VALUES (?,?,'2025-06-30','consolidated',NULL,NULL,100.0,100.0,1.0,'shares',1.0,"
                 "'2025-08-01T10:00:00','s','d','t','r',NULL,NULL)", (SYM, SISIN))
    conn.executemany("INSERT INTO price_delivery VALUES (" + ",".join("?" * 21) + ")",
                     [(SYM, SISIN, "NSE", d, 10, 11, 9, 10.0, 10, 1, 1, 1, 1, 50.0, 1.0, 10.0, d, "x", "d", "t", d)
                      for d in ("2025-09-01", "2026-02-02", "2026-05-02")])
    conn.commit()


def _dump(conn):
    return (conn.execute("SELECT * FROM ratio_panel ORDER BY 1,3,8,7").fetchall(),
            conn.execute("SELECT * FROM valuation_daily ORDER BY 1,3").fetchall())


def test_compute_start_gives_a_trailing_year_but_no_row_before_the_window(tmp_path):
    """Q1 to Q3 FY26 end before the window: they are inputs only, yet a day in the window has its four-quarter EPS."""
    try:
        _profile(tmp_path)
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        _four_quarters(conn)
        stores.apply_window(conn)
        assert conn.execute("SELECT DISTINCT period_end FROM fin_quarter_xbrl ORDER BY 1").fetchall() \
            == [("2026-03-31",)]
        assert conn.execute("SELECT DISTINCT period_end FROM fin_quarter_xbrl_input ORDER BY 1").fetchall() \
            == [("2025-06-30",), ("2025-09-30",), ("2025-12-31",)]
        assert conn.execute("SELECT MIN(date) FROM price_delivery").fetchone()[0] == "2026-02-02"
        ratios.build_ratios(conn)
        row = conn.execute("SELECT trailing_eps, pe FROM valuation_daily WHERE date='2026-05-02'").fetchone()
        assert row[0] == pytest.approx(4.6) and row[1] == pytest.approx(10 / 4.6)
        assert conn.execute("SELECT MIN(date) FROM valuation_daily").fetchone()[0] >= "2026-01-01"
        assert conn.execute("SELECT MIN(period_end) FROM ratio_panel").fetchone()[0] >= "2026-01-01"
        fy = {r[0]: r[1] for r in conn.execute("SELECT metric, value FROM ratio_panel WHERE fiscal_period='FY26'")}
        assert fy["revenue_from_operations"] == pytest.approx(4600.0)       # the two input quarters are in the year
        assert conn.execute("SELECT COUNT(*) FROM sqlite_temp_master WHERE type='view'").fetchone()[0] == 0
        first = _dump(conn)
        ratios.build_ratios(conn)                                           # --part ratios again: identical
        assert _dump(conn) == first
    finally:
        profile.activate(None)


def test_without_compute_start_nothing_is_held_back(tmp_path):
    try:
        _profile(tmp_path, compute_start=None)
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        _four_quarters(conn)
        stores.apply_window(conn)
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_input'").fetchall() == []
        ratios.build_ratios(conn)
        assert conn.execute("SELECT trailing_eps FROM valuation_daily WHERE date='2026-05-02'").fetchone()[0] is None
    finally:
        profile.activate(None)


def test_half_year_point_in_time_ratio_is_also_written_under_the_quarter_label():
    out = [(SYM, SISIN, "H1FY27", "H1", "2026-04-01", "2026-09-30", "consolidated", "roe", 12.5, "pct", 1.0, "F_ROE", "[]",
            "2026-11-02", "k", 1),
           (SYM, SISIN, "H1FY27", "H1", "2026-04-01", "2026-09-30", "consolidated", "nim_pct", 3.1, "pct", 1.0, "F_NIM", "[]",
            "2026-11-02", "k", 1)]
    ratios._quarter_labelled(out, 0)
    labelled = [r for r in out if r[3] == "Q"]
    assert len(labelled) == 1                                              # the NIM is a period measure: no copy
    assert labelled[0][2:9] == ("Q2FY27", "Q", "2026-07-01", "2026-09-30", "consolidated", "roe", 12.5)


def test_bank_cost_to_income_and_one_payout_row_per_year(tmp_path):
    _profile(tmp_path)
    try:
        _bank_cost_to_income_and_payout()
    finally:
        profile.activate(None)


def _bank_cost_to_income_and_payout():
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','1','T Ltd')", (SYM, SISIN))
    _quarter_rows(conn, [("Q2FY27", "2026-09-30", "2026-10-17T10:00:00",
                          {"operating_expenses": 400.0, "net_interest_income": 700.0, "other_income": 300.0})])
    out: list = []
    ratios._panel(conn, SYM, SISIN, out)
    row = [r for r in out if r[7] == "cost_to_income"]
    assert len(row) == 1 and row[0][8] == pytest.approx(40.0) and row[0][11] == "F_COST_INCOME"
    # two annual-report figures for one year and the corporate-action sum: the corporate-action sum is the one row
    eps = (SYM, SISIN, "FY26", "FY", "2025-04-01", "2026-03-31", "consolidated", "eps_basic_fy", 50.0, "inr_per_share", 1.0,
           "F_EPS_FY", "[]", "2026-05-01", "k", 1)
    out = [eps]
    for basis, value, table in (("consolidated", 22.0, "ar_facts"), ("not_stated", 41.0, "corporate_actions"),
                                ("consolidated", 22.0, "ar_facts")):
        conn.execute("INSERT INTO fin_annual_line VALUES (?,?,'FY26','2026-03-31',?,'P&L','dividend_per_share','c',?,"
                     "'inr_per_share',1,'d',NULL,'q','db',?,'r','2026-05-02','k',1,0,'reported','FY')",
                     (SYM, SISIN, basis, value, table))
    ratios._payout_bvps(conn, SYM, SISIN, out)
    payout = sorted((r[6], round(r[8], 6)) for r in out if r[7] == "dividend_payout_pct")
    assert payout == [("consolidated", 82.0)]          # 41 / 50, not the report's 22 and not two rows


def test_annual_eps_is_restated_across_a_bonus_only_under_a_profile(tmp_path):
    """HDFC Bank-like year: Q1 was filed before a 1:1 bonus (EPS 24), the other three after (12 each)."""
    def build():
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','1','T Ltd')", (SYM, SISIN))
        _quarter_rows(conn, [("Q1FY26", "2025-06-30", "2025-07-19T10:00:00", {"eps_basic": 24.0}),
                             ("Q2FY26", "2025-09-30", "2025-10-18T10:00:00", {"eps_basic": 12.0}),
                             ("Q3FY26", "2025-12-31", "2026-01-17T10:00:00", {"eps_basic": 12.0}),
                             ("Q4FY26", "2026-03-31", "2026-04-18T10:00:00", {"eps_basic": 12.0})])
        conn.executemany("INSERT INTO price_delivery VALUES (" + ",".join("?" * 21) + ")",
                         [(SYM, SISIN, "NSE", d, 10, 11, 9, 10.0, 10, 1, 1, 1, 1, 50.0, f, 10.0, d, "x", "d", "t", d)
                          for d, f in (("2025-07-01", 0.5), ("2025-10-01", 1.0), ("2026-04-01", 1.0))])
        out: list = []
        ratios._panel(conn, SYM, SISIN, out)
        return [r[8] for r in out if r[7] == "eps_basic_fy"]

    assert build() == [60.0]                    # no profile: the quarters are summed as filed, as before
    try:
        _profile(tmp_path)
        assert build() == [pytest.approx(48.0)]  # 24 * 0.5 / 1.0 + 12 + 12 + 12
    finally:
        profile.activate(None)


# --- T-073: stock-in-trade cost lines, exact share count, TTM from the annual line, point in time --------------
def test_gross_margin_uses_stock_in_trade_and_inventory_change(tmp_path):
    """HINDUNILVR Q2 FY27: revenue 18,226 cr, materials 6,408 cr, stock-in-trade purchases 3,654 cr and an
    inventory change of -507 cr -> 47.58% gross margin."""
    try:
        _profile(tmp_path, compute_start=None)
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','1','T Ltd')", (SYM, SISIN))
        _quarter_rows(conn, [("Q2FY27", "2026-09-30", "2026-10-28T10:00:00",
                              {"revenue_from_operations": 182_260_000_000.0,
                               "cost_of_materials": 64_080_000_000.0,
                               "purchases_of_stock_in_trade": 36_540_000_000.0,
                               "changes_in_inventories": -5_070_000_000.0})])
        out: list = []
        ratios._panel(conn, SYM, SISIN, out)
        gm = [r for r in out if r[7] == "gross_margin_pct" and r[3] == "Q"]
        assert gm and gm[0][8] == pytest.approx(47.58, abs=0.02)
        assert gm[0][11] == "F_GROSS_M" and len(json.loads(gm[0][12])) == 4
    finally:
        profile.activate(None)


def test_the_exact_pattern_share_total_wins_over_rounded_paid_up_capital():
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    for as_of, shares, known, table in (
            ("2026-09-30", 2_220_000_000.0, "2026-08-07T10:00:00", "quarterly"),
            ("2026-09-30", 2_247_226_523.0, "2026-10-19T10:00:00", "shp_category"),
            ("2025-12-31", 2_220_000_000.0, "2026-01-20T10:00:00", "quarterly")):
        conn.execute("INSERT INTO share_capital VALUES (?,?,?,'consolidated',NULL,NULL,?,NULL,NULL,'shares',1.0,?,"
                     "'s','d',?,'r',NULL,NULL)", (SYM, SISIN, as_of, shares, known, table))
    sh = ratios._share_count(conn, SYM, "consolidated", "2026-10-20")
    assert sh is not None and sh[0] == 2_247_226_523.0
    # before the pattern was filed the rounded paid-up row is the only fallback
    fallback = ratios._share_count(conn, SYM, "consolidated", "2026-10-01")
    assert fallback is not None and fallback[0] == 2_220_000_000.0


def _valuation_fixture(conn, share_known="2026-10-20T10:00:00", prices=("2026-10-01", "2026-10-21")):
    conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','1','T Ltd')", (SYM, SISIN))
    _quarter_rows(conn, [("Q2FY27", "2026-09-30", "2026-10-23T10:00:00", {"eps_basic": 5.0, "pat": 500.0})])
    conn.execute("INSERT INTO share_capital VALUES (?,?,'2026-09-30','consolidated',NULL,NULL,100.0,100.0,1.0,"
                 "'shares',1.0,?,'s','d','shp_category','r',NULL,NULL)", (SYM, SISIN, share_known))
    conn.executemany("INSERT INTO price_delivery VALUES (" + ",".join("?" * 21) + ")",
                     [(SYM, SISIN, "NSE", d, 10, 11, 9, 10.0, 10, 1, 1, 1, 1, 50.0, 1.0, 10.0, d, "x", "d", "t", d)
                      for d in prices])
    conn.commit()


def test_no_valuation_session_uses_a_filing_later_than_itself(tmp_path):
    try:
        _profile(tmp_path, compute_start=None)
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        _valuation_fixture(conn)
        ratios.build_ratios(conn)
        rows = conn.execute("SELECT date, known_at, shares_outstanding FROM valuation_daily ORDER BY date").fetchall()
        assert rows and all(k[:10] <= d for d, k, _s in rows)
        assert [r[0] for r in rows] == ["2026-10-21"]      # 1 Oct: the count was not filed yet
        assert rows[0][2] == 100.0
    finally:
        profile.activate(None)


def test_an_undated_share_count_is_never_used(tmp_path):
    """q12 build 8 Nov: a share_capital row with known_at NULL crashed the valuation pass; it must be skipped."""
    try:
        _profile(tmp_path, compute_start=None)
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        _valuation_fixture(conn, share_known=None)
        ratios.build_ratios(conn)
        assert conn.execute("SELECT COUNT(*) FROM valuation_daily").fetchone()[0] == 0
    finally:
        profile.activate(None)


def test_ttm_uses_the_annual_line_when_the_filing_prints_no_last_fy(tmp_path):
    """The Oct filing prints the ytd and prior-ytd EPS columns only; the last full year comes from its own annual
    line (FY26 71.58, known April) -> TTM 75.62, not a value from a later filing (T-073)."""
    try:
        _profile(tmp_path, compute_start=None)
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        _valuation_fixture(conn, prices=("2026-10-24",))
        conn.execute("INSERT INTO fin_annual_line VALUES (?,?,'FY26','2026-03-31','consolidated','P&L','eps_basic','c',"
                     "71.58,'inr_per_share',1,'d',NULL,'q','db','t','r','2026-04-23T10:00:00','k',1,0,"
                     "'xbrl_reported','FY')", (SYM, SISIN))
        for role, end, value in (("ytd", "2026-09-30", 38.51), ("prior_ytd", "2025-09-30", 34.47)):
            conn.execute("INSERT INTO fin_quarter_printed (symbol, isin, period_start, period_end, fiscal_period, "
                         "period_type, column_role, basis, statement, line_item, caption, value, unit, scale, raw_token, "
                         "quote, doc_key, page, known_at, known_at_source, check_status, check_detail, is_reported) "
                         "VALUES (?,?,'2026-04-01',?,'H1FY27','ytd',?,'consolidated','P&L','eps_basic','Basic',?,"
                         "'inr_per_share',1.0,'x','q','doc1',1,'2026-10-23T10:00:00','doc.known_at','sum_ok',NULL,1)",
                         (SYM, SISIN, end, role, value))
        conn.commit()
        ratios.build_ratios(conn)
        row = conn.execute("SELECT trailing_eps, pe, input_refs FROM valuation_daily WHERE date='2026-10-24'").fetchone()
        assert row is not None
        assert row[0] == pytest.approx(71.58 + 38.51 - 34.47)
        assert row[1] == pytest.approx(10.0 / row[0])
        assert json.loads(row[2])["ttm"] == "last_fy(annual)+ytd-prior_ytd"
    finally:
        profile.activate(None)


def test_ev_uses_the_latest_filed_balance_sheet_half_year(tmp_path):
    """A half-year net debt filed in February makes EV/EBITDA form before the next annual report, and
    `input_refs.net_debt` states which balance sheet was used (T-073)."""
    try:
        _profile(tmp_path, compute_start=None, window_start="2026-01-01")
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','1','T Ltd')", (SYM, SISIN))
        _quarter_rows(conn, [
            ("Q1FY26", "2025-06-30", "2025-08-01T10:00:00", {"eps_basic": 1.0, "ebitda": 100.0}),
            ("Q2FY26", "2025-09-30", "2025-11-01T10:00:00", {"eps_basic": 1.0, "ebitda": 100.0}),
            ("Q3FY26", "2025-12-31", "2026-01-10T10:00:00", {"eps_basic": 1.0, "ebitda": 100.0}),
            ("Q4FY26", "2026-03-31", "2026-01-20T10:00:00", {"eps_basic": 1.0, "ebitda": 100.0})])
        conn.execute("INSERT INTO share_capital VALUES (?,?,'2026-01-01','consolidated',NULL,NULL,100.0,100.0,1.0,"
                     "'shares',1.0,'2026-01-05T10:00:00','s','d','shp_category','r',NULL,NULL)", (SYM, SISIN))
        conn.execute("INSERT INTO fin_annual_line VALUES (?,?,'H1FY26','2025-09-30','consolidated','BS','net_debt','c',"
                     "400.0,'inr',1.0,'d',NULL,'q','db','t','r','2026-02-01T10:00:00','k',1,1,'xbrl_derived','H1')",
                     (SYM, SISIN))
        conn.executemany("INSERT INTO price_delivery VALUES (" + ",".join("?" * 21) + ")",
                         [(SYM, SISIN, "NSE", d, 10, 11, 9, 10.0, 10, 1, 1, 1, 1, 50.0, 1.0, 10.0, d, "x", "d", "t", d)
                          for d in ("2026-02-02",)])
        conn.commit()
        ratios.build_ratios(conn)
        row = conn.execute("SELECT trailing_ebitda, net_debt, ev_ebitda, input_refs FROM valuation_daily "
                           "WHERE date='2026-02-02'").fetchone()
        assert row is not None
        assert row[0] == pytest.approx(400.0) and row[1] == pytest.approx(400.0)
        assert row[2] == pytest.approx((10.0 * 100 + 400.0) / 400.0)
        assert json.loads(row[3])["net_debt"] == "bs 2025-09-30 H1 known 2026-02-01"
    finally:
        profile.activate(None)
