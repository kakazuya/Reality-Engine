"""T-242 (26 Nov 2026): filed-XBRL cross-check of hy4 results rows, and the loader's status moves."""
from __future__ import annotations

import datetime as dt
import sqlite3

from reality_engine.scripts import load_observations as lo
from reality_engine.v2 import xbrl_crosscheck as xc


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
