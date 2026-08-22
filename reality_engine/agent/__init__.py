"""
Agent module for Reality Engine.
Provides schema definitions, tool registry, function dispatchers, and LLM orchestrator.
"""

from reality_engine.agent.schemas import (
    ScripAlphaThesis,
    MarketBreadthSummary,
    DailyAlphaReport,
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

__all__ = [
    "ScripAlphaThesis",
    "MarketBreadthSummary",
    "DailyAlphaReport",
    "get_scrip_techno_delivery",
    "get_quarterly_financials",
    "search_concall_guidance",
    "get_distilled_parameters",
    "simulate_macro_shock",
    "trace_macro_causal_chain",
    "get_market_breadth_overview",
    "get_tool_declarations",
    "dispatch_tool_call",
    "AgentOrchestrator",
    "agent_orchestrator",
]
