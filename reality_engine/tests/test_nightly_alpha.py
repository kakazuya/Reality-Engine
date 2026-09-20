"""
Wave A nightly chain tests (TEMP SQLite DBs only — never the live DB).

Covers the task acceptance:
  * dry-run plans correctly with zero DB/network writes
  * exclusive lock blocks a second instance (incl. 6h stale break)
  * checkpoint-fail aborts predict stages (mocked)
  * snapshot naming matches prior manual runs

All dependencies are injected fakes; the temp DatabaseManager only
exercises local schema reads/writes inside a throwaway file.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.pipeline import nightly_alpha as na


def _make_db():
    fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fh.close()
    mgr = DatabaseManager(Path(fh.name))
    return mgr, fh.name


def _insert_price(conn, symbol, isin, d, prev_close=100.0, close=102.0):
    conn.execute(
        """
        INSERT OR IGNORE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector, is_nifty200, is_active)
        VALUES (?, ?, ?, 'Industrials', 'Capital Goods', 1, 1)
        """,
        (isin, symbol, f"{symbol} Ltd"),
    )
    change = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_price_delivery
            (date, symbol, isin, series, open, high, low, close, prev_close, change_pct,
             total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct,
             delivery_spike_ratio, rsi_14)
        VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, ?, 100000, 200.0, 100, 50000, 50.0, 1.0, 50.0)
        """,
        (d, symbol, isin, close * 0.99, close * 1.01, close, close, prev_close, change),
    )


# ---------------------------------------------------------------------------
# Fakes (record calls; never touch network or the live DB)
# ---------------------------------------------------------------------------
class FakeMaster:
    def __init__(self):
        self.calls = 0

    def sync_all(self):
        self.calls += 1
        return {"total_upserted": 1}


class FakeBackfill:
    def __init__(self):
        self.calls = []

    def backfill_bhavcopy_history(self, days_count=25, end_date=None):
        self.calls.append({"days_count": days_count, "end_date": end_date})
        return days_count


class FakeRepo:
    def get_nifty200_companies(self):
        return [{"nse_symbol": "HAL", "isin": "INE1", "bse_code": None}]

    def get_all_companies(self, active_only=True):
        return [{"nse_symbol": "HAL", "isin": "INE1", "bse_code": None}]


class FakePhase1Pass:
    def __init__(self):
        self.repo = FakeRepo()
        self.calls = 0

    def validate_top_200_checkpoint(self, target_date=None):
        self.calls += 1
        return {
            "target_universe_count": 200,
            "target_date": target_date or "2026-08-27",
            "technical_data_available_count": 196,
            "technical_data_complete_count": 195,
            "fundamental_data_available_count": 190,
            "fundamental_data_complete_count": 185,
            "solvency_data_available_count": 180,
            "checkpoint_passed": True,
        }


class FakePhase1Fail(FakePhase1Pass):
    def validate_top_200_checkpoint(self, target_date=None):
        self.calls += 1
        return {
            "target_universe_count": 200,
            "target_date": target_date or "2026-08-27",
            "technical_data_available_count": 10,
            "technical_data_complete_count": 5,
            "fundamental_data_available_count": 4,
            "fundamental_data_complete_count": 2,
            "solvency_data_available_count": 1,
            "checkpoint_passed": False,
        }


class FakeFundamentals:
    def __init__(self):
        self.calls = []

    def fetch_all_fundamentals(self, companies, max_workers=4, rate_limit_sec=0.5,
                               max_companies=None, persist=True):
        self.calls.append({"n": len(companies), "persist": persist})
        return {
            "attempted": len(companies),
            "succeeded": len(companies),
            "failed": 0,
            "quarterly_rows": 0,
            "annual_rows": 0,
            "forensic_rows": 0,
            "document_rows": 0,
            "failed_symbols": [],
        }


class FakeScreener:
    def __init__(self, n=20):
        self.n = n
        self.legacy_calls = []
        self.ensemble_calls = []

    def _frame(self, prefix):
        return [
            {"symbol": f"{prefix}{i:02d}", "composite_rank": i + 1,
             "composite_score": 90.0 - i, "ensemble_composite": 80.0 - i}
            for i in range(self.n)
        ]

    def run_screener(self, target_date=None, top_n=20, universe="all"):
        self.legacy_calls.append({"target_date": target_date, "top_n": top_n, "universe": universe})
        return self._frame("LEG")[:top_n]

    def ensemble_screen(self, target_date=None, top_n=20, universe="all"):
        self.ensemble_calls.append({"target_date": target_date, "top_n": top_n, "universe": universe})
        return self._frame("ENS")[:top_n]


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    def synthesize_daily_alpha_report(self, target_date=None, universe="nifty200",
                                      top_n=5, screener_pool_size=20, use_ensemble=False, **kw):
        self.calls.append({"use_ensemble": use_ensemble})
        return {"dummy": True, "mode": "ensemble" if use_ensemble else "legacy"}


class FakeWriter:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.calls = []

    def export_daily_alpha_report(self, report):
        self.calls.append(report)
        d = self.base / "reports" / "2026-08-27"
        d.mkdir(parents=True, exist_ok=True)
        out = {}
        for key, name in (("json", "daily_alpha.json"), ("markdown", "daily_alpha.md"),
                          ("html", "daily_alpha.html")):
            p = d / name
            p.write_text(f"fake {key} {len(self.calls)}", encoding="utf-8")
            out[key] = p
        return out


class FakeEOD:
    def __init__(self):
        self.calls = []

    def correct_eod(self, universe="nifty200", target_date=None, dry_run=False, **kw):
        self.calls.append({"universe": universe, "target_date": target_date, "dry_run": dry_run})
        return {"symbols_corrected": 1, "noise_floors_updated": 1, "lens_rank_changes": 0}


# ---------------------------------------------------------------------------
# 1. Dry-run plans correctly, zero writes
# ---------------------------------------------------------------------------
class TestDryRunPlan(unittest.TestCase):
    def setUp(self):
        self.mgr, self.db_path = _make_db()
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmp.name)
        # Seed a couple of weekdays so the missing-day probe has something to read.
        end = date(2026, 8, 20)
        cur = end - timedelta(days=10)
        with self.mgr.session() as conn:
            d = cur
            while d <= end:
                if d.weekday() < 5:
                    _insert_price(conn, "HAL", "INE1", d.isoformat())
                d += timedelta(days=1)
        self.fakes = {
            "master_sync_mgr": FakeMaster(),
            "backfill_mgr": FakeBackfill(),
            "phase1_runner_obj": FakePhase1Pass(),
            "fundamentals_client_obj": FakeFundamentals(),
            "screener": FakeScreener(),
            "orchestrator": FakeOrchestrator(),
            "report_writer": FakeWriter(self.log_dir),
            "eod_corrector_obj": FakeEOD(),
        }

    def tearDown(self):
        self.tmp.cleanup()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_dry_run_resolves_plan_and_writes_nothing(self):
        lock_p = self.log_dir / "nightly.lock"
        summary = na.run_nightly(
            dry_run=True,
            part="all",
            date_str="2026-08-27",
            db_manager=self.mgr,
            log_dir=self.log_dir,
            lock_path=lock_p,
            **self.fakes,
        )
        self.assertTrue(summary["dry_run"])
        self.assertEqual(summary["date_ist"], "2026-08-27")
        self.assertEqual(summary["planned_stages"], na.plan_stages("all"))
        self.assertIn("backfill_days_planned", summary)
        self.assertEqual(summary["exit_code"], 0)
        # Zero writes: no stage fakes invoked.
        self.assertEqual(self.fakes["master_sync_mgr"].calls, 0)
        self.assertEqual(self.fakes["backfill_mgr"].calls, [])
        self.assertEqual(self.fakes["fundamentals_client_obj"].calls, [])
        self.assertEqual(self.fakes["screener"].legacy_calls, [])
        self.assertEqual(self.fakes["screener"].ensemble_calls, [])
        self.assertEqual(self.fakes["orchestrator"].calls, [])
        self.assertEqual(self.fakes["eod_corrector_obj"].calls, [])
        # No lock file, no health JSON on dry-run.
        self.assertFalse(lock_p.exists())
        self.assertEqual(list(self.log_dir.glob("nightly_*.json")), [])

    def test_dry_run_part_split(self):
        self.assertEqual(na.plan_stages("fetch_predict"), list(na.FETCH_STAGES))
        self.assertEqual(na.plan_stages("correct_validate"), list(na.CORRECT_STAGES))
        self.assertEqual(na.plan_stages("all"), list(na.FETCH_STAGES) + list(na.CORRECT_STAGES))
        # resolve_backfill_days: missing + 5 buffer, cap 60.
        self.assertEqual(na.resolve_backfill_days(0), 0)
        self.assertEqual(na.resolve_backfill_days(3), 8)
        self.assertEqual(na.resolve_backfill_days(100), 60)


# ---------------------------------------------------------------------------
# 2. Lock blocks a second instance (incl. stale break)
# ---------------------------------------------------------------------------
class TestNightlyLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = Path(self.tmp.name) / "nightly.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_acquire_blocked(self):
        fd1 = na.acquire_lock(self.lock)
        try:
            self.assertTrue(self.lock.exists())
            with self.assertRaises(RuntimeError):
                na.acquire_lock(self.lock)
        finally:
            na.release_lock(fd1, self.lock)
        self.assertFalse(self.lock.exists())
        # Re-acquire after release works.
        fd2 = na.acquire_lock(self.lock)
        na.release_lock(fd2, self.lock)

    def test_stale_lock_broken_after_6h(self):
        # Simulate a crashed run: lock file left behind with old mtime.
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text("stale pid\n", encoding="utf-8")
        old = time.time() - (7 * 3600)
        os.utime(str(self.lock), (old, old))
        fd3 = na.acquire_lock(self.lock)  # must break stale, not raise
        na.release_lock(fd3, self.lock)
        self.assertFalse(self.lock.exists())

    def test_run_nightly_respects_held_lock(self):
        mgr, db_path = _make_db()
        try:
            fd = na.acquire_lock(self.lock)
            try:
                summary = na.run_nightly(
                    dry_run=False,
                    part="fetch_predict",
                    date_str="2026-08-27",
                    db_manager=mgr,
                    master_sync_mgr=FakeMaster(),
                    log_dir=Path(self.tmp.name),
                    lock_path=self.lock,
                )
                self.assertEqual(summary["exit_code"], 2)
                self.assertIn("holds the lock", summary.get("error", ""))
            finally:
                na.release_lock(fd, self.lock)
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 3. Checkpoint-fail aborts predict stages
# ---------------------------------------------------------------------------
class TestCheckpointGate(unittest.TestCase):
    def setUp(self):
        self.mgr, self.db_path = _make_db()
        with self.mgr.session() as conn:
            _insert_price(conn, "HAL", "INE1", "2026-08-27")
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_checkpoint_fail_aborts_predict(self):
        master, backfill, fund = FakeMaster(), FakeBackfill(), FakeFundamentals()
        phase_fail = FakePhase1Fail()
        screener, orch, eod = FakeScreener(), FakeOrchestrator(), FakeEOD()
        summary = na.run_nightly(
            dry_run=False,
            part="fetch_predict",
            date_str="2026-08-27",
            db_manager=self.mgr,
            master_sync_mgr=master,
            backfill_mgr=backfill,
            phase1_runner_obj=phase_fail,
            fundamentals_client_obj=fund,
            screener=screener,
            orchestrator=orch,
            report_writer=FakeWriter(self.log_dir),
            eod_corrector_obj=eod,
            log_dir=self.log_dir,
            lock_path=self.log_dir / "nightly.lock",
        )
        # Fetch stages ran; predict stages aborted without touching screens/orchestrator.
        self.assertEqual(summary["stages"]["checkpoint"]["status"], "failed")
        for name in ("screen_legacy", "screen_ensemble",
                     "daily_alpha_ensemble", "daily_alpha_legacy"):
            self.assertEqual(summary["stages"][name]["status"], "aborted")
        self.assertEqual(screener.legacy_calls, [])
        self.assertEqual(screener.ensemble_calls, [])
        self.assertEqual(orch.calls, [])
        self.assertNotEqual(summary["exit_code"], 0)
        # Health JSON persisted with the abort recorded.
        health = self.log_dir / "nightly_2026-08-27.json"
        self.assertTrue(health.exists())
        data = json.loads(health.read_text(encoding="utf-8"))
        self.assertEqual(data["stages"]["screen_legacy"]["status"], "aborted")
        self.assertFalse(data["checkpoint"]["passed"])

    def test_checkpoint_pass_runs_predict_and_overlap(self):
        screener, orch = FakeScreener(), FakeOrchestrator()
        summary = na.run_nightly(
            dry_run=False,
            part="fetch_predict",
            date_str="2026-08-27",
            db_manager=self.mgr,
            master_sync_mgr=FakeMaster(),
            backfill_mgr=FakeBackfill(),
            phase1_runner_obj=FakePhase1Pass(),
            fundamentals_client_obj=FakeFundamentals(),
            screener=screener,
            orchestrator=orch,
            report_writer=FakeWriter(self.log_dir),
            eod_corrector_obj=FakeEOD(),
            log_dir=self.log_dir,
            lock_path=self.log_dir / "nightly.lock",
        )
        self.assertEqual(summary["stages"]["screen_legacy"]["status"], "ok")
        self.assertEqual(summary["stages"]["screen_ensemble"]["status"], "ok")
        self.assertEqual(len(screener.legacy_calls), 1)
        self.assertEqual(len(screener.ensemble_calls), 1)
        # Full-universe screens per spec.
        self.assertEqual(screener.legacy_calls[0]["universe"], "all")
        self.assertEqual(screener.ensemble_calls[0]["universe"], "all")
        # Distinct LEG/ENS symbol sets -> zero overlap, 20 each.
        self.assertEqual(summary["top20_overlap"]["overlap_count"], 0)
        self.assertEqual(summary["top20_overlap"]["legacy_count"], 20)
        # Renamed alpha files exist (no collision on daily_alpha.*).
        self.assertIn("ensemble", summary["alpha_files"])
        self.assertIn("legacy", summary["alpha_files"])
        ens_json = Path(summary["alpha_files"]["ensemble"]["json"])
        leg_json = Path(summary["alpha_files"]["legacy"]["json"])
        self.assertTrue(ens_json.exists() and leg_json.exists())
        self.assertNotEqual(ens_json, leg_json)
        self.assertEqual(summary["exit_code"], 0)


# ---------------------------------------------------------------------------
# 4. Snapshot naming matches prior manual runs
# ---------------------------------------------------------------------------
class TestSnapshotNaming(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_filenames_and_content(self):
        rows = [
            {"symbol": "reliance", "composite_rank": 1, "composite_score": 91.5},
            {"symbol": "HAL", "composite_rank": 2, "ensemble_composite": 77.03},
        ]
        leg = na.snapshot_top20(rows, "legacy", "2026-09-18", self.log_dir)
        ens = na.snapshot_top20(rows, "ensemble", "2026-09-18", self.log_dir)
        self.assertEqual(leg.name, "screen_legacy_top20_20260918.json")
        self.assertEqual(ens.name, "screen_ensemble_top20_20260918.json")
        data = json.loads(leg.read_text(encoding="utf-8"))
        self.assertEqual(data["date"], "2026-09-18")
        self.assertEqual(data["mode"], "legacy")
        self.assertEqual(data["count"], 2)
        self.assertEqual([e["symbol"] for e in data["top20"]], ["RELIANCE", "HAL"])
        self.assertEqual([e["composite_rank"] for e in data["top20"]], [1, 2])
        # Immediate-snapshot helper reads back rank order.
        self.assertEqual(na.load_snapshot_symbols(leg), ["RELIANCE", "HAL"])
        ov = na.compute_overlap(["A", "B"], ["B", "C"])
        self.assertEqual(ov["overlap_count"], 1)
        self.assertEqual(ov["overlap"], ["B"])

    def test_snapshot_rejects_bad_mode(self):
        with self.assertRaises(ValueError):
            na.snapshot_top20([], "bogus", "2026-09-18", self.log_dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
