"""
Scheduler + capacity-governor tests (TEMP SQLite + isolated loop dirs — never
the live DB, never the network, never schtasks).

Covers the behaviours the two new schedulers depend on:
  * forecast dry-run resolves dates and writes nothing
  * forecast lock blocks an overlapping tick (rc 2)
  * governor skips thin-evidence cohorts with a reason (no write)
  * governor refuses holdout-disagreeing cohorts (anti-overfit sign gate)
  * decided weights stay in [W_MIN, W_MAX], step L1 <= MAX_STEP_L1, sum == 1
  * apply_decision refuses non-decided input and writes decided rows
  * capacity report-only run writes no rankings; --cohort without --apply is an error
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.pipeline import forecast_tester as ft
from reality_engine.pipeline import capacity_loop as caploop
from reality_engine.processing import capacity_governor as cg

cg._REPO_OVERRIDE = Repository  # governor reads scores via the caller's temp DB, never live


def _make_db():
    fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fh.close()
    return DatabaseManager(Path(fh.name)), fh.name


def _cleanup(*paths):
    for p in paths:
        for cand in (p, p + "-wal", p + "-shm"):
            try:
                os.unlink(cand)
            except OSError:
                pass


def _master(conn, symbol, isin):
    conn.execute(
        "INSERT OR IGNORE INTO master_companies "
        "(isin, nse_symbol, company_name, industry, sector, is_nifty200, is_active) "
        "VALUES (?, ?, ?, 'Industrials', 'Capital Goods', 1, 1)",
        (isin, symbol, f"{symbol} Ltd"))


def _price(conn, symbol, isin, d, close=100.0):
    _master(conn, symbol, isin)
    conn.execute(
        "INSERT OR REPLACE INTO daily_price_delivery "
        "(date, symbol, isin, series, open, high, low, close, prev_close, change_pct, "
        "total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct, "
        "delivery_spike_ratio, rsi_14) VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, 0.0, "
        "1000, 10.0, 5, 500, 50.0, 1.0, 50.0)",
        (d, symbol, isin, close, close, close, close, close))


def _call(conn, d, symbol, isin, rank=1):
    _master(conn, symbol, isin)
    conn.execute(
        "INSERT OR REPLACE INTO eod_scrip_calls "
        "(date, symbol, isin, composite_rank, technical_score, fundamental_score, "
        "alt_sentiment_score, composite_score, current_market_price) "
        "VALUES (?, ?, ?, ?, 70.0, 60.0, 50.0, 65.0, 100.0)",
        (d, symbol, isin, rank))


def _score_row(conn, asof, horizon, regime, inv, lens, edge, n=2):
    conn.execute(
        "INSERT OR REPLACE INTO model_validation_scores "
        "(asof_date, horizon_days, mode, lens_family, regime_tag, investor_majority, "
        "n, mean_fwd_ret, universe_mean_ret) VALUES (?, ?, 'ensemble', ?, ?, ?, ?, ?, 0.0)",
        (asof, horizon, lens, regime, inv, n, edge))


class ForecastTesterTest(unittest.TestCase):
    def setUp(self):
        self.mgr, self.db_file = _make_db()
        self.tmp = tempfile.TemporaryDirectory()
        self.loop_dir = Path(self.tmp.name) / "forecast"

    def tearDown(self):
        self.tmp.cleanup()
        _cleanup(self.db_file)

    def test_dry_run_resolves_dates_and_writes_nothing(self):
        base = date(2026, 9, 1)
        with self.mgr.session() as conn:
            for i in range(12):
                _price(conn, "HAL", "INE0HAL", (base + timedelta(days=i)).isoformat())
            _call(conn, base.isoformat(), "HAL", "INE0HAL")
        res = ft.run_once(db_manager=self.mgr, loop_dir=self.loop_dir, dry_run=True)
        self.assertEqual(res["dates_scored"], 1)
        with self.mgr.session() as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM model_validation_scores").fetchone()[0], 0)

    def test_lock_blocks_overlapping_tick(self):
        self.loop_dir.mkdir(parents=True, exist_ok=True)
        fd = ft.acquire_lock(self.loop_dir / ft.LOCK_NAME)
        try:
            res = ft.run_once(db_manager=self.mgr, loop_dir=self.loop_dir, dry_run=True)
            self.assertTrue(res.get("skipped"))
        finally:
            ft.release_lock(fd, self.loop_dir / ft.LOCK_NAME)
        self.assertFalse((self.loop_dir / ft.LOCK_NAME).exists())

    def test_cli_flags_parse(self):
        self.assertEqual(ft.main(["--dry-run", "--loop-dir", str(self.loop_dir)]), 0)


class CapacityGovernorTest(unittest.TestCase):
    def setUp(self):
        self.mgr, self.db_file = _make_db()
        self.tmp = tempfile.TemporaryDirectory()
        self.loop_dir = Path(self.tmp.name) / "capacity"

    def tearDown(self):
        self.tmp.cleanup()
        _cleanup(self.db_file)

    def _seed_scores(self, conn, regime="neutral", inv="all", dates=None, winner="supply_chain",
                     holdout_agrees=True):
        dates = dates or [f"2026-08-{d:02d}" for d in (1, 4, 5, 6, 7, 8, 11, 12)]
        for i, d in enumerate(dates):
            agree = holdout_agrees or i < len(dates) - cg.HOLDOUT_DATES
            for fam in cg.LENS_FAMILIES if hasattr(cg, "LENS_FAMILIES") else (
                    "factor_statistical", "business_quality", "policy_macro", "supply_chain"):
                edge = 0.01 if (fam == winner and agree) else (-0.005 if fam == winner else 0.0)
                _score_row(conn, d, 5, regime, inv, fam, edge)
        return dates

    def test_thin_evidence_skips_without_writing(self):
        with self.mgr.session() as conn:
            self._seed_scores(conn, dates=["2026-08-01", "2026-08-04"])
        d = cg.evaluate_cohort(self.mgr, "neutral", "all")
        self.assertEqual(d["status"], "skipped")
        self.assertIn("thin_evidence", d["reason"])
        with self.mgr.session() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "model_explainer_rankings" in tables:
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM model_explainer_rankings").fetchone()[0], 0)

    def test_holdout_disagreement_refuses(self):
        with self.mgr.session() as conn:
            self._seed_scores(conn, holdout_agrees=False)
        d = cg.evaluate_cohort(self.mgr, "neutral", "all")
        self.assertEqual(d["status"], "skipped")
        self.assertIn("holdout_disagrees", d["reason"])

    def test_decided_weights_bounded_and_step_capped(self):
        with self.mgr.session() as conn:
            self._seed_scores(conn)
            _price(conn, "HAL", "INE0HAL", "2026-09-18")
            _call(conn, "2026-09-18", "HAL", "INE0HAL")
        d = cg.evaluate_cohort(self.mgr, "neutral", "all")
        self.assertEqual(d["status"], "decided")
        w = d["w_decided"]
        self.assertAlmostEqual(sum(w.values()), 1.0, places=6)
        for v in w.values():
            self.assertGreaterEqual(v, cg.W_MIN - 1e-9)
            self.assertLessEqual(v, cg.W_MAX + 1e-9)
        l1 = sum(abs(w[f] - d["w_current"][f]) for f in w)
        self.assertLessEqual(l1, cg.MAX_STEP_L1 + 1e-9)
        self.assertLessEqual(d["alpha"], cg.ALPHA_MAX + 1e-9)

    def test_apply_refuses_nondecieded_and_writes_decided(self):
        with self.assertRaises(ValueError):
            cg.apply_decision(self.mgr, {"status": "skipped", "reason": "thin"})
        with self.mgr.session() as conn:
            self._seed_scores(conn)
            _price(conn, "HAL", "INE0HAL", "2026-09-18")
            _call(conn, "2026-09-18", "HAL", "INE0HAL")
        d = cg.evaluate_cohort(self.mgr, "neutral", "all")
        res = cg.apply_decision(self.mgr, d)
        self.assertEqual(res["stocks_updated"], 1)
        self.assertEqual(res["rows_written"], 4)
        with self.mgr.session() as conn:
            rows = conn.execute(
                "SELECT lens_family, explain_power FROM model_explainer_rankings "
                "WHERE stock_id='HAL' AND regime_tag='neutral'").fetchall()
            self.assertEqual(len(rows), 4)
            self.assertAlmostEqual(sum(r[1] for r in rows), 1.0, places=6)

    def test_report_only_writes_no_rankings(self):
        with self.mgr.session() as conn:
            self._seed_scores(conn)
        res = caploop.run_once(db_manager=self.mgr, loop_dir=self.loop_dir)
        self.assertEqual(res["decided"], 1)
        self.assertEqual(res["applied"], [])
        with self.mgr.session() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "model_explainer_rankings" in tables:
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM model_explainer_rankings").fetchone()[0], 0)
        self.assertTrue(Path(res["summary_file"]).exists())

    def test_cohort_without_apply_flag_is_error(self):
        self.assertEqual(caploop.main(["--cohort", "neutral/all", "--loop-dir", str(self.loop_dir)]), 1)


if __name__ == "__main__":
    unittest.main()
