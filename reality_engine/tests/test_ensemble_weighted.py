"""
Wave B3 — All-Peers Weighted Ensemble deterministic tests.

Covers (per tasks/next_wave_execution_plan.md §2 Wave B Task B3 acceptance):
  - Each lens-family weight > 0 and weights sum to 1.0
  - Normalization produces values in [0, 1]
  - Composite is a weighted *blend* (sum w*norm), NOT a max/funnel
  - Per-scrip learned noise floor is vol/liquidity adaptive (differs per symbol)
  - ensemble_screen on a temp SQLite returns a weighted blend, ranked correctly

Pure helper tests do not touch the live DB. The integration test swaps the
repository's DB manager for a throwaway temp SQLite and restores it afterwards.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import repo
from reality_engine.processing.composite_screener import (
    BOOTSTRAP_ENSEMBLE_WEIGHTS,
    ENSEMBLE_LENS_FAMILIES,
    CompositeScreener,
    composite_screener,
)


class TestEnsembleWeights(unittest.TestCase):
    """Lens-family weight contract (AGENTS.md §3 #3 — all four peers compete)."""

    def test_bootstrap_weights_positive_and_sum_to_one(self):
        self.assertEqual(set(BOOTSTRAP_ENSEMBLE_WEIGHTS.keys()), set(ENSEMBLE_LENS_FAMILIES))
        total = sum(BOOTSTRAP_ENSEMBLE_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=6)
        for fam, w in BOOTSTRAP_ENSEMBLE_WEIGHTS.items():
            self.assertGreater(w, 0.0, f"lens {fam} weight must be > 0")

    def test_get_ensemble_weights_normalizes_override(self):
        weights = composite_screener.get_ensemble_weights(
            override={"factor_statistical": 2, "business_quality": 2, "policy_macro": 1, "supply_chain": 1}
        )
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        for fam in ENSEMBLE_LENS_FAMILIES:
            self.assertGreater(weights[fam], 0.0)
        # factor(2) and quality(2) share the larger raw mass; policy(1)/supply(1) the rest
        self.assertAlmostEqual(weights["factor_statistical"], 2 / 6, places=6)
        self.assertAlmostEqual(weights["business_quality"], 2 / 6, places=6)
        self.assertAlmostEqual(weights["supply_chain"], 1 / 6, places=6)

    def test_get_ensemble_weights_default_falls_back_to_bootstrap(self):
        # No learned rows in repository -> deterministic bootstrap (repo call mocked).
        with mock.patch.object(repo, "get_ensemble_weights", return_value={}):
            weights = composite_screener.get_ensemble_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        for fam in ENSEMBLE_LENS_FAMILIES:
            self.assertGreater(weights[fam], 0.0)


class TestEnsembleNormalization(unittest.TestCase):
    """Norm(lens_score) must be in [0, 1] and robust to constant columns."""

    def test_normalize_produces_zero_one(self):
        df = pd.DataFrame({
            "lens_factor_statistical": [10.0, 50.0, 90.0],
            "lens_business_quality": [20.0, 20.0, 20.0],  # constant -> neutral 0.5
        })
        out = CompositeScreener._normalize_lens_scores(
            df, ["lens_factor_statistical", "lens_business_quality"]
        )
        self.assertAlmostEqual(out["norm_lens_factor_statistical"].min(), 0.0)
        self.assertAlmostEqual(out["norm_lens_factor_statistical"].max(), 1.0)
        self.assertAlmostEqual(float(out["norm_lens_business_quality"].iloc[0]), 0.5)


class TestEnsembleCompositeIsBlend(unittest.TestCase):
    """composite = Σ w*norm ; it is a blend, not a funnel/max gate."""

    def test_composite_weighted_blend_not_max(self):
        # Row1 strong only on factor; Row2 strong on the other three peers.
        df = pd.DataFrame({
            "symbol": ["AAA", "BBB"],
            "lens_factor_statistical": [100.0, 0.0],
            "lens_business_quality": [0.0, 100.0],
            "lens_policy_macro": [0.0, 100.0],
            "lens_supply_chain": [0.0, 100.0],
        })
        weights = composite_screener.get_ensemble_weights()  # bootstrap
        out = composite_screener.compute_ensemble_composite(df, weights=weights)
        c1 = float(out.loc[out["symbol"] == "AAA", "ensemble_composite"].iloc[0])
        c2 = float(out.loc[out["symbol"] == "BBB", "ensemble_composite"].iloc[0])
        # factor weight 0.30 -> AAA composite = 30; BBB = 0.25+0.25+0.20 = 0.70 -> 70
        self.assertAlmostEqual(c1, 30.0, places=1)
        self.assertAlmostEqual(c2, 70.0, places=1)
        # Blend, not max: AAA's composite is 30 (a blend), not the max raw norm (100).
        self.assertLess(c1, 100.0)
        # Weak-on-one-peer stock (BBB) still clears because the other peers carry weight.
        self.assertGreater(c2, c1)
        for fam in ENSEMBLE_LENS_FAMILIES:
            self.assertIn(f"weight_{fam}", out.columns)

    def test_compute_lens_scores_pure(self):
        df = pd.DataFrame({
            "symbol": ["X"],
            "technical_score": [80.0],
            "fundamental_score": [70.0],
            "alt_sentiment_score": [90.0],
            "total_moat_score": [4.0],   # -> 80 quality
            "policy_agg_eni": [1.0],     # -> 70 policy
        })
        out = composite_screener.compute_lens_scores(df)
        self.assertAlmostEqual(float(out["lens_factor_statistical"].iloc[0]), 0.40 * 80 + 0.35 * 70 + 0.25 * 90)
        self.assertAlmostEqual(float(out["lens_business_quality"].iloc[0]), 80.0)
        self.assertAlmostEqual(float(out["lens_policy_macro"].iloc[0]), 70.0)
        # supply falls back to neutral 50 when not supplied
        self.assertAlmostEqual(float(out["lens_supply_chain"].iloc[0]), 50.0)


class TestPerScripNoiseFloor(unittest.TestCase):
    """Per-scrip vol/liquidity-adaptive floor replaces the global hard cutoff."""

    def test_floor_adaptive_across_symbols(self):
        # Liquid, low-vol name -> low floor
        f_liquid = composite_screener.get_per_scrip_noise_floor("LIQ", turnover_lacs=2000.0, change_pct=0.2)
        # Illiquid, high-vol name -> higher floor
        f_illiquid = composite_screener.get_per_scrip_noise_floor("ILL", turnover_lacs=20.0, change_pct=6.0)
        self.assertGreater(f_illiquid, f_liquid)
        # Same symbol with different inputs is deterministic but distinct
        self.assertGreater(
            composite_screener.get_per_scrip_noise_floor("Z", turnover_lacs=10.0, change_pct=5.0),
            composite_screener.get_per_scrip_noise_floor("Z", turnover_lacs=1000.0, change_pct=0.1),
        )
        # Floor is clamped to a sane band
        clamped = composite_screener.get_per_scrip_noise_floor("X", turnover_lacs=0.0, change_pct=100.0)
        self.assertLessEqual(clamped, 80.0)
        self.assertGreaterEqual(clamped, 30.0)


class TestEnsembleScreenIntegration(unittest.TestCase):
    """Full ensemble_screen against a throwaway temp SQLite (no live DB touched)."""

    DATE = "2026-08-28"

    def setUp(self):
        self._orig_db = repo.db
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._mgr = DatabaseManager(Path(self._tmp.name))
        repo.db = self._mgr  # point the singleton repo at the temp DB
        self._seed()

    def tearDown(self):
        repo.db = self._orig_db
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _seed(self):
        repo.upsert_master_companies([
            {"isin": "INE001A", "nse_symbol": "AAA", "company_name": "Alpha", "industry": "Capital Goods", "sector": "Capital Goods", "is_nifty200": 1},
            {"isin": "INE002B", "nse_symbol": "BBB", "company_name": "Beta", "industry": "Information Technology", "sector": "Technology", "is_nifty200": 1},
            {"isin": "INE003C", "nse_symbol": "CCC", "company_name": "Gamma", "industry": "Metals & Mining", "sector": "Metals", "is_nifty200": 1},
        ])
        # Direct minimal inserts (repository upserts require every named binding; these
        # tables only need the NOT NULL subset for the ensemble screen to function).
        with repo.db.session() as conn:
            conn.executemany(
                """
                INSERT INTO quarterly_financials
                    (isin, symbol, quarter_end_date, financial_year,
                     yoy_revenue_growth_pct, yoy_pat_growth_pct, ebitda_margin_pct, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'yfinance')
                """,
                [
                    ("INE001A", "AAA", "2026-06-30", "FY27-Q1", 30.0, 30.0, 22.0),
                    ("INE002B", "BBB", "2026-06-30", "FY27-Q1", 12.0, 10.0, 18.0),
                    ("INE003C", "CCC", "2026-06-30", "FY27-Q1", 4.0, 2.0, 12.0),
                ],
            )
            conn.executemany(
                """
                INSERT INTO company_forensic_health
                    (isin, symbol, fiscal_year, promoter_pledge_pct,
                     interest_coverage_ratio, debt_to_equity_ratio, last_evaluated_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("INE001A", "AAA", "FY26", 5.0, 5.0, 0.5, "2026-06-30"),
                    ("INE002B", "BBB", "FY26", 8.0, 4.0, 0.7, "2026-06-30"),
                    ("INE003C", "CCC", "FY26", 10.0, 3.0, 0.9, "2026-06-30"),
                ],
            )
        repo.upsert_daily_price_delivery([
            self._price_row("AAA", "INE001A", close=100.0, dcs=120.0, rsi=62.0, change=1.0, turnover=800.0),
            self._price_row("BBB", "INE002B", close=200.0, dcs=60.0, rsi=55.0, change=0.5, turnover=800.0),
            self._price_row("CCC", "INE003C", close=50.0, dcs=20.0, rsi=45.0, change=-0.5, turnover=800.0),
        ])

    @staticmethod
    def _price_row(symbol, isin, close, dcs, rsi, change, turnover):
        return {
            "date": TestEnsembleScreenIntegration.DATE,
            "symbol": symbol,
            "isin": isin,
            "series": "EQ",
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "prev_close": close - change,
            "change_pct": change,
            "total_volume": 1_000_000,
            "deliverable_volume": 600_000,
            "delivery_pct": 60.0,
            "delivery_spike_ratio": dcs / 60.0,
            "delivery_conviction_score": dcs,
            "turnover_lacs": turnover,
            "num_trades": 50_000,
            "sma_20": close - 3.0,
            "sma_50": close - 5.0,
            "sma_200": close - 10.0,
            "rsi_14": rsi,
            "high_52w": close + 20.0,
            "low_52w": close - 30.0,
            "distance_from_52w_high_pct": 16.0,
        }

    def test_ensemble_screen_returns_weighted_blend_ranked(self):
        df = composite_screener.ensemble_screen(
            target_date=self.DATE,
            top_n=10,
            universe="all",
            min_turnover_lacs=0.0,
            noise_floor_override=0.0,  # isolate blend/sort from floor in this assertion
            persist=False,
        )
        self.assertFalse(df.empty, "ensemble_screen should return candidates from the temp DB")
        self.assertIn("ensemble_composite", df.columns)
        # Every lens family carried strictly positive weight in this run.
        for fam in ENSEMBLE_LENS_FAMILIES:
            self.assertIn(f"weight_{fam}", df.columns)
            self.assertGreater(float(df[f"weight_{fam}"].iloc[0]), 0.0)
        # Ranked by blended composite, descending (a blend, not funnel order).
        comp = df["ensemble_composite"].astype(float).tolist()
        self.assertEqual(comp, sorted(comp, reverse=True))
        # The blend is not merely the max raw lens (quality/policy/supply default ~50 -> norm 0.5)
        self.assertLess(float(df["ensemble_composite"].min()), 100.0)
        # attrs carry weights for audit
        self.assertAlmostEqual(sum(df.attrs.get("ensemble_weights", {}).values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
