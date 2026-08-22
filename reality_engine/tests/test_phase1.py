"""
Unit & Integration Test Suite for Phase 1 Reality Engine
Verifies Database WAL mode, Master Synchronization, Technical Flow Analytics,
Fundamental Acceleration, Forensic Solvency Gates, Composite Screening, and Checkpoint Validation.
"""

import unittest
from pathlib import Path
import pandas as pd
import numpy as np

from reality_engine.db.database import db_manager
from reality_engine.db.repository import repo
from reality_engine.processing.technical_engine import technical_engine
from reality_engine.processing.fundamental_engine import fundamental_engine
from reality_engine.processing.composite_screener import composite_screener
from reality_engine.pipeline.phase1_runner import phase1_runner


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

    def test_05_top_200_reality_checkpoint(self):
        """Validates that all Top 200 stocks have complete technical and fundamental data."""
        summary = phase1_runner.validate_top_200_checkpoint()
        self.assertTrue(summary["checkpoint_passed"], "Phase 1 Checkpoint must pass with >=95% complete data")
        self.assertEqual(summary["target_universe_count"], 200)
        self.assertEqual(summary["technical_data_complete_count"], 200)
        self.assertEqual(summary["fundamental_data_complete_count"], 200)


if __name__ == "__main__":
    unittest.main()
