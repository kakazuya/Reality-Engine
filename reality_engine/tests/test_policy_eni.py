"""Wave B1 deterministic acceptance test for the Policy ENI peer.

Uses a fresh temp-file SQLite DB (never the live equity_intelligence.db) so the suite
never mutates production data. Verifies:
  1. ENI formula correctness (Steel Cust Duty Hike -3.8 x 0.85 = -3.23).
  2. risk_type mapping (positive=Tailwind, negative=Headwind, zero=Auxiliary).
  3. factor_type inference from policy name.
  4. Persistence round-trip into regulatory_political_risks (ISIN/symbol anchored).
  5. Aggregation + threshold: HAL net-positive passes (AggENI>=0); headwind-only fails.
  6. v_policy_adjusted_screen emulation returns only rows with AggENI>=0.
  7. Idempotent upsert on (symbol, policy_name).
  8. SQLite VIEW v_policy_adjusted_screen is created and queryable when present.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing import policy_engine as pe
from reality_engine.processing.policy_engine import PolicyRisk


class TestPolicyENI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="policy_eni_"))
        self.db_path = self.tmp / "policy_test.db"
        self.mgr = DatabaseManager(db_path=self.db_path)
        self.repo = Repository(manager=self.mgr)
        # Seed master_companies so company_id resolves to a positive rowid.
        with self.mgr.session() as conn:
            for sym, isin in (
                ("TATASTEEL", "INE081A01012"),
                ("HAL", "INE066A01013"),
                ("POLYPLEX", "INE663A01015"),
                ("RELIANCE", "INE002A01018"),
            ):
                conn.execute(
                    "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) "
                    "VALUES (?,?,?,1)", (isin, sym, sym)
                )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def test_01_eni_formula(self):
        # Steel Cust Duty Hike: -3.8 * 0.85 = -3.23
        r = PolicyRisk("Steel Cust Duty Hike", -3.8, 0.85, "Short-term")
        self.assertEqual(r.eni, -3.23)
        # PLI Defence tailwind: 4.2 * 0.70 = 2.94
        r2 = PolicyRisk("PLI Defence", 4.2, 0.70, "Structural")
        self.assertEqual(r2.eni, 2.94)
        # agg helper
        self.assertEqual(pe.agg_policy_score([r, r2]), -0.29)

    def test_02_risk_type_mapping(self):
        self.assertEqual(PolicyRisk.risk_type_for(3.0), "Tailwind")
        self.assertEqual(PolicyRisk.risk_type_for(-2.5), "Headwind")
        self.assertEqual(PolicyRisk.risk_type_for(0.0), "Auxiliary")

    def test_03_factor_type_inference(self):
        self.assertEqual(pe.infer_factor_type("Steel Cust Duty Hike"), "Tariff")
        self.assertEqual(pe.infer_factor_type("PLI Defence"), "Subsidy")
        self.assertEqual(pe.infer_factor_type("Green Energy Transition"), "Tariff")  # default Tariff
        self.assertEqual(pe.infer_factor_type("Antitrust Penalty"), "Antitrust")
        self.assertEqual(pe.infer_factor_type("Carbon Emission Norm"), "Environmental")

    def test_04_persist_roundtrip(self):
        net = pe.upsert_policy_risk(
            "TATASTEEL", "Steel Cust Duty Hike", -3.8, 0.85,
            factor_type="Tariff", time_horizon="Short-term", r=self.repo,
        )
        self.assertEqual(net, -3.23)

        rows = self.repo.get_policy_risks_for_symbol("TATASTEEL")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["policy_name"], "Steel Cust Duty Hike")
        self.assertEqual(row["net_impact_score"], -3.23)
        self.assertEqual(row["severity_score"], -3.8)
        self.assertEqual(row["probability"], 0.85)
        self.assertEqual(row["risk_type"], "Headwind")
        self.assertEqual(row["factor_type"], "Tariff")
        # company_id resolved from master rowid (positive integer)
        self.assertTrue(isinstance(row["company_id"], int) and row["company_id"] > 0)

        # Aggregation matches the single stored ENI.
        self.assertEqual(self.repo.get_policy_agg_eni("TATASTEEL"), -3.23)
        # Negative -> not approved by the policy gate.
        self.assertFalse(pe.is_policy_approved("TATASTEEL", r=self.repo))

    def test_05_agg_threshold_pass(self):
        # HAL: PLI Defence 2.94 + Defence Indigenisation 1.35 = 4.29 -> passes.
        pe.upsert_policy_risk("HAL", "PLI Defence", 4.2, 0.70, r=self.repo)
        pe.upsert_policy_risk("HAL", "Defence Indigenisation Capex", 1.5, 0.90, r=self.repo)
        agg = self.repo.get_policy_agg_eni("HAL")
        self.assertEqual(agg, 4.29)
        self.assertTrue(agg >= 0)
        self.assertTrue(pe.is_policy_approved("HAL", r=self.repo))

    def test_06_headwind_only_fails(self):
        # POLYPLEX: packaging RM duty headwind only -> AggENI < 0 -> fails.
        pe.upsert_policy_risk("POLYPLEX", "Packaging RM Duty Headwind", -2.0, 0.70, r=self.repo)
        self.assertEqual(self.repo.get_policy_agg_eni("POLYPLEX"), -1.4)
        self.assertFalse(pe.is_policy_approved("POLYPLEX", r=self.repo))

    def test_07_policy_adjusted_screen_emulation(self):
        # Seed: HAL passes, TATASTEEL fails, POLYPLEX fails.
        pe.upsert_policy_risk("HAL", "PLI Defence", 4.2, 0.70, r=self.repo)
        pe.upsert_policy_risk("HAL", "Defence Indigenisation Capex", 1.5, 0.90, r=self.repo)
        pe.upsert_policy_risk("TATASTEEL", "Steel Cust Duty Hike", -3.8, 0.85, r=self.repo)
        pe.upsert_policy_risk("TATASTEEL", "PLI Speciality Steel", 2.5, 0.60, r=self.repo)
        pe.upsert_policy_risk("POLYPLEX", "Packaging RM Duty Headwind", -2.0, 0.70, r=self.repo)

        rows = pe.query_policy_adjusted_screen(r=self.repo)
        symbols = {row["symbol"] for row in rows}
        self.assertIn("HAL", symbols)
        self.assertNotIn("TATASTEEL", symbols)
        self.assertNotIn("POLYPLEX", symbols)
        # Confirm HAL's net_policy_score is the aggregate (>=0).
        hal = next(r for r in rows if r["symbol"] == "HAL")
        self.assertEqual(hal["net_policy_score"], 4.29)
        self.assertGreaterEqual(hal["net_policy_score"], 0)

    def test_08_idempotent_upsert(self):
        pe.upsert_policy_risk("HAL", "PLI Defence", 4.2, 0.70, r=self.repo)
        # Re-upsert with a changed severity -> single row, value updated.
        pe.upsert_policy_risk("HAL", "PLI Defence", 3.0, 0.50, r=self.repo)
        rows = self.repo.get_policy_risks_for_symbol("HAL")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["net_impact_score"], 1.5)  # 3.0 * 0.50

    def test_09_sqlite_view_queryable(self):
        pe.upsert_policy_risk("HAL", "PLI Defence", 4.2, 0.70, r=self.repo)
        pe.upsert_policy_risk("HAL", "Defence Indigenisation Capex", 1.5, 0.90, r=self.repo)
        pe.upsert_policy_risk("TATASTEEL", "Steel Cust Duty Hike", -3.8, 0.85, r=self.repo)
        ok = pe.ensure_policy_adjusted_screen_view(r=self.repo)
        self.assertTrue(ok)
        with self.mgr.session() as conn:
            view_rows = conn.execute("SELECT symbol, net_policy_score FROM v_policy_adjusted_screen ORDER BY symbol").fetchall()
        view_symbols = {r["symbol"] for r in view_rows}
        self.assertIn("HAL", view_symbols)
        self.assertNotIn("TATASTEEL", view_symbols)  # filtered by HAVING >= 0

    def test_10_clamping(self):
        # Out-of-range severity / probability must be clamped.
        net = pe.upsert_policy_risk("HAL", "Clamp Test", 9.0, 1.5, r=self.repo)
        rows = self.repo.get_policy_risks_for_symbol("HAL")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity_score"], 5.0)
        self.assertEqual(rows[0]["probability"], 1.0)
        self.assertEqual(rows[0]["net_impact_score"], 5.0)
        self.assertEqual(net, 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
