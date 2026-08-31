"""
Deterministic tests for Wave D3 — EODCorrector continuous self-correction.

Uses throwaway temp SQLite databases; never touches the project's real DB. Verifies the
plan §2 Wave D Task D3 acceptance:

  * correct_eod --universe nifty200 re-ranks lenses and learns per-scrip noise floors.
  * noise-floor --symbol TITAGARH returns a value (adaptive, not a global hard cutoff).
  * correct-event --event ... revises the 2nd-order graph (revision_count stamped).
  * re-rank lenses changes explain_power (competitive survival).
  * cadence is NOT intraday: correct_eod requires a closed-session EOD date and rejects
    an intraday/partial date.

All data is seeded explicitly so the tests are fully deterministic.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.eod_corrector import (
    EODCorrector,
    LENS_FAMILY_QUALITY,
    LENS_FAMILY_FACTOR,
    LENS_FAMILY_POLICY,
    LENS_FAMILY_SUPPLY,
)
from reality_engine.processing.ensemble_ranker import EnsembleRanker
from reality_engine.processing.event_graph import spawn_event_graph


def _insert_company(conn, symbol, isin, nifty200=1):
    conn.execute(
        """
        INSERT OR REPLACE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector, is_nifty200, is_active)
        VALUES (?, ?, ?, 'Industrials', 'Capital Goods', ?, 1)
        """,
        (isin, symbol, f"{symbol} Ltd", nifty200),
    )


def _insert_price(conn, symbol, isin, date, prev_close, close, turnover=200.0, volume=100000):
    change = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_price_delivery
            (date, symbol, isin, series, open, high, low, close, prev_close, change_pct,
             total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct,
             delivery_spike_ratio, rsi_14)
        VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, ?, ?, ?, 100, ?, 50.0, 1.0, 50.0)
        """,
        (date, symbol, isin, close * 0.99, close * 1.01, close, close, prev_close, change,
         int(volume), float(turnover), int(volume * 0.5)),
    )


class EODCorrectorTestBase(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))  # runs schema.sql
        self.repo = Repository(self.mgr)
        self.repo.ensure_eod_corrector_schema(self.mgr)
        self.repo.ensure_ensemble_ranking_schema(self.mgr)
        self.repo.ensure_moat_schema(self.mgr)
        # ripple_effects + macro_events for event tests
        self.repo.ensure_ripple_effects_schema(self.mgr)
        self.repo.ensure_macro_event_doc_id(self.mgr)
        self.corrector = EODCorrector(self.mgr)
        self.ranker = EnsembleRanker(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self._fh.name)
        except OSError:
            pass


class TestCorrectEODLearnsNoiseFloors(EODCorrectorTestBase):
    def test_correct_eod_updates_noise_floors_and_summary(self):
        with self.mgr.session() as conn:
            _insert_company(conn, "TITAGARH", "INE1", 1)
            # 3 sessions so realized-vol has >1 return; last session is the EOD target.
            _insert_price(conn, "TITAGARH", "INE1", "2026-08-25", 100.0, 102.0, turnover=300.0)
            _insert_price(conn, "TITAGARH", "INE1", "2026-08-26", 102.0, 99.0, turnover=120.0)
            _insert_price(conn, "TITAGARH", "INE1", "2026-08-27", 99.0, 101.0, turnover=150.0)

        res = self.corrector.correct_eod(universe="nifty200", target_date="2026-08-27", dry_run=False)

        # Summary correctness
        self.assertEqual(res["target_date"], "2026-08-27")
        self.assertFalse(res["dry_run"])
        self.assertEqual(res["symbols_corrected"], 1)
        self.assertEqual(res["noise_floors_updated"], 1)

        # The floor is actually persisted and retrievable.
        floor = self.repo.get_per_scrip_noise_floor("TITAGARH")
        self.assertIsNotNone(floor)
        self.assertGreaterEqual(floor, 30.0)
        self.assertLessEqual(floor, 80.0)

        # Audit log recorded.
        log = self.repo.get_eod_correction_log(limit=5)
        self.assertTrue(any(r["correction_type"] == "eod" for r in log))

    def test_dry_run_does_not_persist(self):
        with self.mgr.session() as conn:
            _insert_company(conn, "TITAGARH", "INE1", 1)
            _insert_price(conn, "TITAGARH", "INE1", "2026-08-27", 99.0, 101.0, turnover=150.0)

        res = self.corrector.correct_eod(universe="nifty200", target_date="2026-08-27", dry_run=True)
        self.assertTrue(res["dry_run"])
        # Nothing persisted.
        self.assertIsNone(self.repo.get_per_scrip_noise_floor("TITAGARH"))
        self.assertEqual(self.repo.get_eod_correction_log(limit=5), [])


class TestNoiseFloorAdaptive(EODCorrectorTestBase):
    def test_get_noise_floor_returns_value_for_titagarh(self):
        # No learned floor, no history -> deterministic adaptive stub (not a global cutoff).
        f = self.corrector.get_noise_floor("TITAGARH")
        self.assertIsInstance(f, float)
        self.assertGreaterEqual(f, 30.0)
        self.assertLessEqual(f, 80.0)

    def test_noise_floor_is_adaptive_not_global(self):
        # Liquid name should clear at a LOWER floor than an illiquid name.
        liquid = self.corrector.get_noise_floor("TITAGARH", turnover_lacs=5000.0, change_pct=0.2)
        illiquid = self.corrector.get_noise_floor("TITAGARH", turnover_lacs=5.0, change_pct=8.0)
        self.assertLess(liquid, illiquid, "illiquid should require a stronger signal (higher floor)")

    def test_get_noise_floor_returns_learned_value(self):
        self.repo.set_per_scrip_noise_floor("TITAGARH", 62.5, realized_vol=0.03, liquidity=80.0)
        self.assertAlmostEqual(self.corrector.get_noise_floor("TITAGARH"), 62.5)


class TestReRankLenses(EODCorrectorTestBase):
    def _seed_rankings(self, symbol, factor=0.90, quality=0.10, policy=0.10, supply=0.10):
        self.ranker.upsert_ranking(symbol, None, None, None, "all", LENS_FAMILY_FACTOR, 0.01, factor)
        self.ranker.upsert_ranking(symbol, None, None, None, "all", LENS_FAMILY_QUALITY, 0.04, quality)
        self.ranker.upsert_ranking(symbol, None, None, None, "all", LENS_FAMILY_POLICY, 0.20, policy)
        self.ranker.upsert_ranking(symbol, None, None, None, "all", LENS_FAMILY_SUPPLY, 0.10, supply)

    def test_rerank_changes_explain_power(self):
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
            # prev day DOWN, target day UP -> realized +1; factor predicted -1 (mismatch->decay),
            # quality predicted +1 via moat>=3 (match->reward).
            _insert_price(conn, sym, "INEH", "2026-08-26", 100.0, 98.0, turnover=300.0)
            _insert_price(conn, sym, "INEH", "2026-08-27", 98.0, 102.0, turnover=300.0)
            # Moat substrate: bullish (score >= 3) -> business_quality predicts +1.
            conn.execute(
                """
                INSERT OR REPLACE INTO moat_evaluations
                    (company_id, ticker, total_moat_score, moat_trajectory)
                VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol=?), ?, 4.0, 'Expanding')
                """,
                (sym, sym),
            )

        self._seed_rankings(sym, factor=0.90, quality=0.10, policy=0.10, supply=0.10)

        res = self.corrector.correct_eod(universe=[sym], target_date="2026-08-27", dry_run=False)
        self.assertEqual(res["symbols_corrected"], 1)
        self.assertGreaterEqual(res["lens_rank_changes"], 1)

        after = {r["lens_family"]: float(r["explain_power"])
                 for r in self.ranker.get_rankings(sym, "all")}
        # Business-quality predicted correctly -> rewarded (up).
        self.assertGreater(after[LENS_FAMILY_QUALITY], 0.10)
        # Factor predicted wrong direction (prior day down, price up) -> penalized (down).
        self.assertLess(after[LENS_FAMILY_FACTOR], 0.90)

    def test_competitive_survival_reorders_ranks(self):
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
            _insert_price(conn, sym, "INEH", "2026-08-26", 100.0, 98.0, turnover=300.0)
            _insert_price(conn, sym, "INEH", "2026-08-27", 98.0, 102.0, turnover=300.0)
            conn.execute(
                """
                INSERT OR REPLACE INTO moat_evaluations
                    (company_id, ticker, total_moat_score, moat_trajectory)
                VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol=?), ?, 4.0, 'Expanding')
                """,
                (sym, sym),
            )
        # Seed factor as the dominant lens initially, but only *marginally* so that a
        # single EOD competitive-survival batch (factor penalized, quality rewarded) can
        # actually reorder the ranks. A 0.90 vs 0.10 gap cannot reorder in one ±0.05 step.
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_FACTOR, 0.01, 0.15)
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_QUALITY, 0.04, 0.10)
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_POLICY, 0.20, 0.10)
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_SUPPLY, 0.10, 0.10)

        before_ranks = {r["lens_family"]: r["rank"] for r in self.ranker.get_rankings(sym, "all")}
        self.assertEqual(before_ranks[LENS_FAMILY_FACTOR], 1)  # factor was top

        self.corrector.correct_eod(universe=[sym], target_date="2026-08-27", dry_run=False)

        after_ranks = {r["lens_family"]: r["rank"] for r in self.ranker.get_rankings(sym, "all")}
        # After the EOD batch, business_quality (rewarded) should climb and factor (penalized)
        # should drop in rank relative to before.
        self.assertLess(after_ranks[LENS_FAMILY_QUALITY], before_ranks[LENS_FAMILY_QUALITY])
        self.assertGreater(after_ranks[LENS_FAMILY_FACTOR], before_ranks[LENS_FAMILY_FACTOR])


class TestCadenceNotIntraday(EODCorrectorTestBase):
    def test_rejects_intraday_or_missing_session_date(self):
        with self.mgr.session() as conn:
            _insert_company(conn, "TITAGARH", "INE1", 1)
            _insert_price(conn, "TITAGARH", "INE1", "2026-08-27", 99.0, 101.0, turnover=150.0)

        # A date with NO daily_price_delivery rows is treated as intraday/partial -> rejected.
        with self.assertRaises(ValueError):
            self.corrector.correct_eod(universe=["TITAGARH"], target_date="2099-01-01", dry_run=False)

    def test_accepts_valid_eod_date(self):
        with self.mgr.session() as conn:
            _insert_company(conn, "TITAGARH", "INE1", 1)
            _insert_price(conn, "TITAGARH", "INE1", "2026-08-27", 99.0, 101.0, turnover=150.0)

        res = self.corrector.correct_eod(universe=["TITAGARH"], target_date="2026-08-27", dry_run=False)
        self.assertEqual(res["symbols_corrected"], 1)


class TestCorrectEventRevisesSecondOrder(EODCorrectorTestBase):
    def test_correct_event_revises_second_order_graph(self):
        # Spawn the canonical transient graph (creates macro_events + ripple_effects).
        spawn_event_graph("US_TARIFF_TEXTILE_RELIEF", manager=self.mgr)
        ripples_before = self.repo.get_ripple_effects_for_event("US_TARIFF_TEXTILE_RELIEF")
        self.assertTrue(any(r["order_level"] >= 2 for r in ripples_before))

        res = self.corrector.correct_event("US_TARIFF_TEXTILE_RELIEF")
        self.assertTrue(res["graph_respawned"])
        rev = res["ripple_revision"]
        self.assertGreaterEqual(rev["n_revised"], 1)

        # 2nd-order rows now carry revision_count >= 1 (durable change to the graph).
        ripples_after = self.repo.get_ripple_effects_for_event("US_TARIFF_TEXTILE_RELIEF")
        second_order = [r for r in ripples_after if r["order_level"] >= 2]
        self.assertTrue(second_order)
        self.assertTrue(all(int(r.get("revision_count") or 0) >= 1 for r in second_order))

        # Audit log recorded for the event correction.
        log = self.repo.get_eod_correction_log(limit=5)
        self.assertTrue(any(r["correction_type"] == "event" for r in log))

    def test_correct_event_reranks_impacted_lenses(self):
        # Seed a ranking for a symbol, then run an event correction targeting it.
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_FACTOR, 0.01, 0.50)
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_POLICY, 0.20, 0.20)
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_SUPPLY, 0.10, 0.15)
        self.ranker.upsert_ranking(sym, None, None, None, "all", LENS_FAMILY_QUALITY, 0.04, 0.15)

        res = self.corrector.correct_event("US_TARIFF_TEXTILE_RELIEF", symbols=[sym])
        self.assertGreaterEqual(res["lens_rank_changes"], 1)

        after = {r["lens_family"]: float(r["explain_power"]) for r in self.ranker.get_rankings(sym, "all")}
        # Event is a macro/policy/supply signal -> those lenses are reinforced.
        self.assertGreater(after[LENS_FAMILY_POLICY], 0.20)
        self.assertGreater(after[LENS_FAMILY_SUPPLY], 0.15)


class TestCLIDispatchers(EODCorrectorTestBase):
    def test_cmd_noise_floor_prints_and_returns(self):
        import reality_engine.processing.eod_corrector as ec

        class _Args:
            symbol = "TITAGARH"
            turnover = 2000.0
            change = 0.2

        # Monkeypatch default corrector to use temp DB
        orig = ec._default_corrector
        ec._default_corrector = self.corrector
        try:
            val = ec.cmd_noise_floor(_Args())
        finally:
            ec._default_corrector = orig
        self.assertIsInstance(val, float)

    def test_cmd_correct_eod_runs(self):
        import reality_engine.processing.eod_corrector as ec

        class _Args:
            universe = "nifty200"
            date = "2026-08-27"
            dry_run = False
            update_substrate = False
            symbols = None

        with self.mgr.session() as conn:
            _insert_company(conn, "TITAGARH", "INE1", 1)
            _insert_price(conn, "TITAGARH", "INE1", "2026-08-27", 99.0, 101.0, turnover=150.0)

        orig = ec._default_corrector
        ec._default_corrector = self.corrector
        try:
            res = ec.cmd_correct_eod(_Args())
        finally:
            ec._default_corrector = orig
        self.assertEqual(res["symbols_corrected"], 1)


if __name__ == "__main__":
    unittest.main()
