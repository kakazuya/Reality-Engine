"""
Deterministic tests for the missed-days catcher (catchup_scheduler).

All tests use throwaway temp SQLite databases and injected dependency stubs;
none touches the project's real DB or the network. Verifies the task acceptance:

  * get_missing_trading_days detects the gap when the computer was off and
    returns the correct list of missing trading days.
  * run_catchup(dry_run=True) reports the missing count WITHOUT mutating raw
    price data (no backfill, no macro distillation).
  * IST timezone handling (now_ist carries the +05:30 offset).
  * The 16:00 pre-close guard skips TODAY's EOD correction when today's
    bhavcopy is not yet available.

Pure helper functions are tested directly so the behaviour is unambiguous.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.pipeline import catchup_scheduler as cs


def _make_db() -> "tuple[DatabaseManager, str]":
    fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fh.close()
    mgr = DatabaseManager(Path(fh.name))  # runs schema.sql
    return mgr, fh.name


def _insert_company(conn, symbol, isin, nifty200=1):
    conn.execute(
        """
        INSERT OR IGNORE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector, is_nifty200, is_active)
        VALUES (?, ?, ?, 'Industrials', 'Capital Goods', ?, 1)
        """,
        (isin, symbol, f"{symbol} Ltd", nifty200),
    )


def _insert_price(conn, symbol, isin, d: str, prev_close, close, turnover=200.0):
    _insert_company(conn, symbol, isin)
    change = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_price_delivery
            (date, symbol, isin, series, open, high, low, close, prev_close, change_pct,
             total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct,
             delivery_spike_ratio, rsi_14)
        VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, ?, 100000, ?, 100, ?, 50.0, 1.0, 50.0)
        """,
        (d, symbol, isin, close * 0.99, close * 1.01, close, close, prev_close, change,
         float(turnover), int(close * 500)),
    )


def _insert_raw_doc(conn, source_type, published_date, title="doc"):
    conn.execute(
        "INSERT INTO raw_documents (title, source_type, published_date) VALUES (?, ?, ?)",
        (title, source_type, published_date),
    )


class FakeBackfill:
    def __init__(self):
        self.calls = []

    def backfill_bhavcopy_history(self, days_count=25, end_date=None):
        self.calls.append({"days_count": days_count, "end_date": end_date})
        return days_count  # pretend all requested sessions ingested


class FakeDistillationEngine:
    def __init__(self, event_ids=None):
        self.event_ids = event_ids or []
        self.calls = []

    def distill_all_macro_documents(self, source_type_prefix=None, limit=None):
        self.calls.append(1)
        return {
            "distilled": len(self.event_ids),
            "details": [
                {"doc_id": i + 1, "event_id": eid, "events_created": 1}
                for i, eid in enumerate(self.event_ids)
            ],
        }


class FakePruning:
    def __init__(self):
        self.calls = []

    def prune_decayed_signals(self, manager=None, dry_run=False):
        self.calls.append({"dry_run": dry_run})
        return {"vectors_purged": 0, "ripples_pruned": 0, "macros_archived": 0, "dry_run": dry_run}


class FakeDistillationPruner:
    def __init__(self):
        self.calls = []

    def run_monthly_distillation(self, symbol, manager=None, youtube_n=20, concall_n=4,
                                 chunk_ids_override=None, llm_client=None):
        self.calls.append(symbol)
        return {"symbol": symbol, "chunks_distilled": 0, "vectors_purged": 0}


class FakeEODCorrector:
    def __init__(self):
        self.correct_eod_calls = []
        self.correct_event_calls = []

    def correct_eod(self, universe="nifty200", target_date=None, dry_run=False,
                    update_substrate=False, symbols=None):
        self.correct_eod_calls.append({"target_date": target_date, "dry_run": dry_run})
        return {"symbols_corrected": 1, "noise_floors_updated": 1, "lens_rank_changes": 1}

    def correct_event(self, event_id, symbols=None, dry_run=False):
        self.correct_event_calls.append(event_id)
        return {"event_id": event_id, "lens_rank_changes": 0}


class FakeBackfillPopulate:
    """Simulates backfill that loads every missing day EXCEPT today (bhavcopy for
    today is not yet published at the 16:00 pre-close slot)."""

    def __init__(self, mgr, today):
        self.mgr = mgr
        self.today = today
        self.calls = []

    def backfill_bhavcopy_history(self, days_count=25, end_date=None):
        missing = cs.get_missing_trading_days(self.mgr, self.today)
        self.calls.append({"days_count": days_count, "missing": missing})
        with self.mgr.session() as conn:
            for md in missing:
                if md == self.today.isoformat():
                    continue
                _insert_price(conn, "HAL", "INE1", md, 100.0, 104.0)
        return len(missing)


class TestMissingTradingDays(unittest.TestCase):
    def setUp(self):
        self.mgr, self.path = _make_db()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _seed_through(self, last: str):
        """Insert a contiguous weekday run ending at ``last`` (YYYY-MM-DD)."""
        end = date.fromisoformat(last)
        cur = end - timedelta(days=20)
        with self.mgr.session() as conn:
            # walk forward, inserting only weekdays, up to `end`
            d = cur
            while d <= end:
                if d.weekday() < 5:
                    _insert_price(conn, "HAL", "INE1", d.isoformat(), 100.0, 102.0)
                d += timedelta(days=1)

    def test_missing_detected_after_gap(self):
        # Computer last synced 2026-08-20; today is 2026-08-27.
        self._seed_through("2026-08-20")
        today = date(2026, 8, 27)
        missing = cs.get_missing_trading_days(self.mgr, today)

        # Recompute the expected weekdays in (08-21 .. 08-27) using the same rule.
        expected = []
        d = date(2026, 8, 21)
        while d <= today:
            if cs.is_trading_day(d, set()):
                expected.append(d.isoformat())
            d += timedelta(days=1)

        self.assertEqual(set(missing), set(expected))
        # Specifically 5 trading days: Fri 21, Mon 24, Tue 25, Wed 26, Thu 27.
        self.assertEqual(len(missing), 5)
        self.assertIn("2026-08-27", missing)

    def test_no_missing_when_up_to_date(self):
        self._seed_through("2026-08-27")
        missing = cs.get_missing_trading_days(self.mgr, date(2026, 8, 27))
        self.assertEqual(missing, [])

    def test_empty_db_returns_empty(self):
        missing = cs.get_missing_trading_days(self.mgr, date(2026, 8, 27))
        self.assertEqual(missing, [])

    def test_holiday_excluded(self):
        # Seed through 2026-08-20, mark 2026-08-21 (Fri) as a holiday.
        self._seed_through("2026-08-20")
        holidays = {"2026-08-21"}
        missing = cs.get_missing_trading_days(self.mgr, date(2026, 8, 27), holidays=holidays)
        self.assertNotIn("2026-08-21", missing)
        self.assertEqual(len(missing), 4)


class TestMissingMacroSources(unittest.TestCase):
    def setUp(self):
        self.mgr, self.path = _make_db()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_all_missing_on_fresh_db(self):
        missing = cs.get_missing_macro_sources(self.mgr, datetime(2026, 8, 27, tzinfo=cs.IST))
        self.assertEqual(set(missing), set(cs.MACRO_SOURCE_PREFIXES))

    def test_recent_ingest_not_missing(self):
        today = "2026-08-27"
        with self.mgr.session() as conn:
            _insert_raw_doc(conn, "Union_Budget", today)
            _insert_raw_doc(conn, "PIB_Circular", "2026-08-17")  # 10 days old -> missing
        missing = cs.get_missing_macro_sources(self.mgr, datetime(2026, 8, 27, tzinfo=cs.IST))
        self.assertNotIn("union_budget", missing)
        self.assertIn("pib", missing)
        self.assertIn("state_budget", missing)
        self.assertIn("economic_survey", missing)
        self.assertIn("rbi", missing)


class TestRunCatchupDryRun(unittest.TestCase):
    def setUp(self):
        self.mgr, self.path = _make_db()
        # Seed through 2026-08-20 so 5 trading days are missing up to 2026-08-27.
        end = date(2026, 8, 20)
        cur = end - timedelta(days=20)
        with self.mgr.session() as conn:
            d = cur
            while d <= end:
                if d.weekday() < 5:
                    _insert_price(conn, "HAL", "INE1", d.isoformat(), 100.0, 102.0)
                d += timedelta(days=1)
        self.fake_bm = FakeBackfill()
        self.fake_de = FakeDistillationEngine()
        self.fake_pe = FakePruning()
        self.fake_dp = FakeDistillationPruner()
        self.fake_ec = FakeEODCorrector()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_dry_run_reports_count_and_does_not_mutate(self):
        summary = cs.run_catchup(
            dry_run=True,
            mode="post-close",
            today=date(2026, 8, 27),
            db_manager=self.mgr,
            backfill_manager=self.fake_bm,
            distillation_engine=self.fake_de,
            pruning_engine=self.fake_pe,
            distillation_pruner=self.fake_dp,
            eod_corrector=self.fake_ec,
        )
        self.assertEqual(summary["missing_trading_day_count"], 5)
        # No raw backfill / macro distillation in dry-run.
        self.assertEqual(self.fake_bm.calls, [])
        self.assertEqual(self.fake_de.calls, [])
        # Pruning ran in dry-run mode.
        self.assertEqual(len(self.fake_pe.calls), 1)
        self.assertTrue(self.fake_pe.calls[0]["dry_run"])
        # EOD correction not invoked (missing days have no price rows in dry-run).
        self.assertEqual(self.fake_ec.correct_eod_calls, [])
        # Aux feeds skipped in dry-run.
        self.assertTrue(summary["actions"]["aux_feeds"]["skipped"])


class TestISTTimezone(unittest.TestCase):
    def test_now_ist_offset(self):
        n = cs.now_ist()
        self.assertIsNotNone(n.tzinfo)
        self.assertEqual(n.utcoffset(), timedelta(hours=5, minutes=30))

    def test_resolve_mode_pre_close_window(self):
        # 16:00 IST -> pre-close
        self.assertEqual(cs.resolve_mode("auto", datetime(2026, 8, 27, 16, 0, tzinfo=cs.IST)),
                         "pre-close")
        # 23:00 IST -> post-close
        self.assertEqual(cs.resolve_mode("auto", datetime(2026, 8, 27, 23, 0, tzinfo=cs.IST)),
                         "post-close")
        # explicit overrides win
        self.assertEqual(cs.resolve_mode("post-close"), "post-close")


class TestPreCloseGuard(unittest.TestCase):
    def test_guard_pure_function(self):
        # Pre-close + today + no data -> skip.
        self.assertTrue(cs.should_skip_eod_for_date(
            "2026-08-27", "pre-close", "2026-08-27", has_data=False))
        # Pre-close + today + data ready -> do NOT skip.
        self.assertFalse(cs.should_skip_eod_for_date(
            "2026-08-27", "pre-close", "2026-08-27", has_data=True))
        # Post-close never skips.
        self.assertFalse(cs.should_skip_eod_for_date(
            "2026-08-27", "post-close", "2026-08-27", has_data=False))
        # Pre-close but not today -> never skip.
        self.assertFalse(cs.should_skip_eod_for_date(
            "2026-08-26", "pre-close", "2026-08-27", has_data=False))

    def test_pre_close_skips_today_but_corrects_ready_days(self):
        mgr, path = _make_db()
        try:
            # Max date 2026-08-20; insert data for 08-21 only (today 08-27 has none).
            end = date(2026, 8, 20)
            cur = end - timedelta(days=20)
            with mgr.session() as conn:
                d = cur
                while d <= end:
                    if d.weekday() < 5:
                        _insert_price(conn, "HAL", "INE1", d.isoformat(), 100.0, 102.0)
                    d += timedelta(days=1)

            fake_bm = FakeBackfillPopulate(mgr, date(2026, 8, 27))
            fake_de = FakeDistillationEngine()
            fake_pe = FakePruning()
            fake_dp = FakeDistillationPruner()
            fake_ec = FakeEODCorrector()

            summary = cs.run_catchup(
                dry_run=False,
                mode="pre-close",
                today=date(2026, 8, 27),
                db_manager=mgr,
                backfill_manager=fake_bm,
                distillation_engine=fake_de,
                pruning_engine=fake_pe,
                distillation_pruner=fake_dp,
                eod_corrector=fake_ec,
            )
            targets = [c["target_date"] for c in fake_ec.correct_eod_calls]
            self.assertIn("2026-08-24", targets)        # ready missing day corrected
            self.assertNotIn("2026-08-27", targets)     # today skipped (no bhavcopy)
            # Verify the skip was recorded in the summary.
            today_entry = next(
                (e for e in summary["actions"]["eod_corrections"] if e["date"] == "2026-08-27"),
                None,
            )
            self.assertIsNotNone(today_entry)
            self.assertTrue(today_entry.get("skipped"))
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
