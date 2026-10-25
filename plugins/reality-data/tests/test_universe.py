"""ETF/MF identity resolution and the point-in-time universe tool.

Run from the repo root:
    python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PLUGIN_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

# The harness TMP dir (and any ``tmp*`` directory) is ACL-denied; use a local one.
_TMP_ROOT = Path(__file__).resolve().parents[3] / ".tmp_universe_tests"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _case_dir() -> Path:
    path = _TMP_ROOT / f"case_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    path.mkdir()
    return path

import core  # noqa: E402
import universe as universe_mod  # noqa: E402


class FundResolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.warm()

    def test_etf_by_bse_code_symbol_and_isin(self):
        for query in ("543437", "MONQ50", "INF247L01AU3"):
            with self.subTest(query=query):
                out = core.resolve(query)
                match = next((m for m in out["matches"] if m["isin"] == "INF247L01AU3"), None)
                self.assertIsNotNone(match, f"{query} did not resolve to MONQ50")
                self.assertEqual(match["kind"], "etf")
                self.assertEqual(match["nse_symbol"], "MONQ50")
                self.assertIn("Motilal", match["name"])
        self.assertEqual(core.resolve_one("543437")["isin"], "INF247L01AU3")
        self.assertIn("funds", core.resolve("MONQ50")["provenance"])

    def test_equity_keeps_kind_equity(self):
        self.assertEqual(core.resolve("PPL")["matches"][0]["kind"], "equity")


class UniverseToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _case_dir()
        path = self.tmp / "equity_intelligence.db"
        con = sqlite3.connect(path)
        con.executescript(
            "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, bse_code TEXT, company_name TEXT);"
            "CREATE TABLE universe_membership(theme TEXT, isin TEXT, symbol TEXT, valid_from TEXT,"
            " valid_to TEXT, weight REAL, method TEXT, evidence_id TEXT, evidence_quote TEXT,"
            " pivot INTEGER, built_at TEXT);"
            "CREATE TABLE universe_membership_runs(run_id TEXT, built_at TEXT, joins TEXT,"
            " exits TEXT, pivots TEXT, report_json TEXT);"
        )
        con.executemany("INSERT INTO master_companies VALUES (?,?,?,?)", [
            ("INE467B01029", "TCS", "532540", "Tata Consultancy Services"),
            ("INE040A01034", "HDFCBANK", "500180", "HDFC Bank"),
        ])
        today = dt.date.today()
        built = (today - dt.timedelta(days=2)).isoformat()
        con.executemany(
            "INSERT INTO universe_membership VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("omc_refining", "INE467B01029", "TCS", "2024-01-01", None, 0.4, "segment",
                 "results_xbrl.db:facts:x:Refining:2024-03-31", "Refining = 40%", 1, built),
                ("omc_refining", "INE242A01010", "IOC", "2024-01-01", "2024-06-30", 0.9, "segment",
                 "results_xbrl.db:facts:y:Refining:2023-12-31", "Refining = 90%", 0, built),
                ("omc_refining", "INE040A01034", "HDFCBANK", "2025-01-01", None, 0.7, "industry",
                 "equity_intelligence.db:company_industry:INE040A01034", "Petroleum Products", 0, built),
                ("omc_refining", "INE029A01011", "BPCL", "2024-01-01", None, 0.2, "industry",
                 "equity_intelligence.db:company_industry:INE029A01011", "Refineries & Marketing", 0, built),
            ],
        )
        con.execute("INSERT INTO universe_membership_runs VALUES (?,?,?,?,?,?)",
                    ("r1", built, "[]", "[]", "[]", "{}"))
        con.commit()
        con.close()
        self._old = core.DB_FILES["equity_intelligence"]
        core.close_all()
        core.DB_FILES["equity_intelligence"] = path

    def tearDown(self):
        core.close_all()
        core.DB_FILES["equity_intelligence"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_point_in_time_members_sorted_by_weight(self):
        out = universe_mod.universe("omc_refining", as_of="2024-09-01")
        self.assertTrue(out["found"])
        self.assertEqual([m["isin"] for m in out["members"]],
                         ["INE467B01029", "INE029A01011"])  # exited IOC and future HDFCBANK excluded
        self.assertEqual(out["members"][0]["symbol"], "TCS")
        self.assertTrue(out["members"][0]["pivot"])
        self.assertEqual(out["stale_days"], 2)
        self.assertEqual(out["members"][0]["since"], "2024-01-01")
        self.assertIn("evidence_id", out["members"][0])

    def test_min_weight_and_unknown_theme(self):
        out = universe_mod.universe("omc_refining", as_of="2024-09-01", min_weight=0.3)
        self.assertEqual([m["symbol"] for m in out["members"]], ["TCS"])
        miss = universe_mod.universe("gold_jewelry_finance", as_of="2024-09-01")
        self.assertFalse(miss["found"])
        self.assertIn("gold_jewellery_finance", miss["closest_themes"])

    def test_known_theme_without_rows(self):
        out = universe_mod.universe("dairy", as_of="2024-09-01")
        self.assertTrue(out["found"])
        self.assertEqual(out["members"], [])


if __name__ == "__main__":
    unittest.main()
