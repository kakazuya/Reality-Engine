"""Tests for the independent row check layer (``reality_engine/pilot3/row_checks.py``, T-113 A).

Run from the repo root:
    python -m pytest reality_engine/tests/test_row_checks.py -q

Every catalogue builds a tiny sqlite database whose columns are copied from the built dev database
(``doc``, ``doc_page``, ``guidance``, ``kpi_series``, ``company``, and the two filed-statement tables), puts the
ticket's sentences in the page text verbatim, and asserts the verdict: the known-wrong rows are quarantined, the
known-right rows are never quarantined (and are verified where the brief says so).  No test reads the live data.
"""
from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import row_checks as rc

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def tmp_path():
    """A writable scratch directory for this test (the repo's .tmp).

    The pytest tmp_path plugin is shadowed on purpose: in this Windows workspace the sandbox lets the test process
    create a directory but not LIST one it created, and pytest's own basetemp root (.tmp/pytest-of-<user>) then
    fails before a test runs.  The checker and sqlite only need writable paths, never a directory listing.
    """
    base = ROOT / ".tmp" / f"row_checks_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)

DDL = """
CREATE TABLE doc (
    doc_key TEXT PRIMARY KEY, symbol TEXT, isin TEXT, doc_type TEXT, doc_family TEXT, title TEXT,
    filing_date TEXT, known_at TEXT, pages INTEGER, sha256 TEXT, source TEXT, source_key TEXT);
CREATE TABLE doc_page (
    doc_key TEXT, symbol TEXT, page INTEGER, text TEXT, method TEXT, chars INTEGER, known_at TEXT, ocr_conf REAL,
    PRIMARY KEY (doc_key, page));
CREATE TABLE guidance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, isin TEXT, metric TEXT, target_period TEXT, low REAL, high REAL, unit TEXT,
    direction TEXT, said_on TEXT, doc_key TEXT, page INTEGER, quote TEXT, speaker TEXT,
    known_at TEXT, known_at_source TEXT, revision_of INTEGER, extractor_rule TEXT);
CREATE TABLE kpi_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, isin TEXT, metric TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT 'total',
    value REAL NOT NULL, unit TEXT NOT NULL, scale REAL NOT NULL DEFAULT 1,
    period_type TEXT NOT NULL, fiscal_period TEXT NOT NULL, as_of_date TEXT,
    basis TEXT NOT NULL DEFAULT 'not_stated', doc_key TEXT NOT NULL, page INTEGER NOT NULL,
    quote TEXT NOT NULL, known_at TEXT, known_at_source TEXT, is_reported INTEGER NOT NULL DEFAULT 1,
    raw_label TEXT, raw_value TEXT, extractor_rule TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'sentence', conf_rank INTEGER NOT NULL DEFAULT 2,
    method TEXT NOT NULL DEFAULT 'text_layer', ocr_conf REAL, source_type TEXT NOT NULL DEFAULT '',
    entity TEXT NOT NULL DEFAULT '',
    UNIQUE(symbol, metric, dimension, fiscal_period, value, unit, doc_key, page));
CREATE TABLE company (
    symbol TEXT, isin TEXT, isin_from TEXT, isin_to TEXT, isin_source TEXT, bse_code TEXT, name TEXT);
CREATE TABLE fin_quarter_current (
    symbol TEXT, isin TEXT, period_start TEXT, period_end TEXT, fiscal_period TEXT, basis TEXT, statement TEXT,
    line_item TEXT, value REAL, unit TEXT, scale REAL, known_at TEXT, known_at_source TEXT, is_reported INTEGER,
    preferred_from TEXT, preferred_to TEXT, source_table TEXT, source TEXT, page INTEGER, column_role TEXT,
    check_status TEXT, xbrl_tag TEXT);
CREATE TABLE fin_annual_line (
    symbol TEXT, isin TEXT, fiscal_year TEXT, period_end TEXT, basis TEXT, statement TEXT, line_item TEXT,
    caption TEXT, value REAL, unit TEXT, scale REAL, doc_key TEXT, page INTEGER, quote TEXT, source_db TEXT,
    source_table TEXT, source_rowid TEXT, known_at TEXT, known_at_source TEXT, is_reported INTEGER,
    is_derived INTEGER, definition TEXT, period_type TEXT);
"""

GUIDANCE_DEFAULTS = dict(
    symbol="", isin=None, metric="", target_period="FY27", low=None, high=None, unit="pct", direction="up",
    said_on="2026-05-01", doc_key="d1", page=1, quote="", speaker="", known_at="2026-05-01T00:00:00",
    known_at_source="test", revision_of=None, extractor_rule="guidance_cue_v1",
)
KPI_DEFAULTS = dict(
    symbol="", isin=None, metric="", dimension="total", value=0.0, unit="pct", scale=1.0, period_type="Q",
    fiscal_period="Q1FY27", as_of_date="2026-06-30", basis="consolidated", doc_key="d1", page=1, quote="",
    known_at="2026-08-01T00:00:00", known_at_source="test", is_reported=1, raw_label=None, raw_value=None,
    extractor_rule="sentence_v1", confidence="sentence", conf_rank=2, method="text_layer", ocr_conf=None,
    source_type="transcript", entity="",
)


def build(tmp_path: Path, pages: dict[int, str], guidance: list[dict] | None = None,
          kpi: list[dict] | None = None, fin_q: list[dict] | None = None, fin_a: list[dict] | None = None,
          sectors: dict[str, str] | None = None, db_name: str = "row_checks_fixture.db") -> tuple[str, str]:
    """Build the fixture database and its sector profile; return (db path, profile path)."""
    guidance, kpi, fin_q, fin_a = guidance or [], kpi or [], fin_q or [], fin_a or []
    sectors = sectors or {}
    db = tmp_path / db_name
    con = sqlite3.connect(db)
    con.executescript(DDL)
    con.execute("INSERT INTO doc(doc_key,symbol,isin,doc_type,doc_family,title,filing_date,known_at,pages) "
                "VALUES ('d1','',NULL,'transcript','transcript','test doc','2026-05-01','2026-05-01T00:00:00',?)",
                (len(pages),))
    con.executemany("INSERT INTO doc_page(doc_key,symbol,page,text) VALUES ('d1','',?,?)",
                    [(page, text) for page, text in pages.items()])
    for symbol, sector in sectors.items():
        con.execute("INSERT INTO company(symbol,name) VALUES (?,?)", (symbol, f"{symbol} Ltd"))
    for row in guidance:
        data = {**GUIDANCE_DEFAULTS, **row}
        con.execute(f"INSERT INTO guidance({','.join(data)}) VALUES ({','.join('?' * len(data))})", tuple(data.values()))
    for row in kpi:
        data = {**KPI_DEFAULTS, **row}
        con.execute(f"INSERT INTO kpi_series({','.join(data)}) VALUES ({','.join('?' * len(data))})", tuple(data.values()))
    con.executemany("INSERT INTO fin_quarter_current(symbol,fiscal_period,line_item,value,scale,basis) "
                    "VALUES (:symbol,:fiscal_period,:line_item,:value,:scale,:basis)",
                    [{**dict(symbol="", fiscal_period="", line_item="", value=None, scale=1.0, basis="consolidated"),
                      **r} for r in fin_q])
    con.executemany("INSERT INTO fin_annual_line(symbol,fiscal_year,line_item,value,scale,basis) "
                    "VALUES (:symbol,:fiscal_year,:line_item,:value,:scale,:basis)",
                    [{**dict(symbol="", fiscal_year="", line_item="", value=None, scale=1.0, basis="consolidated"),
                      **r} for r in fin_a])
    con.commit()
    con.close()
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"companies": [{"symbol": s, "sector": v} for s, v in sectors.items()]}),
                       encoding="utf-8")
    return str(db), str(profile)


def run_checks(tmp_path: Path, db: str, profile: str, tables: tuple[str, ...] = ("guidance", "kpi_series"),
               **kw) -> Path:
    out = tmp_path / "verdicts.db"
    rc.run(db, str(out), profile, tables, **kw)
    return out


def verdict(out: Path, table: str, row_id: int) -> tuple[str, list[str]]:
    con = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    v = con.execute("SELECT status FROM row_check WHERE tbl=? AND row_id=?", (table, row_id)).fetchone()
    fails = [r[0] for r in con.execute("SELECT check_name FROM row_check_fail WHERE tbl=? AND row_id=? ORDER BY check_name",
                                       (table, row_id))]
    con.close()
    assert v is not None, (table, row_id)
    return v["status"], fails


# -------------------------------------------------------------------------------------------- unit tests

def test_numbers_in_reads_ranges_grouping_and_parentheses():
    assert [v for v, _, _ in rc.numbers_in("20%-22%")] == [20.0, 22.0]
    assert [v for v, _, _ in rc.numbers_in("Rs.33,688 million")] == [33688.0]
    assert [v for v, _, _ in rc.numbers_in("1,40,647.0")] == [140647.0]
    assert [v for v, _, _ in rc.numbers_in("(12.3)")] == [12.3]
    assert [v for v, _, _ in rc.numbers_in("a reduction of 145 KT")] == [145.0]
    assert [v for v, _, _ in rc.numbers_in("20.5%")] == [20.5]


def test_delta_and_denominator_patterns():
    assert rc._DELTA.search("the number is a reduction of ")
    assert rc._DELTA.search("revenue grew by ")
    assert not rc._DELTA.search("margin was ")
    assert rc._DENOM.search("2.5% of our revenues")
    assert rc._DENOM.search("40 bps of aum")
    assert not rc._DENOM.search("2.5% growth")


def test_period_end_arithmetic():
    assert rc.period_end("FY26") == "2026-03-31"
    assert rc.period_end("Q1FY27") == "2026-06-30"
    assert rc.period_end("Q2FY27") == "2026-09-30"
    assert rc.period_end("Q4FY26") == "2026-03-31"
    assert rc.period_end("H1FY26") == "2025-09-30"
    assert rc.period_end("9MFY26") == "2025-12-31"
    assert rc.period_end("not a period") is None


# ----------------------------------------------------------------------------------- known-wrong guidance

V2_WRONG = [
    ("BANK", "aum_growth", 12.0, 13.0, "FY27",
     "So our understanding as of now is next year, we expect system growth to be between 12% to 13%, when you "
     "look at nominal GDP and the credit growth that's required."),
    ("BANK", "aum_growth", 9.0, 9.5, "FY26",
     "At least if you see through large part of FY26, the nominal GDP growth expected was somewhere around the "
     "9%, 9.5%, so one consensus until the large part of the year."),
    ("BANK", "aum_growth", 12.0, 12.0, "FY27",
     "This is what we had expected, and we calibrated our strategies and our growth in line with that, and that "
     "is why we grew at 12%."),
    ("INSURER", "aum_growth", 14.0, 14.0, "FY27",
     "So this 14% will be an optimum mix of the agency growth and the banca growth."),
    ("INSURER", "aum_growth", 14.0, 15.0, "FY27",
     "And for the year, we had guided for a growth of 14% to 15%."),
    ("INSURER", "opex_to_nti", None, None, "FY27",
     "As and when they move in, we will be changing our products and our opex or commission structure in line "
     "with the regulators guidelines."),
]


def test_v2_known_wrong_guidance_rows_are_quarantined(tmp_path):
    pages = {i + 1: row[5] for i, row in enumerate(V2_WRONG)}
    guidance = [dict(id=i + 1, symbol=row[0], metric=row[1], low=row[2], high=row[3], target_period=row[4],
                     quote=row[5], page=i + 1, said_on="2026-04-24", known_at="2026-04-24T15:45:11")
                for i, row in enumerate(V2_WRONG)]
    db, profile = build(tmp_path, pages, guidance=guidance,
                        sectors={"BANK": "bank", "INSURER": "insurance_life"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    for i in range(1, len(V2_WRONG) + 1):
        status, fails = verdict(out, "guidance", i)
        assert status == "quarantined", (i, fails)


GEMINI_WRONG = [
    ("LENDER", "credit_cost", 4.4, 4.6, "FY27",
     "• Return on assets – Return on assets is estimated to be in the range of 4.4%-4.6%."),
    ("LENDER", "credit_cost", 19.0, 20.0, "FY27",
     "• Return on equity – Given excess capital, ROE metric is estimated to be between 19%-20%."),
    ("LENDER", "aum_growth", 16.0, 18.0, "FY27",
     "• Non-interest income – The Company estimates non-interest income to grow by 16-18%."),
    ("LENDER", "leverage", 7.55, 7.65, "FY26",
     "It is an improvement of 7 basis points sequentially and COF is expected to be -- we had outlined at the "
     "beginning of the year from a guidance standpoint, the number to be between 7.55% to 7.65%."),
    ("LENDER", "new_customers", 120.0, 120.0, "FY27",
     "As I shared as part of our annual investor outlook, the 5-year outlook that business by business, the "
     "120 million franchise, principally has very high wallet share across each line of business that we are in."),
    ("IT", "revenue_growth", 1.0, 1.0, "FY27",
     "We expect Onsite mix excluding new acquisitions to reduce by 75 bps to 1% for the year."),
    ("ETERNAL", "ebitda_margin", None, None, "FY26",
     "So, that's why you see the growth in margin versus our earlier guidance of margin perhaps remaining flat."),
]


def test_gemini_known_wrong_rows_are_quarantined(tmp_path):
    pages = {i + 1: row[5] for i, row in enumerate(GEMINI_WRONG)}
    guidance = [dict(id=i + 1, symbol=row[0], metric=row[1], low=row[2], high=row[3], target_period=row[4],
                     quote=row[5], page=i + 1)
                for i, row in enumerate(GEMINI_WRONG)]
    db, profile = build(tmp_path, pages, guidance=guidance,
                        sectors={"LENDER": "nbfc", "IT": "it_services", "ETERNAL": "consumer_internet"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    for i in range(1, len(GEMINI_WRONG) + 1):
        status, fails = verdict(out, "guidance", i)
        assert status == "quarantined", (i, fails)


# ------------------------------------------------------------------------------------ known-right guidance

def test_known_right_guidance_rows(tmp_path):
    pages = {
        1: "Our operating margin guidance for financial year '27 is 20% to 22%.",
        2: "The Company expects to disburse 60-62 MM new loans in FY27.",
        3: "I would say probably between 26%, 27% growth we should deliver now on a full year basis.",
    }
    guidance = [
        dict(id=1, symbol="IT", metric="ebitda_margin", low=20.0, high=22.0, target_period="FY27",
             quote=pages[1], page=1, said_on="2026-07-17", known_at="2026-07-17T00:00:00"),
        dict(id=2, symbol="LENDER", metric="new_loans", low=60.0, high=62.0, unit="mn", target_period="FY27",
             quote=pages[2], page=2, said_on="2026-07-24", known_at="2026-07-24T00:00:00"),
        dict(id=3, symbol="LENDER", metric="aum_growth", low=26.0, high=27.0, target_period="FY27",
             quote=pages[3], page=3, said_on="2026-07-24", known_at="2026-07-24T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, guidance=guidance, sectors={"IT": "it_services", "LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    assert verdict(out, "guidance", 1)[0] == "verified"
    assert verdict(out, "guidance", 2)[0] == "verified"
    status, _ = verdict(out, "guidance", 3)
    assert status == "unverified", "a lender's unqualified growth is soft, never quarantined"


# --------------------------------------------------------------------------------------------- kpi cases

def test_list_order_ignores_a_single_value_after_two_labels(tmp_path):
    pages = {
        1: "The company's EV also recorded healthy growth during the quarter. Retail sales during the quarter "
           "were broadly in line with wholesale dispatches, resulting in dealer inventory closing of around "
           "13 days at the end of the quarter.",
        2: "Revenue and order intake during the year stood at over ` 1,550 Crore and over ` 540 Crore "
           "respectively, with a focus on projects offering better execution visibility.",
    }
    kpi = [
        dict(id=1, symbol="AUTO", metric="dealer_inventory_days", fiscal_period="Q1FY27", period_type="Q",
             value=13.0, unit="days", quote="dealer inventory closing of around 13 days", page=1),
        dict(id=2, symbol="EPC", metric="order_intake", dimension="protection", fiscal_period="FY26",
             period_type="FY", value=1550.0, unit="inr_cr", scale=1e7, known_at="2026-05-01T00:00:00",
             quote="order intake during the year stood at over ` 1,550 Crore", page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"AUTO": "auto_oem", "EPC": "epc_capital_goods"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2):
        status, fails = verdict(out, "kpi_series", rid)
        assert status != "quarantined", (rid, fails)


def test_bps_row_pins_the_percent_reading(tmp_path):
    quote = ("credit cost of 0.18%, lowest in the industry.\nOpex to Net \ntotal income\n19.6%\nQ2 FY25\n20.5%\n"
             "Net NPA\n0.12%\nQ2 FY25\n0.12%\n12.2%\nQ2 FY25\n13.0%\nPAT\n₹ 643 \nCr\nGrowth\n18%\nAUM\n₹ 126,749\n"
             "Cr\nGrowth\n24%\nPBT\n₹ 833\nCr\nGrowth\n18%\nROE\nAnnualised")
    kpi = [dict(id=1, symbol="LENDER", metric="credit_cost_bps", dimension="bhfl", entity="bhfl",
                fiscal_period="Q2FY26", value=18.0, unit="bps", quote=quote, page=1)]
    db, profile = build(tmp_path, {1: quote}, kpi=kpi, sectors={"LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "verified", fails


NPA_QUOTE = ("Gross NPA and Net NPA as of 31 March 2026 stood at 1.27% and 0.52% respectively, as against "
             "1.18% and 0.56% as of 31 March 2025")


def test_npa_list_order_places_each_number(tmp_path):
    kpi = [
        dict(id=1, symbol="LENDER", metric="gnpa_pct", fiscal_period="Q4FY26", value=1.27, quote=NPA_QUOTE),
        dict(id=2, symbol="LENDER", metric="nnpa_pct", fiscal_period="Q4FY26", value=0.52, quote=NPA_QUOTE),
        dict(id=3, symbol="LENDER", metric="gnpa_pct", fiscal_period="FY25", period_type="FY", value=1.18,
             quote=NPA_QUOTE),
        dict(id=4, symbol="LENDER", metric="nnpa_pct", fiscal_period="FY25", period_type="FY", value=0.56,
             quote=NPA_QUOTE),
        dict(id=5, symbol="LENDER", metric="nnpa_pct", fiscal_period="FY25", period_type="FY", value=1.18,
             quote=NPA_QUOTE),
    ]
    db, profile = build(tmp_path, {1: NPA_QUOTE}, kpi=kpi, sectors={"LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2, 3, 4):
        assert verdict(out, "kpi_series", rid)[0] == "verified", rid
    status, fails = verdict(out, "kpi_series", 5)
    assert status == "quarantined" and "list_order" in fails, fails


def test_part_not_total_usd_revenue_against_the_period_median(tmp_path):
    pages = {
        1: "Revenue from products and platforms\n 246",
        2: "Revenues \n5,082",
        3: "Revenue from software services\n 4,836",
    }
    kpi = [
        dict(id=1, symbol="IT", metric="revenue_usd", fiscal_period="Q1FY27", value=246.0, unit="usd_mn",
             scale=1e6, quote=pages[1], page=1),
        dict(id=2, symbol="IT", metric="revenue_usd", fiscal_period="Q1FY27", value=5082.0, unit="usd_mn",
             scale=1e6, quote=pages[2], page=2),
        dict(id=3, symbol="IT", metric="revenue_usd", fiscal_period="Q1FY27", value=4836.0, unit="usd_mn",
             scale=1e6, quote=pages[3], page=3),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"IT": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "part_not_total" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] != "quarantined"
    assert verdict(out, "kpi_series", 3)[0] != "quarantined"


def test_part_not_total_inr_revenue_against_the_filed_statement(tmp_path):
    pages = {
        1: "Revenue from Operations related to Novelis Segment has amounting to ₹ 24,584 Crore",
        2: "Total Revenue from Operations 274,944",
    }
    kpi = [
        dict(id=1, symbol="METAL", metric="revenue", fiscal_period="FY26", period_type="FY", value=24584.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="METAL", metric="revenue", fiscal_period="FY26", period_type="FY", value=274944.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2),
    ]
    fin_a = [dict(symbol="METAL", fiscal_year="FY26", line_item="revenue_from_operations", value=274944.0,
                  scale=1e7)]
    db, profile = build(tmp_path, pages, kpi=kpi, fin_a=fin_a, sectors={"METAL": "metals_nonferrous"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "part_not_total" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] == "verified"


def test_period_word_catches_a_nine_month_figure_stored_as_a_year(tmp_path):
    quote = "Revenue for nine months FY26 stood at 500 crore"
    kpi = [
        dict(id=1, symbol="CO", metric="revenue", fiscal_period="FY26", period_type="FY", value=500.0,
             unit="inr_cr", scale=1e7, quote=quote),
        dict(id=2, symbol="CO", metric="revenue", fiscal_period="9MFY26", period_type="9M", value=500.0,
             unit="inr_cr", scale=1e7, quote=quote),
    ]
    db, profile = build(tmp_path, {1: quote}, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "period_word" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] == "verified"


def test_period_word_ignores_a_comparative_and_a_table(tmp_path):
    pages = {
        1: "Cost of funds was 7.52%, an improvement of 27 bps over Q1 FY26",
        2: "AUM ₹ 140,706 Cr Growth 23% PBT ₹ 866 Cr Growth 20% ROE Annualised In Q4 FY25, PAT had a one-time gain",
    }
    kpi = [
        dict(id=1, symbol="LENDER", metric="cost_of_funds_pct", fiscal_period="Q2FY26", value=7.52,
             quote=pages[1], page=1),
        dict(id=2, symbol="LENDER", metric="aum", dimension="total", fiscal_period="Q4FY26", value=140706.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2, extractor_rule="table_v1"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2):
        status, fails = verdict(out, "kpi_series", rid)
        assert "period_word" not in fails, (rid, fails)
        assert status != "quarantined", (rid, fails)


def test_variant_word_is_soft_and_exempt_when_the_metric_says_so(tmp_path):
    pages = {
        1: "Adjusted PAT was 500 crore.",
        2: "Adjusted EBITDA was 500 crore",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="pat", fiscal_period="FY26", period_type="FY", value=500.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="CO", metric="ebitda_adjusted_usd", fiscal_period="FY26", period_type="FY",
             value=500.0, unit="inr_cr", scale=1e7, quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "variant" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] == "verified"


def test_entity_mismatch_is_soft(tmp_path):
    quote = "Customer franchise stood at 1.15 million as of 30 September 2025"
    quote2 = quote.replace("1.15", "5.0")
    kpi = [
        dict(id=1, symbol="LENDER", metric="customer_franchise", dimension="bajaj_financial_securities",
             entity="bhfl", fiscal_period="Q2FY26", value=1.15, unit="count_mn", quote=quote, page=1),
        dict(id=2, symbol="LENDER", metric="customer_franchise", dimension="bhfl", entity="bhfl",
             fiscal_period="Q2FY26", value=5.0, unit="count_mn", quote=quote2, page=2),
    ]
    pages = {1: quote, 2: quote2}
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "entity_mismatch" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] == "verified"


def test_report_writes_summary_and_a_seeded_sample(tmp_path):
    pages = {i: f"Revenues {i}00" for i in (1, 2, 3)}
    kpi = [dict(id=i, symbol="CO", metric="revenue", fiscal_period=f"Q{i}FY26", value=i * 100.0, unit="inr_cr",
                scale=1e7, quote=pages[i], page=i) for i in (1, 2, 3)]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    report = tmp_path / "report"
    out = run_checks(tmp_path, db, profile, ("kpi_series",), report=str(report), sample=2, seed=81108,
                     status="verified")
    summary = report / "row_checks_summary.csv"
    sample = report / "row_checks_sample.tsv"
    assert summary.exists() and sample.exists()
    header = next(csv.reader(summary.open(encoding="utf-8")))
    assert header == ["table", "metric", "sector", "doc_type", "rule", "status", "count"]
    lines = sample.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == ["id", "table", "symbol", "metric", "dimension", "period", "value", "unit",
                                    "quote", "fails"]
    assert len(lines) == 3, lines
    assert verdict(out, "kpi_series", 1)[0] == "verified"


def test_currency_in_the_label_to_number_span_is_quarantined(tmp_path):
    pages = {
        1: "Adjusted Net Debt\n$ \n6,724 $ \n5,176",
        2: "Net debt was ₹5,176 crore",
        3: "Net debt was Rs 5,176 crore",
        4: "order inflows of around USD 225 million (approximately ` 2,000 Crore)",
    }
    kpi = [
        dict(id=1, symbol="METAL", metric="net_debt", dimension="novelis", fiscal_period="Q4FY25",
             value=5176.0, unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="METAL", metric="net_debt", fiscal_period="FY26", period_type="FY", value=5176.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2),
        dict(id=3, symbol="METAL", metric="net_debt", fiscal_period="FY27", period_type="FY", value=5176.0,
             unit="usd_mn", scale=1e6, quote=pages[3], page=3),
        dict(id=4, symbol="EPC", metric="order_intake", fiscal_period="FY26", period_type="FY", value=2000.0,
             unit="inr_cr", scale=1e7, quote=pages[4], page=4),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        sectors={"METAL": "metals_nonferrous", "EPC": "epc_capital_goods"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "currency" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] == "verified"
    status, fails = verdict(out, "kpi_series", 3)
    assert status == "quarantined" and "currency" in fails, fails
    # a backtick is this corpus's rupee glyph, so the rupee approximation is the number's currency
    assert "currency" not in verdict(out, "kpi_series", 4)[1]


def test_dimension_word_flags_a_segment_named_before_a_total_label(tmp_path):
    pages = {
        1: "Aluminium Upstream EBITDA per tonne $1,500",
        2: "Aluminium Upstream ... EBITDA per tonne $1,583",
        3: "Renewables ... Revenues of Rs 122 Cr",
        4: "Consolidated revenues of Rs 500 crore",
        5: "Aluminium Upstream PAT was Rs 100 crore",
        6: "Return on Average Assets (RoA) of 4.26% in FY26",
    }
    kpi = [
        dict(id=1, symbol="METAL", metric="ebitda_per_tonne", dimension="aluminium_upstream",
             fiscal_period="Q4FY26", value=1500.0, unit="usd_per_tonne", quote=pages[1], page=1),
        dict(id=2, symbol="METAL", metric="ebitda_per_tonne", dimension="total", fiscal_period="Q4FY26",
             value=1583.0, unit="usd_per_tonne", quote=pages[2], page=2),
        dict(id=3, symbol="EPC", metric="revenue", dimension="renewables", fiscal_period="Q2FY26",
             value=122.0, unit="inr_cr", scale=1e7, quote=pages[3], page=3),
        dict(id=4, symbol="EPC", metric="revenue", dimension="total", fiscal_period="Q2FY26", value=122.0,
             unit="inr_cr", scale=1e7, quote=pages[3], page=3),
        dict(id=5, symbol="IT", metric="revenue", dimension="total", fiscal_period="Q2FY26", value=500.0,
             unit="inr_cr", scale=1e7, quote=pages[4], page=4),
        dict(id=6, symbol="IT", metric="pat", dimension="total", fiscal_period="Q2FY26", value=100.0,
             unit="inr_cr", scale=1e7, quote=pages[5], page=5),
        dict(id=7, symbol="LENDER", metric="roa_pct", dimension="total", fiscal_period="FY26",
             period_type="FY", value=4.26, unit="pct", quote=pages[6], page=6),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        sectors={"METAL": "metals_nonferrous", "EPC": "epc_capital_goods", "IT": "it_services",
                                 "LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (2, 4, 6):
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "dimension_word" in fails, (rid, fails)
    assert verdict(out, "kpi_series", 5)[0] == "verified"
    # the metric's full name before its own abbreviation is not a segment word
    assert "dimension_word" not in verdict(out, "kpi_series", 7)[1]
