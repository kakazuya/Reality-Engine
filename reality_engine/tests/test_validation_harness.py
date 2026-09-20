"""
Wave B — validation harness + notifier tests (temp DBs only, never live DB).

Known-answer checks on synthetic prices/predictions:
  * perfect predictor  -> hit-rate 1.0, IC ~1.0
  * alternating up/down -> hit-rate exactly 0.5
  * horizons count trading bars present in daily_price_delivery (calendar gaps skipped)
  * per-lens calibration recovers the better lens (weight_A > weight_B, sum 1, floor kept)
  * fit never mutates model_explainer_rankings; apply_calibration does (deliberate path)
  * mode_symbols filter isolates one run among mixed same-date rows
  * thesis target-before-stop scoring (1 hit + 1 stopped-out -> 0.5)
  * notifier: missing creds -> False (no crash); dry_run with creds -> True (no network);
    digest contains stages / hit-rates / failures and never raises.
"""

import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.ensemble_ranker import EnsembleRanker
from reality_engine.processing.validation_harness import (
    EXPLAIN_FLOOR,
    ValidationHarness,
    fit_lens_weights,
)
from reality_engine.reporting.notifier import format_nightly_digest, send_telegram


def _mk_mgr():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    mgr = DatabaseManager(Path(tmp.name))
    return mgr, tmp.name


def _isin(symbol):
    return f"INE_{symbol}"


def _add_master(mgr, symbols):
    with mgr.session() as conn:
        for s in symbols:
            conn.execute(
                "INSERT OR IGNORE INTO master_companies (isin, nse_symbol, company_name)"
                " VALUES (?, ?, ?)",
                (_isin(s), s, f"{s} Ltd"),
            )


def _add_prices(mgr, symbol, closes, start, isin=None, spreads=None):
    """Consecutive-date bars; spreads[i]=(high_mult, low_mult) overrides default."""
    isin = isin or _isin(symbol)
    with mgr.session() as conn:
        prev = closes[0]
        for i, c in enumerate(closes):
            d = (start + timedelta(days=i)).isoformat()
            hm, lm = (spreads[i] if spreads and i < len(spreads) else (1.02, 0.98))
            conn.execute(
                "INSERT OR REPLACE INTO daily_price_delivery (date, symbol, isin, open, high,"
                " low, close, prev_close, change_pct, total_volume, deliverable_volume,"
                " delivery_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (d, symbol, isin, prev, c * hm, c * lm, c, prev,
                 (c / prev - 1.0) * 100.0, 1000, 500, 50.0),
            )
            prev = c


def _add_prices_on_dates(mgr, symbol, closes, dates, isin=None):
    isin = isin or _isin(symbol)
    with mgr.session() as conn:
        prev = closes[0]
        for d, c in zip(dates, closes):
            conn.execute(
                "INSERT OR REPLACE INTO daily_price_delivery (date, symbol, isin, open, high,"
                " low, close, prev_close, change_pct, total_volume, deliverable_volume,"
                " delivery_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (d, symbol, isin, prev, c * 1.02, c * 0.98, c, prev,
                 (c / prev - 1.0) * 100.0, 1000, 500, 50.0),
            )
            prev = c


def _add_pred(mgr, asof, symbol, rank, score, cmp_price=100.0, isin=None):
    isin = isin or _isin(symbol)
    with mgr.session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO eod_scrip_calls (date, symbol, isin, composite_rank,"
            " technical_score, fundamental_score, alt_sentiment_score, composite_score,"
            " current_market_price) VALUES (?, ?, ?, ?, 50, 50, 50, ?, ?)",
            (asof, symbol, isin, rank, score, cmp_price),
        )


class _Base(unittest.TestCase):
    def setUp(self):
        self.mgr, self._path = _mk_mgr()
        self.repo = Repository(self.mgr)
        self.reports = Path(tempfile.mkdtemp())
        self.h = ValidationHarness(self.mgr, self.reports)

    def tearDown(self):
        try:
            os.unlink(self._path)
        except OSError:
            pass


class TestPerfectPredictor(_Base):
    def test_hit_rate_1_and_ic_1(self):
        syms = [f"PERF{i}" for i in range(8)]
        _add_master(self.mgr, syms)
        asof = date(2026, 9, 1)
        # Every symbol rises; bigger index -> bigger 5-bar gain.
        for i, s in enumerate(syms):
            gain = 0.01 * (i + 1)
            closes = [100.0] + [100.0 * (1 + gain * k / 5.0) for k in range(1, 8)]
            _add_prices(self.mgr, s, closes, asof)
            _add_pred(self.mgr, asof.isoformat(), s, rank=i + 1,
                      score=gain * 1000.0, cmp_price=100.0)
        out = self.h.score_predictions(asof.isoformat(), horizon_days=[5], mode="ensemble")
        self.assertEqual(out["horizons"][5]["n"], 8)
        self.assertAlmostEqual(out["horizons"][5]["hit_rate"], 1.0)
        self.assertAlmostEqual(out["horizons"][5]["ic"], 1.0, places=6)
        self.assertGreater(out["horizons"][5]["mean_fwd_ret_top20"], 0)
        rows = self.repo.get_validation_scores(asof_date=asof.isoformat(), mode="ensemble")
        self.assertTrue(rows)
        overall = [r for r in rows if r["lens_family"] in (None, "__all__")
                   and r["investor_majority"] == "all" and r["horizon_days"] == 5]
        self.assertEqual(len(overall), 1)
        self.assertAlmostEqual(overall[0]["hit_rate"], 1.0)
        self.assertEqual(overall[0]["regime_tag"], "unknown")  # no breadth seeded


class TestCoinFlipPredictor(_Base):
    def test_hit_rate_half(self):
        syms = [f"FLIP{i}" for i in range(10)]
        _add_master(self.mgr, syms)
        asof = date(2026, 9, 1)
        for i, s in enumerate(syms):
            up = (i % 2 == 0)
            closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0,
                      110.0 if up else 90.0]
            _add_prices(self.mgr, s, closes, asof)
            _add_pred(self.mgr, asof.isoformat(), s, rank=i + 1, score=float(10 - i))
        out = self.h.score_predictions(asof.isoformat(), horizon_days=[5], mode="legacy")
        self.assertAlmostEqual(out["horizons"][5]["hit_rate"], 0.5)


class TestTradingDayHorizons(_Base):
    def test_calendar_gap_skipped(self):
        # Bars on Fri 2026-09-04 and Mon 2026-09-07 only: horizon 1 must be Monday.
        _add_master(self.mgr, ["GAP"])
        fri, mon = "2026-09-04", "2026-09-07"
        _add_prices_on_dates(self.mgr, "GAP", [100.0, 110.0], [fri, mon])
        _add_pred(self.mgr, fri, "GAP", rank=1, score=90.0)
        out = self.h.score_predictions(fri, horizon_days=[1, 5], mode="ensemble")
        self.assertIn(1, out["horizons"])       # Monday bar exists
        self.assertNotIn(5, out["horizons"])    # no 5th bar -> horizon skipped
        self.assertAlmostEqual(out["horizons"][1]["mean_fwd_ret_top20"], 0.10, places=6)
        self.assertAlmostEqual(out["horizons"][1]["hit_rate"], 1.0)


class TestLensCalibration(_Base):
    def _seed(self, asof):
        good = [f"GOOD{i}" for i in range(4)]
        bad = [f"BAD{i}" for i in range(4)]
        _add_master(self.mgr, good + bad)
        ranker = EnsembleRanker(self.mgr)
        rank = 0
        for s in good + bad:
            rank += 1
            if s.startswith("GOOD"):
                closes = [100.0, 102, 104, 106, 108, 112]
            else:
                closes = [100.0, 99, 98, 97, 96, 94]
            _add_prices(self.mgr, s, closes, asof)
            _add_pred(self.mgr, asof.isoformat(), s, rank=rank, score=50.0)
            dom = "factor_statistical" if s.startswith("GOOD") else "supply_chain"
            for fam in ("factor_statistical", "business_quality",
                        "policy_macro", "supply_chain"):
                ranker.upsert_ranking(s, None, None, None, "all", fam,
                                      p_value=0.05,
                                      explain_power=0.9 if fam == dom else 0.1)
        return good, bad

    def test_calibration_recovers_better_lens(self):
        asof = date(2026, 9, 1)
        self._seed(asof)
        out = self.h.score_predictions(asof.isoformat(), horizon_days=[5], mode="ensemble")
        self.assertIn(5, out["horizons"])
        rows = self.repo.get_validation_scores(asof_date=asof.isoformat(), mode="ensemble")
        lens_rows = {r["lens_family"]: r for r in rows
                     if r["lens_family"] is not None and r["horizon_days"] == 5}
        self.assertIn("factor_statistical", lens_rows)
        self.assertIn("supply_chain", lens_rows)
        self.assertAlmostEqual(lens_rows["factor_statistical"]["hit_rate"], 1.0)
        self.assertAlmostEqual(lens_rows["supply_chain"]["hit_rate"], 0.0)

        prop = self.h.fit_lens_weights("unknown", "all")
        w = prop["weights"]
        self.assertAlmostEqual(sum(w.values()), 1.0, places=6)
        self.assertGreater(w["factor_statistical"], w["supply_chain"])
        for fam, weight in w.items():
            if weight > EXPLAIN_FLOOR:
                continue
            self.assertAlmostEqual(weight, EXPLAIN_FLOOR, delta=0.01,
                msg=f"{fam}: floored-then-renormalized minors may sit just under FLOOR")
        stored = self.repo.get_lens_weight_proposals(regime_tag="unknown",
                                                     investor_majority="all")
        self.assertEqual(len(stored), 4)

    def test_fit_does_not_mutate_rankings_but_apply_does(self):
        asof = date(2026, 9, 1)
        good, _ = self._seed(asof)
        self.h.score_predictions(asof.isoformat(), horizon_days=[5], mode="ensemble")
        ranker = EnsembleRanker(self.mgr)
        before = {r["lens_family"]: r["explain_power"]
                  for r in ranker.get_rankings(good[0], "all")}
        prop = fit_lens_weights("unknown", "all", manager=self.mgr)
        after_fit = {r["lens_family"]: r["explain_power"]
                     for r in ranker.get_rankings(good[0], "all")}
        self.assertEqual(before, after_fit)  # fit is proposal-only
        res = self.h.apply_calibration(prop, stock_ids=[good[0]])
        self.assertEqual(res["stocks_updated"], 1)
        self.assertEqual(res["rows_written"], 4)
        after_apply = {r["lens_family"]: r["explain_power"]
                       for r in ranker.get_rankings(
                           good[0], prop["investor_majority"],
                           regime_tag=prop["regime_tag"])}
        for fam, weight in prop["weights"].items():
            self.assertAlmostEqual(after_apply[fam], weight, places=6)
        self.assertAlmostEqual(sum(after_apply.values()), 1.0, places=6)
        best_prop = max(prop["weights"], key=prop["weights"].get)
        best_applied = max(after_apply, key=after_apply.get)
        self.assertEqual(best_applied, best_prop)


class TestModeSymbolsFilter(_Base):
    def test_mixed_same_date_rows_isolated(self):
        syms = [f"ENS{i}" for i in range(3)] + [f"LEG{i}" for i in range(3)]
        _add_master(self.mgr, syms)
        asof = date(2026, 9, 1)
        for i, s in enumerate(syms):
            _add_prices(self.mgr, s, [100.0, 101, 102, 103, 104, 105], asof)
            _add_pred(self.mgr, asof.isoformat(), s, rank=i + 1, score=float(i))
        ens = [s for s in syms if s.startswith("ENS")]
        out = self.h.score_predictions(asof.isoformat(), horizon_days=[5],
                                       mode="ensemble", mode_symbols=ens)
        self.assertEqual(out["n_predictions"], 3)
        self.assertEqual(out["horizons"][5]["n"], 3)


class TestThesisHit(_Base):
    def test_target_before_stop(self):
        _add_master(self.mgr, ["HIT", "STOP"])
        asof = date(2026, 9, 1)
        # HIT: day-1 high clears 110 target, low never touches 95 stop.
        with self.mgr.session() as conn:
            for sym, bars in {
                "HIT": [(100, 112, 99), (100, 113, 99)],
                "STOP": [(100, 101, 94), (100, 101, 99)],
            }.items():
                conn.execute(
                    "INSERT OR REPLACE INTO daily_price_delivery (date, symbol, isin, open,"
                    " high, low, close, prev_close, change_pct, total_volume,"
                    " deliverable_volume, delivery_pct) VALUES (?, ?, ?, 100, 100, 100,"
                    " 100, 100, 0, 1000, 500, 50.0)", (asof.isoformat(), sym, _isin(sym)))
                for i, (c, hi, lo) in enumerate(bars, start=1):
                    d = (asof + timedelta(days=i)).isoformat()
                    conn.execute(
                        "INSERT OR REPLACE INTO daily_price_delivery (date, symbol, isin,"
                        " open, high, low, close, prev_close, change_pct, total_volume,"
                        " deliverable_volume, delivery_pct) VALUES (?, ?, ?, 100, ?, ?,"
                        " ?, 100, 0, 1000, 500, 50.0)", (d, sym, _isin(sym), hi, lo, c))
        for i, s in enumerate(["HIT", "STOP"]):
            _add_pred(self.mgr, asof.isoformat(), s, rank=i + 1, score=50.0, cmp_price=100.0)
        day_dir = self.reports / asof.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "daily_alpha_ensemble.json").write_text(json.dumps({
            "date": asof.isoformat(),
            "high_conviction_theses": [
                {"symbol": "HIT", "current_market_price": 100.0,
                 "recommended_entry_range": "INR 99.00 - INR 101.00",
                 "target_price": 110.0, "stop_loss": 95.0},
                {"symbol": "STOP", "current_market_price": 100.0,
                 "recommended_entry_range": "INR 99.00 - INR 101.00",
                 "target_price": 110.0, "stop_loss": 95.0},
            ],
        }), encoding="utf-8")
        out = self.h.score_predictions(asof.isoformat(), horizon_days=[2], mode="ensemble")
        self.assertEqual(out["thesis_n"], 2)
        self.assertAlmostEqual(out["thesis_hit_rate"], 0.5)


class TestRegimeAndBreadth(_Base):
    def test_bullish_regime_from_breadth(self):
        _add_master(self.mgr, ["R"])
        asof = date(2026, 9, 1)
        _add_prices(self.mgr, "R", [100.0, 101, 102, 103, 104, 105], asof)
        _add_pred(self.mgr, asof.isoformat(), "R", rank=1, score=10.0)
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO nse_index_breadth (date, index_name, change_pct,"
                " advances_count, declines_count, advance_decline_ratio)"
                " VALUES (?, 'Nifty 200', 1.0, 160, 40, 4.0)", (asof.isoformat(),))
        out = self.h.score_predictions(asof.isoformat(), horizon_days=[5], mode="ensemble")
        self.assertEqual(out["regime_tag"], "bullish")


class TestNotifier(unittest.TestCase):
    def test_missing_creds_returns_false(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
        old = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(env)
            self.assertFalse(send_telegram("hello"))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_dry_run_with_creds_no_network(self):
        old = (os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "fake-token"
            os.environ["TELEGRAM_CHAT_ID"] = "fake-chat"
            self.assertTrue(send_telegram("hello", dry_run=True))
        finally:
            for k, v in (("TELEGRAM_BOT_TOKEN", old[0]), ("TELEGRAM_CHAT_ID", old[1])):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_send_rejects_empty_message(self):
        with self.assertRaises(ValueError):
            send_telegram("   ")

    def test_digest_content_and_never_crashes(self):
        health = {
            "today_ist": "2026-09-16", "mode": "post-close", "dry_run": False,
            "missing_trading_days": [],
            "actions": {
                "backfill": {"requested": 5, "sessions_ingested": 5},
                "distillation": {"distilled": 2, "event_ids": ["E1"]},
                "eod_corrections": [{"date": "2026-09-16", "symbols_corrected": 10}],
                "pruning": {"prune_decayed_signals": {"error": "boom"}},
            },
        }
        val = {"asof_date": "2026-09-10", "mode": "ensemble", "regime_tag": "neutral",
               "n_predictions": 40, "n_scored": 38,
               "horizons": {5: {"n": 38, "hit_rate": 0.6, "mean_fwd_ret_top20": 0.02,
                                "universe_mean_ret": 0.005, "ic": 0.3}},
               "thesis_hit_rate": 0.5, "thesis_n": 4}
        text = format_nightly_digest(health, val)
        for needle in ("stages", "checkpoint", "H+5d", "hit=60.0%", "failures",
                       "pruning.prune_decayed_signals: boom"):
            self.assertIn(needle, text)
        # Degenerate inputs never raise.
        self.assertIn("digest", format_nightly_digest(None, None).lower())
        self.assertIn("digest", format_nightly_digest("/nonexistent/path.json", {}).lower())


if __name__ == "__main__":
    unittest.main()
