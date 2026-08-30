"""
Unit and Integration Test Suite for AI Agent Tool Registry, Orchestrator, and Report Exporter
"""

import json
import unittest
from pathlib import Path

from reality_engine.config import REPORTS_DIR
from reality_engine.agent.schemas import (
    ScripAlphaThesis,
    MarketBreadthSummary,
    DailyAlphaReport,
    ConvictionLevel,
    MarketRegime,
)
from reality_engine.agent.tools import (
    get_scrip_techno_delivery,
    get_quarterly_financials,
    search_concall_guidance,
    get_distilled_parameters,
    simulate_macro_shock,
    trace_macro_causal_chain,
    get_market_breadth_overview,
    get_tool_declarations,
    dispatch_tool_call,
)
from reality_engine.agent.orchestrator import AgentOrchestrator, agent_orchestrator
from reality_engine.reporting.writer import ReportWriter, report_writer


class TestAgentAndReporting(unittest.TestCase):
    """Verifies schemas, tools, orchestrator, and multi-format report exporter."""

    def test_01_schemas_serialization_and_validation(self):
        """Tests ScripAlphaThesis, MarketBreadthSummary, and DailyAlphaReport contracts."""
        thesis = ScripAlphaThesis(
            symbol="HAL",
            company_name="Hindustan Aeronautics Limited",
            composite_rank=1,
            current_market_price=5029.90,
            recommended_entry_range="INR 4954.45 - INR 5105.35",
            target_price=5935.28,
            stop_loss=4728.11,
            risk_reward_ratio=3.0,
            conviction_level=ConvictionLevel.HIGH_CONVICTION,
            techno_delivery_thesis="Breakout confirmed with 2.04x DSR and strong volume.",
            fundamental_thesis="YoY revenue growth +1.8% and +777 bps margin expansion.",
            causal_macro_rationale="Defence DAP 2026 indigenization policy beneficiary.",
            key_catalysts=["Order execution", "Tender pipeline conversion"],
            key_risks=["Supply chain delay", "Market multiple compression"]
        )

        breadth = MarketBreadthSummary(
            advance_decline_ratio=1.45,
            market_regime=MarketRegime.ACCUMULATION,
            top_performing_sectors=["Nifty Media (+1.2%)", "Nifty Auto (+0.8%)"],
            vulnerable_sectors=["Nifty Metal (-0.5%)"]
        )

        report = DailyAlphaReport(
            date="2026-08-14",
            universe="NIFTY200",
            market_breadth=breadth,
            high_conviction_theses=[thesis],
            macro_shock_radar=[{"scenario_id": "DEFENCE_INDIGENIZATION_DAP", "beneficiaries": ["HAL"]}],
            disqualified_solvency_count=28,
            generated_timestamp="2026-08-18T00:00:00"
        )

        # 1. Dict serialization
        d = report.to_dict()
        self.assertEqual(d["date"], "2026-08-14")
        self.assertEqual(d["universe"], "NIFTY200")
        self.assertEqual(d["market_breadth"]["market_regime"], "ACCUMULATION")
        self.assertEqual(len(d["high_conviction_theses"]), 1)
        self.assertEqual(d["high_conviction_theses"][0]["symbol"], "HAL")

        # 2. JSON serialization
        j = report.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["disqualified_solvency_count"], 28)

        # 3. Model validation from dict and json
        report_from_d = DailyAlphaReport.from_dict(d)
        self.assertIsInstance(report_from_d.market_breadth, MarketBreadthSummary)
        self.assertIsInstance(report_from_d.high_conviction_theses[0], ScripAlphaThesis)
        self.assertEqual(report_from_d.high_conviction_theses[0].target_price, 5935.28)

        report_from_j = DailyAlphaReport.from_json(j)
        self.assertEqual(report_from_j.date, "2026-08-14")
        self.assertEqual(report_from_j.high_conviction_theses[0].symbol, "HAL")

    def test_02_tool_declarations_and_dispatcher(self):
        """Verifies function schemas and dynamic tool call routing."""
        declarations = get_tool_declarations()
        self.assertEqual(len(declarations), 7)
        tool_names = [d["name"] for d in declarations]
        expected_tools = [
            "get_scrip_techno_delivery",
            "get_quarterly_financials",
            "search_concall_guidance",
            "get_distilled_parameters",
            "simulate_macro_shock",
            "trace_macro_causal_chain",
            "get_market_breadth_overview",
        ]
        for et in expected_tools:
            self.assertIn(et, tool_names)

        # Test dispatching get_market_breadth_overview
        res_breadth = dispatch_tool_call("get_market_breadth_overview", {})
        self.assertIn("advance_decline_ratio", res_breadth)
        self.assertIn("market_regime", res_breadth)

        # Test dispatching get_scrip_techno_delivery
        res_techno = dispatch_tool_call("get_scrip_techno_delivery", {"symbol": "HAL", "lookback_days": 5})
        self.assertEqual(res_techno["status"], "SUCCESS")
        self.assertEqual(res_techno["symbol"], "HAL")

        # Test error handling
        res_err = dispatch_tool_call("non_existent_tool", {})
        self.assertEqual(res_err["status"], "ERROR")

    def test_03_individual_tools_execution(self):
        """Tests all 7 tools against the local database."""
        # 1. Technical & Delivery
        t1 = get_scrip_techno_delivery("HAL", lookback_days=10)
        self.assertEqual(t1["status"], "SUCCESS")
        self.assertGreater(t1["current_market_price"], 0)
        self.assertGreaterEqual(t1["delivery_spike_ratio"], 0)

        # 2. Quarterly Financials
        t2 = get_quarterly_financials("HAL", quarters=4)
        self.assertEqual(t2["status"], "SUCCESS")
        self.assertGreater(t2["quarters_count"], 0)
        self.assertGreater(t2["latest_revenue_inr_cr"], 0)

        # 3. Concall guidance search
        t3 = search_concall_guidance("HAL", query="order book guidance", top_k=5)
        self.assertEqual(t3["symbol"], "HAL")
        self.assertIsInstance(t3["hits"], list)

        # 4. Distilled parameters
        t4 = get_distilled_parameters("KAYNES", parameter_key="ALL")
        self.assertEqual(t4["symbol"], "KAYNES")
        self.assertIsInstance(t4["parameters"], dict)

        # 5. Simulate macro shock
        t5 = simulate_macro_shock("UNION_BUDGET_2026_RAIL_CAPEX")
        self.assertEqual(t5["shock_scenario"], "UNION_BUDGET_2026_RAIL_CAPEX")
        self.assertGreaterEqual(len(t5["beneficiaries"]), 1)

        # 6. Trace macro causal chain
        t6 = trace_macro_causal_chain("DEFENCE_INDIGENIZATION_DAP", impact_filter="BENEFICIARIES_ONLY")
        self.assertEqual(t6["macro_event_or_policy"], "DEFENCE_INDIGENIZATION_DAP")
        self.assertGreaterEqual(t6["traces_count"], 1)

        # 7. Market breadth overview
        t7 = get_market_breadth_overview()
        self.assertGreater(t7["total_traded_stocks"], 0)
        self.assertGreater(t7["advance_decline_ratio"], 0)

    def test_04_agent_orchestrator_synthesis(self):
        """Tests end-to-end report synthesis by AgentOrchestrator."""
        orchestrator = AgentOrchestrator()
        report = orchestrator.synthesize_daily_alpha_report(universe="nifty200", top_n=5)

        self.assertIsInstance(report, DailyAlphaReport)
        self.assertEqual(report.universe, "NIFTY200")
        self.assertEqual(len(report.high_conviction_theses), 5)

        # Verify each thesis has complete trade setups and theses
        for thesis in report.high_conviction_theses:
            self.assertGreater(thesis.composite_rank, 0)
            self.assertTrue(len(thesis.symbol) > 0)
            self.assertGreater(thesis.current_market_price, 0)
            self.assertGreater(thesis.target_price, thesis.current_market_price)
            self.assertLess(thesis.stop_loss, thesis.current_market_price)
            self.assertGreaterEqual(thesis.risk_reward_ratio, 2.5)
            self.assertIn(thesis.conviction_level, [
                ConvictionLevel.HIGH_CONVICTION,
                ConvictionLevel.MODERATE,
                ConvictionLevel.SPECULATIVE
            ])
            self.assertTrue(len(thesis.techno_delivery_thesis) > 50)
            self.assertTrue(len(thesis.fundamental_thesis) > 50)
            self.assertTrue(len(thesis.causal_macro_rationale) > 30)
            self.assertGreaterEqual(len(thesis.key_catalysts), 2)
            self.assertGreaterEqual(len(thesis.key_risks), 2)

        self.assertGreaterEqual(len(report.macro_shock_radar), 3)

    def test_05_report_writer_multi_format_export(self):
        """Tests exporting DailyAlphaReport to JSON, Markdown, and HTML."""
        orchestrator = AgentOrchestrator()
        report = orchestrator.synthesize_daily_alpha_report(universe="nifty200", top_n=5)

        writer = ReportWriter()
        exported = writer.export_daily_alpha_report(report)

        json_path = exported["json"]
        md_path = exported["markdown"]
        html_path = exported["html"]

        # 1. Check JSON export
        self.assertTrue(json_path.exists())
        self.assertGreater(json_path.stat().st_size, 5000)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["date"], report.date)
            self.assertEqual(len(data["high_conviction_theses"]), 5)

        # 2. Check Markdown export
        self.assertTrue(md_path.exists())
        self.assertGreater(md_path.stat().st_size, 5000)
        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()
            self.assertIn("# Reality Engine - Daily Alpha & Causal Market Report", md_text)
            self.assertIn("## 1. Executive Market Breadth & Macro Regime", md_text)
            self.assertIn("## 2. High-Conviction Alpha Candidate Summary", md_text)
            self.assertIn("## 3. Deep Single-Stock Alpha Theses", md_text)
            self.assertIn("## 4. Macroeconomic Shock & Causal Policy Radar", md_text)
            self.assertIn(report.high_conviction_theses[0].symbol, md_text)

        # 3. Check HTML export
        self.assertTrue(html_path.exists())
        self.assertGreater(html_path.stat().st_size, 10000)
        with open(html_path, "r", encoding="utf-8") as f:
            html_text = f.read()
            self.assertIn("<!DOCTYPE html>", html_text)
            self.assertIn("Daily Alpha Report", html_text)
            self.assertIn("High-Conviction Alpha Portfolio", html_text)
            self.assertIn("Deep Scrip Alpha Theses", html_text)
            self.assertIn("Policy Transmission Radar", html_text)
            self.assertIn(report.high_conviction_theses[0].symbol, html_text)

    def test_06_nullable_policy_no_template_GMRAIRPORT_regression(self):
        """Regression: nullable policy for no-template symbol must not regress to ENI 0 / false tailwind.

        Observed failure case GMRAIRPORT (Services; no mapped policy template) must preserve
        policy_agg_eni is None, policy_coverage == 'no_template', policy_approval is None
        via the candidate path used by test_04_agent_orchestrator_synthesis, and the
        synthesized rationale must be neutral (ENI unknown / no mapped template) without
        claiming a policy tailwind.
        """
        orchestrator = AgentOrchestrator()

        # 1. Direct _fetch_topdown_metrics preserves nullable ENI for GMRAIRPORT
        metrics = orchestrator._fetch_topdown_metrics("GMRAIRPORT", {"symbol": "GMRAIRPORT", "isin": "INE776C01039"})
        self.assertIsNone(metrics["policy_agg_eni"])
        self.assertIsNone(metrics["policy_eni"])
        self.assertEqual(metrics["policy_coverage"], "no_template")
        self.assertIsNone(metrics["policy_approval"])
        # neutral calc helper remains 0.0 for arithmetic but must not overwrite audit None
        self.assertEqual(metrics["policy_agg_eni_calc"], 0.0)

        # 2. Same via minimal candidate_row shape used by evaluate_candidate_scrip (as in test_04)
        candidate_row = {"symbol": "GMRAIRPORT", "isin": "INE776C01039", "close": 92.5, "composite_score": 58.0}
        metrics2 = orchestrator._fetch_topdown_metrics(candidate_row["symbol"], candidate_row)
        self.assertIsNone(metrics2["policy_agg_eni"])
        self.assertEqual(metrics2["policy_coverage"], "no_template")
        self.assertIsNone(metrics2["policy_approval"])

        # 3. Full public path: evaluate_candidate_scrip -> thesis preserves audit fields
        thesis = orchestrator.evaluate_candidate_scrip(candidate_row, rank=1)
        self.assertIsNone(getattr(thesis, "policy_agg_eni"))
        self.assertEqual(getattr(thesis, "policy_coverage"), "no_template")
        self.assertIsNone(getattr(thesis, "policy_approval"))
        # alias / calc consistency
        self.assertIsNone(getattr(thesis, "policy_agg_eni", None))
        self.assertEqual(getattr(thesis, "policy_agg_eni_calc", 0.0), 0.0)

        # 4. Rationale must be neutral and must not fabricate a tailwind
        rationale = thesis.causal_macro_rationale
        self.assertIn("ENI unknown", rationale)
        self.assertIn("no mapped policy template", rationale)
        self.assertNotIn("policy tailwind", rationale.lower())
        # verdict helper also contains the same neutral phrasing
        self.assertIn("no_template", rationale.lower())
        self.assertIn("policy neutral", rationale.lower())


if __name__ == "__main__":
    unittest.main()
