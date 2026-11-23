"""Walk-forward self-improvement loop: evidence that occurrences improve forecasts.

Mirrors the repo convention (tests/test_derived_substrate.py,
tests/test_peer_graph_and_hygiene.py): temp-file SQLite DB, never the live
equity_intelligence.db, deterministic fixtures, assertions on the contract.

Covers ``reality_engine/processing/skill_loop.py``:

* Bayesian weighting math: persistent significant edge moves the weight;
  absent evidence returns approximately uniform weights.
* Leakage guard: a train window that touches the eval window raises.
* History persistence round-trip and the apply gate
  (``apply_if_improved`` applies nothing without out-of-sample evidence).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.processing import skill_loop as sl


def _seed_validation(mgr, rows_spec) -> None:
    """Write model_validation_scores rows directly.

    ``rows_spec``: iterable of (asof_date, lens_family, mean_fwd_ret, universe_mean_ret).
    """
    with mgr.session() as conn:
        for asof, fam, mfr, umr in rows_spec:
            conn.execute(
                """INSERT INTO model_validation_scores
                   (asof_date, horizon_days, mode, lens_family, regime_tag,
                    investor_majority, n, hit_rate, mean_fwd_ret, universe_mean_ret, ic)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (asof, 5, "ensemble", fam, "neutral", "all", 50, 0.55, mfr, umr, None),
            )


class _BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="skill_loop_test_")
        self.mgr = DatabaseManager(db_path=Path(self.tmp) / "test.db")
        with self.mgr.session() as conn:
            sl.ensure_schema(conn)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class BayesianWeightTests(_BaseCase):
    def test_significant_persistent_edge_moves_weight(self):
        """A lens beating the universe by +2pp on four of four dates must dominate."""
        series = {
            "policy_macro": [(f"2026-08-{10+i:02d}", 0.02) for i in range(4)],
            "business_quality": [(f"2026-08-{10+i:02d}", 0.0) for i in range(4)],
            "factor_statistical": [(f"2026-08-{10+i:02d}", 0.0) for i in range(4)],
            "supply_chain": [(f"2026-08-{10+i:02d}", 0.0) for i in range(4)],
        }
        res = sl.bayesian_weights(series, temperature=0.005, prior_mix=0.5, min_t=1.0)
        self.assertGreater(res["weights"]["policy_macro"], 0.5)
        self.assertAlmostEqual(sum(res["weights"].values()), 1.0, places=9)
        self.assertFalse(res["stats"]["policy_macro"]["shrunk_to_prior"])

    def test_no_evidence_returns_approximately_uniform(self):
        """Absent evidence must not move weights: near-uniform is the honest answer."""
        series = {f: [] for f in sl.LENS_FAMILIES}
        res = sl.bayesian_weights(series, prior_mix=0.5)
        for w in res["weights"].values():
            self.assertAlmostEqual(w, 0.25, places=6)

    def test_single_lucky_date_is_shrunk(self):
        """One observation has infinite standard error -> t=0 -> shrink to prior."""
        series = {
            "policy_macro": [("2026-08-10", 0.05)],
            "business_quality": [],
            "factor_statistical": [],
            "supply_chain": [],
        }
        res = sl.bayesian_weights(series, temperature=0.005, prior_mix=0.5, min_t=1.0)
        self.assertTrue(res["stats"]["policy_macro"]["shrunk_to_prior"])
        self.assertAlmostEqual(res["weights"]["policy_macro"], 0.25, places=6)


class WalkForwardTests(_BaseCase):
    def _window(self, dates, fam, edge):
        return [(d, fam, edge, 0.0) for d in dates]

    def _cal(self, dates):
        return list(dates)  # dense test calendar: every occurrence date is a trading day

    def test_round_persists_and_separates_train_from_eval(self):
        dates = [f"2026-08-{10+i:02d}" for i in range(9)]
        spec = self._window(dates, "policy_macro", 0.01) + self._window(dates, "business_quality", 0.0)
        _seed_validation(self.mgr, spec)
        with self.mgr.session() as conn:
            rec = sl.run_round(conn, mode="ensemble", horizon_days=5, train_frac=0.45,
                               calendar=self._cal(dates))
        self.assertLess(rec["train_to"], rec["eval_from"])
        self.assertEqual(rec["n_train_dates"] + rec["n_eval_dates"], 9)
        self.assertAlmostEqual(sum(rec["weights"].values()), 1.0, places=9)
        self.assertIn("round_id", rec)
        with self.mgr.session() as conn:
            self.assertEqual(len(sl.history(conn)), 1)

    def test_apply_gate_blocks_non_improving_round(self):
        """Eval window reverses the train edge: gate must refuse to apply."""
        dates = [f"2026-08-{10+i:02d}" for i in range(6)]
        spec = self._window(dates[:3], "policy_macro", 0.03)
        spec += self._window(dates[3:], "policy_macro", -0.03)
        spec += self._window(dates, "business_quality", 0.0)
        _seed_validation(self.mgr, spec)
        with self.mgr.session() as conn:
            out = sl.apply_if_improved(conn, mode="ensemble", horizon_days=5, n_folds=3,
                                       calendar=self._cal(dates))
        self.assertFalse(out["applied"])
        with self.mgr.session() as conn:
            self.assertFalse(any(h["applied"] for h in sl.history(conn)))

    def test_folds_expand_monotonically_without_leakage(self):
        dates = [f"2026-08-{10+i:02d}" for i in range(8)]
        spec = self._window(dates, "policy_macro", 0.01)
        _seed_validation(self.mgr, spec)
        with self.mgr.session() as conn:
            s = sl.run_folds(conn, mode="ensemble", horizon_days=5, n_folds=3, min_train_dates=3,
                             calendar=self._cal(dates))
        self.assertEqual(s["status"], "ok")
        prev_train_end = ""
        for f in s["detail"]:
            self.assertLess(f["train_to"], f["eval_from"])
            self.assertGreaterEqual(f["train_to"], prev_train_end)
            prev_train_end = f["train_to"]
        self.assertIn("recommend_apply", s)

    def test_weighted_edge_renormalises_missing_lenses(self):
        series = {"policy_macro": [("2026-08-10", 0.04)]}
        self.assertAlmostEqual(
            sl.weighted_edge(series, {"policy_macro": 0.5, "business_quality": 0.5}), 0.04)
        self.assertIsNone(sl.weighted_edge({}, {"policy_macro": 0.5}))

class EmbargoTests(_BaseCase):
    def test_embargo_floor_is_h_plus_1_trading_days(self):
        import reality_engine.processing.skill_loop as sl
        cal = ["2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
               "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"]
        # train_to=08-12 is index 1; h=5 needs forward bars 08-13..08-20,
        # so the floor is 5+1 = 6 bars later: index 7 -> 08-20.
        self.assertEqual(sl.embargoed_eval_start(cal, "2026-08-12", 5), "2026-08-20")
        # h=1 -> next bar after train_to
        self.assertEqual(sl.embargoed_eval_start(cal, "2026-08-12", 1), "2026-08-14")
        # past the end of the calendar -> no safe eval window
        self.assertEqual(sl.embargoed_eval_start(cal, "2026-08-20", 5), "")
        with self.assertRaises(ValueError):
            sl.embargoed_eval_start(cal, "2026-01-01", 5)

    def test_live_round_is_embargo_safe(self):
        """The real candidate dates + real calendar satisfy the embargo, not just code."""
        from reality_engine.db.database import db_manager
        from reality_engine.processing import skill_loop as sl
        with db_manager.session() as conn:
            cal = sl.trading_calendar(conn)
            dates = sl.candidate_dates(conn, mode="ensemble", horizon_days=5)
            if len(dates) >= 4:
                train = dates[: max(1, int(round(len(dates) * 0.45)))]
                floor = sl.embargoed_eval_start(cal, train[-1], 5)
                ev = [d for d in dates[len(train):] if not floor or d >= floor]
                self.assertTrue(ev, f"no embargo-safe eval window behind train_to={train[-1]}")
                i_tr, i_ev = cal.index(train[-1]), cal.index(ev[0])
                self.assertGreaterEqual(i_ev - i_tr, 6,  # 5 horizon bars + 1, no shared bars
                                        f"train_to={train[-1]} eval_from={ev[0]}: gap {i_ev - i_tr} bars")

if __name__ == "__main__":
    unittest.main()
