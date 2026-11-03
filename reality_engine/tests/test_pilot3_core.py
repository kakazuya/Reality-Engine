"""T-049 part A: pilot3 core database (registry, pages, stores, ratios, queries, oracle).

Unit tests use tiny synthetic tables; the integration test builds the real database from the read-only
stores and sandboxes and is skipped when they are not on this machine."""
from __future__ import annotations

import sqlite3

import pytest

from reality_engine import pilot3
from reality_engine.pilot3 import oracle, queries, ratios, schema, stores


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    return conn


def test_fiscal_period_follows_the_indian_year():
    assert stores.fiscal_period("2026-06-30") == "Q1FY27"
    assert stores.fiscal_period("2026-03-31") == "Q4FY26"
    assert stores.fiscal_period("2025-12-31") == "Q3FY26"
    assert stores.fiscal_period("2025-05-31") is None


def test_lexicon_matches_statement_captions_only():
    assert stores.lexicon_item("Profit for the year") == ("pat", "P&L")
    assert stores.lexicon_item("Consolidated EBITDA") == ("ebitda", "P&L")
    assert stores.lexicon_item("Net cash flow from operating activities") == ("cash_flow_from_operations", "CF")
    assert stores.lexicon_item("Five branches: total revenue from operations for year ended 31 March 2026") is None
    assert stores.lexicon_item("EBITDA growth") is None


def test_unit_scales():
    assert stores._unit("Rs crore") == ("inr_crore", 1e7)
    assert stores._unit("%") == ("pct", 1.0)
    assert oracle.scale_of("INR_crore") == 1e7 and oracle.scale_of("million") == 1e6 and oracle.scale_of("inr") == 1.0


def _shp_xml(fraction: bool) -> bytes:
    pct = (lambda x: x / 100) if fraction else (lambda x: x)
    ns = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
          'xmlns:s="http://example.com/shp"')

    def ctx(name):
        return (f'<xbrli:context id="{name}I"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>'
                f'<xbrli:period><xbrli:instant>2025-06-30</xbrli:instant></xbrli:period><xbrli:scenario>'
                f'<xbrldi:explicitMember dimension="s:CategoryOfShareholdersAxis">s:{name}Member</xbrldi:explicitMember>'
                f'</xbrli:scenario></xbrli:context>')

    def facts(name, shares, p):
        return (f'<s:NumberOfShares contextRef="{name}I">{shares}</s:NumberOfShares>'
                f'<s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="{name}I">{pct(p)}'
                f'</s:ShareholdingAsAPercentageOfTotalNumberOfShares>')

    body = "".join(ctx(n) for n in ("ShareholdingOfPromoterAndPromoterGroup", "PublicShareholding", "MutualFundsOrUti"))
    body += "<s:ISIN>INE000A01010</s:ISIN>"
    body += facts("ShareholdingOfPromoterAndPromoterGroup", 600, 60.0) + facts("PublicShareholding", 400, 40.0)
    body += facts("MutualFundsOrUti", 100, 10.0)
    return f"<xbrli:xbrl {ns}>{body}</xbrli:xbrl>".encode()


@pytest.mark.parametrize("fraction", [False, True])
def test_shp_xbrl_percent_is_normalised_to_percent(fraction):
    parsed = stores.parse_shp_xbrl(_shp_xml(fraction))
    assert parsed["head"]["ISIN"] == "INE000A01010"
    f = parsed["facts"][("MutualFundsOrUti", "2025-06-30")]
    assert f["ShareholdingAsAPercentageOfTotalNumberOfShares"] == pytest.approx(10.0)
    assert f["NumberOfShares"] == 100


def test_judge_scales_and_rounding():
    cr = [(235055400000.0, "inr", "x")]
    assert oracle.judge(23505.54, "inr_cr", cr)[0] == "reproduced"
    assert oracle.judge(23506, "inr_cr", cr)[0] == "reproduced"
    assert oracle.judge(24000, "inr_cr", cr)[0] == "mismatch"
    assert oracle.judge(6.3, "pct", [(6.2629, "pct", "x")])[0] == "reproduced"  # oracle rounded to one decimal
    assert oracle.judge(6.5, "pct", [(5.9924, "pct", "x")])[0] == "mismatch"
    assert oracle.judge(1.0, "pct", [])[0] == "missing"


def test_period_parsing_and_classification():
    assert oracle.parse_period("Q1 FY27 (30-Jun-26)") == ("Q", "Q1FY27")
    assert oracle.parse_period("FY2026") == ("FY", "FY26")
    assert oracle.parse_period("28 Mar 2025 (last session)") == ("D", "2025-03-28")
    assert oracle.parse_period("Mar 2025 (quarter end)") == ("D", "2025-03-31")
    assert oracle.to_date(("Q", "Q1FY27")) == "2026-06-30" and oracle.to_date(("Q", "Q4FY26")) == "2026-03-31"
    assert oracle.classify("closing price", "inr") == ("px", "close")
    assert oracle.classify("promoter and promoter group holding", "pct")[0] == "shp"
    assert oracle.classify("consolidated AUM", "inr_cr")[0] == "other"


def _seed(conn: sqlite3.Connection) -> None:
    rows = []
    for period, end, known, rev, pbt, fin, dep, oth, eps in (
            ("Q1FY26", "2025-06-30", "2025-08-01T10:00:00", 1000.0, 100.0, 20.0, 30.0, 5.0, 1.0),
            ("Q2FY26", "2025-09-30", "2025-11-01T10:00:00", 1100.0, 110.0, 20.0, 30.0, 5.0, 1.1),
            ("Q3FY26", "2025-12-31", "2026-02-01T10:00:00", 1200.0, 120.0, 20.0, 30.0, 5.0, 1.2),
            ("Q4FY26", "2026-03-31", "2026-05-01T10:00:00", 1300.0, 130.0, 20.0, 30.0, 5.0, 1.3)):
        for item, value in (("revenue_from_operations", rev), ("pbt_before_exceptional", pbt), ("finance_cost", fin),
                            ("depreciation", dep), ("other_income", oth), ("pat", pbt * 0.7), ("eps_basic", eps)):
            rows.append(("T", "INE000A01010", end[:7] + "-01", end, period, "consolidated", "A", "P&L", item, item, value,
                         "inr", 1.0, "f", "d", "t", "r", known, "src", 1))
    conn.executemany("INSERT INTO fin_quarter_xbrl VALUES (" + ",".join("?" * 20) + ")", rows)
    conn.execute("INSERT INTO company VALUES ('T','INE000A01010',NULL,NULL,'t','1','Test')")
    conn.execute("INSERT INTO share_capital VALUES ('T','INE000A01010','2025-06-30','consolidated',NULL,NULL,"
                 "100.0,100.0,1.0,'shares',1.0,'2025-08-01T10:00:00','s','d','t','r',NULL,NULL)")
    prices = [("T", "INE000A01010", "NSE", d, 10, 11, 9, 10.0, 10, 1, 1, 1, 1, 50.0, 1.0, 10.0, d, "x", "d", "t", d)
              for d in ("2025-09-01", "2026-02-02", "2026-05-02")]
    conn.executemany("INSERT INTO price_delivery VALUES (" + ",".join("?" * 21) + ")", prices)


def test_ratio_panel_formulas_and_point_in_time():
    conn = _conn()
    _seed(conn)
    out: list = []
    ratios._panel(conn, "T", "INE000A01010", out)
    by = {(r[2], r[7]): r for r in out}
    assert by[("Q1FY26", "ebitda")][8] == pytest.approx(100 + 20 + 30 - 5)          # excludes other income
    assert by[("Q1FY26", "ebitda_margin_pct")][8] == pytest.approx(100 * 145 / 1000)
    assert by[("FY26", "revenue_from_operations")][8] == pytest.approx(4600.0)
    assert by[("FY26", "eps_basic_fy")][8] == pytest.approx(4.6)
    assert by[("FY26", "revenue_from_operations")][13] == "2026-05-01T10:00:00"     # known_at = latest input
    assert by[("Q1FY26", "ebitda")][11] == "F_EBITDA"


def test_valuation_never_uses_a_filing_that_is_not_out_yet():
    conn = _conn()
    _seed(conn)
    assert ratios._valuation(conn, "T", "INE000A01010") == 3
    rows = {r[0]: r for r in conn.execute("SELECT date, trailing_eps, pe, known_at FROM valuation_daily")}
    assert rows["2025-09-01"][1] is None            # only Q1 filed: no four-quarter EPS yet
    assert rows["2026-02-02"][1] is None            # Q4 not filed on 2 Feb 2026
    assert rows["2026-05-02"][1] == pytest.approx(4.6) and rows["2026-05-02"][2] == pytest.approx(10 / 4.6)
    assert rows["2026-05-02"][3] >= "2026-05-01"


def test_queries_respect_as_of():
    conn = _conn()
    _seed(conn)
    assert queries.fin_quarter(conn, "T", "Q4FY26", "pat", "consolidated", "2026-04-30") == []
    assert queries.fin_quarter(conn, "T", "Q4FY26", "pat", "consolidated", "2026-05-01")[0][0] == pytest.approx(91.0)
    assert queries.px_on(conn, "T", "2026-02-03", "close")[0][0] == 10.0
    assert queries.shares(conn, "T", "2026-03-31")[0][0] == 100.0


def _real_stores_present() -> bool:
    return all(path.is_file() for path in pilot3.SANDBOX_DB.values()) and (pilot3.data_root() / "ar_facts.db").is_file()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from reality_engine.pilot3 import build

    db = tmp_path_factory.mktemp("pilot3") / "pilot3.db"
    build.build(db, "all")
    return db


@pytest.mark.skipif(not _real_stores_present(), reason="read-only stores / sandboxes not on this machine")
def test_integration_build_counts_and_oracle(built):
    conn = sqlite3.connect(built)
    quarters = dict(conn.execute("SELECT symbol, COUNT(DISTINCT quarter_end) FROM shp_category GROUP BY symbol"))
    assert quarters["BAJFINANCE"] >= 23 and quarters["HINDALCO"] >= 20 and quarters["KEC"] >= 22
    for table in ("doc_page", "fin_quarter_xbrl", "price_delivery", "ratio_panel", "valuation_daily", "share_capital"):
        got = dict(conn.execute(f"SELECT symbol, COUNT(*) FROM {table} GROUP BY symbol"))
        assert set(got) == set(pilot3.SYMBOLS), table
    # no row may be known before its own period ended
    assert conn.execute("SELECT COUNT(*) FROM fin_quarter_xbrl WHERE substr(known_at,1,10) < period_end").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM doc_page_fts WHERE doc_page_fts MATCH 'revenue'").fetchone()[0] > 0
    conn.close()
    report = oracle.run(built)
    assert report["price_delivery"]["reproduced"] == report["price_delivery"]["questions"]
    assert report["valuation_daily"]["reproduced"] == report["valuation_daily"]["questions"]
    assert all(r["reproduced"] > 0 for r in report.values())


# --- part D: statements, company-stated reader, balance-sheet ratios --------------------------------
from reality_engine.pilot3 import statements  # noqa: E402


def test_lexicon_company_stated_captions_and_year_suffix():
    assert stores.lexicon_item("Net Working Capital days FY26") == ("net_working_capital_days", "BS")
    assert stores.lexicon_item("Net debt including acceptances at year end")[0] == "net_debt_incl_acceptances"
    assert stores.lexicon_item("Debtors Turnover Ratio (days) - worsened YoY")[0] == "receivable_days"
    assert stores.lexicon_item("Revenue FY26") is None  # the year suffix is only stripped for company-stated items
    assert "net_debt_incl_acceptances" in stores.COMPANY_STATED and "net_worth" not in stores.COMPANY_STATED


DECK_PAGE = ("Hindalco Q4 FY26 - Earnings Presentation\n(` Crore)\nParticulars\nQ4 FY25\nQ3 FY26\nQ4 FY26\nChange \nYoY %\n"
             "QoQ \nChange %\nFY25\nFY26\nChange \nYoY %\nEBITDA\n10,296\n \n8,543\n \n11,197\n \n9%\n31%\n35,496\n \n38,097\n \n7%\n")


def test_table_reader_maps_columns_to_period_headers_and_ignores_percent_columns():
    rows = {(r[1], r[2]): r[3] for r in statements.table_rows(DECK_PAGE) if r[0] == "ebitda"}
    assert rows[("FY", "FY26")] == 38097.0 and rows[("Q", "Q4FY25")] == 10296.0 and len(rows) == 5


def test_table_reader_skips_rows_whose_column_count_does_not_match():
    page = DECK_PAGE.replace("38,097\n \n", "")
    assert [r for r in statements.table_rows(page) if r[0] == "ebitda"] == []


def test_sentence_reader_takes_the_value_period_not_the_comparison_period():
    text = "EBITDA margins have increased by 70 bps to 6.5% from 5.8% in Q1 FY24"
    rows = statements.sentence_rows(text, ("Q", "Q1FY25"))
    assert rows[0][:4] == ("ebitda_margin_pct", "Q", "Q1FY25", 6.5)
    call = "On the debt front, our net debt, including acceptances is at INR 6,722 crores, marginally lower"
    assert statements.sentence_rows(call, ("Q", "Q4FY26"))[0][:5] == ("net_debt_incl_acceptances", "Q", "Q4FY26", 6722.0, "inr_crore")


def test_ar_statement_reader_handles_wrapped_labels_and_note_columns():
    page = ("(` Crore)\nTotal assets\n347,795\n265,991\nB. CASH FLOW FROM INVESTING ACTIVITIES\nPayments to acquire Property Plant and Equipment, "
            "Intangible Assets \n \nand Investment Property\n(7,352)\n(6,007)\nTotal equity\n12\n136,595\n123,721\n")
    got = {r[0]: r[2:4] for r in statements.ar_statement_rows(page)}
    assert got["total_assets"] == (347795.0, 265991.0) and got["total_equity"] == (136595.0, 123721.0)
    assert got["capex_payments"] == (-7352.0, -6007.0)


def test_dividend_year_assignment():
    from datetime import date

    assert statements._dividend_fy(date(2026, 7, 10), "final") == "FY26"
    assert statements._dividend_fy(date(2025, 11, 14), "interim") == "FY26"
    assert statements._dividend_fy(date(2026, 2, 14), "interim") == "FY26"


def test_plausibility_gate_drops_segment_rows(tmp_path):
    conn = _conn()
    conn.execute("INSERT INTO fin_quarter_xbrl VALUES ('KEC','I','2025-04-01','2025-06-30','Q1FY26','consolidated','a','P&L',"
                 "'pbt_before_exceptional','x',100.0,'inr',1,'f','d','t','r','2025-07-01','k',1)")
    for item, value in (("finance_cost", 20.0), ("depreciation", 10.0), ("other_income", 0.0), ("revenue_from_operations", 1000.0)):
        conn.execute("INSERT INTO fin_quarter_xbrl VALUES ('KEC','I','2025-04-01','2025-06-30','Q1FY26','consolidated','a','P&L',?,"
                     "'x',?,'inr',1,'f','d','t','r','2025-07-01','k',1)", (item, value))
    # EBITDA 130 rupees (pbt 100 + fin 20 + dep 10): 1.3e-5 crore is "within 25%" of 1.3e-5 crore, 48% margin is not
    assert statements._plausible(conn, "KEC", "ebitda", "Q1FY26", 130.0 / 1e7, "inr_crore")
    assert not statements._plausible(conn, "KEC", "ebitda", "Q1FY26", 300.0 / 1e7, "inr_crore")
    assert not statements._plausible(conn, "KEC", "ebitda_margin_pct", "Q1FY26", 48.0, "pct")
    assert statements._plausible(conn, "KEC", "ebitda_margin_pct", "Q1FY26", 13.0, "pct")
    assert not statements._plausible(conn, "BAJFINANCE", "ebitda", "Q1FY26", 1.0, "inr_crore")


def test_balance_ratios_from_seeded_sheet():
    conn = _conn()
    _seed(conn)
    schema.create(conn, ("fin_annual_line",))
    rows = [("equity_owners", "BS", 6000.0), ("net_worth", "BS", 6000.0), ("total_borrowings", "BS", 3000.0),
            ("net_debt", "BS", 2500.0), ("capital_employed", "BS", 9000.0), ("trade_receivables", "BS", 365.0),
            ("inventories", "BS", 0.0), ("trade_payables_current", "BS", 0.0), ("total_assets", "BS", 12000.0)]
    for item, stmt, value in rows:
        conn.execute("INSERT INTO fin_annual_line VALUES ('KEC','I','FY26','2026-03-31','consolidated',?,?,'c',?,'inr',1,'f',NULL,'q',"
                     "'d','t','r','2026-05-16','k',1,1,'xbrl_derived','FY')", (stmt, item, value))
    out: list = []
    ratios._balance_ratios(conn, "KEC", "I", out)
    metrics = {r[7]: r[8] for r in out}
    assert metrics["debt_to_equity"] == pytest.approx(0.5)
    assert "receivable_days" not in metrics or metrics["receivable_days"] >= 0  # needs four quarters of revenue


@pytest.mark.skipif(not _real_stores_present(), reason="read-only stores / sandboxes not on this machine")
def test_integration_part_d_sources_and_definitions(built):
    conn = sqlite3.connect(built)
    defs = dict(conn.execute("SELECT definition, COUNT(*) FROM fin_annual_line GROUP BY definition"))
    assert {"reported", "xbrl_reported", "xbrl_derived", "company_stated"} <= set(defs)
    # every new number has a known_at and a source: XBRL file + facts rowid, or doc + page + a quote on that page
    assert conn.execute("SELECT COUNT(*) FROM fin_annual_line WHERE known_at IS NULL AND definition!='reported'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM fin_annual_line WHERE definition LIKE 'xbrl%' AND (doc_key IS NULL OR source_rowid IS NULL)"
                        ).fetchone()[0] == 0
    stated = conn.execute("SELECT doc_key, page, quote FROM fin_annual_line WHERE definition='company_stated' "
                          "AND source_table='doc_page' LIMIT 400").fetchall()
    assert stated
    for doc_key, page, quote in stated:
        text = conn.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?", (doc_key, page)).fetchone()
        assert text, (doc_key, page)  # the page was imported into this database
    # derived and company-stated net debt sit side by side for Hindalco
    kinds = {r[0] for r in conn.execute("SELECT definition FROM fin_annual_line WHERE symbol='HINDALCO' AND fiscal_year='FY26' "
                                        "AND line_item='net_debt'")}
    assert {"xbrl_derived", "company_stated"} <= kinds
    # XBRL balance sheet agrees with the printed one: Bajaj consolidated net worth FY26 (113,999.02 crore)
    nw = conn.execute("SELECT value FROM fin_annual_line WHERE symbol='BAJFINANCE' AND fiscal_year='FY26' AND basis='consolidated' "
                      "AND line_item='net_worth' AND definition='xbrl_derived'").fetchone()[0]
    assert nw / 1e7 == pytest.approx(113999.02, rel=1e-4)
    assert conn.execute("SELECT COUNT(*) FROM fin_quarter_xbrl WHERE symbol='BAJFINANCE' AND line_item='net_interest_income'").fetchone()[0] > 20
    assert conn.execute("SELECT COUNT(*) FROM dividend_event").fetchone()[0] > 15
    conn.close()
