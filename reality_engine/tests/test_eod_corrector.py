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
        # Ripple table FIRST: ensure_eod_corrector_schema ALTERs revision_count /
        # last_revised_at onto it, which only works when the table already exists.
        self.repo.ensure_ripple_effects_schema(self.mgr)
        self.repo.ensure_eod_corrector_schema(self.mgr)
        self.repo.ensure_ensemble_ranking_schema(self.mgr)
        self.repo.ensure_moat_schema(self.mgr)
        self.repo.ensure_financial_metrics_schema(self.mgr)
        self.repo.ensure_regulatory_political_risks_schema(self.mgr)
        self.repo.ensure_substrate_history_schema(self.mgr)
        # macro_events for event tests
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
class TestDatedPredictorHonesty(EODCorrectorTestBase):
    """Goal-loop iteration 3: LEVELS GATE, FLOWS VOTE (dated deltas + momentum only).

    Dated quality/policy predictors return 0 on static fixtures (levels are
    state, not news); dated supply votes only on genuine same-session ripple
    arrivals; undated (None) calls keep legacy level behavior for
    competitive-survival re-ranking; factor momentum is untouched.
    """

    def _seed_static_substrate(self, sym="HAL", isin="INEH", score=4.0,
                               significance=80.0, severity=2.0, prob=0.9):
        with self.mgr.session() as conn:
            _insert_company(conn, sym, isin, 1)
            _insert_price(conn, sym, isin, "2026-08-26", 100.0, 98.0, turnover=300.0)
            _insert_price(conn, sym, isin, "2026-08-27", 98.0, 102.0, turnover=300.0)
            conn.execute(
                """
                INSERT OR REPLACE INTO moat_evaluations
                    (company_id, ticker, total_moat_score, moat_trajectory)
                VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol=?), ?, ?, 'Expanding')
                """,
                (sym, sym, float(score)),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO financial_metrics
                    (company_id, isin, symbol, fiscal_year, roic, wacc,
                     roic_wacc_spread, fcf_margin, debt_to_ebitda, gross_margin_peer_percentile)
                VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol=?), ?, ?, 2025,
                        0.15, 0.10, 0.05, 0.12, 1.0, 70)
                """,
                (sym, isin, sym),
            )
            conn.execute(
                """
                INSERT INTO regulatory_political_risks
                    (company_id, ticker, symbol, policy_name, risk_type, factor_type,
                     severity_score, probability, net_impact_score, coverage_status)
                VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol=?), ?, ?, 'POLICY_A',
                        'Tailwind', 'Tariff', ?, ?, ?, 'mapped')
                """,
                (sym, sym, sym, float(severity), float(prob), float(severity) * float(prob)),
            )
            conn.execute(
                """
                INSERT INTO ripple_effects
                    (event_id, target_company_id, order_level, significance_rank,
                     transmission_elasticity, raw_magnitude, probability, lag_time_months,
                     created_at)
                VALUES ('OLD_EVENT',
                        (SELECT rowid FROM master_companies WHERE nse_symbol=?),
                        1, ?, 1.0, 0.10, 0.9, 0, '2026-01-05 09:00:00')
                """,
                (sym, float(significance)),
            )

    def test_dated_quality_policy_supply_return_zero_on_static_fixtures(self):
        self._seed_static_substrate()
        # Sanity: undated level behavior still votes (backward compat baseline).
        self.assertEqual(self.corrector._predict_quality("HAL"), 1)
        self.assertEqual(self.corrector._predict_policy("HAL"), 1)
        self.assertEqual(self.corrector._predict_supply("HAL"), 1)
        # Dated: static stale substrate is state, not news -> all three vote 0.
        self.assertEqual(self.corrector._predict_quality("HAL", "2026-08-27"), 0)
        self.assertEqual(self.corrector._predict_policy("HAL", "2026-08-27"), 0)
        self.assertEqual(self.corrector._predict_supply("HAL", "2026-08-27"), 0)

    def test_dated_supply_votes_on_fresh_arrival_ripple(self):
        self._seed_static_substrate()
        with self.mgr.session() as conn:
            conn.execute(
                """
                INSERT INTO ripple_effects
                    (event_id, target_company_id, order_level, significance_rank,
                     transmission_elasticity, raw_magnitude, probability, lag_time_months,
                     created_at)
                VALUES ('FRESH_EVENT',
                        (SELECT rowid FROM master_companies WHERE nse_symbol=?),
                        1, 80.0, 1.0, 0.10, 0.9, 0, '2026-08-27 10:15:00')
                """,
                ("HAL",),
            )
        # Fresh same-session arrival votes by sign(significance - 50) = +1.
        self.assertEqual(self.corrector._predict_supply("HAL", "2026-08-27"), 1)
        # ... but not for a different session date (no arrival that day).
        self.assertEqual(self.corrector._predict_supply("HAL", "2026-08-28"), 0)
        # Quality/policy still vote 0 even with fresh supply (levels never vote dated).
        self.assertEqual(self.corrector._predict_quality("HAL", "2026-08-27"), 0)
        self.assertEqual(self.corrector._predict_policy("HAL", "2026-08-27"), 0)

    def test_dated_supply_votes_on_revised_ripple(self):
        self._seed_static_substrate()
        with self.mgr.session() as conn:
            conn.execute(
                """
                UPDATE ripple_effects SET last_revised_at = '2026-08-27 15:30:00'
                WHERE event_id = 'OLD_EVENT'
                """,
            )
        # Same-session revision is a genuine flow -> votes +1 (significance 80).
        self.assertEqual(self.corrector._predict_supply("HAL", "2026-08-27"), 1)

    def test_undated_backward_compat_preserved(self):
        self._seed_static_substrate()
        # None-date keeps legacy level semantics for existing callers
        # (competitive-survival re-ranking path).
        self.assertEqual(self.corrector._predict_quality("HAL", None), 1)
        self.assertEqual(self.corrector._predict_policy("HAL", None), 1)
    def test_factor_momentum_untouched(self):
        self._seed_static_substrate()
        # Prior-day momentum is already a flow: down day -> -1, unaffected by dating.
        self.assertEqual(self.corrector._predict_factor("HAL", -2.0), -1)
        self.assertEqual(self.corrector._predict_factor("HAL", 1.5), 1)
        # No explicit prior: falls back to price history; whatever history says,
        # the explicit-prev contract above is what attribution consumes. Here the
        # history DataFrame path yields a defined int (no crash, no None-date gap).
        hist_val = self.corrector._predict_factor("HAL", None)
        self.assertIn(hist_val, (-1, 0, 1))


class TestSubstrateHistoryDeltaVotes(EODCorrectorTestBase):
    """P0b peers-speak: dated deltas vote -1/+1/0 on fixed fixtures; levels gate."""

    def _seed_company(self, sym="HAL", isin="INEH"):
        with self.mgr.session() as conn:
            _insert_company(conn, sym, isin, 1)
            _insert_price(conn, sym, isin, "2026-08-26", 100.0, 98.0, turnover=300.0)
            _insert_price(conn, sym, isin, "2026-08-27", 98.0, 102.0, turnover=300.0)

    def test_quality_history_write_and_delta_votes(self):
        self._seed_company()
        self.repo.upsert_moat_evaluation(
            ticker="HAL", switching_costs=2, network_effects=2, cost_advantage=2,
            intangible_assets=2, efficient_scale=2, moat_trajectory="Stable", isin="INEH")
        with self.mgr.session() as conn:
            conn.execute("UPDATE moat_history SET asof_date='2026-08-20' WHERE symbol='HAL'")
        self.repo.upsert_moat_evaluation(
            ticker="HAL", switching_costs=5, network_effects=5, cost_advantage=5,
            intangible_assets=5, efficient_scale=5, moat_trajectory="Expanding", isin="INEH")
        with self.mgr.session() as conn:
            rows = conn.execute("SELECT * FROM moat_history WHERE symbol='HAL'").fetchall()
            self.assertGreaterEqual(len(rows), 1)
            conn.execute("UPDATE moat_history SET asof_date='2026-08-26' WHERE symbol='HAL' AND moat_score >= 4.5")
        self.assertEqual(self.corrector._predict_quality("HAL", "2026-08-27"), 1)
        self.assertEqual(self.corrector._predict_quality("HAL"), 1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM moat_history WHERE symbol='HAL' AND asof_date='2026-08-26'")
            conn.execute("INSERT INTO moat_history (symbol, asof_date, moat_score, moat_width, trajectory, source) "
                         "VALUES ('HAL', '2026-08-26', 2.0, 'None', 'Stable', 'test')")
            conn.execute("INSERT INTO moat_history (symbol, asof_date, moat_score, moat_width, trajectory, source) "
                         "VALUES ('HAL', '2026-08-28', 1.0, 'None', 'Deteriorating', 'test')")
        self.assertEqual(self.corrector._predict_quality("HAL", "2026-08-28"), -1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM moat_history WHERE symbol='HAL' AND asof_date='2026-08-28'")
            conn.execute("INSERT INTO moat_history (symbol, asof_date, moat_score, moat_width, trajectory, source) "
                         "VALUES ('HAL', '2026-08-28', 2.0, 'None', 'Stable', 'test')")
        self.assertEqual(self.corrector._predict_quality("HAL", "2026-08-28"), 0)

    def test_policy_history_write_and_delta_votes(self):
        self._seed_company()
        self.repo.upsert_regulatory_political_risk(
            symbol="HAL", policy_name="POLICY_A", severity_score=1.0, probability=0.5, coverage_status="mapped")
        with self.mgr.session() as conn:
            conn.execute("UPDATE policy_eni_history SET asof_date='2026-08-20' WHERE symbol='HAL'")
        self.repo.upsert_regulatory_political_risk(
            symbol="HAL", policy_name="POLICY_A", severity_score=4.0, probability=0.9, coverage_status="mapped")
        with self.mgr.session() as conn:
            rows = conn.execute("SELECT * FROM policy_eni_history WHERE symbol='HAL'").fetchall()
            self.assertGreaterEqual(len(rows), 1)
            conn.execute("UPDATE policy_eni_history SET asof_date='2026-08-26' WHERE symbol='HAL' AND net_impact_score > 1.0")
        self.assertEqual(self.corrector._predict_policy("HAL", "2026-08-27"), 1)
        self.assertEqual(self.corrector._predict_policy("HAL"), 1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM policy_eni_history WHERE symbol='HAL' AND asof_date='2026-08-26'")
            conn.execute("INSERT INTO policy_eni_history (symbol, policy_name, asof_date, net_impact_score, severity, source) "
                         "VALUES ('HAL', 'POLICY_A', '2026-08-26', 3.6, 4.0, 'test')")
            conn.execute("INSERT INTO policy_eni_history (symbol, policy_name, asof_date, net_impact_score, severity, source) "
                         "VALUES ('HAL', 'POLICY_A', '2026-08-28', -3.6, -4.0, 'test')")
        self.assertEqual(self.corrector._predict_policy("HAL", "2026-08-28"), -1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM policy_eni_history WHERE symbol='HAL' AND asof_date='2026-08-28'")
            conn.execute("INSERT INTO policy_eni_history (symbol, policy_name, asof_date, net_impact_score, severity, source) "
                         "VALUES ('HAL', 'POLICY_A', '2026-08-28', 3.6, 4.0, 'test')")
        self.assertEqual(self.corrector._predict_policy("HAL", "2026-08-28"), 0)

    def test_supply_history_revision_delta_votes(self):
        self._seed_company()
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO financial_metrics (company_id, isin, symbol, fiscal_year, roic, wacc, "
                "roic_wacc_spread, fcf_margin, debt_to_ebitda, gross_margin_peer_percentile) "
                "VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol='HAL'), 'INEH', 'HAL', 2025, "
                "0.15, 0.10, 0.05, 0.12, 1.0, 70)")
            conn.execute(
                "INSERT INTO moat_evaluations (company_id, ticker, total_moat_score, moat_trajectory) "
                "VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol='HAL'), 'HAL', 4.0, 'Expanding')")
        n = self.repo.upsert_ripple_effects("EV1", [
            {"order_level": 1, "target_company_id": 1, "transmission_channel": "direct",
             "significance_rank": 80.0, "transmission_elasticity": 1.0,
             "raw_magnitude": 0.5, "probability": 0.9, "lag_time_months": 0},
            {"order_level": 2, "target_company_id": 1, "transmission_channel": "direct",
             "significance_rank": 70.0, "transmission_elasticity": 1.0,
             "raw_magnitude": 0.4, "probability": 0.8, "lag_time_months": 0},
        ])
        self.assertEqual(n, 2)
        with self.mgr.session() as conn:
            hist = conn.execute("SELECT * FROM ripple_history").fetchall()
            self.assertGreaterEqual(len(hist), 2)
            conn.execute("UPDATE ripple_history SET asof_date='2026-08-20'")
        rev = self.repo.apply_event_revision("EV1", manager=self.mgr)
        self.assertGreaterEqual(rev["n_revised"], 1)
        # Day-one revision snapshot lands fresh: revision-delta votes (no
        # same-session arrival on 2026-08-27, so this is the history vote).
        self.assertEqual(self.corrector._supply_session_arrival("HAL", "2026-08-27"), 0)
        self.assertNotEqual(self.corrector._ripple_significance_delta("HAL", "2026-08-27"), 0.0)
        self.assertIn(self.corrector._predict_supply("HAL", "2026-08-27"), (-1, 1))
        self.assertEqual(self.corrector._predict_supply("HAL"), 1)

    def test_stale_levels_never_vote_dated(self):
        # High moat / positive ENI / high significance with no dated history:
        # legacy undated levels vote +1, but dated predictors vote 0.
        self._seed_company()
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO moat_evaluations (company_id, ticker, total_moat_score, moat_trajectory) "
                "VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol='HAL'), 'HAL', 4.0, 'Expanding')")
            conn.execute(
                "INSERT INTO regulatory_political_risks (company_id, ticker, symbol, policy_name, risk_type, factor_type, "
                "severity_score, probability, net_impact_score, coverage_status) "
                "VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol='HAL'), 'HAL', 'HAL', 'POLICY_A', "
                "'Tailwind', 'Tariff', 2.0, 0.9, 1.8, 'mapped')")
        self.assertEqual(self.corrector._predict_quality("HAL"), 1)
        self.assertEqual(self.corrector._predict_policy("HAL"), 1)
        self.assertEqual(self.corrector._predict_quality("HAL", "2026-08-27"), 0)
        self.assertEqual(self.corrector._predict_policy("HAL", "2026-08-27"), 0)


if __name__ == "__main__":
    unittest.main()
