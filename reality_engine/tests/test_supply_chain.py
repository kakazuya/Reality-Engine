"""Wave B2 deterministic acceptance test for the Supply-Chain (ripple DAG) peer.

Uses a fresh temp-file SQLite DB (never the live equity_intelligence.db) so the
suite never mutates production data. Verifies:
  1. PN product: probs [0.9, 0.8, 0.5] -> PN 0.9, 0.72, 0.36 along the chain.
  2. S formula: steel-duty chain -> S(1st)=76.0, S(2nd)~20.3, S(3rd)~8.5 (≈9.x),
     returned ordered S DESC.
  3. Ripples persistence round-trip (parent_ripple_id resolved for the self-DAG).
  4. trace_ripple_chain returns ordered S DESC with correct PN/MN for event 999.
  5. Pruning threshold: PN<0.08 or S<5.0 flags rows correctly.
  6. geographic_exposure schema + upsert/get round-trip.
  7. Demo fallback: an event with no ripple rows returns the canonical 3-level
     steel-duty demo chain, ordered S DESC.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing import causal_engine as ce


class TestSupplyChain(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="supply_chain_"))
        self.db_path = self.tmp / "supply_test.db"
        self.mgr = DatabaseManager(db_path=self.db_path)
        self.repo = Repository(manager=self.mgr)
        self.engine = ce.CausalGraphEngine(manager=self.mgr)
        self.engine.ensure_ripple_schema()
        # Seed master_companies so company_id resolution has positive rowids.
        with self.mgr.session() as conn:
            for sym, isin in (
                ("TATASTEEL", "INE081A01012"),
                ("HAL", "INE066A01013"),
            ):
                conn.execute(
                    "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) "
                    "VALUES (?,?,?,1)", (isin, sym, sym)
                )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def _insert_chain(self, event_id, ripples):
        """ripples: list of dicts with _ref/_parent_ref and magnitude fields.

        Injects the NOT-NULL fields the canonical ripple_effects schema requires
        (transmission_channel, target_type) so we exercise the real persistence
        path without touching the repo method owned by another wave.
        """
        norm = []
        for r in ripples:
            rr = dict(r)
            rr.setdefault("transmission_channel", "direct")
            rr.setdefault("target_type", "Sector")
            norm.append(rr)
        self.repo.upsert_ripple_effects(event_id, norm)

    def test_01_pn_product(self):
        # Chain probs [0.9, 0.8, 0.5] -> PN 0.9, 0.72, 0.36.
        self._insert_chain(1, [
            {"_ref": "r1", "order_level": 1, "raw_magnitude": 1.0, "probability": 0.9,
             "lag_time_months": 0, "transmission_elasticity": 1.0},
            {"_ref": "r2", "_parent_ref": "r1", "order_level": 2, "raw_magnitude": 1.0,
             "probability": 0.8, "lag_time_months": 3, "transmission_elasticity": 1.0},
            {"_ref": "r3", "_parent_ref": "r2", "order_level": 3, "raw_magnitude": 1.0,
             "probability": 0.5, "lag_time_months": 6, "transmission_elasticity": 1.0},
        ])
        chain = self.engine.get_ripple_chain_for_event(1)
        self.assertEqual(len(chain), 3)
        pns = sorted([c["pn_raw"] for c in chain], reverse=True)
        self.assertAlmostEqual(pns[0], 0.9, places=6)    # root
        self.assertAlmostEqual(pns[1], 0.72, places=6)   # 0.9*0.8
        self.assertAlmostEqual(pns[2], 0.36, places=6)   # 0.9*0.8*0.5

    def test_02_s_formula_steel_duty(self):
        # Steel-duty acceptance case (event 999). Verify S DESC ordering & values.
        self._insert_chain(999, [
            {"_ref": "r1", "order_level": 1, "raw_magnitude": 3.80, "probability": 1.0,
             "lag_time_months": 0, "transmission_elasticity": 1.0},
            {"_ref": "r2", "_parent_ref": "r1", "order_level": 2, "raw_magnitude": -2.43,
             "probability": 1.0, "lag_time_months": 3, "transmission_elasticity": 1.0},
            {"_ref": "r3", "_parent_ref": "r2", "order_level": 3, "raw_magnitude": -1.41,
             "probability": 1.0, "lag_time_months": 6, "transmission_elasticity": 1.0},
        ])
        chain = self.engine.get_ripple_chain_for_event(999)
        # Three distinct magnitudes and S DESC ordering
        ss = [c["s_raw"] for c in chain]
        self.assertEqual(ss, sorted(ss, reverse=True))
        # 1st (raw +3.80, lag 0): S = 3.8*20/1 = 76.0
        top = max(chain, key=lambda c: c["s_raw"])
        self.assertAlmostEqual(top["s_raw"], 76.0, places=4)
        self.assertAlmostEqual(top["raw"], 3.80, places=6)
        # 2nd (raw -2.43, cum lag 3): S = 2.43*20/(1+ln4) ≈ 20.36
        mid = sorted(chain, key=lambda c: c["s_raw"], reverse=True)[1]
        self.assertAlmostEqual(mid["s_raw"], 20.36, delta=0.05)
        # 3rd (raw -1.41, cum lag 9): S = 1.41*20/(1+ln10) ≈ 8.55 (≈9.x)
        bot = min(chain, key=lambda c: c["s_raw"])
        self.assertGreaterEqual(bot["s_raw"], 8.0)
        self.assertLessEqual(bot["s_raw"], 10.0)

    def test_03_persistence_roundtrip(self):
        self._insert_chain(999, [
            {"_ref": "r1", "order_level": 1, "raw_magnitude": 3.80, "probability": 1.0,
             "lag_time_months": 0, "transmission_elasticity": 1.0},
            {"_ref": "r2", "_parent_ref": "r1", "order_level": 2, "raw_magnitude": -2.43,
             "probability": 1.0, "lag_time_months": 3, "transmission_elasticity": 1.0},
            {"_ref": "r3", "_parent_ref": "r2", "order_level": 3, "raw_magnitude": -1.41,
             "probability": 1.0, "lag_time_months": 6, "transmission_elasticity": 1.0},
        ])
        rows = self.repo.get_ripple_effects_for_event(999)
        self.assertEqual(len(rows), 3)
        by_ref = {r["order_level"]: r for r in rows}
        # parent_ripple_id of level-2 points at level-1's ripple_id
        self.assertIsNone(by_ref[1]["parent_ripple_id"])
        self.assertEqual(by_ref[2]["parent_ripple_id"], by_ref[1]["ripple_id"])
        self.assertEqual(by_ref[3]["parent_ripple_id"], by_ref[2]["ripple_id"])

    def test_04_trace_ripple_chain_ordered(self):
        self._insert_chain(999, [
            {"_ref": "r1", "order_level": 1, "raw_magnitude": 3.80, "probability": 1.0,
             "lag_time_months": 0, "transmission_elasticity": 1.0},
            {"_ref": "r2", "_parent_ref": "r1", "order_level": 2, "raw_magnitude": -2.43,
             "probability": 1.0, "lag_time_months": 3, "transmission_elasticity": 1.0},
            {"_ref": "r3", "_parent_ref": "r2", "order_level": 3, "raw_magnitude": -1.41,
             "probability": 1.0, "lag_time_months": 6, "transmission_elasticity": 1.0},
        ])
        chain = self.engine.trace_ripple_chain(999, max_hops=3)
        self.assertEqual(len(chain), 3)
        ss = [c["s_raw"] for c in chain]
        self.assertEqual(ss, sorted(ss, reverse=True))
        # PN for steel duty = 1.0 everywhere (all prob=1.0)
        for c in chain:
            self.assertAlmostEqual(c["pn_raw"], 1.0, places=6)
        # MN for the +3.80 node = 3.80 ; for -2.43 node = -2.43 ; for -1.41 = -1.41
        mns = {round(c["mn"], 2) for c in chain}
        self.assertEqual(mns, {3.80, -2.43, -1.41})
        # The top-S node is the +3.80 root with S=76.0
        self.assertAlmostEqual(chain[0]["s_raw"], 76.0, places=4)
        self.assertAlmostEqual(chain[0]["raw"], 3.80, places=6)

    def test_05_prune_threshold(self):
        # PN<0.08 -> prune; S<5.0 -> prune; otherwise keep.
        self.assertTrue(self.engine.should_prune_ripple_row(0.036, 100.0))   # PN<0.08
        self.assertTrue(self.engine.should_prune_ripple_row(0.20, 3.0))      # S<5.0
        self.assertFalse(self.engine.should_prune_ripple_row(0.20, 10.0))    # keep
        self.assertFalse(self.engine.should_prune_ripple_row(0.90, 76.0))    # keep (steel root)

        # A deep low-probability node is flagged pruned in the chain itself.
        self._insert_chain(7, [
            {"_ref": "r1", "order_level": 1, "raw_magnitude": 5.0, "probability": 0.9,
             "lag_time_months": 0, "transmission_elasticity": 1.0},
            {"_ref": "r2", "_parent_ref": "r1", "order_level": 2, "raw_magnitude": 5.0,
             "probability": 0.8, "lag_time_months": 3, "transmission_elasticity": 1.0},
            {"_ref": "r3", "_parent_ref": "r2", "order_level": 3, "raw_magnitude": 5.0,
             "probability": 0.05, "lag_time_months": 6, "transmission_elasticity": 1.0},
        ])
        chain = self.engine.get_ripple_chain_for_event(7)
        by_pn = {round(c["pn_raw"], 4): c for c in chain}
        # node3 PN = 0.9*0.8*0.05 = 0.036 -> pruned
        self.assertIn(0.036, by_pn)
        self.assertTrue(by_pn[0.036]["pruned"])
        # node1 PN=0.9, node2 PN=0.72 -> not pruned
        self.assertFalse(by_pn[0.9]["pruned"])
        self.assertFalse(by_pn[0.72]["pruned"])

    def test_06_geographic_exposure(self):
        self.engine.ensure_geographic_exposure_schema()
        with self.mgr.session() as conn:
            cid = conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) "
                "VALUES (?,?,?,1) RETURNING rowid",
                ("INE999Z01000", "TESTCO", "TESTCO"),
            ).fetchone()["rowid"]
        self.repo.upsert_geographic_exposure(cid, "IND", 60.0, 70.0)
        self.repo.upsert_geographic_exposure(cid, "USA", 25.0, 20.0)
        rows = self.repo.get_geographic_exposure(cid)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["country_id"] for r in rows}, {"IND", "USA"})
        ind = next(r for r in rows if r["country_id"] == "IND")
        self.assertAlmostEqual(ind["revenue_share_pct"], 60.0)
        self.assertAlmostEqual(ind["asset_exposure_pct"], 70.0)
        # Idempotent re-upsert updates rather than duplicates.
        self.repo.upsert_geographic_exposure(cid, "IND", 65.0, 75.0)
        rows2 = self.repo.get_geographic_exposure(cid)
        self.assertEqual(len(rows2), 2)
        ind2 = next(r for r in rows2 if r["country_id"] == "IND")
        self.assertAlmostEqual(ind2["revenue_share_pct"], 65.0)

    def test_07_demo_fallback(self):
        # Event with no ripple rows -> canonical steel-duty demo chain.
        chain = self.engine.trace_ripple_chain(888, max_hops=3)
        self.assertEqual(len(chain), 3)
        ss = [c["s_raw"] for c in chain]
        self.assertEqual(ss, sorted(ss, reverse=True))
        top = max(chain, key=lambda c: c["s_raw"])
        self.assertAlmostEqual(top["s_raw"], 76.0, places=4)
        self.assertTrue(any(c.get("is_demo") for c in chain))


if __name__ == "__main__":
    unittest.main(verbosity=2)
