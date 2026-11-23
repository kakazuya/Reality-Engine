"""
Horizon-excess tests — goal-loop iteration 1 (hermetic).

Temp-file SQLite DB per case (precedent: test_portfolio_ledger.py); never the
live equity_intelligence.db. Covers:

* universe resolution incl. the NULL (unmappable) case
* excess math on seeded closes (BUY win, SELL mirror, missing-leg skip)
* weekly cohort split in excess_table
* CLI flag-parsing defaults (default path output unchanged)
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from reality_engine.db.database import DatabaseManager
from reality_engine.processing import portfolio_ledger as pl


def _mk_mgr(testcase):
    fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fh.close()
    testcase._fh_names.append(fh.name)
    mgr = DatabaseManager(Path(fh.name))
    pl.ensure_portfolio_schema(mgr)
    return mgr


def _company(conn, symbol, isin, tier=None, nifty50=0):
    conn.execute(
        "INSERT OR REPLACE INTO master_companies "
        "(isin, nse_symbol, company_name, market_cap_tier, is_nifty50, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (isin, symbol, f"{symbol} Ltd", tier, nifty50),
    )


def _price(conn, symbol, isin, date, close, prev=None):
    prev = close if prev is None else prev
    change = ((close - prev) / prev * 100.0) if prev else 0.0
    conn.execute(
        "INSERT OR REPLACE INTO daily_price_delivery "
        "(date, symbol, isin, series, open, high, low, close, prev_close, "
        " change_pct, total_volume, turnover_lacs, num_trades, "
        " deliverable_volume, delivery_pct) "
        "VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, ?, 100000, 200.0, 100, 50000, 50.0)",
        (date, symbol, isin, close * 0.99, close * 1.01, close * 0.99,
         close, prev, change),
    )


def _index(conn, index_name, date, close):
    conn.execute(
        "INSERT OR REPLACE INTO nse_index_breadth "
        "(date, index_name, open, high, low, close, change_pct) "
        "VALUES (?, ?, ?, ?, ?, ?, 0.0)",
        (date, index_name, close * 0.999, close * 1.001, close * 0.999, close),
    )


def _close_action(mgr, action_id):
    with mgr.session() as conn:
        conn.execute(
            "UPDATE portfolio_actions SET status = 'closed' WHERE action_id = ?",
            (action_id,),
        )


class HorizonExcessBase(unittest.TestCase):
    def setUp(self):
        self._fh_names = []
        self.mgr = _mk_mgr(self)

    def tearDown(self):
        for name in self._fh_names:
            try:
                os.unlink(name)
            except OSError:
                pass


class TestResolveUniverse(HorizonExcessBase):
    def test_flag_tier_rule(self):
        cases = [
            ("NIFTYCO", "INE000N01000", "LARGE", 1, "Nifty 50"),
            ("MIDCO", "INE000M01000", "MID", 0, "Nifty Midcap 150"),
            ("SMALLCO", "INE000S01000", "SMALL", 0, "Nifty Smallcap 250"),
            ("MICROCO", "INE000X01000", "MICRO", 0, "Nifty Microcap 250"),
        ]
        with self.mgr.session() as conn:
            for sym, isin, tier, flag, _ in cases:
                _company(conn, sym, isin, tier, flag)
        for sym, _, _, _, want in cases:
            with self.subTest(sym=sym):
                self.assertEqual(pl.resolve_action_universe(sym, self.mgr), want)

    def test_null_when_unmappable(self):
        with self.mgr.session() as conn:
            _company(conn, "BIGCO", "INE000B01000", "LARGE", 0)  # LARGE, not nifty50
            _company(conn, "TIERLESS", "INE000T01000", None, 0)  # NULL tier
        self.assertIsNone(pl.resolve_action_universe("BIGCO", self.mgr))
        self.assertIsNone(pl.resolve_action_universe("TIERLESS", self.mgr))
        self.assertIsNone(pl.resolve_action_universe("UNKNOWN", self.mgr))
        self.assertIsNone(pl.resolve_action_universe("", self.mgr))


class TestHorizonExcessMath(HorizonExcessBase):
    def _seed_pair(self, sym, isin, tier, stock_entry, stock_exit,
                   index_name, index_entry, index_exit,
                   action_date="2026-06-01", horizon=30):
        target = (datetime.date.fromisoformat(action_date)
                  + datetime.timedelta(days=horizon)).isoformat()
        with self.mgr.session() as conn:
            _company(conn, sym, isin, tier, 0)
            _price(conn, sym, isin, action_date, stock_entry)
            _price(conn, sym, isin, target, stock_exit)
            _index(conn, index_name, action_date, index_entry)
            _index(conn, index_name, target, index_exit)
        return action_date, target

    def test_buy_win(self):
        self._seed_pair("MIDCO", "INE000M01000", "MID",
                        100.0, 110.0, "Nifty Midcap 150", 1000.0, 1020.0)
        row = {"symbol": "MIDCO", "action": "BUY", "action_date": "2026-06-01"}
        out = pl.horizon_excess(row, 30, self.mgr)
        self.assertNotIn("skipped", out)
        self.assertEqual(out["index_name"], "Nifty Midcap 150")
        self.assertEqual(out["exit_date"], "2026-07-01")
        self.assertAlmostEqual(out["stock_ret"], 0.10)
        self.assertAlmostEqual(out["index_ret"], 0.02)
        self.assertAlmostEqual(out["excess"], 0.10 - 0.02 - 0.005)
        self.assertAlmostEqual(out["stock_entry"], 100.0)
        self.assertAlmostEqual(out["stock_exit"], 110.0)

    def test_sell_mirror(self):
        # SELL: short notional — both legs sign-flipped, same excess formula.
        self._seed_pair("SMALLCO", "INE000S01000", "SMALL",
                        100.0, 90.0, "Nifty Smallcap 250", 1000.0, 1020.0)
        row = {"symbol": "SMALLCO", "action": "SELL", "action_date": "2026-06-01"}
        out = pl.horizon_excess(row, 30, self.mgr)
        self.assertNotIn("skipped", out)
        self.assertAlmostEqual(out["stock_ret"], 0.10)   # -(0.9 - 1)
        self.assertAlmostEqual(out["index_ret"], -0.02)  # -(1.02 - 1)
        self.assertAlmostEqual(out["excess"], 0.10 - (-0.02) - 0.005)

    def test_exit_first_close_on_or_after_target(self):
        # No bar exactly on target: exit settles on the next available close.
        with self.mgr.session() as conn:
            _company(conn, "MIDCO", "INE000M01000", "MID", 0)
            _price(conn, "MIDCO", "INE000M01000", "2026-06-01", 100.0)
            _price(conn, "MIDCO", "INE000M01000", "2026-07-05", 108.0)
            _index(conn, "Nifty Midcap 150", "2026-06-01", 1000.0)
            _index(conn, "Nifty Midcap 150", "2026-07-05", 1010.0)
        row = {"symbol": "MIDCO", "action": "BUY", "action_date": "2026-06-01"}
        out = pl.horizon_excess(row, 30, self.mgr)
        self.assertEqual(out["exit_date"], "2026-07-05")
        self.assertAlmostEqual(out["stock_ret"], 0.08)

    def test_hold_always_excluded(self):
        row = {"symbol": "MIDCO", "action": "HOLD", "action_date": "2026-06-01"}
        self.assertEqual(pl.horizon_excess(row, 30, self.mgr),
                         {"skipped": "hold-excluded"})

    def test_missing_leg_skips(self):
        with self.mgr.session() as conn:
            _company(conn, "MIDCO", "INE000M01000", "MID", 0)
            _company(conn, "BARE", "INE000R01000", "MID", 0)
            _price(conn, "MIDCO", "INE000M01000", "2026-06-01", 100.0)
            # MIDCO: entry bar only — no exit bar on/after target.
            _index(conn, "Nifty Midcap 150", "2026-06-01", 1000.0)
            _index(conn, "Nifty Midcap 150", "2026-07-01", 1010.0)
        base = {"action": "BUY", "action_date": "2026-06-01"}
        self.assertEqual(
            pl.horizon_excess({**base, "symbol": "MIDCO"}, 30, self.mgr),
            {"skipped": "missing-stock-exit"})
        self.assertEqual(
            pl.horizon_excess({**base, "symbol": "BARE"}, 30, self.mgr),
            {"skipped": "missing-stock-entry"})
        # Index leg absent entirely (stock legs present): entry missing
        # (checked before exit).
        with self.mgr.session() as conn:
            _price(conn, "MIDCO", "INE000M01000", "2026-07-01", 110.0)
            conn.execute("DELETE FROM nse_index_breadth")
        self.assertEqual(
            pl.horizon_excess({**base, "symbol": "MIDCO"}, 30, self.mgr),
            {"skipped": "missing-index-entry"})

    def test_unmapped_universe_skips(self):
        with self.mgr.session() as conn:
            _company(conn, "BIGCO", "INE000B01000", "LARGE", 0)
            _price(conn, "BIGCO", "INE000B01000", "2026-06-01", 100.0)
            _price(conn, "BIGCO", "INE000B01000", "2026-07-01", 110.0)
        row = {"symbol": "BIGCO", "action": "BUY", "action_date": "2026-06-01"}
        self.assertEqual(pl.horizon_excess(row, 30, self.mgr),
                         {"skipped": "unmapped-universe"})

    def test_closed_at_stop_uses_realized_window(self):
        # Closed BUY stopped before entry+30d: exit resolves to the
        # closed leg and the index leg shares that same date.
        with self.mgr.session() as conn:
            _company(conn, "MIDCO", "INE000M01000", "MID", 0)
            _price(conn, "MIDCO", "INE000M01000", "2026-06-01", 100.0)
            _price(conn, "MIDCO", "INE000M01000", "2026-06-10", 90.0)
            _price(conn, "MIDCO", "INE000M01000", "2026-07-01", 110.0)
            _index(conn, "Nifty Midcap 150", "2026-06-01", 1000.0)
            _index(conn, "Nifty Midcap 150", "2026-06-10", 990.0)
            _index(conn, "Nifty Midcap 150", "2026-07-01", 1020.0)
        row = {"symbol": "MIDCO", "action": "BUY",
               "action_date": "2026-06-01",
               "status": "closed", "closed_date": "2026-06-10"}
        out = pl.horizon_excess(row, 30, self.mgr)
        self.assertNotIn("skipped", out)
        self.assertEqual(out["exit_date"], "2026-06-10")
        self.assertAlmostEqual(out["stock_exit"], 90.0)
        self.assertAlmostEqual(out["index_exit"], 990.0)
        self.assertAlmostEqual(out["stock_ret"], -0.10)
        self.assertAlmostEqual(out["index_ret"], -0.01)
        self.assertAlmostEqual(out["excess"], -0.10 - (-0.01) - 0.005)

    def test_open_action_keeps_horizon_exit(self):
        # Same bars, no close: pure horizon exit despite the early bar.
        with self.mgr.session() as conn:
            _company(conn, "MIDCO", "INE000M01000", "MID", 0)
            _price(conn, "MIDCO", "INE000M01000", "2026-06-01", 100.0)
            _price(conn, "MIDCO", "INE000M01000", "2026-06-10", 90.0)
            _price(conn, "MIDCO", "INE000M01000", "2026-07-01", 110.0)
            _index(conn, "Nifty Midcap 150", "2026-06-01", 1000.0)
            _index(conn, "Nifty Midcap 150", "2026-06-10", 990.0)
            _index(conn, "Nifty Midcap 150", "2026-07-01", 1020.0)
        row = {"symbol": "MIDCO", "action": "BUY",
               "action_date": "2026-06-01"}
        out = pl.horizon_excess(row, 30, self.mgr)
        self.assertNotIn("skipped", out)
        self.assertEqual(out["exit_date"], "2026-07-01")
        self.assertAlmostEqual(out["stock_ret"], 0.10)
        self.assertAlmostEqual(out["index_ret"], 0.02)

    def test_sell_mirror_preserved_under_early_close(self):
        # SELL short notional under early close: both legs sign-flipped.
        with self.mgr.session() as conn:
            _company(conn, "SMALLCO", "INE000S01000", "SMALL", 0)
            _price(conn, "SMALLCO", "INE000S01000", "2026-06-01", 100.0)
            _price(conn, "SMALLCO", "INE000S01000", "2026-06-10", 90.0)
            _price(conn, "SMALLCO", "INE000S01000", "2026-07-01", 80.0)
            _index(conn, "Nifty Smallcap 250", "2026-06-01", 1000.0)
            _index(conn, "Nifty Smallcap 250", "2026-06-10", 990.0)
            _index(conn, "Nifty Smallcap 250", "2026-07-01", 1020.0)
        row = {"symbol": "SMALLCO", "action": "SELL",
               "action_date": "2026-06-01",
               "status": "closed", "closed_date": "2026-06-10"}
        out = pl.horizon_excess(row, 30, self.mgr)
        self.assertNotIn("skipped", out)
        self.assertEqual(out["exit_date"], "2026-06-10")
        self.assertAlmostEqual(out["stock_ret"], 0.10)  # -(0.9 - 1)
        self.assertAlmostEqual(out["index_ret"], 0.01)  # -(0.99 - 1)
        self.assertAlmostEqual(out["excess"], 0.10 - 0.01 - 0.005)

    def test_late_close_keeps_horizon_exit(self):
        # Closed after the horizon exit: pure horizon window, no skip.
        with self.mgr.session() as conn:
            _company(conn, "MIDCO", "INE000M01000", "MID", 0)
            _price(conn, "MIDCO", "INE000M01000", "2026-06-01", 100.0)
            _price(conn, "MIDCO", "INE000M01000", "2026-07-01", 110.0)
            _index(conn, "Nifty Midcap 150", "2026-06-01", 1000.0)
            _index(conn, "Nifty Midcap 150", "2026-07-01", 1020.0)
        row = {"symbol": "MIDCO", "action": "BUY",
               "action_date": "2026-06-01",
               "status": "closed", "closed_date": "2026-08-01"}
        out = pl.horizon_excess(row, 30, self.mgr)
        self.assertNotIn("skipped", out)
        self.assertEqual(out["exit_date"], "2026-07-01")
        self.assertAlmostEqual(out["stock_ret"], 0.10)


class TestExcessTable(HorizonExcessBase):
    def _seed_closed_buy(self, sym, isin, action_date, stock_exit):
        target = (datetime.date.fromisoformat(action_date)
                  + datetime.timedelta(days=30)).isoformat()
        with self.mgr.session() as conn:
            _company(conn, sym, isin, "MID", 0)
            _price(conn, sym, isin, action_date, 100.0)
            _price(conn, sym, isin, target, stock_exit)
        _index_seed = [("2026-06-01", 1000.0), ("2026-07-01", 1000.0),
                       ("2026-06-09", 1000.0), ("2026-07-09", 1000.0)]
        with self.mgr.session() as conn:
            for d, c in _index_seed:
                _index(conn, "Nifty Midcap 150", d, c)
        rec = pl.record_action(sym, "BUY", action_date, 100.0, 120.0, 90.0,
                               manager=self.mgr)
        _close_action(self.mgr, rec["action_id"])

    def test_grouping_and_weekly_cohorts(self):
        # Flat index: excess = stock_ret - 0.005. Two Mondays apart.
        self._seed_closed_buy("AAA", "INE000A01000", "2026-06-01", 110.0)  # +0.095
        self._seed_closed_buy("BBB", "INE000B01000", "2026-06-09", 90.0)   # -0.105
        out = pl.excess_table(horizons=(30,), manager=self.mgr)
        cell = out["cells"]["Nifty Midcap 150"]["30"]
        self.assertEqual(cell["n"], 2)
        self.assertAlmostEqual(cell["mean_excess"], (0.095 - 0.105) / 2)
        self.assertAlmostEqual(cell["hit_rate_excess_gt0"], 0.5)
        self.assertEqual(set(cell["cohorts"]), {"2026-06-01", "2026-06-08"})
        self.assertEqual(cell["cohorts"]["2026-06-01"]["n"], 1)
        self.assertAlmostEqual(cell["cohorts"]["2026-06-01"]["mean_excess"], 0.095)
        self.assertAlmostEqual(cell["cohorts"]["2026-06-08"]["mean_excess"], -0.105)
        # Other legs empty but structured; HOLDs never enter the table.
        self.assertEqual(out["cells"]["Nifty 50"]["30"]["n"], 0)
        self.assertIsNone(out["cells"]["Nifty 50"]["30"]["mean_excess"])
        self.assertIsNone(out["cells"]["Nifty 50"]["30"]["hit_rate_excess_gt0"])
        self.assertEqual(out["actions_evaluated"], 2)
        self.assertEqual(out["uncovered_actions"], 0)

    def test_hold_excluded_and_skip_counts(self):
        self._seed_closed_buy("AAA", "INE000A01000", "2026-06-01", 110.0)
        hold = pl.record_action("BBB", "HOLD", "2026-06-01", None, None, None,
                                manager=self.mgr)
        _close_action(self.mgr, hold["action_id"])
        # Unmapped LARGE action: uncovered, never force-fit.
        with self.mgr.session() as conn:
            _company(conn, "BIGCO", "INE000C01000", "LARGE", 0)
        big = pl.record_action("BIGCO", "BUY", "2026-06-01", 100.0, 120.0, 90.0,
                               manager=self.mgr)
        _close_action(self.mgr, big["action_id"])
        out = pl.excess_table(horizons=(30, 90), manager=self.mgr)
        cell = out["cells"]["Nifty Midcap 150"]["30"]
        self.assertEqual(cell["n"], 1)  # HOLD contributed nothing
        self.assertEqual(out["actions_evaluated"], 2)  # HOLD not evaluated
        self.assertEqual(out["uncovered_actions"], 1)
        self.assertEqual(out["skipped"].get("unmapped-universe"), 2)
        self.assertIn("missing-stock-exit", out["skipped"])  # 90-day leg

    def test_empty_book_structured(self):
        out = pl.excess_table(manager=self.mgr)
        self.assertEqual(out["horizons"], [30, 90, 180, 365])
        self.assertEqual(len(out["universes"]), 4)
        for uni in out["universes"]:
            for h in ("30", "90", "180", "365"):
                self.assertEqual(out["cells"][uni][h]["n"], 0)

    def test_unknown_universe_rejected(self):
        with self.assertRaises(ValueError):
            pl.excess_table(universes=["nifty999"], manager=self.mgr)


class TestLedgerCliFlags(unittest.TestCase):
    def test_horizon_parsing(self):
        from reality_engine.cli import _parse_ledger_horizons
        self.assertEqual(_parse_ledger_horizons(None), pl.HORIZON_DEFAULTS)
        self.assertEqual(_parse_ledger_horizons("30,90,180,365"), (30, 90, 180, 365))
        self.assertEqual(_parse_ledger_horizons("30"), (30,))
        with self.assertRaises(ValueError):
            _parse_ledger_horizons("30,-5")
        with self.assertRaises(ValueError):
            _parse_ledger_horizons("")

    def test_universe_parsing(self):
        from reality_engine.cli import _parse_ledger_universes
        self.assertIsNone(_parse_ledger_universes(None))
        self.assertEqual(_parse_ledger_universes("nifty50,midcap150"),
                         ["nifty50", "midcap150"])

    def test_parser_defaults_leave_default_path(self):
        from reality_engine.cli import main  # noqa: F401  (import surface)
        import reality_engine.cli as cli_mod
        import argparse as _ap
        probe = _ap.ArgumentParser()
        sub = probe.add_subparsers(dest="command")
        p = sub.add_parser("portfolio-ledger")
        p.add_argument("--asof", default=None)
        p.add_argument("--date", default=None)
        p.add_argument("--horizons", default=None)
        p.add_argument("--universes", default=None)
        args = probe.parse_args(["portfolio-ledger"])
        self.assertIsNone(args.horizons)
        self.assertIsNone(args.universes)
        self.assertTrue(hasattr(cli_mod, "cmd_portfolio_ledger"))

    def test_default_output_is_summarize_payload(self):
        from reality_engine.cli import cmd_portfolio_ledger
        summary = {"open_count": 1, "closed_count": 0, "win_rate": None,
                   "mean_pnl": None, "total_pnl": 0.0, "by_action": {}}
        args = argparse.Namespace(asof=None, date=None,
                                  horizons=None, universes=None)
        with patch.object(pl, "summarize", return_value=dict(summary)) as ms:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_portfolio_ledger(args)
            ms.assert_called_once_with()
        self.assertEqual(json.loads(buf.getvalue()),
                         {"ok": True, **summary})

    def test_flagged_output_is_excess_table(self):
        from reality_engine.cli import cmd_portfolio_ledger
        table = {"horizons": [30], "universes": ["Nifty 50"], "cells": {},
                 "skipped": {}, "actions_evaluated": 0, "uncovered_actions": 0}
        args = argparse.Namespace(asof=None, date=None,
                                  horizons="30", universes="nifty50")
        with patch.object(pl, "excess_table",
                           return_value=dict(table)) as me:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_portfolio_ledger(args)
            me.assert_called_once_with(horizons=(30,), universes=["nifty50"])
        self.assertEqual(json.loads(buf.getvalue()), {"ok": True, **table})


class P1GridBase(unittest.TestCase):
    def setUp(self):
        self._fh_names = []
        self.mgr = _mk_mgr(self)

    def tearDown(self):
        for name in self._fh_names:
            try:
                os.unlink(name)
            except OSError:
                pass

    def _n50(self, sym, isin):
        with self.mgr.session() as conn:
            _company(conn, sym, isin, "LARGE", 1)

    def _seed_n50_index(self, start, n_days, base=24000.0, step=10.0):
        day = datetime.date.fromisoformat(start)
        out = []
        for i in range(n_days):
            d = (day + datetime.timedelta(days=i)).isoformat()
            out.append((d, base + step * i))
        with self.mgr.session() as conn:
            for d, c in out:
                _index(conn, "Nifty 50", d, c)
        return out

    def _seed_stock(self, sym, isin, dates_closes):
        with self.mgr.session() as conn:
            for d, c in dates_closes:
                _price(conn, sym, isin, d, c)

    def _closed_action(self, sym, action, action_date, closed_date,
                       entry=100.0, target=120.0, stop=90.0):
        if action == "SELL":
            entry, target, stop = 100.0, 90.0, 110.0
        rec = pl.record_action(sym, action, action_date, entry, target, stop,
                               manager=self.mgr)
        with self.mgr.session() as conn:
            conn.execute(
                "UPDATE portfolio_actions SET status = 'closed', "
                "closed_date = ? WHERE action_id = ?",
                (closed_date, rec["action_id"]),
            )
        return rec


class TestP1Regime(P1GridBase):
    def test_uptrend_drawdown_unknown(self):
        bars = [(f"2025-09-{d:02d}", 100.0 + i)
                for i, d in enumerate(range(1, 31))]
        self.assertEqual(
            pl._p1_regime_from_bars("2025-09-30", bars), "uptrend")
        down = [(d, 200.0 - i * 2.0) for i, (d, _) in enumerate(bars)]
        self.assertEqual(
            pl._p1_regime_from_bars("2025-09-30", down), "drawdown")
        self.assertEqual(pl._p1_regime_from_bars("2025-09-30", bars[:5]),
                         "unknown")  # <20 trailing bars
        self.assertEqual(pl._p1_regime_from_bars("2025-08-01", bars),
                         "unknown")  # nothing on/before the date
        self.assertEqual(pl._p1_regime_from_bars("not-a-date", bars),
                         "unknown")

    def test_point_in_time_no_peek(self):
        # A later crash must not change the earlier date's regime.
        bars = [(f"2025-09-{d:02d}", 100.0 + i)
                for i, d in enumerate(range(1, 31))]
        before = pl._p1_regime_from_bars("2025-09-20", bars)
        crashed = bars + [("2025-10-01", 10.0)]
        self.assertEqual(pl._p1_regime_from_bars("2025-09-20", crashed), before)


class TestP1PureExcess(P1GridBase):
    def _bars(self, dates, closes):
        return list(zip(dates, closes))

    def test_buy_sell_mirror_and_cost(self):
        stock = self._bars(["2025-09-01", "2025-10-01"], [100.0, 110.0])
        index = self._bars(["2025-09-01", "2025-10-01"], [1000.0, 1020.0])
        buy = pl._p1_pure_excess("BUY", "2025-09-01", 30, stock, index)
        sell = pl._p1_pure_excess("SELL", "2025-09-01", 30, stock, index)
        self.assertAlmostEqual(buy, 0.10 - 0.02 - 0.005)
        self.assertAlmostEqual(sell, -0.10 + 0.02 - 0.005)
        # Same inputs, same formula as horizon_excess up to the window rule.
        self.assertAlmostEqual(buy - sell, 0.20 - 0.04)

    def test_unresolvable_window_is_none(self):
        stock = self._bars(["2025-09-01"], [100.0])  # no exit bar
        index = self._bars(["2025-09-01", "2025-10-01"], [1000.0, 1020.0])
        self.assertIsNone(
            pl._p1_pure_excess("BUY", "2025-09-01", 30, stock, index))
        self.assertIsNone(
            pl._p1_pure_excess("HOLD", "2025-09-01", 30, stock, index))
        self.assertIsNone(
            pl._p1_pure_excess("BUY", "not-a-date", 30, stock, index))

    def test_identical_window_both_legs(self):
        # Index exit keys off the resolved STOCK exit date: a late index
        # bar before the stock exit must not leak into the window.
        stock = [("2025-09-01", 100.0), ("2025-10-05", 110.0)]
        index = [("2025-09-01", 1000.0), ("2025-10-01", 9999.0),
                 ("2025-10-05", 1020.0)]
        out = pl._p1_pure_excess("BUY", "2025-09-01", 30, stock, index)
        self.assertAlmostEqual(out, 0.10 - 0.02 - 0.005)


class TestP1CellStats(unittest.TestCase):
    def test_empty_cell_structured(self):
        out = pl._p1_cell_stats([])
        self.assertEqual(out["n"], 0)
        self.assertIsNone(out["mean_excess"])
        self.assertIsNone(out["clustered_mean"])
        self.assertIsNone(out["cohort_hit_ci_lower"])

    def test_single_cohort_has_no_clustered_interval(self):
        # G<2 must fail loudly (None), never approximate.
        out = pl._p1_cell_stats([("2026-08-24", 0.01)])
        self.assertEqual(out["n"], 1)
        self.assertAlmostEqual(out["mean_excess"], 0.01)
        self.assertEqual(out["cohorts"], 1)
        self.assertIsNone(out["clustered_mean"])
        self.assertIsNone(out["clustered_ci"])
        self.assertIsNone(out["cohort_hit_ci_lower"])
        self.assertIsNotNone(out["hit_ci_lower"])  # trade-level Wilson defined

    def test_two_cohorts_cluster(self):
        items = [("2026-08-24", 0.02), ("2026-08-24", 0.04),
                 ("2026-08-31", 0.06), ("2026-08-31", 0.08)]
        out = pl._p1_cell_stats(items)
        self.assertEqual(out["n"], 4)
        self.assertAlmostEqual(out["mean_excess"], 0.05)
        self.assertEqual(out["cohorts"], 2)
        self.assertAlmostEqual(out["clustered_mean"], 0.05)
        lo, hi = out["clustered_ci"]
        self.assertLess(lo, 0.05)
        self.assertGreater(hi, 0.05)
        # All-positive weeks: cluster hit lower is defined and high.
        self.assertIsNotNone(out["cohort_hit_ci_lower"])

    def test_wilson_lower_bounds(self):
        self.assertIsNone(pl._p1_wilson_lower(0, 0))
        self.assertAlmostEqual(pl._p1_wilson_lower(10, 10), 0.722, places=3)
        self.assertLess(pl._p1_wilson_lower(5, 10), 0.5)
        self.assertGreater(pl._p1_wilson_lower(9, 10), 0.5)


class TestP1Grid(P1GridBase):
    def _seed_two_actions(self):
        idx = self._seed_n50_index("2025-09-01", 60)
        dates = [d for d, _ in idx]
        self._n50("AAA", "INE000A01000")
        self._n50("BBB", "INE000B01000")
        self._seed_stock("AAA", "INE000A01000",
                         [(d, 100.0 + i * 0.5) for i, d in enumerate(dates)])
        self._seed_stock("BBB", "INE000B01000",
                         [(d, 200.0 - i * 0.3) for i, d in enumerate(dates)])
        self._closed_action("AAA", "BUY", dates[-30], dates[-20])
        self._closed_action("BBB", "SELL", dates[-30], dates[-25])
        return dates

    def test_grid_shape_and_placebo(self):
        dates = self._seed_two_actions()
        grid = pl.p1_grid(horizons=(30,), universes=["nifty50"],
                          n_draws=10, manager=self.mgr)
        self.assertEqual(grid["meta"]["horizons"], [30])
        self.assertEqual(grid["meta"]["universes"], ["Nifty 50"])
        self.assertEqual(grid["meta"]["book_total"], 2)
        self.assertEqual(grid["meta"]["actions_evaluated"], 2)
        self.assertEqual(grid["meta"]["eod_max"], dates[-1])
        node = grid["cells"]["Nifty 50"]["30"]
        pooled = node["pooled"]
        self.assertEqual(pooled["n"], 2)
        self.assertIsNotNone(pooled["mean_excess"])
        self.assertIsNotNone(pooled["hit_rate"])
        self.assertIsNotNone(pooled["hit_ci_lower"])
        self.assertEqual(pooled["placebo_n"], 2 * 10)
        self.assertIsNotNone(pooled["placebo_mean"])
        self.assertIsNotNone(pooled["placebo_ci"])
        self.assertIsNotNone(pooled["placebo_delta"])
        self.assertAlmostEqual(pooled["placebo_delta"],
                               pooled["mean_excess"] - pooled["placebo_mean"])
        # Regime split covers a defined regime; unknown stays structured.
        self.assertIn("uptrend", node["by_regime"])
        self.assertIn("drawdown", node["by_regime"])
        # Tiny sample rejects on every gate except possibly the placebo.
        self.assertEqual(len(grid["verdicts"]), 2)
        for v in grid["verdicts"]:
            self.assertEqual(v["verdict"], "reject")
            self.assertTrue(v["reasons"])
            self.assertIn("cost_note", v)
        self.assertIsNotNone(grid["evidence"])

    def test_deterministic_placebo(self):
        self._seed_two_actions()
        a = pl.p1_grid(horizons=(30,), universes=["nifty50"],
                       n_draws=10, manager=self.mgr)
        b = pl.p1_grid(horizons=(30,), universes=["nifty50"],
                       n_draws=10, manager=self.mgr)
        self.assertEqual(a["cells"]["Nifty 50"]["30"]["pooled"]["placebo_mean"],
                         b["cells"]["Nifty 50"]["30"]["pooled"]["placebo_mean"])

    def test_quarantine_excluded(self):
        from reality_engine.processing.substrate_hygiene import ensure_schema
        self._seed_two_actions()
        with self.mgr.session() as conn:
            ensure_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO substrate_quarantine "
                "(rule_id, table_name, row_key, severity, reason) "
                "VALUES (?,?,?,?,?)",
                ("synthetic_isin_companies", "master_companies",
                 "AAA", "quarantine", "test"),
            )
        grid = pl.p1_grid(horizons=(30,), universes=["nifty50"],
                          n_draws=5, manager=self.mgr)
        self.assertEqual(grid["meta"]["quarantined_excluded"], 1)
        self.assertEqual(
            grid["cells"]["Nifty 50"]["30"]["pooled"]["n"], 1)

    def test_empty_book_structured(self):
        grid = pl.p1_grid(horizons=(30,), universes=["nifty50"],
                          n_draws=5, manager=self.mgr)
        pooled = grid["cells"]["Nifty 50"]["30"]["pooled"]
        self.assertEqual(pooled["n"], 0)
        self.assertIsNone(pooled["mean_excess"])
        self.assertIsNone(pooled["placebo_mean"])
        self.assertEqual(grid["verdicts"], [])

    def test_bad_horizons_rejected(self):
        with self.assertRaises(ValueError):
            pl.p1_grid(horizons=(), manager=self.mgr)
        with self.assertRaises(ValueError):
            pl.p1_grid(horizons=(30, -5), manager=self.mgr)
        with self.assertRaises(ValueError):
            pl.p1_grid(horizons=(30,), universes=["nifty999"],
                       manager=self.mgr)

    def test_save_roundtrip(self):
        import json as _json
        self._seed_two_actions()
        grid = pl.p1_grid(horizons=(30,), universes=["nifty50"],
                          n_draws=5, manager=self.mgr)
        dest = os.path.join(tempfile.gettempdir(),
                            "p1_grid_roundtrip_%d.json" % os.getpid())
        try:
            out = pl.save_p1_grid(grid, dest)
            self.assertEqual(out, dest)
            with open(dest, encoding="utf-8") as _fh:
                back = _json.loads(_fh.read())
            self.assertEqual(back["meta"]["book_total"], 2)
            self.assertEqual(
                back["cells"]["Nifty 50"]["30"]["pooled"]["n"], 2)
        finally:
            try:
                os.unlink(dest)
            except OSError:
                pass

    def test_verdict_promote_branch(self):
        # Synthetic passing leg: exercises the promote path no live
        # substrate can reach (kept hermetic by construction).
        pooled = {"n": 60, "mean_excess": 0.06, "hit_rate": 0.7,
                  "cohorts": 30, "clustered_mean": 0.06,
                  "clustered_se": 0.005, "clustered_ci": [0.05, 0.07],
                  "cohort_hit_ci_lower": 0.6}
        by_regime = {
            "uptrend": {"n": 30, "mean_excess": 0.055},
            "drawdown": {"n": 30, "mean_excess": 0.065},
            "unknown": {"n": 0, "mean_excess": None},
        }
        v = pl._p1_verdict("BUY", "Nifty 50", 30, pooled, by_regime, 0.001)
        self.assertEqual(v["verdict"], "promote")
        self.assertTrue(all(c["pass"] for c in v["checks"]))
        # And the falsification gate bites when the placebo drifts.
        v2 = pl._p1_verdict("BUY", "Nifty 50", 30, pooled, by_regime, 0.05)
        self.assertEqual(v2["verdict"], "reject")
        self.assertFalse(all(c["pass"] for c in v2["checks"]))


if __name__ == "__main__":
    unittest.main()
