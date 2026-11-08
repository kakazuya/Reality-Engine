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
    con.executemany("INSERT INTO fin_quarter_current(symbol,fiscal_period,line_item,value,unit,scale,basis) "
                    "VALUES (:symbol,:fiscal_period,:line_item,:value,:unit,:scale,:basis)",
                    [{**dict(symbol="", fiscal_period="", line_item="", value=None, unit="inr", scale=1.0,
                             basis="consolidated"), **r} for r in fin_q])
    con.executemany("INSERT INTO fin_annual_line(symbol,fiscal_year,line_item,value,unit,scale,basis) "
                    "VALUES (:symbol,:fiscal_year,:line_item,:value,:unit,:scale,:basis)",
                    [{**dict(symbol="", fiscal_year="", line_item="", value=None, unit="inr", scale=1.0,
                             basis="consolidated"), **r} for r in fin_a])
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
        4: "So we expect to close the year at around 17% of EBITDA margin.",
    }
    guidance = [
        dict(id=1, symbol="IT", metric="ebitda_margin", low=20.0, high=22.0, target_period="FY27",
             quote=pages[1], page=1, said_on="2026-07-17", known_at="2026-07-17T00:00:00"),
        dict(id=2, symbol="LENDER", metric="new_loans", low=60.0, high=62.0, unit="mn", target_period="FY27",
             quote=pages[2], page=2, said_on="2026-07-24", known_at="2026-07-24T00:00:00"),
        dict(id=3, symbol="LENDER", metric="aum_growth", low=26.0, high=27.0, target_period="FY27",
             quote=pages[3], page=3, said_on="2026-07-24", known_at="2026-07-24T00:00:00"),
        dict(id=4, symbol="IT", metric="ebitda_margin", low=17.0, high=17.0, target_period="FY24",
             quote=pages[4], page=4, said_on="2024-03-15", known_at="2024-03-15T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, guidance=guidance, sectors={"IT": "it_services", "LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    assert verdict(out, "guidance", 1)[0] == "verified"
    assert verdict(out, "guidance", 2)[0] == "verified"
    status, _ = verdict(out, "guidance", 3)
    assert status == "unverified", "a lender's unqualified growth is soft, never quarantined"
    # "17% of EBITDA margin": the denominator is the metric's own name, so the label stands
    assert verdict(out, "guidance", 4)[0] == "verified"


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
    quote = "credit cost of 0.18%, lowest in the industry."
    kpi = [dict(id=1, symbol="LENDER", metric="credit_cost_bps", dimension="bhfl", entity="bhfl",
                fiscal_period="Q2FY26", value=18.0, unit="bps", quote=quote, page=1)]
    db, profile = build(tmp_path, {1: quote}, kpi=kpi, sectors={"LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    # the percent reading pins the number; the row is unverified only because nothing corroborates it (round 10)
    assert status == "unverified" and "value_present" not in fails and "single_source" in fails, fails


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
        # the list order places each number, but four values in one sentence are not a single source: served
        # unverified under the high bar
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "list_order" not in fails, (rid, fails)
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
    db, profile = build(tmp_path, {1: quote}, kpi=kpi,
                        fin_q=[dict(symbol="CO", fiscal_period="9MFY26", line_item="revenue_from_operations",
                                    value=500.0, scale=1e7)],
                        sectors={"CO": "it_services"})
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
    db, profile = build(tmp_path, pages, kpi=kpi,
                        fin_a=[dict(symbol="CO", fiscal_year="FY26", line_item="operating_profit", value=500.0,
                                    scale=1e7)],
                        sectors={"CO": "it_services"})
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
    assert "entity_mismatch" not in verdict(out, "kpi_series", 2)[1]


def test_report_writes_summary_and_a_seeded_sample(tmp_path):
    pages = {i: f"Revenues {i}00" for i in (1, 2, 3)}
    kpi = [dict(id=i, symbol="CO", metric="revenue", fiscal_period=f"Q{i}FY26", value=i * 100.0, unit="inr_cr",
                scale=1e7, quote=pages[i], page=i) for i in (1, 2, 3)]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        fin_q=[dict(symbol="CO", fiscal_period=f"Q{i}FY26", line_item="revenue_from_operations",
                                    value=i * 100.0, scale=1e7) for i in (1, 2, 3)],
                        sectors={"CO": "it_services"})
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
    assert "currency" not in verdict(out, "kpi_series", 2)[1]
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
                        fin_q=[dict(symbol="IT", fiscal_period="Q2FY26", line_item="revenue_from_operations",
                                    value=500.0, scale=1e7)],
                        sectors={"METAL": "metals_nonferrous", "EPC": "epc_capital_goods", "IT": "it_services",
                                 "LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (2, 4, 6):
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "dimension_word" in fails, (rid, fails)
    assert "dimension_word" not in verdict(out, "kpi_series", 5)[1]
    # the metric's full name before its own abbreviation is not a segment word
    assert "dimension_word" not in verdict(out, "kpi_series", 7)[1]


# ------------------------------------------------------------------- out-of-pilot reading (unseen6, round 3)

def test_gross_margin_is_not_an_ebitda_margin_label(tmp_path):
    pages = {
        1: "I think we have already guided our gross margin 59% and we remain with that for a year.",
        2: "Gross Margin guidance of 79.3% for the year.",
    }
    guidance = [
        dict(id=1, symbol="PHARMA", metric="ebitda_margin", low=59.0, high=59.0, target_period="FY23",
             quote=pages[1], page=1, said_on="2022-05-01", known_at="2022-05-01T00:00:00"),
        dict(id=2, symbol="PHARMA", metric="gross_margin", low=79.3, high=79.3, target_period="FY26",
             quote=pages[2], page=2, said_on="2025-05-01", known_at="2025-05-01T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, guidance=guidance, sectors={"PHARMA": "pharma"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    # "margin" is this metric's weak word, so a gross-margin figure is not pinned as EBITDA: served unverified
    assert status == "unverified" and "label_weak" in fails, fails
    assert verdict(out, "guidance", 2)[0] == "verified"


def test_a_denominator_is_not_a_metric_label(tmp_path):
    quote = ("Yes, so the capex is typically in the range of 2% to 3% of revenue and while we are getting into "
             "some additional capacity, you may have it at the higher end of this range and that other times "
             "towards the lower end of this range, but typically this would be the range for capex from a near "
             "term point of view.")
    guidance = [dict(id=1, symbol="CO", metric="revenue_growth", low=2.0, high=3.0, target_period="FY20",
                     quote=quote, said_on="2019-08-01", known_at="2019-08-01T00:00:00")]
    db, profile = build(tmp_path, {1: quote}, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "quarantined" and "label_foreign" in fails, fails


def test_improve_by_is_a_delta_not_a_level(tmp_path):
    quote = ("So as we have been discussing in the past calls also, the EBITDA margins have been low for the "
             "past few quarters, but we expect by Q1/Q2, EBITDA should improve by 1% at least and then "
             "stabilize around 11%.")
    guidance = [dict(id=1, symbol="EPC", metric="ebitda_margin", low=1.0, high=1.0, target_period="Q2FY25",
                     quote=quote, said_on="2024-11-01", known_at="2024-11-01T00:00:00")]
    db, profile = build(tmp_path, {1: quote}, guidance=guidance, sectors={"EPC": "epc_capital_goods"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "quarantined" and "delta_value" in fails, fails


def test_target_frame_medium_term_and_cagr(tmp_path):
    pages = {
        1: "Our medium-term revenue growth target is 20% and we are on track.",
        2: "Our 4-year revenue CAGR will be close to 12% to 12.5%.",
        3: ("Going forward also, we intend to maintain the revenue growth rate at around 14%, which has been "
            "our CAGR for the last 3 to 5 years."),
    }
    guidance = [
        dict(id=1, symbol="CO", metric="revenue_growth", low=20.0, high=20.0, target_period="FY20",
             quote=pages[1], page=1, said_on="2019-08-01", known_at="2019-08-01T00:00:00"),
        dict(id=2, symbol="CO", metric="revenue_growth", low=12.0, high=12.5, target_period="FY24",
             quote=pages[2], page=2, said_on="2023-08-01", known_at="2023-08-01T00:00:00"),
        dict(id=3, symbol="CO", metric="revenue_growth", low=14.0, high=14.0, target_period="FY27",
             quote=pages[3], page=3, said_on="2026-08-01", known_at="2026-08-01T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    for rid in (1, 2):
        status, fails = verdict(out, "guidance", rid)
        assert status == "quarantined" and "target_frame" in fails, (rid, fails)
    # a frame word about the past ("has been our CAGR") is not the target's frame
    assert "target_frame" not in verdict(out, "guidance", 3)[1]


def test_target_year_mismatch_and_comparative(tmp_path):
    pages = {
        1: "To comeback on the CapEx done, the guidance it's approximately 80 to 90 crores for 20-21.",
        2: "Capex guidance of 80 to 90 crores for FY20, as against FY19 capex of 50 crores.",
        3: "• AUM – The Company estimates AUM growth of 22-24%, aided by new businesses launched in last few years.",
    }
    guidance = [
        dict(id=1, symbol="EPC", metric="capex", low=80.0, high=90.0, unit="inr_cr", target_period="FY20",
             quote=pages[1], page=1, said_on="2019-08-01", known_at="2019-08-01T00:00:00"),
        dict(id=2, symbol="EPC", metric="capex", low=80.0, high=90.0, unit="inr_cr", target_period="FY20",
             quote=pages[2], page=2, said_on="2019-08-01", known_at="2019-08-01T00:00:00"),
        dict(id=3, symbol="LENDER", metric="aum_growth", low=22.0, high=24.0, target_period="FY27",
             quote=pages[3], page=3, said_on="2026-08-01", known_at="2026-08-01T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, guidance=guidance,
                        sectors={"EPC": "epc_capital_goods", "LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "quarantined" and "target_year" in fails, fails
    assert "target_year" not in verdict(out, "guidance", 2)[1]
    # "22-24%" is a percentage range, not fiscal years; the period itself is not in the quote, so the row is
    # unpinned (unverified), never quarantined for it
    assert "target_year" not in verdict(out, "guidance", 3)[1]
    assert verdict(out, "guidance", 3)[0] == "unverified"


def test_list_order_ignores_a_delta_number(tmp_path):
    quote = "Cost of funds and opex to NTI improved by 27 basis points, and cost of funds came in at 7.52%."
    kpi = [dict(id=1, symbol="LENDER", metric="cost_of_funds_pct", fiscal_period="Q2FY26", value=7.52,
                quote=quote, page=1)]
    db, profile = build(tmp_path, {1: quote}, kpi=kpi, sectors={"LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    assert "list_order" not in verdict(out, "kpi_series", 1)[1]


def test_third_party_repo_is_a_word_not_a_prefix_of_report(tmp_path):
    quote = ("So, I think on a blended basis certainly while we see margins improving and maybe in the fourth "
             "quarter we should be able to report EBITDA margins North of 20% for FY23, but to give a very "
             "specific number at this stage would be difficult.")
    guidance = [dict(id=1, symbol="CO", metric="ebitda_margin", low=20.0, high=20.0, target_period="FY23",
                     quote=quote, said_on="2023-02-01", known_at="2023-02-01T00:00:00")]
    db, profile = build(tmp_path, {1: quote}, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert "third_party" not in fails, fails
    assert status == "verified", fails


# ------------------------------------------------------------------ the verified bar (not_pinned / scope_word)

def test_sentence_bounds_keeps_an_abbreviation():
    text = rc.fold("Capex will be Rs. 80 crore. Next paragraph.")
    pos = text.index("80")
    lo, hi = rc.sentence_bounds(text, pos)
    assert text[lo:hi].startswith("capex will be rs."), text[lo:hi]
    assert text[lo:hi].endswith("crore"), text[lo:hi]


def test_period_token_reads_a_four_digit_year():
    plain, _ = rc.period_tokens("q3 fy2026", 0)
    assert "q3fy26" in plain, plain
    plain, _ = rc.period_tokens("h1 fy 2026", 0)
    assert "h1fy26" in plain, plain


def test_not_pinned_a_label_beyond_45_chars(tmp_path):
    quote = ("Revenue, as we discussed at length in the previous call and in many meetings, guidance 20% for FY27.")
    guidance = [dict(id=1, symbol="CO", metric="revenue_growth", low=20.0, high=20.0, target_period="FY27",
                     quote=quote, said_on="2026-08-01", known_at="2026-08-01T00:00:00")]
    db, profile = build(tmp_path, {1: quote}, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "unverified" and "not_pinned" in fails, fails


def test_not_pinned_b_scope_word_between_label_and_number(tmp_path):
    quote = "Revenue per store guidance of 12% for FY27."
    guidance = [dict(id=1, symbol="CO", metric="revenue_growth", low=12.0, high=12.0, target_period="FY27",
                     quote=quote, said_on="2026-08-01", known_at="2026-08-01T00:00:00")]
    db, profile = build(tmp_path, {1: quote}, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "unverified" and "not_pinned" in fails, fails


def test_not_pinned_c_forward_word_only_in_another_sentence(tmp_path):
    quote = "Our guidance remains strong. The operating margin is 20% for FY27."
    guidance = [dict(id=1, symbol="CO", metric="ebitda_margin", low=20.0, high=20.0, target_period="FY27",
                     quote=quote, said_on="2026-08-01", known_at="2026-08-01T00:00:00")]
    db, profile = build(tmp_path, {1: quote}, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "unverified" and "not_pinned" in fails, fails
    assert "forward_word" not in fails, fails


def test_not_pinned_d_period_stated_or_year_phrase(tmp_path):
    pages = {
        1: "Our operating margin guidance is 20% to 22%.",
        2: "Our operating margin guidance for FY27 is 20% to 22%.",
    }
    guidance = [
        dict(id=1, symbol="CO", metric="ebitda_margin", low=20.0, high=22.0, target_period="FY27",
             quote=pages[1], page=1, said_on="2026-08-01", known_at="2026-08-01T00:00:00"),
        dict(id=2, symbol="CO", metric="ebitda_margin", low=20.0, high=22.0, target_period="FY27",
             quote=pages[2], page=2, said_on="2026-08-01", known_at="2026-08-01T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "unverified" and "not_pinned" in fails, fails
    assert verdict(out, "guidance", 2)[0] == "verified"


def test_not_pinned_e_reported_actual_governing_the_number(tmp_path):
    quote = "EBITDA margin guidance was 20% for FY27."
    guidance = [dict(id=1, symbol="CO", metric="ebitda_margin", low=20.0, high=20.0, target_period="FY27",
                     quote=quote, said_on="2026-08-01", known_at="2026-08-01T00:00:00")]
    db, profile = build(tmp_path, {1: quote}, guidance=guidance, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    # a past-tense verb governing the number is a hard past_figure
    assert status == "quarantined" and "past_figure" in fails, fails


def test_kpi_scope_word_is_soft_and_per_unit_is_exempt(tmp_path):
    pages = {
        1: "Revenue per store was 500 crore",
        2: "EBITDA per tonne guidance was 1,500",
    }
    kpi = [
        dict(id=1, symbol="LENDER", metric="revenue", fiscal_period="Q1FY26", value=500.0, unit="inr_cr",
             scale=1e7, quote=pages[1], page=1, known_at="2025-08-01T00:00:00"),
        dict(id=2, symbol="METAL", metric="ebitda_per_tonne", fiscal_period="FY26", period_type="FY",
             value=1500.0, unit="usd_per_tonne", quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        sectors={"LENDER": "nbfc", "METAL": "metals_nonferrous"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "scope_word" in fails, fails
    assert "scope_word" not in verdict(out, "kpi_series", 2)[1]


# --------------------------------------------------------------------- round 5: KPI wrong classes

def test_multi_number_counts_unit_values_for_any_rule(tmp_path):
    pages = {
        1: "EBITDA Margin (%) 10.3% 10.2% 10.0% +15bps +35bps 10.9% 10.3%",
        2: "EBITDA margin was 10.3% as against 10.2% last year",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="ebitda_margin_pct", dimension="total", fiscal_period="9MFY24",
             period_type="9M", value=10.3, quote=pages[1], page=1, extractor_rule="sentence_v1"),
        dict(id=2, symbol="CO", metric="ebitda_margin_pct", dimension="total", fiscal_period="FY24",
             period_type="FY", value=10.3, quote=pages[2], page=2, extractor_rule="sentence_v1"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "multi_number" in fails, fails
    assert "multi_number" not in verdict(out, "kpi_series", 2)[1]


def test_not_company_speaker_and_a_range_end_are_not_levels(tmp_path):
    pages = {
        1: "I wanted to understand the order inflow of 5 to 6,000 Crores.",
        2: "Can you quantify the order inflow of 5,000 crore?",
        3: "The company secured an order inflow of 5,000 crore in Q1.",
        4: "Analyst: how is the order inflow looking? The order inflow was 5,000 crore in Q1.",
    }
    kpi = [
        dict(id=1, symbol="EPC", metric="order_intake", fiscal_period="Q1FY26", value=6000.0, unit="inr_cr",
             scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="EPC", metric="order_intake", fiscal_period="Q1FY26", value=5000.0, unit="inr_cr",
             scale=1e7, quote=pages[2], page=2),
        dict(id=3, symbol="EPC", metric="order_intake", fiscal_period="Q1FY26", value=5000.0, unit="inr_cr",
             scale=1e7, quote=pages[3], page=3),
        dict(id=4, symbol="EPC", metric="order_intake", fiscal_period="Q1FY26", value=5000.0, unit="inr_cr",
             scale=1e7, quote="The order inflow was 5,000 crore in Q1.", page=4),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"EPC": "epc_capital_goods"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "not_company_speaker" in fails and "range_value" in fails, fails
    status, fails = verdict(out, "kpi_series", 2)
    assert status == "quarantined" and "not_company_speaker" in fails, fails
    fails = verdict(out, "kpi_series", 3)[1]
    assert "not_company_speaker" not in fails and "range_value" not in fails, fails
    # the page marks the speaker as an analyst just before the quote
    assert "not_company_speaker" in verdict(out, "kpi_series", 4)[1]


def test_uncorroborated_total_amounts(tmp_path):
    pages = {1: "Revenues 500", 2: "Revenues 500", 3: "Order intake of 1,000 crore"}
    kpi = [
        dict(id=1, symbol="CO", metric="revenue", fiscal_period="FY26", period_type="FY", value=500.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="BANK", metric="revenue", fiscal_period="FY26", period_type="FY", value=500.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2),
        dict(id=3, symbol="BANK", metric="order_intake", fiscal_period="FY26", period_type="FY", value=1000.0,
             unit="inr_cr", scale=1e7, quote=pages[3], page=3),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        fin_a=[dict(symbol="BANK", fiscal_year="FY26", line_item="revenue_from_operations",
                                    value=500.0, scale=1e7)],
                        sectors={"CO": "it_services", "BANK": "bank"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "uncorroborated" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] == "verified"
    # orders have no filed statement, so a total order row always needs a second source
    assert "uncorroborated" in verdict(out, "kpi_series", 3)[1]


def test_unit_kind_days_and_percent(tmp_path):
    pages = {
        1: "Net working capital 1,198 671",
        2: "EBITDA margin at 23.1",
        3: "EBITDA margin at 23.1%",
        4: "Annualised loan loss 2.05",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="working_capital_days", fiscal_period="FY26", period_type="FY",
             value=1198.0, unit="days", quote=pages[1], page=1),
        dict(id=2, symbol="CO", metric="ebitda_margin_pct", fiscal_period="FY26", period_type="FY",
             value=23.1, unit="pct", quote=pages[2], page=2),
        dict(id=3, symbol="CO", metric="ebitda_margin_pct", fiscal_period="FY26", period_type="FY",
             value=23.1, unit="pct", quote=pages[3], page=3),
        dict(id=4, symbol="LENDER", metric="credit_cost_bps", fiscal_period="FY26", period_type="FY",
             value=205.0, unit="bps", quote=pages[4], page=4),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services", "LENDER": "nbfc"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "unit_kind" in fails, fails
    # a label naming the ratio ("EBITDA margin at 23.1") is the unit context
    assert "unit_kind" not in verdict(out, "kpi_series", 2)[1]
    assert "unit_kind" not in verdict(out, "kpi_series", 3)[1]
    # a bare loan-loss number has no percent context at all
    status, fails = verdict(out, "kpi_series", 4)
    assert status == "quarantined" and "unit_kind" in fails, fails


def test_guidance_past_verb_and_nearer_foreign_label(tmp_path):
    pages = {
        1: "Increased sales investment by 21% YoY in FY20.",
        2: ("This coming 2020-2021 we expect around 50 Crores of revenue with say around 20% of EBITDA "
            "margins in this year."),
        3: "We are on track to reach the 50% revenue threshold that we have set.",
    }
    guidance = [
        dict(id=1, symbol="IT", metric="revenue_growth", low=21.0, high=21.0, target_period="FY20",
             quote=pages[1], page=1, said_on="2020-02-01", known_at="2020-02-01T00:00:00"),
        dict(id=2, symbol="IT", metric="revenue_growth", low=20.0, high=20.0, target_period="FY21",
             quote=pages[2], page=2, said_on="2020-08-01", known_at="2020-08-01T00:00:00"),
        dict(id=3, symbol="IT", metric="revenue_growth", low=50.0, high=50.0, target_period="FY21",
             quote=pages[3], page=3, said_on="2020-08-01", known_at="2020-08-01T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, guidance=guidance, sectors={"IT": "it_services"})
    out = run_checks(tmp_path, db, profile, ("guidance",))
    status, fails = verdict(out, "guidance", 1)
    assert status == "quarantined" and "past_figure" in fails, fails
    status, fails = verdict(out, "guidance", 2)
    assert status == "quarantined" and "label_conflict" in fails, fails
    # a "revenue threshold" is a share, so the row is unpinned (soft), not verified
    status, fails = verdict(out, "guidance", 3)
    assert status == "unverified" and "not_pinned" in fails, fails


# --------------------------------------------------- round 6: independent corroboration, speaker structure

def add_doc(db: str, doc_key: str, pages: dict[int, str]) -> None:
    """Attach one more transcript document to a fixture database."""
    con = sqlite3.connect(db)
    con.execute("INSERT INTO doc(doc_key,symbol,isin,doc_type,doc_family,title,filing_date,known_at,pages) "
                "VALUES (?, '', NULL, 'transcript', 'transcript', 'test doc', '2026-05-01', "
                "'2026-05-01T00:00:00', ?)", (doc_key, len(pages)))
    con.executemany("INSERT INTO doc_page(doc_key,symbol,page,text) VALUES (?, '', ?, ?)",
                    [(doc_key, page, text) for page, text in pages.items()])
    con.commit()
    con.close()


MULTI_A = "EBITDA Margin (%) 10.3% 10.2% 10.0%"
MULTI_B = "EBITDA Margin (%) 10.3% 11.0% 9.6%"
SINGLE_C = "EBITDA margin of 10.3% for 9M FY24"


def test_multi_number_rows_do_not_corroborate_each_other(tmp_path):
    kpi = [
        dict(id=1, symbol="CO", metric="ebitda_margin_pct", dimension="total", fiscal_period="9MFY24",
             period_type="9M", value=10.3, quote=MULTI_A, page=1, extractor_rule="sentence_v1"),
        dict(id=2, symbol="CO", metric="ebitda_margin_pct", dimension="total", fiscal_period="9MFY24",
             period_type="9M", value=10.3, quote=MULTI_B, page=1, doc_key="d2",
             extractor_rule="sentence_v1"),
    ]
    db, profile = build(tmp_path, {1: MULTI_A}, kpi=kpi, sectors={"CO": "it_services"},
                        db_name="corr1.db")
    add_doc(db, "d2", {1: MULTI_B})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2):
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "multi_number" in fails, (rid, fails)

    # a single-valued source quote is an independent witness, so the multi-column row can verify
    kpi.append(dict(id=3, symbol="CO", metric="ebitda_margin_pct", dimension="total", fiscal_period="9MFY24",
                    period_type="9M", value=10.3, quote=SINGLE_C, page=1, doc_key="d3",
                    extractor_rule="sentence_v1"))
    db2, profile2 = build(tmp_path, {1: MULTI_A}, kpi=kpi, sectors={"CO": "it_services"},
                          db_name="corr2.db")
    add_doc(db2, "d2", {1: MULTI_B})
    add_doc(db2, "d3", {1: SINGLE_C})
    out2 = run_checks(tmp_path, db2, profile2, ("kpi_series",))
    status, fails = verdict(out2, "kpi_series", 1)
    assert status == "verified" and "multi_number" in fails, fails


def test_analyst_turn_by_speaker_structure(tmp_path):
    mgmt = "Management:\nMr. Sanjay Mehta - Managing Director\nMr. Rakesh Sharma - Chief Financial Officer\n"
    transcript = (
        "Sanjay Mehta: Good morning. Our net cash balance is INR 200 crore.\n"
        "Vaibhav Shah: The net cash balance has also come down to INR 200-odd crores.\n"
        "Sanjay Mehta: We will explain that.\n"
        "Analyst: What is the order inflow?\n"
        "Vimal Kejriwal: The order inflow was INR 3,000 crore.\n"
        "I just wanted to check the order inflow of INR 4,000 crore.\n"
    )
    pages = {1: mgmt, 2: transcript}
    kpi = [
        dict(id=1, symbol="CO", metric="cash_balance", fiscal_period="Q1FY26", value=200.0, unit="inr_cr",
             scale=1e7, quote="The net cash balance has also come down to INR 200-odd crores.", page=2),
        dict(id=2, symbol="CO", metric="cash_balance", fiscal_period="Q2FY26", value=200.0, unit="inr_cr",
             scale=1e7, quote="Our net cash balance is INR 200 crore", page=2),
        dict(id=3, symbol="CO", metric="order_intake", fiscal_period="Q1FY26", value=3000.0, unit="inr_cr",
             scale=1e7, quote="The order inflow was INR 3,000 crore", page=2),
        dict(id=4, symbol="CO", metric="order_intake", fiscal_period="Q2FY26", value=4000.0, unit="inr_cr",
             scale=1e7, quote="I just wanted to check the order inflow of INR 4,000 crore.", page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "not_company_speaker" in fails, fails
    assert "not_company_speaker" not in verdict(out, "kpi_series", 2)[1]
    assert "not_company_speaker" not in verdict(out, "kpi_series", 3)[1]
    # the new analyst wording is caught even without a speaker line
    assert "not_company_speaker" in verdict(out, "kpi_series", 4)[1]


# ------------------------------------------ round 7: disagreement, witness validity, history, scale

def test_cross_doc_disagreement_unverifies_both(tmp_path):
    kpi = [
        dict(id=1, symbol="KALY", metric="revenue", dimension="total", fiscal_period="Q4FY23", value=33818.0,
             unit="inr_mn", quote="Revenue from operations 33,818", page=1),
        dict(id=2, symbol="KALY", metric="revenue", dimension="total", fiscal_period="Q4FY23", value=5486.0,
             unit="inr_mn", quote="Revenue from operations 5,486", page=1, doc_key="d2"),
    ]
    db, profile = build(tmp_path, {1: "Revenue from operations 33,818"}, kpi=kpi,
                        sectors={"KALY": "fmcg"})
    add_doc(db, "d2", {1: "Revenue from operations 5,486"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2):
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "cross_doc" in fails, (rid, fails)


def test_a_witness_must_pass_its_own_hard_checks(tmp_path):
    pages = {
        1: "Profit After Tax 72.0 134.7 -47% 34.2",
        2: "Profit After Tax of 34.2 crore in Q3 FY23",
    }
    kpi = [
        dict(id=1, symbol="ASHOKA", metric="pat", dimension="total", fiscal_period="Q4FY23", value=34.2,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        # same key and value, single-valued, but its own quote names the previous quarter: not a witness
        dict(id=2, symbol="ASHOKA", metric="pat", dimension="total", fiscal_period="Q4FY23", value=34.2,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2, doc_key="d2"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"ASHOKA": "epc_capital_goods"})
    add_doc(db, "d2", {2: pages[2]})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    assert verdict(out, "kpi_series", 1)[0] == "unverified"
    status, fails = verdict(out, "kpi_series", 2)
    assert status == "quarantined" and "period_word" in fails, fails


def test_a_history_row_only_verifies_on_a_filed_figure(tmp_path):
    pages = {
        1: "ROE 7% 8% 9% 10% 8% 7% 8% 15% 16% 6%",
        2: "ROE of 6% in Q3 FY24",
    }
    kpi = [
        dict(id=1, symbol="UFLEX", metric="roe_pct", dimension="total", fiscal_period="Q3FY24", value=6.0,
             quote=pages[1], page=1),
        dict(id=2, symbol="UFLEX", metric="roe_pct", dimension="total", fiscal_period="Q3FY24", value=6.0,
             quote=pages[2], page=2, doc_key="d2"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"UFLEX": "packaging"})
    add_doc(db, "d2", {2: pages[2]})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "history_row" in fails, fails
    # the single-valued witness is valid, but a history row is not verifiable from witnesses at all
    assert "cross_doc" not in fails, fails


def test_scale_doubt_below_ten_and_the_filed_exemption(tmp_path):
    pages = {1: "Capital Expenditure (CAPEX) ` 2.2", 2: "Capital Expenditure (CAPEX) Rs 25 crore",
             3: "Revenue from operations Rs 2.2 crore"}
    kpi = [
        dict(id=1, symbol="ALK", metric="capex", dimension="total", fiscal_period="FY23", period_type="FY",
             value=2.2, unit="inr_mn", quote=pages[1], page=1),
        dict(id=2, symbol="ALK", metric="capex", dimension="total", fiscal_period="FY23", period_type="FY",
             value=25.0, unit="inr_cr", scale=1e7, quote=pages[2], page=2),
        dict(id=3, symbol="CO", metric="revenue", dimension="total", fiscal_period="FY23", period_type="FY",
             value=2.2, unit="inr_cr", scale=1e7, quote=pages[3], page=3),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        fin_a=[dict(symbol="CO", fiscal_year="FY23", line_item="revenue_from_operations",
                                    value=2.2, scale=1e7)],
                        sectors={"ALK": "pharma", "CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "scale_doubt" in fails, fails
    assert "scale_doubt" not in verdict(out, "kpi_series", 2)[1]
    # the same doubt is cleared by a matching filed figure
    status, fails = verdict(out, "kpi_series", 3)
    assert status == "verified" and "scale_doubt" in fails, fails


# -------------------------------------- round 8: sign, cumulative words, same-doc conflicts, page unit

def test_net_cash_sign_both_ways(tmp_path):
    pages = {
        1: "We strengthened our balance sheet with strong net cash position of ₹ 19 bn.",
        2: "Net debt of ₹ 1,200 crore in Q3 FY24.",
        3: "Our net cash of INR 200 crore.",
        4: "Net debt of ₹ 500 crore.",
        5: "Net debt of (500) crore.",
        6: "Net debt of minus INR 500 crore.",
    }
    kpi = [
        dict(id=1, symbol="ALKEM", metric="net_debt", fiscal_period="9MFY23", period_type="9M", value=19.0,
             unit="inr_bn", scale=1e9, quote=pages[1], page=1, known_at="2023-02-10T00:00:00"),
        dict(id=2, symbol="ALKEM", metric="net_debt", fiscal_period="Q3FY24", value=1200.0, unit="inr_cr",
             scale=1e7, quote=pages[2], page=2, known_at="2024-02-01T00:00:00"),
        dict(id=3, symbol="ALKEM", metric="net_debt", fiscal_period="Q3FY24", value=-200.0, unit="inr_cr",
             scale=1e7, quote=pages[3], page=3, known_at="2024-02-01T00:00:00"),
        dict(id=4, symbol="ALKEM", metric="net_debt", fiscal_period="Q3FY24", value=-500.0, unit="inr_cr",
             scale=1e7, quote=pages[4], page=4, known_at="2024-02-01T00:00:00"),
        dict(id=5, symbol="ALKEM", metric="net_debt", fiscal_period="Q3FY24", value=-500.0, unit="inr_cr",
             scale=1e7, quote=pages[5], page=5, known_at="2024-02-01T00:00:00"),
        dict(id=6, symbol="ALKEM", metric="net_debt", fiscal_period="Q3FY24", value=-500.0, unit="inr_cr",
             scale=1e7, quote=pages[6], page=6, known_at="2024-02-01T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"ALKEM": "pharma"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "net_cash_sign" in fails, fails
    # net debt stored positive, and net cash stored negative, are the right signs
    assert "net_cash_sign" not in verdict(out, "kpi_series", 2)[1]
    assert "net_cash_sign" not in verdict(out, "kpi_series", 3)[1]
    # a negative net debt is wrong unless the quote prints the minus / bracket / the word minus
    status, fails = verdict(out, "kpi_series", 4)
    assert status == "quarantined" and "net_cash_sign" in fails, fails
    assert "net_cash_sign" not in verdict(out, "kpi_series", 5)[1]
    assert "net_cash_sign" not in verdict(out, "kpi_series", 6)[1]


def test_period_word_cumulative_phrases_conflict_with_a_quarter(tmp_path):
    pages = {
        1: ("capex for up-to-date was around INR79 crores and maybe the pending capex would be approximately "
            "INR15-odd crores for March '24"),
        2: "capex for the quarter was INR 79 crores.",
        3: "Cumulative revenue was 500 crore.",
    }
    kpi = [
        dict(id=1, symbol="ASHOKA", metric="capex", fiscal_period="Q2FY24", value=79.0, unit="inr_cr",
             scale=1e7, quote=pages[1], page=1, known_at="2023-11-13T00:00:00"),
        dict(id=2, symbol="ASHOKA", metric="capex", fiscal_period="Q2FY24", value=79.0, unit="inr_cr",
             scale=1e7, quote=pages[2], page=2, known_at="2023-11-13T00:00:00"),
        dict(id=3, symbol="ASHOKA", metric="revenue", fiscal_period="Q2FY24", value=500.0, unit="inr_cr",
             scale=1e7, quote=pages[3], page=3, known_at="2023-11-13T00:00:00"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"ASHOKA": "epc_capital_goods"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "period_word" in fails, fails
    assert "period_word" not in verdict(out, "kpi_series", 2)[1]
    status, fails = verdict(out, "kpi_series", 3)
    assert status == "quarantined" and "period_word" in fails, fails


def test_analyst_question_starting_on_the_previous_page(tmp_path):
    page1 = ("Management:\nMr. Anand Athreya - Chief Executive Officer\n"
             "Mr. Sumit Dhingra - Chief Financial Officer\n"
             "Sangam Iyer: Sorry to harp on the working capital again. Just want to understand that first.\n")
    page2 = ("our cash -- net cash balance has also come down to INR200-odd crores. So that's why I was "
             "just trying to understand how to look at the incremental cash flow\n"
             "Sumit Dhingra: It is related to the revenue that got shipped during the quarter.\n")
    kpi = [dict(id=1, symbol="TEJAS", metric="net_debt", fiscal_period="Q3FY24", value=-200.0, unit="inr_cr",
                scale=1e7, page=2, known_at="2024-01-25T00:00:00",
                quote="net cash balance has also come down to INR200-odd crores. So that's why I was just "
                      "trying to understand how")]
    db, profile = build(tmp_path, {1: page1, 2: page2}, kpi=kpi, sectors={"TEJAS": "telecom"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "not_company_speaker" in fails, fails
    assert "net_cash_sign" not in fails, fails


def test_a_prose_line_is_not_a_speaker_label(tmp_path):
    assert rc.plausible_speaker("Sangam Iyer")
    assert rc.plausible_speaker("Moderator")
    assert not rc.plausible_speaker("Coming to the order book status")
    assert not rc.plausible_speaker("Some of the key highlights include")
    assert not rc.plausible_speaker("FIVE")
    # the previous page carries a prose line after the real speaker: the turn is still the company's
    page1 = ("Management:\nMr. Anand Athreya - Chief Executive Officer\n"
             "Anand Athreya: Good morning. Our commentary follows.\n"
             "Coming to the order book status - the order book is set out below.\n")
    page2 = "order book as on 31st March 2023 is INR 15,805 crores."
    kpi = [dict(id=1, symbol="ASHOKA", metric="order_book", fiscal_period="FY23", period_type="FY",
                value=15805.0, unit="inr_cr", scale=1e7, quote=page2, page=2)]
    db, profile = build(tmp_path, {1: page1, 2: page2}, kpi=kpi, sectors={"ASHOKA": "epc_capital_goods"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    assert "not_company_speaker" not in verdict(out, "kpi_series", 1)[1]


def test_cumulative_words_after_the_number_do_not_count(tmp_path):
    page = ("EBITDA per tonne $525 - Demand for aluminum products remains resilient - Over $225 million in "
            "run-rate cost savings achieved to date under global efficiency program")
    kpi = [dict(id=1, symbol="HINDALCO", metric="ebitda_per_tonne", fiscal_period="Q1FY27", value=525.0,
                unit="usd_per_tonne", quote=page, page=1)]
    db, profile = build(tmp_path, {1: page}, kpi=kpi, sectors={"HINDALCO": "metals_nonferrous"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    assert "period_word" not in verdict(out, "kpi_series", 1)[1]


def test_question_next_is_soft_when_the_speaker_is_not_found(tmp_path):
    pages = {
        1: "Management:\nMr. Anand Athreya - Chief Executive Officer\n",
        2: "Some unrelated preamble text without any speaker line.",
        3: "Our order inflow was INR 5,000 crore. Could you tell us how that splits?",
    }
    kpi = [dict(id=1, symbol="EPC", metric="order_intake", fiscal_period="Q1FY26", value=5000.0,
                unit="inr_cr", scale=1e7, page=3,
                quote="Our order inflow was INR 5,000 crore. Could you tell us how that splits?")]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"EPC": "epc_capital_goods"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "question_next" in fails, fails


def test_same_document_conflict_is_soft(tmp_path):
    pages = {
        1: "Revenue from operations 100", 2: "Revenue from operations 100.5",
        3: "Revenue from operations 100", 4: "Revenue from operations 140",
        5: "EBITDA 100", 6: "Adjusted EBITDA 140",
    }
    kpi = [
        dict(id=1, symbol="A", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=100.0, unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="A", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=100.5, unit="inr_cr", scale=1e7, quote=pages[2], page=2),
        dict(id=3, symbol="B", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=100.0, unit="inr_cr", scale=1e7, quote=pages[3], page=3),
        dict(id=4, symbol="B", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=140.0, unit="inr_cr", scale=1e7, quote=pages[4], page=4),
        dict(id=5, symbol="C", metric="ebitda", dimension="total", fiscal_period="FY26", period_type="FY",
             value=100.0, unit="inr_cr", scale=1e7, quote=pages[5], page=5),
        dict(id=6, symbol="C", metric="ebitda", dimension="total", fiscal_period="FY26", period_type="FY",
             value=140.0, unit="inr_cr", scale=1e7, quote=pages[6], page=6),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        sectors={"A": "it_services", "B": "it_services", "C": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2):
        assert "same_doc_conflict" not in verdict(out, "kpi_series", rid)[1]
    for rid in (3, 4):
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "same_doc_conflict" in fails, (rid, fails)
    # one row is a variant of the line: the pair is not a conflict
    assert "variant" in verdict(out, "kpi_series", 6)[1]
    assert "same_doc_conflict" not in verdict(out, "kpi_series", 5)[1]
    assert "same_doc_conflict" not in verdict(out, "kpi_series", 6)[1]


def test_a_zero_filed_figure_is_not_a_witness(tmp_path):
    pages = {1: "Revenue from operations 500 crore in Q1 FY26"}
    kpi = [dict(id=1, symbol="CO", metric="revenue", dimension="total", fiscal_period="Q1FY26", value=500.0,
                unit="inr_cr", scale=1e7, quote=pages[1], page=1, known_at="2025-08-01T00:00:00")]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        fin_q=[dict(symbol="CO", fiscal_period="Q1FY26", line_item="revenue_from_operations",
                                    value=0.0, scale=1e7)],
                        sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "fin_conflict" not in fails and "uncorroborated" in fails, fails


def test_page_unit_declaration_conflicts_with_the_row_unit(tmp_path):
    pages = {
        1: "All amounts are in million of Indian Rupees\nRevenue 500",
        2: "(Rs. in Mn)\nRevenue 600",
        3: "(in Crores)\nRevenue 700",
        4: "All amounts are in crore\nRevenue 800",
        5: "(Rs. in Mn)\nRevenue 900 crore",
        6: "All amounts are in ₹ crore\nRevenues 19,277",
    }
    kpi = [
        dict(id=1, symbol="A", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=500.0, unit="inr_cr", scale=1e7, quote="Revenue 500", page=1),
        dict(id=2, symbol="B", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=600.0, unit="inr_mn", scale=1e6, quote="Revenue 600", page=2),
        dict(id=3, symbol="C", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=700.0, unit="inr_mn", scale=1e6, quote="Revenue 700", page=3),
        dict(id=4, symbol="D", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=800.0, unit="inr_cr", scale=1e7, quote="Revenue 800", page=4),
        dict(id=5, symbol="E", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
             value=900.0, unit="inr_cr", scale=1e7, quote="Revenue 900 crore", page=5),
        # a rupee page declaration does not judge a dollar row printed on the same page
        dict(id=6, symbol="F", metric="revenue_usd", dimension="total", fiscal_period="FY26", period_type="FY",
             value=19277.0, unit="usd_mn", scale=1e6, quote="Revenues 19,277", page=6),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        sectors={s: "it_services" for s in "ABCDEF"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "page_unit" in fails, fails
    assert "page_unit" not in verdict(out, "kpi_series", 2)[1]
    status, fails = verdict(out, "kpi_series", 3)
    assert status == "quarantined" and "page_unit" in fails, fails
    assert "page_unit" not in verdict(out, "kpi_series", 4)[1]
    # the quote's own unit word wins over the page header
    assert "page_unit" not in verdict(out, "kpi_series", 5)[1]
    assert "page_unit" not in verdict(out, "kpi_series", 6)[1]


def test_variant_words_extend_to_debt_and_margins(tmp_path):
    pages = {
        1: "Adjusted Net Debt 500",
        2: "EBITDA margin excluding other income 20%",
        3: "EBITDA pre Ind AS & excl. other income 100",
        4: "Revenue as per contracted price 100",
    }
    kpi = [
        dict(id=1, symbol="A", metric="net_debt", fiscal_period="FY26", period_type="FY", value=500.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="B", metric="ebitda_margin_pct", fiscal_period="FY26", period_type="FY", value=20.0,
             unit="pct", quote=pages[2], page=2),
        dict(id=3, symbol="C", metric="ebitda", fiscal_period="FY26", period_type="FY", value=100.0,
             unit="inr_cr", scale=1e7, quote=pages[3], page=3),
        dict(id=4, symbol="D", metric="revenue", fiscal_period="FY26", period_type="FY", value=100.0,
             unit="inr_cr", scale=1e7, quote=pages[4], page=4),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        sectors={"A": "it_services", "B": "it_services", "C": "it_services",
                                 "D": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2, 3):
        status, fails = verdict(out, "kpi_series", rid)
        assert "variant" in fails and status != "quarantined", (rid, status, fails)
    # the foreign label sits inside the qualifier phrase: variant, not a hard label_conflict
    assert "label_conflict" not in verdict(out, "kpi_series", 3)[1]
    # "as per" is not a per-unit variant
    assert "variant" not in verdict(out, "kpi_series", 4)[1]


def test_bare_leverage_is_not_a_debt_ratio_label(tmp_path):
    pages = {1: "Operating leverage of 2.1x", 2: "Net debt to EBITDA of 2.1x"}
    kpi = [
        dict(id=1, symbol="A", metric="net_debt_to_ebitda", fiscal_period="FY26", period_type="FY", value=2.1,
             unit="multiple", quote=pages[1], page=1),
        dict(id=2, symbol="B", metric="net_debt_to_ebitda", fiscal_period="FY26", period_type="FY", value=2.1,
             unit="multiple", quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        sectors={"A": "it_services", "B": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status != "verified" and "label_weak" in fails, (status, fails)
    assert "label_weak" not in verdict(out, "kpi_series", 2)[1]


# ------------------------------------------- round 9: corroboration is not a label, glued qualifiers, filed scale

def test_corroboration_does_not_verify_a_weak_label_or_a_variant(tmp_path):
    pages = {1: "Leverage ratio 4.7"}
    kpi = [
        dict(id=1, symbol="A", metric="net_debt_to_ebitda", fiscal_period="FY26", period_type="FY", value=4.7,
             unit="multiple", quote=pages[1], page=1),
        dict(id=2, symbol="A", metric="net_debt_to_ebitda", fiscal_period="FY26", period_type="FY", value=4.7,
             unit="multiple", quote="Leverage ratio of 4.7x", page=1, doc_key="d2"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"A": "it_services"})
    add_doc(db, "d2", {1: "Leverage ratio of 4.7x"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2):
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "label_weak" in fails, (rid, status, fails)

    pages2 = {1: "Adjusted profit after tax 100 crore"}
    kpi2 = [
        dict(id=1, symbol="B", metric="pat", dimension="total", fiscal_period="FY26", period_type="FY",
             value=100.0, unit="inr_cr", scale=1e7, quote=pages2[1], page=1),
        dict(id=2, symbol="B", metric="pat", dimension="total", fiscal_period="FY26", period_type="FY",
             value=100.0, unit="inr_cr", scale=1e7, quote="Profit after tax (adjusted) 100 crore", page=1,
             doc_key="d2"),
    ]
    db, profile = build(tmp_path, pages2, kpi=kpi2,
                        fin_a=[dict(symbol="B", fiscal_year="FY26", line_item="pat", value=100.0, scale=1e7)],
                        sectors={"B": "it_services"}, db_name="variant_corr.db")
    add_doc(db, "d2", {1: "Profit after tax (adjusted) 100 crore"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2):
        status, fails = verdict(out, "kpi_series", rid)
        assert status == "unverified" and "variant" in fails, (rid, status, fails)


def test_variant_qualifier_glued_to_digits_or_hyphens(tmp_path):
    pages = {
        1: "EBITDA margin (pre IndAS116) at 19.7%",
        2: "EBITDA margin post IndAS116 at 21.2%",
        3: "EBITDA margin (ex-IndAS) at 18.4%",
        4: "EBITDA margin pre IND-AS at 17.1%",
    }
    kpi = [dict(id=i + 1, symbol="CO", metric="ebitda_margin_pct", fiscal_period="FY26", period_type="FY",
                value=value, unit="pct", quote=pages[i + 1], page=i + 1)
           for i, value in enumerate((19.7, 21.2, 18.4, 17.1))]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    for rid in (1, 2, 3, 4):
        status, fails = verdict(out, "kpi_series", rid)
        assert "variant" in fails and status != "quarantined", (rid, status, fails)


def test_a_filed_unit_that_names_a_scale_is_applied(tmp_path):
    pages = {1: "Revenue from operations 100 crore"}
    kpi = [dict(id=1, symbol="CO", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
                value=100.0, unit="inr_cr", scale=1e7, quote=pages[1], page=1)]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        fin_a=[dict(symbol="CO", fiscal_year="FY26", line_item="revenue_from_operations",
                                    value=1000.0, unit="rs mn", scale=1.0)],
                        sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "verified" and "fin_conflict" not in fails, fails


def test_a_sub_crore_filed_value_does_not_witness(tmp_path):
    pages = {1: "Revenue from operations 500 crore"}
    kpi = [dict(id=1, symbol="CO", metric="revenue", dimension="total", fiscal_period="FY26", period_type="FY",
                value=500.0, unit="inr_cr", scale=1e7, quote=pages[1], page=1)]
    db, profile = build(tmp_path, pages, kpi=kpi,
                        fin_a=[dict(symbol="CO", fiscal_year="FY25", line_item="revenue_from_operations",
                                    value=5000.0, unit="inr", scale=1e7),
                               dict(symbol="CO", fiscal_year="FY26", line_item="revenue_from_operations",
                                    value=5.0, unit="inr", scale=1.0)],
                        sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "fin_conflict" not in fails and "uncorroborated" in fails, fails


# ------------------------------------------------------------- round 10: verified needs a second source
# Six general wrong classes from a hidden read of unseen companies, plus the structural rule that a kpi row
# with no independent second source is not `verified`.  Every sentence is invented to the class's shape.

def test_an_uncorroborated_kpi_row_is_single_source(tmp_path):
    pages = {1: "EBITDA margin was 12.5% in Q2 FY26 on lower employee costs.",
            2: "EBITDA margin was 12.5% in Q2 FY26 on lower employee costs."}
    kpi = [
        dict(id=1, symbol="CO", metric="ebitda_margin_pct", dimension="total", fiscal_period="Q2FY26",
             value=12.5, unit="pct", quote=pages[1], page=1),
        # a tagged segment line IS the filing: no quote, no second source needed
        dict(id=2, symbol="CO", metric="revenue", dimension="total", fiscal_period="Q2FY26", value=500.0,
             unit="inr_cr", scale=1e7, quote="", page=2, extractor_rule="xbrl_segment"),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "single_source" in fails, fails
    assert verdict(out, "kpi_series", 2)[0] == "verified"


def test_a_footnote_notes_amount_is_not_the_metric(tmp_path):
    pages = {
        1: "Net Debt *Includes investments in liquid funds and FDs of INR 3,165 crores",
        2: "Gross debt was INR 3,165 crores.* (*Includes investments in liquid funds and FDs)",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="gross_debt", dimension="total", fiscal_period="Q2FY26", value=3165.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="CO", metric="gross_debt", dimension="total", fiscal_period="Q2FY26", value=3165.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "power_utility"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "footnote_note" in fails, fails
    status, fails = verdict(out, "kpi_series", 2)
    assert status != "quarantined" and "footnote_note" not in fails, fails


def test_a_rating_agencys_projection_is_not_the_company_actual(tmp_path):
    pages = {
        1: "Rating rationale: the company's net debt to EBITDA is estimated at 1.1 times in fiscal 2026 "
           "and is expected to remain stable.",
        2: "Net debt to EBITDA was 1.1 times in Q2 FY26 and we expect it to remain stable.",
        3: "Net debt to EBITDA stood at 1.1 times in fiscal 2025, on a constant-currency basis.",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="net_debt_to_ebitda", dimension="total", fiscal_period="Q2FY26",
             value=1.1, unit="x", quote=pages[1], page=1),
        dict(id=2, symbol="CO", metric="net_debt_to_ebitda", dimension="total", fiscal_period="Q2FY26",
             value=1.1, unit="x", quote=pages[2], page=2),
        # a past-year row whose number is followed by a later fiscal year: a projection, not the level
        dict(id=3, symbol="CO", metric="net_debt_to_ebitda", dimension="total", fiscal_period="FY24",
             value=1.1, unit="x", quote=pages[3], page=3),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "projection" in fails, fails
    fails = verdict(out, "kpi_series", 2)[1]
    assert "projection" not in fails, fails
    fails = verdict(out, "kpi_series", 3)[1]
    assert "projection" in fails, fails


def test_a_regulators_allowed_rate_is_not_the_company_ratio(tmp_path):
    pages = {
        1: "The tariff allows a return on equity of 15.5% for the control period.",
        2: "Our return on equity improved to 15.5% in Q2 FY26 on higher margins.",
    }
    kpi = [
        dict(id=1, symbol="UTIL", metric="roe_pct", dimension="total", fiscal_period="Q2FY26", value=15.5,
             unit="pct", quote=pages[1], page=1),
        dict(id=2, symbol="UTIL", metric="roe_pct", dimension="total", fiscal_period="Q2FY26", value=15.5,
             unit="pct", quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"UTIL": "power_utility"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "regulated_rate" in fails, fails
    status, fails = verdict(out, "kpi_series", 2)
    assert status != "quarantined" and "regulated_rate" not in fails, fails


def test_a_vertical_named_in_a_total_rows_quote_is_soft(tmp_path):
    pages = {
        1: "Revenue of our flagship hospital business stood at 500 crore in Q2 FY26.",
        2: "Total revenue grew to 500 crore in Q2 FY26 on strong volume growth.",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="revenue", dimension="total", fiscal_period="Q2FY26", value=500.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="CO", metric="revenue", dimension="total", fiscal_period="Q2FY26", value=500.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "healthcare"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "segment_scope" in fails, fails
    fails = verdict(out, "kpi_series", 2)[1]
    assert "segment_scope" not in fails, fails


def test_a_nearer_cash_label_is_not_gross_debt(tmp_path):
    pages = {
        1: "Our gross debt is at a comfortable level when we have a cash of INR 3,165 crores.",
        2: "Net debt of INR 3,165 crores at 30 June 2026, with cash of INR 500 crores.",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="gross_debt", dimension="total", fiscal_period="Q2FY26", value=3165.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="CO", metric="net_debt", dimension="total", fiscal_period="Q2FY26", value=3165.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "quarantined" and "label_conflict" in fails, fails
    status, fails = verdict(out, "kpi_series", 2)
    assert status != "quarantined" and "label_conflict" not in fails, fails


def test_a_past_level_in_narrative_is_soft(tmp_path):
    pages = {
        1: "Net debt had almost neared INR 20,000 crores in FY23, before the demerger.",
        2: "Net debt was INR 20,000 crores at the end of Q2 FY26.",
    }
    kpi = [
        dict(id=1, symbol="CO", metric="net_debt", dimension="total", fiscal_period="Q2FY26", value=20000.0,
             unit="inr_cr", scale=1e7, quote=pages[1], page=1),
        dict(id=2, symbol="CO", metric="net_debt", dimension="total", fiscal_period="Q2FY26", value=20000.0,
             unit="inr_cr", scale=1e7, quote=pages[2], page=2),
    ]
    db, profile = build(tmp_path, pages, kpi=kpi, sectors={"CO": "it_services"})
    out = run_checks(tmp_path, db, profile, ("kpi_series",))
    status, fails = verdict(out, "kpi_series", 1)
    assert status == "unverified" and "past_level" in fails, fails
    fails = verdict(out, "kpi_series", 2)[1]
    assert "past_level" not in fails, fails
