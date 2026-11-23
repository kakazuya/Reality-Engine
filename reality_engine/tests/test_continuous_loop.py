"""
Continuous loop driver tests (TEMP SQLite + fake agent runner — never omp,
never the live DB, never the network).

Covers the behaviours the 30-minute scheduler depends on:
  * check phase writes a brief + run-log record and never spawns the agent
  * brief surfaces the harness' open work (unscored call dates) and prior handoff
  * iterate phase builds the headless command and records the agent result
  * ``--continue`` is passed only once the loop has its own session
  * an in-flight tick blocks an overlapping tick (rc 2); a stale lock is broken
  * the max-time string resolves to seconds + grace
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.pipeline import continuous_loop as cl

IST = timezone(timedelta(hours=5, minutes=30))


def _make_db():
    fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fh.close()
    mgr = DatabaseManager(Path(fh.name))
    return mgr, fh.name


def _insert_master(conn, symbol, isin):
    conn.execute(
        """
        INSERT OR IGNORE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector, is_nifty200, is_active)
        VALUES (?, ?, ?, 'Industrials', 'Capital Goods', 1, 1)
        """,
        (isin, symbol, f"{symbol} Ltd"),
    )


def _insert_price(conn, symbol, isin, d, close=100.0):
    _insert_master(conn, symbol, isin)
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_price_delivery
            (date, symbol, isin, series, open, high, low, close, prev_close, change_pct,
             total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct,
             delivery_spike_ratio, rsi_14)
        VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, 0.0, 1000, 10.0, 5, 500, 50.0, 1.0, 50.0)
        """,
        (d, symbol, isin, close, close, close, close, close),
    )


def _insert_call(conn, d, symbol, isin, rank=1, target=None):
    _insert_master(conn, symbol, isin)
    conn.execute(
        """
        INSERT OR REPLACE INTO eod_scrip_calls
            (date, symbol, isin, composite_rank, technical_score, fundamental_score,
             alt_sentiment_score, composite_score, current_market_price,
             recommended_entry_range, target_price, stop_loss, conviction_level)
        VALUES (?, ?, ?, ?, 70.0, 60.0, 50.0, 65.0, 100.0, '95-105', ?, ?, 'MODERATE')
        """,
        (d, symbol, isin, rank, target, (target or 0) * 0.9 or None),
    )


class ContinuousLoopTest(unittest.TestCase):
    def setUp(self):
        self.mgr, self.db_file = _make_db()
        self.tmp = tempfile.TemporaryDirectory()
        self.loop_dir = Path(self.tmp.name) / "loop"
        # Friday; the loop clock sits two days later (Mon) to force a gap probe.
        self.asof = "2026-09-11"
        self.now = datetime(2026, 9, 14, 15, 30, tzinfo=IST)
        with self.mgr.session() as conn:
            _insert_price(conn, "HAL", "INE0HAL", self.asof)
            _insert_call(conn, self.asof, "HAL", "INE0HAL", rank=1, target=120.0)
            _insert_call(conn, self.asof, "BEL", "INE0BEL", rank=2)

    def tearDown(self):
        self.tmp.cleanup()
        for path in (self.db_file, self.db_file + "-wal", self.db_file + "-shm"):
            try:
                os.unlink(path)
            except OSError:
                pass

    # -- 1. check phase -------------------------------------------------
    def test_check_phase_writes_brief_and_never_spawns_agent(self):
        def exploding_runner(cmd, timeout_seconds, log_path=None):
            raise AssertionError("check phase must not spawn the agent")

        result = cl.run_once(
            phase="check",
            loop_dir=self.loop_dir,
            db_manager=self.mgr,
            now=self.now,
            agent_runner=exploding_runner,
        )
        self.assertEqual(result["phase"], "check")
        self.assertEqual(result["health"]["pending_validation_dates"], 1)
        self.assertGreaterEqual(result["health"]["missing_trading_days"], 1)

        brief = Path(result["brief_file"])
        self.assertTrue(brief.exists())
        text = brief.read_text(encoding="utf-8")
        self.assertIn(self.asof, text)
        self.assertIn("open harness queue", text)
        self.assertIn("2 calls, 1 with target/SL", text)
        self.assertIn("missing trading day", text)
        self.assertIn("Previous handoff", text)

        runs = cl.recent_runs(self.loop_dir)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["rc"], 0)
        self.assertEqual(runs[0]["phase"], "check")
        self.assertFalse(self.loop_dir.joinpath(cl.LOCK_NAME).exists(), "lock must be released")

    # -- 2. iterate phase -----------------------------------------------
    def test_iterate_phase_builds_command_and_logs_result(self):
        seen = {}

        def fake_runner(cmd, timeout_seconds, log_path=None):
            seen["cmd"] = list(cmd)
            seen["timeout"] = timeout_seconds
            return {
                "rc": 0,
                "timed_out": False,
                "duration_seconds": 1.5,
                "stdout_tail": "done",
                "stderr_tail": "",
                "log_file": None,
            }

        result = cl.run_once(
            phase="iterate",
            loop_dir=self.loop_dir,
            db_manager=self.mgr,
            now=self.now,
            agent_runner=fake_runner,
        )
        cmd = seen["cmd"]
        self.assertIn("--auto-approve", cmd)
        self.assertIn("--max-time", cmd)
        self.assertNotIn("--continue", cmd, "first run has no loop session to continue")
        attached = [a for a in cmd if a.startswith("@")]
        self.assertEqual(len(attached), 2, "standing prompt + this run's brief")
        self.assertTrue(attached[0].endswith("continuous_loop.md"))
        self.assertIn("run #1", cmd[-1])

        self.assertEqual(result["agent"]["rc"], 0)
        runs = cl.recent_runs(self.loop_dir)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["rc"], 0)
        self.assertEqual(runs[0]["run_index"], 1)

        # Next tick resumes the loop's own session and bumps the run index.
        sessions = self.loop_dir / cl.SESSIONS_SUBDIR
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / "session.json").write_text("{}", encoding="utf-8")
        next_brief = self.loop_dir / "next.md"
        next_brief.write_text("x", encoding="utf-8")
        resumed = cl.build_agent_command(next_brief, loop_dir=self.loop_dir)
        self.assertIn("--continue", resumed)
        self.assertEqual(cl.collect_health(db_manager=self.mgr, loop_dir=self.loop_dir, now=self.now)["loop"]["run_index"], 2)

    # -- 3. locking -----------------------------------------------------
    def test_lock_blocks_overlapping_tick(self):
        self.loop_dir.mkdir(parents=True, exist_ok=True)
        fd = cl.acquire_lock(self.loop_dir / cl.LOCK_NAME)
        try:
            result = cl.run_once(
                phase="check", loop_dir=self.loop_dir, db_manager=self.mgr, now=self.now
            )
            self.assertTrue(result["skipped"])
            self.assertEqual(cl.recent_runs(self.loop_dir)[-1]["rc"], 2)
        finally:
            cl.release_lock(fd, self.loop_dir / cl.LOCK_NAME)
        self.assertFalse(self.loop_dir.joinpath(cl.LOCK_NAME).exists())

    def test_stale_lock_is_broken(self):
        self.loop_dir.mkdir(parents=True, exist_ok=True)
        lock = self.loop_dir / cl.LOCK_NAME
        lock.write_text("dead run", encoding="utf-8")
        old = time.time() - (cl.STALE_LOCK_SECONDS + 60)
        os.utime(lock, (old, old))
        fd = cl.acquire_lock(lock)
        try:
            self.assertTrue(lock.exists())
        finally:
            cl.release_lock(fd, lock)

    # -- 4. small pure helpers -----------------------------------------
    def test_previous_state_is_carried_into_the_brief(self):
        self.loop_dir.mkdir(parents=True, exist_ok=True)
        (self.loop_dir / cl.STATE_NAME).write_text("## Next\nship the harness wiring\n", encoding="utf-8")
        health = cl.collect_health(db_manager=self.mgr, loop_dir=self.loop_dir, now=self.now)
        brief = cl.render_brief(health, cl.read_state(self.loop_dir))
        self.assertIn("ship the harness wiring", brief)
        self.assertIn("run index: **1**", brief)

    def test_max_time_resolution(self):
        self.assertEqual(cl.resolve_timeout("20m"), 20 * 60 + cl.AGENT_TIMEOUT_GRACE_SECONDS)
        self.assertEqual(cl.resolve_timeout("90s"), 90 + cl.AGENT_TIMEOUT_GRACE_SECONDS)
        self.assertEqual(cl.resolve_timeout("1200"), 1200 + cl.AGENT_TIMEOUT_GRACE_SECONDS)
        self.assertEqual(cl.resolve_timeout("garbage"), 20 * 60 + cl.AGENT_TIMEOUT_GRACE_SECONDS)


if __name__ == "__main__":
    unittest.main()
