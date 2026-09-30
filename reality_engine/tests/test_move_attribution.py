"""
Slice 1 tests — Move attribution ledger (hermetic temp-DB precedent:
test_ensemble_ranker.py / test_eod_corrector.py setUp with tempfile).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.ensemble_ranker import EnsembleRanker
from reality_engine.processing.move_attributor import (
    LENS_FAMILIES,
    attribute_move,
    attribute_universe,
    ensure_move_attribution_schema,
)


def _insert_company(conn, symbol, isin, nifty200=1):
    conn.execute(
        """
        INSERT OR REPLACE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector, is_nifty200, is_active)
        VALUES (?, ?, ?, 'Industrials', 'Capital Goods', ?, 1)
        """,
        (isin, symbol, f"{symbol} Ltd", nifty200),
    )


def _insert_price(conn, symbol, isin, date, prev_close, close, turnover=200.0, volume=100000):
    change = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_price_delivery
            (date, symbol, isin, series, open, high, low, close, prev_close, change_pct,
             total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct,
             delivery_spike_ratio, rsi_14)
        VALUES (?, ?, ?, 'EQ', ?, ?, ?, ?, ?, ?, ?, ?, 100, ?, 50.0, 1.0, 50.0)
        """,
        (date, symbol, isin, close * 0.99, close * 1.01, close, close, prev_close, change,
         int(volume), float(turnover), int(volume * 0.5)),
    )


def _insert_moat(conn, symbol, score=4.0, trajectory="Expanding"):
    conn.execute(
        """
        INSERT OR REPLACE INTO moat_evaluations
            (company_id, ticker, total_moat_score, moat_trajectory)
        VALUES ((SELECT rowid FROM master_companies WHERE nse_symbol=?), ?, ?, ?)
        """,
        (symbol, symbol, float(score), trajectory),
    )


def _insert_financial(conn, symbol, isin, company_id=1, fiscal_year=2025):
    conn.execute(
        """
        INSERT OR REPLACE INTO financial_metrics
            (company_id, isin, symbol, fiscal_year, roic, wacc,
             roic_wacc_spread, fcf_margin, debt_to_ebitda, gross_margin_peer_percentile)
        VALUES (?, ?, ?, ?, 0.15, 0.10, 0.05, 0.12, 1.0, 70)
        """,
        (company_id, isin, symbol, fiscal_year),
    )


def _seed_rankings(ranker, symbol):
    ranker.upsert_ranking(symbol, None, None, None, "all", "factor_statistical", 0.01, 0.30)
    ranker.upsert_ranking(symbol, None, None, None, "all", "business_quality", 0.04, 0.25)
    ranker.upsert_ranking(symbol, None, None, None, "all", "policy_macro", 0.20, 0.25)
    ranker.upsert_ranking(symbol, None, None, None, "all", "supply_chain", 0.10, 0.20)


def _row_for(mgr, symbol, date):
    with mgr.session() as conn:
        r = conn.execute(
            "SELECT * FROM move_attribution WHERE symbol=? AND attribution_date=?",
            (symbol, date),
        ).fetchone()
        return dict(r) if r else None


class MoveAttributionTestBase(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))  # runs schema.sql
        self.repo = Repository(self.mgr)
        self.repo.ensure_eod_corrector_schema(self.mgr)
        self.repo.ensure_ensemble_ranking_schema(self.mgr)
        self.repo.ensure_moat_schema(self.mgr)
        self.repo.ensure_financial_metrics_schema(self.mgr)
        self.repo.ensure_regulatory_political_risks_schema(self.mgr)
        self.repo.ensure_substrate_history_schema(self.mgr)
        ensure_move_attribution_schema(self.mgr)
        self.ranker = EnsembleRanker(self.mgr)

    def tearDown(self):
        try:
            os.unlink(self._fh.name)
        except OSError:
            pass


class TestMoveAttributionSchema(MoveAttributionTestBase):
    def test_exact_columns_and_index(self):
        expected = [
            "attribution_id",
            "symbol",
            "attribution_date",
            "realized_move_pct",
            "noise_floor",
            "is_material",
            "explained_total",
            "residual",
            "lens_factor_statistical_dir",
            "lens_business_quality_dir",
            "lens_policy_macro_dir",
            "lens_supply_chain_dir",
            "lens_factor_statistical_w",
            "lens_business_quality_w",
            "lens_policy_macro_w",
            "lens_supply_chain_w",
            "lens_factor_statistical_share",
            "lens_business_quality_share",
            "lens_policy_macro_share",
            "lens_supply_chain_share",
            "investor_majority",
            "regime_tag",
        ]
        with self.mgr.session() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info('move_attribution')").fetchall()]
            self.assertEqual(cols, expected)
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='move_attribution'"
            ).fetchone()[0]
            self.assertIn("UNIQUE(symbol, attribution_date)", ddl.replace("  ", " "))
            self.assertIn("DEFAULT 'all'", ddl)
            self.assertIn("DEFAULT '*'", ddl)
            idx = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_move_attrib_date'"
            ).fetchone()
            self.assertIsNotNone(idx)
            self.assertIn("attribution_date", idx[0])
        # Idempotent.
        ensure_move_attribution_schema(self.mgr)

    def test_lens_families_mirror(self):
        self.assertEqual(
            tuple(LENS_FAMILIES),
            ("factor_statistical", "business_quality", "policy_macro", "supply_chain"),
        )


class TestAttributeMove(MoveAttributionTestBase):
    def test_explained_bounds_and_share_sum(self):
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
            _insert_price(conn, sym, "INEH", "2026-08-26", 100.0, 98.0, turnover=300.0)
            _insert_price(conn, sym, "INEH", "2026-08-27", 98.0, 102.0, turnover=300.0)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEH")
        _seed_rankings(self.ranker, sym)

        out = attribute_move(sym, "2026-08-27", manager=self.mgr)
        self.assertGreaterEqual(out["explained_total"], 0.0)
        self.assertLessEqual(out["explained_total"], 1.0)
        shares = [
            out["lens_factor_statistical_share"],
            out["lens_business_quality_share"],
            out["lens_policy_macro_share"],
            out["lens_supply_chain_share"],
        ]
        self.assertAlmostEqual(sum(shares), out["explained_total"], places=9)
        self.assertAlmostEqual(out["residual"], 1.0 - out["explained_total"], places=9)
        # v1 predictor-honesty rule (levels gate, flows vote): the dated quality
        # predictor returns 0 on the static moat fixture (moat 4.0 is state, not
        # news), so its directional share is 0 despite matching level
        # semantics; factor predicted -1 (prior-day down) so its share is 0 too.
        self.assertEqual(out["lens_business_quality_dir"], 0)
        self.assertAlmostEqual(out["lens_business_quality_share"], 0.0, places=9)
        self.assertEqual(out["lens_factor_statistical_share"], 0.0)
        # Persisted row matches the returned dict.
        row = _row_for(self.mgr, sym, "2026-08-27")
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["explained_total"], out["explained_total"], places=9)
        self.assertAlmostEqual(row["realized_move_pct"], (102.0 - 98.0) / 98.0 * 100.0, places=6)

    def test_immaterial_flagged_not_skipped(self):
        sym = "INFY"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEI", 1)
            _insert_price(conn, sym, "INEI", "2026-08-27", 100.0, 100.5, turnover=200.0)
            _insert_moat(conn, sym, score=2.0, trajectory="Stable")
            _insert_financial(conn, sym, "INEI")
        out = attribute_move(sym, "2026-08-27", manager=self.mgr)
        # 0.5% move vs 2.0 fallback floor (sparse history) -> immaterial, but stored.
        self.assertEqual(out["is_material"], 0)
        row = _row_for(self.mgr, sym, "2026-08-27")
        self.assertIsNotNone(row)
        self.assertEqual(row["is_material"], 0)
        self.assertGreaterEqual(row["explained_total"], 0.0)
        self.assertLessEqual(row["explained_total"], 1.0)

    def test_realized_prefers_close_to_close_over_change_pct(self):
        sym = "TCS"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INET", 1)
            _insert_price(conn, sym, "INET", "2026-08-27", 100.0, 102.0, turnover=200.0)
            conn.execute(
                "UPDATE daily_price_delivery SET change_pct = 99.9 WHERE symbol=? AND date=?",
                (sym, "2026-08-27"),
            )
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INET")
        out = attribute_move(sym, "2026-08-27", manager=self.mgr)
        self.assertAlmostEqual(out["realized_move_pct"], 2.0, places=6)

    def test_regime_investor_defaults(self):
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
            _insert_price(conn, sym, "INEH", "2026-08-27", 100.0, 102.0, turnover=200.0)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEH")
        out = attribute_move(sym, "2026-08-27", manager=self.mgr)
        self.assertEqual(out["investor_majority"], "all")
        self.assertEqual(out["regime_tag"], "*")
        row = _row_for(self.mgr, sym, "2026-08-27")
        self.assertEqual(row["investor_majority"], "all")
        self.assertEqual(row["regime_tag"], "*")

    def test_investor_forensic_holdings_max(self):
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
            _insert_price(conn, sym, "INEH", "2026-08-27", 100.0, 102.0, turnover=200.0)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEH")
            conn.execute(
                """
                INSERT OR REPLACE INTO company_forensic_health
                    (isin, symbol, fiscal_year, promoter_holding_pct,
                     fii_holding_pct, dii_holding_pct, public_holding_pct,
                     last_evaluated_date)
                VALUES (?, ?, 'FY26', 10.0, 40.0, 20.0, 30.0, '2026-08-27')
                """,
                ("INEH", sym),
            )
        out = attribute_move(sym, "2026-08-27", manager=self.mgr)
        self.assertEqual(out["investor_majority"], "FII")

    def test_missing_eod_row_raises(self):
        with self.assertRaises(ValueError):
            attribute_move("NOPE", "2026-08-27", manager=self.mgr)

    def test_upsert_idempotent(self):
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
            _insert_price(conn, sym, "INEH", "2026-08-27", 100.0, 102.0, turnover=200.0)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEH")
        attribute_move(sym, "2026-08-27", manager=self.mgr)
        attribute_move(sym, "2026-08-27", manager=self.mgr)
        with self.mgr.session() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM move_attribution WHERE symbol=? AND attribution_date=?",
                (sym, "2026-08-27"),
            ).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_low_vol_two_pct_move_is_material(self):
        sym = "LOWVOL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEL", 1)
            # ~±0.5% daily σ history: 10 alternating ±0.5% sessions.
            px = 100.0
            for i in range(10):
                prev, px = px, px * (1.005 if i % 2 == 0 else 0.995)
                _insert_price(conn, sym, "INEL", f"2026-08-{10 + i:02d}", prev, px)
            # ~2% up move on the attribution date.
            _insert_price(conn, sym, "INEL", "2026-08-20", px, px * 1.02)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEL")
        out = attribute_move(sym, "2026-08-20", manager=self.mgr)
        self.assertAlmostEqual(out["realized_move_pct"], 2.0, places=6)
        self.assertGreaterEqual(out["noise_floor"], 0.5)
        self.assertLessEqual(out["noise_floor"], 8.0)
        self.assertEqual(out["is_material"], 1)

    def test_small_move_immaterial_but_stored(self):
        sym = "LOWVOL2"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEM", 1)
            px = 100.0
            for i in range(10):
                prev, px = px, px * (1.005 if i % 2 == 0 else 0.995)
                _insert_price(conn, sym, "INEM", f"2026-08-{10 + i:02d}", prev, px)
            _insert_price(conn, sym, "INEM", "2026-08-20", px, px * 1.002)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEM")
        out = attribute_move(sym, "2026-08-20", manager=self.mgr)
        self.assertAlmostEqual(out["realized_move_pct"], 0.2, places=6)
        self.assertGreaterEqual(out["noise_floor"], 0.5)
        self.assertLessEqual(out["noise_floor"], 8.0)
        self.assertEqual(out["is_material"], 0)
        row = _row_for(self.mgr, sym, "2026-08-20")
        self.assertIsNotNone(row)
        self.assertEqual(row["is_material"], 0)

    def test_sparse_history_falls_back_to_two(self):
        sym = "THIN"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEN", 1)
            _insert_price(conn, sym, "INEN", "2026-08-27", 100.0, 103.0, turnover=200.0)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEN")
        out = attribute_move(sym, "2026-08-27", manager=self.mgr)
        self.assertAlmostEqual(out["noise_floor"], 2.0, places=9)
        self.assertEqual(out["is_material"], 1)

    def test_explained_math_unchanged_under_new_floor(self):
        sym = "HAL"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, "INEH", 1)
            px = 100.0
            for i in range(10):
                prev, px = px, px * (1.005 if i % 2 == 0 else 0.995)
                _insert_price(conn, sym, "INEH", f"2026-08-{10 + i:02d}", prev, px)
            _insert_price(conn, sym, "INEH", "2026-08-20", px, px * 1.02)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, "INEH")
        _seed_rankings(self.ranker, sym)
        out = attribute_move(sym, "2026-08-20", manager=self.mgr)
        shares = [
            out["lens_factor_statistical_share"],
            out["lens_business_quality_share"],
            out["lens_policy_macro_share"],
            out["lens_supply_chain_share"],
        ]
        self.assertAlmostEqual(sum(shares), out["explained_total"], places=9)
        self.assertAlmostEqual(out["residual"], 1.0 - out["explained_total"], places=9)
        self.assertGreaterEqual(out["explained_total"], 0.0)
        self.assertLessEqual(out["explained_total"], 1.0)


class TestAttributeUniverse(MoveAttributionTestBase):
    def test_universe_summary_sane(self):
        for sym, isin in (("AAA", "INEA"), ("BBB", "INEB")):
            with self.mgr.session() as conn:
                _insert_company(conn, sym, isin, 1)
                _insert_price(conn, sym, isin, "2026-08-26", 100.0, 101.0, turnover=200.0)
                _insert_price(conn, sym, isin, "2026-08-27", 101.0, 101.5, turnover=200.0)
                _insert_moat(conn, sym, score=4.0)
                _insert_financial(conn, sym, isin)
            _seed_rankings(self.ranker, sym)

        res = attribute_universe(universe=["AAA", "BBB"], days=2, manager=self.mgr)
        self.assertEqual(res["symbols"], ["AAA", "BBB"])
        self.assertEqual(res["dates"], ["2026-08-26", "2026-08-27"])
        self.assertEqual(res["rows_written"], 4)
        self.assertGreaterEqual(res["median_residual"], 0.0)
        self.assertLessEqual(res["median_residual"], 1.0)
        self.assertGreaterEqual(res["material_count"], 0)

        with self.mgr.session() as conn:
            rows = conn.execute("SELECT * FROM move_attribution").fetchall()
        self.assertEqual(len(rows), 4)
        for r in rows:
            d = dict(r)
            self.assertGreaterEqual(d["explained_total"], 0.0)
            self.assertLessEqual(d["explained_total"], 1.0)
            share_sum = (
                d["lens_factor_statistical_share"]
                + d["lens_business_quality_share"]
                + d["lens_policy_macro_share"]
                + d["lens_supply_chain_share"]
            )
            self.assertAlmostEqual(share_sum, d["explained_total"], places=9)
            self.assertAlmostEqual(d["residual"], 1.0 - d["explained_total"], places=9)
            self.assertEqual(d["regime_tag"], "*")
            self.assertEqual(d["investor_majority"], "all")

    def test_empty_universe_guards(self):
        res = attribute_universe(universe=[], days=5, manager=self.mgr)
        self.assertEqual(res["rows_written"], 0)
        self.assertEqual(res["median_residual"], 0.0)
        self.assertEqual(res["material_count"], 0)


class TestSubstrateVersioning(MoveAttributionTestBase):
    """P0b peers-speak: additive history beside live levels; deltas vote, levels gate."""

    def test_history_tables_exist_beside_live_levels(self):
        self.repo.ensure_ripple_effects_schema(self.mgr)
        with self.mgr.session() as conn:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for t in ("moat_history", "policy_eni_history", "ripple_history",
                  "moat_evaluations", "regulatory_political_risks", "ripple_effects"):
            self.assertIn(t, names)
        with self.mgr.session() as conn:
            before = conn.execute("SELECT COUNT(*) AS n FROM moat_history WHERE symbol='HAL'").fetchone()["n"]
        self.repo.upsert_moat_evaluation(
            ticker="HAL", switching_costs=5, network_effects=5, cost_advantage=5,
            intangible_assets=5, efficient_scale=5, moat_trajectory="Expanding", isin="INEH")
        with self.mgr.session() as conn:
            rows = conn.execute("SELECT * FROM moat_history WHERE symbol='HAL'").fetchall()
        # Same-day second upsert collapses to latest; live level row is one row.
        self.assertGreaterEqual(len(rows), 1)
        self.assertLessEqual(len(rows), int(before) + 1)
        with self.mgr.session() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM moat_evaluations WHERE ticker='HAL'").fetchone()["n"]
        self.assertEqual(n, 1)
        latest = max(dict(r)["moat_score"] for r in rows)
        self.assertAlmostEqual(float(latest), 5.0, places=9)

    def test_quality_delta_votes_upgrade_downgrade_flat(self):
        from reality_engine.processing.eod_corrector import EODCorrector
        sym, isin = "HAL", "INEH"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, isin, 1)
        self.repo.upsert_moat_evaluation(
            ticker=sym, switching_costs=2, network_effects=2, cost_advantage=2,
            intangible_assets=2, efficient_scale=2, moat_trajectory="Stable", isin=isin)
        with self.mgr.session() as conn:
            conn.execute("UPDATE moat_history SET asof_date='2026-08-20' WHERE symbol=?", (sym,))
        self.repo.upsert_moat_evaluation(
            ticker=sym, switching_costs=5, network_effects=5, cost_advantage=5,
            intangible_assets=5, efficient_scale=5, moat_trajectory="Expanding", isin=isin)
        with self.mgr.session() as conn:
            conn.execute("UPDATE moat_history SET asof_date='2026-08-26' WHERE symbol=? AND moat_score >= 4.5", (sym,))
        c = EODCorrector(self.mgr)
        self.assertEqual(c._predict_quality(sym, "2026-08-27"), 1)
        self.assertEqual(c._predict_quality(sym), 1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM moat_history WHERE symbol=? AND asof_date='2026-08-26'", (sym,))
            conn.execute("INSERT INTO moat_history (symbol, asof_date, moat_score, moat_width, trajectory, source) "
                         "VALUES (?, '2026-08-26', 2.0, 'None', 'Stable', 'test')", (sym,))
            conn.execute("INSERT INTO moat_history (symbol, asof_date, moat_score, moat_width, trajectory, source) "
                         "VALUES (?, '2026-08-28', 1.0, 'None', 'Deteriorating', 'test')", (sym,))
        self.assertEqual(c._predict_quality(sym, "2026-08-28"), -1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM moat_history WHERE symbol=? AND asof_date='2026-08-28'", (sym,))
            conn.execute("INSERT INTO moat_history (symbol, asof_date, moat_score, moat_width, trajectory, source) "
                         "VALUES (?, '2026-08-28', 2.0, 'None', 'Stable', 'test')", (sym,))
        self.assertEqual(c._predict_quality(sym, "2026-08-28"), 0)

    def test_policy_delta_votes_upgrade_downgrade_flat(self):
        from reality_engine.processing.eod_corrector import EODCorrector
        sym = "HAL"
        self.repo.upsert_regulatory_political_risk(
            symbol=sym, policy_name="POLICY_A", severity_score=1.0, probability=0.5, coverage_status="mapped")
        with self.mgr.session() as conn:
            conn.execute("UPDATE policy_eni_history SET asof_date='2026-08-20' WHERE symbol=?", (sym,))
        self.repo.upsert_regulatory_political_risk(
            symbol=sym, policy_name="POLICY_A", severity_score=4.0, probability=0.9, coverage_status="mapped")
        with self.mgr.session() as conn:
            conn.execute("UPDATE policy_eni_history SET asof_date='2026-08-26' WHERE symbol=? AND net_impact_score > 1.0", (sym,))
        c = EODCorrector(self.mgr)
        self.assertEqual(c._predict_policy(sym, "2026-08-27"), 1)
        self.assertEqual(c._predict_policy(sym), 1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM policy_eni_history WHERE symbol=? AND asof_date='2026-08-26'", (sym,))
            conn.execute("INSERT INTO policy_eni_history (symbol, policy_name, asof_date, net_impact_score, severity, source) "
                         "VALUES (?, 'POLICY_A', '2026-08-26', 3.6, 4.0, 'test')", (sym,))
            conn.execute("INSERT INTO policy_eni_history (symbol, policy_name, asof_date, net_impact_score, severity, source) "
                         "VALUES (?, 'POLICY_A', '2026-08-28', -3.6, -4.0, 'test')", (sym,))
        self.assertEqual(c._predict_policy(sym, "2026-08-28"), -1)
        with self.mgr.session() as conn:
            conn.execute("DELETE FROM policy_eni_history WHERE symbol=? AND asof_date='2026-08-28'", (sym,))
            conn.execute("INSERT INTO policy_eni_history (symbol, policy_name, asof_date, net_impact_score, severity, source) "
                         "VALUES (?, 'POLICY_A', '2026-08-28', 3.6, 4.0, 'test')", (sym,))
        self.assertEqual(c._predict_policy(sym, "2026-08-28"), 0)
        with self.mgr.session() as conn:
            before = conn.execute("SELECT COUNT(*) AS n FROM policy_eni_history").fetchone()["n"]
        self.repo.upsert_regulatory_political_risk(
            symbol="COV", policy_name="__NO_POLICY_TEMPLATE__", severity_score=None,
            probability=None, net_impact_score=None, coverage_status="no_template")
        with self.mgr.session() as conn:
            after = conn.execute("SELECT COUNT(*) AS n FROM policy_eni_history").fetchone()["n"]
        self.assertEqual(before, after)

    def test_levels_still_gate_share_zero_from_levels(self):
        # Standing high-moat / positive-ENI / high-significance levels with no
        # dated history must not carry directional share: quality/policy/supply
        # dirs are 0 even though legacy undated levels would vote +1.
        from reality_engine.processing.eod_corrector import EODCorrector
        sym, isin = "GATE", "INEG"
        with self.mgr.session() as conn:
            _insert_company(conn, sym, isin, 1)
            _insert_price(conn, sym, isin, "2026-08-26", 100.0, 98.0, turnover=300.0)
            _insert_price(conn, sym, isin, "2026-08-27", 98.0, 102.0, turnover=300.0)
            _insert_moat(conn, sym, score=4.0)
            _insert_financial(conn, sym, isin)
        _seed_rankings(self.ranker, sym)
        c = EODCorrector(self.mgr)
        self.assertEqual(c._predict_quality(sym), 1)
        self.assertEqual(c._predict_quality(sym, "2026-08-27"), 0)
        out = attribute_move(sym, "2026-08-27", manager=self.mgr)
        self.assertEqual(out["lens_business_quality_dir"], 0)
        self.assertAlmostEqual(out["lens_business_quality_share"], 0.0, places=9)
        self.assertEqual(out["lens_policy_macro_dir"], 0)
        self.assertAlmostEqual(out["lens_policy_macro_share"], 0.0, places=9)

    def test_legacy_undated_path_unchanged(self):
        from reality_engine.processing.eod_corrector import EODCorrector
        sym = "HAL"
        self.repo.upsert_moat_evaluation(
            ticker=sym, switching_costs=5, network_effects=5, cost_advantage=5,
            intangible_assets=5, efficient_scale=5, moat_trajectory="Stable", isin="INEH")
        c = EODCorrector(self.mgr)
        self.assertEqual(c._predict_quality(sym, None), 1)
        self.repo.upsert_regulatory_political_risk(
            symbol=sym, policy_name="POLICY_A", severity_score=2.0, probability=0.9, coverage_status="mapped")
        self.assertEqual(c._predict_policy(sym, None), 1)

    def test_cross_day_revisions_accumulate_and_vote(self):
        # Two genuine revisions on different dates via the writers (no manual
        # UPDATE of asof_date): history gains two dated rows and the dated
        # predictors vote the delta. Same-day same-content rewrites collapse.
        from reality_engine.processing.eod_corrector import EODCorrector
        c = EODCorrector(self.mgr)
        self.repo.upsert_moat_evaluation(
            ticker="CROSSM", switching_costs=2, network_effects=2, cost_advantage=2,
            intangible_assets=2, efficient_scale=2, moat_trajectory="Stable",
            isin="INEX", asof_date="2026-08-20")
        self.repo.upsert_moat_evaluation(
            ticker="CROSSM", switching_costs=2, network_effects=2, cost_advantage=2,
            intangible_assets=2, efficient_scale=2, moat_trajectory="Stable",
            isin="INEX", asof_date="2026-08-20")
        self.repo.upsert_moat_evaluation(
            ticker="CROSSM", switching_costs=5, network_effects=5, cost_advantage=5,
            intangible_assets=5, efficient_scale=5, moat_trajectory="Expanding",
            isin="INEX", asof_date="2026-08-26")
        with self.mgr.session() as conn:
            mrows = conn.execute(
                "SELECT asof_date, moat_score FROM moat_history WHERE symbol='CROSSM' ORDER BY asof_date").fetchall()
        self.assertEqual(len(mrows), 2)
        self.assertEqual([r["asof_date"] for r in mrows], ["2026-08-20", "2026-08-26"])
        self.assertGreater(float(mrows[1]["moat_score"]) - float(mrows[0]["moat_score"]), 0.0)
        self.assertEqual(c._predict_quality("CROSSM", "2026-08-27"), 1)
        self.repo.upsert_regulatory_political_risk(
            symbol="CROSSP", policy_name="POLICY_A", severity_score=1.0,
            probability=0.5, coverage_status="mapped", asof_date="2026-08-20")
        self.repo.upsert_regulatory_political_risk(
            symbol="CROSSP", policy_name="POLICY_A", severity_score=1.0,
            probability=0.5, coverage_status="mapped", asof_date="2026-08-20")
        self.repo.upsert_regulatory_political_risk(
            symbol="CROSSP", policy_name="POLICY_A", severity_score=4.0,
            probability=0.9, coverage_status="mapped", asof_date="2026-08-26")
        with self.mgr.session() as conn:
            prows = conn.execute(
                "SELECT asof_date, net_impact_score FROM policy_eni_history WHERE symbol='CROSSP' ORDER BY asof_date").fetchall()
        self.assertEqual(len(prows), 2)
        self.assertEqual([r["asof_date"] for r in prows], ["2026-08-20", "2026-08-26"])
        self.assertGreater(float(prows[1]["net_impact_score"]) - float(prows[0]["net_impact_score"]), 0.0)
        self.assertEqual(c._predict_policy("CROSSP", "2026-08-27"), 1)

if __name__ == "__main__":
    unittest.main()
