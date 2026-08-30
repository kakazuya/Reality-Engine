"""Deterministic tests for Wave D2 Transient Event-Graph Spawner.

Uses a temporary SQLite database; does NOT touch the project's real DB. Verifies:
  * event nuance parsing (30% / effective date / conditional flag / exceptions)
  * spawn creates macro_events + ripple_effects with >=3 levels
  * PRIMARY (order 1) is NOT the biggest beneficiary (max S is order >=2)
  * 2nd-order forward/back supply-chain neighbors fetched correctly
  * transactional rollback when the MacroEventExtraction lens is invalid
  * lag_time_months quantized (0m / 3m / 6m)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase, main

from reality_engine.db.database import DatabaseManager
from reality_engine.processing.event_graph import EventGraphSpawner, spawn_event_graph


class TempDBMixin:
    """Create a throwaway SQLite DB and wire it into the spawner."""

    def setUp(self) -> None:
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.db_path = Path(self._fh.name)
        self.manager = DatabaseManager(self.db_path)  # runs schema.sql init
        self.spawner = EventGraphSpawner(manager=self.manager)

    def tearDown(self) -> None:
        try:
            self.db_path.unlink()
        except Exception:
            pass


class TestParseEventNuance(TempDBMixin, TestCase):
    def test_parses_thirty_percent_and_conditional_flag(self):
        nu = self.spawner.parse_event_nuance("US_TARIFF_TEXTILE_RELIEF")
        self.assertEqual(nu["pct_reduction"], 30.0)
        self.assertEqual(nu["effective_date"], "2026-04-01")
        self.assertEqual(nu["exceptions"], ["dyes", "yarn"])
        self.assertTrue(nu["conditional_flag"])
        self.assertIn("US manufacturing plant", nu["conditional_detail"] or "")

    def test_unknown_event_returns_blank_nuance(self):
        nu = self.spawner.parse_event_nuance("NONEXISTENT_EVENT")
        self.assertEqual(nu["pct_reduction"], 0.0)
        self.assertFalse(nu["conditional_flag"])
        self.assertEqual(nu["exceptions"], [])


class TestSupplyChainNeighbors(TempDBMixin, TestCase):
    def test_second_order_forward_and_back(self):
        nb = self.spawner.fetch_supply_chain_neighbors(self.spawner.TEXTILE_PRIMARY)
        self.assertEqual(nb["upstream"], ["CottonGrowers", "DyeChemicals", "YarnSpinners"])
        self.assertEqual(nb["downstream"], ["GarmentFactories", "TextileMachineryMakers", "RetailApparel"])

    def test_neighbors_via_alias_event_id(self):
        nb = self.spawner.fetch_supply_chain_neighbors("US_TARIFF_TEXTILE_RELIEF")
        self.assertEqual(len(nb["upstream"]), 3)
        self.assertEqual(len(nb["downstream"]), 3)


class TestSpawnUsTariff(TempDBMixin, TestCase):
    def test_spawn_creates_macro_events_and_ripple_dag(self):
        res = self.spawner.spawn_us_tariff_textile_relief()
        self.assertEqual(res["events_created"], 1)
        self.assertGreaterEqual(res["ripples_created"], 7)
        self.assertEqual(res["status"], "spawned")

        # macro_events row exists
        events = self.spawner.repo.get_macro_events()
        self.assertTrue(any(e["event_id"] == "US_TARIFF_TEXTILE_RELIEF" for e in events))

        # ripple_effects has at least 3 order levels
        ripples = self.spawner.repo.get_ripple_effects_for_event("US_TARIFF_TEXTILE_RELIEF")
        levels = {r["order_level"] for r in ripples}
        self.assertIn(1, levels)
        self.assertIn(2, levels)
        self.assertIn(3, levels)
        # 6 second-order + 1 primary + 1 third-order = 8
        self.assertEqual(len(ripples), 8)

    def test_primary_is_not_biggest_beneficiary(self):
        self.spawner.spawn_us_tariff_textile_relief()
        chain = self.spawner.trace_transient_chain("US_TARIFF_TEXTILE_RELIEF", max_hops=3)
        self.assertTrue(chain, "chain must be non-empty")
        top = max(chain, key=lambda c: c["s"])
        self.assertNotEqual(
            top["order_level"], 1,
            "Acceptance violated: the primary (order 1) is the biggest beneficiary.",
        )
        # The biggest beneficiary should be the downstream TextileMachineryMakers rebound.
        self.assertEqual(top["order_level"], 2)

    def test_lag_time_months_quantized(self):
        self.spawner.spawn_us_tariff_textile_relief()
        ripples = self.spawner.repo.get_ripple_effects_for_event("US_TARIFF_TEXTILE_RELIEF")
        by_level = {r["order_level"]: r["lag_time_months"] for r in ripples}
        self.assertEqual(by_level[1], 0)    # primary at effective date
        self.assertEqual(by_level[2], 3)    # 2nd-order 3 months
        self.assertEqual(by_level[3], 6)    # 3rd-order 6 months

    def test_trace_delegates_to_causal_engine(self):
        self.spawner.spawn_us_tariff_textile_relief()
        chain = self.spawner.trace_transient_chain("US_TARIFF_TEXTILE_RELIEF", max_hops=2)
        # max_hops=2 should still return a chain (ordered by S DESC)
        self.assertTrue(chain)
        ss = [c["s"] for c in chain]
        self.assertEqual(ss, sorted(ss, reverse=True))


class TestTransactionalValidation(TempDBMixin, TestCase):
    def test_invalid_extraction_rolls_back_no_write(self):
        # A dict missing the required event_name must be rejected and write nothing.
        with self.assertRaises(ValueError):
            self.spawner.spawn_transient_event(
                event_name="Bad Event",
                event_category="Trade",
                event_id="TGE_BAD_EVENT",
                extraction={"event_category": "Trade"},  # invalid lens
            )
        # No macro_events row should have been written for this event (or at all).
        self.assertEqual(self.spawner.repo.get_macro_events(), [])

    def test_valid_dict_extraction_spawns(self):
        # A fully valid dict lens must spawn successfully (exercises the dict path).
        extraction = {
            "event_name": "Valid Dict Event",
            "event_category": "Trade",
            "primary_effects": [{
                "target_type": "Sector",
                "target_name": "TestSector",
                "transmission_channel": "test",
                "raw_magnitude": 0.2,
                "probability": 0.9,
                "lag_time_months": 0,
                "second_order_effects": [],
            }],
        }
        res = self.spawner.spawn_transient_event(
            event_name="Valid Dict Event",
            event_category="Trade",
            event_id="TGE_VALID",
            extraction=extraction,
        )
        self.assertEqual(res["events_created"], 1)
        self.assertEqual(len(self.spawner.repo.get_ripple_effects_for_event("TGE_VALID")), 1)


class TestModuleWrapper(TempDBMixin, TestCase):
    def test_spawn_event_graph_wrapper(self):
        res = spawn_event_graph("US_TARIFF_TEXTILE_RELIEF", manager=self.manager)
        self.assertEqual(res["event_id"], "US_TARIFF_TEXTILE_RELIEF")
        self.assertEqual(res["events_created"], 1)

    def test_spawn_event_graph_unknown_raises(self):
        with self.assertRaises(NotImplementedError):
            spawn_event_graph("SOME_FUTURE_EVENT", manager=self.manager)


if __name__ == "__main__":
    main()
