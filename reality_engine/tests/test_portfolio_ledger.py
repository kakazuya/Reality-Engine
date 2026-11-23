"""
Slice 3 tests — Portfolio/ROC ledger + calibration feedback (hermetic).

Temp-file SQLite DB per case (precedent: test_move_attribution.py /
test_ensemble_ranker.py); never the live equity_intelligence.db.
Deterministic price fixtures; assertions on the Slice 3 contract:

* record -> MTM -> close lifecycle (target hit, stop hit, horizon expiry)
* idempotent re-record via UNIQUE(symbol, action_date, action)
* summarize math incl. HOLD directional-agreement scoring
* calibration path with stubbed skill_loop folds (gate respected both ways)
"""

from __future__ import annotations

import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reality_engine.db.database import DatabaseManager
from reality_engine.processing import portfolio_ledger as pl
from reality_engine.processing import skill_loop as sl


def _insert_company(conn, symbol, isin):
    conn.execute(
        """
        INSERT OR REPLACE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector, is_nifty200, is_nifty50, is_active)
        VALUES (?, ?, ?, 'Industrials', 'Capital Goods', 1, 1, 1)
        """,
        (isin, symbol, f"{symbol} Ltd"),
    )


def _insert_price(conn, symbol, isin, date, prev_close, close,
                  high=None, low=None):
    high = close * 1.01 if high is None else high
    low = close if low is None else low
    change = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_price_delivery
            (date, symbol, isin, series, open, high, low, close, prev_close, change_pct,
             total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct,
             delivery_spike_ratio, rsi_14)
        VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, ?, 100000, 200.0, 100, 50000, 50.0, 1.0, 50.0)
        """,
        (date, symbol, isin, close * 0.99, high, low, close, prev_close, change),
    )


def _date(base: datetime.date, offset: int) -> str:
    return (base + datetime.timedelta(days=offset)).isoformat()


def _row_for(mgr, action_id):
    with mgr.session() as conn:
        r = conn.execute(
            "SELECT * FROM portfolio_actions WHERE action_id = ?", (action_id,)
        ).fetchone()
        return dict(r) if r else None


class PortfolioLedgerBase(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))  # runs schema.sql
        pl.ensure_portfolio_schema(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self._fh.name)
        except OSError:
            pass

    def _seed_symbol(self, symbol="AAA", isin="INE000A01000"):
        with self.mgr.session() as conn:
            _insert_company(conn, symbol, isin)
        return symbol, isin


class TestPortfolioSchema(PortfolioLedgerBase):
    def test_exact_columns_and_unique_and_index(self):
        with self.mgr.session() as conn:
            cols = conn.execute("PRAGMA table_info('portfolio_actions')").fetchall()
        by_name = {c[1]: c for c in cols}
        expected = ["action_id", "symbol", "action", "action_date", "entry_price",
                    "target_price", "stop_loss", "thesis_ref", "status",
                    "closed_date", "exit_price", "pnl_pct"]
        self.assertEqual([c[1] for c in cols], expected)
        self.assertEqual(by_name["action_id"][5], 1)  # PK
        self.assertEqual(by_name["status"][4], "'open'")  # DEFAULT 'open'
        with self.mgr.session() as conn:
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='portfolio_actions'"
            ).fetchone()[0]
            idx = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='idx_portfolio_status_date'"
            ).fetchone()
        self.assertIn("UNIQUE(symbol, action_date, action)", ddl)
        self.assertIn("CHECK(action IN ('BUY','SELL','HOLD'))", ddl)
        self.assertIsNotNone(idx)
        self.assertIn("(status, action_date)", idx[0])
        # Idempotent re-ensure.
        pl.ensure_portfolio_schema(self.mgr)

    def test_summarize_without_table_writes_nothing(self):
        fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        fh.close()
        try:
            mgr = DatabaseManager(Path(fh.name))
            with mgr.session() as conn:
                conn.execute("DROP TABLE IF EXISTS portfolio_actions")
            out = pl.summarize(mgr)
            self.assertEqual(out["open_count"], 0)
            self.assertEqual(out["closed_count"], 0)
            self.assertIsNone(out["win_rate"])
            with mgr.session() as conn:
                gone = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='portfolio_actions'"
                ).fetchone()
            self.assertIsNone(gone)  # probe created nothing
        finally:
            try:
                os.unlink(fh.name)
            except OSError:
                pass


class TestRecordAction(PortfolioLedgerBase):
    def test_record_and_idempotent_rerecord(self):
        first = pl.record_action("aaa", "BUY", "2026-06-01", 100.0, 110.0, 90.0,
                                 thesis_ref="t1", manager=self.mgr)
        self.assertEqual(first["symbol"], "AAA")
        self.assertEqual(first["action"], "BUY")
        self.assertEqual(first["status"], "open")
        second = pl.record_action("AAA", "BUY", "2026-06-01", 999.0, 999.0, 999.0,
                                  thesis_ref="t2", manager=self.mgr)
        self.assertEqual(second["action_id"], first["action_id"])
        self.assertEqual(second["entry_price"], 100.0)  # existing row unchanged
        self.assertEqual(second["thesis_ref"], "t1")
        with self.mgr.session() as conn:
            n = conn.execute("SELECT COUNT(*) FROM portfolio_actions").fetchone()[0]
        self.assertEqual(n, 1)

    def test_hold_recorded_without_levels(self):
        row = pl.record_action("AAA", "HOLD", "2026-06-01", None, None, None,
                               manager=self.mgr)
        self.assertEqual(row["action"], "HOLD")
        self.assertEqual(row["status"], "open")
        self.assertIsNone(row["entry_price"])

    def test_rejects_bad_action_symbol_levels(self):
        with self.assertRaises(ValueError):
            pl.record_action("AAA", "LONG", "2026-06-01", 100.0, 110.0, 90.0,
                             manager=self.mgr)
        with self.assertRaises(ValueError):
            pl.record_action("", "BUY", "2026-06-01", 100.0, 110.0, 90.0,
                             manager=self.mgr)
        with self.assertRaises(ValueError):
            pl.record_action("AAA", "BUY", "2026-06-01", -5.0, 110.0, 90.0,
                             manager=self.mgr)


class TestMarkToMarket(PortfolioLedgerBase):
    def test_buy_target_hit(self):
        sym, isin = self._seed_symbol()
        rec = pl.record_action(sym, "BUY", "2026-06-01", 100.0, 110.0, 90.0,
                               manager=self.mgr)
        with self.mgr.session() as conn:
            _insert_price(conn, sym, isin, "2026-06-02", 100.0, 102.0,
                          high=103.0, low=101.0)
            _insert_price(conn, sym, isin, "2026-06-03", 102.0, 111.0,
                          high=112.0, low=108.0)
        out = pl.mark_to_market("2026-06-03", manager=self.mgr)
        self.assertEqual(out, {"marked": 1, "closed": 1, "open_pnl_sum": 0.0})
        row = _row_for(self.mgr, rec["action_id"])
        self.assertEqual(row["status"], "closed")
        self.assertEqual(row["closed_date"], "2026-06-03")
        self.assertEqual(row["exit_price"], 110.0)
        self.assertAlmostEqual(row["pnl_pct"], 10.0)

    def test_buy_stop_before_target_same_bar(self):
        sym, isin = self._seed_symbol()
        rec = pl.record_action(sym, "BUY", "2026-06-01", 100.0, 110.0, 90.0,
                               manager=self.mgr)
        with self.mgr.session() as conn:
            _insert_price(conn, sym, isin, "2026-06-02", 100.0, 100.0,
                          high=115.0, low=85.0)
        out = pl.mark_to_market("2026-06-02", manager=self.mgr)
        self.assertEqual(out["closed"], 1)
        row = _row_for(self.mgr, rec["action_id"])
        self.assertEqual(row["exit_price"], 90.0)  # stop wins the same-bar tie
        self.assertAlmostEqual(row["pnl_pct"], -10.0)

    def test_sell_mirrored_triggers(self):
        for sym, trg, stp, high, low, px, pnl in [
            ("AAA", 90.0, 110.0, 95.0, 88.0, 90.0, 10.0),    # target via low
            ("BBB", 90.0, 110.0, 112.0, 105.0, 110.0, -10.0),  # stop via high
        ]:
            with self.subTest(sym=sym):
                _, isin = self._seed_symbol(sym, f"INE{sym}01000")
                rec = pl.record_action(sym, "SELL", "2026-06-01", 100.0, trg, stp,
                                       manager=self.mgr)
                with self.mgr.session() as conn:
                    _insert_price(conn, sym, isin, "2026-06-02", 100.0, 92.0,
                                  high=high, low=low)
                pl.mark_to_market("2026-06-02", manager=self.mgr)
                row = _row_for(self.mgr, rec["action_id"])
                self.assertEqual(row["exit_price"], px)
                self.assertAlmostEqual(row["pnl_pct"], pnl)

    def test_horizon_expiry_closes_at_latest_close(self):
        sym, isin = self._seed_symbol()
        rec = pl.record_action(sym, "BUY", "2026-06-01", 100.0, 10000.0, 0.01,
                               manager=self.mgr)
        base = datetime.date(2026, 6, 2)
        with self.mgr.session() as conn:
            prev = 100.0
            for i in range(61):
                close = 100.0 + i * 0.05
                _insert_price(conn, sym, isin, _date(base, i), prev, close,
                              high=close * 1.001, low=close * 0.999)
                prev = close
        out = pl.mark_to_market(_date(base, 60), manager=self.mgr)
        self.assertEqual(out["closed"], 1)
        row = _row_for(self.mgr, rec["action_id"])
        self.assertEqual(row["status"], "closed")
        self.assertEqual(row["closed_date"], _date(base, 60))
        self.assertAlmostEqual(row["exit_price"], 100.0 + 60 * 0.05)
        self.assertAlmostEqual(row["pnl_pct"], (row["exit_price"] / 100.0 - 1.0) * 100.0)

    def test_open_position_reports_unrealized(self):
        sym, isin = self._seed_symbol()
        pl.record_action(sym, "BUY", "2026-06-01", 100.0, 10000.0, 0.01,
                         manager=self.mgr)
        with self.mgr.session() as conn:
            _insert_price(conn, sym, isin, "2026-06-02", 100.0, 101.0)
            _insert_price(conn, sym, isin, "2026-06-03", 101.0, 102.0)
        out = pl.mark_to_market("2026-06-03", manager=self.mgr)
        self.assertEqual(out["marked"], 1)
        self.assertEqual(out["closed"], 0)
        self.assertAlmostEqual(out["open_pnl_sum"], 2.0)

    def test_hold_resolves_with_zero_pnl(self):
        sym, isin = self._seed_symbol()
        rec = pl.record_action(sym, "HOLD", "2026-06-01", 100.0, None, None,
                               manager=self.mgr)
        base = datetime.date(2026, 6, 2)
        closes = [100.0, 101.0, 102.0, 103.0, 105.0]
        with self.mgr.session() as conn:
            prev = 100.0
            for i, close in enumerate(closes):
                _insert_price(conn, sym, isin, _date(base, i), prev, close)
                prev = close
        early = pl.mark_to_market(_date(base, 3), manager=self.mgr)
        self.assertEqual(early["closed"], 0)  # only 4 sessions visible
        late = pl.mark_to_market(_date(base, 4), manager=self.mgr)
        self.assertEqual(late["closed"], 1)
        row = _row_for(self.mgr, rec["action_id"])
        self.assertEqual(row["status"], "closed")
        self.assertEqual(row["exit_price"], 105.0)
        self.assertEqual(row["pnl_pct"], 0.0)

    def test_no_forward_bars_stays_open(self):
        sym, _ = self._seed_symbol()
        pl.record_action(sym, "BUY", "2026-06-01", 100.0, 110.0, 90.0,
                         manager=self.mgr)
        out = pl.mark_to_market("2026-06-01", manager=self.mgr)
        self.assertEqual(out, {"marked": 0, "closed": 0, "open_pnl_sum": 0.0})


class TestSummarize(PortfolioLedgerBase):
    def _lifecycle(self):
        a, isin_a = self._seed_symbol("AAA", "INE000A01000")
        b, isin_b = self._seed_symbol("BBB", "INE000B01000")
        c, isin_c = self._seed_symbol("CCC", "INE000C01000")
        pl.record_action(a, "BUY", "2026-06-01", 100.0, 110.0, 90.0, manager=self.mgr)
        pl.record_action(b, "SELL", "2026-06-01", 100.0, 90.0, 110.0, manager=self.mgr)
        pl.record_action(c, "HOLD", "2026-06-01", 100.0, None, None, manager=self.mgr)
        with self.mgr.session() as conn:
            _insert_price(conn, a, isin_a, "2026-06-02", 100.0, 111.0,
                          high=112.0, low=108.0)   # BUY target -> +10
            _insert_price(conn, b, isin_b, "2026-06-02", 100.0, 111.0,
                          high=112.0, low=108.0)   # SELL stop  -> -10
            prev = 100.0
            for i, close in enumerate([100.0, 101.0, 102.0, 103.0, 104.0]):
                _insert_price(conn, c, isin_c,
                              _date(datetime.date(2026, 6, 2), i), prev, close)
                prev = close
        pl.mark_to_market("2026-06-06", manager=self.mgr)

    def test_summary_math(self):
        self._lifecycle()
        s = pl.summarize(self.mgr)
        self.assertEqual(s["open_count"], 0)
        self.assertEqual(s["closed_count"], 3)
        # Positional: +10 and -10 -> mean 0, total 0; wins: 1 pos + 0 HOLD (no
        # attribution evidence -> conservative 0.0) over 3 closed.
        self.assertAlmostEqual(s["mean_pnl"], 0.0)
        self.assertAlmostEqual(s["total_pnl"], 0.0)
        self.assertAlmostEqual(s["win_rate"], 1.0 / 3.0)
        by = s["by_action"]
        self.assertEqual(by["BUY"], {"count": 1, "closed": 1, "wins": 1.0, "hit": 1.0})
        self.assertEqual(by["SELL"], {"count": 1, "closed": 1, "wins": 0.0, "hit": 0.0})
        self.assertEqual(by["HOLD"]["count"], 1)
        self.assertEqual(by["HOLD"]["closed"], 1)
        self.assertEqual(by["HOLD"]["hit"], 0.0)

    def test_hold_agreement_scoring(self):
        # Minimal Slice 1 ledger (raw DDL: no Slice 1 import, read-only use).
        with self.mgr.session() as conn:
            conn.execute(
                "CREATE TABLE move_attribution (symbol TEXT, attribution_date TEXT, "
                "realized_move_pct REAL, residual REAL)"
            )
            conn.execute(
                "INSERT INTO move_attribution VALUES ('AAA','2026-06-01', 2.0, 0.8)"
            )
            conn.execute(
                "INSERT INTO move_attribution VALUES ('BBB','2026-06-01', 2.0, 0.8)"
            )
        for sym in ("AAA", "BBB"):
            self._seed_symbol(sym, f"INE{sym}01000")
        pl.record_action("AAA", "HOLD", "2026-06-01", 100.0, None, None,
                         manager=self.mgr)
        pl.record_action("BBB", "HOLD", "2026-06-01", 100.0, None, None,
                         manager=self.mgr)
        with self.mgr.session() as conn:
            # AAA drifts up (+, agrees with +unexplained component); BBB down.
            prev_a = prev_b = 100.0
            for i, (ca, cb) in enumerate([(100, 100), (101, 99), (102, 98),
                                          (103, 97), (105, 95)]):
                d = _date(datetime.date(2026, 6, 2), i)
                _insert_price(conn, "AAA", "INEAAA01000", d, prev_a, float(ca))
                _insert_price(conn, "BBB", "INEBBB01000", d, prev_b, float(cb))
                prev_a, prev_b = float(ca), float(cb)
        pl.mark_to_market("2026-06-06", manager=self.mgr)
        s = pl.summarize(self.mgr)
        self.assertAlmostEqual(s["by_action"]["HOLD"]["wins"], 1.0)
        self.assertAlmostEqual(s["by_action"]["HOLD"]["hit"], 0.5)
        self.assertAlmostEqual(s["win_rate"], 0.5)
        self.assertIsNone(s["mean_pnl"])  # no positional closes
        self.assertEqual(s["total_pnl"], 0.0)

    def test_empty_summary(self):
        s = pl.summarize(self.mgr)
        self.assertEqual(s["open_count"], 0)
        self.assertEqual(s["closed_count"], 0)
        self.assertIsNone(s["win_rate"])
        self.assertIsNone(s["mean_pnl"])
        self.assertEqual(s["total_pnl"], 0.0)


_IMPROVED_FOLDS = {
    "status": "ok", "mode": "ensemble", "horizon_days": 5,
    "folds": 2, "folds_improved": 2, "folds_decided": 2,
    "mean_delta": 0.01, "median_delta": 0.01, "recommend_apply": True,
    "detail": [{"fold": 1, "weights": {"factor_statistical": 0.4,
                                       "policy_macro": 0.2,
                                       "business_quality": 0.2,
                                       "supply_chain": 0.2},
                "improved": True, "round_id": 7}],
}

_FLAT_FOLDS = {
    "status": "ok", "mode": "ensemble", "horizon_days": 5,
    "folds": 2, "folds_improved": 0, "folds_decided": 2,
    "mean_delta": -0.001, "median_delta": -0.001, "recommend_apply": False,
    "detail": [{"fold": 1, "weights": {"factor_statistical": 0.25,
                                       "policy_macro": 0.25,
                                       "business_quality": 0.25,
                                       "supply_chain": 0.25},
                "improved": False, "round_id": 9}],
}


class TestCalibration(PortfolioLedgerBase):
    def _rankings_count(self):
        with self.mgr.session() as conn:
            try:
                return conn.execute(
                    "SELECT COUNT(*) FROM model_explainer_rankings").fetchone()[0]
            except Exception:
                return 0

    def test_applied_path_gate_open(self):
        with patch.object(sl, "run_folds", return_value=dict(_IMPROVED_FOLDS)), \
             patch.object(sl, "apply_if_improved",
                          return_value={"applied": True,
                                        "weights": _IMPROVED_FOLDS["detail"][0]["weights"],
                                        "calibration": {"ok": True}}):
            out = pl.run_attribution_calibration(manager=self.mgr)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["applied"])
        self.assertIn("weights", out)
        self.assertIn("calibration", out)
        self.assertEqual(out["scores_published"], 0)  # empty book: no score rows
        self.assertEqual(self._rankings_count(), 0)  # never touched directly

    def test_not_improved_path_gate_holds(self):
        with patch.object(sl, "run_folds", return_value=dict(_FLAT_FOLDS)), \
             patch.object(sl, "apply_if_improved",
                          return_value={"applied": False,
                                        "reason": "no out-of-sample improvement",
                                        "summary": {"status": "ok"}}):
            out = pl.run_attribution_calibration(manager=self.mgr)
        self.assertEqual(out["status"], "ok")
        self.assertFalse(out["applied"])
        self.assertIn("reason", out)
        self.assertNotIn("weights", out)
        self.assertEqual(self._rankings_count(), 0)

    def test_never_writes_rankings_directly(self):
        src = Path(pl.__file__).read_text(encoding="utf-8")
        self.assertNotIn("INSERT INTO model_explainer_rankings", src)
        self.assertNotIn("UPDATE model_explainer_rankings", src)
        self.assertNotIn("DELETE FROM model_explainer_rankings", src)


class _StubScreenerStable:
    """Deterministic Stable-moat screener so the resolver is the only variable."""

    def _lookup_moat_metrics(self, sym, isin):
        return {"total_moat_score": 4.0, "moat_trajectory": "Stable",
                "moat_width": "Wide", "pricing_power_score": 4}

    def _lookup_policy_agg_eni(self, sym):
        return None

    def _lookup_roic_wacc_spread(self, sym, isin):
        return 0.05

    def _roic_wacc_spread_impl(self, sym, isin):
        return (0.05, "measured")

    def roic_wacc_status(self, sym, isin):
        return "measured"

    def _lookup_secular_growth_score(self, industry, sector):
        return 4.0


class _StubScreenerBroken:
    """Same stub with a Deteriorating trajectory (SELL-quality fixture)."""

    def _lookup_moat_metrics(self, sym, isin):
        return {"total_moat_score": 2.0, "moat_trajectory": "Deteriorating",
                "moat_width": "Narrow", "pricing_power_score": 2}

    def _lookup_policy_agg_eni(self, sym):
        return None

    def _lookup_roic_wacc_spread(self, sym, isin):
        return 0.05

    def _roic_wacc_spread_impl(self, sym, isin):
        return (0.05, "measured")

    def roic_wacc_status(self, sym, isin):
        return "measured"

    def _lookup_secular_growth_score(self, industry, sector):
        return 4.0


class TestSeedTrackRecord(PortfolioLedgerBase):
    """Seed-script contract: resolver-derived actions, HOLD default, idempotency.

    Exercises the same resolver path the theses use
    (``AgentOrchestrator._resolve_thesis_action`` driven by move-attribution
    rows + a ``forensic_solvency`` funda dict), not reimplemented math —
    fixtures only supply rows/prices/stubbed moat trajectories. The seed
    runner itself is covered through ``run_seed`` against the temp DB.
    """

    def setUp(self):
        super().setUp()
        from reality_engine.agent.orchestrator import AgentOrchestrator
        from reality_engine.db.repository import Repository
        from reality_engine.processing.move_attributor import (
            ensure_move_attribution_schema,
        )
        ensure_move_attribution_schema(self.mgr)
        self.repo = Repository(self.mgr)
        self.orch = AgentOrchestrator(repository=self.repo,
                                      screener=_StubScreenerStable())

    def _company(self, symbol, isin):
        with self.mgr.session() as conn:
            _insert_company(conn, symbol, isin)
        return symbol, isin

    def _attrib(self, symbol, date, realized, residual, material=1):
        # Fixture carries a factor_statistical dir WITH the realized sign: the
        # iteration-4 factor gate requires momentum with the entry, and the raw
        # INSERT below bypasses _build_attribution, so the witness must be
        # seeded explicitly (dir columns default 0/NULL = neutral = HOLD).
        fdir = 1 if realized > 0 else (-1 if realized < 0 else 0)
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO move_attribution "
                "(symbol, attribution_date, realized_move_pct, noise_floor, "
                "is_material, explained_total, residual, investor_majority, "
                "regime_tag, lens_factor_statistical_dir, "
                "lens_factor_statistical_w, lens_factor_statistical_share) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, date, realized, 1.0, material,
                 1.0 - residual, residual, "all", "*",
                 fdir, 0.25, 0.25 if fdir else 0.0),
            )

    def _call(self, symbol, isin, date, cmp_=100.0, target=110.0, stop=90.0,
              approved=1):
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO eod_scrip_calls "
                "(date, symbol, isin, composite_rank, technical_score, "
                "fundamental_score, alt_sentiment_score, composite_score, "
                "current_market_price, target_price, stop_loss, "
                "is_solvency_approved) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (date, symbol, isin, 1, 60.0, 60.0, 60.0, 60.0,
                 cmp_, target, stop, approved),
            )

    def test_resolver_derived_buy_on_seeded_fixture(self):
        # Unexplained weakness + Stable moat + approved solvency -> BUY.
        self._company("BUYCO", "INEBUY01000")
        self._attrib("BUYCO", "2026-06-01", realized=-3.0, residual=0.8)
        self._call("BUYCO", "INEBUY01000", "2026-06-01")
        with self.mgr.session() as conn:
            attr = dict(conn.execute(
                "SELECT * FROM move_attribution WHERE symbol='BUYCO'").fetchone())
        action, block = self.orch._resolve_thesis_action(
            "BUYCO",
            candidate_row={"symbol": "BUYCO", "isin": "INEBUY01000"},
            attribution=attr,
            attribution_date="2026-06-01",
            funda={"forensic_solvency": {"is_solvency_approved": 1}},
        )
        self.assertEqual(action, "BUY")
        self.assertIsInstance(block, dict)
        row = pl.record_action("BUYCO", action, "2026-06-01", 100.0, 110.0,
                               90.0, thesis_ref="seed_track_record:2026-06-01",
                               manager=self.mgr)
        self.assertEqual(row["action"], "BUY")
        self.assertEqual(row["thesis_ref"], "seed_track_record:2026-06-01")

    def test_sell_shape_broken_quality(self):
        # Unexplained strength + Deteriorating moat -> SELL (solvency moot).
        from reality_engine.agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(repository=self.repo,
                                 screener=_StubScreenerBroken())
        action, block = orch._resolve_thesis_action(
            "SELLCO",
            candidate_row={"symbol": "SELLCO", "isin": "INESEL01000"},
            attribution={"realized_move_pct": 3.0, "noise_floor": 1.0,
                         "is_material": 1, "explained_total": 0.2,
                         "residual": 0.8, "per_lens": [],
                         "investor_majority": "all", "regime_tag": "*"},
            attribution_date="2026-06-01",
            funda={"forensic_solvency": {"is_solvency_approved": 0}},
        )
        self.assertEqual(action, "SELL")
        self.assertIsInstance(block, dict)
        row = pl.record_action("SELLCO", action, "2026-06-01", 100.0, 90.0,
                               110.0, manager=self.mgr)
        self.assertEqual(row["action"], "SELL")

    def test_hold_default_with_no_attribution_row(self):
        action, block = self.orch._resolve_thesis_action(
            "NOATTR",
            candidate_row={"symbol": "NOATTR", "isin": "INENO01000"},
            attribution=None,
            attribution_date="2026-06-01",
            funda={"forensic_solvency": {"is_solvency_approved": 1}},
        )
        self.assertEqual(action, "HOLD")
        self.assertIsNone(block)

    def test_idempotent_double_seed(self):
        first = pl.record_action("AAA", "BUY", "2026-06-01", 100.0, 110.0,
                                 90.0,
                                 thesis_ref="seed_track_record:2026-06-01",
                                 manager=self.mgr)
        second = pl.record_action("AAA", "BUY", "2026-06-01", 999.0, 999.0,
                                  999.0, thesis_ref="other",
                                  manager=self.mgr)
        self.assertEqual(second["action_id"], first["action_id"])
        self.assertEqual(second["entry_price"], 100.0)  # UNIQUE row unchanged
        with self.mgr.session() as conn:
            n = conn.execute("SELECT COUNT(*) FROM portfolio_actions").fetchone()[0]
        self.assertEqual(n, 1)

    def test_seed_run_skip_counts_structure(self):
        from reality_engine.scripts import seed_track_record as seed
        self._company("GOOD", "INEGOOD0100")
        self._company("NOCALL", "INENOC01000")
        self._company("NOPRICE", "INENOP01000")
        self._attrib("GOOD", "2026-06-01", realized=-3.0, residual=0.8)
        self._attrib("NOCALL", "2026-06-01", realized=-3.0, residual=0.8)
        with self.mgr.session() as conn:
            # Same-date bars give the attribution date price coverage; GOOD
            # also gets a forward close (entry source), the others do not.
            _insert_price(conn, "GOOD", "INEGOOD0100", "2026-06-01", 100.0,
                          100.0)
            _insert_price(conn, "GOOD", "INEGOOD0100", "2026-06-02", 100.0,
                          101.0)
            _insert_price(conn, "NOCALL", "INENOC01000", "2026-06-01", 100.0,
                          100.0)
            _insert_price(conn, "NOCALL", "INENOC01000", "2026-06-02", 100.0,
                          101.0)
            _insert_price(conn, "NOPRICE", "INENOP01000", "2026-06-01", 100.0,
                          100.0)
        self._call("GOOD", "INEGOOD0100", "2026-06-01")
        # NOCALL deliberately has no call row. NOPRICE's call row carries a
        # zero CMP (rejected as an entry price) and has no forward close, so
        # it exercises the no_price skip.
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO eod_scrip_calls "
                "(date, symbol, isin, composite_rank, technical_score, "
                "fundamental_score, alt_sentiment_score, composite_score, "
                "current_market_price, target_price, stop_loss, "
                "is_solvency_approved) "
                "VALUES ('2026-06-01','NOPRICE','INENOP01000',1,60,60,60,60,"
                "0.0,110.0,90.0,1)"
            )
        self._attrib("NOPRICE", "2026-06-01", realized=-3.0, residual=0.8)
        out = seed.run_seed(days=25, per_date=None, manager=self.mgr,
                            orch=self.orch)
        self.assertEqual(out["candidates"], 3)
        self.assertEqual(out["skipped"]["no_call"], 1)
        self.assertEqual(out["skipped"]["no_price"], 1)
        self.assertEqual(out["skipped"]["resolver"], 0)
        self.assertEqual(out["recorded"]["BUY"], 1)
        self.assertEqual(out["actions_now_open"], 1)
        self.assertIn("mark_to_market", out)
        self.assertIn("roc", out)
        self.assertIn("open_count", out["roc"])


class TestP0HonestBook(PortfolioLedgerBase):
    """P0 honest-book regressions: framing, avoided-loss SELL, vol brackets, quarantine."""

    def _prices(self, symbol, isin, closes, start=datetime.date(2026, 6, 1)):
        with self.mgr.session() as conn:
            prev = closes[0]
            for i, close in enumerate(closes):
                _insert_price(conn, symbol, isin, _date(start, i), prev, close,
                              high=close * 1.01, low=close * 0.99)
                prev = close

    def test_long_framed_sell_rejected(self):
        with self.assertRaises(ValueError):
            pl.record_action("AAA", "SELL", "2026-06-01", 100.0, 110.0, 90.0,
                             manager=self.mgr)
        with self.assertRaises(ValueError):
            pl.record_action("AAA", "SELL", "2026-06-01", 100.0, 90.0, 90.0,
                             manager=self.mgr)
        with self.assertRaises(ValueError):
            pl.record_action("AAA", "BUY", "2026-06-01", 100.0, 90.0, 80.0,
                             manager=self.mgr)
        with self.assertRaises(ValueError):
            pl.record_action("AAA", "HOLD", "2026-06-01", 100.0, 110.0, 90.0,
                             manager=self.mgr)

    def test_sell_stopout_books_avoided_loss(self):
        # Honest SELL framing: target below, stop above. Stop-out exits at
        # the stop (above entry) and books avoided-loss-vs-holding.
        sym, isin = self._seed_symbol("SELLX", "INESELX0100")
        rec = pl.record_action(sym, "SELL", "2026-06-01", 100.0, 90.0, 104.0,
                               manager=self.mgr)
        with self.mgr.session() as conn:
            _insert_price(conn, sym, isin, "2026-06-02", 100.0, 105.0,
                          high=106.0, low=103.0)
        pl.mark_to_market("2026-06-02", manager=self.mgr)
        row = _row_for(self.mgr, rec["action_id"])
        self.assertEqual(row["status"], "closed")
        self.assertEqual(row["exit_price"], 104.0)
        self.assertAlmostEqual(row["pnl_pct"], -4.0)

    def test_sell_target_win_books_gain(self):
        sym, isin = self._seed_symbol("SELLW", "INESELW0100")
        rec = pl.record_action(sym, "SELL", "2026-06-01", 100.0, 90.0, 104.0,
                               manager=self.mgr)
        with self.mgr.session() as conn:
            _insert_price(conn, sym, isin, "2026-06-02", 100.0, 89.0,
                          high=99.0, low=88.0)
        pl.mark_to_market("2026-06-02", manager=self.mgr)
        row = _row_for(self.mgr, rec["action_id"])
        self.assertEqual(row["exit_price"], 90.0)
        self.assertAlmostEqual(row["pnl_pct"], 10.0)

    def test_bracket_scales_with_sigma(self):
        low = pl.bracket_for_entry(100.0, 0.5, "BUY")
        high = pl.bracket_for_entry(100.0, 6.0, "BUY")
        self.assertGreater(high["target_price"], low["target_price"])
        self.assertLess(high["stop_loss"], low["stop_loss"])
        self.assertNotAlmostEqual(high["target_price"], low["target_price"])
        sell = pl.bracket_for_entry(100.0, 2.0, "SELL")
        self.assertLess(sell["target_price"], 100.0)
        self.assertGreater(sell["stop_loss"], 100.0)
        # Trailing-history path: flat closes -> narrow; choppy closes -> wide.
        flat_sym, flat_isin = self._seed_symbol("FLATV", "INEFLA01000")
        chop_sym, chop_isin = self._seed_symbol("CHOPV", "INECHO01000")
        base = datetime.date(2026, 5, 1)
        self._prices(flat_sym, flat_isin, [100.0] * 20, start=base)
        chops = [100.0 + (6.0 if i % 2 else -6.0) for i in range(20)]
        self._prices(chop_sym, chop_isin, chops, start=base)
        with self.mgr.session() as conn:
            flat = pl.vol_scaled_bracket(flat_sym, 100.0, "BUY", "2026-06-01",
                                         conn=conn)
            chop = pl.vol_scaled_bracket(chop_sym, 100.0, "BUY", "2026-06-01",
                                         conn=conn)
        self.assertGreater(chop["target_price"], flat["target_price"])
        self.assertLess(chop["stop_loss"], flat["stop_loss"])

    def test_quarantine_rows_excluded_from_reads(self):
        from reality_engine.processing.substrate_hygiene import ensure_schema
        sym, isin = self._seed_symbol("PHANTM", "INE_AUTO_PH1")
        rec = pl.record_action(sym, "SELL", "2026-06-01", 100.0, 90.0, 110.0,
                               manager=self.mgr)
        with self.mgr.session() as conn:
            _insert_price(conn, sym, isin, "2026-06-02", 100.0, 111.0,
                          high=112.0, low=108.0)
            ensure_schema(conn)
    def test_seed_excludes_quarantine_and_uses_vol_brackets(self):
        from reality_engine.scripts import seed_track_record as seed
        from reality_engine.agent.orchestrator import AgentOrchestrator
        from reality_engine.db.repository import Repository
        from reality_engine.processing.move_attributor import (
            ensure_move_attribution_schema,
        )
        from reality_engine.processing.substrate_hygiene import ensure_schema
        ensure_move_attribution_schema(self.mgr)
        repo = Repository(self.mgr)
        orch = AgentOrchestrator(repository=repo)
        for sym, isin in (("NIFTYQ", "INEQ00001001"), ("GHOSTQ", "INE_AUTO_GH1")):
            with self.mgr.session() as conn:
                _insert_company(conn, sym, isin)
        with self.mgr.session() as conn:
            conn.execute(
                "UPDATE master_companies SET is_nifty50 = 1 WHERE nse_symbol = 'NIFTYQ'")
            ensure_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO substrate_quarantine "
                "(rule_id, table_name, row_key, severity, reason) "
                "VALUES (?,?,?,?,?)",
                ("synthetic_isin_companies", "master_companies",
                 "INE_AUTO_GH1", "quarantine", "synthetic backfill ISIN"),
            )
            for sym, isin in (("NIFTYQ", "INEQ00001001"), ("GHOSTQ", "INE_AUTO_GH1")):
                conn.execute(
                    "INSERT OR REPLACE INTO move_attribution "
                    "(symbol, attribution_date, realized_move_pct, noise_floor, "
                    "is_material, explained_total, residual, investor_majority, "
                    "regime_tag, lens_factor_statistical_dir, "
                    "lens_factor_statistical_w, lens_factor_statistical_share) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sym, "2026-06-01", -3.0, 1.0, 1, 0.2, 0.8, "all", "*",
                     -1, 0.25, 0.25),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO eod_scrip_calls "
                    "(date, symbol, isin, composite_rank, technical_score, "
                    "fundamental_score, alt_sentiment_score, composite_score, "
                    "current_market_price, target_price, stop_loss, "
                    "is_solvency_approved) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("2026-06-01", sym, isin, 1, 60.0, 60.0, 60.0,
                     60.0, 100.0, 118.0, 94.0, 1),
                )
                _insert_price(conn, sym, isin, "2026-06-01", 100.0,
                              100.0)
                _insert_price(conn, sym, isin, "2026-06-02", 100.0,
                              101.0)
        out = seed.run_seed(days=25, per_date=None, manager=self.mgr,
                            orch=orch)
        with self.mgr.session() as conn:
            syms = [r[0] for r in conn.execute(
                "SELECT symbol FROM portfolio_actions").fetchall()]
        self.assertNotIn("GHOSTQ", syms)
        self.assertEqual(out["skipped"]["quarantined"], 1)
        with self.mgr.session() as conn:
            sells = conn.execute(
                "SELECT target_price, entry_price, stop_loss FROM portfolio_actions "
                "WHERE action = 'SELL'").fetchall()
            for tgt, ent, stp in sells:
                self.assertLess(tgt, ent)
                self.assertLess(ent, stp)


if __name__ == "__main__":
    unittest.main()
