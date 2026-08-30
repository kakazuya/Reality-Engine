"""Policy coverage audit: every active company queryable without fabricating ENI.

Uses isolated temp DB (never production). Verifies:
 a) mapped row -> numeric ENI, coverage='mapped', approved True/False
 b) coverage-only sentinel -> ENI None, coverage='no_template', approved None, NULL impacts, ISIN populated
 c) seed_derived_policy_risks on General Diversified/Other creates exactly one sentinel with NULL impacts and is idempotent
 d) mapped validation + coverage validation at boundary
 e) unknown symbol -> ENI None, coverage='unknown', approved None
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing import policy_engine as pe


class TestPolicyCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="policy_cov_"))
        self.db_path = self.tmp / "cov_test.db"
        self.mgr = DatabaseManager(db_path=self.db_path)
        self.repo = Repository(manager=self.mgr)
        # Ensure regulatory schema with coverage_status
        self.repo.ensure_regulatory_political_risks_schema()
        # Seed master companies
        with self.mgr.session() as conn:
            companies = [
                ("INE001S01001", "STEELTEST", "Steel Test Co", "Steel", "Metals & Mining"),
                ("INE002B01002", "BANKTEST", "Bank Test Co", "Bank", "Financial Services"),
                ("INE003G01003", "DIVERSTEST", "Diversified Test Co", "General Diversified", "Other"),
                ("INE004O01004", "OTHERTEST", "Other Test Co", "Other", "Other"),
                ("INE005C01005", "CAPGOODSTEST", "Cap Goods Test Co", "Capital Goods", "Capital Goods"),
            ]
            for isin, sym, name, ind, sec in companies:
                conn.execute(
                    "INSERT INTO master_companies (isin, nse_symbol, company_name, industry, sector, is_active, is_nifty200) VALUES (?,?,?,?,?,?,?)",
                    (isin, sym, name, ind, sec, 1, 1),
                )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_mapped_row_returns_numeric_and_coverage_mapped(self):
        # Mapped: negative ENI
        net = self.repo.upsert_regulatory_political_risk(
            symbol="STEELTEST",
            policy_name="Steel Cust Duty Hike",
            severity_score=-3.8,
            probability=0.85,
            factor_type="Tariff",
            coverage_status="mapped",
        )
        self.assertEqual(net, -3.23)
        self.assertEqual(self.repo.get_policy_agg_eni("STEELTEST"), -3.23)
        self.assertEqual(self.repo.get_policy_coverage("STEELTEST"), "mapped")
        # via policy_engine helpers
        self.assertEqual(pe.get_agg_eni("STEELTEST", r=self.repo), -3.23)
        self.assertEqual(pe.get_policy_coverage("STEELTEST", r=self.repo), "mapped")
        self.assertIs(pe.is_policy_approved("STEELTEST", r=self.repo), False)
        # Check ISIN populated
        rows = self.repo.get_policy_risks_for_symbol("STEELTEST")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["isin"], "INE001S01001")
        self.assertEqual(rows[0]["coverage_status"], "mapped")
        self.assertEqual(rows[0]["severity_score"], -3.8)
        self.assertEqual(rows[0]["policy_name"], "Steel Cust Duty Hike")

        # Mapped positive
        self.repo.upsert_regulatory_political_risk(
            symbol="BANKTEST",
            policy_name="RBI Rate Cut",
            severity_score=2.4,
            probability=0.55,
            factor_type="FX",
            coverage_status="mapped",
        )
        self.assertEqual(self.repo.get_policy_agg_eni("BANKTEST"), round(2.4*0.55,2))
        self.assertEqual(self.repo.get_policy_coverage("BANKTEST"), "mapped")
        self.assertIs(pe.is_policy_approved("BANKTEST", r=self.repo), True)
        rows2 = self.repo.get_policy_risks_for_symbol("BANKTEST")
        self.assertEqual(rows2[0]["isin"], "INE002B01002")
        self.assertTrue(rows2[0]["coverage_status"] == "mapped")

    def test_b_coverage_only_sentinel_returns_none(self):
        # Direct coverage-only insert
        net = self.repo.upsert_regulatory_political_risk(
            symbol="DIVERSTEST",
            policy_name="__NO_POLICY_TEMPLATE__",
            severity_score=None,
            probability=None,
            net_impact_score=None,
            coverage_status="no_template",
        )
        self.assertIsNone(net)
        self.assertIsNone(self.repo.get_policy_agg_eni("DIVERSTEST"))
        self.assertEqual(self.repo.get_policy_coverage("DIVERSTEST"), "no_template")
        self.assertIsNone(pe.get_agg_eni("DIVERSTEST", r=self.repo))
        self.assertEqual(pe.get_policy_coverage("DIVERSTEST", r=self.repo), "no_template")
        self.assertIsNone(pe.is_policy_approved("DIVERSTEST", r=self.repo))
        # Compat coerce should allow bool restore
        self.assertIs(pe.is_policy_approved("DIVERSTEST", r=self.repo, coerce_unknown_to_bool=True), True)
        self.assertIs(pe.is_policy_approved("DIVERSTEST", r=self.repo, coerce_unknown_to_bool=False), False)

        rows = self.repo.get_policy_risks_for_symbol("DIVERSTEST")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["policy_name"], "__NO_POLICY_TEMPLATE__")
        self.assertEqual(r["coverage_status"], "no_template")
        self.assertIsNone(r["severity_score"])
        self.assertIsNone(r["probability"])
        self.assertIsNone(r["net_impact_score"])
        self.assertEqual(r["isin"], "INE003G01003")
        # Ensure ISIN auto-resolution still works when isin not supplied (already resolved via master)
        self.assertTrue(r["isin"])

    def test_b_validation_at_boundary(self):
        # coverage-only MUST use sentinel and NULLs
        with self.assertRaises(ValueError):
            self.repo.upsert_regulatory_political_risk(
                symbol="OTHERTEST", policy_name="WRONG_NAME", severity_score=None, probability=None, coverage_status="no_template"
            )
        with self.assertRaises(ValueError):
            self.repo.upsert_regulatory_political_risk(
                symbol="OTHERTEST", policy_name="__NO_POLICY_TEMPLATE__", severity_score=-1.0, probability=0.5, coverage_status="no_template"
            )
        # mapped MUST have numeric severity/prob and not use sentinel
        with self.assertRaises(ValueError):
            self.repo.upsert_regulatory_political_risk(
                symbol="STEELTEST", policy_name="__NO_POLICY_TEMPLATE__", severity_score=1.0, probability=0.5, coverage_status="mapped"
            )
        with self.assertRaises(ValueError):
            self.repo.upsert_regulatory_political_risk(
                symbol="STEELTEST", policy_name="Some Policy", severity_score=None, probability=0.5, coverage_status="mapped"
            )

    def test_c_seed_derived_creates_sentinel_idempotent_and_isi_populated(self):
        # Before seed, DIVERSTEST etc have no rows -> unknown
        self.assertEqual(self.repo.get_policy_coverage("DIVERSTEST"), "unknown")
        self.assertIsNone(self.repo.get_policy_agg_eni("DIVERSTEST"))
        # Seed for all active companies
        res = pe.seed_derived_policy_risks(universe="all", r=self.repo)
        # Should have scanned 5
        self.assertEqual(res["scanned"], 5)
        # Mapped: STEELTEST->STEEL_SAFEGUARD_DUTY, BANKTEST->RBI_RATE_CYCLE
        self.assertGreaterEqual(res["inserted"], 2)
        # Coverage: DIVERSTEST, OTHERTEST, CAPGOODSTEST -> 3 coverage rows
        self.assertEqual(res["coverage_rows_inserted"], 3)
        self.assertEqual(res["skipped_no_template"], 0)
        # Verify each no-template company has exactly one sentinel with NULL impacts
        for sym, isin in [("DIVERSTEST", "INE003G01003"), ("OTHERTEST", "INE004O01004"), ("CAPGOODSTEST", "INE005C01005")]:
            rows = self.repo.get_policy_risks_for_symbol(sym)
            self.assertEqual(len(rows), 1, f"{sym} should have exactly one coverage row, got {rows}")
            r = rows[0]
            self.assertEqual(r["policy_name"], "__NO_POLICY_TEMPLATE__")
            self.assertEqual(r["coverage_status"], "no_template")
            self.assertIsNone(r["severity_score"])
            self.assertIsNone(r["probability"])
            self.assertIsNone(r["net_impact_score"])
            self.assertEqual(r["isin"], isin)
            self.assertEqual(self.repo.get_policy_coverage(sym), "no_template")
            self.assertIsNone(self.repo.get_policy_agg_eni(sym))
            self.assertIsNone(pe.is_policy_approved(sym, r=self.repo))
        # Mapped companies should remain mapped
        self.assertEqual(self.repo.get_policy_coverage("STEELTEST"), "mapped")
        self.assertEqual(self.repo.get_policy_coverage("BANKTEST"), "mapped")
        # Verify ISIN populated for mapped too
        for sym in ("STEELTEST", "BANKTEST"):
            rows = self.repo.get_policy_risks_for_symbol(sym)
            self.assertTrue(rows[0]["isin"] is not None)

        # Idempotent rerun: should skip all, insert 0, coverage 0, scanned same
        res2 = pe.seed_derived_policy_risks(universe="all", r=self.repo)
        self.assertEqual(res2["inserted"], 0)
        self.assertEqual(res2["coverage_rows_inserted"], 0)
        self.assertEqual(res2["skipped_existing"], 5)
        self.assertEqual(res2["scanned"], 5)
        # Still exactly 3 coverage rows total (not duplicated)
        with self.mgr.session() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM regulatory_political_risks WHERE policy_name='__NO_POLICY_TEMPLATE__'").fetchone()[0]
        self.assertEqual(cnt, 3)
        # Total rows = 2 mapped + 3 coverage =5
        with self.mgr.session() as conn:
            cnt_all = conn.execute("SELECT COUNT(*) FROM regulatory_political_risks").fetchone()[0]
        self.assertEqual(cnt_all, 5)

    def test_d_unknown_symbol(self):
        # Symbol with no master row and no policy row
        self.assertEqual(self.repo.get_policy_coverage("NOTEXIST"), "unknown")
        self.assertIsNone(self.repo.get_policy_agg_eni("NOTEXIST"))
        self.assertIsNone(pe.is_policy_approved("NOTEXIST", r=self.repo))
        # Ensure unknown not treated as 0 in query_policy_adjusted_screen
        rows = self.repo.query_policy_adjusted_screen(min_agg_eni=0.0)
        symbols = {r["symbol"] for r in rows}
        self.assertNotIn("NOTEXIST", symbols)

    def test_e_migration_column_exists_and_default_mapped(self):
        # Ensure coverage_status column exists via PRAGMA and existing mapped default
        with self.mgr.session() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info('regulatory_political_risks')").fetchall()}
            self.assertIn("coverage_status", cols)
        # Insert mapped without explicit coverage_status -> should default to mapped
        self.repo.upsert_regulatory_political_risk(
            symbol="STEELTEST", policy_name="Another Policy", severity_score=1.0, probability=0.5
        )
        rows = [r for r in self.repo.get_policy_risks_for_symbol("STEELTEST") if r["policy_name"]=="Another Policy"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["coverage_status"], "mapped")
        # Existing coverage rows remain no_template
        # Also test query_policy_adjusted_screen includes mapped row with numeric net
        self.repo.upsert_regulatory_political_risk(
            symbol="BANKTEST", policy_name="RBI Rate Cut", severity_score=2.0, probability=0.6, coverage_status="mapped"
        )
        q = self.repo.query_policy_adjusted_screen(min_agg_eni=0.0)
        # BANKTEST should be in screen (positive)
        self.assertTrue(any(r["symbol"]=="BANKTEST" and r["net_policy_score"] is not None and r["policy_coverage"]=="mapped" for r in q))
        # DIVERSTEST sentinel should NOT be in screen (since we seeded earlier? Need fresh DB scenario:
        # In this test method DB already has STEELTEST mapped, but DIVERSTEST not yet seeded in this method's DB (fresh per method).
        # So query should not contain DIVERSTEST. Ensure no coverage row appears.
        self.assertFalse(any(r["symbol"]=="DIVERSTEST" for r in q))

    def test_f_composite_screener_not_coerce_unknown_to_zero(self):
        # Verify composite_screener lens handling keeps policy_agg_eni as None not 0
        from reality_engine.processing.composite_screener import CompositeScreener
        cs = CompositeScreener()
        cs.repo = self.repo
        # Create coverage row for DIVERSTEST
        self.repo.upsert_regulatory_political_risk(
            symbol="DIVERSTEST", policy_name="__NO_POLICY_TEMPLATE__", severity_score=None, probability=None, coverage_status="no_template"
        )
        # Check lookup returns None not 0
        self.assertIsNone(cs._lookup_policy_agg_eni("DIVERSTEST"))
        # Enrich a df with that symbol and verify policy_coverage explicit
        import pandas as pd
        df = pd.DataFrame([{"symbol": "DIVERSTEST", "isin": "INE003G01003", "industry": "General Diversified", "sector": "Other"}])
        enriched = cs._enrich_with_topdown_metrics(df)
        self.assertIn("policy_coverage", enriched.columns)
        self.assertEqual(enriched.loc[0, "policy_coverage"], "no_template")
        self.assertTrue(pd.isna(enriched.loc[0, "policy_agg_eni"]))
        # Lens should be neutral 50, not based on 0
        lens_df = cs.compute_lens_scores(enriched)
        self.assertEqual(lens_df.loc[0, "lens_policy_macro"], 50.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
