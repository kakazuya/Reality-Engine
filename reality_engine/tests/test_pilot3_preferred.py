"""T-088: one preferred comparative per quarter, growth on the same quarter a year earlier, stated and derived
ratios together, the entity apart from the basis, and trailing-twelve-month PAT.

Fixture only: a scratch SQLite file built from the real DDL, no store, no network, no model.  The path is a
unique file under ``.tmp/`` (not a fresh directory: a created directory needs a Windows ACL this sandbox does
not grant).
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import kpi, ratios, schema

SERVER = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
SYM = "BAJFINANCE"
SCRATCH = Path(".tmp")


def _conn():
    SCRATCH.mkdir(exist_ok=True)
    path = SCRATCH / f"t088_{uuid.uuid4().hex}.db"
    conn = sqlite3.connect(path)
    schema.create(conn, list(schema.TABLES))
    conn.executescript(kpi.SCHEMA)
    conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'500034','500034','Bajaj Finance Limited')",
                 (SYM, "INE296A01024"))
    conn.commit()
    return conn, path


@pytest.fixture()
def lookups(monkeypatch):
    made = []

    def make():
        conn, path = _conn()
        monkeypatch.setenv("REALITY_PILOT3_DB", str(path))
        if str(SERVER) not in sys.path:
            sys.path.insert(0, str(SERVER))
        spec = importlib.util.spec_from_file_location("lookups_pilot3", SERVER / "lookups_pilot3.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        made.append((module, path))
        return module, conn

    yield make
    for module, path in made:
        module.close()
        try:
            path.unlink(missing_ok=True)
        except OSError:      # a failed test may still hold the file open on Windows
            pass


def _printed(conn, period, end, role, value, known, status, line="total_income", basis="consolidated", page=1):
    conn.execute("INSERT INTO fin_quarter_printed (symbol, isin, period_end, fiscal_period, period_type, column_role, "
                 "basis, statement, line_item, caption, value, unit, scale, raw_token, quote, doc_key, page, known_at, "
                 "known_at_source, check_status, check_detail, is_reported) "
                 "VALUES (?,?,?,?,?,?,?,'P&L',?,?,?,'inr',1,?,?,?,?,?,'x',?,'',1)",
                 (SYM, "INE296A01024", end, period, "quarter", role, basis, line, "Total income", value,
                  f"{value:.2f}", f"Total income {value}", f"doc-{known[:10]}", page, known, status))


def _xbrl(conn, period, end, item, value, known, basis="consolidated"):
    conn.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, audited, "
                 "statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, source_table, "
                 "source_rowid, known_at, known_at_source, is_reported) "
                 "VALUES (?,?,?,?,?,?,'A','P&L',?,?,?, 'inr',1,'f','d','t','r',?,'s',1)",
                 (SYM, "INE296A01024", end[:7] + "-01", end, period, basis, item, item, value, known))


def _kpi(conn, metric, value, period, entity, known, rank=4, basis="not_stated", page=1, quote=None):
    conn.execute("INSERT INTO kpi_series (symbol, metric, dimension, value, unit, scale, period_type, fiscal_period, "
                 "basis, doc_key, page, quote, known_at, extractor_rule, confidence, conf_rank, entity) "
                 "VALUES (?,?, 'total', ?, 'pct',1,'Q',?,?,?,?,?,?,'sentence_v1','sentence',?,?)",
                 (SYM, metric, value, period, basis, f"BAJFINANCE/deck/{known[:10]}.pdf", page,
                  quote or f"{metric} {value}", known, rank, entity))


# --- 1. one preferred figure per quarter, restatement and as-of ---------------------------------------
def test_preferred_comparative_newest_filing_wins_and_as_of_holds_it(lookups):
    module, conn = lookups()
    _printed(conn, "Q2FY26", "2025-09-30", "current", 201_807_600_000.0, "2025-11-10T17:11:10", "xbrl_ok")
    _printed(conn, "Q2FY26", "2025-09-30", "preceding", 201_807_600_000.0, "2026-02-03T17:07:39", "xbrl_ok")
    _printed(conn, "Q2FY26", "2025-09-30", "year_ago", 199_923_800_000.0, "2026-10-19T17:19:48", "unchecked")
    conn.commit()

    now = module.fin(SYM, "total_income", "Q2FY26", as_of="2026-11-04")
    assert now["n"] == 1 and now["rows"][0]["preferred"] is True and now["rows"][0]["restated"] is True
    assert now["rows"][0]["value_inr"] == pytest.approx(199_923_800_000.0)
    alt = now["rows"][0]["alternatives"]
    assert [a["value_inr"] for a in alt] == [pytest.approx(201_807_600_000.0)]
    assert alt[0]["filing_date"] == "2025-11-10"

    before = module.fin(SYM, "total_income", "Q2FY26", as_of="2026-01-01")
    assert before["rows"][0]["value_inr"] == pytest.approx(201_807_600_000.0)
    assert before["rows"][0]["restated"] is False


# --- 2. growth on the same quarter a year earlier, never another quarter's cell ----------------------
def test_yoy_prefers_the_xbrl_confirmed_year_ago_twin_over_a_sum_ok_twin():
    conn, _path = _conn()
    _xbrl(conn, "Q2FY27", "2026-09-30", "revenue_from_operations", 49_244_000_000.0, "2026-10-23T20:16:14")
    _printed(conn, "Q2FY27", "2026-09-30", "current", 49_244_000_000.0, "2026-10-23T16:16:06", "xbrl_ok",
             line="revenue_from_operations")
    _printed(conn, "Q2FY26", "2025-09-30", "year_ago", 45_480_000_000.0, "2026-10-23T16:16:06", "sum_ok",
             line="revenue_from_operations")
    _printed(conn, "Q2FY26", "2025-09-30", "year_ago", 44_490_000_000.0, "2026-10-23T16:16:06", "xbrl_ok",
             line="revenue_from_operations")
    conn.commit()
    ratios.build_ratios(conn)
    value = conn.execute("SELECT value FROM ratio_panel WHERE symbol=? AND metric='revenue_growth_yoy_pct' "
                         "AND fiscal_period='Q2FY27' AND basis='consolidated'", (SYM,)).fetchone()[0]
    assert value == pytest.approx(100.0 * (49_244 / 44_490 - 1.0))          # 10.69%, not 8.28%
    refs = json.loads(conn.execute("SELECT input_refs FROM ratio_panel WHERE symbol=? AND "
                                   "metric='revenue_growth_yoy_pct' AND fiscal_period='Q2FY27'",
                                   (SYM,)).fetchone()[0])
    assert refs[1].endswith("Q2FY26:consolidated:revenue_from_operations")  # the same filing's year_ago, unlabelled


def test_yoy_uses_the_same_filings_sum_ok_year_ago_column_not_the_first_printing():
    """HINDUNILVR (T-088 round 2): Q2 FY27 18,226 over the Q2 FY26 year_ago column 15,919 (sum_ok, same filing)
    = 14.49%; the earlier first printing 16,241 is pre-restatement and must not be the base. Q1 FY27 likewise
    17,341 / 15,757 = 10.05%, not 16,514."""
    conn, _path = _conn()
    _xbrl(conn, "Q1FY27", "2026-06-30", "revenue_from_operations", 17_341.0, "2026-07-28T19:00:00")
    _xbrl(conn, "Q2FY27", "2026-09-30", "revenue_from_operations", 18_226.0, "2026-10-28T19:00:00")
    _printed(conn, "Q1FY27", "2026-06-30", "current", 17_341.0, "2026-07-28T15:00:00", "sum_ok",
             line="revenue_from_operations")
    _printed(conn, "Q1FY26", "2025-06-30", "year_ago", 15_757.0, "2026-07-28T15:00:00", "sum_ok",
             line="revenue_from_operations")
    _printed(conn, "Q2FY27", "2026-09-30", "current", 18_226.0, "2026-10-28T15:00:00", "sum_ok",
             line="revenue_from_operations")
    _printed(conn, "Q2FY26", "2025-09-30", "current", 16_241.0, "2025-10-23T11:11:45", "sum_ok",
             line="revenue_from_operations")
    _printed(conn, "Q2FY26", "2025-09-30", "year_ago", 15_919.0, "2026-10-28T15:00:00", "sum_ok",
             line="revenue_from_operations")
    conn.commit()
    ratios.build_ratios(conn)
    got = {r[0]: r[1] for r in conn.execute(
        "SELECT fiscal_period, value FROM ratio_panel WHERE symbol=? AND metric='revenue_growth_yoy_pct' "
        "AND basis='consolidated'", (SYM,))}
    assert got["Q2FY27"] == pytest.approx(100.0 * (18_226 / 15_919 - 1.0))   # 14.49%
    assert got["Q1FY27"] == pytest.approx(100.0 * (17_341 / 15_757 - 1.0))   # 10.05%


def test_yoy_fallback_base_is_labelled_and_still_same_quarter():
    """No year_ago cell in the current filing: the earlier printing is used, labelled @fallback."""
    conn, _path = _conn()
    _xbrl(conn, "Q2FY27", "2026-09-30", "revenue_from_operations", 49_244.0, "2026-10-23T20:16:14")
    _printed(conn, "Q2FY26", "2025-09-30", "current", 44_490.0, "2025-10-16T16:12:39", "xbrl_ok",
             line="revenue_from_operations")
    conn.commit()
    ratios.build_ratios(conn)
    refs = json.loads(conn.execute("SELECT input_refs FROM ratio_panel WHERE symbol=? AND "
                                   "metric='revenue_growth_yoy_pct' AND fiscal_period='Q2FY27'",
                                   (SYM,)).fetchone()[0])
    assert refs[1].endswith("Q2FY26:consolidated:revenue_from_operations@fallback")


def test_growth_refuses_a_year_ago_cell_of_another_quarter():
    conn, _path = _conn()
    _xbrl(conn, "Q2FY27", "2026-09-30", "revenue_from_operations", 49_244_000_000.0, "2026-10-23T20:16:14")
    _printed(conn, "Q2FY26", "2025-09-30", "year_ago", 45_479_000_000.0, "2026-10-23T16:16:06", "xbrl_ok",
             line="revenue_from_operations")
    conn.execute("UPDATE fin_quarter_printed SET fiscal_period='Q3FY26', period_end='2025-12-31'")
    conn.commit()
    ratios.build_ratios(conn)
    assert conn.execute("SELECT COUNT(*) FROM ratio_panel WHERE metric='revenue_growth_yoy_pct'").fetchone()[0] == 0


# --- 3. stated and derived together, each labelled ---------------------------------------------------
def test_ratio_returns_derived_and_company_stated_roe(lookups):
    module, conn = lookups()
    for known, value in (("2026-10-19T19:59:18", 17.914), ("2026-04-29T22:47:24", 16.958)):
        conn.execute("INSERT INTO ratio_panel VALUES (?,?, 'Q2FY27','Q','2026-07-01','2026-09-30','consolidated','roe',"
                     "?,'pct',1.0,'F_ROE','[]',?,'max(known_at of inputs)',1)", (SYM, "INE296A01024", value, known))
    _kpi(conn, "roe_pct", 20.6, "Q2FY27", SYM, "2026-10-19T17:19:48", rank=4, quote="Annualised ROE 20.6")
    _kpi(conn, "roe_pct", 12.7, "Q2FY27", "bhfl", "2026-10-23T14:45:33", rank=1, quote="ROE improved ... to 12.7%")
    _kpi(conn, "roe_pct", 19.0, "Q2FY27", SYM, "2026-10-23T14:45:33", rank=1, quote="core ROE of between 19% and 20%")
    conn.commit()
    reply = module.ratio(SYM, "roe", "Q2FY27")
    derived = [r for r in reply["rows"] if r["definition"] == "derived"]
    stated = [r for r in reply["rows"] if r["definition"] == "company_stated"]
    assert derived and derived[0]["value"] == pytest.approx(17.914)
    assert len(stated) == 1 and stated[0]["value"] == pytest.approx(20.6)
    assert stated[0]["quote"] == "Annualised ROE 20.6" and stated[0]["provenance"]["source"].endswith("p1")


# --- 4. entity apart from basis; kpi() puts the company's rows first and collapses exact duplicates --
def test_kpi_entity_first_and_exact_duplicates_collapsed(lookups):
    module, conn = lookups()
    _kpi(conn, "roe_pct", 18.1, "FY26", SYM, "2026-04-29T17:30:47", rank=4)
    _kpi(conn, "roe_pct", 18.1, "FY26", SYM, "2026-07-30T15:39:18", rank=4)      # same figure, another filing
    _kpi(conn, "roe_pct", 12.1, "FY26", "bhfl", "2026-04-29T17:30:47", rank=4)
    _kpi(conn, "roe_pct", 20.0, "FY26", SYM, "2026-04-29T16:38:46", rank=1)
    conn.commit()
    reply = module.kpi(SYM, "roe_pct", "FY26")
    rows = reply["rows"]
    assert rows[0]["entity"] == SYM and rows[0]["value"] == pytest.approx(18.1)
    assert rows[-1]["entity"] == "bhfl"
    assert len([r for r in rows if r["value"] == 18.1]) == 1
    assert reply["n"] == 3


def test_kpi_stored_basis_that_names_a_subsidiary_moves_to_the_entity(lookups):
    module, conn = lookups()
    _kpi(conn, "cost_of_funds_pct", 7.21, "Q1FY27", "bhfl", "2026-07-30T15:39:18", basis="bhfl",
         quote="Cost of funds was 7.21%")
    conn.commit()
    row = module.kpi(SYM, "cost_of_funds", "Q1FY27")["rows"][0]
    assert (row["entity"], row["basis"], row["dimension"]) == ("bhfl", "not_stated", "total")


# --- 5. trailing twelve months of PAT, with its four inputs ------------------------------------------
def test_trailing_pat_and_pat_before_exceptional_show_their_quarters():
    conn, _path = _conn()
    for period, end, known, pat in (("Q3FY26", "2025-12-31", "2026-02-03T19:13:05", 40_660_100_000.0),
                                    ("Q4FY26", "2026-03-31", "2026-04-29T22:45:16", 55_533_000_000.0),
                                    ("Q1FY27", "2026-06-30", "2026-07-30T19:00:09", 60_806_000_000.0),
                                    ("Q2FY27", "2026-09-30", "2026-10-19T19:59:04", 63_665_700_000.0)):
        _xbrl(conn, period, end, "pat", pat, known)
    _xbrl(conn, "Q3FY26", "2025-12-31", "exceptional_items", -2_652_200_000.0, "2026-02-03T19:13:05")
    conn.commit()
    ratios.build_ratios(conn)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT metric, value, input_refs FROM ratio_panel WHERE symbol=? AND period_type='TTM' AND fiscal_period='Q2FY27'",
        (SYM,))}
    assert rows["pat_ttm"][0] == pytest.approx(220_664_800_000.0)             # 22,066.48 crore
    refs = json.loads(rows["pat_ttm"][1])
    assert len(refs) == 4 and [r.split(":")[2] for r in refs] == ["Q3FY26", "Q4FY26", "Q1FY27", "Q2FY27"]
    assert rows["pat_before_exceptional_ttm"][0] == pytest.approx(223_317_000_000.0)
    assert any("Q3FY26:consolidated:exceptional_items" in r for r in json.loads(rows["pat_before_exceptional_ttm"][1]))


# --- 6. the two claims: the glued value and the wrong-basis lease liabilities --------------------------
def test_stores_reject_a_value_glued_from_two_printed_numbers():
    from reality_engine.pilot3 import stores

    assert stores._concatenated_value(917_626_822_725.0, "9,176 (FY26); 8,227 (FY25)", "not_found")
    assert not stores._concatenated_value(3_749.0, "Total 3,749 3,459", "page")
    assert not stores._concatenated_value(9_176.0, "Total 9,176", "not_found")


def test_stores_read_the_statement_basis_from_the_page_wording():
    from reality_engine.pilot3 import stores

    assert stores._statement_basis("The Company does not face a significant liquidity risk.") == "standalone"
    assert stores._statement_basis("The Group does not face a significant liquidity risk. The Group provides "
                                   "for gratuity; the Company contributes.") == "consolidated"
    assert stores._statement_basis("Total 3,749 3,459") is None


# --- T-192 2: EBITDA is the company's own operating measure, the derived one a labelled second row ------------
def _kpi_ebitda(conn, value, period, label, known, rank=4, basis="consolidated"):
    conn.execute("INSERT INTO kpi_series (symbol, metric, dimension, value, unit, scale, period_type, fiscal_period, "
                 "basis, doc_key, page, quote, known_at, extractor_rule, confidence, conf_rank, entity, raw_label) "
                 "VALUES (?,?,'total',?,'inr_cr',1,'FY',?,?,?,?,?,?,'table_v1','table',?,?,?)",
                 (SYM, "ebitda", value, period, basis, f"BAJFINANCE/deck/{known[:10]}.pdf", 1,
                  f"{label}\n{value}", known, rank, SYM, label))


def test_ebitda_serves_the_companys_printed_measure_not_one_derivation(lookups):
    """Two company-printed rows and one derived row: the operating definition wins and the derived row is a second,
    labelled answer.  "EBITDA before R&D" strips an operating cost, so it is a different measure (T-192)."""
    module, conn = lookups()
    conn.execute("INSERT INTO ratio_panel VALUES (?,?, 'FY25','FY','2024-04-01','2025-03-31','consolidated','ebitda',"
                 "65556100000.0,'inr',1.0,'F_EBITDA','[]','2025-05-27T00:01:19','x',1)",
                 (SYM, "INE296A01024"))
    _kpi_ebitda(conn, 8148.0, "FY25", "EBITDA before R&D", "2026-05-21T22:12:58")
    _kpi_ebitda(conn, 6605.0, "FY25", "EBITDA (before Forex and Other Income)", "2026-05-21T22:12:58")
    conn.commit()
    reply = module.fact(SYM, "ebitda", "FY25")
    assert reply["found"] is True and reply["route"] == "kpi"
    assert reply["answer"]["value"] == pytest.approx(6605.0)
    # the derived row is kept as a labelled second answer, never merged into the company's own figure
    assert [a["value"] for a in reply["alternatives"] if a.get("value") in (65556100000.0, 6555.61)], \
        reply["alternatives"]


def test_ebitda_rank_prefers_the_operating_label():
    from lookups_pilot3 import _ebitda_rank

    assert _ebitda_rank({"raw_label": "EBITDA (before Forex and Other Income)"}) == 0
    assert _ebitda_rank({"raw_label": "Operating EBITDA"}) == 0
    assert _ebitda_rank({"raw_label": "EBITDA before R&D"}) == 1


# --- T-192 4: a target naming a subsidiary/segment/investee is never the group's ---------------------------
def test_guidance_never_serves_an_entitys_target_as_the_groups(lookups):
    module, conn = lookups()
    conn.execute("INSERT INTO guidance (symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
                 "doc_key, page, quote, speaker, known_at, known_at_source, revision_of, extractor_rule, entity) "
                 "VALUES (?,?,'ebitda_margin','FY31',15,15,'pct','flat','2025-08-08','d1',18,'margin of 15% or more',"
                 "'m','2025-08-08T12:07:00','doc.known_at',NULL,'guidance_cue_v1','Lannett')",
                 (SYM, "INE296A01024"))
    conn.execute("INSERT INTO guidance (symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
                 "doc_key, page, quote, speaker, known_at, known_at_source, revision_of, extractor_rule, entity) "
                 "VALUES (?,?,'ebitda_margin','FY27',21,21,'pct','up','2026-05-27','d2',6,'north of 21%','m',"
                 "'2026-05-27T18:14:02','doc.known_at',NULL,'guidance_cue_v1','')",
                 (SYM, "INE296A01024"))
    conn.commit()
    reply = module.guidance(SYM, "ebitda_margin")
    assert [(r["period"], r["low"]) for r in reply["rows"]] == [("FY27", 21.0)]

