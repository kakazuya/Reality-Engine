"""T-242 (26 Nov 2026): filed-XBRL cross-check of hy4 rows (quarter P&L + annual/half-year BS/CF/P&L), and the
loader's status moves."""
from __future__ import annotations

import datetime as dt
import sqlite3

from reality_engine.scripts import load_observations as lo
from reality_engine.v2 import xbrl_crosscheck as xc


def test_as_at_and_half_year_periods():
    assert xc.as_at_date("As at 30.09.2026") == dt.date(2026, 9, 30)
    assert xc.as_at_date("31st March 2026") == dt.date(2026, 3, 31)
    assert xc.as_at_date("31.03.2026") == dt.date(2026, 3, 31)
    assert xc.as_at_date("2025-26") == dt.date(2026, 3, 31)
    for not_as_at in ("Half year ended 30.09.2026", "Year ended March 31, 2026", "Q2 FY27", "2025", ""):
        assert xc.as_at_date(not_as_at) is None, not_as_at
    assert xc.half_year_end("Half year ended 30.09.2026") == dt.date(2026, 9, 30)
    assert xc.half_year_end("Six months ended September 30, 2026") == dt.date(2026, 9, 30)
    assert xc.half_year_end("01.04.2026-30.09.2026") == dt.date(2026, 9, 30)
    assert xc.half_year_end("Quarter ended 30.09.2026") is None
    assert xc.duration_end("Year ended 31.03.2026") == ("FY", dt.date(2026, 3, 31))
    assert xc.duration_end("Quarter ended 30.06.2026") == ("Q", dt.date(2026, 6, 30))
    assert xc.duration_end("Half year ended 31.03.2026") == ("H1", dt.date(2026, 3, 31))
    assert xc.duration_end("Nine months ended 31.12.2025") is None
    assert xc.duration_end("Year ended 01.04.2026-30.09.2026") is None   # span contradicts "year"


def test_quarter_end_reads_quarter_periods_only():
    assert xc.quarter_end("Quarter ended 30.09.2026") == dt.date(2026, 9, 30)
    assert xc.quarter_end("quarter ended June 30, 2026") == dt.date(2026, 6, 30)
    assert xc.quarter_end("For the quarter ended 31st March, 2026") == dt.date(2026, 3, 31)
    assert xc.quarter_end("Q2 FY27") == dt.date(2026, 9, 30)
    assert xc.quarter_end("Q4FY26") == dt.date(2026, 3, 31)
    assert xc.quarter_end("3 months ended 30.09.2026") == dt.date(2026, 9, 30)
    for not_quarter in ("Half year ended 30.09.2026", "Year ended 31-Mar-26", "As at 30.09.2026",
                        "Nine months ended 31.12.2025", "30.09.2026"):
        assert xc.quarter_end(not_quarter) is None, not_quarter


def test_power_of_ten_finds_a_unit_step_only():
    assert xc._power_of_ten(5730.78, 573_078_000.0, 1.0) == 1e5
    assert xc._power_of_ten(110.81e5, 57.02e5, 1.0) is None


def _db(tmp_path, rows):
    p = tmp_path / "obs.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE observation (observation_id INTEGER, symbol TEXT, measure TEXT, value REAL, "
                "value_text TEXT, scale REAL, period TEXT, basis TEXT, entity_scope TEXT, status TEXT, "
                "record_type TEXT, segment TEXT, geography TEXT, product TEXT)")
    con.executemany("INSERT INTO observation VALUES (?,?,?,?,?,?,?,?,?,?,'number',NULL,NULL,NULL)", rows)
    con.commit()
    con.close()
    return p


def test_check_db_match_unit_fix_contradiction_and_skips(tmp_path):
    q = dt.date(2026, 6, 30)
    xbrl = {"ACME": {("pat", q, "consolidated"): 3_305_300_000.0, ("finance_cost", q, "standalone"): 114_000.0,
                     ("revenue_from_operations", q, "standalone"): 30_713_600_000.0,
                     ("exceptional_items", q, "consolidated"): -240_000_000.0}}
    db = _db(tmp_path, [
        (1, "ACME", "pat", 330.0, "330", 1e7, "quarter ended June 30, 2026", "consolidated", "company", "unverified"),
        (2, "ACME", "finance_cost", 1.14, "1.14", 1.0, "Quarter ended 30.06.2026", "standalone", "company", "verified"),
        (3, "ACME", "revenue_from_operations", 45520.0, "45,520", 1e6, "Q1 FY27", "standalone", "company", "verified"),
        (4, "ACME", "pat", 34.19, "34.19", 1e7, "quarter ended June 30, 2026", "consolidated", "subsidiary", "verified"),
        (5, "ACME", "exceptional_items", 24.0, "24", 1e7, "quarter ended June 30, 2026", "consolidated", "company", "verified"),
        (6, "ACME", "pat", 644.0, "644", 1e7, "year ended March 31, 2026", "consolidated", "company", "verified"),
    ])
    verdicts, stats = xc.check_db(db, xbrl)
    by = {v["id"]: v["verdict"] for v in verdicts}
    assert by == {1: "xbrl_match", 2: "xbrl_unit_fix", 3: "xbrl_contradicts", 5: "xbrl_match"}
    assert stats["skip_scope"] == 1 and stats["skip_period"] == 1


def test_check_db_annual_lines_bs_cf_and_sign_convention(tmp_path):
    h1, fy = dt.date(2026, 9, 30), dt.date(2026, 3, 31)
    annual = {"ACME": {
        ("cash_and_equivalents", h1, "consolidated", "stock"): [(1_234_500_000.0, True)],
        ("total_assets", fy, "standalone", "stock"): [(50_000_000.0, True)],
        ("equity_share_capital", h1, "consolidated", "stock"): [(1_000_000.0, True)],
        ("cash_flow_from_operations", h1, "consolidated", "H1"): [(500_000_000.0, True)],
        ("dividends_paid", fy, "consolidated", "FY"): [(-25_000_000.0, True)],
    }}
    db = _db(tmp_path, [
        (11, "ACME", "cash_and_cash_equivalents", 123.45, "123.45", 1e7, "As at 30.09.2026", "consolidated",
         "company", "unverified"),
        (12, "ACME", "total_assets", 45.6, "45.6", 1e6, "31st March 2026", "standalone", "company", "verified"),
        (13, "ACME", "equity_share_capital", 1.0, "1.0", 1e3, "30 September 2026", "consolidated", "company",
         "verified"),
        (14, "ACME", "cash_flow.operating", 50.0, "50", 1e7, "Half year ended September 30, 2026", "consolidated",
         "company", "unverified"),
        (15, "ACME", "dividends_paid", 2.5, "2.5", 1e7, "Year ended March 31, 2026", "consolidated", "company",
         "verified"),
    ])
    verdicts, _ = xc.check_db(db, {}, annual)
    by = {v["id"]: v for v in verdicts}
    assert by[11]["verdict"] == "xbrl_match" and by[11]["kind"] == "stock"
    assert by[12]["verdict"] == "xbrl_contradicts"
    assert by[13]["verdict"] == "xbrl_unit_fix" and by[13]["fix_scale"] == 1e6
    assert by[14]["verdict"] == "xbrl_match" and by[14]["kind"] == "H1"
    assert by[15]["verdict"] == "xbrl_match" and "sign_convention" in by[15]["evidence"]


def test_half_year_row_never_uses_a_quarter_line(tmp_path):
    h1 = dt.date(2026, 9, 30)
    xbrl = {"ACME": {("pat", h1, "consolidated"): 1.0}}
    annual = {"ACME": {("pat", h1, "consolidated", "Q"): [(2.0, True)]}}
    db = _db(tmp_path, [
        (21, "ACME", "pat", 9.0, "9", 1e7, "Half year ended 30.09.2026", "consolidated", "company", "verified"),
    ])
    verdicts, stats = xc.check_db(db, xbrl, annual)
    assert verdicts == [] and stats["no_xbrl_period"] == 1


def test_match_in_either_source_wins_over_the_other_source(tmp_path):
    q = dt.date(2026, 9, 30)
    xbrl = {"ACME": {("pat", q, "consolidated"): 1.0}}
    annual = {"ACME": {("pat", q, "consolidated", "Q"): [(9e7, True)]}}
    db = _db(tmp_path, [
        (31, "ACME", "pat", 9.0, "9", 1e7, "Quarter ended 30.09.2026", "consolidated", "company", "verified"),
    ])
    verdicts, _ = xc.check_db(db, xbrl, annual)
    assert len(verdicts) == 1 and verdicts[0]["verdict"] == "xbrl_match"
    assert verdicts[0]["source"] == "annual" and verdicts[0]["also"][0]["source"] == "quarter"


def test_loader_moves_status_on_xbrl_verdicts_only():
    cols = ["observation_id", "status"]
    rows = [(1, "unverified"), (2, "verified"), (3, "verified"), (4, "verified")]
    checks = {1: ("xbrl_match", None, "", "xbrl_crosscheck"), 2: ("xbrl_contradicts", None, "", "x"),
              3: ("xbrl_unit_fix", None, "", "x"), 4: ("model_checked", None, "", "sonnet")}
    out, moved = lo._apply_check_status(rows, cols, checks)
    assert [r[1] for r in out] == ["verified", "unverified", "unverified", "verified"]
    assert moved == {"unverified->verified": 1, "verified->unverified": 2}


def test_read_provenance_on_rows_and_backfill(tmp_path, monkeypatch):
    """Shivam 26 Nov 2026: every row says which model, gateway, harness and prompt read it."""
    from reality_engine.scripts import backfill_read_provenance as bf
    from reality_engine.v2 import observations as obs
    assert obs.gateway_of({"base": "https://opencode.ai/zen/go/v1"}) == "opencode-go"
    assert obs.gateway_of({"api": "gemini_native"}) == "google-ai-studio"
    assert obs.gateway_of({"base": "https://api.kilo.ai/v1"}) == "kilo-gateway"
    con = obs.create_db(tmp_path / "o.db")
    monkeypatch.setattr(obs, "PROMPT_FP", "results:abc")
    row = {c: None for c in obs.OBS_COLUMNS} | {"symbol": "ACME", "doc_key": "d", "page": 1, "measure": "pat",
                                                 "status": "verified", "record_type": "number"}
    row = {k: ("" if v is None and k not in ("value", "value_high", "scale") else v)
           for k, v in row.items()}
    row.update({"adjusted": 0, "is_total": 0, "scale": 1.0, "reader": "hy4-flash-free"})
    obs.write_rows(con, [row])
    got = con.execute("SELECT read_model, read_gateway, read_harness, prompt_fp FROM observation").fetchone()
    assert got == ("opencode-go/hy4-flash-free", "opencode-go", obs.READ_HARNESS_DEFAULT, "results:abc")
    con.execute("UPDATE observation SET read_model='', read_gateway='', read_harness='', prompt_fp=''")
    con.execute("INSERT INTO page_reply VALUES ('d', 1, 'fp1', '{}', '2026-11-26')")
    con.commit()
    con.close()
    bf.backfill(tmp_path / "o.db")
    con = sqlite3.connect(tmp_path / "o.db")
    assert con.execute("SELECT read_model, read_gateway, prompt_fp FROM observation").fetchone() == (
        "opencode-go/hy4-flash-free", "opencode-go", "fp1")


def test_loader_arith_flags_never_downgrade_a_total_and_xbrl_match_wins():
    cols = ["observation_id", "status", "is_total"]
    rows = [(1, "verified", 1), (2, "verified", 0), (3, "verified", 0), (4, "unverified", 0)]
    checks = {1: ("arith_sum_mismatch", None, "", "arith_checks"), 2: ("arith_sum_mismatch", None, "", "arith_checks"),
              3: ("arith_subset_as_total", None, "", "arith_checks"), 4: ("xbrl_match", None, "", "xbrl_crosscheck")}
    out, _ = lo._apply_check_status(rows, cols, checks)
    assert [r[1] for r in out] == ["verified", "unverified", "unverified", "verified"]


def test_match_needs_the_printed_digit_else_near():
    """Eagle 26 Nov: AHLEAST CF (578.22) lakh stored vs 576.22 filed is within 1% but a misread digit."""
    assert xc._printed_tol("(578.22)", 1e5) < 600
    q = dt.date(2026, 6, 30)
    xbrl = {"ACME": {("pat", q, "consolidated"): 3_305_300_000.0}}
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    db = _db(d, [(1, "ACME", "pat", 330.0, "330", 1e7, "quarter ended June 30, 2026", "consolidated", "company", "unverified"),
                 (2, "ACME", "pat", 331.53, "331.53", 1e7, "quarter ended June 30, 2026", "consolidated", "company", "unverified")])
    verdicts, _ = xc.check_db(db, xbrl)
    assert {v["id"]: v["verdict"] for v in verdicts} == {1: "xbrl_match", 2: "xbrl_near"}
