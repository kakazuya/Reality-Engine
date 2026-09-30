"""
Desk backtest tests — temp DB / pure fixtures only (never the live DB).

Covers the assignment acceptance: Rs 10cr init cash, 40% sweep trigger,
tax boundaries (364/365/366 + pre/post-2024-07-23 regimes via the reused
``sip_backtest`` schedule), SELL-invariant abort, vol-bracket clamps,
quarantine exclusion on every read, 4x4 cell shape + placebo~=0 on a
shuffled fixture, cost bridge, drawdown/Calmar/TUW + sleeve attribution,
and the artifact contract (cells + coverage footer + scope caveats).
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.processing import desk_backtest as db
from reality_engine.processing import portfolio_ledger as pl
from reality_engine.processing import sip_backtest as sb


def _days(start: str, n: int) -> list:
    base = datetime.date.fromisoformat(start)
    return [(base + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _flat(symbols, days, price):
    return {s: {d: float(price(s, d) if callable(price) else price)
                for d in days} for s in symbols}


def _company(conn, sym, isin, n50=0, tier=None, sector="Banks"):
    conn.execute(
        "INSERT OR REPLACE INTO master_companies "
        "(isin, nse_symbol, company_name, industry, sector, "
        "market_cap_tier, is_nifty50, is_active) "
        "VALUES (?,?,?,?,?,?,?,1)",
        (isin, sym, "%s Ltd" % sym, "Ind", sector, tier, n50),
    )


def _price(conn, sym, isin, date, close, prev=None):
    prev = close if prev is None else prev
    conn.execute(
        "INSERT OR REPLACE INTO daily_price_delivery "
        "(date, symbol, isin, open, high, low, close, prev_close, change_pct,"
        " total_volume, deliverable_volume, delivery_pct)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, 1000, 500, 50.0)",
        (date, sym, isin, close, close, close, close, prev),
    )


def _index(conn, name, date, close):
    conn.execute(
        "INSERT OR REPLACE INTO nse_index_breadth "
        "(date, index_name, close, change_pct) VALUES (?,?,?,0.0)",
        (date, name, close),
    )


def _quarantine(conn, isin):
    from reality_engine.processing.substrate_hygiene import ensure_schema
    ensure_schema(conn)
    conn.execute(
        "INSERT OR REPLACE INTO substrate_quarantine "
        "(rule_id, table_name, row_key, severity, reason) "
        "VALUES (?,?,?,?,?)",
        ("synthetic_isin_companies", "master_companies",
         isin, "quarantine", "test"),
    )


class TestDeskConstants(unittest.TestCase):
    def test_cash_start_sweep_horizons(self):
        self.assertEqual(db.DESK_INITIAL_CASH, 100000000.0)
        self.assertEqual(db.DESK_START, "2021-10-27")
        self.assertEqual(db.SWEEP_MAX_FRACTION, 0.40)
        self.assertEqual(tuple(db.DESK_HORIZONS), (30, 90, 180, 365))
        self.assertEqual(db.K_TARGET, 3.0)
        self.assertEqual(db.K_STOP, 1.0)
        self.assertEqual(db.RISK_FREE_RATE, 0.0)

    def test_no_tax_table_duplication(self):
        self.assertNotIn("TAX_SCHEDULE", vars(db))
        self.assertIn("TAX_SCHEDULE", vars(sb))
        self.assertEqual(len(sb.TAX_SCHEDULE), 2)

    def test_bootstrap_weights_frozen(self):
        self.assertEqual(db.DESK_BOOTSTRAP_WEIGHTS,
                         {"factor_statistical": 0.30,
                          "business_quality": 0.25,
                          "policy_macro": 0.25,
                          "supply_chain": 0.20})

    def test_strategies_paper_only(self):
        for leg in ("F1", "F2", "F3"):
            self.assertTrue(db.STRATEGY_STATUS[leg]["paper_only"])
            self.assertFalse(db.STRATEGY_STATUS[leg]["promoted"])


class TestInitCashAndSweep(unittest.TestCase):
    def test_lump_sum_10cr_sweep_40(self):
        days = _days("2021-10-27", 3)
        prices = _flat(["AAA"], days, 100.0)
        book = db.run_desk_book(["AAA"], prices, {"AAA": "Banks"}, days,
                                thesis_fn=None)
        self.assertAlmostEqual(book["contributions"], 100000000.0, places=2)
        self.assertEqual(len(book["nav_daily"]), 3)
        for row in book["nav_daily"]:
            self.assertAlmostEqual(row["nav_post"], 100000000.0, places=2)
            self.assertTrue(row["sweep_active"])
            self.assertAlmostEqual(row["sweep_fraction"], 0.40, places=9)
        for row in book["sweep_path"]:
            self.assertLessEqual(row["sweep_fraction"], 0.400001)
        self.assertEqual(book["n_buys"], 0)
        self.assertEqual(book["n_sells"], 0)
        self.assertEqual(book["flags"]["initial_cash"], 100000000.0)
        self.assertTrue(book["flags"]["lump_sum"])
        self.assertFalse(book["flags"]["sip"])
        self.assertEqual(book["flags"]["fractional_shares"], "backtest-only")

    def test_thesis_buy_disables_sweep(self):
        days = _days("2021-10-27", 3)
        prices = _flat(["AAA"], days, 100.0)
        book = db.run_desk_book(["AAA"], prices, {"AAA": "Banks"}, days,
                                thesis_fn=lambda s, d: "BUY")
        self.assertGreater(book["n_buys"], 0)
        self.assertFalse(any(r["sweep_active"] for r in book["nav_daily"]))
        self.assertAlmostEqual(book["nav_daily"][-1]["nav_post"],
                               100000000.0, delta=100000000.0 * 0.01)

    def test_gold_sweep_leg(self):
        days = _days("2021-10-27", 3)
        prices = {"AAA": {d: 100.0 for d in days},
                  "GOLDBEES": {d: 50.0 for d in days}}
        book = db.run_desk_book(["AAA"], prices, {"AAA": "Banks"}, days,
                                thesis_fn=None,
                                gold_symbols=("GOLDBEES",))
        self.assertGreater(book["n_sweep_buys"], 0)
        self.assertGreater(book["sweep_path"][-1]["etf_value"], 0.0)

    def test_buy_then_sell_pays_tax(self):
        days = _days("2023-01-02", 5)
        prices = {"AAA": {d: (100.0 if d < days[2] else 200.0)
                          for d in days}}
        order = {"n": 0}

        def thesis(s, d):
            if d == days[0]:
                return "BUY"
            if d == days[3]:
                return "SELL"
            return "HOLD"

        book = db.run_desk_book(["AAA"], prices, {"AAA": "Banks"}, days,
                                thesis_fn=thesis)
        self.assertGreater(book["n_buys"], 0)
        self.assertGreaterEqual(book["n_sells"], 1)
        self.assertGreater(book["taxes_paid"], 0.0)

    def test_march_harvest_sells_losses(self):
        days = ["2024-03-27", "2024-03-28", "2024-03-29"]
        prices = {"AAA": {"2024-03-27": 100.0, "2024-03-28": 60.0,
                          "2024-03-29": 50.0}}
        book = db.run_desk_book(
            ["AAA"], prices, {"AAA": "Banks"}, days,
            thesis_fn=lambda s, d: "BUY" if d == days[0] else "HOLD")
        self.assertGreaterEqual(book["n_harvest_sells"], 1)


class TestTaxBoundariesReused(unittest.TestCase):
    def _sell_tax(self, buy, hold_days, gain=10000.0):
        sell = (datetime.date.fromisoformat(buy)
                + datetime.timedelta(days=hold_days)).isoformat()
        gains = [{"symbol": "AAA", "buy_date": buy, "qty": 1.0,
                  "gain": gain, "holding_days": hold_days}]
        return sb.tax_on_sale(gains, sell, {})

    def test_regime_boundary(self):
        self.assertEqual(sb.rate_for("2024-07-22")["stcg_rate"], 0.15)
        self.assertEqual(sb.rate_for("2024-07-23")["stcg_rate"], 0.20)
        self.assertEqual(sb.rate_for("2024-07-23")["ltcg_rate"], 0.125)

    def test_holding_364_365_short_366_long(self):
        t364, _ = self._sell_tax("2024-09-02", 364)
        t365, _ = self._sell_tax("2024-09-02", 365)
        t366, _ = self._sell_tax("2024-09-02", 366)
        self.assertAlmostEqual(t364, 0.20 * 10000.0, places=6)
        self.assertAlmostEqual(t365, 0.20 * 10000.0, places=6)
        self.assertAlmostEqual(t366, 0.0, places=6)

    def test_pre_2024_stcg_15(self):
        tax, _ = self._sell_tax("2023-01-02", 100)
        self.assertAlmostEqual(tax, 0.15 * 10000.0, places=6)

    def test_ltcg_exemption_per_fy(self):
        lt = lambda g: [{"symbol": "A", "buy_date": "2023-06-01",
                         "qty": 1.0, "gain": g, "holding_days": 400}]
        used: dict = {}
        tax1, inc1 = sb.tax_on_sale(lt(100000.0), "2025-05-01", used)
        self.assertAlmostEqual(tax1, 0.0, places=6)
        self.assertAlmostEqual(inc1, 100000.0, places=6)
        used["FY26"] = used.get("FY26", 0.0) + inc1
        tax2, inc2 = sb.tax_on_sale(lt(100000.0), "2025-06-01", used)
        self.assertAlmostEqual(tax2, 0.125 * 75000.0, places=6)
        self.assertAlmostEqual(inc2, 25000.0, places=6)


class TestSellInvariant(unittest.TestCase):
    def test_sell_good_framing_passes(self):
        db.assert_thesis_framing("SELL", 100.0, 94.0, 102.0)
        db.assert_thesis_framing("BUY", 100.0, 106.0, 98.0)
        db.assert_thesis_framing("HOLD", None, None, None)

    def test_sell_long_framed_aborts(self):
        with self.assertRaises(ValueError):
            db.assert_thesis_framing("SELL", 100.0, 106.0, 102.0)
        with self.assertRaises(ValueError):
            db.assert_thesis_framing("SELL", 100.0, 106.0, 98.0)
        with self.assertRaises(ValueError):
            db.assert_thesis_framing("BUY", 100.0, 94.0, 98.0)
        with self.assertRaises(ValueError):
            db.assert_thesis_framing("HOLD", 100.0, 90.0, 110.0)

    def test_run_aborts_on_bad_thesis_dict(self):
        days = _days("2021-10-27", 2)
        prices = _flat(["AAA"], days, 100.0)

        def bad_thesis(s, d):
            return {"action": "SELL", "entry": 100.0,
                    "target": 118.0, "stop": 94.0}

        with self.assertRaises(ValueError):
            db.run_desk_book(["AAA"], prices, {"AAA": "Banks"}, days,
                             thesis_fn=bad_thesis)

    def test_bracket_mirrored(self):
        hist = [100.0 + (i % 2) for i in range(30)]
        buy = db.desk_bracket(100.0, hist, "BUY")
        sell = db.desk_bracket(100.0, hist, "SELL")
        self.assertGreater(buy["target_price"], 100.0)
        self.assertLess(buy["stop_loss"], 100.0)
        self.assertLess(sell["target_price"], 100.0)
        self.assertGreater(sell["stop_loss"], 100.0)


class TestVolBrackets(unittest.TestCase):
    def test_flat_clamped_to_min(self):
        self.assertAlmostEqual(db.trailing_sigma_pct([100.0] * 30), 0.5,
                               places=9)

    def test_wild_capped_to_max(self):
        closes = [100.0 if i % 2 == 0 else 200.0 for i in range(30)]
        self.assertAlmostEqual(db.trailing_sigma_pct(closes), 8.0, places=9)

    def test_short_history_fallback(self):
        self.assertAlmostEqual(db.trailing_sigma_pct([100.0, 101.0]), 2.0,
                               places=9)


class TestQuarantineMarket(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))

    def tearDown(self):
        try:
            os.unlink(self._fh.name)
        except OSError:
            pass

    def _seed(self, with_quarantine_table=True):
        days = ["2021-10-27", "2021-10-28", "2021-10-29"]
        with self.mgr.session() as conn:
            _company(conn, "AAA", "INE000A01000", 1, None, "Banks")
            _company(conn, "BBB", "INE000B01000", 0, "MID", "IT")
            _company(conn, "CCC", "INE000C01000", 0, "SMALL", "IT")
            _company(conn, "DDD", "INE000D01000", 0, "MICRO", "IT")
            _company(conn, "EEE", "INE000E01000", 0, "LARGE", "IT")
            _company(conn, "FFF", "INE_AUTO_FFF", 0, "MICRO", "IT")
            for sym, isin, px in (("AAA", "INE000A01000", 100.0),
                                  ("BBB", "INE000B01000", 50.0),
                                  ("CCC", "INE000C01000", 20.0),
                                  ("DDD", "INE000D01000", 10.0),
                                  ("EEE", "INE000E01000", 500.0),
                                  ("FFF", "INE_AUTO_FFF", 5.0)):
                for d in days:
                    _price(conn, sym, isin, d, px)
            for name in ("Nifty 50", "Nifty Midcap 150",
                         "Nifty Smallcap 250", "Nifty Microcap 250"):
                for d in days:
                    _index(conn, name, d, 1000.0)
            if with_quarantine_table:
                _quarantine(conn, "INE_AUTO_FFF")
        return days

    def test_quarantine_excluded_every_read(self):
        self._seed()
        mkt = db.load_desk_market(self.mgr, start="2021-10-27",
                                  end="2021-10-29")
        self.assertNotIn("FFF", mkt["symbols"])
        self.assertNotIn("FFF", mkt["price_map"])
        self.assertGreaterEqual(mkt["coverage"]["quarantined_excluded"], 1)
        self.assertIn("EEE", mkt["coverage"]["unmapped"])
        self.assertEqual(mkt["coverage"]["per_universe_n"]["Nifty 50"], 1)
        self.assertEqual(
            mkt["coverage"]["per_universe_n"]["Nifty Midcap 150"], 1)
        self.assertEqual(
            mkt["coverage"]["per_universe_n"]["Nifty Smallcap 250"], 1)
        self.assertEqual(
            mkt["coverage"]["per_universe_n"]["Nifty Microcap 250"], 1)
        self.assertEqual(mkt["flags"]["initial_cash"], 100000000.0)

    def test_explicit_symbols_still_filtered(self):
        self._seed()
        mkt = db.load_desk_market(self.mgr, symbols=["AAA", "FFF"],
                                  start="2021-10-27", end="2021-10-29")
        self.assertEqual(mkt["symbols"], ["AAA"])
        self.assertEqual(mkt["coverage"]["quarantined_excluded"], 1)

    def test_zero_close_unusable(self):
        days = self._seed()
        with self.mgr.session() as conn:
            _price(conn, "AAA", "INE000A01000", "2021-10-30", 0.0)
        mkt = db.load_desk_market(self.mgr, start="2021-10-27",
                                  end="2021-10-30")
        self.assertNotIn("2021-10-30", mkt["price_map"]["AAA"])


class TestExcess4x4(unittest.TestCase):
    def _flat_world(self, n=60, px=100.0):
        days = _days("2021-10-27", n)
        pmap = {"AAA": {d: px for d in days},
                "BBB": {d: px for d in days}}
        imap = {"Nifty 50": {d: 1000.0 for d in days},
                "Nifty Midcap 150": {d: 500.0 for d in days},
                "Nifty Smallcap 250": {d: 200.0 for d in days},
                "Nifty Microcap 250": {d: 100.0 for d in days}}
        return days, pmap, imap

    def test_cell_shape_and_placebo_zero(self):
        days, pmap, imap = self._flat_world()
        entries = [{"symbol": "AAA", "action": "BUY",
                    "entry_date": days[10], "closed_date": None}]
        grid = db.excess_4x4(
            entries, pmap, imap,
            universe_of={"AAA": "Nifty 50", "BBB": "Nifty 50"},
            horizons=(30,), n_draws=10, seed=7)
        cell = grid["cells"]["Nifty 50"]["30"]
        for key in ("n", "cohorts", "clustered_mean_bps",
                    "clustered_ci_bps", "hit", "hit_ci_lower",
                    "cohort_hit_ci_lower", "placebo_mean_bps",
                    "placebo_ci_bps", "placebo_delta_bps",
                    "by_regime", "index_relative"):
            self.assertIn(key, cell)
        self.assertEqual(cell["n"], 1)
        self.assertIsNotNone(cell["placebo_mean_bps"])
        self.assertLessEqual(abs(cell["placebo_mean_bps"]), 100.0)
        self.assertIn("Nifty 50", grid["coverage"]["per_universe_n"])
        self.assertIn("unmapped", grid["coverage"])

    def test_sell_avoided_loss_mirror(self):
        days = _days("2021-10-27", 40)
        pmap = {"AAA": {d: (100.0 if d < days[20] else 110.0) for d in days},
                "BBB": {d: 100.0 for d in days}}
        imap = {"Nifty 50": {d: 1000.0 for d in days},
                "Nifty Midcap 150": {d: 500.0 for d in days},
                "Nifty Smallcap 250": {d: 200.0 for d in days},
                "Nifty Microcap 250": {d: 100.0 for d in days}}
        sbars = db._bars_from_map(pmap)
        ibars = db._bars_from_map(imap)
        peers = {"BBB": sbars["BBB"]}
        buy = db.excess_for_entry("BUY", days[5], 30, None, "AAA",
                                  sbars["AAA"], peers, ibars["Nifty 50"])
        sell = db.excess_for_entry("SELL", days[5], 30, None, "AAA",
                                   sbars["AAA"], peers, ibars["Nifty 50"])
        self.assertGreater(buy["xs_excess"], 0.0)
        self.assertLess(sell["xs_excess"], 0.0)
        self.assertAlmostEqual(buy["xs_excess"] + sell["xs_excess"],
                               -2.0 * pl.EXCESS_COST, places=9)

    def test_realized_window_min_close(self):
        # Closed leg (10-05) beats the horizon leg (entry+30 -> 11-01,
        # past the last bar 10-29): min(close, entry+h) = 10-05.
        bars = [("2021-10-%02d" % d, 100.0 + d) for d in range(1, 30)]
        rw = db.realized_window(bars, "2021-10-02", 30,
                                closed_date="2021-10-05")
        self.assertIn("exit_date", rw)
        self.assertEqual(rw["exit_date"], "2021-10-05")
        # Pure horizon leg inside coverage: entry+3 -> 10-05 exactly.
        rw2 = db.realized_window(bars, "2021-10-02", 3, closed_date=None)
        self.assertIn("exit_date", rw2)
        self.assertEqual(rw2["exit_date"], "2021-10-05")
        # Closed leg past EOD still resolves the horizon leg (10-29),
        # not a skip: min(close, entry+h).
        rw3 = db.realized_window(bars, "2021-10-02", 10,
                                 closed_date="2021-12-01")
        self.assertIn("exit_date", rw3)
        self.assertEqual(rw3["exit_date"], "2021-10-12")

    def test_quarantined_entries_skipped(self):
        days, pmap, imap = self._flat_world()
        entries = [{"symbol": "QQQ", "action": "BUY",
                    "entry_date": days[10], "closed_date": None}]
        pmap["QQQ"] = {d: 10.0 for d in days}
        grid = db.excess_4x4(
            entries, pmap, imap,
            universe_of={"QQQ": "Nifty 50"},
            horizons=(30,), n_draws=2, quarantined={"QQQ"})
        self.assertEqual(grid["cells"]["Nifty 50"]["30"]["n"], 0)
        self.assertEqual(grid["coverage"]["quarantined_excluded"], 1)


class TestCostsDrawdownArtifact(unittest.TestCase):
    def test_cost_bridge_math(self):
        b = db.apply_cost_stack(0.02, tax_drag=0.0)
        self.assertAlmostEqual(b["net"], 0.0125, places=12)
        bps = db.cost_bridge_bps(0.02)
        # Spec Sec 1.8 stack: 50bps impact + 10bps STT/side + 5bps other.
        self.assertAlmostEqual(bps["impact_prior_bps"], 50.0, places=6)
        self.assertAlmostEqual(bps["stt_buy_bps"], 10.0, places=6)
        self.assertAlmostEqual(bps["stt_sell_bps"], 10.0, places=6)
        self.assertAlmostEqual(bps["other_bps"], 5.0, places=6)
        self.assertAlmostEqual(bps["net_bps"], 125.0, places=6)
        self.assertAlmostEqual(bps["gross_bps"], 200.0, places=6)
        self.assertTrue(bps["impact_prior_assumed"])

    def test_drawdown_calmar_tuw(self):
        dates = ["2022-01-01", "2022-02-01", "2022-03-01", "2022-04-01"]
        rep = db.drawdown_report(dates, [100.0, 120.0, 90.0, 135.0])
        self.assertAlmostEqual(rep["max_dd"], 0.25, places=9)
        self.assertEqual(rep["peak_date"], "2022-02-01")
        self.assertEqual(rep["trough_date"], "2022-03-01")
        self.assertEqual(rep["recovery_date"], "2022-04-01")
        self.assertEqual(rep["time_under_water_days"], 59)
        self.assertIsNotNone(rep["cagr"])
        self.assertIsNotNone(rep["calmar"])

    def test_sleeve_attribution(self):
        dates = _days("2022-01-01", 4)
        attr = db.sleeve_drawdown_attribution(
            dates, [100.0, 110.0, 105.0, 115.0],
            [100.0, 110.0, 90.0, 115.0])
        self.assertGreater(attr["reduction"], 0.0)
        self.assertAlmostEqual(attr["reduction_bps"],
                               attr["reduction"] * 10000.0, places=9)

    def test_artifact_contract(self):
        days = _days("2021-10-27", 40)
        pmap = {"AAA": {d: 100.0 + float(days.index(d)) * 0.1
                        for d in days},
                "BBB": {d: 100.0 for d in days}}
        imap = {"Nifty 50": {d: 1000.0 for d in days},
                "Nifty Midcap 150": {d: 500.0 for d in days},
                "Nifty Smallcap 250": {d: 200.0 for d in days},
                "Nifty Microcap 250": {d: 100.0 for d in days}}
        book = db.run_desk_book(["AAA", "BBB"], pmap,
                                {"AAA": "Banks", "BBB": "IT"}, days,
                                thesis_fn=lambda s, d: "BUY"
                                if (s == "AAA" and d == days[0]) else "HOLD")
        grid = db.excess_4x4(book["entries_log"], pmap, imap,
                             universe_of={"AAA": "Nifty 50",
                                          "BBB": "Nifty 50"},
                             horizons=(30,), n_draws=5)
        art = db.build_desk_artifact(book=book, grid=grid)
        self.assertEqual(art["meta"]["initial_cash"], 100000000.0)
        self.assertEqual(art["meta"]["horizons"], [30, 90, 180, 365])
        self.assertEqual(len(art["meta"]["universes"]), 4)
        self.assertIn("Nifty 50", art["cells"])
        self.assertEqual(len(art["meta"]["cost_schedule"]["regimes"]), 2)
        for leg in ("F1", "F2", "F3"):
            self.assertTrue(art["strategies"][leg]["paper_only"])
            self.assertFalse(art["strategies"][leg]["promoted"])
        self.assertTrue(art["scope_caveats"])
        footer = db.format_coverage_4x4(grid)
        self.assertIn("unmapped", footer)
        self.assertIn("quarantined_excluded", footer)

    def test_f_legs_paper_only(self):
        f1 = db.f1_forensic_avoid("AAA", "2024-01-02", {}, {})
        self.assertFalse(f1["avoid"])
        self.assertTrue(f1["paper_only"] and not f1["promoted"])
        f1b = db.f1_forensic_avoid(
            "AAA", "2024-01-02",
            {"ni_negative": True, "de_gt_1_5": False, "sgi_gt_1_5": False,
             "margin_collapse": True, "leverage_jump": False,
             "f5_score": 1}, {})
        self.assertTrue(f1b["avoid"])
        f1c = db.f1_forensic_avoid(
            "AAA", "2024-01-02", {"ni_negative": True},
            {"feat": "2025-01-01"})
        self.assertIn("pit-violation", f1c["reason"])
        f2 = db.f2_continuation_signal("AAA", "2024-01-02", 5.0, 2.0, 1, 1)
        self.assertTrue(f2["enter"])
        f2b = db.f2_continuation_signal("AAA", "2024-01-02", 1.0, 2.0, 1, 1)
        self.assertFalse(f2b["enter"])
        kill = db.f2_kill(499.0)
        self.assertTrue(kill["kill"])
        self.assertFalse(db.f2_kill(500.0)["kill"])
        f3 = db.f3_carry_allocation("RISK-OFF", True)
        self.assertAlmostEqual(f3["sleeve_fraction"], 0.40, places=9)
        self.assertTrue(f3["paper_only"] and not f3["promoted"])


class TestEndToEndTempDb(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))

    def tearDown(self):
        try:
            os.unlink(self._fh.name)
        except OSError:
            pass
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                os.unlink(self._fh.name + suffix)
            except OSError:
                pass

    def test_run_desk_backtest_wires_grid(self):
        days = _days("2021-10-27", 40)
        with self.mgr.session() as conn:
            _company(conn, "AAA", "INE000A01000", 1, None, "Banks")
            _company(conn, "BBB", "INE000B01000", 1, None, "IT")
            for d in days:
                _price(conn, "AAA", "INE000A01000", d,
                       100.0 + float(days.index(d)) * 0.2)
                _price(conn, "BBB", "INE000B01000", d, 50.0)
            for name, base in (("Nifty 50", 1000.0),
                               ("Nifty Midcap 150", 500.0),
                               ("Nifty Smallcap 250", 200.0),
                               ("Nifty Microcap 250", 100.0)):
                for d in days:
                    _index(conn, name, d, base)
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "desk_artifact.json")
            art = db.run_desk_backtest(
                self.mgr, thesis_fn=lambda s, d: "BUY"
                if (s == "AAA" and d == days[0]) else "HOLD",
                start="2021-10-27", end=days[-1], save_to=dest, n_draws=5)
            self.assertTrue(os.path.exists(dest))
            with open(dest, encoding="utf-8") as fh:
                loaded = json.load(fh)
            self.assertIn("cells", loaded)
            self.assertIn("coverage_footer", art)
            self.assertIn("Nifty 50", art["cells"])
            self.assertGreaterEqual(
                art["cells"]["Nifty 50"]["30"]["n"], 1)
            self.assertEqual(art["book_summary"]["contributions"],
                             100000000.0)


if __name__ == "__main__":
    unittest.main()
