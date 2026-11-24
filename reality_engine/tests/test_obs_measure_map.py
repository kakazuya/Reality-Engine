"""Synthetic unit and CLI tests for reality_engine.v2.obs_measure_map (T-241)."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from reality_engine.v2 import obs_measure_map as omm
from reality_engine.v2 import observations as obs_mod


def _make_obs_db(path: Path, rows: list[dict[str, object]]) -> None:
    con = obs_mod.create_db(path)
    for i, r in enumerate(rows, start=1):
        unit = str(r.get("unit", ""))
        uf = str(r.get("unit_family", ""))
        con.execute(
            """
            INSERT INTO observation
                (symbol, doc_key, page, known_at, measure, printed_label, value, value_text,
                 unit, unit_family, record_type, statement, status, status_reason)
            VALUES (?, ?, ?, '2026-11-01', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("symbol", f"SYM{i}"),
                r.get("doc_key", f"D:/raw/SYM{i}/concall_transcript/c.pdf"),
                int(r.get("page", 1)),
                r["measure"],
                r.get("printed_label", ""),
                r.get("value"),
                r.get("value_text", ""),
                unit,
                uf,
                r.get("record_type", "number"),
                r.get("statement", ""),
                r.get("status", "verified"),
                r.get("status_reason", ""),
            ),
        )
    con.commit()
    con.close()


def test_junk_years_dates_pages_and_codes_quarantined(tmp_path: Path):
    obs_db = tmp_path / "obs.db"
    out_db = tmp_path / "out.db"
    _make_obs_db(
        obs_db,
        [
            {"measure": "NEW:launch_year", "value": 2019.0, "value_text": "2019", "unit": ""},
            {"measure": "NEW:fiscal_year", "value": 2025.0, "value_text": "2025", "unit": ""},
            {"measure": "NEW:total_pages", "value": 18.0, "value_text": "18", "unit": "pages"},
            {"measure": "NEW:conference_call_date", "value": 14.0, "value_text": "May 14, 2026", "unit": ""},
            {"measure": "NEW:pin_code", "value": 400051.0, "value_text": "400051", "unit": ""},
            {"measure": "NEW:pseudonym", "value": 12345.0, "value_text": "253520230609", "unit": ""},
            {"measure": "NEW:launch_year", "printed_label": "Scrip Code:", "value": 540935.0, "value_text": "540935", "unit": ""},
            # Project completion date is business timeline, NOT letterhead call/filing date
            {"measure": "NEW:completion_date", "printed_label": "expected completion", "value": None, "value_text": "March '25", "unit": ""},
            # Duration in years (note observations.py rs-bug tagged 'money') must NOT be quarantined
            {"measure": "NEW:duration_years", "value": 5.0, "value_text": "5", "unit": "years", "unit_family": "money"},
            # Statement on launch_year (no value) must NOT be quarantined
            {"measure": "NEW:launch_year", "record_type": "statement", "statement": "Plant commissioned in 2020."},
        ],
    )
    stats = omm.run(obs_db, out_db)
    assert stats["junk_total"] == 7

    # Original DB untouched
    orig = sqlite3.connect(str(obs_db))
    assert orig.execute("SELECT COUNT(*) FROM observation WHERE status='quarantined'").fetchone()[0] == 0
    orig.close()

    con = sqlite3.connect(str(out_db))
    got = con.execute(
        "SELECT observation_id, status, status_reason FROM observation ORDER BY observation_id"
    ).fetchall()
    con.close()
    for oid in range(7):
        assert got[oid][1] == "quarantined"
        assert "junk_measure" in got[oid][2]
    assert got[7][1] == "verified"
    assert got[8][1] == "verified"
    assert got[9][1] == "verified"


def test_percent_vs_crore_never_merged_and_dict_alias_match(tmp_path: Path):
    obs_db = tmp_path / "obs.db"
    out_db = tmp_path / "out.db"
    _make_obs_db(
        obs_db,
        [
            # Exact dict match with <> and word-order/plural/synonym
            {"symbol": "A", "measure": "NEW:<ebitda_margin>", "value": 18.0, "value_text": "18%", "unit": "%", "unit_family": "percent"},
            {"symbol": "A", "measure": "NEW:net_worth", "value": 500.0, "value_text": "500", "unit": "crores", "unit_family": "money"},
            {"symbol": "A", "measure": "NEW:ratio_of_debt_to_equity", "value": 0.5, "value_text": "0.5x", "unit": "x", "unit_family": "ratio"},
            {"symbol": "A", "measure": "NEW:capital_expenditure", "value": 120.0, "value_text": "120", "unit": "INR crores", "unit_family": "money"},
            # Conflicting unit family for dict match (percent on net_worth) must NOT map to total_equity (money)
            {"symbol": "B", "measure": "NEW:net_worth", "value": 12.0, "value_text": "12%", "unit": "%", "unit_family": "percent"},
            # Same-name cluster candidates across 3 companies, but one in % and one in crores -> NEVER merge
            {"symbol": "A", "measure": "NEW:custom_metric", "value": 15.0, "value_text": "15%", "unit": "%", "unit_family": "percent"},
            {"symbol": "B", "measure": "NEW:custom_metric", "value": 20.0, "value_text": "20%", "unit": "%", "unit_family": "percent"},
            {"symbol": "C", "measure": "NEW:custom_metric", "value": 25.0, "value_text": "25%", "unit": "%", "unit_family": "percent"},
            {"symbol": "D", "measure": "NEW:custom_metric_crore", "value": 100.0, "value_text": "100", "unit": "crores", "unit_family": "money"},
            {"symbol": "E", "measure": "NEW:custom_metric_crore", "value": 200.0, "value_text": "200", "unit": "crores", "unit_family": "money"},
            {"symbol": "F", "measure": "NEW:custom_metric_crore", "value": 300.0, "value_text": "300", "unit": "crores", "unit_family": "money"},
            # Different names sharing tokens but different unit families (% vs crore) -> NEVER merge
            {"symbol": "A", "measure": "NEW:incentive_pct", "value": 5.0, "value_text": "5%", "unit": "%", "unit_family": "percent"},
            {"symbol": "B", "measure": "NEW:incentive_pct", "value": 6.0, "value_text": "6%", "unit": "%", "unit_family": "percent"},
            {"symbol": "C", "measure": "NEW:incentive_pct", "value": 7.0, "value_text": "7%", "unit": "%", "unit_family": "percent"},
            {"symbol": "D", "measure": "NEW:incentive_amount", "value": 50.0, "value_text": "50", "unit": "crores", "unit_family": "money"},
            {"symbol": "E", "measure": "NEW:incentive_amount", "value": 60.0, "value_text": "60", "unit": "crores", "unit_family": "money"},
            {"symbol": "F", "measure": "NEW:incentive_amount", "value": 70.0, "value_text": "70", "unit": "crores", "unit_family": "money"},
        ],
    )
    omm.run(obs_db, out_db)
    con = sqlite3.connect(str(out_db))
    rows = con.execute("SELECT observation_id, measure FROM observation ORDER BY observation_id").fetchall()
    mmap = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT new_name, canonical, source, rows FROM measure_map")}
    con.close()

    assert rows[0][1] == "ebitda_margin"
    assert rows[1][1] == "total_equity"
    assert rows[2][1] == "debt_equity"
    assert rows[3][1] == "capex"
    # Conflicting unit family row stays unmapped
    assert rows[4][1] == "NEW:net_worth"
    # Separate unit families never merge
    assert mmap["NEW:custom_metric"][0] != mmap["NEW:custom_metric_crore"][0]
    assert mmap["NEW:incentive_pct"][0] != mmap["NEW:incentive_amount"][0]
    assert mmap["NEW:<ebitda_margin>"][1] == "dict"
    assert mmap["NEW:capital_expenditure"][1] == "alias"


def test_cluster_needs_three_companies_and_cli_report(tmp_path: Path):
    obs_db = tmp_path / "obs.db"
    out_db = tmp_path / "out.db"
    rep_md = tmp_path / "report.md"
    _make_obs_db(
        obs_db,
        [
            # Only 2 companies -> must stay source='none'
            {"symbol": "A", "measure": "NEW:rare_ratio", "value": 1.2, "value_text": "1.2x", "unit": "x", "unit_family": "ratio"},
            {"symbol": "B", "measure": "NEW:<rare_ratio>", "value": 1.4, "value_text": "1.4x", "unit": "x", "unit_family": "ratio"},
            # 3 companies with synonyms/<> -> must cluster
            {"symbol": "A", "measure": "NEW:cd_ratio", "value": 75.0, "value_text": "75%", "unit": "%", "unit_family": "percent"},
            {"symbol": "B", "measure": "NEW:<cd_ratio>", "value": 78.0, "value_text": "78%", "unit": "%", "unit_family": "percent"},
            {"symbol": "C", "measure": "NEW:credit_deposit_ratio", "value": 80.0, "value_text": "80%", "unit": "%", "unit_family": "percent"},
        ],
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "reality_engine.v2.obs_measure_map",
            "--obs",
            str(obs_db),
            "--out",
            str(out_db),
            "--report",
            str(rep_md),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "obs_measure_map done" in proc.stdout
    assert rep_md.exists()

    con = sqlite3.connect(str(out_db))
    mmap = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT new_name, canonical, source, rows FROM measure_map")}
    measures = [r[0] for r in con.execute("SELECT measure FROM observation ORDER BY observation_id")]
    con.close()

    assert mmap["NEW:rare_ratio"] == ("", "none", 1)
    assert mmap["NEW:<rare_ratio>"] == ("", "none", 1)
    assert mmap["NEW:cd_ratio"] == ("NEW:credit_deposit_ratio", "cluster", 1)
    assert mmap["NEW:<cd_ratio>"] == ("NEW:credit_deposit_ratio", "cluster", 1)
    assert mmap["NEW:credit_deposit_ratio"] == ("NEW:credit_deposit_ratio", "cluster", 1)
    assert measures[2:] == ["NEW:credit_deposit_ratio"] * 3
