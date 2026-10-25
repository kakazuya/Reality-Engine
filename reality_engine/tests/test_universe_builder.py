"""Fixture test for the point-in-time theme-universe builder.

A company enters a theme when a new segment matches the theme, and ``pivot`` is
true when that segment is its largest.  The fixture also checks the exit rule:
two consecutive quarters with the segment at 0 close the membership.

Run from the repo root:
    python -m unittest reality_engine.tests.test_universe_builder
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reality_engine.scripts import build_universe_membership as builder  # noqa: E402

# The harness TMP dir (and any ``tmp*`` directory) is ACL-denied; use a local one.
_TMP_ROOT = ROOT / ".tmp_universe_tests"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _case_dir() -> Path:
    path = _TMP_ROOT / f"case_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    path.mkdir()
    return path

ACME = "INE00ACME001"


def _fixture(root: Path) -> None:
    eq = sqlite3.connect(root / "equity_intelligence.db")
    eq.executescript(
        "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, bse_code TEXT, company_name TEXT);"
        "CREATE TABLE company_industry(isin TEXT, symbol TEXT, sector TEXT, industry TEXT,"
        " basic_industry TEXT, fetched_at TEXT);"
    )
    eq.execute("INSERT INTO master_companies VALUES (?,?,?,?)",
               (ACME, "ACME", "500001", "Acme Jewellery Limited"))
    eq.execute("INSERT INTO company_industry VALUES (?,?,?,?,?,?)",
               (ACME, "ACME", "Consumer Durables", "Consumer Durables",
                "Gems Jewellery And Watches", "2026-01-01T00:00:00"))
    eq.commit()
    eq.close()

    xb = sqlite3.connect(root / "results_xbrl.db")
    xb.executescript(
        "CREATE TABLE filings(file TEXT, taxonomy TEXT, xbrl_url TEXT, isin TEXT, symbol TEXT,"
        " scrip_code TEXT, company TEXT, index_period TEXT, reporting_quarter TEXT, consolidated TEXT,"
        " audited TEXT, period_start TEXT, period_end TEXT, fy_start TEXT, fy_end TEXT,"
        " board_meeting TEXT, broadcast_ts TEXT, dissem_ts TEXT, filing_ts TEXT, audit_opinion TEXT,"
        " n_facts INTEGER, status TEXT, parsed_at TEXT);"
        "CREATE TABLE filings_isin(file TEXT, isin_filed TEXT, isin TEXT, method TEXT,"
        " same_issuer INTEGER, as_of TEXT, resolved_at TEXT);"
        "CREATE TABLE facts(file TEXT, concept TEXT, context TEXT, period_start TEXT,"
        " period_end TEXT, instant TEXT, value REAL, unit TEXT, decimals TEXT);"
    )
    # Q1: no theme segment.  Q2: gold jewellery becomes the largest segment.
    # Q3 + Q4: zero for two consecutive quarters -> exit from Q4's known date.
    filings = [
        ("q1.xml", "2025-07-10", "2025-06-30"),
        ("q2.xml", "2025-10-10", "2025-09-30"),
        ("q3.xml", "2026-01-10", "2025-12-31"),
        ("q4.xml", "2026-04-10", "2026-03-31"),
    ]
    for file, known, period_end in filings:
        xb.execute(
            "INSERT INTO filings(file, period_end, dissem_ts) VALUES (?,?,?)",
            (file, period_end, known + "T18:00:00"),
        )
        xb.execute("INSERT INTO filings_isin(file, isin) VALUES (?,?)", (file, ACME))
    segments = {
        "q1.xml": {"Others": 100.0},
        "q2.xml": {"Gold Jewellery": 90.0, "Others": 10.0},
        "q3.xml": {"Others": 100.0},
        "q4.xml": {"Others": 100.0},
    }
    for file, contexts in segments.items():
        for context, value in contexts.items():
            xb.execute(
                "INSERT INTO facts(file, concept, context, period_end, value, unit)"
                " VALUES (?,?,?,?,?,'INR')",
                (file, "SegmentRevenue", context, dict(
                    (f, p) for f, _, p in filings)[file], value),
            )
    xb.commit()
    xb.close()


class UniverseBuilderTests(unittest.TestCase):
    def setUp(self):
        self.root = _case_dir()
        _fixture(self.root)
        self.out = self.root / "out.db"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self) -> dict:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = builder.main(["--db", str(self.out), "--data-root", str(self.root),
                                 "--themes", str(builder.DEFAULT_THEMES)])
        self.assertEqual(code, 0)
        return json.loads(buf.getvalue().splitlines()[0])

    def _members(self):
        con = sqlite3.connect(self.out)
        try:
            return con.execute(
                "SELECT theme, isin, valid_from, valid_to, weight, method, pivot, evidence_id"
                " FROM universe_membership WHERE isin = ?", (ACME,)).fetchall()
        finally:
            con.close()

    def test_join_pivot_and_exit_dates(self):
        self._run()
        rows = self._members()
        self.assertEqual(len(rows), 1)
        theme, isin, valid_from, valid_to, weight, method, pivot, evidence = rows[0]
        self.assertEqual(theme, "gold_jewellery_finance")
        self.assertEqual(isin, ACME)
        self.assertEqual(valid_from, "2025-10-10")   # the quarter the segment appeared
        self.assertEqual(valid_to, "2026-04-10")     # 2nd consecutive zero quarter
        self.assertAlmostEqual(weight, 0.9, places=4)
        self.assertEqual(method, "segment")
        self.assertEqual(pivot, 1)
        self.assertIn("Gold Jewellery", evidence)
        con = sqlite3.connect(self.out)
        try:
            joins, exits, pivots = con.execute(
                "SELECT joins, exits, pivots FROM universe_membership_runs").fetchone()
        finally:
            con.close()
        key = ["gold_jewellery_finance", ACME]
        self.assertIn(key, json.loads(joins))
        self.assertEqual(json.loads(exits), [])  # it exited within this same build
        self.assertIn(key, json.loads(pivots))

    def test_rebuild_is_idempotent(self):
        self._run()
        second = self._run()
        self.assertEqual(second["members"], 1)
        self.assertEqual(self._members()[0][2], "2025-10-10")
        con = sqlite3.connect(self.out)
        try:
            joins, exits = con.execute(
                "SELECT joins, exits FROM universe_membership_runs"
                " ORDER BY built_at DESC, run_id DESC").fetchone()
        finally:
            con.close()
        self.assertFalse(json.loads(joins))
        self.assertFalse(json.loads(exits))


if __name__ == "__main__":
    unittest.main()
