"""T-049 part A: pilot3 core database (registry, pages, stores, ratios, queries, oracle).

Unit tests use tiny synthetic tables; the integration test builds the real database from the read-only
stores and sandboxes and is skipped when they are not on this machine."""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

from reality_engine import pilot3
from reality_engine.pilot3 import oracle, profile, queries, ratios, schema, stores


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    return conn


def test_fiscal_period_follows_the_indian_year():
    assert stores.fiscal_period("2026-06-30") == "Q1FY27"
    assert stores.fiscal_period("2026-03-31") == "Q4FY26"
    assert stores.fiscal_period("2025-12-31") == "Q3FY26"
    assert stores.fiscal_period("2025-05-31") is None


def test_a_transcript_is_never_known_before_the_call_it_transcribes():
    """Defect (4 Nov 2026 review): KEC's Q4 FY26 call was dated 18 Feb 2026 though held on 18 May 2026.

    The stored date comes from a filing record, so the call date printed in the first pages raises it: both
    ``known_at`` and the filing date move forward, a later filing timestamp is kept, and a document with no call
    date in its text keeps the record's dates (it is reported, not guessed)."""
    from reality_engine.pilot3 import call_dates

    con = sqlite3.connect(":memory:")
    con.executescript("CREATE TABLE doc(doc_key, doc_type, filing_date, known_at);"
                      "CREATE TABLE doc_page(doc_key, page, text);")
    con.executemany("INSERT INTO doc VALUES (?,?,?,?)", [
        ("kec/call.pdf", "transcript", "2026-02-18", "2026-02-18T10:00:00"),
        ("kec/later.pdf", "transcript", "2026-05-21", "2026-05-21T16:19:54"),
        ("kec/none.pdf", "transcript", "2026-01-30", "2026-02-02T18:03:23"),
        ("kec/deck.pdf", "deck", "2026-02-18", "2026-05-18T10:00:00"),     # not a transcript: untouched
    ])
    con.executemany("INSERT INTO doc_page VALUES (?,?,?)", [
        ("kec/call.pdf", 1, "KEC International Limited Q4 FY '26 Results Conference Call\nMay 18, 2026\n"),
        ("kec/later.pdf", 1, "Conference Call held on 18 May 2026"),
        ("kec/none.pdf", 1, "Moderator: Ladies and gentlemen, welcome to the call."),
        ("kec/deck.pdf", 1, "Q4 FY 26 Results Conference Call\nMay 18, 2026"),
    ])
    dates = call_dates.raise_doc_dates(
        con, con.execute("SELECT doc_key, doc_type, filing_date, known_at FROM doc").fetchall())
    assert dates["kec/call.pdf"] == ("2026-05-18", "2026-05-18", "2026-05-18")
    # the filing timestamp after the call stays
    assert dates["kec/later.pdf"] == ("2026-05-21", "2026-05-21T16:19:54", "2026-05-18")
    # no call date in the text: the record's dates are kept and the call date is reported as unread
    assert dates["kec/none.pdf"] == ("2026-01-30", "2026-02-02T18:03:23", None)
    assert "kec/deck.pdf" not in dates
    # a date far from the record is a stray header date, not this document's call
    assert call_dates.clamp("2026-02-18", "2026-02-18T10:00:00", ["May 18, 2028"]) == \
        ("2026-02-18", "2026-02-18T10:00:00", None)
    assert call_dates.call_date(["Q2 FY26 Results Conference Call; May 4, 2025"]) == "2025-05-04"


def test_the_call_date_rule_reads_the_first_pages_only():
    """A dated comparison in the body must never date the document: the header is read, the body is not."""
    from reality_engine.pilot3 import call_dates

    assert call_dates.call_date(["19 November 2025\nAnalyst: in your January 2026 call you said ..."]) == "2025-11-19"
    assert call_dates.call_date(["Cover letter\nDate: 21 May 2026"]) == "2026-05-21"
    assert call_dates.call_date(["no date at all in this text"]) is None



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
    conn.executemany("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, audited, "
                     "statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, source_table, "
                     "source_rowid, known_at, known_at_source, is_reported) VALUES (" + ",".join("?" * 20) + ")", rows)
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
    return all(pilot3.sandbox_db(s).is_file() for s in profile.symbols()) \
        and (pilot3.data_root() / "ar_facts.db").is_file()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from reality_engine.pilot3 import build

    db = tmp_path_factory.mktemp("pilot3") / "pilot3.db"
    build.build(db, "all")
    return db


@pytest.mark.slow
@pytest.mark.skipif(not _real_stores_present(), reason="read-only stores / sandboxes not on this machine")
def test_integration_build_counts_and_oracle(built):
    conn = sqlite3.connect(built)
    quarters = dict(conn.execute("SELECT symbol, COUNT(DISTINCT quarter_end) FROM shp_category GROUP BY symbol"))
    assert quarters["BAJFINANCE"] >= 23 and quarters["HINDALCO"] >= 20 and quarters["KEC"] >= 22
    for table in ("doc_page", "fin_quarter_xbrl", "price_delivery", "ratio_panel", "valuation_daily", "share_capital"):
        got = dict(conn.execute(f"SELECT symbol, COUNT(*) FROM {table} GROUP BY symbol"))
        assert set(got) == set(profile.symbols()), table
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
    conn.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, audited, "
                 "statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, source_table, source_rowid, "
                 "known_at, known_at_source, is_reported) VALUES ('KEC','I','2025-04-01','2025-06-30','Q1FY26',"
                 "'consolidated','a','P&L','pbt_before_exceptional','x',100.0,'inr',1,'f','d','t','r','2025-07-01','k',1)")
    for item, value in (("finance_cost", 20.0), ("depreciation", 10.0), ("other_income", 0.0), ("revenue_from_operations", 1000.0)):
        conn.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, audited, "
                     "statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, source_table, "
                     "source_rowid, known_at, known_at_source, is_reported) VALUES ('KEC','I','2025-04-01','2025-06-30',"
                     "'Q1FY26','consolidated','a','P&L',?,'x',?,'inr',1,'f','d','t','r','2025-07-01','k',1)",
                     (item, value))
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


@pytest.mark.slow
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


# --- T-051: holding categories, book value / ROCE at two year ends, Bajaj Finance NIM -----------------

def test_holding_category_mapping_covers_promoter_mf_and_fpi():
    assert stores.MEMBERS["ShareholdingOfPromoterAndPromoterGroup"] == "promoter"
    assert stores.MEMBERS["MutualFundsOrUti"] == stores.MEMBERS["MutualFundsOrUTI"] == "mutual_funds"
    for member in ("ForeignPortfolioInvestor", "InstitutionsForeignPortfolioInvestorCatergoryOne",
                   "InstitutionsForeignPortfolioInvestorCategoryTwo"):
        assert stores.MEMBERS[member].startswith("fpi"), member


def test_shp_rows_under_an_older_isin_are_copied_to_the_symbol(monkeypatch):
    # The file is filed under the previous ISIN; symbol_isin_history says the symbol held it.
    # The harness's .tmp folder denies nested mkdir in this sandbox; its private TEMP folder does not.
    folder = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / f"pilot3_shp_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    try:
        with gzip.open(folder / "HINDALCO_01062025_WEB.xml.gz", "wb") as fh:
            fh.write(_shp_xml(False).replace(b"INE000A01010", b"IN9038A01010"))
        index = [{"file": "HINDALCO_01062025_WEB.xml", "isin": "IN9038A01010", "quarter_end": "2025-06-30",
                  "promoter_pct": 60.0, "public_pct": 40.0, "record_id": "1", "revised": None,
                  "broadcast_at": "2025-07-01T10:00:00", "submission_date": "2025-06-30"}]
        monkeypatch.setattr(stores, "SHP_XBRL", folder)
        monkeypatch.setattr(stores, "fetch", lambda symbol, table: index if table == "shp_index" else [])
        monkeypatch.setattr(stores, "all_isins", lambda symbol: ("INE038A01020", "IN9038A01010"))
        conn = _conn()
        stores.build_shp(conn)
        rows = dict(conn.execute("SELECT category, pct FROM shp_category WHERE isin='IN9038A01010'"))
        assert rows["promoter"] == pytest.approx(60.0)
        assert rows["mutual_funds"] == pytest.approx(10.0)  # the SHP XBRL category, copied for the old ISIN
        assert "fpi_total" not in rows                      # nothing to derive: no FPI member in this file
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _annual(conn, symbol, fy, end, ptype, item, value, statement="BS", known="2026-05-16T10:00:00"):
    conn.execute(
        "INSERT INTO fin_annual_line(symbol,isin,fiscal_year,period_end,basis,statement,line_item,caption,value,"
        "unit,scale,known_at,is_reported,is_derived,definition,period_type) "
        "VALUES(?,?,?,?,'consolidated',?,?,'x',?,'inr',1,?,1,1,'xbrl_derived',?)",
        (symbol, "I", fy, end, statement, item, value, known, ptype))


def _quarter(conn, symbol, end, item, value):
    conn.execute(
        "INSERT INTO fin_quarter_xbrl(symbol,isin,period_start,period_end,fiscal_period,basis,audited,statement,"
        "line_item,xbrl_tag,value,unit,scale,known_at,is_reported) "
        "VALUES(?,?,?,?,?,'consolidated','A','P&L',?,?,?,'inr',1,?,1)",
        (symbol, "I", end[:7] + "-01", end, stores.fiscal_period(end), item, item, value, end + "T10:00:00"))


def test_book_value_per_share_and_roce_for_fy25_and_fy26():
    conn = _conn()
    for end, ebit in (("2024-06-30", 10.0), ("2024-09-30", 10.0), ("2024-12-31", 10.0), ("2025-03-31", 10.0),
                      ("2025-06-30", 12.0), ("2025-09-30", 12.0), ("2025-12-31", 12.0), ("2026-03-31", 12.0)):
        _quarter(conn, "T", end, "pbt_before_exceptional", ebit - 20.0)
        _quarter(conn, "T", end, "finance_cost", 20.0)     # EBIT = pbt + finance cost
    for fy, end, nw, ce in (("FY25", "2025-03-31", 1000.0, 2000.0), ("FY26", "2026-03-31", 1200.0, 2400.0)):
        _annual(conn, "T", fy, end, "FY", "net_worth", nw)
        _annual(conn, "T", fy, end, "FY", "capital_employed", ce)
        conn.execute("INSERT INTO share_capital(symbol,isin,as_of_date,basis,event,ratio,shares_outstanding,"
                     "known_at,unit) VALUES('T','I',?,'consolidated',NULL,NULL,100.0,?,'shares')",
                     (end, end + "T10:00:00"))
    out: list = []
    ratios._balance_ratios(conn, "T", "I", out)
    got = {(r[2], r[7]): r for r in out}
    assert got[("FY25", "book_value_per_share")][8] == pytest.approx(10.0)   # 1000 / 100 shares
    assert got[("FY26", "book_value_per_share")][8] == pytest.approx(12.0)   # 1200 / 100 shares
    assert got[("FY25", "roce")][8] == pytest.approx(2.0)                    # 100 * 40 / 2000
    assert got[("FY26", "roce")][8] == pytest.approx(2.0)                    # 100 * 48 / 2400
    assert got[("FY26", "book_value_per_share")][11] == "F_BVPS" and got[("FY26", "roce")][11] == "F_ROCE"
    assert got[("FY26", "roce")][15] == 1                                    # is_derived


def test_bajaj_nim_is_annualised_net_interest_income_over_the_average_loan_book():
    conn = _conn()
    for end, value in (("2024-06-30", 20.0), ("2024-09-30", 20.0), ("2024-12-31", 22.0), ("2025-03-31", 22.0),
                       ("2025-06-30", 25.0), ("2025-09-30", 25.0), ("2025-12-31", 30.0), ("2026-03-31", 30.0)):
        _quarter(conn, "BAJFINANCE", end, "net_interest_income", value)
    for fy, end, ptype, loans in (("FY24", "2024-03-31", "FY", 800.0), ("FY25", "2025-03-31", "FY", 1000.0),
                                  ("H1FY26", "2025-09-30", "H1", 1100.0), ("FY26", "2026-03-31", "FY", 1200.0)):
        _annual(conn, "BAJFINANCE", fy, end, ptype, "loans", loans)
    out: list = []
    ratios._balance_ratios(conn, "BAJFINANCE", "I", out)
    got = {(r[2], r[7]): r for r in out if r[7] == "nim_pct"}
    assert got[("FY25", "nim_pct")][8] == pytest.approx(100 * 84 / 900)          # 84 NII / avg(800, 1000)
    assert got[("FY26", "nim_pct")][8] == pytest.approx(100 * 110 / 1100)        # 110 NII / avg(1000, 1200)
    assert got[("H1FY26", "nim_pct")][8] == pytest.approx(100 * 2 * 50 / 1050)   # H1 annualised x2
    row = got[("FY26", "nim_pct")]
    assert row[11] == "F_NIM" and row[15] == 1
    assert "net_interest_income" in row[12] and ":loans#" in row[12]             # every input named
    assert row[13] >= "2026-03-31"
    nim = next(f for f in ratios.FORMULAS if f[1] == "nim_pct")
    assert nim[0] == "F_NIM" and nim[3] == "net_interest_income,loans" and nim[4] == "pct"
    # a company-stated NIM is never merged into the derived row: kpi_series stays its own table
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='kpi_series'").fetchone()[0] == 0


# --- T-056 loop 2: bank / insurer lines, share count from the shareholding pattern, deals, index prices -------------
def _fake_reader(monkeypatch, handler):
    monkeypatch.setattr(stores.prepare, "_read_sqlite", lambda db, source, sql, params: (handler(sql, params), {}))


def test_bank_and_life_lines_are_mapped_by_taxonomy_and_never_written_twice(monkeypatch):
    meta = {"bank.xml": ("I", "2026-07-01", "2026-09-30", "Q2FY27", "standalone", "A", "2026-10-17T05:48:06"),
            "life.xml": ("J", "2026-07-01", "2026-09-30", "Q2FY27", "standalone", "A", "2026-10-27T07:26:42")}
    facts = [("bank.xml", "InterestEarned", 1000.0, 1), ("bank.xml", "InterestExpended", 600.0, 2),
             ("bank.xml", "ProfitLossForThePeriod", 120.0, 3), ("bank.xml", "EmployeesCost", 30.0, 4),
             ("bank.xml", "BasicEarningsPerShareAfterExtraordinaryItems", 7.5, 5),
             ("life.xml", "GrossPremiumIncome", 900.0, 6), ("life.xml", "ProfitLossAfterTaxAndExtraordinaryItems", 55.0, 7),
             ("life.xml", "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized", 5.47, 8),
             ("life.xml", "EmployeesCost", 1.0, 9)]          # not a life-taxonomy element: ignored
    _fake_reader(monkeypatch, lambda sql, params: facts)
    rows = stores._quarter_extras("X", meta, {("bank.xml", "employee_cost")})   # the quarterly view gave the bank's cost
    by = {(r[13], r[8]): r for r in rows}
    assert by[("bank.xml", "net_interest_income")][10] == 400.0 and by[("bank.xml", "net_interest_income")][19] == 0
    assert by[("bank.xml", "pat")][10] == 120.0 and by[("bank.xml", "eps_basic")][10] == 7.5
    assert ("bank.xml", "employee_cost") not in by                                 # already written: not twice
    assert by[("life.xml", "pat")][10] == 55.0 and by[("life.xml", "gross_premium")][10] == 900.0
    assert by[("life.xml", "eps_basic")][10] == by[("life.xml", "eps_diluted")][10] == 5.47
    assert ("life.xml", "employee_cost") not in by
    assert len({(r[13], r[8]) for r in rows}) == len(rows)


def test_a_quarter_without_a_results_share_count_takes_the_shareholding_pattern_total(monkeypatch):
    conn = _conn()
    conn.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, audited, "
                 "statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, source_table, source_rowid, "
                 "known_at, known_at_source, is_reported) VALUES ('KEC','I','2026-04-01','2026-06-30','Q1FY27',"
                 "'standalone','A','P&L','pat','pat',1.0,'inr',1.0,'f','d','t','r','2026-07-30','s',1)")
    shp = [("KEC", "I", q, "shareholding_pattern", "ShareholdingPattern", shares, 100.0, None, "pct", "xbrl", "shp.xml", "db",
            "xml.gz", "shp.xml", None, known, "x", 1, None, None) for q, shares, known in
           (("2026-06-30", 1003240534.0, "2026-07-17T23:38:01"), ("2026-09-30", 1003500000.0, "2026-10-15T18:54:56"))]
    conn.executemany("INSERT INTO shp_category VALUES (" + ",".join("?" * 20) + ")", shp)
    conn.execute("INSERT INTO share_capital VALUES ('KEC','I','2026-06-30','standalone',NULL,NULL,1.0,1.0,1.0,'shares',1.0,"
                 "'2026-07-30','s','d','t','r',NULL,NULL)")        # the results filing gave June too; T-073 keeps both
    assert stores.build_share_fallback(conn)["KEC"] == 2           # the exact total joins the rounded paid-up row
    row = conn.execute("SELECT as_of_date, basis, shares_outstanding, known_at, source_table FROM share_capital "
                       "WHERE as_of_date='2026-09-30'").fetchone()
    assert row == ("2026-09-30", "standalone", 1003500000.0, "2026-10-15T18:54:56", "shp_category")
    june = conn.execute("SELECT shares_outstanding, source_table FROM share_capital WHERE as_of_date='2026-06-30' "
                        "ORDER BY source_table").fetchall()
    assert june == [(1003240534.0, "shp_category"), (1.0, "t")]
    assert stores.build_share_fallback(conn)["KEC"] == 0           # rerun adds nothing


def test_deals_and_insider_trades_are_read_by_isin_and_empty_means_no_rows(monkeypatch):
    seen = []

    def handler(sql, params):
        seen.append((sql, params))
        if "bulk_block_deals" in sql:
            return [("id1", "INE389H01022", "2026-09-18", "A CLIENT", "BULK", "BUY", 1000, 55.5, "NSE", 0)] \
                if "INE389H01022" in params else []
        return [("nse", "k1", "INE389H01022", "P", "Promoters", "BUY", "MARKET", "Equity Shares", 10.0, 500.0, 1.0, 1.1,
                 "2026-10-01", "2026-10-02", "2026-10-03", None)] if "INE389H01022" in params else []

    _fake_reader(monkeypatch, handler)
    conn = _conn()
    stores.build_deals(conn)
    stores.build_insiders(conn)
    assert conn.execute("SELECT symbol, deal_date, quantity, trade_price, known_at FROM bulk_block_deal").fetchall() \
        == [("KEC", "2026-09-18", 1000.0, 55.5, "2026-09-18")]
    assert conn.execute("SELECT symbol, person_name, qty, known_at FROM insider_trade").fetchall() \
        == [("KEC", "P", 10.0, "2026-10-03")]                       # no known_at in the store: the intimation date
    assert all("isin IN" in sql for sql, _ in seen)
    assert conn.execute("SELECT COUNT(*) FROM bulk_block_deal WHERE symbol='BAJFINANCE'").fetchone()[0] == 0


def test_index_price_relative_return_is_stock_less_index_in_points_and_null_before_history(monkeypatch):
    index = [("2025-11-03", 100.0), ("2026-05-04", 110.0), ("2026-11-03", 120.0)]
    _fake_reader(monkeypatch, lambda sql, params: index)
    conn = _conn()
    conn.executemany("INSERT INTO price_delivery VALUES (" + ",".join("?" * 21) + ")",
                     [("KEC", "I", "NSE", d, 0, 0, 0, close, 0, 0, 0, 0, 0, 0, 1.0, adj, d, "x", "d", "t", "r")
                      for d, close, adj in (("2025-11-03", 200.0, 50.0), ("2026-05-04", 260.0, 65.0), ("2026-11-03", 300.0, 75.0))])
    stores.build_index_prices(conn)
    got = conn.execute("SELECT stock_close, stock_adj_close, index_close, stock_return_12m, index_return_12m, "
                       "relative_return_12m, relative_return_6m, relative_return_1m FROM index_price "
                       "WHERE symbol='KEC' AND date='2026-11-03'").fetchone()
    # 12 months: stock 75 / 50 = +50 %, index 120 / 100 = +20 %  ->  +30 points
    assert got[:3] == (300.0, 75.0, 120.0)
    assert got[3] == pytest.approx(50.0) and got[4] == pytest.approx(20.0) and got[5] == pytest.approx(30.0)
    assert got[6] == pytest.approx(30.0)                              # 6 months back = 3 May: last print is still 3 Nov 2025
    assert got[7] == pytest.approx(100 * (75 / 65 - 1) - 100 * (120 / 110 - 1))   # 1m = last print on or before 3 Oct
    first = conn.execute("SELECT relative_return_12m FROM index_price WHERE symbol='KEC' AND date='2025-11-03'").fetchone()
    assert first == (None,)                                          # nothing before the first held day


def test_bank_net_worth_and_industrial_ebitda_annual_lines_only_under_a_profile(tmp_path):
    import json

    from reality_engine.pilot3 import profile, statements

    f = {"isin": "I", "file": "f.xml", "known_at": "2026-04-18T07:28:36", "period_end": "2026-03-31", "consolidated": "Standalone"}
    facts = [("Capital", "OneI", None, None, "2026-03-31", 15.0, "INR", 1), ("ReservesAndSurplus", "OneI", None, None, "2026-03-31", 5568.0, "INR", 2),
             ("ProfitLossForThePeriod", "FourD", "2025-04-01", "2026-03-31", None, 746.0, "INR", 3),
             ("ProfitBeforeExceptionalItemsAndTax", "FourD", "2025-04-01", "2026-03-31", None, 100.0, "INR", 4),
             ("FinanceCosts", "FourD", "2025-04-01", "2026-03-31", None, 10.0, "INR", 5),
             ("DepreciationDepletionAndAmortisationExpense", "FourD", "2025-04-01", "2026-03-31", None, 20.0, "INR", 6),
             ("OtherIncome", "FourD", "2025-04-01", "2026-03-31", None, 5.0, "INR", 7),
             ("CurrentInvestments", "OneI", None, None, "2026-03-31", 7.0, "INR", 8)]
    plain = {r[6]: r[8] for r in statements._filing_lines("KEC", f, "FY", facts)}
    assert "net_worth" not in plain and "ebitda" not in plain and "investments" not in plain and plain["pat"] == 746.0
    data = {"name": "x", "pages_db": "p", "raw_root": "r", "manifest": "m", "out": "o", "window_start": "2025-10-01",
            "companies": [{"symbol": "KEC", "isins": ["INE389H01022"], "lender": False}]}
    (tmp_path / "p.json").write_text(json.dumps(data), encoding="utf-8")
    try:
        profile.activate(profile.load(tmp_path / "p.json"))
        got = {r[6]: r[8] for r in statements._filing_lines("KEC", f, "FY", facts)}
    finally:
        profile.activate(None)
    assert got["net_worth"] == 15.0 + 5568.0          # capital + reserves and surplus (a bank has no equity tag)
    assert got["ebitda"] == 100.0 + 10.0 + 20.0 - 5.0
    assert got["investments"] == 7.0


def test_net_debt_after_all_investments_line_next_to_plain_net_debt():
    from reality_engine.pilot3 import statements

    f = {"isin": "I", "file": "f.xml", "known_at": "2026-04-28T16:00:00", "period_end": "2026-03-31", "consolidated": "Consolidated"}
    bs = (("BorrowingsCurrent", 100.0), ("BorrowingsNoncurrent", 50.0), ("CashAndCashEquivalents", 20.0),
          ("CurrentInvestments", 30.0), ("NoncurrentInvestments", 400.0))
    facts = [(tag, "OneI", None, None, "2026-03-31", v, "INR", i) for i, (tag, v) in enumerate(bs, 1)]
    got = {r[6]: r[8] for r in statements._filing_lines("MARUTI", f, "FY", facts)}
    assert got["net_debt"] == 150.0 - 20.0 - 30.0                       # plain definition unchanged
    assert got["net_debt_all_investments"] == 150.0 - 20.0 - 30.0 - 400.0  # treasury in non-current investments
    no_nci = {r[6] for r in statements._filing_lines("MARUTI", f, "FY", facts[:4])}
    assert "net_debt" in no_nci and "net_debt_all_investments" not in no_nci
