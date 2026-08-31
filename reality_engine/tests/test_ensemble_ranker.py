"""
Wave D1 — MoE ensemble_ranker deterministic tests.

Covers (per tasks/next_wave_execution_plan.md §2 Wave D Task D1 acceptance):
  - model_explainer_rankings + lens_activation_log tables are created (idempotent).
  - upsert_ranking persists and ranks rows within a (stock/sector/geo/regime/investor) partition.
  - lens_activation_log audits every run; temperature controls how many lenses fire.
  - get_ensemble_weights returns a complete (Σ==1, each >0) dict, per-investor-majority
    conditional (HAL FII vs HAL retail differ), bootstrap fallback when no learned rows.
  - rank_models(symbol, investor_majority) is queryable and joins ensemble weights.
  - Competitive survival: adjust_explain_power nudges explanation_weight and flips rank.
  - composite_screener.get_ensemble_weights delegates to the ranker via repository.

Uses throwaway temp SQLite DBs; never touches the live default DB.
"""

import os
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.processing.ensemble_ranker import (
    BOOTSTRAP_ENSEMBLE_WEIGHTS,
    INVESTOR_MAJORITIES,
    LENS_FAMILIES,
    EnsembleRanker,
)


def _seed_hal_fii(ranker: EnsembleRanker):
    """Seed all four lens families for HAL under FII with factor-dominant weights."""
    ranker.upsert_ranking("HAL", None, None, None, "FII", "factor_statistical", 0.01, 0.90)
    ranker.upsert_ranking("HAL", None, None, None, "FII", "business_quality", 0.04, 0.10)
    ranker.upsert_ranking("HAL", None, None, None, "FII", "policy_macro", 0.20, 0.10)
    ranker.upsert_ranking("HAL", None, None, None, "FII", "supply_chain", 0.10, 0.10)


def _seed_hal_retail(ranker: EnsembleRanker):
    """Seed all four lens families for HAL under retail with policy-dominant weights."""
    ranker.upsert_ranking("HAL", None, None, None, "retail", "factor_statistical", 0.05, 0.10)
    ranker.upsert_ranking("HAL", None, None, None, "retail", "business_quality", 0.07, 0.10)
    ranker.upsert_ranking("HAL", None, None, None, "retail", "policy_macro", 0.01, 0.70)
    ranker.upsert_ranking("HAL", None, None, None, "retail", "supply_chain", 0.12, 0.10)


class TestEnsembleRankerSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mgr = DatabaseManager(Path(self.tmp.name))
        self.r = EnsembleRanker(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_ensure_schema_creates_tables_idempotent(self):
        self.r.ensure_schema()
        with self.mgr.session() as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            self.assertIn("model_explainer_rankings", tables)
            self.assertIn("lens_activation_log", tables)
        # Idempotent: second call must not raise.
        self.r.ensure_schema()
        # Investor + lens family CHECK constraints enforced.
        with self.mgr.session() as conn:
            with self.assertRaises(Exception):
                conn.execute(
                    "INSERT INTO model_explainer_rankings (stock_id, investor_majority, lens_family) "
                    "VALUES ('X', 'ALIEN', 'factor_statistical')"
                )
            with self.assertRaises(Exception):
                conn.execute(
                    "INSERT INTO model_explainer_rankings (stock_id, investor_majority, lens_family) "
                    "VALUES ('X', 'FII', 'unknown_lens')"
                )


class TestRankOrdering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mgr = DatabaseManager(Path(self.tmp.name))
        self.r = EnsembleRanker(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_upsert_and_rank_ordering(self):
        # Insert in scrambled order; rank must reflect explain_power DESC.
        self.r.upsert_ranking("HAL", None, None, None, "FII", "policy_macro", 0.2, 0.10)
        self.r.upsert_ranking("HAL", None, None, None, "FII", "factor_statistical", 0.01, 0.90)
        self.r.upsert_ranking("HAL", None, None, None, "FII", "supply_chain", 0.1, 0.10)
        self.r.upsert_ranking("HAL", None, None, None, "FII", "business_quality", 0.04, 0.40)

        rows = self.r.get_rankings("HAL", "FII")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["lens_family"], "factor_statistical")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["explain_power"], 0.90)
        self.assertEqual(rows[-1]["rank"], 4)

        # Re-upsert an existing lens with a higher score; ranks must recompute.
        self.r.upsert_ranking("HAL", None, None, None, "FII", "policy_macro", 0.2, 0.95)
        rows = self.r.get_rankings("HAL", "FII")
        fams = [r["lens_family"] for r in rows]
        self.assertEqual(fams[0], "policy_macro")  # now top
        self.assertEqual(rows[0]["explain_power"], 0.95)


class TestActivationLogTemperature(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mgr = DatabaseManager(Path(self.tmp.name))
        self.r = EnsembleRanker(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_temperature_controls_fired_count(self):
        # No learned rows => bootstrap scores (tie) => deterministic canonical ordering.
        low = self.r.fire_lenses(0.0, context={"stock": "HAL", "investor_majority": "FII"})
        high = self.r.fire_lenses(1.0, context={"stock": "HAL", "investor_majority": "FII"})
        # Low temp (exploit) fires the top 2; high temp (explore) fires all 4.
        self.assertEqual(low["n_fired"], 2)
        self.assertEqual(high["n_fired"], 4)
        self.assertLess(low["n_fired"], high["n_fired"])

    def test_activation_log_audited_per_run(self):
        self.r.fire_lenses(0.3, context={"stock": "HAL", "investor_majority": "FII"})
        self.r.fire_lenses(0.9, context={"stock": "HAL", "investor_majority": "FII"})
        log = self.r.get_activation_log(limit=10)
        self.assertEqual(len(log), 2)
        # Most recent first.
        self.assertEqual(log[0]["temperature"], 0.9)
        self.assertEqual(log[1]["temperature"], 0.3)
        # fired_lenses payload is a parsed list.
        self.assertIsInstance(log[0]["fired_lenses_parsed"], list)
        self.assertIn(log[0]["fired_lenses_parsed"][0], LENS_FAMILIES)
        # Context is persisted for audit.
        self.assertEqual(log[0]["context_parsed"].get("stock"), "HAL")

    def test_fire_lenses_is_deterministic(self):
        a = self.r.fire_lenses(0.7, context={"stock": "HAL", "investor_majority": "FII"}, seed=12345)
        b = self.r.fire_lenses(0.7, context={"stock": "HAL", "investor_majority": "FII"}, seed=12345)
        self.assertEqual(a["fired_lenses"], b["fired_lenses"])


class TestEnsembleWeights(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mgr = DatabaseManager(Path(self.tmp.name))
        self.r = EnsembleRanker(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_bootstrap_fallback_complete(self):
        weights = self.r.compute_ensemble_weights(stock="HAL", investor="FII")
        self.assertEqual(set(weights.keys()), set(LENS_FAMILIES))
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        for w in weights.values():
            self.assertGreater(w, 0.0)
        # Matches the documented bootstrap.
        for f in LENS_FAMILIES:
            self.assertAlmostEqual(weights[f], BOOTSTRAP_ENSEMBLE_WEIGHTS[f], places=6)

    def test_conditional_per_investor_majority_differs(self):
        _seed_hal_fii(self.r)
        _seed_hal_retail(self.r)
        w_fii = self.r.compute_ensemble_weights(stock="HAL", investor="FII")
        w_retail = self.r.compute_ensemble_weights(stock="HAL", investor="retail")
        # Both complete.
        self.assertAlmostEqual(sum(w_fii.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(w_retail.values()), 1.0, places=6)
        for w in list(w_fii.values()) + list(w_retail.values()):
            self.assertGreater(w, 0.0)
        # FII is factor-dominant; retail is policy-dominant.
        self.assertGreater(w_fii["factor_statistical"], w_retail["factor_statistical"])
        self.assertGreater(w_retail["policy_macro"], w_fii["policy_macro"])
        self.assertNotEqual(w_fii, w_retail)

    def test_rank_models_queryable_with_weights(self):
        _seed_hal_fii(self.r)
        rows = self.r.rank_models("HAL", "FII")
        self.assertTrue(rows, "rank_models('HAL','FII') must return rows")
        self.assertEqual(rows[0]["lens_family"], "factor_statistical")
        for row in rows:
            self.assertIn("weight", row)
            self.assertGreater(row["weight"], 0.0)
        # Joined ensemble weight matches compute_ensemble_weights.
        w = self.r.compute_ensemble_weights(stock="HAL", investor="FII")
        for row in rows:
            self.assertAlmostEqual(row["weight"], w[row["lens_family"]], places=6)


class TestCompetitiveSurvival(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mgr = DatabaseManager(Path(self.tmp.name))
        self.r = EnsembleRanker(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_adjust_explain_power_flips_rank(self):
        self.r.upsert_ranking("HAL", None, None, None, "FII", "factor_statistical", 0.01, 0.10)
        self.r.upsert_ranking("HAL", None, None, None, "FII", "business_quality", 0.04, 0.90)
        before = self.r.get_rankings("HAL", "FII")
        self.assertEqual(before[0]["lens_family"], "business_quality")

        # EOD corrector reinforces factor_statistical past the leader.
        new_ep = self.r.adjust_explain_power(
            "HAL", None, None, None, "FII", "factor_statistical", delta=1.0
        )
        self.assertAlmostEqual(new_ep, 1.10)
        after = self.r.get_rankings("HAL", "FII")
        self.assertEqual(after[0]["lens_family"], "factor_statistical")
        self.assertEqual(after[0]["rank"], 1)

    def test_explain_power_floored_at_zero(self):
        self.r.upsert_ranking("HAL", None, None, None, "FII", "factor_statistical", 0.01, 0.10)
        new_ep = self.r.adjust_explain_power(
            "HAL", None, None, None, "FII", "factor_statistical", delta=-5.0
        )
        self.assertAlmostEqual(new_ep, 0.0)


class TestCompositeScreenerDelegation(unittest.TestCase):
    """composite_screener.get_ensemble_weights must delegate through repository -> ranker."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mgr = DatabaseManager(Path(self.tmp.name))
        from reality_engine.db.repository import repo
        self.repo = repo
        self._orig_db = self.repo.db
        self.repo.db = self.mgr  # point singleton at temp DB
        self.r = EnsembleRanker(self.mgr)

    def tearDown(self):
        self.repo.db = self._orig_db
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_composite_screener_uses_learned_weights(self):
        _seed_hal_fii(self.r)
        from reality_engine.processing.composite_screener import composite_screener
        weights = composite_screener.get_ensemble_weights(
            context={"stock_id": "HAL", "investor_majority": "FII"}
        )
        self.assertEqual(set(weights.keys()), set(LENS_FAMILIES))
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        # factor explain_power=0.90 of total 1.20 => 0.75
        self.assertAlmostEqual(weights["factor_statistical"], 0.90 / 1.20, places=6)
        self.assertGreater(weights["factor_statistical"], BOOTSTRAP_ENSEMBLE_WEIGHTS["factor_statistical"])


if __name__ == "__main__":
    unittest.main()
