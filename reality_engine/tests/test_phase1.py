"""
Unit & Integration Test Suite for Phase 1 Reality Engine
Verifies Database WAL mode, Master Synchronization, Technical Flow Analytics,
Fundamental Acceleration, Forensic Solvency Gates, Composite Screening, and Checkpoint Validation.

Live-data integration tests (opt-in)
-----------------------------------
`test_02_master_companies_universe` and `test_05_top_200_reality_checkpoint`
are NOT unit tests. They assert that the real production database holds >=200
`is_nifty200=1` master rows and that the Phase-1 Top-200 checkpoint passes at
>=95% technical/fundamental completeness. Those facts only exist in the
populated production DB (`reality_engine/data/equity_intelligence.db`), which
is built by `sync-master` + `backfill` + `run-phase1`.

The singleton-isolation redirect above (lines 24-27) intentionally points this
module at a throwaway temp DB so that merely importing the module cannot touch
the live 33 GB database. Against that temp DB the two live-data assertions are
meaningless -- they can only ever fail, and "fixing" them would mean weakening
real production assertions. So they are gated behind an explicit opt-in env
gate rather than run as unit tests.

Run them deliberately, against the populated production DB:

    # PowerShell
    $env:REALITY_ENGINE_INTEGRATION_TESTS = "1"
    $env:REALITY_ENGINE_DB_PATH = "C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\reality_engine\\data\\equity_intelligence.db"
    & "C:\\Users\\warri\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" -m unittest reality_engine.tests.test_phase1 -v

Note the `os.environ.setdefault` above honours a pre-set REALITY_ENGINE_DB_PATH,
so setting it explicitly is what actually points the gate-enabled run at the
live DB. When REALITY_ENGINE_INTEGRATION_TESTS is unset (the default) both tests
report as SKIPPED and the rest of the suite runs against the temp DB.
"""

import os
import tempfile
import unittest
from pathlib import Path
import pandas as pd
import numpy as np

# Singleton isolation (repo convention: test_factor_spine.py:36-48,
# test_onnx_embedder.py:21-24, test_offer_backfill.py:21-24, ...).
# reality_engine/db/database.py:639 runs `db_manager = DatabaseManager()` at
# IMPORT time, and DatabaseManager.__init__ -> init_db() applies PRAGMAs and
# CREATE TABLE IF NOT EXISTS (database.py:94, :635) to config.DB_PATH. Without
# this redirect, merely importing reality_engine.db.database below writes to the
# live 33 GB reality_engine/data/equity_intelligence.db -- a setUpModule
# singleton swap is too late, it runs after the import-time write has already
# happened. Must be set BEFORE any reality_engine import; config.py:14 honours
# it.
_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_phase1_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.db.database import db_manager  # noqa: E402
from reality_engine.db.repository import repo  # noqa: E402
from reality_engine.processing.technical_engine import technical_engine  # noqa: E402
from reality_engine.processing.fundamental_engine import fundamental_engine  # noqa: E402
from reality_engine.processing.composite_screener import composite_screener  # noqa: E402
from reality_engine.pipeline.phase1_runner import phase1_runner  # noqa: E402

# Opt-in gate for the live-data integration tests (see module docstring).
# Repo-wide there was no pre-existing skipUnless/INTEGRATION convention, so this
# establishes one using the same REALITY_ENGINE_* env prefix the DB-redirect
# convention already uses across reality_engine/tests/.
INTEGRATION_TESTS_ENABLED = os.environ.get(
    "REALITY_ENGINE_INTEGRATION_TESTS", ""
).strip() in ("1", "true", "TRUE", "yes", "on")

_INTEGRATION_SKIP_REASON = (
    "live-data integration test: requires the populated production DB "
    "(>=200 is_nifty200 rows). Set REALITY_ENGINE_INTEGRATION_TESTS=1 and "
    "REALITY_ENGINE_DB_PATH=<path to reality_engine/data/equity_intelligence.db> "
    "to run it."
)


class TestPhase1RealityEngine(unittest.TestCase):
    """Test suite for Phase 1 verification gates."""

    def setUp(self):
        self.repo = repo
        self.db = db_manager

    def test_01_database_tables_and_pragmas(self):
        """Verifies database schema initialization and WAL mode."""
        with self.db.session() as conn:
            # Check journal mode
            journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(journal.upper(), "WAL")

            # Check core tables exist
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
            table_names = [t[0] for t in tables]

            required_tables = [
                "master_companies",
                "daily_price_delivery",
                "quarterly_financials",
                "annual_financials",
                "company_forensic_health",
                "insider_trades",
                "bulk_block_deals",
                "nse_index_breadth",
                "eod_scrip_calls",
                "corporate_documents"
            ]
            for rt in required_tables:
                self.assertIn(rt, table_names, f"Table {rt} missing from SQLite schema")

    @unittest.skipUnless(INTEGRATION_TESTS_ENABLED, _INTEGRATION_SKIP_REASON)
    def test_02_master_companies_universe(self):
        """Verifies master companies are populated with Nifty 200 members."""
        nifty200 = self.repo.get_nifty200_companies()
        self.assertGreaterEqual(len(nifty200), 200, "Should have at least 200 Nifty 200 companies")
        
        # Check mandatory columns
        sample = nifty200[0]
        self.assertTrue(sample["isin"].startswith("INE"))
        self.assertTrue(len(sample["nse_symbol"]) > 0)
        self.assertEqual(sample["is_nifty200"], 1)

    def test_03_technical_indicators_calculation(self):
        """Verifies 20-day delivery SMA, Spike Ratio, DCS, and RSI calculations."""
        # Create synthetic time-series of 25 days
        dates = pd.date_range("2026-07-01", periods=25, freq="B").strftime("%Y-%m-%d").tolist()
        synthetic_df = pd.DataFrame({
            "date": dates,
            "symbol": ["TESTSTOCK"] * 25,
            "isin": ["INE999A01019"] * 25,
            "series": ["EQ"] * 25,
            "open": np.linspace(100, 150, 25),
            "high": np.linspace(105, 155, 25),
            "low": np.linspace(95, 145, 25),
            "close": np.linspace(100, 150, 25),
            "prev_close": np.linspace(98, 148, 25),
            "change_pct": [2.0] * 25,
            "total_volume": [100000] * 25,
            "turnover_lacs": [150.0] * 25,
            "num_trades": [2000] * 25,
            "deliverable_volume": [50000] * 24 + [150000],  # 3x spike on last day
            "delivery_pct": [50.0] * 24 + [75.0],
        })

        computed = technical_engine.calculate_indicators_for_symbol(synthetic_df)
        last_row = computed.iloc[-1]

        self.assertIsNotNone(last_row["delivery_spike_ratio"])
        self.assertGreater(last_row["delivery_spike_ratio"], 1.5, "Delivery spike ratio should exceed 1.5x")
        self.assertGreater(last_row["delivery_conviction_score"], 100.0, "DCS should reflect spike * deliv%")
        self.assertIsNotNone(last_row["rsi_14"])
        self.assertEqual(last_row["high_52w"], 155.0)

    def test_04_fundamental_scoring_and_solvency_gate(self):
        """Verifies fundamental acceleration formula and forensic solvency gate enforcement."""
        # Test solvency pass
        solvency_pass = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=5.0,
            interest_coverage_ratio=6.5,
            debt_to_equity_ratio=0.4
        )
        self.assertEqual(solvency_pass["is_solvency_approved"], 1)
        self.assertEqual(len(solvency_pass["disqualifications"]), 0)

        # Test solvency fail on pledge > 15%
        solvency_fail_pledge = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=25.0,
            interest_coverage_ratio=6.5,
            debt_to_equity_ratio=0.4
        )
        self.assertEqual(solvency_fail_pledge["is_solvency_approved"], 0)

        # Test solvency fail on interest coverage < 2.5x
        solvency_fail_cov = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=5.0,
            interest_coverage_ratio=2.1,
            debt_to_equity_ratio=0.4
        )
        self.assertEqual(solvency_fail_cov["is_solvency_approved"], 0)

        # Test solvency fail on debt to equity > 1.5x
        solvency_fail_lev = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=5.0,
            interest_coverage_ratio=6.5,
            debt_to_equity_ratio=1.8
        )
        self.assertEqual(solvency_fail_lev["is_solvency_approved"], 0)

        # Test OPM delta bps calculation
        opm_delta = fundamental_engine.calculate_opm_delta_bps(24.5, 22.0)
        self.assertEqual(opm_delta, 250.0)

        # Test fundamental growth score with margin expansion
        score = fundamental_engine.compute_fundamental_score(
            yoy_rev_growth=25.0,
            yoy_pat_growth=35.0,
            opm_delta_bps=120.0,
            roce_pct=22.0
        )
        self.assertGreaterEqual(score, 30.0)
        self.assertLessEqual(score, 100.0)

    @unittest.skipUnless(INTEGRATION_TESTS_ENABLED, _INTEGRATION_SKIP_REASON)
    def test_05_top_200_reality_checkpoint(self):
        """Validates that all Top 200 stocks have complete technical and fundamental data."""
        summary = phase1_runner.validate_top_200_checkpoint()
        self.assertTrue(summary["checkpoint_passed"], "Phase 1 Checkpoint must pass with >=95% complete data")
        self.assertEqual(summary["target_universe_count"], 200)
        self.assertEqual(summary["technical_data_complete_count"], 200)
        self.assertEqual(summary["fundamental_data_complete_count"], 200)


if __name__ == "__main__":
    unittest.main()
