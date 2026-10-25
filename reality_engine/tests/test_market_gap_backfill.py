"""Tests for the P1 market-gap backfill: ranged deal windows, ISIN labels, insider date cleaning.

Temp DB only (schema from DatabaseManager + load_market_raw's mkt_* DDL), zero network,
no live database.
"""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.deals_client import DealsClient
from reality_engine.scripts.build_bulk_block_deals import collect, load_windows, resolver, window_map, pick
from reality_engine.scripts.clean_insider_dates import reason
from reality_engine.scripts.fetch_market_raw import sessions
from reality_engine.scripts.fetch_nse_api_raw import day_windows, month_windows, year_windows
from reality_engine.scripts.load_market_raw import DDL
from reality_engine.scripts.market_session_coverage import _short, ranges


class TestWindows(unittest.TestCase):
    def test_year_windows_clip_edges(self):
        got = list(year_windows(date(2019, 1, 1), date(2026, 10, 23)))
        self.assertEqual(len(got), 8)
        self.assertEqual(got[0], (date(2019, 1, 1), date(2019, 12, 31)))
        self.assertEqual(got[-1], (date(2026, 1, 1), date(2026, 10, 23)))

    def test_month_windows_cover_every_day_once(self):
        start, end = date(2019, 1, 15), date(2019, 4, 10)
        got = list(month_windows(start, end))
        self.assertEqual(got[0][0], start)
        self.assertEqual(got[-1][1], end)
        self.assertEqual([a.day for a, _ in got], [15, 1, 1, 1])
        for (_, b), (a, _) in zip(got, got[1:]):
            self.assertEqual(b + timedelta(days=1), a)

    def test_day_windows_skip_weekends(self):
        """The reason a year/month window is needed: the daily window drops Saturday sessions."""
        days = [a for a, _ in day_windows(date(2024, 1, 19), date(2024, 1, 22))]
        self.assertEqual([d.isoformat() for d in days], ["2024-01-19", "2024-01-22"])
        # 2024-01-20 was a special Saturday session with its own bulk deals; the year window
        # spans it, so the ranged fetch picks it up while the day fetch never asks for it.
        (lo, hi), = list(year_windows(date(2024, 1, 1), date(2024, 12, 31)))
        self.assertTrue(lo <= date(2024, 1, 20) <= hi)


class TestIsinWindows(unittest.TestCase):
    def test_pick_prefers_the_window_that_contains_the_day(self):
        wins = [("2000-01-01", "2015-12-31", "INEOLD000001"),
                ("2016-01-01", "9999-12-31", "INENEW000002")]
        self.assertEqual(pick(wins, "2010-05-05"), "INEOLD000001")
        self.assertEqual(pick(wins, "2020-05-05"), "INENEW000002")

    def test_pick_gap_and_before_first(self):
        wins = [("2020-01-01", "2020-06-30", "INEA00000001"),
                ("2021-01-01", "2021-06-30", "INEB00000002")]
        self.assertEqual(pick(wins, "2020-09-01"), "INEA00000001")  # gap -> nearest before
        self.assertEqual(pick(wins, "2019-01-01"), "INEA00000001")  # before first -> first
        self.assertIsNone(pick([], "2020-01-01"))

    def test_window_map_drops_non_isins(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE t (k TEXT, i TEXT, a TEXT, b TEXT)")
        con.executemany("INSERT INTO t VALUES (?,?,?,?)", [
            ("X", "INE1234567890", "2019-01-01", "2019-12-31"),  # 13 chars -> not an ISIN
            ("Y", "INE1234567A1", "2019-01-01", "2019-12-31"),
            ("Z", None, "2019-01-01", "2019-12-31"),
        ])
        got = window_map(con, "SELECT k, i, a, b FROM t")
        self.assertEqual(sorted(got), ["Y"])
        con.close()


class TestExplicitSessions(unittest.TestCase):
    """The bhavcopy fetcher's weekday loop skips Saturday/Muhurat sessions; --dates names them."""

    def test_sessions_without_only_is_weekdays(self):
        got = sessions(date(2024, 1, 19), date(2024, 1, 22))
        self.assertEqual([d.isoformat() for d in got], ["2024-01-19", "2024-01-22"])

    def test_sessions_with_only_is_exactly_that_list(self):
        only = [date(2024, 1, 20), date(2024, 3, 2)]
        self.assertEqual(sessions(date(2024, 1, 1), date(2024, 12, 31), only), only)


class TestRanges(unittest.TestCase):
    def test_compresses_consecutive_days(self):
        self.assertEqual(ranges(["2019-01-02", "2019-01-03", "2019-02-01"]),
                         ["2019-01-02..2019-01-03", "2019-02-01"])
        self.assertEqual(ranges([]), [])
        self.assertEqual(_short([f"2024-01-{d:02d}" for d in range(1, 9)], limit=3),
                         "2024-01-01..2024-01-08")


class TestBulkBlockLabels(unittest.TestCase):
    """collect() + the real repository upsert against a temp DB."""

    def _db(self, td):
        mgr = DatabaseManager(db_path=Path(td) / "t.db")
        with mgr.session() as conn:
            conn.executescript(DDL)  # mkt_* landing tables (load_market_raw owns that DDL)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS symbol_isin_history (
                    exchange TEXT, symbol TEXT, isin TEXT, first_date TEXT, last_date TEXT,
                    n_days INTEGER);
                CREATE TABLE IF NOT EXISTS security_master (
                    isin TEXT PRIMARY KEY, issuer TEXT, name TEXT, nse_symbol TEXT, bse_code TEXT,
                    bse_symbol TEXT, bse_status TEXT, segment TEXT, nse_listing_date TEXT,
                    first_trade TEXT, last_trade TEXT, last_seen_nse TEXT, last_seen_bse TEXT,
                    in_master_companies INTEGER, source TEXT);
            """)
            # NSE: symbol ABCL changes ISIN in 2021; XYZL is unknown to every map.
            conn.executemany("INSERT INTO symbol_isin_history VALUES (?,?,?,?,?,?)", [
                ("NSE", "ABCL", "INE000A01001", "2019-01-01", "2020-12-31", 500),
                ("NSE", "ABCL", "INE000A01019", "2021-01-01", "2026-12-31", 1200),
            ])
            # BSE: scrip 500100 trades with ISIN INE000A01019 only from 2021 (delivery/bhavcopy).
            conn.executemany("INSERT INTO mkt_bse_eq_daily (date, sc_code, isin) VALUES (?,?,?)", [
                ("2021-03-01", "500100", "INE000A01019"),
                ("2021-03-02", "500100", "INE000A01019"),
            ])
            conn.executemany("INSERT INTO mkt_nse_deals VALUES (?,?,?,?,?,?,?,?,?,?)", [
                ("2020-03-02", "BULK", "ABCL", "Alpha Ltd", "CLIENT ONE", "BUY", 100, 10.0, None, 1),
                ("2021-03-02", "BLOCK", "ABCL", "Alpha Ltd", "CLIENT ONE", "BUY", 100, 10.0, None, 1),
                ("2021-03-02", "BULK", "XYZL", "Unknown Ltd", "CLIENT TWO", "SELL", 5, 1.0, None, 1),
            ])
            conn.executemany("INSERT INTO mkt_bse_deals VALUES (?,?,?,?,?,?,?,?,?)", [
                # same date/symbol/client/side/qty/price as the NSE block row: must stay a
                # separate row, not collide on the primary key.
                ("2021-03-02", "BLOCK", "500100", "ABCL", "CLIENT ONE", "BUY", 100, 10.0, 1),
                ("2019-06-03", "BULK", "500999", "OLDCO", "CLIENT THREE", "SELL", 7, 2.5, 1),
            ])
        return mgr, Repository(manager=mgr)

    def test_labels_and_isin_history(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, repo = self._db(td)
            with mgr.session() as conn:
                windows, static = load_windows(conn)
                records, per, unmatched = collect(conn, "2019-01-01", "2026-10-23",
                                                  resolver(windows, static))
            self.assertEqual(len(records), 5)
            self.assertEqual(per[("NSE", "BULK")], 2)
            self.assertEqual(per[("BSE", "BLOCK")], 1)
            # the ISIN that was valid on the deal date, not today's
            self.assertEqual({r["isin"] for r in records if r["symbol"] == "ABCL" and r["exchange"] == "NSE"},
                             {"INE000A01001", "INE000A01019"})
            self.assertEqual(unmatched["NSE:no_isin"], 1)      # XYZL
            self.assertEqual(unmatched["BSE:no_isin"], 1)      # 500999, never in the bhavcopy
            self.assertEqual(sum(1 for r in records if r["isin"] is None), 2)
            ids = [r["id"] for r in records]
            self.assertEqual(len(ids), len(set(ids)))          # NSE+BSE twin rows both survive

    def test_upsert_is_idempotent_and_keeps_the_labels(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, repo = self._db(td)
            with mgr.session() as conn:
                windows, static = load_windows(conn)
                resolve = resolver(windows, static)
                records, _, _ = collect(conn, "2019-01-01", "2026-10-23", resolve)
                DealsClient.persist(records, repo=repo)
                again, _, _ = collect(conn, "2019-01-01", "2026-10-23", resolve)
                DealsClient.persist(again, repo=repo)
            with mgr.session() as conn:
                n, with_isin = conn.execute(
                    "SELECT COUNT(*), COUNT(isin) FROM bulk_block_deals").fetchone()
                self.assertEqual(n, 5)
                self.assertEqual(with_isin, 3)
                got = conn.execute("SELECT exchange, COUNT(*) FROM bulk_block_deals "
                                   "GROUP BY exchange ORDER BY exchange").fetchall()
                self.assertEqual([tuple(r) for r in got], [("BSE", 2), ("NSE", 3)])


class TestInsiderDates(unittest.TestCase):
    def test_reason(self):
        self.assertIsNone(reason("2019-01-31", "2019-02-01 10:00"))
        self.assertIsNone(reason(None, None))
        self.assertEqual(reason("-", "2019-02-01 10:00"), "unparseable")
        self.assertEqual(reason("31-01-2019", "2019-02-01 10:00"), "unparseable")
        # published typo dates that land past the disclosure itself
        self.assertEqual(reason("2036-02-03", "2019-02-01 10:00"), "out_of_range")
        self.assertEqual(reason("2028-05-29", "2019-02-01 10:00"), "out_of_range")
        self.assertEqual(reason("1999-12-31", "2019-02-01 10:00"), "out_of_range")
        # one day after dissemination is still accepted (exchange clock skew)
        self.assertIsNone(reason("2019-02-02", "2019-02-01 10:00"))


if __name__ == "__main__":
    unittest.main()
