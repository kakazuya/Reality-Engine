"""Wave A2 deterministic backfill test for moat + business model profiles.

Uses a fresh temp-file SQLite DB (not the live equity_intelligence.db) so the suite
never mutates production data. Verifies:
  1. Moat formula correctness (POLYPLEX 4/1/3/3/2 -> 2.65 Narrow per canonical formula).
  2. Persistence round-trip (moat_evaluations) with master_companies rowid resolution.
  3. business_profiler archetype write/read (business_model_profiles).
  4. backfill_top_n seeds >= 20 deterministic rows (Top-20 fallback).
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.moat_scorer import (
    MoatScores,
    score_from_text,
    backfill_top_n,
    score_and_persist,
)
from reality_engine.processing import business_profiler


class TestMoatBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="moat_backfill_"))
        self.db_path = self.tmp / "moat_test.db"
        self.mgr = DatabaseManager(db_path=self.db_path)
        self.repo = Repository(manager=self.mgr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def test_01_moat_formula(self):
        ms = MoatScores(4, 1, 3, 3, 2)
        # Canonical formula: 0.25*4 + 0.25*1 + 0.20*3 + 0.20*3 + 0.10*2 = 2.65
        self.assertEqual(ms.total(), 2.65)
        self.assertEqual(ms.width(), "Narrow")
        # HAL 4/3/4/4/3 -> 3.65 Wide (>=3.5)
        hal = MoatScores(4, 3, 4, 4, 3)
        self.assertEqual(hal.total(), 3.65)
        self.assertEqual(hal.width(), "Wide")

    def test_02_score_from_text_deterministic(self):
        a = score_from_text("switching cost network effect cost advantage brand efficient scale")
        b = score_from_text("switching cost network effect cost advantage brand efficient scale")
        self.assertEqual(a, b)
        self.assertIsInstance(a.total(), float)

    def test_03_persist_roundtrip(self):
        # Seed master_companies so company_id resolves to rowid.
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) "
                "VALUES (?,?,?,1)", ("INE123X01010", "HAL", "Hindustan Aeronautics")
            )
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) "
                "VALUES (?,?,?,1)", ("INE456X01010", "POLYPLEX", "Polyplex")
            )

        self.repo.ensure_moat_schema()
        self.repo.upsert_moat_evaluation(
            ticker="HAL", switching_costs=4, network_effects=3, cost_advantage=4,
            intangible_assets=4, efficient_scale=3, moat_trajectory="Stable",
            isin="INE123X01010",
        )
        self.repo.upsert_moat_evaluation(
            ticker="POLYPLEX", switching_costs=4, network_effects=1, cost_advantage=3,
            intangible_assets=3, efficient_scale=2, moat_trajectory="Stable",
            isin="INE456X01010",
        )

        hal = self.repo.get_moat_evaluation("HAL")
        poly = self.repo.get_moat_evaluation("POLYPLEX")
        self.assertIsNotNone(hal)
        self.assertIsNotNone(poly)
        self.assertEqual(hal["total_moat_score"], 3.65)
        self.assertEqual(hal["moat_width"], "Wide")
        self.assertEqual(hal["moat_trajectory"], "Stable")
        # company_id resolved from master rowid (a positive integer)
        self.assertTrue(isinstance(hal["company_id"], int) and hal["company_id"] > 0)
        self.assertEqual(poly["total_moat_score"], 2.65)
        self.assertEqual(poly["moat_width"], "Narrow")

        # list helper returns both
        self.assertEqual(len(self.repo.list_moat_evaluations()), 2)

    def test_04_score_and_persist(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) "
                "VALUES (?,?,?,1)", ("INE789X01010", "RELIANCE", "Reliance Industries")
            )
        self.repo.ensure_moat_schema()
        total, width = score_and_persist(
            "RELIANCE", "INE789X01010", MoatScores(5, 5, 4, 5, 4), trajectory="Expanding",
            r=self.repo,
        )
        self.assertEqual(total, 4.70)
        self.assertEqual(width, "Wide")
        row = self.repo.get_moat_evaluation("RELIANCE")
        self.assertEqual(row["moat_trajectory"], "Expanding")

    def test_05_business_profile_write_read(self):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) "
                "VALUES (?,?,?,1)", ("INE123X01010", "HAL", "Hindustan Aeronautics")
            )
        self.repo.ensure_business_profile_schema()
        business_profiler.upsert_business_profile(
            symbol="HAL", archetype="Tollbooth", recurrence=85, pricing_power=5,
            capital_intensity=4, operating_leverage=3,
            notes="Defence OEM tollbooth", isin="INE123X01010", r=self.repo,
        )
        prof = self.repo.get_business_model_profile("HAL")
        self.assertIsNotNone(prof)
        self.assertEqual(prof["archetype"], "Tollbooth")
        self.assertEqual(prof["revenue_recurrence_pct"], 85)
        self.assertEqual(prof["pricing_power_score"], 5)
        self.assertEqual(prof["capital_intensity_score"], 4)
        self.assertEqual(prof["operating_leverage_score"], 3)

        # Invalid archetype must be rejected by the CHECK constraint.
        with self.assertRaises(Exception):
            self.repo.upsert_business_model_profile(
                symbol="BAD", archetype="NotARealArchetype", revenue_recurrence_pct=10,
                pricing_power_score=1, capital_intensity_score=1, operating_leverage_score=1,
                r=self.repo,
            )

    def test_06_backfill_top_n_seeds_top20(self):
        self.repo.ensure_moat_schema()
        self.repo.ensure_business_profile_schema()
        counts = backfill_top_n(top=20, r=self.repo)
        # Catalog has 25 curated names; backfill seeds all (>=20) deterministically.
        self.assertGreaterEqual(counts["moat"], 20)
        self.assertGreaterEqual(counts["business_profile"], 20)

        # POLYPLEX present and stored with the documented scores -> 2.65 Narrow.
        poly = self.repo.get_moat_evaluation("POLYPLEX")
        self.assertIsNotNone(poly)
        self.assertEqual(poly["total_moat_score"], 2.65)
        self.assertEqual(poly["moat_width"], "Narrow")

        # archetype written for seeded names
        hal = self.repo.get_business_model_profile("HAL")
        self.assertEqual(hal["archetype"], "Tollbooth")
        poly_p = self.repo.get_business_model_profile("POLYPLEX")
        self.assertEqual(poly_p["archetype"], "Asset-Heavy OEM")

        # Idempotent re-run must not error and yields same counts.
        counts2 = backfill_top_n(top=20, r=self.repo)
        self.assertEqual(counts2["moat"], counts["moat"])

    def test_07_business_profiler_seed(self):
        res = business_profiler.seed_business_profiles(top=20, r=self.repo)
        self.assertGreaterEqual(res["business_profile"], 20)
        self.assertGreaterEqual(res["moat"], 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
