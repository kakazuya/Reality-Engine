"""
SIP backtest tests — tax-aware N50 equal-weight benchmark leg (hermetic).

Temp-file SQLite DB per DB case (precedent: test_portfolio_ledger.py);
pure-engine cases use in-memory price maps, no DB. Covers the assignment:

* SIP lot accounting (1L + 3 monthly SIPs -> lots / contributions)
* late-joiner cash-hold (no lots before listing, flagged)
* STCG/LTCG boundary (364 vs 365 vs 366 days)
* drawdown math on a fixed series
"""

from __future__ import annotations

import datetime
import os
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.processing import sip_backtest as sb


def _days(start: str, n: int) -> list:
    base = datetime.date.fromisoformat(start)
    return [(base + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _flat_prices(symbols, days, price_of):
    return {s: {d: float(price_of(s)) for d in days} for s in symbols}


class TestSipSchedule(unittest.TestCase):
    def test_seed_plus_three_sips(self):
        sched = sb.build_sip_schedule("2021-10-27", "2022-01-15")
        self.assertEqual(
            [e["target_date"] for e in sched],
            ["2021-10-27", "2021-11-01", "2021-12-01", "2022-01-01"],
        )
        self.assertEqual(
            [e["amount"] for e in sched], [100000.0, 50000.0, 50000.0, 50000.0]
        )

    def test_resolve_trade_date_next_trading_day(self):
        days = ["2021-11-01", "2021-11-02", "2021-11-03"]
        # Sunday before coverage -> next trading day (holiday rule).
        self.assertEqual(sb.resolve_trade_date("2021-10-31", days), "2021-11-01")
        self.assertEqual(sb.resolve_trade_date("2021-11-02", days), "2021-11-02")
        self.assertIsNone(sb.resolve_trade_date("2021-11-04", days))

    def test_empty_when_end_before_start(self):
        self.assertEqual(sb.build_sip_schedule("2022-01-01", "2021-01-01"), [])


class TestTaxSchedule(unittest.TestCase):
    def test_verified_rates(self):
        pre, post = sb.TAX_SCHEDULE
        self.assertEqual((pre["stcg_rate"], pre["ltcg_rate"], pre["ltcg_exempt"]),
                         (0.15, 0.10, 100000.0))
        self.assertEqual(post["effective_from"], "2024-07-23")
        self.assertEqual((post["stcg_rate"], post["ltcg_rate"], post["ltcg_exempt"]),
                         (0.20, 0.125, 125000.0))

    def test_regime_boundary(self):
        self.assertEqual(sb.rate_for("2024-07-22")["stcg_rate"], 0.15)
        self.assertEqual(sb.rate_for("2024-07-23")["stcg_rate"], 0.20)

    def _sell_tax(self, buy: str, hold_days: int, gain: float = 10000.0):
        sell = (datetime.date.fromisoformat(buy)
                + datetime.timedelta(days=hold_days)).isoformat()
        gains = [{"symbol": "AAA", "buy_date": buy, "qty": 1.0,
                  "gain": gain, "holding_days": hold_days}]
        return sb.tax_on_sale(gains, sell, {}), sell

    def test_holding_boundary_364_365_366(self):
        # Post-2024 regime: STCG 20%; LTCG under 1.25L exempt -> 0.
        (tax364, _), _ = self._sell_tax("2024-09-02", 364)[0], None
        (tax365, _), _ = self._sell_tax("2024-09-02", 365)[0], None
        (tax366, _), _ = self._sell_tax("2024-09-02", 366)[0], None
        self.assertAlmostEqual(tax364, 0.20 * 10000.0, places=6)
        self.assertAlmostEqual(tax365, 0.20 * 10000.0, places=6)  # 365d still short
        self.assertAlmostEqual(tax366, 0.0, places=6)

    def test_ltcg_exemption_tracks_per_fy(self):
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

    def test_sell_fifo_order_and_cost_base(self):
        lots: list = []
        sb.add_lot(lots, "AAA", "2024-09-02", 10.0, 100.0)
        sb.add_lot(lots, "AAA", "2024-09-03", 10.0, 100.0)
        self.assertAlmostEqual(lots[0].cost_per_share, 100.0 * 1.0015, places=9)
        proceeds, gains = sb.sell_fifo(lots, 15.0, 110.0, "2024-10-01")
        self.assertAlmostEqual(proceeds, 15.0 * 110.0 * 0.9985, places=6)
        self.assertEqual([g["qty"] for g in gains], [10.0, 5.0])
        self.assertEqual([g["buy_date"] for g in gains],
                         ["2024-09-02", "2024-09-03"])
        self.assertEqual(len(lots), 1)
        self.assertAlmostEqual(lots[0].qty, 5.0, places=9)


class TestSipLots(unittest.TestCase):
    def test_1l_plus_3sips_buy_only(self):
        days = ["2021-10-27", "2021-12-01", "2022-01-01", "2022-02-01"]
        syms = ["AAA", "BBB"]
        prices = _flat_prices(syms, days, lambda s: 100.0 if s == "AAA" else 200.0)
        sectors = {"AAA": "Banks", "BBB": "IT"}
        sched = [
            {"target_date": "2021-10-27", "amount": 100000.0},
            {"target_date": "2021-12-01", "amount": 50000.0},
            {"target_date": "2022-01-01", "amount": 50000.0},
            {"target_date": "2022-02-01", "amount": 50000.0},
        ]
        art = sb.run_sip(syms, prices, sectors, days, schedule=sched,
                         start="2021-10-27", monthly_rebalance=False,
                         sector_cap=1.0)
        self.assertAlmostEqual(art["contributions"], 250000.0, places=6)
        self.assertEqual(len(art["lots"]), 8)  # 2 names x 4 SIPs
        self.assertEqual(art["n_buys"], 8)
        self.assertEqual(art["n_sells"], 0)
        self.assertAlmostEqual(art["taxes_paid"], 0.0, places=6)
        for key in ("post_tax_xirr", "max_dd", "rolling", "sharpe",
                    "sortino", "taxes_paid", "contributions", "flags"):
            self.assertIn(key, art)

    def test_sector_cap_overflow_stays_cash(self):
        days = _days("2021-10-27", 3)
        syms = ["AAA", "BBB"]
        prices = _flat_prices(syms, days, lambda s: 100.0)
        sectors = {"AAA": "Banks", "BBB": "Banks"}
        art = sb.run_sip(syms, prices, sectors, days,
                         schedule=[{"target_date": days[0], "amount": 100000.0}],
                         start=days[0], monthly_rebalance=False,
                         sector_cap=0.10)
        last = art["cash_path"][-1]
        self.assertGreater(last["cash_fraction"], 0.8)
        for row in art["sector_path"]:
            self.assertLessEqual(sum(row["weights"].values()), 0.11)

    def test_rebalance_sells_pay_tax(self):
        days = _days("2021-10-27", 40)
        syms = ["AAA", "BBB"]
        prices = {
            "AAA": {d: (100.0 if d < days[30] else 300.0) for d in days},
            "BBB": {d: 100.0 for d in days},
        }
        sectors = {"AAA": "Banks", "BBB": "IT"}
        sched = [{"target_date": days[0], "amount": 100000.0},
                 {"target_date": days[30], "amount": 50000.0}]
        art = sb.run_sip(syms, prices, sectors, days, schedule=sched,
                         start=days[0], monthly_rebalance=True, sector_cap=1.0)
        self.assertGreaterEqual(art["n_sells"], 1)
        self.assertGreater(art["taxes_paid"], 0.0)  # pre-2024 STCG 15%


class TestLateJoiner(unittest.TestCase):
    def test_cash_held_until_listed(self):
        days = _days("2021-10-27", 5)
        prices = {
            "EARLY": {d: 100.0 for d in days},
            "LATE": {d: 100.0 for d in days[2:]},
        }
        sectors = {"EARLY": "Banks", "LATE": "IT"}
        art = sb.run_sip(["EARLY", "LATE"], prices, sectors, days,
                         schedule=[{"target_date": days[0], "amount": 50000.0},
                                   {"target_date": days[2], "amount": 50000.0}],
                         start=days[0], monthly_rebalance=False, sector_cap=1.0)
        self.assertEqual(art["late_joiners"], ["LATE"])
        late_lots = [l for l in art["lots"] if l["symbol"] == "LATE"]
        self.assertTrue(late_lots)  # joins once listed
        for lot in late_lots:
            self.assertGreaterEqual(lot["buy_date"], days[2])
        early_lots = [l for l in art["lots"] if l["symbol"] == "EARLY"]
        self.assertTrue(any(l["buy_date"] == days[0] for l in early_lots))


class TestMetrics(unittest.TestCase):
    def test_drawdown_fixed_series(self):
        dates = ["2022-01-01", "2022-02-01", "2022-03-01", "2022-04-01"]
        dd = sb.nav_drawdown(dates, [100.0, 120.0, 90.0, 135.0])
        self.assertAlmostEqual(dd["max_dd"], 0.25, places=9)
        self.assertEqual(dd["peak_date"], "2022-02-01")
        self.assertEqual(dd["trough_date"], "2022-03-01")
        self.assertTrue(dd["within_tolerance"])
        breach = sb.nav_drawdown(["2022-01-01", "2022-02-01"], [100.0, 50.0])
        self.assertAlmostEqual(breach["max_dd"], 0.50, places=9)
        self.assertFalse(breach["within_tolerance"])
        self.assertEqual(breach["tolerance"], 0.40)

    def test_rolling_1yr_math(self):
        dates = _days("2021-10-27", 400)
        navs = [100.0 + float(i) for i in range(400)]
        rolling = sb.rolling_returns(dates, navs)
        self.assertTrue(rolling["1yr"])
        first = rolling["1yr"][0]
        base = navs[dates.index(first["start"])]
        last = navs[dates.index(first["end"])]
        self.assertAlmostEqual(first["return"], last / base - 1.0, places=9)

    def test_sharpe_sortino_degenerate(self):
        self.assertIsNone(sb.sharpe_ratio([100.0, 100.0, 100.0]))
        self.assertIsNone(sb.sortino_ratio([100.0, 100.0, 100.0]))
        noisy = [100.0 + i + (1.0 if i % 3 else -2.0) for i in range(60)]
        self.assertIsNotNone(sb.sharpe_ratio(noisy))
        self.assertIsNotNone(sb.sortino_ratio(noisy))
        self.assertIsNone(sb.sharpe_ratio([100.0]))

    def test_benchmark_artifact(self):
        days = _days("2021-10-27", 40)
        syms = ["AAA", "BBB"]
        prices = _flat_prices(syms, days, lambda s: 100.0)
        art = sb.run_benchmark(syms, prices, {"AAA": "B", "BBB": "I"}, days,
                               schedule=[{"target_date": days[0],
                                          "amount": 100000.0}],
                               start=days[0], sector_cap=1.0)
        self.assertIsNotNone(art["post_tax_xirr"])
        self.assertIn("max_dd", art)
        self.assertTrue(art["rolling"]["1yr"] == [] or art["rolling"]["1yr"])
        self.assertTrue(art["flags"]["equal_weight_pre_breadth"])


class TestLoadMarket(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))

    def tearDown(self):
        try:
            os.unlink(self._fh.name)
        except OSError:
            pass

    def _company(self, conn, sym, isin, n50=1, sector="Banks"):
        conn.execute(
            "INSERT OR REPLACE INTO master_companies "
            "(isin, nse_symbol, company_name, industry, sector, is_nifty50, is_active)"
            " VALUES (?, ?, ?, 'Ind', ?, ?, 1)",
            (isin, sym, f"{sym} Ltd", sector, n50),
        )

    def _price(self, conn, sym, isin, date, close):
        conn.execute(
            "INSERT OR REPLACE INTO daily_price_delivery "
            "(date, symbol, isin, open, high, low, close, prev_close, change_pct,"
            " total_volume, deliverable_volume, delivery_pct)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, 1000, 500, 50.0)",
            (date, sym, isin, close, close, close, close, close),
        )

    def test_n50_defaults_and_late_joiner(self):
        with self.mgr.session() as conn:
            self._company(conn, "AAA", "INE000A01000", 1, "Banks")
            self._company(conn, "BBB", "INE000B01000", 1, "IT")
            self._company(conn, "ZZZ", "INE000Z01000", 0, "Banks")
            for d in ["2021-10-27", "2021-10-28", "2021-10-29"]:
                self._price(conn, "AAA", "INE000A01000", d, 100.0)
            for d in ["2021-10-29"]:
                self._price(conn, "BBB", "INE000B01000", d, 200.0)
        mkt = sb.load_market(self.mgr, start="2021-10-27", end="2021-10-29")
        self.assertEqual(mkt["symbols"], ["AAA", "BBB"])
        self.assertEqual(mkt["flags"]["late_joiners"], ["BBB"])
        self.assertEqual(mkt["flags"]["n_symbols_day_one"], 1)
        self.assertTrue(mkt["flags"]["equal_weight_pre_breadth"])
        self.assertEqual(mkt["sector_map"]["AAA"], "Banks")
        self.assertEqual(mkt["trading_days"],
                         ["2021-10-27", "2021-10-28", "2021-10-29"])


if __name__ == "__main__":
    unittest.main()
