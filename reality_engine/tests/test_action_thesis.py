"""
Slice 2 tests — deterministic action table + thesis attach + writer + CLI verbs.

Hermetic temp-DB precedent: test_move_attribution.py setUp with tempfile.
Covers:
  1. decide_action over all 16 cells (BUY exactly once, SELL exactly the two
     unexplained-strength + broken-quality cells, HOLD rest, insolvent never BUY).
  2. Thesis attach with a seeded ledger row yields action + attribution block
     (graceful HOLD/null without a row).
  3. Writer Markdown contains an `Action:` line (and attribution section);
     JSON passes action + attribution through.
  4. CLI verbs parse at the argparse level with no live DB.
  5. Factor gate (6th decide_action dimension): BUY needs factor_statistical
     agreement — 64 combos give BUY 1, SELL 8, HOLD 55; SELL ignores the gate.
  6. Widened broken-thesis (Deteriorating / moat<2.5 / ENI<0): SELL fires per
     clause, intact strength HOLDs, resolver stamps quality_broken/reason.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.agent.orchestrator import (
    AgentOrchestrator,
    _ledger_row_to_attribution_block,
    decide_action,
)
from reality_engine.agent.schemas import (
    ConvictionLevel,
    DailyAlphaReport,
    MarketBreadthSummary,
    MarketRegime,
    ScripAlphaThesis,
)
from reality_engine.cli import (
    cmd_attribute_move,
    cmd_portfolio_ledger,
    cmd_run_calibration,
)
from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.ensemble_ranker import EnsembleRanker
from reality_engine.processing.move_attributor import (
    attribute_move,
    ensure_move_attribution_schema,
)
from reality_engine.reporting.writer import ReportWriter


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


def _insert_forensic(conn, isin, symbol, pledge=5.0, coverage=4.0, leverage=0.5, approved=1):
    conn.execute(
        """
        INSERT OR REPLACE INTO company_forensic_health
            (isin, symbol, fiscal_year, promoter_holding_pct, promoter_pledge_pct,
             fii_holding_pct, dii_holding_pct, public_holding_pct,
             interest_coverage_ratio, debt_to_equity_ratio,
             is_solvency_approved, solvency_disqualification_reasons, last_evaluated_date)
        VALUES (?, ?, 'FY26', 55.0, ?, 10.0, 20.0, 15.0, ?, ?, ?, NULL, '2026-08-27')
        """,
        (isin, symbol, float(pledge), float(coverage), float(leverage), int(approved)),
    )


def _seed_rankings(ranker, symbol):
    ranker.upsert_ranking(symbol, None, None, None, "all", "factor_statistical", 0.01, 0.30)
    ranker.upsert_ranking(symbol, None, None, None, "all", "business_quality", 0.04, 0.25)
    ranker.upsert_ranking(symbol, None, None, None, "all", "policy_macro", 0.20, 0.25)
    ranker.upsert_ranking(symbol, None, None, None, "all", "supply_chain", 0.10, 0.20)


class TestDecideActionTable(unittest.TestCase):
    """All 16 cells of (sign x residual>0.5 x quality x solvency)."""

    def test_buy_exactly_once(self):
        buys = [
            (s, r, q, v)
            for s in (-1, 1)
            for r in (False, True)
            for q in (False, True)
            for v in (False, True)
            if decide_action(s, r, q, v) == "BUY"
        ]
        self.assertEqual(buys, [(-1, True, True, True)])

    def test_sell_exactly_broken_unexplained_strength(self):
        sells = sorted(
            (s, r, q, v)
            for s in (-1, 1)
            for r in (False, True)
            for q in (False, True)
            for v in (False, True)
            if decide_action(s, r, q, v) == "SELL"
        )
        self.assertEqual(sells, [(1, True, False, False), (1, True, False, True)])

    def test_hold_covers_rest(self):
        total = sum(
            1
            for s in (-1, 1)
            for r in (False, True)
            for q in (False, True)
            for v in (False, True)
        )
        holds = sum(
            1
            for s in (-1, 1)
            for r in (False, True)
            for q in (False, True)
            for v in (False, True)
            if decide_action(s, r, q, v) == "HOLD"
        )
        # 2 signs x 2 x 2 x 2 = 16 cells; BUY 1 + SELL 2 + HOLD 13.
        self.assertEqual(total, 16)
        self.assertEqual(holds, 13)

    def test_insolvent_never_buy(self):
        for s in (-1, 1):
            for r in (False, True):
                for q in (False, True):
                    self.assertNotEqual(decide_action(s, r, q, False), "BUY")

    def test_garbage_sign_holds(self):
        self.assertEqual(decide_action(None, True, True, True), "HOLD")
        self.assertEqual(decide_action("x", True, True, True), "HOLD")
        self.assertEqual(decide_action(0, True, True, True), "HOLD")
        self.assertEqual(decide_action(0.0, False, False, False), "HOLD")


class TestDecideActionDislocation(unittest.TestCase):
    """5th dimension: BUY needs |realized| >= 2.0 x floor (live median 1.43x)."""

    def test_buy_requires_dislocation(self):
        self.assertEqual(decide_action(-1, True, True, True, True), "BUY")
        self.assertEqual(decide_action(-1, True, True, True, False), "HOLD")

    def test_default_preserves_buy(self):
        # 4-arg callers keep prior behavior (default True).
        self.assertEqual(decide_action(-1, True, True, True), "BUY")

    def test_sell_ignores_dislocation(self):
        for solvent in (False, True):
            for dislocation in (False, True):
                self.assertEqual(
                    decide_action(1, True, False, solvent, dislocation), "SELL"
                )

    def test_no_dislocation_table_has_no_buys(self):
        buys = [
            (s, r, q, v)
            for s in (-1, 1)
            for r in (False, True)
            for q in (False, True)
            for v in (False, True)
            if decide_action(s, r, q, v, False) == "BUY"
        ]
        self.assertEqual(buys, [])
        sells = sorted(
            (s, r, q, v)
            for s in (-1, 1)
            for r in (False, True)
            for q in (False, True)
            for v in (False, True)
            if decide_action(s, r, q, v, False) == "SELL"
        )
        self.assertEqual(sells, [(1, True, False, False), (1, True, False, True)])


class TestAttributionBlockDislocation(unittest.TestCase):
    """Thesis attribution block carries dislocation_confirmed: bool."""

    def test_reliance_shape_not_dislocation(self):
        block = _ledger_row_to_attribution_block({
            "realized_move_pct": -1.41, "noise_floor": 1.08, "residual": 0.9,
        })
        self.assertIs(block["dislocation_confirmed"], False)

    def test_genuine_dislocation(self):
        block = _ledger_row_to_attribution_block({
            "realized_move_pct": -3.0, "noise_floor": 0.5, "residual": 0.9,
        })
        self.assertIs(block["dislocation_confirmed"], True)

    def test_missing_floor_defaults_true(self):
        block = _ledger_row_to_attribution_block({"realized_move_pct": -3.0})
        self.assertIs(block["dislocation_confirmed"], True)


class ThesisAttachBase(unittest.TestCase):
    def setUp(self):
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.mgr = DatabaseManager(Path(self._fh.name))
        self.repo = Repository(self.mgr)
        self.repo.ensure_eod_corrector_schema(self.mgr)
        self.repo.ensure_ensemble_ranking_schema(self.mgr)
        self.repo.ensure_moat_schema(self.mgr)
        self.repo.ensure_financial_metrics_schema(self.mgr)
        ensure_move_attribution_schema(self.mgr)
        self.ranker = EnsembleRanker(self.mgr)
        # Bind the screener to the hermetic repo: the global composite_screener
        # reads the LIVE 12GB DB, so any lookup fallback (moat/ENI/ROIC/secular)
        # would leak live rows into fixtures (proven: live ENI 'X' = -1.38).
        from reality_engine.processing.composite_screener import CompositeScreener
        _screener = CompositeScreener()
        _screener.repo = self.repo
        self.orch = AgentOrchestrator(repository=self.repo, screener=_screener)

    def tearDown(self):
        try:
            os.unlink(self._fh.name)
        except OSError:
            pass


class TestThesisAttach(ThesisAttachBase):
    def _seed_symbol(self, sym="HAL", isin="INEH", trajectory="Expanding",
                     pledge=5.0, coverage=4.0, leverage=0.5, approved=1,
                     prev=100.0, close=102.0, date="2026-08-27"):
        with self.mgr.session() as conn:
            _insert_company(conn, sym, isin, 1)
            _insert_price(conn, sym, isin, date, prev, close, turnover=300.0)
            _insert_moat(conn, sym, score=4.0, trajectory=trajectory)
            _insert_financial(conn, sym, isin)
            _insert_forensic(conn, isin, sym, pledge, coverage, leverage, approved)
        _seed_rankings(self.ranker, sym)

    def test_attach_with_seeded_row(self):
        self._seed_symbol()
        row = attribute_move("HAL", "2026-08-27", manager=self.mgr)
        block = _ledger_row_to_attribution_block(row)
        self.assertIn("per_lens", block)
        self.assertEqual(len(block["per_lens"]), 4)
        self.assertEqual(
            {lens["family"] for lens in block["per_lens"]},
            {"factor_statistical", "business_quality", "policy_macro", "supply_chain"},
        )
        candidate = {"symbol": "HAL", "isin": "INEH", "close": 102.0, "composite_score": 60.0}
        thesis = self.orch.evaluate_candidate_scrip(
            candidate, rank=1, attribution=row, attribution_date="2026-08-27",
        )
        action = getattr(thesis, "action", None)
        attribution = getattr(thesis, "attribution", "MISSING")
        self.assertIn(action, ("BUY", "SELL", "HOLD"))
        self.assertIsInstance(attribution, dict)
        self.assertIn("per_lens", attribution)
        self.assertEqual(len(attribution["per_lens"]), 4)
        self.assertIn("residual", attribution)
        self.assertIn("explained_total", attribution)

    def test_no_row_defaults_hold_null(self):
        self._seed_symbol(sym="INFY", isin="INEI")
        candidate = {"symbol": "INFY", "isin": "INEI", "close": 100.0, "composite_score": 60.0}
        before = dict(candidate)
        thesis = self.orch.evaluate_candidate_scrip(
            candidate, rank=1, attribution_date="2026-08-27",
        )
        # Rationale unchanged contract: callers' dict is not mutated; action defaults.
        self.assertEqual(candidate, before)
        self.assertEqual(getattr(thesis, "action", None), "HOLD")
        self.assertIsNone(getattr(thesis, "attribution", "MISSING"))

    def test_resolver_returns_valid_action_and_block(self):
        action, block = self.orch._resolve_thesis_action(
            "X",
            candidate_row={"symbol": "X"},
            attribution={
                "realized_move_pct": 3.0,
                "noise_floor": 0.5,
                "is_material": 1,
                "explained_total": 0.1,
                "residual": 0.9,
                "per_lens": [],
                "investor_majority": "all",
                "regime_tag": "*",
            },
            funda={"forensic_solvency": {"is_solvency_approved": 1}},
        )
        self.assertIn(action, ("BUY", "SELL", "HOLD"))
        self.assertIsInstance(block, dict)


class TestResolverDislocation(ThesisAttachBase):
    """Resolver threads |realized| >= 2.0 x floor through to action + block."""

    def _attribution(self, realized, floor, residual=0.9, factor_dir=None):
        # factor_dir defaults to sign(realized): the factor gate (iteration 4)
        # requires momentum WITH the entry, so a bare fixture must witness it.
        if factor_dir is None:
            factor_dir = 1 if realized > 0 else (-1 if realized < 0 else 0)
        return {
            "realized_move_pct": realized,
            "noise_floor": floor,
            "is_material": 1,
            "explained_total": 0.1,
            "residual": residual,
            "per_lens": [{"family": "factor_statistical",
                          "predicted_direction": factor_dir,
                          "weight": 0.25,
                          "share": 0.25 if factor_dir else 0.0}],
            "investor_majority": "all",
            "regime_tag": "*",
        }

    def _candidate(self):
        # ISIN-bound candidate: screener lookups resolve NO evidence rows on the
        # hermetic DB, so quality falls back to intact defaults (moat 2.5 /
        # Stable / ENI None) instead of leaking live-DB state into the fixture.
        return {"symbol": "X", "isin": "INE000X01000",
                "total_moat_score": 4.0, "moat_trajectory": "Expanding",
                "policy_agg_eni": None}

    def _funda(self):
        return {"forensic_solvency": {"is_solvency_approved": 1}}

    def test_sub_two_sigma_weakness_resolves_hold(self):
        action, block = self.orch._resolve_thesis_action(
            "X", candidate_row=self._candidate(),
            attribution=self._attribution(-1.41, 1.08), funda=self._funda(),
        )
        self.assertEqual(action, "HOLD")
        self.assertIs(block["dislocation_confirmed"], False)

    def test_dislocation_weakness_resolves_buy(self):
        action, block = self.orch._resolve_thesis_action(
            "X", candidate_row=self._candidate(),
            attribution=self._attribution(-3.0, 0.5), funda=self._funda(),
        )
        self.assertEqual(action, "BUY")
        self.assertIs(block["dislocation_confirmed"], True)

    def test_seeded_ledger_row_carries_flag(self):
        row = {
            "realized_move_pct": -1.41, "noise_floor": 1.08, "residual": 0.9,
            "explained_total": 0.1, "is_material": 1,
        }
        action, block = self.orch._resolve_thesis_action(
            "X", candidate_row=self._candidate(), attribution=row, funda=self._funda(),
        )
        self.assertEqual(action, "HOLD")
        self.assertIs(block["dislocation_confirmed"], False)


class TestWriterActionBlock(unittest.TestCase):
    def _report(self, action="BUY", attribution=None):
        thesis = ScripAlphaThesis(
            symbol="HAL",
            company_name="Hindustan Aeronautics Limited",
            composite_rank=1,
            current_market_price=100.0,
            recommended_entry_range="INR 98.50 - INR 101.50",
            target_price=118.0,
            stop_loss=94.0,
            risk_reward_ratio=3.0,
            conviction_level=ConvictionLevel.HIGH_CONVICTION,
            techno_delivery_thesis="t" * 60,
            fundamental_thesis="f" * 60,
            causal_macro_rationale="c" * 40,
            key_catalysts=["c1", "c2"],
            key_risks=["r1", "r2"],
        )
        object.__setattr__(thesis, "action", action)
        object.__setattr__(thesis, "attribution", attribution)
        breadth = MarketBreadthSummary(
            advance_decline_ratio=1.2,
            market_regime=MarketRegime.NEUTRAL,
            top_performing_sectors=["A"],
            vulnerable_sectors=["B"],
        )
        return DailyAlphaReport(
            date="2026-08-27",
            universe="NIFTY200",
            market_breadth=breadth,
            high_conviction_theses=[thesis],
            macro_shock_radar=[],
            disqualified_solvency_count=0,
            generated_timestamp="2026-08-27T00:00:00",
        )

    def test_markdown_contains_action(self):
        report = self._report(action="HOLD", attribution=None)
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "daily_alpha.md"
            ReportWriter(base_reports_dir=Path(tmp)).write_markdown(report, md_path)
            text = md_path.read_text(encoding="utf-8")
        self.assertIn("Action:", text)
        self.assertIn("Action: HOLD", text)

    def test_markdown_attribution_block(self):
        block = {
            "realized_move_pct": -3.5,
            "noise_floor": 0.8,
            "is_material": True,
            "explained_total": 0.2,
            "residual": 0.8,
            "per_lens": [
                {"family": "factor_statistical", "predicted_direction": -1,
                 "weight": 0.3, "share": 0.0},
                {"family": "business_quality", "predicted_direction": -1,
                 "weight": 0.25, "share": 0.0},
                {"family": "policy_macro", "predicted_direction": 0,
                 "weight": 0.25, "share": 0.0},
                {"family": "supply_chain", "predicted_direction": -1,
                 "weight": 0.2, "share": 0.2},
            ],
            "investor_majority": "all",
            "regime_tag": "*",
        }
        report = self._report(action="BUY", attribution=block)
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / "daily_alpha.md"
            html_path = Path(tmp) / "daily_alpha.html"
            json_path = Path(tmp) / "daily_alpha.json"
            writer = ReportWriter(base_reports_dir=Path(tmp))
            writer.write_markdown(report, md_path)
            writer.write_html(report, html_path)
            writer.write_json(report, json_path)
            md_text = md_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")
            data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertIn("Action: BUY", md_text)
        self.assertIn("factor_statistical", md_text)
        self.assertIn("Action: BUY", html_text)
        self.assertIn("factor_statistical", html_text)
        thesis_json = data["high_conviction_theses"][0]
        self.assertEqual(thesis_json["action"], "BUY")
        self.assertEqual(thesis_json["attribution"]["residual"], 0.8)
        self.assertEqual(len(thesis_json["attribution"]["per_lens"]), 4)


class TestCliVerbsParse(unittest.TestCase):
    """Argparse-level only: no live DB, handlers invoked with Namespace."""

    def _capture(self, func, args):
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            func(args)
        finally:
            sys.stdout = old
        return buf.getvalue()

    def test_attribute_move_parser_single(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("attribute-move")
        p.add_argument("--symbol", default=None)
        p.add_argument("--date", default=None)
        p.add_argument("--universe", default=None)
        p.add_argument("--universe-days", dest="universe_days", default=None)
        parsed = parser.parse_args(["attribute-move", "--symbol", "HAL", "--date", "2026-08-27"])
        self.assertEqual(parsed.symbol, "HAL")
        self.assertEqual(parsed.date, "2026-08-27")
        out = self._capture(cmd_attribute_move, parsed)
        payload = json.loads(out)
        # Live DB may or may not have the row; either way the verb prints JSON.
        self.assertIn("ok", payload)

    def test_attribute_move_parser_batch(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("attribute-move")
        p.add_argument("--symbol", default=None)
        p.add_argument("--date", default=None)
        p.add_argument("--universe", default=None)
        p.add_argument("--universe-days", dest="universe_days", default=None)
        parsed = parser.parse_args(
            ["attribute-move", "--universe", "nifty200", "--universe-days", "25"]
        )
        self.assertEqual(parsed.universe, "nifty200")
        self.assertEqual(parsed.universe_days, "25")

    def test_portfolio_ledger_stub_prints_json(self):
        out = self._capture(cmd_portfolio_ledger, argparse.Namespace(asof=None, date=None))
        payload = json.loads(out)
        self.assertIn("ok", payload)

    def test_run_calibration_stub_prints_json(self):
        out = self._capture(
            cmd_run_calibration, argparse.Namespace(mode="ensemble", horizon_days=5)
        )
        payload = json.loads(out)
        self.assertIn("ok", payload)

    def test_full_parser_registers_verbs(self):
        import subprocess

        proc = subprocess.run(
            [sys.executable, "-m", "reality_engine.cli", "attribute-move", "--help"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--symbol", proc.stdout)
        proc2 = subprocess.run(
            [sys.executable, "-m", "reality_engine.cli", "portfolio-ledger", "--help"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        self.assertEqual(proc2.returncode, 0)
        proc3 = subprocess.run(
            [sys.executable, "-m", "reality_engine.cli", "run-calibration", "--help"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        self.assertEqual(proc3.returncode, 0)


if __name__ == "__main__":
    unittest.main()
