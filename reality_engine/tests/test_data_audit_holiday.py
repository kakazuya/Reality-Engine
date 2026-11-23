"""
Holiday-aware audit_price staleness + 2022-08-08 Muharram Observed fix.
Covers:
  - 2022-08-08 treated as holiday (not unexplained gap)
  - weekend staleness not degraded (Fri 2026-08-28 -> Sun 2026-08-30)
  - true gaps still flagged
"""
import datetime as dt
import sqlite3
import unittest

from reality_engine.pipeline.data_audit import NSE_WEEKDAY_HOLIDAYS, STALE_AFTER_DAYS, audit_price


def _make_price_conn(dates):
    """Create in-memory DB with daily_price_delivery containing given date strings (YYYY-MM-DD)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE daily_price_delivery (
            date TEXT,
            symbol TEXT,
            sma_20 REAL,
            rsi_14 REAL,
            delivery_spike_ratio REAL,
            sma_200 REAL
        )
        """
    )
    for d in dates:
        # insert one symbol per date; per-session row counts still >0
        conn.execute(
            "INSERT INTO daily_price_delivery (date, symbol, sma_20, rsi_14, delivery_spike_ratio, sma_200) VALUES (?,?,?,?,?,?)",
            (d, "TEST", 100.0, 50.0, 1.0, 100.0),
        )
    conn.commit()
    return conn


class TestDataAuditHoliday(unittest.TestCase):

    def test_nse_holiday_set_contains_observed_muharram(self):
        self.assertIn("2022-08-08", NSE_WEEKDAY_HOLIDAYS)
        self.assertIn("2022-08-09", NSE_WEEKDAY_HOLIDAYS)

    def test_2022_08_08_treated_as_holiday_not_unexplained(self):
        # Range Thu 2022-08-04 to Fri 2022-08-12, missing 08 Mon and 09 Tue (both holidays now)
        # have: Thu 04, Fri 05, Wed 10, Thu 11, Fri 12
        have_dates = ["2022-08-04", "2022-08-05", "2022-08-10", "2022-08-11", "2022-08-12"]
        conn = _make_price_conn(have_dates)
        today = dt.date(2022, 8, 13)  # Saturday after
        out = audit_price(conn, today)
        conn.close()
        # Both 2022-08-08 and 09 should be in market_holidays_excluded, not unexplained
        self.assertIn("2022-08-08", out["market_holidays_excluded"])
        self.assertIn("2022-08-09", out["market_holidays_excluded"])
        self.assertNotIn("2022-08-08", out["unexplained_gaps"])
        self.assertEqual(out["unexplained_gap_count"], 0)
        # Ensure 2022-08-08 not counted as unexplained
        self.assertEqual(out["unexplained_gaps"], [])

    def test_weekend_staleness_not_degraded(self):
        # Latest Fri 2026-08-28, today Sun 2026-08-30 => 2 calendar days, 0 trading days
        have_dates = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
        conn = _make_price_conn(have_dates)
        today = dt.date(2026, 8, 30)  # Sunday
        out = audit_price(conn, today)
        conn.close()
        self.assertEqual(out["latest_session"], "2026-08-28")
        self.assertEqual(out["staleness_days"], 2)
        self.assertEqual(out["staleness_trading_days"], 0)
        self.assertTrue(out["is_weekend_today"])
        self.assertTrue(out["is_weekend_stale_exempt"])
        # Should not be CRITICAL; with no gaps and fresh via trading, status OK
        self.assertNotEqual(out["status"], "CRITICAL")
        self.assertEqual(out["status"], "OK")
        # Also ensure DEGRADED not returned due to weekend alone
        # fresh should be True via trading_trading <=2

    def test_weekend_staleness_friday_to_saturday(self):
        have_dates = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
        conn = _make_price_conn(have_dates)
        today = dt.date(2026, 8, 29)  # Saturday
        out = audit_price(conn, today)
        conn.close()
        self.assertEqual(out["staleness_days"], 1)
        self.assertEqual(out["staleness_trading_days"], 0)
        self.assertTrue(out["is_weekend_today"])
        self.assertTrue(out["is_weekend_stale_exempt"])
        self.assertEqual(out["status"], "OK")

    def test_true_gap_still_flagged(self):
        # Omit a non-holiday weekday (Wed 2026-08-26) inside range; should be unexplained
        have_dates = ["2026-08-24", "2026-08-25", "2026-08-27", "2026-08-28"]
        conn = _make_price_conn(have_dates)
        today = dt.date(2026, 8, 30)
        out = audit_price(conn, today)
        conn.close()
        self.assertIn("2026-08-26", out["unexplained_gaps"])
        self.assertEqual(out["unexplained_gap_count"], 1)
        self.assertNotIn("2026-08-26", out["market_holidays_excluded"])

    def test_true_gap_not_hidden_by_adjacent_holiday(self):
        # Range includes observed holiday 2022-08-08 but missing 2022-08-12 Fri (not holiday) should still flag
        have_dates = ["2022-08-04", "2022-08-05", "2022-08-10", "2022-08-11"]
        # dmin 2022-08-04 to dmax 2022-08-11, missing 08,09 (holidays) => unexplained 0
        # Now extend dmax to 12 but omit 12
        have_dates2 = ["2022-08-04", "2022-08-05", "2022-08-10", "2022-08-11", "2022-08-15"]
        # Actually 12 Fri missing, but 2022-08-12 is not holiday, 13-14 weekend, 15 Mon present => missing 12 should be unexplained
        conn = _make_price_conn(have_dates2)
        today = dt.date(2022, 8, 16)
        out = audit_price(conn, today)
        conn.close()
        self.assertIn("2022-08-12", out["unexplained_gaps"])
        self.assertNotIn("2022-08-08", out["unexplained_gaps"])

    def test_stale_beyond_weekend_still_critical(self):
        # Latest 2026-08-20 Thu, today Sun 2026-08-30 => calendar 10, trading ~7 (>2) => not fresh => CRITICAL or DEGRADED
        # Need no gaps, total>0, but staleness >7 calendar and >2 trading => fresh False
        have_dates = ["2026-08-20"]
        conn = _make_price_conn(have_dates)
        today = dt.date(2026, 8, 30)
        out = audit_price(conn, today)
        conn.close()
        self.assertEqual(out["staleness_days"], 10)
        # trading between 2026-08-21 and 30 inclusive excluding weekend/holidays: 21 Fri, 24-28 Mon-Fri, =6? Let's compute
        # 21 Fri, 22 Sat skip,23 Sun skip,24 Mon,25 Tue,26 Wed,27 Thu,28 Fri,29 Sat skip,30 Sun skip => 6 trading days
        self.assertGreater(out["staleness_trading_days"], 2)
        # fresh false => status CRITICAL (since total>0 but not fresh)
        self.assertEqual(out["status"], "CRITICAL")

    def test_holiday_does_not_count_as_stale_trading_day(self):
        # Thu 2025-08-14 latest, holiday 2025-08-15 Independence Day (Fri), today Mon 2025-08-18 => trading should be 1 (Mon only)
        have_dates = ["2025-08-14"]
        conn = _make_price_conn(have_dates)
        today = dt.date(2025, 8, 18)  # Monday
        out = audit_price(conn, today)
        conn.close()
        self.assertEqual(out["staleness_days"], 4)  # 14->18 =4
        self.assertEqual(out["staleness_trading_days"], 1)  # Fri 15 holiday skip, Sat Sun skip, Mon 18 =1
        self.assertFalse(out["is_weekend_today"])
        # 1 trading day stale => fresh via trading <=2 => OK if no gaps
        self.assertEqual(out["status"], "OK")

    def test_output_fields_exist(self):
        conn = _make_price_conn(["2026-08-28"])
        today = dt.date(2026, 8, 30)
        out = audit_price(conn, today)
        conn.close()
        for field in ("staleness_days", "staleness_trading_days", "is_weekend_today", "is_weekend_stale_exempt", "unexplained_gaps", "market_holidays_excluded"):
            self.assertIn(field, out)


if __name__ == "__main__":
    unittest.main()
