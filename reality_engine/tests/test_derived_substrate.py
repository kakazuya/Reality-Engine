"""Derived substrate isolation test — business_profiler + moat_scorer + policy_engine.

Mirrors isolation pattern from reality_engine/tests/test_moat_backfill.py:
- Temp-file SQLite DB (never live equity_intelligence.db)
- 3 master companies across Bank/Steel/Information Technology + annual_financials
- Verifies derive_universe_profiles, derive_universe_moats, seed_derived_policy_risks

Checks:
 1) profiles: 3 derived, isin populated, qualitative_notes startswith DERIVED_NOTES, idempotent
 2) moats: 3 rows, moat_width in {Wide,Narrow,None}, isin populated, idempotent
 3) policy: >=1 per company matching template, isin populated, UNIQUE(symbol,policy_name) idempotent
 4) curated-skip: pre-existing non-derived profile row left untouched when overwrite=False
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.business_profiler import DERIVED_NOTES, derive_universe_profiles
from reality_engine.processing.moat_scorer import derive_universe_moats
from reality_engine.processing.policy_engine import seed_derived_policy_risks, DERIVED_POLICY_TEMPLATES


# Helper to seed the 3-company fixture
def _seed_three_companies(mgr):
    with mgr.session() as conn:
        # Clean any prior (fresh DB will be empty, but idempotent)
        # Insert 3 master companies with distinct industries that map to the 11-template set
        companies = [
            ("INE001B01001", "BANKTEST", "Bank Test Co", "Bank", "Financial Services"),
            ("INE002S01002", "STEELTEST", "Steel Test Co", "Steel", "Metals & Mining"),
            ("INE003I01003", "ITTEST", "IT Test Co", "Information Technology", "Information Technology"),
        ]
        for isin, sym, name, industry, sector in companies:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, industry, sector, is_active, is_nifty200, is_nifty500) "
                "VALUES (?,?,?,?,?,?,1,1)",
                (isin, sym, name, industry, sector, 1),
            )
        # annual_financials rows for blending (roce_pct, opm_pct, debt_to_equity)
        financials = [
            ("INE001B01001", "BANKTEST", "FY26", 14.0, 18.0, 0.3),
            ("INE002S01002", "STEELTEST", "FY26", 9.0, 12.0, 0.8),
            ("INE003I01003", "ITTEST", "FY26", 22.0, 25.0, 0.1),
        ]
        for isin, sym, fy, roce, opm, de in financials:
            conn.execute(
                "INSERT INTO annual_financials (isin, symbol, fiscal_year, roce_pct, opm_pct, debt_to_equity) "
                "VALUES (?,?,?,?,?,?)",
                (isin, sym, fy, roce, opm, de),
            )


def _template_for_symbol(symbol):
    # Mirror policy_engine._template_for_industry mapping for our 3 industries
    # Used for assertions: Bank -> RBI_RATE_CYCLE, Steel -> STEEL_SAFEGUARD_DUTY, IT -> US_VISA_RISK
    mapping = {
        "BANKTEST": "RBI_RATE_CYCLE",
        "STEELTEST": "STEEL_SAFEGUARD_DUTY",
        "ITTEST": "US_VISA_RISK",
    }
    return mapping.get(symbol)


class TestDerivedSubstrate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="derived_substrate_"))
        self.db_path = self.tmp / "derived_test.db"
        self.mgr = DatabaseManager(db_path=self.db_path)
        self.repo = Repository(manager=self.mgr)
        _seed_three_companies(self.mgr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def test_derive_universe_profiles_idempotent(self):
        # First run: should derive 3 profiles
        res = derive_universe_profiles(universe="all", r=self.repo)
        # Support both 'derived' and 'business_profile' keys
        derived = res.get("derived", res.get("business_profile", 0))
        self.assertEqual(derived, 3, f"expected 3 derived profiles, got {res}")
        self.assertEqual(res.get("scanned"), 3)

        # Verify each symbol has a profile, isin populated, notes startswith DERIVED_NOTES
        for sym, isin in [("BANKTEST", "INE001B01001"), ("STEELTEST", "INE002S01002"), ("ITTEST", "INE003I01003")]:
            prof = self.repo.get_business_model_profile(sym)
            self.assertIsNotNone(prof, f"profile missing for {sym}")
            # isin populated (either 'isin' or 'isin' column)
            prof_isin = prof.get("isin")
            self.assertEqual(prof_isin, isin, f"isin mismatch for {sym}")
            notes = prof.get("qualitative_notes") or prof.get("notes") or ""
            self.assertTrue(str(notes).startswith("Derived from financials+industry heuristics FY26"),
                            f"notes for {sym} should start with DERIVED_NOTES, got {notes!r}")
            self.assertTrue(str(notes).startswith(DERIVED_NOTES))

        # Idempotent second run: 0 new
        res2 = derive_universe_profiles(universe="all", r=self.repo)
        derived2 = res2.get("derived", res2.get("business_profile", 0))
        self.assertEqual(derived2, 0, f"second run should process 0 new, got {res2}")
        # Ensure counts still 3
        with self.mgr.session() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM business_model_profiles").fetchone()[0]
        self.assertEqual(cnt, 3)

    def test_derive_universe_moats(self):
        # Moats require profiles? No, but ensure financials present. Run moat derive.
        res = derive_universe_moats(universe="all", r=self.repo)
        derived = res.get("derived", res.get("moat", 0))
        self.assertEqual(derived, 3, f"expected 3 derived moats, got {res}")
        self.assertEqual(res.get("scanned"), 3)

        for sym, isin in [("BANKTEST", "INE001B01001"), ("STEELTEST", "INE002S01002"), ("ITTEST", "INE003I01003")]:
            row = self.repo.get_moat_evaluation(sym)
            self.assertIsNotNone(row, f"moat missing for {sym}")
            self.assertEqual(row.get("isin"), isin, f"moat isin mismatch for {sym}")
            # moat_width in {Wide,Narrow,None}
            self.assertIn(row.get("moat_width"), {"Wide", "Narrow", "None", None})
            # Check isin populated also at DB level
            self.assertTrue(row.get("isin"))

        # Idempotent second run
        res2 = derive_universe_moats(universe="all", r=self.repo)
        derived2 = res2.get("derived", res2.get("moat", 0))
        self.assertEqual(derived2, 0, f"second moat run should be 0, got {res2}")

    def test_seed_derived_policy_risks_idempotent(self):
        res = seed_derived_policy_risks(universe="all", r=self.repo)
        inserted = res.get("inserted", res.get("rows_inserted", 0))
        # Each of the 3 companies should match a template -> at least 3 inserted
        self.assertGreaterEqual(inserted, 3, f"expected >=3 policy inserted, got {res}")
        self.assertEqual(res.get("scanned"), 3)

        # Each symbol should have >=1 policy row matching its industry template and isin populated
        for sym, expected_policy in [("BANKTEST", "RBI_RATE_CYCLE"), ("STEELTEST", "STEEL_SAFEGUARD_DUTY"), ("ITTEST", "US_VISA_RISK")]:
            rows = self.repo.get_policy_risks_for_symbol(sym)
            self.assertGreaterEqual(len(rows), 1, f"policy missing for {sym}")
            # Check policy_name matching template
            policy_names = {r.get("policy_name") for r in rows}
            self.assertIn(expected_policy, policy_names, f"{sym} should have policy {expected_policy}, got {policy_names}")
            # isin populated for each row (check first row)
            for r in rows:
                # Either isin or isin column; repo stores isin
                isin_val = r.get("isin") or r.get("isin")
                self.assertIsNotNone(isin_val, f"policy isin missing for {sym}")
                # also check that isin matches expected master
                self.assertIn(isin_val, ("INE001B01001", "INE002S01002", "INE003I01003"))

        # Idempotent re-run adds nothing new (UNIQUE symbol+policy_name)
        res2 = seed_derived_policy_risks(universe="all", r=self.repo)
        inserted2 = res2.get("inserted", res2.get("rows_inserted", 0))
        self.assertEqual(inserted2, 0, f"second policy run should insert 0, got {res2}")
        with self.mgr.session() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM regulatory_political_risks").fetchone()[0]
        self.assertGreaterEqual(cnt, 3)

    def test_curated_skip_profile_overwrite_false(self):
        # Insert a pre-existing profile row with non-derived notes for BANKTEST
        self.repo.ensure_business_profile_schema()
        # Use repository helper to create curated row
        self.repo.upsert_business_model_profile(
            symbol="BANKTEST",
            archetype="Network",
            revenue_recurrence_pct=80,
            pricing_power_score=4,
            capital_intensity_score=3,
            operating_leverage_score=4,
            qualitative_notes="Curated manual entry — should survive derive",
            isin="INE001B01001",
        )
        # Verify curated present
        pre = self.repo.get_business_model_profile("BANKTEST")
        self.assertEqual(pre.get("qualitative_notes"), "Curated manual entry — should survive derive")

        # Now derive with overwrite=False (default) — should skip BANKTEST, derive the other 2
        res = derive_universe_profiles(universe="all", overwrite=False, r=self.repo)
        derived = res.get("derived", res.get("business_profile", 0))
        # Only STEELTEST and ITTEST should be derived -> 2
        self.assertEqual(derived, 2, f"curated skip should derive 2, got {res}")

        # BANKTEST should remain curated untouched
        post = self.repo.get_business_model_profile("BANKTEST")
        self.assertEqual(post.get("qualitative_notes"), "Curated manual entry — should survive derive")
        self.assertEqual(post.get("isin"), "INE001B01001")

        # Other symbols should be derived
        for sym in ("STEELTEST", "ITTEST"):
            prof = self.repo.get_business_model_profile(sym)
            self.assertIsNotNone(prof)
            notes = prof.get("qualitative_notes") or ""
            self.assertTrue(str(notes).startswith(DERIVED_NOTES), f"{sym} should be derived, got {notes!r}")

        # Second derive still skips curated and already-derived -> 0 new
        res2 = derive_universe_profiles(universe="all", overwrite=False, r=self.repo)
        self.assertEqual(res2.get("derived", res2.get("business_profile", 0)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
