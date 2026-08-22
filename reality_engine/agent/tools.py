"""
Agent Tool Registry & Dispatcher Module
Provides 7 specialized function tools for quantitative, fundamental,
causal macro, and concall transcript analysis with OpenAI/Gemini function schemas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np

from reality_engine.db.database import db_manager
from reality_engine.db.repository import repo
from reality_engine.search.hybrid_search import HybridSearchEngine
from reality_engine.processing.macro_simulator import macro_simulator
from reality_engine.processing.causal_engine import causal_engine
from reality_engine.processing.distillation_engine import distillation_engine
from reality_engine.processing.fundamental_engine import fundamental_engine

logger = logging.getLogger("reality_engine.agent.tools")

# Singleton hybrid search engine instance
_search_engine = HybridSearchEngine(db_manager)


# ====================================================================
# 1. Tool Functions
# ====================================================================

def get_scrip_techno_delivery(symbol: str, lookback_days: int = 20) -> Dict[str, Any]:
    """
    Fetch historical OHLCV, Deliverable Quantity, Delivery %, Delivery Spike Ratio,
    RSI, and Moving Averages for a given stock symbol.
    """
    clean_sym = str(symbol).upper().strip()
    df = repo.get_price_history(clean_sym, limit=max(1, int(lookback_days)))
    if df.empty:
        return {
            "symbol": clean_sym,
            "status": "NOT_FOUND",
            "message": f"No technical/delivery data found for symbol {clean_sym}",
            "history": []
        }

    latest = df.iloc[-1].to_dict()
    cmp = float(latest.get("close") or 0.0)
    sma20 = float(latest.get("sma_20") or 0.0)
    sma50 = float(latest.get("sma_50") or 0.0)
    sma200 = float(latest.get("sma_200") or 0.0)
    rsi = float(latest.get("rsi_14") or 50.0)
    dsr = float(latest.get("delivery_spike_ratio") or 1.0)
    dcs = float(latest.get("delivery_conviction_score") or 0.0)
    deliv_pct = float(latest.get("delivery_pct") or 0.0)
    dist_52w = float(latest.get("distance_from_52w_high_pct") or 0.0)

    # Trend alignment assessment
    if cmp > sma20 and (sma20 >= sma50 or sma50 == 0) and (sma50 >= sma200 or sma200 == 0):
        trend_alignment = "STRONG_UPTREND (Close > SMA20 >= SMA50 >= SMA200)"
    elif cmp > sma20:
        trend_alignment = "MOMENTUM_EXPANSION (Close > SMA20)"
    elif cmp < sma20 and (sma20 < sma50 or sma50 == 0):
        trend_alignment = "DOWNTREND (Close < SMA20 < SMA50)"
    else:
        trend_alignment = "CONSOLIDATION_RANGE"

    # Institutional accumulation signal
    if dsr >= 2.0 and deliv_pct >= 50.0:
        delivery_signal = "EXTREME_INSTITUTIONAL_ACCUMULATION (DSR >= 2.0x, Deliv% >= 50%)"
    elif dsr >= 1.5 and deliv_pct >= 40.0:
        delivery_signal = "STRONG_INSTITUTIONAL_DELIVERY (DSR >= 1.5x, Deliv% >= 40%)"
    elif dsr >= 1.2:
        delivery_signal = "ABOVE_AVERAGE_DELIVERY_SPIKE"
    else:
        delivery_signal = "NORMAL_DELIVERY_FLOW"

    # RSI momentum signal
    if 55.0 <= rsi <= 75.0:
        rsi_signal = "BULLISH_MOMENTUM_ZONE (55 - 75)"
    elif rsi > 75.0:
        rsi_signal = "OVERBOUGHT_EXTENSION (> 75)"
    elif rsi < 35.0:
        rsi_signal = "OVERSOLD_REVERSAL_ZONE (< 35)"
    else:
        rsi_signal = "NEUTRAL_MOMENTUM"

    history_records = []
    for _, row in df.iterrows():
        history_records.append({
            "date": str(row.get("date")),
            "close": float(row.get("close") or 0.0),
            "change_pct": float(row.get("change_pct") or 0.0),
            "total_volume": int(row.get("total_volume") or 0),
            "deliverable_volume": int(row.get("deliverable_volume") or 0),
            "delivery_pct": float(row.get("delivery_pct") or 0.0),
            "delivery_spike_ratio": float(row.get("delivery_spike_ratio") or 1.0),
            "delivery_conviction_score": float(row.get("delivery_conviction_score") or 0.0),
            "rsi_14": float(row.get("rsi_14") or 50.0),
        })

    return {
        "symbol": clean_sym,
        "status": "SUCCESS",
        "latest_date": str(latest.get("date")),
        "current_market_price": cmp,
        "prev_close": float(latest.get("prev_close") or 0.0),
        "change_pct": float(latest.get("change_pct") or 0.0),
        "total_volume": int(latest.get("total_volume") or 0),
        "deliverable_volume": int(latest.get("deliverable_volume") or 0),
        "delivery_pct": deliv_pct,
        "delivery_spike_ratio": dsr,
        "delivery_conviction_score": dcs,
        "sma_20": sma20,
        "sma_50": sma50,
        "sma_200": sma200,
        "rsi_14": rsi,
        "high_52w": float(latest.get("high_52w") or 0.0),
        "low_52w": float(latest.get("low_52w") or 0.0),
        "distance_from_52w_high_pct": dist_52w,
        "trend_alignment": trend_alignment,
        "delivery_signal": delivery_signal,
        "rsi_signal": rsi_signal,
        "data_points_count": len(df),
        "history": history_records,
    }


def get_quarterly_financials(symbol: str, quarters: int = 8) -> Dict[str, Any]:
    """
    Fetch the last N quarters of financial results including Revenue, EBITDA,
    Net Profit, Margins, YoY growth percentages, and forensic solvency health.
    """
    clean_sym = str(symbol).upper().strip()
    df = repo.get_quarterly_financials_history(clean_sym, quarters=max(1, int(quarters)))
    company = repo.get_company_by_symbol(clean_sym)
    forensic = repo.get_forensic_health(clean_sym)

    if df.empty:
        return {
            "symbol": clean_sym,
            "status": "NOT_FOUND",
            "message": f"No quarterly financial records found for {clean_sym}",
            "quarters": []
        }

    quarters_list: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        quarters_list.append({
            "quarter_end_date": str(row.get("quarter_end_date")),
            "financial_year": str(row.get("financial_year")),
            "revenue_inr_cr": float(row.get("revenue_inr_cr") or 0.0),
            "ebitda_inr_cr": float(row.get("ebitda_inr_cr") or 0.0),
            "ebitda_margin_pct": float(row.get("ebitda_margin_pct") or 0.0),
            "net_profit_inr_cr": float(row.get("net_profit_inr_cr") or 0.0),
            "pat_margin_pct": float(row.get("pat_margin_pct") or 0.0),
            "eps_inr": float(row.get("eps_inr") or 0.0),
            "yoy_revenue_growth_pct": float(row.get("yoy_revenue_growth_pct") or 0.0),
            "yoy_pat_growth_pct": float(row.get("yoy_pat_growth_pct") or 0.0),
            "qoq_revenue_growth_pct": float(row.get("qoq_revenue_growth_pct") or 0.0),
            "qoq_pat_growth_pct": float(row.get("qoq_pat_growth_pct") or 0.0),
            "has_concall_transcript": bool(row.get("has_concall_transcript")),
        })

    latest = quarters_list[0]
    prior = quarters_list[1] if len(quarters_list) > 1 else None
    opm_delta_bps = fundamental_engine.calculate_opm_delta_bps(
        latest["ebitda_margin_pct"],
        prior["ebitda_margin_pct"] if prior else 0.0
    ) if prior else 0.0

    forensic_summary: Dict[str, Any] = {}
    if not forensic.empty:
        f_row = forensic.iloc[-1].to_dict()
        forensic_summary = {
            "is_solvency_approved": int(f_row.get("is_solvency_approved") or 0),
            "promoter_holding_pct": float(f_row.get("promoter_holding_pct") or 0.0),
            "promoter_pledge_pct": float(f_row.get("promoter_pledge_pct") or 0.0),
            "interest_coverage_ratio": float(f_row.get("interest_coverage_ratio") or 0.0),
            "debt_to_equity_ratio": float(f_row.get("debt_to_equity_ratio") or 0.0),
            "market_cap_inr_cr": float(f_row.get("market_cap_inr_cr") or 0.0),
            "pe_ratio": float(f_row.get("pe_ratio") or 0.0),
            "solvency_disqualification_reasons": str(f_row.get("solvency_disqualification_reasons") or ""),
        }

    return {
        "symbol": clean_sym,
        "company_name": company.get("company_name", clean_sym) if company else clean_sym,
        "status": "SUCCESS",
        "quarters_count": len(quarters_list),
        "latest_financial_period": latest["financial_year"],
        "latest_revenue_inr_cr": latest["revenue_inr_cr"],
        "latest_ebitda_inr_cr": latest["ebitda_inr_cr"],
        "latest_ebitda_margin_pct": latest["ebitda_margin_pct"],
        "latest_net_profit_inr_cr": latest["net_profit_inr_cr"],
        "latest_yoy_revenue_growth_pct": latest["yoy_revenue_growth_pct"],
        "latest_yoy_pat_growth_pct": latest["yoy_pat_growth_pct"],
        "opm_delta_bps": opm_delta_bps,
        "forensic_solvency": forensic_summary,
        "quarters": quarters_list,
    }


def search_concall_guidance(symbol: str, query: str, top_k: int = 5) -> Dict[str, Any]:
    """
    Perform a hybrid semantic and keyword search over earnings conference call transcripts
    and investor presentations for a specific stock.
    """
    clean_sym = str(symbol).upper().strip()
    hits = _search_engine.search(query=query, symbol=clean_sym, top_k=max(1, int(top_k)))
    return {
        "symbol": clean_sym,
        "query": query,
        "top_k": top_k,
        "hits_count": len(hits),
        "hits": [h.to_dict() for h in hits],
    }


def get_distilled_parameters(symbol: str, parameter_key: str = "ALL") -> Dict[str, Any]:
    """
    Fetch distilled company intelligence including sector cyclicality, cycle duration,
    current cycle stage, and raw material / regulatory sensitivities.
    """
    clean_sym = str(symbol).upper().strip()
    param_filter = None if parameter_key.upper() == "ALL" else parameter_key
    rows = distillation_engine.get_distilled_parameters(clean_sym, parameter_key=param_filter)

    params_map: Dict[str, Any] = {}
    for r in rows:
        key = r.get("parameter_key", "")
        params_map[key] = {
            "parameter_key": key,
            "value": r.get("value"),
            "confidence_score": r.get("confidence_score", 1.0),
            "source_document_ref": r.get("source_document_ref"),
            "last_updated_date": str(r.get("last_updated_date")),
        }

    return {
        "symbol": clean_sym,
        "parameter_key": parameter_key,
        "parameters_count": len(params_map),
        "parameters": params_map,
    }


def simulate_macro_shock(shock_scenario: str, sector_filter: str = "ALL") -> Dict[str, Any]:
    """
    Simulate a macroeconomic, geopolitical, military, or commodity shock and retrieve
    all companies with direct or indirect exposure across the causal graph.
    """
    return macro_simulator.simulate_macro_shock(
        shock_scenario=shock_scenario,
        sector_filter=sector_filter
    )


def trace_macro_causal_chain(
    macro_event_or_policy: str,
    impact_filter: str = "BENEFICIARIES_ONLY",
    max_hops: int = 3
) -> Dict[str, Any]:
    """
    Trace the multi-hop transmission chain of a macro event, Union Budget policy,
    commodity shift, or geopolitical shock down to listed Indian companies.
    """
    traces = causal_engine.trace_causal_chain(
        start_node_id=macro_event_or_policy,
        max_hops=max_hops,
        impact_filter=impact_filter
    )
    return {
        "macro_event_or_policy": macro_event_or_policy,
        "impact_filter": impact_filter,
        "max_hops": max_hops,
        "traces_count": len(traces),
        "traces": traces,
    }


def get_market_breadth_overview() -> Dict[str, Any]:
    """
    Fetch market-wide sector advance/decline ratios, sector momentum scores,
    and market breadth snapshot across NSE indices and daily price delivery.
    """
    latest_date = repo.get_latest_price_delivery_date() or "2026-08-14"

    # 1. Market-wide advances & declines from daily_price_delivery
    with db_manager.session() as conn:
        breadth_row = conn.execute(
            """
            SELECT 
                SUM(CASE WHEN change_pct > 0 THEN 1 ELSE 0 END) as advances,
                SUM(CASE WHEN change_pct < 0 THEN 1 ELSE 0 END) as declines,
                SUM(CASE WHEN change_pct = 0 THEN 1 ELSE 0 END) as unchanged,
                COUNT(*) as total_stocks
            FROM daily_price_delivery
            WHERE date = ?
            """,
            (latest_date,)
        ).fetchone()

    adv = int(breadth_row["advances"] or 0) if breadth_row else 0
    dec = int(breadth_row["declines"] or 0) if breadth_row else 0
    unch = int(breadth_row["unchanged"] or 0) if breadth_row else 0
    total = int(breadth_row["total_stocks"] or 0) if breadth_row else 0
    ad_ratio = round(adv / max(1, dec), 2)

    # Determine market regime
    if ad_ratio >= 1.5:
        market_regime = "BULLISH"
    elif ad_ratio >= 1.05:
        market_regime = "ACCUMULATION"
    elif 0.80 <= ad_ratio < 1.05:
        market_regime = "NEUTRAL"
    elif 0.50 <= ad_ratio < 0.80:
        market_regime = "DISTRIBUTION"
    else:
        market_regime = "VOLATILE"

    # 2. Sector index performance from nse_index_breadth
    with db_manager.session() as conn:
        sector_rows = conn.execute(
            """
            SELECT index_name, change_pct, advances_count, declines_count, advance_decline_ratio
            FROM nse_index_breadth
            WHERE date = ?
            ORDER BY change_pct DESC
            """,
            (latest_date,)
        ).fetchall()

    sector_data = [dict(r) for r in sector_rows]

    # Filter for relevant sector indices (exclude broad cap composite duplicates)
    top_sectors: List[str] = []
    vulnerable_sectors: List[str] = []

    for s in sector_data:
        name = s["index_name"]
        chg = float(s.get("change_pct") or 0.0)
        # Skip broad 100/200/500 indices for pure sector list
        if any(w in name for w in ["Auto", "Bank", "IT", "Pharma", "Metal", "FMCG", "Realty", "Energy", "Infra", "Media", "Consumer", "Financial"]):
            if chg > 0:
                top_sectors.append(f"{name} (+{chg:.2f}%)")
            else:
                vulnerable_sectors.append(f"{name} ({chg:.2f}%)")

    # If top_sectors empty, take top 3 general indices
    if not top_sectors and sector_data:
        top_sectors = [f"{s['index_name']} ({s['change_pct']:+.2f}%)" for s in sector_data[:3]]
    if not vulnerable_sectors and sector_data:
        vulnerable_sectors = [f"{s['index_name']} ({s['change_pct']:+.2f}%)" for s in sector_data[-3:]]

    return {
        "date": latest_date,
        "advance_decline_ratio": ad_ratio,
        "advances_count": adv,
        "declines_count": dec,
        "unchanged_count": unch,
        "total_traded_stocks": total,
        "market_regime": market_regime,
        "top_performing_sectors": top_sectors[:5],
        "vulnerable_sectors": vulnerable_sectors[:5],
        "all_sectors": sector_data,
    }


# ====================================================================
# 2. Tool Declarations Schema (OpenAI / Gemini function calling format)
# ====================================================================

TOOL_DECLARATIONS: List[Dict[str, Any]] = [
    {
        "name": "get_scrip_techno_delivery",
        "description": "Fetch historical OHLCV, Deliverable Quantity, Delivery %, Delivery Spike Ratio, RSI, and Moving Averages for a given stock symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE Ticker Symbol, e.g. 'HAL', 'KAYNES', 'TITAGARH', 'TCS'"
                },
                "lookback_days": {
                    "type": "integer",
                    "description": "Number of past trading days to retrieve (default 20)",
                    "default": 20
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_quarterly_financials",
        "description": "Fetch the last 8 quarters of financial results including Revenue, EBITDA, Net Profit, Margins, YoY growth percentages, and forensic solvency health.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE Ticker Symbol, e.g. 'HAL', 'TITAGARH'"
                },
                "quarters": {
                    "type": "integer",
                    "description": "Number of quarters to fetch (default 8)",
                    "default": 8
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "search_concall_guidance",
        "description": "Perform a hybrid semantic and keyword search over earnings conference call transcripts and investor presentations for a specific stock.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE Ticker Symbol"
                },
                "query": {
                    "type": "string",
                    "description": "Search topic, e.g. 'capex expansion order book guidance margin commentary'"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of transcript excerpts to return (default 5)",
                    "default": 5
                }
            },
            "required": ["symbol", "query"]
        }
    },
    {
        "name": "get_distilled_parameters",
        "description": "Fetch distilled company intelligence including sector cyclicality, cycle duration, current cycle stage, and raw material / regulatory sensitivities.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE Ticker Symbol"
                },
                "parameter_key": {
                    "type": "string",
                    "description": "Specific parameter to retrieve ('cyclicality_profile', 'business_sensitivities', 'geopolitical_supply_chain', 'capital_allocation', 'order_book_metrics') or 'ALL'",
                    "default": "ALL"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "simulate_macro_shock",
        "description": "Simulate a macroeconomic, geopolitical, military, or commodity shock and retrieve all companies with direct or indirect exposure across the causal graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "shock_scenario": {
                    "type": "string",
                    "description": "Macro/geopolitical trigger, e.g. 'UNION_BUDGET_2026_RAIL_CAPEX', 'COMMODITY_CRUDE_OIL', 'DEFENCE_INDIGENIZATION_DAP'"
                },
                "sector_filter": {
                    "type": "string",
                    "description": "Optional sector or industry to narrow the stress test (default 'ALL')",
                    "default": "ALL"
                }
            },
            "required": ["shock_scenario"]
        }
    },
    {
        "name": "trace_macro_causal_chain",
        "description": "Trace the multi-hop transmission chain of a macro event, Union Budget policy, commodity shift, or geopolitical shock down to listed Indian companies.",
        "parameters": {
            "type": "object",
            "properties": {
                "macro_event_or_policy": {
                    "type": "string",
                    "description": "The macro trigger node ID, e.g. 'UNION_BUDGET_2026_RAIL_CAPEX', 'DEFENCE_INDIGENIZATION_DAP'"
                },
                "impact_filter": {
                    "type": "string",
                    "enum": ["ALL", "BENEFICIARIES_ONLY", "VICTIMS_ONLY"],
                    "description": "Filter by impact direction (default 'BENEFICIARIES_ONLY')",
                    "default": "BENEFICIARIES_ONLY"
                },
                "max_hops": {
                    "type": "integer",
                    "description": "Propagation depth across graph edges (1 to 4, default 3)",
                    "default": 3
                }
            },
            "required": ["macro_event_or_policy"]
        }
    },
    {
        "name": "get_market_breadth_overview",
        "description": "Fetch market-wide sector advance/decline ratios, sector momentum scores, and market breadth snapshot.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]


def get_tool_declarations() -> List[Dict[str, Any]]:
    """Returns OpenAI/Gemini compatible JSON tool schemas."""
    return TOOL_DECLARATIONS


# ====================================================================
# 3. Dynamic Tool Dispatcher
# ====================================================================

TOOL_ROUTER = {
    "get_scrip_techno_delivery": get_scrip_techno_delivery,
    "get_quarterly_financials": get_quarterly_financials,
    "search_concall_guidance": search_concall_guidance,
    "get_distilled_parameters": get_distilled_parameters,
    "simulate_macro_shock": simulate_macro_shock,
    "trace_macro_causal_chain": trace_macro_causal_chain,
    "get_market_breadth_overview": get_market_breadth_overview,
}


def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dynamically routes and executes tool calls with validated argument parsing.
    """
    func = TOOL_ROUTER.get(tool_name)
    if not func:
        return {
            "status": "ERROR",
            "error": f"Tool '{tool_name}' not found in Agent Tool Registry.",
            "available_tools": list(TOOL_ROUTER.keys())
        }

    try:
        args = arguments or {}
        # Ensure arguments match signature
        if tool_name == "get_market_breadth_overview":
            return func()
        return func(**args)
    except TypeError as te:
        logger.error("Argument error executing %s with args %s: %s", tool_name, arguments, te)
        return {
            "status": "ERROR",
            "tool_name": tool_name,
            "error": f"Invalid arguments for {tool_name}: {te}",
            "arguments_passed": arguments
        }
    except Exception as e:
        logger.exception("Error executing tool %s: %s", tool_name, e)
        return {
            "status": "ERROR",
            "tool_name": tool_name,
            "error": str(e)
        }
