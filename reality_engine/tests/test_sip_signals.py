"""
SIP signal-leg tests — hermetic temp-DB (precedent: test_move_attribution.py).

Covers the observable contract of reality_engine.processing.sip_signals:
  1. Pre-window dates behave as benchmark (both legs equal-weight).
  2. Leg A tilts toward fresh BUY names; stale (>30d) votes don't tilt.
  3. Leg B fades fresh SELL + fresh quality -1 + snapshot quality-broken
     names; pre-window there is no fade.
  4. load_signal_maps excludes quarantined (INE_AUTO_*) masters, never deletes.
  5. Live zero rows for supply -1 / quality -1 are handled: fade still fires
     via SELL + snapshot quality (the shipped reality).
  6. Report raises a clear RuntimeError while the sip_backtest engine is absent
     (no silent empty artifact); scope caveat forbids multi-lens claims.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing import sip_signals as S
from reality_engine.processing.sip_signals import SignalMaps


def _company(conn, symbol, isin, sector="Financial Services", nifty50=0):
    conn.execute(
        """
        INSERT OR REPLACE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector,
             market_cap_tier, is_nifty50, is_active)
        VALUES (?, ?, ?, 'Banks', ?, 'LARGE', ?, 1)
        """,
        (isin, symbol, f"{symbol} Ltd", sector, int(nifty50)),
    )


def _price(conn, symbol, isin, date, prev_close, close):
    change = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_price_delivery
            (date, symbol, isin, series, open, high, low, close, prev_close,
             change_pct, total_volume, turnover_lacs, num_trades,
             deliverable_volume, delivery_pct, delivery_spike_ratio, rsi_14)
        VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, ?, 100000, 200.0, 100,
                50000, 50.0, 1.0, 50.0)
        """,
        (date, symbol, isin, close * 0.99, close * 1.01, close, close,
         prev_close, change),
    )


def _action(conn, symbol, action, date, framing="buy"):
    if framing == "buy":
        entry, target, stop = 100.0, 106.0, 98.0
    else:  # honest SELL framing: target < entry < stop
        entry, target, stop = 100.0, 94.0, 102.0
    conn.execute(
        """
        INSERT OR REPLACE INTO portfolio_actions
            (symbol, action, action_date, entry_price, target_price,
             stop_loss, status)
        VALUES (?, ?, ?, ?, ?, ?, 'open')
        """,
        (symbol, action, date, entry, target, stop),
    )


def _moat(conn, symbol, score=4.0, trajectory="Stable"):
    conn.execute(
        """
        INSERT OR REPLACE INTO moat_evaluations
            (company_id, ticker, total_moat_score, moat_trajectory)
        VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol=?),
                ?, ?, ?)
        """,
        (symbol, symbol, float(score), trajectory),
    )


def _attrib(conn, symbol, date, sdir=0, qdir=0):
    conn.execute(
        """
        INSERT OR REPLACE INTO move_attribution
            (symbol, attribution_date, realized_move_pct, noise_floor,
             is_material, explained_total, residual,
             lens_factor_statistical_dir, lens_business_quality_dir,
             lens_policy_macro_dir, lens_supply_chain_dir,
             lens_factor_statistical_w, lens_business_quality_w,
             lens_policy_macro_w, lens_supply_chain_w,
             lens_factor_statistical_share, lens_business_quality_share,
             lens_policy_macro_share, lens_supply_chain_share,
             investor_majority, regime_tag)
        VALUES (?, ?, -3.0, 1.0, 1, 0.3, 0.7, 1, ?, 0, ?, 0.3, 0.25, 0.25,
                0.2, 0.3, 0.0, 0.0, 0.0, 'all', '*')
        """,
        (symbol, date, int(qdir), int(sdir)),
    )


class SipSignalsBase(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))
        self.repo = Repository(self.mgr)
        for _fn in ("ensure_ensemble_ranking_schema", "ensure_moat_schema",
                    "ensure_financial_metrics_schema"):
            try:
                getattr(self.repo, _fn)(self.mgr)
            except Exception:
                pass
        from reality_engine.processing.move_attributor import (
            ensure_move_attribution_schema,
        )
        from reality_engine.processing.portfolio_ledger import (
            ensure_portfolio_schema,
        )

        ensure_move_attribution_schema(self.mgr)
        ensure_portfolio_schema(self.mgr)

    def tearDown(self):
        try:
            Path(self._fh.name).unlink()
        except Exception:
            pass

    def _universe(self):
        with self.mgr.session() as conn:
            _company(conn, "AAA", "INEAAA01000")
            _company(conn, "BBB", "INEBBB01000")
            _company(conn, "CCC", "INECCC01000")
            for d in ("2026-08-20", "2026-09-01", "2026-09-15"):
                _price(conn, "AAA", "INEAAA01000", d, 100.0, 102.0)
                _price(conn, "BBB", "INEBBB01000", d, 100.0, 102.0)
                _price(conn, "CCC", "INECCC01000", d, 100.0, 102.0)
            _moat(conn, "AAA", 4.0, "Stable")
            _moat(conn, "BBB", 4.0, "Stable")
            _moat(conn, "CCC", 4.0, "Stable")


class TestPreWindowIsBenchmark(SipSignalsBase):
    def test_both_legs_equal_weight_before_2026_08(self):
        self._universe()
        with self.mgr.session() as conn:
            _action(conn, "AAA", "BUY", "2026-09-15")
            _action(conn, "BBB", "SELL", "2026-09-15", framing="sell")
        maps = S.load_signal_maps(self.mgr)
        syms = ["AAA", "BBB", "CCC"]
        for mode in ("A", "B", "ZZZ"):
            w = S.weights_for_rebalance(syms, "2021-11-01", mode, maps)
            self.assertEqual(
                {k: round(v, 6) for k, v in w.items()},
                {"AAA": round(1 / 3, 6), "BBB": round(1 / 3, 6),
                 "CCC": round(1 / 3, 6)},
                f"mode {mode} must equal-weight pre-window",
            )

    def test_unknown_mode_equal_weights_in_window(self):
        self._universe()
        maps = S.load_signal_maps(self.mgr)
        w = S.weights_for_rebalance(["AAA", "BBB"], "2026-09-16", "Q", maps)
        self.assertAlmostEqual(w["AAA"], 0.5)
        self.assertAlmostEqual(w["BBB"], 0.5)

    def test_empty_universe_empty_weights(self):
        maps = SignalMaps()
        self.assertEqual(S.weights_for_rebalance([], "2026-09-16", "A", maps), {})


class TestLegARotation(SipSignalsBase):
    def test_fresh_buy_tilts(self):
        self._universe()
        with self.mgr.session() as conn:
            _action(conn, "AAA", "BUY", "2026-09-15")
        maps = S.load_signal_maps(self.mgr)
        w = S.weights_for_rebalance(["AAA", "BBB", "CCC"], "2026-09-16", "A", maps)
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertGreater(w["AAA"], w["BBB"])
        self.assertAlmostEqual(w["BBB"], w["CCC"])
        # exact tilt: 2 / (2+1+1)
        self.assertAlmostEqual(w["AAA"], 2.0 / 4.0)
        self.assertAlmostEqual(w["BBB"], 1.0 / 4.0)

    def test_stale_buy_does_not_tilt(self):
        self._universe()
        with self.mgr.session() as conn:
            _action(conn, "AAA", "BUY", "2026-08-01")  # 46d before 09-16
        maps = S.load_signal_maps(self.mgr)
        w = S.weights_for_rebalance(["AAA", "BBB", "CCC"], "2026-09-16", "A", maps)
        self.assertAlmostEqual(w["AAA"], 1 / 3)
        self.assertAlmostEqual(w["BBB"], 1 / 3)

    def test_no_votes_is_benchmark(self):
        self._universe()
        maps = S.load_signal_maps(self.mgr)
        w = S.weights_for_rebalance(["AAA", "BBB"], "2026-09-16", "A", maps)
        self.assertAlmostEqual(w["AAA"], 0.5)
        self.assertAlmostEqual(w["BBB"], 0.5)


class TestLegBFade(SipSignalsBase):
    def test_fresh_sell_fades(self):
        self._universe()
        with self.mgr.session() as conn:
            _action(conn, "AAA", "SELL", "2026-09-15", framing="sell")
        maps = S.load_signal_maps(self.mgr)
        w = S.weights_for_rebalance(["AAA", "BBB", "CCC"], "2026-09-16", "B", maps)
        self.assertEqual(w["AAA"], 0.0)
        self.assertAlmostEqual(w["BBB"], 0.5)
        self.assertAlmostEqual(w["CCC"], 0.5)

    def test_fresh_quality_neg_fades(self):
        self._universe()
        with self.mgr.session() as conn:
            _attrib(conn, "BBB", "2026-09-15", qdir=-1)
        maps = S.load_signal_maps(self.mgr)
        self.assertIn("BBB", maps.quality_neg_by_date.get("2026-09-15", set()))
        w = S.weights_for_rebalance(["AAA", "BBB", "CCC"], "2026-09-16", "B", maps)
        self.assertEqual(w["BBB"], 0.0)
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_snapshot_quality_broken_fades_without_fresh_vote(self):
        self._universe()
        with self.mgr.session() as conn:
            _moat(conn, "CCC", 2.0, "Stable")  # low moat -> broken
        maps = S.load_signal_maps(self.mgr)
        self.assertIn("CCC", maps.quality_broken)
        self.assertTrue(maps.meta["quality_broken_is_snapshot_not_pit"])
        w = S.weights_for_rebalance(["AAA", "BBB", "CCC"], "2026-09-16", "B", maps)
        self.assertEqual(w["CCC"], 0.0)

    def test_intact_names_never_fade(self):
        self._universe()
        maps = S.load_signal_maps(self.mgr)
        self.assertEqual(maps.quality_broken, {})
        w = S.weights_for_rebalance(["AAA", "BBB"], "2026-09-16", "B", maps)
        self.assertAlmostEqual(w["AAA"], 0.5)

    def test_fade_all_is_benchmark_not_zero_portfolio(self):
        self._universe()
        with self.mgr.session() as conn:
            _moat(conn, "AAA", 2.0, "Stable")
            _moat(conn, "BBB", 2.0, "Stable")
        maps = S.load_signal_maps(self.mgr)
        w = S.weights_for_rebalance(["AAA", "BBB"], "2026-09-16", "B", maps)
        self.assertAlmostEqual(w["AAA"], 0.5)
        self.assertAlmostEqual(w["BBB"], 0.5)


class TestQuarantineAndScope(SipSignalsBase):
    def test_quarantined_masters_excluded_never_deleted(self):
        self._universe()
        with self.mgr.session() as conn:
            _company(conn, "QUAR", "INE_AUTO_000001")
            _action(conn, "QUAR", "BUY", "2026-09-15")
            _moat(conn, "QUAR", 2.0, "Stable")
        maps = S.load_signal_maps(self.mgr)
        buys = S.active_buy_set(maps, "2026-09-16")
        self.assertNotIn("QUAR", buys)
        self.assertNotIn("QUAR", maps.quality_broken)
        with self.mgr.session() as conn:
            row = conn.execute(
                "SELECT nse_symbol FROM master_companies WHERE nse_symbol='QUAR'"
            ).fetchone()
        self.assertIsNotNone(row, "quarantined rows are excluded, never deleted")

    def test_scope_caveat_forbids_multi_lens_claim(self):
        self.assertIn("factor/technical-only", S.SCOPE_CAVEAT)
        self.assertIn("NOT", S.SCOPE_CAVEAT)
        self.assertIn("multi-lens", S.SCOPE_CAVEAT)

    def test_zero_neg_vote_census_recorded(self):
        self._universe()
        maps = S.load_signal_maps(self.mgr)
        self.assertEqual(maps.meta["n_supply_neg_votes"], 0)
        self.assertEqual(maps.meta["n_quality_neg_votes"], 0)
        self.assertTrue(maps.meta["policy_eni_unobservable_here"])


class TestReportContract(unittest.TestCase):
    def test_report_runs_three_legs_on_sip_engine(self):
        from reality_engine.processing.sip_signals import SCOPE_CAVEAT

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
            name = fh.name
        try:
            mgr = DatabaseManager(Path(name))
            with mgr.session() as conn:
                _company(conn, "AAA", "INEAAA01000")
                _company(conn, "BBB", "INEBBB01000")
                for d in ("2026-09-15", "2026-09-16"):
                    _price(conn, "AAA", "INEAAA01000", d, 100.0, 102.0)
                    _price(conn, "BBB", "INEBBB01000", d, 100.0, 102.0)
            rep = S.signal_vs_benchmark_report(
                mgr, symbols=["AAA", "BBB"],
                start="2026-09-15", end="2026-09-16")
            for key in ("benchmark", "leg_a_p0_rotation", "leg_b_f1_fade",
                        "deltas_vs_benchmark_post_tax"):
                self.assertIn(key, rep)
            self.assertIn("factor/technical-only", rep["scope_caveat"])
            self.assertEqual(rep["scope_caveat"], SCOPE_CAVEAT)
            self.assertIn("post_tax_xirr", rep["benchmark"])
            self.assertIn("leg_a_p0_rotation",
                          rep["deltas_vs_benchmark_post_tax"])
        finally:
            try:
                Path(name).unlink()
            except Exception:
                pass

    def test_weights_fn_signature_and_unknown_symbol(self):
        syms = ["AAA", "BBB"]
        maps = SignalMaps(
            buy_by_date={"2026-09-15": {"AAA"}}, meta={"n_buy_votes": 1}
        )
        fn = S.make_weights_fn(syms, "A", maps)
        self.assertGreater(fn("AAA", "2026-09-16"), fn("BBB", "2026-09-16"))
        self.assertEqual(fn("ZZZ-UNKNOWN", "2026-09-16"), 0.0)
        self.assertEqual(fn("AAA", "2021-11-01"), 0.5)  # pre-window benchmark


if __name__ == "__main__":
    unittest.main()
