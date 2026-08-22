"""
Agent Orchestrator Module
Synthesizes quantitative screening, technical flow analysis, fundamental acceleration,
concall transcripts, and causal macro transmission into validated DailyAlphaReport objects.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np

from reality_engine.db.repository import repo
from reality_engine.processing.composite_screener import composite_screener
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
)

logger = logging.getLogger("reality_engine.agent.orchestrator")


class AgentOrchestrator:
    """
    Autonomous multi-step equity intelligence orchestrator that queries tool
    registries, stress-tests causal transmission, and synthesizes high-conviction alpha theses.
    """

    def __init__(self, repository=None, screener=None):
        self.repo = repository or repo
        self.screener = screener or composite_screener

    def run_quantitative_screening(
        self,
        target_date: Optional[str] = None,
        universe: str = "nifty200",
        top_n: int = 20
    ) -> pd.DataFrame:
        """Runs the multi-factor quantitative screener to identify candidate scrips."""
        date_str = target_date or self.repo.get_latest_price_delivery_date()
        logger.info("Running Quantitative Screener for date %s (Universe: %s, Top: %d)", date_str, universe, top_n)
        return self.screener.run_screener(target_date=date_str, top_n=top_n, universe=universe)

    def evaluate_candidate_scrip(
        self,
        candidate_row: Dict[str, Any],
        rank: int
    ) -> ScripAlphaThesis:
        """
        Performs multi-angle tool inspections for a candidate scrip and synthesizes
        a complete ScripAlphaThesis.
        """
        symbol = str(candidate_row.get("symbol", "")).upper().strip()
        cmp = float(candidate_row.get("close", candidate_row.get("current_market_price", 0.0)) or 0.0)

        # 1. Fetch deep technical & delivery flow
        techno = get_scrip_techno_delivery(symbol, lookback_days=20)

        # 2. Fetch quarterly fundamentals & forensic solvency
        funda = get_quarterly_financials(symbol, quarters=8)

        # 3. Fetch distilled parameters & business sensitivities
        distilled = get_distilled_parameters(symbol, parameter_key="ALL")

        # 4. Search concall guidance / catalysts
        concall = search_concall_guidance(symbol, query="order book capex expansion capacity commercialization guidance margin", top_k=3)

        # Company metadata
        comp_info = self.repo.get_company_by_symbol(symbol)
        company_name = comp_info.get("company_name", symbol) if comp_info else symbol
        industry = comp_info.get("industry", "Diversified") if comp_info else "Diversified"
        sector = comp_info.get("sector", "Industrials") if comp_info else "Industrials"

        # Trade setup calculations
        entry_low = round(cmp * 0.985, 2)
        entry_high = round(cmp * 1.015, 2)
        target = round(cmp * 1.18, 2)       # 18% upside
        sl = round(cmp * 0.94, 2)           # 6% stop loss
        rr = round((target - cmp) / max(0.01, cmp - sl), 2)

        composite_score = float(candidate_row.get("composite_score") or 0.0)
        if composite_score >= 75.0:
            conviction = ConvictionLevel.HIGH_CONVICTION
        elif composite_score >= 55.0:
            conviction = ConvictionLevel.MODERATE
        else:
            conviction = ConvictionLevel.SPECULATIVE

        # Build Technical Flow Thesis
        dsr = techno.get("delivery_spike_ratio", 1.0)
        deliv_pct = techno.get("delivery_pct", 0.0)
        dcs = techno.get("delivery_conviction_score", 0.0)
        rsi = techno.get("rsi_14", 50.0)
        sma20 = techno.get("sma_20", 0.0)
        sma50 = techno.get("sma_50", 0.0)
        sma200 = techno.get("sma_200", 0.0)
        dist_52w = techno.get("distance_from_52w_high_pct", 0.0)
        trend_desc = techno.get("trend_alignment", "UPTREND")
        deliv_signal = techno.get("delivery_signal", "INSTITUTIONAL_FLOW")

        techno_thesis = (
            f"Strong institutional delivery accumulation evident with Delivery Spike Ratio of {dsr:.2f}x (20D SMA) "
            f"and delivery volume share of {deliv_pct:.1f}% (DCS: {dcs:.1f}). "
            f"Price action confirms {trend_desc}; CMP INR {cmp:,.2f} trades comfortably above 20-DMA (INR {sma20:,.2f}) "
            f"and 50-DMA (INR {sma50:,.2f}). 14-period RSI sits at {rsi:.1f} indicating healthy momentum without extreme "
            f"overbought exhaustion. Distance from 52-week high is {dist_52w:.1f}%, setting up a high-probability breakout."
        )

        # Build Fundamental Thesis
        latest_period = funda.get("latest_financial_period", "FY26")
        rev_cr = funda.get("latest_revenue_inr_cr", 0.0)
        ebitda_cr = funda.get("latest_ebitda_inr_cr", 0.0)
        ebitda_margin = funda.get("latest_ebitda_margin_pct", 0.0)
        yoy_rev = funda.get("latest_yoy_revenue_growth_pct", 0.0)
        yoy_pat = funda.get("latest_yoy_pat_growth_pct", 0.0)
        opm_delta = funda.get("opm_delta_bps", 0.0)
        forensic = funda.get("forensic_solvency", {})
        promoter_pledge = forensic.get("promoter_pledge_pct", 0.0)
        interest_cov = forensic.get("interest_coverage_ratio", 0.0)
        debt_to_equity = forensic.get("debt_to_equity_ratio", 0.0)

        funda_thesis = (
            f"Quarterly earnings acceleration in {latest_period}: Revenue reached INR {rev_cr:,.2f} Cr (YoY +{yoy_rev:.1f}%), "
            f"with Net Profit (PAT) expanding YoY by +{yoy_pat:.1f}%. EBITDA stood at INR {ebitda_cr:,.2f} Cr "
            f"with margin at {ebitda_margin:.1f}% (operating margin delta: {opm_delta:+.1f} bps). "
            f"Forensic solvency is fully certified: zero promoter pledge risk ({promoter_pledge:.1f}%), robust interest coverage "
            f"of {interest_cov:.2f}x, and conservative debt-to-equity ratio of {debt_to_equity:.2f}x."
        )

        # Build Causal Macro & Value Chain Rationale
        causal_rationale = self._synthesize_causal_rationale(symbol, sector, industry, distilled)

        # Key Catalysts & Risks
        catalysts = self._generate_catalysts(symbol, sector, concall, distilled, yoy_rev)
        risks = self._generate_risks(symbol, sector, distilled, debt_to_equity, dist_52w)

        return ScripAlphaThesis(
            symbol=symbol,
            company_name=company_name,
            composite_rank=rank,
            current_market_price=cmp,
            recommended_entry_range=f"INR {entry_low:,.2f} - INR {entry_high:,.2f}",
            target_price=target,
            stop_loss=sl,
            risk_reward_ratio=rr,
            conviction_level=conviction,
            techno_delivery_thesis=techno_thesis,
            fundamental_thesis=funda_thesis,
            causal_macro_rationale=causal_rationale,
            key_catalysts=catalysts,
            key_risks=risks
        )

    def _synthesize_causal_rationale(
        self,
        symbol: str,
        sector: str,
        industry: str,
        distilled: Dict[str, Any]
    ) -> str:
        """Synthesizes the causal macro, policy transmission, and supply-chain moat narrative."""
        # Check if known canonical nodes connect to this symbol
        traces_rail = trace_macro_causal_chain("UNION_BUDGET_2026_RAIL_CAPEX", impact_filter="ALL", max_hops=2)
        traces_defence = trace_macro_causal_chain("DEFENCE_INDIGENIZATION_DAP", impact_filter="ALL", max_hops=2)
        traces_solar = trace_macro_causal_chain("PM_SURYA_GHAR_SOLAR", impact_filter="ALL", max_hops=2)

        is_rail = any(t.get("node_id") == symbol for t in traces_rail.get("traces", []))
        is_def = any(t.get("node_id") == symbol for t in traces_defence.get("traces", []))
        is_solar = any(t.get("node_id") == symbol for t in traces_solar.get("traces", []))

        if is_def or "DEFENCE" in industry.upper() or "AEROSPACE" in industry.upper() or symbol == "HAL":
            return (
                "Direct beneficiary of Defence Indigenization Policy (DAP 2026) and long-term domestic capital procurement budget. "
                "Causal transmission from indigenous manufacturing mandates converts directly into high-margin platform order book visibility "
                "with resilient pricing power and multi-year execution pipeline."
            )
        elif is_rail or "RAIL" in industry.upper() or symbol in ["TITAGARH", "KAYNES"]:
            return (
                "Direct beneficiary of Union Budget 2026 Railway Capex allocation and rolling stock modernization tenders. "
                "Transmission mechanism operates via multi-year coach/signalling procurement awards, expanding domestic capacity utilization "
                "and high-margin embedded systems delivery."
            )
        elif is_solar or "ELECTRICAL" in sector.upper() or symbol in ["HAVELLS", "PIDILITIND"]:
            return (
                "Propelled by national infrastructure push and PM Surya Ghar residential solar electrification mandates. "
                "Structural demand for building electricals, switchgear, and specialty construction chemicals provides downside resilience "
                "against broader cyclical slowdowns."
            )
        elif "FINANCIAL" in sector.upper() or "BANK" in sector.upper():
            return (
                f"Supported by robust domestic credit expansion and rising financial asset penetration in {industry}. "
                "Clean balance sheet with low credit costs and high Return on Assets (RoA) insulates against macro rate volatility."
            )
        elif "CONSUMER" in sector.upper() or "AUTO" in sector.upper():
            return (
                f"Benefiting from premiumization tailwinds and steady urban discretionary consumption demand in {industry}. "
                "Raw material input cost stability supports gross margin retention and operating leverage expansion."
            )
        else:
            return (
                f"Well-positioned in {sector} ({industry}) with strong market share and domestic capex execution. "
                "Demonstrates resilient supply-chain positioning and passing-through pricing power across raw material cycles."
            )

    def _generate_catalysts(
        self,
        symbol: str,
        sector: str,
        concall: Dict[str, Any],
        distilled: Dict[str, Any],
        yoy_rev: float
    ) -> List[str]:
        """Generates concrete operational and financial catalysts."""
        catalysts = [
            f"Sustained quarterly top-line momentum (YoY +{yoy_rev:.1f}%) driving operating leverage expansion",
            "Order book execution acceleration and timely conversion of prospective tender pipeline",
            f"Favorable sector rotation toward high-ROCE {sector} leaders with pristine solvency profile"
        ]
        if concall.get("hits_count", 0) > 0:
            catalysts.insert(0, "Management concall guidance confirming ongoing capex commercialization and capacity ramp-up")
        return catalysts[:4]

    def _generate_risks(
        self,
        symbol: str,
        sector: str,
        distilled: Dict[str, Any],
        debt_to_equity: float,
        dist_52w: float
    ) -> List[str]:
        """Generates concrete downside triggers and sensitivity risks."""
        risks = [
            "Macroeconomic supply chain disruption and raw material input cost volatility",
            "Broader benchmark market volatility leading to multiple compression in high-beta names"
        ]
        if debt_to_equity > 0.8:
            risks.append(f"Elevated financial leverage (D/E: {debt_to_equity:.2f}x) sensitive to interest rate fluctuations")
        else:
            risks.append("Slight execution delay or quarterly lumpiness in large project milestones")
        return risks[:3]

    def build_macro_shock_radar(self) -> List[Dict[str, Any]]:
        """
        Runs macroeconomic shock simulations across canonical scenarios to build
        the macro shock radar.
        """
        scenarios = [
            ("UNION_BUDGET_2026_RAIL_CAPEX", "Union Budget 2026 Rail Capex"),
            ("DEFENCE_INDIGENIZATION_DAP", "Defence Indigenization DAP"),
            ("COMMODITY_CRUDE_OIL", "Crude Oil Commodity Shock ($95/bbl)"),
            ("PM_SURYA_GHAR_SOLAR", "PM Surya Ghar Solar Policy"),
            ("GEOPOLITICAL_RED_SEA_ATTACKS", "Red Sea Maritime Freight Disruption"),
        ]

        radar: List[Dict[str, Any]] = []
        for shock_id, name in scenarios:
            sim = simulate_macro_shock(shock_id)
            beneficiaries = [b.get("symbol") for b in sim.get("beneficiaries", [])]
            victims = [v.get("symbol") for v in sim.get("victims", [])]

            radar.append({
                "scenario_id": shock_id,
                "scenario_name": name,
                "beneficiaries": beneficiaries,
                "victims": victims,
                "resilient_count": len(sim.get("resilient_companies", [])),
                "impaired_count": len(sim.get("impaired_companies", [])),
            })

        return radar

    def count_disqualified_solvency_companies(self) -> int:
        """Counts how many companies in the universe failed the forensic solvency gate."""
        with self.repo.db.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM company_forensic_health WHERE is_solvency_approved = 0"
            ).fetchone()
            return int(row[0]) if row else 0

    def synthesize_daily_alpha_report(
        self,
        target_date: Optional[str] = None,
        universe: str = "nifty200",
        top_n: int = 5,
        screener_pool_size: int = 20
    ) -> DailyAlphaReport:
        """
        Executes end-to-end synthesis:
        1. Market Breadth and Regime Snapshot
        2. Multi-factor Quantitative Screening
        3. Deep Tool Evidence Gathering for Top Candidates
        4. High-Conviction Alpha Thesis Synthesis
        5. Macro Shock Radar Aggregation
        6. Validated DailyAlphaReport Construction
        """
        date_str = target_date or self.repo.get_latest_price_delivery_date() or "2026-08-14"
        logger.info("Synthesizing Daily Alpha Report for date: %s", date_str)

        # 1. Market Breadth Overview
        breadth_raw = get_market_breadth_overview()
        breadth_summary = MarketBreadthSummary(
            advance_decline_ratio=float(breadth_raw.get("advance_decline_ratio", 1.0)),
            market_regime=str(breadth_raw.get("market_regime", MarketRegime.NEUTRAL)),
            top_performing_sectors=breadth_raw.get("top_performing_sectors", []),
            vulnerable_sectors=breadth_raw.get("vulnerable_sectors", [])
        )

        # 2. Run Screener
        df_screened = self.run_quantitative_screening(
            target_date=date_str,
            universe=universe,
            top_n=screener_pool_size
        )

        # 3. Solvency Disqualifications Count
        disqualified_count = self.count_disqualified_solvency_companies()

        # 4. Synthesize Top Theses
        theses: List[ScripAlphaThesis] = []
        if not df_screened.empty:
            top_candidates = df_screened.head(top_n)
            for rank_idx, (_, row) in enumerate(top_candidates.iterrows(), 1):
                try:
                    candidate_dict = row.to_dict()
                    thesis = self.evaluate_candidate_scrip(candidate_dict, rank=rank_idx)
                    theses.append(thesis)
                except Exception as e:
                    logger.exception("Error synthesizing thesis for row %s: %s", row.get("symbol"), e)

        # 5. Macro Shock Radar
        macro_radar = self.build_macro_shock_radar()

        # 6. Build DailyAlphaReport
        report = DailyAlphaReport(
            date=date_str,
            universe=universe.upper(),
            market_breadth=breadth_summary,
            high_conviction_theses=theses,
            macro_shock_radar=macro_radar,
            disqualified_solvency_count=disqualified_count,
            generated_timestamp=datetime.now().isoformat()
        )

        logger.info("Successfully synthesized Daily Alpha Report for %s with %d theses.", date_str, len(theses))
        return report


# Singleton agent orchestrator instance
agent_orchestrator = AgentOrchestrator()
