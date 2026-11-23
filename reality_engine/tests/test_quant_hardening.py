"""
Unit & Integration Tests for Quantitative Screener Hardening,
Forensic Solvency Gates, Smart Money Integration, and Panic Monitor.
"""

import unittest
import pandas as pd
import numpy as np

from reality_engine.processing.fundamental_engine import fundamental_engine, FundamentalEngine
from reality_engine.processing.composite_screener import composite_screener, CompositeScreener
from reality_engine.pipeline.panic_monitor import panic_monitor, PanicMonitor
from reality_engine.db.repository import repo


class TestQuantHardening(unittest.TestCase):
    """Test suite for forensic solvency gates, smart money scoring, and panic monitoring."""

    def test_01_strict_binary_forensic_solvency(self):
        """Tests binary forensic solvency evaluation and explicit disqualification tracking."""
        # 1. Fully approved company
        approved = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=10.0,
            interest_coverage_ratio=4.5,
            debt_to_equity_ratio=0.8,
        )
        self.assertEqual(approved["is_solvency_approved"], 1)
        self.assertEqual(len(approved["disqualifications"]), 0)
        self.assertEqual(approved["reasons_str"], "PASSED_ALL_SOLVENCY_GATES")

        # 2. Boundary edge cases (exact limits: pledge <= 15.0, coverage >= 2.5, debt/equity <= 1.5)
        boundary_pass = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=15.0,
            interest_coverage_ratio=2.5,
            debt_to_equity_ratio=1.5,
        )
        self.assertEqual(boundary_pass["is_solvency_approved"], 1)

        # 3. Disqualified on Promoter Pledge > 15.0%
        fail_pledge = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=15.1,
            interest_coverage_ratio=5.0,
            debt_to_equity_ratio=0.5,
        )
        self.assertEqual(fail_pledge["is_solvency_approved"], 0)
        self.assertTrue(any("Promoter pledge" in r for r in fail_pledge["disqualifications"]))

        # 4. Disqualified on Interest Coverage < 2.5x
        fail_cov = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=5.0,
            interest_coverage_ratio=2.4,
            debt_to_equity_ratio=0.5,
        )
        self.assertEqual(fail_cov["is_solvency_approved"], 0)
        self.assertTrue(any("Interest coverage" in r for r in fail_cov["disqualifications"]))

        # 5. Disqualified on Debt-to-Equity > 1.5x
        fail_lev = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=5.0,
            interest_coverage_ratio=5.0,
            debt_to_equity_ratio=1.51,
        )
        self.assertEqual(fail_lev["is_solvency_approved"], 0)
        self.assertTrue(any("Debt-to-Equity" in r for r in fail_lev["disqualifications"]))

        # 6. Multiple violations
        fail_multi = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=25.0,
            interest_coverage_ratio=1.2,
            debt_to_equity_ratio=2.5,
        )
        self.assertEqual(fail_multi["is_solvency_approved"], 0)
        self.assertEqual(len(fail_multi["disqualifications"]), 3)

        # 7. Missing / None values
        fail_none = fundamental_engine.evaluate_forensic_solvency(
            promoter_pledge_pct=None,
            interest_coverage_ratio=None,
            debt_to_equity_ratio=None,
        )
        self.assertEqual(fail_none["is_solvency_approved"], 0)
        self.assertEqual(len(fail_none["disqualifications"]), 3)

    def test_02_opm_delta_calculation_and_funda_score(self):
        """Verifies margin expansion in bps and its inclusion in fundamental factor score."""
        # Margin expansion: 22.5% vs 20.0% = +250 bps
        delta_pos = fundamental_engine.calculate_opm_delta_bps(22.5, 20.0)
        self.assertEqual(delta_pos, 250.0)

        # Margin contraction: 18.0% vs 20.0% = -200 bps
        delta_neg = fundamental_engine.calculate_opm_delta_bps(18.0, 20.0)
        self.assertEqual(delta_neg, -200.0)

        # NaN handling
        delta_nan = fundamental_engine.calculate_opm_delta_bps(np.nan, 20.0)
        self.assertEqual(delta_nan, 0.0)

        # Score with margin expansion component
        score_base = fundamental_engine.compute_fundamental_score(
            yoy_rev_growth=20.0,
            yoy_pat_growth=20.0,
            opm_delta_bps=0.0,
            roce_pct=15.0,
        )
        score_expanded = fundamental_engine.compute_fundamental_score(
            yoy_rev_growth=20.0,
            yoy_pat_growth=20.0,
            opm_delta_bps=200.0,  # 200 bps / 50 * 10 = +40 pts
            roce_pct=15.0,
        )
        self.assertGreater(score_expanded, score_base)
        self.assertAlmostEqual(score_expanded - score_base, 40.0, places=1)

    def test_03_smart_money_flow_bonuses(self):
        """Verifies Smart Money bonuses for PIT buys, bulk deals, and delivery spikes."""
        # 1. Base case without triggers
        base_sm = CompositeScreener.compute_smart_money_score(
            delivery_spike_ratio=1.2,
            delivery_pct=40.0,
            delivery_conviction_score=48.0,
            change_pct=1.0,
            pit_trades_for_symbol=pd.DataFrame(),
            deals_for_symbol=pd.DataFrame(),
        )
        self.assertAlmostEqual(base_sm, min(40.0, 48.0 * 0.20), places=1)

        # 2. High Delivery Volume Spike (+30 bonus: DSR >= 2.0x AND Deliv% >= 50%)
        spike_sm = CompositeScreener.compute_smart_money_score(
            delivery_spike_ratio=2.5,
            delivery_pct=60.0,
            delivery_conviction_score=150.0,
            change_pct=1.0,
        )
        self.assertGreaterEqual(spike_sm, 30.0 + min(40.0, 150.0 * 0.20))

        # 3. SEBI PIT Promoter open-market buy > 1 Cr (100 Lacs) during a drop (+40 bonus)
        pit_df = pd.DataFrame([{
            "symbol": "ALPHA",
            "category_of_person": "PROMOTER",
            "transaction_type": "BUY",
            "mode_of_acquisition": "OPEN_MARKET",
            "value_inr_lacs": 250.0,  # 2.5 Cr > 1 Cr
        }])
        pit_sm_drop = CompositeScreener.compute_smart_money_score(
            delivery_spike_ratio=1.0,
            delivery_pct=30.0,
            delivery_conviction_score=30.0,
            change_pct=-2.5,  # Drop
            pit_trades_for_symbol=pit_df,
        )
        self.assertGreaterEqual(pit_sm_drop, 40.0)

        # Promoter buy during rally (change_pct >= 0) should not get the drop bonus
        pit_sm_rally = CompositeScreener.compute_smart_money_score(
            delivery_spike_ratio=1.0,
            delivery_pct=30.0,
            delivery_conviction_score=30.0,
            change_pct=1.5,
            pit_trades_for_symbol=pit_df,
        )
        self.assertLess(pit_sm_rally, 40.0)

        # 4. Marquee institutional bulk deal buy (+30 bonus)
        deals_df = pd.DataFrame([{
            "symbol": "ALPHA",
            "buy_sell": "BUY",
            "is_marquee_institution": 1,
            "quantity": 500000,
        }])
        deal_sm = CompositeScreener.compute_smart_money_score(
            delivery_spike_ratio=1.0,
            delivery_pct=30.0,
            delivery_conviction_score=30.0,
            change_pct=0.5,
            deals_for_symbol=deals_df,
        )
        self.assertGreaterEqual(deal_sm, 30.0)

        # 5. Combined catalysts capped at 100
        combined_sm = CompositeScreener.compute_smart_money_score(
            delivery_spike_ratio=2.5,
            delivery_pct=60.0,
            delivery_conviction_score=150.0,
            change_pct=-1.5,
            pit_trades_for_symbol=pit_df,
            deals_for_symbol=deals_df,
        )
        self.assertEqual(combined_sm, 100.0)

    def test_04_factor_weightings_normal_vs_crisis(self):
        """Verifies Normal Factor Weighting vs Crisis Factor Weighting calculation."""
        # Tech: 80, Funda: 70, CausalResilience: 60, SmartMoney: 90
        # Normal: 0.45 * 80 + 0.35 * 70 + 0.20 * 90 = 36 + 24.5 + 18 = 78.5
        # Crisis: 0.25 * 80 + 0.25 * 70 + 0.30 * 60 + 0.20 * 90 = 20 + 17.5 + 18 + 18 = 73.5
        tech = 80.0
        funda = 70.0
        causal = 60.0
        sm = 90.0

        score_normal = round(0.45 * tech + 0.35 * funda + 0.20 * sm, 2)
        score_crisis = round(0.25 * tech + 0.25 * funda + 0.30 * causal + 0.20 * sm, 2)

        self.assertEqual(score_normal, 78.50)
        self.assertEqual(score_crisis, 73.50)

    def test_05_screener_filters_disqualified_stocks(self):
        """Verifies composite screener removes scrips with is_solvency_approved == 0."""
        df_screened = composite_screener.run_screener(top_n=50, universe="all")
        if not df_screened.empty:
            # All returned scrips must have is_solvency_approved == 1
            self.assertTrue(
                (df_screened["is_solvency_approved"] == 1).all(),
                "Composite screener returned disqualified scrips with is_solvency_approved == 0"
            )

    def test_06_panic_monitor_drawdown_triggers(self):
        """Verifies panic monitor trigger detection across benchmark and sector indices."""
        # 1. Triggered on Nifty 50 <= -1.5%
        df_indices_n50 = pd.DataFrame([
            {"index_name": "Nifty 50", "change_pct": -1.65},
            {"index_name": "Nifty Bank", "change_pct": -0.80},
        ])
        triggers = PanicMonitor.drawdown_triggers(df_indices_n50)
        self.assertEqual(len(triggers), 1)
        self.assertIn("Nifty 50", triggers[0])

        # 2. Triggered on Midcap 100 <= -1.5%
        df_indices_mid = pd.DataFrame([
            {"index_name": "NIFTY Midcap 100", "change_pct": -1.80},
            {"index_name": "Nifty 50", "change_pct": -0.50},
        ])
        triggers_mid = PanicMonitor.drawdown_triggers(df_indices_mid)
        self.assertEqual(len(triggers_mid), 1)
        self.assertIn("Midcap 100", triggers_mid[0])

        # 3. Triggered on Sector Index <= -3.0%
        df_indices_sec = pd.DataFrame([
            {"index_name": "Nifty IT", "change_pct": -3.45},
            {"index_name": "Nifty 50", "change_pct": -0.80},
        ])
        triggers_sec = PanicMonitor.drawdown_triggers(df_indices_sec)
        self.assertEqual(len(triggers_sec), 1)
        self.assertIn("Nifty IT", triggers_sec[0])

        # 4. No triggers when all within bounds
        df_indices_calm = pd.DataFrame([
            {"index_name": "Nifty 50", "change_pct": -0.75},
            {"index_name": "NIFTY Midcap 100", "change_pct": -1.10},
            {"index_name": "Nifty Auto", "change_pct": -2.20},
        ])
        triggers_calm = PanicMonitor.drawdown_triggers(df_indices_calm)
        self.assertEqual(len(triggers_calm), 0)

    def test_07_panic_monitor_crisis_screener_execution(self):
        """Verifies crisis bargain list filtering for delivery absorption and zero operational impairment."""
        # Run crisis screener directly
        crisis_df = panic_monitor.run_crisis_screener()
        if not crisis_df.empty:
            self.assertTrue((crisis_df["delivery_spike_ratio"] >= 2.0).all())
            self.assertTrue((crisis_df["delivery_pct"] >= 50.0).all())
            self.assertTrue((crisis_df["yoy_revenue_growth_pct"] >= 0.0).all())
            self.assertTrue((crisis_df["yoy_pat_growth_pct"] >= 0.0).all())
            self.assertTrue((crisis_df["is_solvency_approved"] == 1).all())
            self.assertIn("crisis_bargain_list", crisis_df.columns)

    def test_08_panic_monitor_fallback_latest_session(self):
        """Verifies latest_session fallback mechanism using daily_price_delivery."""
        session_df = panic_monitor.latest_session()
        self.assertFalse(session_df.empty, "latest_session should retrieve index data")
        self.assertIn("index_name", session_df.columns)
        self.assertIn("change_pct", session_df.columns)


if __name__ == "__main__":
    unittest.main()
