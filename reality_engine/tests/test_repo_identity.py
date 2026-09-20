"""Repository identity joins: geographic_exposure via company_id, ISIN ranking mapping, BERGERPAINT alias."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository


class TestRepoIdentity(unittest.TestCase):
    def test_geographic_exposure_join_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = DatabaseManager(db_path=Path(td) / "test.db")
            repo = Repository(manager=mgr)
            repo.upsert_master_companies([{"isin": "INE002A01018", "nse_symbol": "RELIANCE", "company_name": "RELIANCE LTD", "is_active": 1}])
            # resolve rowid
            with mgr.session() as conn:
                cid = conn.execute("SELECT rowid FROM master_companies WHERE nse_symbol='RELIANCE'").fetchone()[0]
                # ensure schema
                repo.ensure_geographic_exposure_schema(manager=mgr)
                repo.upsert_geographic_exposure(company_id=cid, country_id="IND", revenue_share_pct=80)
                repo.upsert_geographic_exposure(company_id=cid, country_id="USA", revenue_share_pct=20)
            # via symbol
            rows = repo.get_geographic_exposure_by_symbol("RELIANCE")
            self.assertEqual(len(rows), 2)
            # via ISIN alias still works for _resolve_company_id path (isin param)
            # direct company_id fetch
            rows2 = repo.get_geographic_exposure(cid)
            self.assertEqual(len(rows2), 2)
            # verify table has no isin column
            with mgr.session() as conn:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(geographic_exposure)").fetchall()}
                self.assertNotIn("isin", cols)
                self.assertIn("company_id", cols)

    def test_bergerpaint_alias_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = DatabaseManager(db_path=Path(td) / "test.db")
            repo = Repository(manager=mgr)
            repo.upsert_master_companies([{"isin": "INE054A01025", "nse_symbol": "BERGEPAINT", "company_name": "BERGER PAINTS LTD", "is_active": 1}])
            # master spelling is BERGEPAINT, query with BERGERPAINT should still resolve
            comp = repo.get_company_by_symbol("BERGERPAINT")
            self.assertIsNotNone(comp)
            self.assertEqual(comp["nse_symbol"], "BERGEPAINT")
            # reverse also
            comp2 = repo.get_company_by_symbol("BERGEPAINT")
            self.assertIsNotNone(comp2)

    def test_ranking_isin_additive_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = DatabaseManager(db_path=Path(td) / "test.db")
            repo = Repository(manager=mgr)
            repo.upsert_master_companies([{"isin": "INE002A01018", "nse_symbol": "RELIANCE", "company_name": "RELIANCE LTD", "is_active": 1}])
            repo.ensure_ensemble_ranking_schema(manager=mgr)
            repo.upsert_model_explainer_rankings([
                {"stock_id": "RELIANCE", "sector_id": "*", "geo_id": "*", "regime_tag": "*", "investor_majority": "all", "lens_family": "business_quality", "p_value": 0.01, "explain_power": 0.9, "rank": 1},
                {"stock_id": "RELIANCE", "sector_id": "*", "geo_id": "*", "regime_tag": "*", "investor_majority": "all", "lens_family": "policy_macro", "p_value": 0.02, "explain_power": 0.7, "rank": 2},
            ])
            by_symbol = repo.get_model_explainer_rankings(stock_id="RELIANCE")
            self.assertEqual(len(by_symbol), 2)
            by_isin = repo.get_model_explainer_rankings_by_isin("INE002A01018")
            self.assertEqual(len(by_isin), 2)
            self.assertEqual({r["lens_family"] for r in by_isin}, {"business_quality", "policy_macro"})

    def test_validation_scores_upsert_preserves_created_at(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            mgr = DatabaseManager(db_path=Path(td) / "test.db")
            repo = Repository(manager=mgr)
            rec = {"asof_date": "2026-09-01", "horizon_days": 5, "mode": "ensemble",
                   "lens_family": None, "regime_tag": "unknown", "investor_majority": "all",
                   "n": 8, "hit_rate": 1.0}
            repo.upsert_validation_scores([rec])
            with mgr.session() as conn:
                first = conn.execute("SELECT created_at FROM model_validation_scores").fetchone()[0]
            time.sleep(1.05)
            repo.upsert_validation_scores([{**rec, "hit_rate": 0.5}])
            with mgr.session() as conn:
                rows = conn.execute("SELECT created_at, hit_rate FROM model_validation_scores").fetchall()
            self.assertEqual(len(rows), 1, "conflict must upsert, not duplicate")
            self.assertEqual(rows[0][0], first, "created_at must survive conflict-update")
            self.assertAlmostEqual(rows[0][1], 0.5, "metrics must still refresh")

    def test_document_chunks_no_industry_tags_backfill(self):
        # relies on pdf_ingestor backfill tested elsewhere, just check repo helper exists
        from reality_engine.ingestion.pdf_ingestor import backfill_document_chunk_industry_tags
        self.assertTrue(callable(backfill_document_chunk_industry_tags))


if __name__ == "__main__":
    unittest.main()
