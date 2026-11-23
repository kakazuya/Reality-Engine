"""
Test MoE all-universe deterministic seeding (opt-in full coverage).

Validates the additive full-universe path:
 - 3 master symbols: AAA (no substrate → all floors), BBB (partial moat only), CCC (fully seeded)
 - seed_universe_rankings(universe='all', manager=temp) → 60 rows = 3 × 5 × 4
 - 3 distinct stock_id, 20 rows/symbol, 5 investor cohorts, 4 lens families
 - rerun is idempotent (no duplicates)
 - compute_ensemble_weights / get_ensemble_weights sum to 1.0 even with floor values
 - CLI parser/help exposes --universe / --limit / --all-investor-cohorts (and seed-peers forwarding)

Uses isolated temp SQLite DBs; never touches the live production DB.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.ensemble_ranker import (
    BOOTSTRAP_ENSEMBLE_WEIGHTS,
    EXPLAIN_FLOOR,
    INVESTOR_MAJORITIES,
    LENS_FAMILIES,
    EnsembleRanker,
    seed_universe_rankings,
)


class TestMoeAllUniverse(unittest.TestCase):
    """Isolated temp-DB full-universe MoE seeding."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mgr = DatabaseManager(Path(self.tmp.name))
        self.repo = Repository(self.mgr)

        # Ensure all peer substrate tables exist in this fresh temp DB
        # (master_companies etc come from schema.sql via DatabaseManager.init_db;
        # the peer tables are SQLite-fallback DDL via repository helpers).
        self.repo.ensure_moat_schema(self.mgr)
        self.repo.ensure_business_profile_schema(self.mgr)
        self.repo.ensure_regulatory_political_risks_schema(self.mgr)
        self.repo.ensure_financial_metrics_schema(self.mgr)
        self.repo.ensure_geographic_exposure_schema(self.mgr)
        self.repo.ensure_ripple_effects_schema(self.mgr)
        self.repo.ensure_ensemble_ranking_schema(self.mgr)

        # 3 master symbols — ordered AAA < BBB < CCC deterministically
        # All active; no Nifty flags needed because universe='all' selects is_active=1.
        # Set is_nifty* to 0 to prove the full-universe path does not rely on flags.
        self.repo.upsert_master_companies([
            {"isin": "INE001A01001", "nse_symbol": "AAA", "company_name": "AAA Corp", "is_active": 1, "is_nifty200": 0, "is_nifty500": 0},
            {"isin": "INE002B01002", "nse_symbol": "BBB", "company_name": "BBB Corp", "is_active": 1, "is_nifty200": 0, "is_nifty500": 0},
            {"isin": "INE003C01003", "nse_symbol": "CCC", "company_name": "CCC Corp", "is_active": 1, "is_nifty200": 0, "is_nifty500": 0},
        ])
        with self.mgr.session() as conn:
            rows = conn.execute("SELECT rowid AS cid, isin, nse_symbol FROM master_companies ORDER BY nse_symbol ASC").fetchall()
            self.cid_map = {r["nse_symbol"]: int(r["cid"]) for r in rows}
            self.isin_map = {r["nse_symbol"]: r["isin"] for r in rows}

        # BBB — partial: moat only (quality substrate present, others floor)
        self.repo.upsert_moat_evaluation(
            ticker="BBB",
            switching_costs=3,
            network_effects=2,
            cost_advantage=3,
            intangible_assets=2,
            efficient_scale=2,
            moat_trajectory="Stable",
            isin=self.isin_map["BBB"],
            company_id=self.cid_map["BBB"],
            manager=self.mgr,
        )
        # Ensure BBB has NO policy/financial/geographic/ripple rows (floor path)

        # CCC — fully seeded: moat + policy + financial_metrics + geographic + ripple
        self.repo.upsert_moat_evaluation(
            ticker="CCC",
            switching_costs=5,
            network_effects=4,
            cost_advantage=5,
            intangible_assets=4,
            efficient_scale=3,
            moat_trajectory="Expanding",
            isin=self.isin_map["CCC"],
            company_id=self.cid_map["CCC"],
            manager=self.mgr,
        )
        self.repo.upsert_regulatory_political_risk(
            symbol="CCC",
            policy_name="POLICY_A",
            severity_score=4.0,
            probability=0.9,
            manager=self.mgr,
        )
        # Also add a second policy row to make ENI aggregation non-trivial
        self.repo.upsert_regulatory_political_risk(
            symbol="CCC",
            policy_name="POLICY_B",
            severity_score=-1.5,
            probability=0.6,
            manager=self.mgr,
        )
        self.repo.upsert_financial_metrics([
            {
                "company_id": self.cid_map["CCC"],
                "isin": self.isin_map["CCC"],
                "symbol": "CCC",
                "fiscal_year": 2025,
                "roic": 0.15,
                "wacc": 0.10,
                "roic_wacc_spread": 0.05,
                "fcf_margin": 0.12,
                "debt_to_ebitda": 1.2,
                "gross_margin_peer_percentile": 80,
            }
        ])
        self.repo.upsert_geographic_exposure(self.cid_map["CCC"], "IND", 70.0, 60.0, manager=self.mgr)
        self.repo.upsert_geographic_exposure(self.cid_map["CCC"], "USA", 30.0, 25.0, manager=self.mgr)
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO ripple_effects (event_id, target_company_id, order_level, significance_rank, transmission_elasticity, raw_magnitude, probability, lag_time_months) VALUES (?,?,?,?,?,?,?,?)",
                ("TEST_EVENT", self.cid_map["CCC"], 1, 55.0, 1.0, 0.10, 0.9, 0),
            )

        # AAA remains with no peer rows → all floor

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _count_rankings(self) -> int:
        with self.mgr.session() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM model_explainer_rankings").fetchone()
            return int(row["c"]) if row else 0

    def test_full_universe_creates_60_rows(self):
        result = seed_universe_rankings(universe="all", manager=self.mgr)
        self.assertEqual(result["symbols_seeded"], 3)
        self.assertEqual(result["rows_written"], 60)
        self.assertEqual(len(result["symbols_list"]), 3)
        self.assertListEqual(sorted(result["symbols_list"]), ["AAA", "BBB", "CCC"])
        self.assertEqual(self._count_rankings(), 60)

    def test_20_rows_per_symbol_5_cohorts_4_families(self):
        seed_universe_rankings(universe="all", manager=self.mgr)
        with self.mgr.session() as conn:
            rows = conn.execute("SELECT stock_id, investor_majority, lens_family FROM model_explainer_rankings").fetchall()
            self.assertEqual(len(rows), 60)
            stock_ids = {r["stock_id"] for r in rows}
            self.assertEqual(stock_ids, {"AAA", "BBB", "CCC"})
            # Per-symbol count = 20
            for sym in ("AAA", "BBB", "CCC"):
                with self.mgr.session() as c2:
                    cnt = c2.execute("SELECT COUNT(*) FROM model_explainer_rankings WHERE stock_id=?", (sym,)).fetchone()[0]
                    self.assertEqual(cnt, 20, f"{sym} should have 20 rows (5×4)")
            # Investor cohorts and lens families
            cohorts = {r["investor_majority"] for r in rows}
            fams = {r["lens_family"] for r in rows}
            self.assertEqual(cohorts, set(INVESTOR_MAJORITIES))
            self.assertEqual(fams, set(LENS_FAMILIES))
            # Each symbol has 5 cohorts × each cohort 4 families
            for sym in ("AAA", "BBB", "CCC"):
                for inv in INVESTOR_MAJORITIES:
                    with self.mgr.session() as c3:
                        cnt = c3.execute(
                            "SELECT COUNT(*) FROM model_explainer_rankings WHERE stock_id=? AND investor_majority=?",
                            (sym, inv),
                        ).fetchone()[0]
                        self.assertEqual(cnt, 4, f"{sym}/{inv} should have 4 lens families")
                    with self.mgr.session() as c4:
                        fam_rows = c4.execute(
                            "SELECT lens_family FROM model_explainer_rankings WHERE stock_id=? AND investor_majority=?",
                            (sym, inv),
                        ).fetchall()
                        self.assertEqual({r["lens_family"] for r in fam_rows}, set(LENS_FAMILIES))

    def test_rerun_is_idempotent(self):
        seed_universe_rankings(universe="all", manager=self.mgr)
        first = self._count_rankings()
        self.assertEqual(first, 60)
        # Rerun should not create duplicates (ON CONFLICT upsert)
        seed_universe_rankings(universe="all", manager=self.mgr)
        second = self._count_rankings()
        self.assertEqual(second, 60)
        # Third run with same args still 60
        seed_universe_rankings(universe="all", manager=self.mgr)
        third = self._count_rankings()
        self.assertEqual(third, 60)

    def test_weights_sum_to_one_with_floor_values(self):
        seed_universe_rankings(universe="all", manager=self.mgr)
        ranker = EnsembleRanker(self.mgr)
        # AAA has all floors → still 20 rows with deterministic tilt; weights must sum to 1 and match tilt-derived normalization
        for sym in ("AAA", "BBB", "CCC"):
            for inv in INVESTOR_MAJORITIES:
                weights = ranker.compute_ensemble_weights(stock=sym, investor=inv)
                self.assertEqual(set(weights.keys()), set(LENS_FAMILIES))
                total = sum(weights.values())
                self.assertAlmostEqual(total, 1.0, places=6, msg=f"weights sum !=1 for {sym}/{inv}: {weights}")
                for w in weights.values():
                    self.assertGreater(w, 0.0, f"weight must be >0 for {sym}/{inv}")
                    self.assertLessEqual(w, 1.0)
        # Explicit floor check: AAA with no substrate has explain_power >= EXPLAIN_FLOOR and p_value in (0.01,0.04)
        with self.mgr.session() as conn:
            aaa_rows = conn.execute(
                "SELECT explain_power, p_value FROM model_explainer_rankings WHERE stock_id='AAA'"
            ).fetchall()
            for r in aaa_rows:
                self.assertGreaterEqual(float(r["explain_power"]), EXPLAIN_FLOOR - 1e-9)
                self.assertGreaterEqual(float(r["p_value"]), 0.01)
                self.assertLessEqual(float(r["p_value"]), 0.04)
        # Rank Models join must also expose weight and be consistent with compute_ensemble_weights
        for sym in ("AAA",):
            for inv in ("FII", "retail", "all"):
                rows = ranker.rank_models(sym, inv)
                self.assertEqual(len(rows), 4)
                w = ranker.compute_ensemble_weights(stock=sym, investor=inv)
                for row in rows:
                    self.assertIn("weight", row)
                    self.assertAlmostEqual(row["weight"], w[row["lens_family"]], places=6)

    def test_limit_slices_deterministically(self):
        # universe='all' with limit=2 should seed only first 2 symbols in alphabetical order (AAA, BBB)
        result = seed_universe_rankings(universe="all", limit=2, manager=self.mgr)
        self.assertEqual(result["symbols_seeded"], 2)
        self.assertEqual(result["rows_written"], 40)
        self.assertListEqual(result["symbols_list"], ["AAA", "BBB"])
        self.assertEqual(self._count_rankings(), 40)
        # Remaining symbol CCC should have no rows
        with self.mgr.session() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM model_explainer_rankings WHERE stock_id='CCC'").fetchone()[0]
            self.assertEqual(cnt, 0)

    def test_symbol_keyed_compatibility(self):
        """Rankings remain symbol-keyed (stock_id = nse_symbol) for compatibility; wildcard partition preserved."""
        seed_universe_rankings(universe="all", manager=self.mgr)
        with self.mgr.session() as conn:
            rows = conn.execute("SELECT DISTINCT sector_id, geo_id, regime_tag FROM model_explainer_rankings").fetchall()
            # All should be wildcard '*' when only symbol+investor are seeded
            for r in rows:
                self.assertEqual(r["sector_id"], "*")
                self.assertEqual(r["geo_id"], "*")
                self.assertEqual(r["regime_tag"], "*")
            # Stock IDs must be symbols, not ISINs
            stock_ids = {r["stock_id"] for r in conn.execute("SELECT DISTINCT stock_id FROM model_explainer_rankings").fetchall()}
            # Our 3 symbols are AAA/BBB/CCC, not ISINs
            self.assertEqual(stock_ids, {"AAA", "BBB", "CCC"})
            for sid in stock_ids:
                self.assertNotIn("INE", sid)

    def test_cli_parser_run_moe_eod_help(self):
        """CLI help exposes --universe/--limit/--all-investor-cohorts without executing production DB."""
        # Isolate subprocess from production DB via env var (fresh temp DB)
        import tempfile as _tf
        _tmp_cli = _tf.NamedTemporaryFile(suffix=".db", delete=False)
        _tmp_cli.close()
        _env = dict(os.environ)
        _env["REALITY_ENGINE_DB_PATH"] = _tmp_cli.name
        try:
            cmd = [sys.executable, str(PROJECT_ROOT / "reality_engine" / "cli.py"), "run-moe-eod", "--help"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=_env)
            combined = (result.stdout or "") + (result.stderr or "")
            # argparse --help should exit 0 and print usage
            self.assertEqual(result.returncode, 0, msg=combined)
            self.assertIn("--universe", combined)
            self.assertIn("--limit", combined)
            self.assertIn("--all-investor-cohorts", combined)
            # Ensure default universe choice is documented at least as choice list or help text
            self.assertIn("nifty200", combined)
        finally:
            try:
                os.unlink(_tmp_cli.name)
            except OSError:
                pass

    def test_cli_parser_seed_peers_help(self):
        import tempfile as _tf
        _tmp_cli = _tf.NamedTemporaryFile(suffix=".db", delete=False)
        _tmp_cli.close()
        _env = dict(os.environ)
        _env["REALITY_ENGINE_DB_PATH"] = _tmp_cli.name
        try:
            cmd = [sys.executable, str(PROJECT_ROOT / "reality_engine" / "cli.py"), "seed-peers", "--help"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=_env)
            combined = (result.stdout or "") + (result.stderr or "")
            self.assertEqual(result.returncode, 0, msg=combined)
            self.assertIn("--universe", combined)
            self.assertIn("--limit", combined)
            # seed-peers forwards all-universe settings to MoE; help should at least mention shared args
            # The orchestrator's help prints Shared args handling; we check the flag exists via parser
            self.assertIn("seed", combined.lower())
        finally:
            try:
                os.unlink(_tmp_cli.name)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
