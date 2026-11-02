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
