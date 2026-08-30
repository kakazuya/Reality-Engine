"""
Reality Engine - Streamlit Equity Intelligence Dashboard
Dark Financial Terminal Interface for Quantitative Screening, Causal Macro Graphs,
Stock Dossiers, EOD Alpha Reports, and Local Drop-in Document Ingestion.
"""

from __future__ import annotations

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np
import streamlit as st

# Ensure project root is in sys.path
ENGINE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ENGINE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.config import DATA_DIR, REPORTS_DIR
from reality_engine.db.database import db_manager
from reality_engine.db.repository import repo
from reality_engine.processing.composite_screener import composite_screener
from reality_engine.processing.causal_engine import causal_engine
from reality_engine.processing.macro_simulator import macro_simulator
from reality_engine.processing.distillation_engine import distillation_engine
from reality_engine.pipeline.panic_monitor import panic_monitor
from reality_engine.pipeline.inbox_runner import InboxRunner
from reality_engine.search.hybrid_search import HybridSearchEngine
from reality_engine.agent.orchestrator import AgentOrchestrator
from reality_engine.reporting.writer import ReportWriter
from reality_engine.agent.tools import get_market_breadth_overview

logger = logging.getLogger("reality_engine.dashboard")

# ====================================================================
# Page Configuration & Dark Financial Terminal Theme
# ====================================================================

st.set_page_config(
    page_title="Reality Engine - Equity Intelligence Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

CUSTOM_CSS = """
<style>
/* Dark Financial Terminal Styling */
:root {
    --bg-main: #0d1117;
    --bg-card: #161b22;
    --bg-card-hover: #1f242c;
    --border-color: #30363d;
    --text-main: #e6edf3;
    --text-muted: #8b949e;
    --accent-blue: #58a6ff;
    --accent-cyan: #38bdf8;
    --bull-green: #3fb950;
    --bear-red: #f85149;
    --warn-amber: #d29922;
    --purple: #bc8cff;
}

body, .stApp {
    background-color: var(--bg-main);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* Header & Typography */
h1, h2, h3, h4, h5, h6 {
    color: #ffffff;
    font-weight: 600;
    letter-spacing: -0.02em;
}

/* Card Styling */
.terminal-card {
    background-color: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 16px;
}

.terminal-card:hover {
    border-color: #484f58;
}

/* Metric Boxes */
.metric-box {
    background: linear-gradient(180deg, rgba(22, 27, 34, 0.9) 0%, rgba(13, 17, 23, 0.9) 100%);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 14px 16px;
    text-align: left;
}
.metric-box-title {
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
}
.metric-box-value {
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
    font-family: "SF Mono", "Segoe UI Mono", "Courier New", monospace;
    line-height: 1.2;
}
.metric-box-sub {
    font-size: 11px;
    margin-top: 4px;
    font-weight: 500;
}

/* Badges */
.badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-family: "SF Mono", monospace;
}
.badge-bull {
    background-color: rgba(63, 185, 80, 0.15);
    color: var(--bull-green);
    border: 1px solid rgba(63, 185, 80, 0.4);
}
.badge-bear {
    background-color: rgba(248, 81, 73, 0.15);
    color: var(--bear-red);
    border: 1px solid rgba(248, 81, 73, 0.4);
}
.badge-neutral {
    background-color: rgba(210, 153, 34, 0.15);
    color: var(--warn-amber);
    border: 1px solid rgba(210, 153, 34, 0.4);
}
.badge-info {
    background-color: rgba(88, 166, 255, 0.15);
    color: var(--accent-blue);
    border: 1px solid rgba(88, 166, 255, 0.4);
}
.badge-purple {
    background-color: rgba(188, 140, 255, 0.15);
    color: var(--purple);
    border: 1px solid rgba(188, 140, 255, 0.4);
}

/* Transmission Node Cards */
.transmission-node {
    background: #11151c;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
}
.transmission-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
}
.transmission-route {
    color: var(--text-muted);
    font-size: 12px;
    margin-top: 4px;
}

/* Trade Setup Card */
.trade-card {
    background-color: var(--bg-card);
    border: 1px solid var(--border-color);
    border-left: 4px solid var(--accent-blue);
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 18px;
}
.trade-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgba(48, 54, 61, 0.6);
    padding-bottom: 10px;
    margin-bottom: 12px;
}
.trade-metric-pill {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 6px 12px;
    text-align: center;
}

/* Tables */
div[data-testid="stDataFrame"] {
    border: 1px solid var(--border-color);
    border-radius: 6px;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 4px;
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: var(--text-muted);
    font-weight: 600;
    font-size: 13px;
    padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    color: #ffffff !important;
}

/* Button overrides */
.stButton > button {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    font-weight: 600;
    transition: all 0.2s ease;
}
.stButton > button:hover {
    background-color: #30363d;
    border-color: #8b949e;
    color: #ffffff;
}
.stButton > button[kind="primary"] {
    background-color: #238636;
    color: #ffffff;
    border-color: rgba(240, 246, 252, 0.1);
}
.stButton > button[kind="primary"]:hover {
    background-color: #2ea043;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ====================================================================
# Data Helpers & Cached Queries
# ====================================================================

@st.cache_data(ttl=10)
def get_available_dates() -> List[str]:
    with db_manager.session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM daily_price_delivery ORDER BY date DESC LIMIT 30"
        ).fetchall()
        # Fallback if table empty
        return [r[0] for r in rows] if rows else ["2026-08-14"]


@st.cache_data(ttl=60)
def get_all_stock_symbols() -> List[Dict[str, str]]:
    with db_manager.session() as conn:
        rows = conn.execute(
            """SELECT nse_symbol, isin, company_name, market_cap_tier, industry, is_nifty200 
               FROM master_companies WHERE is_active = 1 ORDER BY is_nifty200 DESC, nse_symbol ASC"""
        ).fetchall()
        return [dict(r) for r in rows]


@st.cache_data(ttl=30)
def query_screener(target_date: str, universe: str, top_n: int) -> pd.DataFrame:
    return composite_screener.run_screener(target_date=target_date, top_n=top_n, universe=universe)


@st.cache_data(ttl=60)
def query_market_breadth() -> Dict[str, Any]:
    return get_market_breadth_overview()


@st.cache_data(ttl=60)
def query_sector_breadth(target_date: str) -> pd.DataFrame:
    with db_manager.session() as conn:
        rows = conn.execute(
            """SELECT index_name, change_pct, advances_count, declines_count, advance_decline_ratio, pe_ratio, pb_ratio 
               FROM nse_index_breadth WHERE date = ? ORDER BY change_pct DESC""",
            (target_date,)
        ).fetchall()
        if rows:
            return pd.DataFrame([dict(r) for r in rows])
        # Fallback query from daily_price_delivery joined with master_companies
        sec_rows = conn.execute(
            """SELECT c.industry as index_name, 
                      ROUND(AVG(p.change_pct), 2) as change_pct,
                      SUM(CASE WHEN p.change_pct > 0 THEN 1 ELSE 0 END) as advances_count,
                      SUM(CASE WHEN p.change_pct < 0 THEN 1 ELSE 0 END) as declines_count,
                      ROUND(CAST(SUM(CASE WHEN p.change_pct > 0 THEN 1 ELSE 0 END) AS REAL) / 
                            MAX(1, SUM(CASE WHEN p.change_pct < 0 THEN 1 ELSE 0 END)), 2) as advance_decline_ratio,
                      0.0 as pe_ratio, 0.0 as pb_ratio
               FROM daily_price_delivery p
               JOIN master_companies c ON p.symbol = c.nse_symbol
               WHERE p.date = ? AND c.industry IS NOT NULL AND c.industry != ''
               GROUP BY c.industry
               ORDER BY change_pct DESC""",
            (target_date,)
        ).fetchall()
        return pd.DataFrame([dict(r) for r in sec_rows])


# ====================================================================
# Sidebar Controls & Global State
# ====================================================================

dates = get_available_dates()
latest_date = dates[0] if dates else "2026-08-14"

with st.sidebar:
    st.markdown(
        """
        <div style="padding: 10px 0 16px 0;">
            <div style="font-size: 20px; font-weight: 800; color: #ffffff; letter-spacing: -0.03em;">
                ⚡ REALITY ENGINE
            </div>
            <div style="font-size: 11px; color: #8b949e; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">
                Institutional Equity Terminal
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.markdown("---")
    
    selected_date = st.selectbox("📅 Valuation Session Date", options=dates, index=0)
    
    st.markdown("### ⚙️ System Controls")
    
    col_sb1, col_sb2 = st.columns(2)
    with col_sb1:
        if st.button("🌱 Seed Graph", use_container_width=True, help="Seed canonical macro causal graph and ontologies"):
            with st.spinner("Seeding canonical ontologies & graph..."):
                distillation_engine.seed_canonical_company_parameters()
                macro_simulator.seed_canonical_causal_graph()
                st.success("Knowledge Graph Seeded!")
    with col_sb2:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    st.markdown("---")
    st.markdown("### 📦 Incremental One-Stop Fetcher")
    st.caption("Last 60 sessions where not onboarded. Max period (5y price + 5y financials) is auto-handled by pipeline — you don't need to trigger it.")
    if st.button("⬇️ Fetch Last 60 Sessions (incremental)", use_container_width=True, help="Backfill missing last 60 trading sessions only via HistoricalBackfillManager"):
        with st.spinner("Backfilling last 60 sessions incremental..."):
            from reality_engine.pipeline.backfill import backfill_manager
            inserted = backfill_manager.backfill_bhavcopy_history(days_count=60)
            st.success(f"Incremental backfill done! {inserted} rows upserted. 60-session window synced.")
            st.cache_data.clear()
    if st.button("🧹 Prune & Distill", use_container_width=True, help="CALL prune_decayed_signals() + run-distillation 20+4"):
        with st.spinner("Pruning embeddings >12m & distilling 24 vectors..."):
            try:
                import reality_engine.processing.pruning_engine as pe
                if hasattr(pe, "prune_decayed_signals"):
                    pe.prune_decayed_signals(dry_run=False)  # type: ignore
                else:
                    raise AttributeError
            except Exception:
                import subprocess
                subprocess.run(["python", "reality_engine/cli.py", "prune-decayed-signals"], check=False)
            from reality_engine.processing.distillation_pruner import run_monthly_distillation
            run_monthly_distillation()
            st.success("Lifecycle pruned & distilled — vectors reclaimed.")
            st.cache_data.clear()

    st.markdown("---")
    
    # DB Stats summary
    with db_manager.session() as conn:
        n_comp = conn.execute("SELECT count(*) FROM master_companies").fetchone()[0]
        n_prices = conn.execute("SELECT count(*) FROM daily_price_delivery").fetchone()[0]
        n_nodes = conn.execute("SELECT count(*) FROM graph_nodes").fetchone()[0]
        n_edges = conn.execute("SELECT count(*) FROM graph_causal_edges").fetchone()[0]
        n_params = conn.execute("SELECT count(*) FROM company_distilled_parameters").fetchone()[0]
    
    st.markdown(
        f"""
        <div style="font-size: 11px; color: #8b949e; line-height: 1.6;">
            <div><strong>Master Universe:</strong> {n_comp:,} equities</div>
            <div><strong>Price / Delivery:</strong> {n_prices:,} records</div>
            <div><strong>Causal Graph:</strong> {n_nodes} nodes | {n_edges} edges</div>
            <div><strong>Distilled Params:</strong> {n_params} parameters</div>
            <div><strong>Engine Core:</strong> SQLite WAL + LanceDB</div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ====================================================================
# Main Tabs Navigation
# ====================================================================

tab_market, tab_screener, tab_graph, tab_dossier, tab_alpha, tab_inbox = st.tabs([
    "📊 Market Overview & Regime",
    "🎯 Quantitative Screener",
    "🕸️ Causal Graph & Shocks",
    "🔍 Stock Intelligence Dossier",
    "📋 EOD Alpha Reports",
    "📥 Local Inbox Manager"
])


# ====================================================================
# TAB 1: Market Overview & Regime
# ====================================================================

with tab_market:
    st.markdown("## 📊 Market Overview & Regime Analysis")
    st.markdown(f"**Session Valuation Date:** `{selected_date}` | Real-time Market Breadth & Drawdown Panic Radar")
    
    # 1. Market Breadth Metrics Row
    breadth = query_market_breadth()
    ad_ratio = float(breadth.get("advance_decline_ratio", 1.0))
    adv_count = int(breadth.get("advances_count", 0))
    dec_count = int(breadth.get("declines_count", 0))
    regime = str(breadth.get("market_regime", "NEUTRAL"))
    
    # Check panic status
    panic_res = panic_monitor.evaluate(session_date=selected_date)
    is_panic = panic_res.get("triggered", False)
    panic_triggers = panic_res.get("triggers", [])
    
    # Determine regime badge class
    if "BULL" in regime or "EXPANSION" in regime or "UPTREND" in regime:
        regime_class = "badge-bull"
    elif "BEAR" in regime or "DISTRIBUTION" in regime or "DOWNTREND" in regime:
        regime_class = "badge-bear"
    else:
        regime_class = "badge-neutral"
        
    m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
    
    with m_col1:
        st.markdown(
            f"""
            <div class="metric-box">
                <div class="metric-box-title">Market Regime</div>
                <div class="metric-box-value"><span class="badge {regime_class}">{regime}</span></div>
                <div class="metric-box-sub" style="color: #8b949e;">Breadth Classification</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with m_col2:
        ad_color = "#3fb950" if ad_ratio >= 1.0 else "#f85149"
        st.markdown(
            f"""
            <div class="metric-box">
                <div class="metric-box-title">Advance / Decline Ratio</div>
                <div class="metric-box-value" style="color: {ad_color};">{ad_ratio:.2f}</div>
                <div class="metric-box-sub" style="color: #8b949e;">{adv_count:,} Adv / {dec_count:,} Dec</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with m_col3:
        st.markdown(
            f"""
            <div class="metric-box">
                <div class="metric-box-title">Market Advances</div>
                <div class="metric-box-value" style="color: #3fb950;">{adv_count:,}</div>
                <div class="metric-box-sub" style="color: #8b949e;">Green Scrips</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with m_col4:
        st.markdown(
            f"""
            <div class="metric-box">
                <div class="metric-box-title">Market Declines</div>
                <div class="metric-box-value" style="color: #f85149;">{dec_count:,}</div>
                <div class="metric-box-sub" style="color: #8b949e;">Red Scrips</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with m_col5:
        panic_badge = "badge-bear" if is_panic else "badge-bull"
        panic_label = "PANIC DETECTED" if is_panic else "NORMAL"
        st.markdown(
            f"""
            <div class="metric-box">
                <div class="metric-box-title">Panic Radar</div>
                <div class="metric-box-value"><span class="badge {panic_badge}">{panic_label}</span></div>
                <div class="metric-box-sub" style="color: #8b949e;">{len(panic_triggers)} Active Triggers</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # 2. Panic Radar Alert Card
    if is_panic:
        st.error(f"🚨 **PANIC RADAR TRIGGERED**: Market drawdown condition activated ({len(panic_triggers)} triggers active). High-absorption crisis bargain scanner is operational.")
        with st.expander("🔍 View Active Drawdown Triggers", expanded=True):
            for t in panic_triggers:
                st.markdown(f"- **{t}**")
    else:
        st.info("✅ **Panic Radar**: Market volatility and index drawdowns are within normal operational thresholds. No systemic panic detected.")

    # 3. Sector Performance & Breadth Breakdown
    st.markdown("### 🏢 Sector Breadth & Index Momentum")
    df_sectors = query_sector_breadth(selected_date)
    
    if not df_sectors.empty:
        col_sec_chart, col_sec_table = st.columns([1.2, 1])
        
        with col_sec_chart:
            st.markdown("#### Sector % Change Distribution")
            chart_data = df_sectors.set_index("index_name")[["change_pct"]].sort_values(by="change_pct", ascending=True)
            st.bar_chart(chart_data, horizontal=True, color="#58a6ff")
            
        with col_sec_table:
            st.markdown("#### Sector Performance Table")
            cols_to_show = ["index_name", "change_pct", "advances_count", "declines_count", "advance_decline_ratio"]
            avail_cols = [c for c in cols_to_show if c in df_sectors.columns]
            df_sec_display = df_sectors[avail_cols].rename(columns={
                "index_name": "Sector / Index",
                "change_pct": "Change %",
                "advances_count": "Adv",
                "declines_count": "Dec",
                "advance_decline_ratio": "A/D"
            })
            st.dataframe(
                df_sec_display,
                use_container_width=True,
                height=350,
                column_config={
                    "Change %": st.column_config.NumberColumn(format="%.2f%%"),
                    "A/D": st.column_config.NumberColumn(format="%.2fx")
                }
            )
    else:
        st.warning(f"No sector breadth data recorded for date {selected_date}.")


# ====================================================================
# TAB 2: Quantitative Screener
# ====================================================================

with tab_screener:
    st.markdown("## 🎯 Multi-Factor Quantitative Screener")
    st.markdown("Dynamic screening combining Rolling Momentum, Volatility Expansion, Institutional Delivery Spikes, and Forensic Solvency Gates.")
    
    # Screener Filters Container
    with st.expander("🛠️ Screener Configuration & Filter Gates", expanded=True):
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        with f_col1:
            universe_choice = st.selectbox(
                "Universe Scope",
                options=["nifty200", "all", "nifty500", "nifty50"],
                index=0,
                help="Select universe tier for candidate pool"
            )
            top_candidates_count = st.slider("Max Candidates", min_value=10, max_value=100, value=25, step=5)
        with f_col2:
            min_composite_score = st.slider("Min Composite Score", min_value=0.0, max_value=100.0, value=50.0, step=5.0)
            delivery_filter = st.selectbox(
                "Delivery Spike Filter",
                options=["All (>= 1.0x)", "Above Average (>= 1.2x)", "Strong Institutional (>= 1.5x)", "Extreme Accumulation (>= 2.0x)"],
                index=0
            )
        with f_col3:
            cap_tier = st.selectbox(
                "Market Cap Tier",
                options=["All", "LARGE", "MID", "SMALL", "MICRO"],
                index=0
            )
            solvency_filter = st.selectbox(
                "Forensic Solvency Gate",
                options=["Approved Only (Strict)", "Include Disqualified"],
                index=0
            )
        with f_col4:
            sort_by = st.selectbox(
                "Sort Results By",
                options=["composite_score", "delivery_spike_ratio", "yoy_revenue_growth_pct", "yoy_pat_growth_pct", "technical_score", "fundamental_score"],
                index=0
            )
            crisis_mode = st.checkbox("Crisis Bargain Mode (Drawdown Absorption)", value=False)

    # Execution
    if crisis_mode:
        p_res = panic_monitor.evaluate(session_date=selected_date)
        df_screener = p_res.get("crisis_bargain_list", pd.DataFrame())
        st.info(f"Screening in Crisis Bargain Mode: Found {len(df_screener)} candidates meeting high-resilience absorption criteria.")
    else:
        df_screener = query_screener(target_date=selected_date, universe=universe_choice, top_n=top_candidates_count * 2)

    if not df_screener.empty:
        # Apply filters
        df_filtered = df_screener.copy()
        
        # Min Composite Score
        if "composite_score" in df_filtered.columns:
            df_filtered = df_filtered[df_filtered["composite_score"] >= min_composite_score]
            
        # Delivery Spike Ratio Filter
        if "delivery_spike_ratio" in df_filtered.columns:
            if "1.2x" in delivery_filter:
                df_filtered = df_filtered[df_filtered["delivery_spike_ratio"] >= 1.2]
            elif "1.5x" in delivery_filter:
                df_filtered = df_filtered[df_filtered["delivery_spike_ratio"] >= 1.5]
            elif "2.0x" in delivery_filter:
                df_filtered = df_filtered[df_filtered["delivery_spike_ratio"] >= 2.0]

        # Solvency Filter
        if "is_solvency_approved" in df_filtered.columns and "Approved" in solvency_filter:
            df_filtered = df_filtered[df_filtered["is_solvency_approved"] == 1]
            
        # Market Cap Tier Filter
        if cap_tier != "All" and "market_cap_tier" in df_filtered.columns:
            df_filtered = df_filtered[df_filtered["market_cap_tier"].str.upper() == cap_tier]

        # Sort
        if sort_by in df_filtered.columns:
            df_filtered = df_filtered.sort_values(by=sort_by, ascending=False).head(top_candidates_count)

        # Re-index composite rank
        df_filtered["Rank"] = range(1, len(df_filtered) + 1)
        
        # Add conviction label
        def assign_conviction(score):
            if score >= 75.0:
                return "HIGH"
            elif score >= 55.0:
                return "MODERATE"
            return "SPECULATIVE"
            
        if "composite_score" in df_filtered.columns:
            df_filtered["Conviction"] = df_filtered["composite_score"].apply(assign_conviction)

        # Summary KPIs
        kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
        with kpi_c1:
            st.metric("Screened Candidates", len(df_filtered))
        with kpi_c2:
            avg_comp = df_filtered["composite_score"].mean() if "composite_score" in df_filtered.columns else 0.0
            st.metric("Avg Composite Score", f"{avg_comp:.1f} / 100")
        with kpi_c3:
            high_conv_cnt = (df_filtered["Conviction"] == "HIGH").sum() if "Conviction" in df_filtered.columns else 0
            st.metric("High Conviction Scrips", high_conv_cnt)
        with kpi_c4:
            max_dsr = df_filtered["delivery_spike_ratio"].max() if "delivery_spike_ratio" in df_filtered.columns else 1.0
            top_sym = df_filtered.iloc[0]["symbol"] if not df_filtered.empty else "-"
            st.metric(f"Top Spike ({top_sym})", f"{max_dsr:.2f}x")

        # Table Column Selection & Formatting
        display_cols = [
            "Rank", "symbol", "close", "change_pct", "delivery_pct", "delivery_spike_ratio",
            "Conviction", "technical_score", "fundamental_score", "composite_score",
            "yoy_revenue_growth_pct", "yoy_pat_growth_pct", "is_solvency_approved"
        ]
        avail_display = [c for c in display_cols if c in df_filtered.columns]
        
        df_table = df_filtered[avail_display].rename(columns={
            "symbol": "Symbol",
            "close": "CMP (INR)",
            "change_pct": "Change %",
            "delivery_pct": "Delivery %",
            "delivery_spike_ratio": "Spike Ratio",
            "technical_score": "Tech Score",
            "fundamental_score": "Funda Score",
            "composite_score": "Composite Score",
            "yoy_revenue_growth_pct": "YoY Rev %",
            "yoy_pat_growth_pct": "YoY PAT %",
            "is_solvency_approved": "Solvency"
        })

        st.dataframe(
            df_table,
            use_container_width=True,
            height=450,
            column_config={
                "CMP (INR)": st.column_config.NumberColumn(format="₹%.2f"),
                "Change %": st.column_config.NumberColumn(format="%.2f%%"),
                "Delivery %": st.column_config.NumberColumn(format="%.1f%%"),
                "Spike Ratio": st.column_config.NumberColumn(format="%.2fx"),
                "Tech Score": st.column_config.NumberColumn(format="%.1f"),
                "Funda Score": st.column_config.NumberColumn(format="%.1f"),
                "Composite Score": st.column_config.NumberColumn(format="%.1f"),
                "YoY Rev %": st.column_config.NumberColumn(format="%.1f%%"),
                "YoY PAT %": st.column_config.NumberColumn(format="%.1f%%"),
                "Solvency": st.column_config.CheckboxColumn("Approved")
            }
        )

        # CSV Export
        csv_data = df_table.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export Screener Results to CSV",
            data=csv_data,
            file_name=f"screener_reality_engine_{selected_date}_{universe_choice}.csv",
            mime="text/csv"
        )
    else:
        st.warning(f"No quantitative candidates matched the screening parameters for {selected_date}.")


# ====================================================================
# TAB 3: Causal Knowledge Graph & Shocks
# ====================================================================

with tab_graph:
    st.markdown("## 🕸️ Causal Knowledge Graph & Macro Shocks")
    st.markdown("Multi-hop shock transmission simulating policy shifts, commodity price changes, and geopolitical events down to Indian equities.")
    
    # 1. Shock Scenario Controls
    with st.expander("⚙️ Shock Scenario & Graph Traversal Settings", expanded=True):
        g_col1, g_col2, g_col3 = st.columns([1.5, 1, 1])
        
        # Query existing graph nodes
        graph_nodes = causal_engine.get_all_nodes()
        node_options = [n["node_id"] for n in graph_nodes if n.get("node_type") != "COMPANY"] or [
            "UNION_BUDGET_2026_RAIL_CAPEX",
            "COMMODITY_CRUDE_OIL",
            "GEOPOLITICAL_RED_SEA_ATTACKS",
            "DEFENCE_INDIGENIZATION_DAP",
            "PM_SURYA_GHAR_SOLAR"
        ]
        
        with g_col1:
            selected_shock = st.selectbox(
                "Select Macro Shock / Policy Event",
                options=node_options,
                index=0,
                help="Select an origin shock node in the causal graph"
            )
        with g_col2:
            max_hops = st.slider("Transmission Hop Depth", min_value=1, max_value=4, value=3)
        with g_col3:
            impact_filter = st.selectbox(
                "Impact Direction Filter",
                options=["ALL", "BENEFICIARIES_ONLY", "VICTIMS_ONLY"],
                index=0
            )

    # 2. Run Causal Transmission Trace & Macro Simulation
    traces = causal_engine.trace_causal_chain(start_node_id=selected_shock, max_hops=max_hops, impact_filter=impact_filter)
    sim_res = macro_simulator.simulate_macro_shock(shock_scenario=selected_shock)
    
    beneficiaries = sim_res.get("beneficiaries", [])
    victims = sim_res.get("victims", [])

    # Overview Metrics Row
    sg_col1, sg_col2, sg_col3, sg_col4 = st.columns(4)
    with sg_col1:
        st.metric("Total Transmissions", len(traces))
    with sg_col2:
        st.metric("Beneficiaries (+)", len(beneficiaries), delta=f"+{len(beneficiaries)}")
    with sg_col3:
        st.metric("Victims / Impaired (-)", len(victims), delta=f"-{len(victims)}", delta_color="inverse")
    with sg_col4:
        avg_elasticity = np.mean([abs(t.get("cumulative_impact", 1.0)) for t in traces]) if traces else 0.0
        st.metric("Avg Shock Elasticity", f"{avg_elasticity:.2f}x")

    st.markdown("---")

    # 3. Transmission Routes Visualization & Cards
    st.markdown("### ⚡ Causal Transmission Paths")
    
    if traces:
        for idx, t in enumerate(traces, 1):
            impact_val = float(t.get("cumulative_impact", 1.0))
            is_pos = impact_val >= 0
            badge_class = "badge-bull" if is_pos else "badge-bear"
            badge_text = "BENEFICIARY" if is_pos else "VICTIM"
            sign_prefix = "+" if is_pos else ""
            
            st.markdown(
                f"""
                <div class="transmission-node">
                    <div class="transmission-header">
                        <div>
                            <span style="font-weight: 700; color: #ffffff; font-size: 14px;">#{idx} {t.get('name', t.get('node_id'))}</span>
                            <span style="font-size: 11px; color: #8b949e; margin-left: 8px;">[{t.get('node_type')}]</span>
                        </div>
                        <div>
                            <span class="badge {badge_class}">{badge_text} ({sign_prefix}{impact_val:.2f}x)</span>
                            <span class="badge badge-info" style="margin-left: 6px;">Hop {t.get('depth')}</span>
                        </div>
                    </div>
                    <div class="transmission-route">
                        <strong>Transmission Mechanism:</strong> {t.get('mechanisms') or 'Direct primary transmission'}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
        # Beneficiaries vs Victims breakdown
        st.markdown("<br>", unsafe_allow_html=True)
        col_b, col_v = st.columns(2)
        
        with col_b:
            st.markdown("#### 🟢 High-Resilience Beneficiaries")
            if beneficiaries:
                b_df = pd.DataFrame([{
                    "Symbol": b["symbol"],
                    "Hop": f"Hop {b['depth']}",
                    "Elasticity": f"+{b['impact']:.2f}x",
                    "Mechanism": b["mechanisms"]
                } for b in beneficiaries])
                st.dataframe(b_df, use_container_width=True, hide_index=True)
            else:
                st.info("No direct beneficiaries under this filter.")
                
        with col_v:
            st.markdown("#### 🔴 Vulnerable / Cost Impaired")
            if victims:
                v_df = pd.DataFrame([{
                    "Symbol": v["symbol"],
                    "Hop": f"Hop {v['depth']}",
                    "Elasticity": f"{v['impact']:.2f}x",
                    "Mechanism": v["mechanisms"]
                } for v in victims])
                st.dataframe(v_df, use_container_width=True, hide_index=True)
            else:
                st.info("No cost victims under this filter.")
    else:
        st.warning(f"No causal transmission paths found from '{selected_shock}'. Click 'Seed Graph' in the sidebar to populate canonical macro relationships.")


# ====================================================================
# TAB 4: Stock Intelligence Dossier
# ====================================================================

with tab_dossier:
    st.markdown("## 🔍 Stock Intelligence Dossier")
    st.markdown("Institutional forensic analysis across Price/Delivery Flow, Solvency Health, Distilled Ontologies, and Concall Guidance.")
    
    # Stock Search & Quick Buttons
    all_symbols = get_all_stock_symbols()
    sym_list = [s["nse_symbol"] for s in all_symbols] or ["HAL", "TITAGARH", "KAYNES", "PIDILITIND", "RELIANCE", "ASIANPAINT", "SCI", "HAVELLS"]
    
    st.markdown("**Quick Access High-Conviction Scrips:**")
    quick_cols = st.columns(8)
    preset_syms = ["HAL", "TITAGARH", "KAYNES", "PIDILITIND", "RELIANCE", "ASIANPAINT", "SCI", "HAVELLS"]
    
    # Store selected symbol in session state
    if "selected_stock" not in st.session_state:
        st.session_state["selected_stock"] = "HAL"
        
    for idx, psym in enumerate(preset_syms):
        with quick_cols[idx]:
            if st.button(psym, key=f"quick_{psym}", use_container_width=True):
                st.session_state["selected_stock"] = psym
                st.rerun()

    cur_idx = sym_list.index(st.session_state["selected_stock"]) if st.session_state["selected_stock"] in sym_list else 0
    selected_stock = st.selectbox(
        "🔎 Search Stock Symbol",
        options=sym_list,
        index=cur_idx,
        help="Type or select any stock symbol across NSE universe"
    )
    st.session_state["selected_stock"] = selected_stock

    # Fetch Company Metadata
    comp = repo.get_company_by_symbol(selected_stock)
    if comp:
        comp_name = comp.get("company_name", selected_stock)
        isin = comp.get("isin", "")
        industry = comp.get("industry", "Diversified")
        cap_tier = comp.get("market_cap_tier", "MID")
        is_n50 = bool(comp.get("is_nifty50"))
        is_n200 = bool(comp.get("is_nifty200"))
        is_n500 = bool(comp.get("is_nifty500"))
        
        # Header Badge
        n50_badge = '<span class="badge badge-purple" style="margin-right: 4px;">NIFTY 50</span>' if is_n50 else ""
        n200_badge = '<span class="badge badge-info" style="margin-right: 4px;">NIFTY 200</span>' if is_n200 else ""
        n500_badge = '<span class="badge badge-neutral" style="margin-right: 4px;">NIFTY 500</span>' if is_n500 else ""
        
        st.markdown(
            f"""
            <div class="terminal-card" style="margin-top: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-size: 24px; font-weight: 800; color: #ffffff;">{selected_stock}</span>
                        <span style="font-size: 16px; color: #8b949e; margin-left: 10px;">{comp_name}</span>
                    </div>
                    <div>
                        {n50_badge}{n200_badge}{n500_badge}
                        <span class="badge badge-info">{cap_tier} CAP</span>
                    </div>
                </div>
                <div style="font-size: 12px; color: #8b949e; margin-top: 6px;">
                    <strong>ISIN:</strong> <code>{isin}</code> | <strong>BSE Code:</strong> <code>{comp.get('bse_code', 'N/A')}</code> | <strong>Industry:</strong> {industry}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        # 1. Technical & Delivery Metrics
        st.markdown("### 📈 Technical & Institutional Delivery Flow")
        df_price = repo.get_price_history(selected_stock, limit=25)
        
        if not df_price.empty:
            latest_p = df_price.iloc[-1]
            cmp_val = float(latest_p.get("close") or 0.0)
            chg_val = float(latest_p.get("change_pct") or 0.0)
            deliv_pct = float(latest_p.get("delivery_pct") or 0.0)
            dsr_val = float(latest_p.get("delivery_spike_ratio") or 1.0)
            dcs_val = float(latest_p.get("delivery_conviction_score") or 0.0)
            rsi_val = float(latest_p.get("rsi_14") or 50.0)
            sma20_val = float(latest_p.get("sma_20") or 0.0)
            dist_52w = float(latest_p.get("distance_from_52w_high_pct") or 0.0)
            
            p_col1, p_col2, p_col3, p_col4, p_col5 = st.columns(5)
            with p_col1:
                chg_color = "#3fb950" if chg_val >= 0 else "#f85149"
                st.markdown(
                    f"""
                    <div class="metric-box">
                        <div class="metric-box-title">CMP (INR)</div>
                        <div class="metric-box-value">₹{cmp_val:,.2f}</div>
                        <div class="metric-box-sub" style="color: {chg_color};">{chg_val:+.2f}% Session</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with p_col2:
                st.markdown(
                    f"""
                    <div class="metric-box">
                        <div class="metric-box-title">Delivery %</div>
                        <div class="metric-box-value" style="color: #38bdf8;">{deliv_pct:.1f}%</div>
                        <div class="metric-box-sub" style="color: #8b949e;">Deliverable Share</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with p_col3:
                dsr_color = "#3fb950" if dsr_val >= 1.5 else "#8b949e"
                st.markdown(
                    f"""
                    <div class="metric-box">
                        <div class="metric-box-title">Delivery Spike Ratio</div>
                        <div class="metric-box-value" style="color: {dsr_color};">{dsr_val:.2f}x</div>
                        <div class="metric-box-sub" style="color: #8b949e;">vs 20-Day Avg Vol</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with p_col4:
                rsi_color = "#bc8cff" if 55.0 <= rsi_val <= 75.0 else "#8b949e"
                st.markdown(
                    f"""
                    <div class="metric-box">
                        <div class="metric-box-title">RSI (14-Day)</div>
                        <div class="metric-box-value" style="color: {rsi_color};">{rsi_val:.1f}</div>
                        <div class="metric-box-sub" style="color: #8b949e;">Momentum Oscillator</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with p_col5:
                st.markdown(
                    f"""
                    <div class="metric-box">
                        <div class="metric-box-title">Dist from 52W High</div>
                        <div class="metric-box-value">{dist_52w:.1f}%</div>
                        <div class="metric-box-sub" style="color: #8b949e;">SMA 20: ₹{sma20_val:,.1f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            # Price & Delivery Chart
            st.markdown("<br>", unsafe_allow_html=True)
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.markdown("#### Historical Close Price (INR)")
                st.line_chart(df_price.set_index("date")["close"], color="#38bdf8")
            with chart_col2:
                st.markdown("#### Delivery Volume & Spike History")
                st.bar_chart(df_price.set_index("date")["deliverable_volume"], color="#3fb950")
        else:
            st.info("No historical price/delivery records found for this symbol.")

        st.markdown("---")

        # 2. Quarterly Financials & Solvency Health
        st.markdown("### 📑 Quarterly Financials & Forensic Solvency")
        funda_col, solv_col = st.columns([1.3, 1])
        
        with funda_col:
            df_q = repo.get_quarterly_financials_history(selected_stock, quarters=6)
            if not df_q.empty:
                st.markdown("#### Recent Quarterly P&L Performance")
                q_cols = ["quarter_end_date", "financial_year", "revenue_inr_cr", "ebitda_inr_cr", "ebitda_margin_pct", "net_profit_inr_cr", "yoy_revenue_growth_pct", "yoy_pat_growth_pct"]
                avail_q = [c for c in q_cols if c in df_q.columns]
                df_q_show = df_q[avail_q].rename(columns={
                    "quarter_end_date": "Quarter End",
                    "financial_year": "FY",
                    "revenue_inr_cr": "Rev (Cr)",
                    "ebitda_inr_cr": "EBITDA (Cr)",
                    "ebitda_margin_pct": "OPM %",
                    "net_profit_inr_cr": "PAT (Cr)",
                    "yoy_revenue_growth_pct": "YoY Rev %",
                    "yoy_pat_growth_pct": "YoY PAT %"
                })
                st.dataframe(
                    df_q_show,
                    use_container_width=True,
                    height=240,
                    column_config={
                        "Rev (Cr)": st.column_config.NumberColumn(format="₹%,.1f"),
                        "EBITDA (Cr)": st.column_config.NumberColumn(format="₹%,.1f"),
                        "OPM %": st.column_config.NumberColumn(format="%.1f%%"),
                        "PAT (Cr)": st.column_config.NumberColumn(format="₹%,.1f"),
                        "YoY Rev %": st.column_config.NumberColumn(format="%.1f%%"),
                        "YoY PAT %": st.column_config.NumberColumn(format="%.1f%%")
                    }
                )
            else:
                st.info("No quarterly financial statements stored for this symbol.")
                
        with solv_col:
            st.markdown("#### Forensic Solvency & Governance Gates")
            df_f = repo.get_forensic_health(selected_stock)
            if not df_f.empty:
                f_row = df_f.iloc[-1]
                is_appr = int(f_row.get("is_solvency_approved") or 0) == 1
                solv_badge = '<span class="badge badge-bull">SOLVENCY APPROVED</span>' if is_appr else '<span class="badge badge-bear">SOLVENCY DISQUALIFIED</span>'
                
                st.markdown(
                    f"""
                    <div class="terminal-card">
                        <div style="margin-bottom: 12px;">{solv_badge}</div>
                        <div style="font-size: 13px; line-height: 1.8; color: #c9d1d9;">
                            <div><strong>Promoter Holding:</strong> {f_row.get('promoter_holding_pct', 0.0)}% | <strong>Pledged:</strong> {f_row.get('promoter_pledge_pct', 0.0)}%</div>
                            <div><strong>Institutional:</strong> FII {f_row.get('fii_holding_pct', 0.0)}% | DII {f_row.get('dii_holding_pct', 0.0)}%</div>
                            <div><strong>Solvency Coverage:</strong> Interest {f_row.get('interest_coverage_ratio', 0.0)}x | D/E {f_row.get('debt_to_equity_ratio', 0.0)}x</div>
                            <div><strong>Valuation:</strong> P/E {f_row.get('pe_ratio', 'N/A')} | P/B {f_row.get('pb_ratio', 'N/A')} | MCap ₹{f_row.get('market_cap_inr_cr', 0.0):,.0f} Cr</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                if not is_appr and f_row.get("solvency_disqualification_reasons"):
                    st.error(f"Disqualification Note: {f_row.get('solvency_disqualification_reasons')}")
            else:
                st.info("Forensic health assessment not yet computed.")

        st.markdown("---")

        # 3. Distilled Parameters & Business Sensitivities
        st.markdown("### 🧩 Distilled Parameters & Structural Sensitivities")
        distilled = distillation_engine.get_distilled_parameters(selected_stock)
        
        if distilled:
            d_cols = st.columns(len(distilled) if len(distilled) <= 3 else 3)
            for idx, dp in enumerate(distilled):
                target_col = d_cols[idx % 3]
                with target_col:
                    pkey = dp.get("parameter_key", "").replace("_", " ").title()
                    pval = dp.get("value")
                    with st.container():
                        st.markdown(
                            f"""
                            <div class="terminal-card">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                    <span style="font-weight: 700; color: #58a6ff; font-size: 13px;">{pkey}</span>
                                    <span class="badge badge-info">{dp.get('confidence_score', 1.0)*100:.0f}% Conf</span>
                                </div>
                            """,
                            unsafe_allow_html=True
                        )
                        if isinstance(pval, dict):
                            for k, v in pval.items():
                                clean_k = k.replace("_", " ").title()
                                st.markdown(f"<div style='font-size: 12px; color: #c9d1d9;'><strong>{clean_k}:</strong> {v}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div style='font-size: 12px; color: #c9d1d9;'>{pval}</div>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("No dynamic distilled parameters seeded for this symbol. Click 'Seed Graph' in the sidebar to populate standard parameters.")

        st.markdown("---")

        # 4. Hybrid Concall Guidance Search Box
        st.markdown("### 🎙️ Hybrid Concall Transcript & Guidance Search")
        search_query = st.text_input(
            "Search Concall & Guidance Excerpts",
            value="capex order book guidance expansion margin export",
            help="Enter search query for hybrid lexical + dense search over investor transcripts"
        )
        
        if search_query:
            searcher = HybridSearchEngine()
            hits = searcher.search(query=search_query, symbol=selected_stock, top_k=3)
            if hits:
                for idx, h in enumerate(hits, 1):
                    st.markdown(
                        f"""
                        <div class="terminal-card" style="border-left: 3px solid #bc8cff;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                                <span style="font-weight: 700; color: #bc8cff; font-size: 13px;">Transcript Match #{idx}</span>
                                <span class="badge badge-purple">RRF Score: {h.score:.4f} | Citation: {h.citation}</span>
                            </div>
                            <div style="font-size: 13px; color: #e6edf3; font-style: italic;">
                                "{h.text}"
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            else:
                st.info(f"No concall transcripts matching '{search_query}' found for {selected_stock}.")
    else:
        st.error(f"Stock symbol '{selected_stock}' not found in master companies database.")


# ====================================================================
# TAB 5: EOD Alpha Reports
# ====================================================================

with tab_alpha:
    st.markdown("## 📋 EOD Alpha & Institutional Trade Theses")
    st.markdown("Validated high-conviction alpha theses with actionable entry, target, stop loss, catalysts, and invalidation criteria.")

    # Action Row
    top_a_col1, top_a_col2, top_a_col3 = st.columns([1.5, 1, 1])
    
    with top_a_col1:
        st.markdown(f"**Target Report Session:** `{selected_date}`")
    with top_a_col2:
        report_universe = st.selectbox("Report Universe", options=["NIFTY200", "ALL"], index=0)
    with top_a_col3:
        if st.button("🚀 Generate Fresh Alpha Report", type="primary", use_container_width=True):
            with st.spinner("Executing Agent Orchestrator & synthesizing theses..."):
                orch = AgentOrchestrator()
                fresh_report = orch.synthesize_daily_alpha_report(
                    target_date=selected_date,
                    universe=report_universe.lower(),
                    top_n=5,
                    screener_pool_size=20
                )
                writer = ReportWriter()
                writer.export_daily_alpha_report(fresh_report)
                st.success(f"Daily Alpha Report generated for {selected_date}!")
                st.cache_data.clear()
                st.rerun()

    # Load Existing Report
    report_file = REPORTS_DIR / selected_date / "daily_alpha.json"
    if not report_file.exists():
        # Fallback check any available report folder
        available_reports = list(REPORTS_DIR.glob("*/daily_alpha.json"))
        if available_reports:
            report_file = available_reports[0]
            
    if report_file.exists():
        try:
            with open(report_file, "r", encoding="utf-8") as rf:
                report_data = json.load(rf)
                
            mb_data = report_data.get("market_breadth", {})
            theses_list = report_data.get("high_conviction_theses", [])
            
            # Market Overview Bar
            st.markdown(
                f"""
                <div class="terminal-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-weight: 700; font-size: 16px; color: #ffffff;">Executive Market Breadth:</span>
                            <span class="badge badge-bull" style="margin-left: 8px;">{mb_data.get('market_regime', 'EXPANSION')}</span>
                        </div>
                        <div>
                            <span style="color: #8b949e; font-size: 13px;">Advance / Decline: <strong>{mb_data.get('advance_decline_ratio', 1.0):.2f}</strong></span>
                            <span style="color: #8b949e; font-size: 13px; margin-left: 14px;">Filtered Disqualifications: <strong>{report_data.get('disqualified_solvency_count', 0)}</strong></span>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Summary Table
            st.markdown("### 🏆 Top High-Conviction Candidates")
            summary_theses = []
            for t in theses_list:
                summary_theses.append({
                    "Rank": f"#{t.get('composite_rank')}",
                    "Symbol": t.get("symbol"),
                    "Company": t.get("company_name"),
                    "CMP (INR)": f"₹{t.get('current_market_price', 0.0):,.2f}",
                    "Entry Range": t.get("recommended_entry_range"),
                    "Target": f"₹{t.get('target_price', 0.0):,.2f}",
                    "Stop Loss": f"₹{t.get('stop_loss', 0.0):,.2f}",
                    "R:R": f"{t.get('risk_reward_ratio', 3.0):.1f}x",
                    "Conviction": t.get("conviction_level")
                })
            st.dataframe(pd.DataFrame(summary_theses), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("### 📜 Deep Scrip Alpha Theses & Trade Setups")

            # Trade Setup Cards
            for t in theses_list:
                sym = t.get("symbol")
                cmp_val = float(t.get("current_market_price", 0.0))
                tgt_val = float(t.get("target_price", 0.0))
                sl_val = float(t.get("stop_loss", 0.0))
                upside_pct = ((tgt_val - cmp_val) / max(1.0, cmp_val)) * 100
                risk_pct = ((cmp_val - sl_val) / max(1.0, cmp_val)) * 100
                rr = float(t.get("risk_reward_ratio", 3.0))
                conv = t.get("conviction_level", "HIGH_CONVICTION")
                
                st.markdown(
                    f"""
                    <div class="trade-card">
                        <div class="trade-card-header">
                            <div>
                                <span style="font-size: 18px; font-weight: 800; color: #ffffff;">#{t.get('composite_rank')} {sym}</span>
                                <span style="font-size: 14px; color: #8b949e; margin-left: 8px;">- {t.get('company_name')}</span>
                            </div>
                            <div>
                                <span class="badge badge-bull">{conv}</span>
                                <span class="badge badge-info" style="margin-left: 6px;">R:R {rr:.1f}x</span>
                            </div>
                        </div>
                        
                        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px;">
                            <div class="trade-metric-pill">
                                <div style="font-size: 10px; color: #8b949e; text-transform: uppercase;">Entry Range</div>
                                <div style="font-size: 14px; font-weight: 700; color: #ffffff;">{t.get('recommended_entry_range')}</div>
                            </div>
                            <div class="trade-metric-pill">
                                <div style="font-size: 10px; color: #8b949e; text-transform: uppercase;">Target Price</div>
                                <div style="font-size: 14px; font-weight: 700; color: #3fb950;">₹{tgt_val:,.2f} (+{upside_pct:.1f}%)</div>
                            </div>
                            <div class="trade-metric-pill">
                                <div style="font-size: 10px; color: #8b949e; text-transform: uppercase;">Stop Loss</div>
                                <div style="font-size: 14px; font-weight: 700; color: #f85149;">₹{sl_val:,.2f} (-{risk_pct:.1f}%)</div>
                            </div>
                            <div class="trade-metric-pill">
                                <div style="font-size: 10px; color: #8b949e; text-transform: uppercase;">Horizon</div>
                                <div style="font-size: 14px; font-weight: 700; color: #38bdf8;">{t.get('time_horizon', '1 - 3 Months')}</div>
                            </div>
                        </div>
                        
                        <div style="margin-bottom: 10px;">
                            <div style="font-size: 12px; font-weight: 700; color: #58a6ff; text-transform: uppercase; margin-bottom: 4px;">Investment Thesis</div>
                            <div style="font-size: 13px; color: #c9d1d9; line-height: 1.5;">{t.get('investment_thesis')}</div>
                        </div>
                        
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 10px;">
                            <div>
                                <div style="font-size: 11px; font-weight: 700; color: #3fb950; text-transform: uppercase; margin-bottom: 4px;">Key Catalysts</div>
                                <ul style="margin: 0; padding-left: 18px; font-size: 12px; color: #c9d1d9;">
                                    {"".join(f"<li>{c}</li>" for c in t.get('catalysts', []))}
                                </ul>
                            </div>
                            <div>
                                <div style="font-size: 11px; font-weight: 700; color: #f85149; text-transform: uppercase; margin-bottom: 4px;">Risks & Invalidation Rules</div>
                                <ul style="margin: 0; padding-left: 18px; font-size: 12px; color: #c9d1d9;">
                                    {"".join(f"<li>{r}</li>" for r in t.get('risks', []))}
                                </ul>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            # Export options
            st.markdown("### 📥 Report Export Downloads")
            dl_c1, dl_c2, dl_c3 = st.columns(3)
            
            md_path = report_file.parent / "daily_alpha.md"
            html_path = report_file.parent / "daily_alpha.html"
            
            with dl_c1:
                st.download_button(
                    "📄 Download JSON",
                    data=json.dumps(report_data, indent=2),
                    file_name=f"daily_alpha_{selected_date}.json",
                    mime="application/json",
                    use_container_width=True
                )
            with dl_c2:
                if md_path.exists():
                    st.download_button(
                        "📝 Download Markdown",
                        data=md_path.read_text(encoding="utf-8"),
                        file_name=f"daily_alpha_{selected_date}.md",
                        mime="text/markdown",
                        use_container_width=True
                    )
            with dl_c3:
                if html_path.exists():
                    st.download_button(
                        "🌐 Download HTML",
                        data=html_path.read_text(encoding="utf-8"),
                        file_name=f"daily_alpha_{selected_date}.html",
                        mime="text/html",
                        use_container_width=True
                    )

        except Exception as ex:
            st.error(f"Error reading report {report_file}: {ex}")
    else:
        st.info(f"No Daily Alpha Report currently saved for {selected_date}. Click 'Generate Fresh Alpha Report' above to synthesize a report.")


# ====================================================================
# TAB 6: Local Inbox Manager
# ====================================================================

with tab_inbox:
    st.markdown("## 📥 Local Drop-in Inbox Manager")
    st.markdown("Ingest research reports, investor presentations, concall transcripts, and financial screenshots via the local inbox pipeline.")

    inbox_runner = InboxRunner()
    inbox_base = inbox_runner.inbox

    # 1. File Upload Dropzone
    st.markdown("### 📤 Upload Documents to Local Inbox")
    uploaded_files = st.file_uploader(
        "Drop files here (PDFs, Images, or Text documents)",
        accept_multiple_files=True,
        type=["pdf", "png", "jpg", "jpeg", "webp", "txt"]
    )
    
    if uploaded_files:
        saved_count = 0
        for uf in uploaded_files:
            suffix = Path(uf.name).suffix.lower()
            if suffix == ".pdf":
                target_sub = inbox_base / "pdfs"
            elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                target_sub = inbox_base / "images"
            else:
                target_sub = inbox_base / "text"
            target_sub.mkdir(parents=True, exist_ok=True)
            
            dest_file = target_sub / uf.name
            with open(dest_file, "wb") as f:
                f.write(uf.getbuffer())
            saved_count += 1
        st.success(f"Successfully staged {saved_count} files into `{inbox_base}`!")

    st.markdown("---")

    # 2. Inbox Folders Status Overview
    likes_dir = inbox_base / "likes"
    likes_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = list((inbox_base / "pdfs").glob("*.*")) if (inbox_base / "pdfs").exists() else []
    img_files = list((inbox_base / "images").glob("*.*")) if (inbox_base / "images").exists() else []
    txt_files = list((inbox_base / "text").glob("*.*")) if (inbox_base / "text").exists() else []
    proc_files = list((inbox_base / "processed").glob("*.*")) if (inbox_base / "processed").exists() else []
    fail_files = list((inbox_base / "failed").glob("*.*")) if (inbox_base / "failed").exists() else []
    likes_files = list(likes_dir.glob("*.*"))

    st.markdown("### 📁 Inbox Folder Staging Status")
    ib_c1, ib_c2, ib_c3, ib_c4, ib_c5, ib_c6 = st.columns(6)
    with ib_c1:
        st.metric("Pending PDFs", len(pdf_files))
    with ib_c2:
        st.metric("Pending Images", len(img_files))
    with ib_c3:
        st.metric("Pending Text", len(txt_files))
    with ib_c4:
        st.metric("Processed Files", len(proc_files))
    with ib_c5:
        st.metric("Failed Files", len(fail_files))
    with ib_c6:
        st.metric("Liked / Pinned", len(likes_files))

    total_pending = len(pdf_files) + len(img_files) + len(txt_files)
    
    # 3. Action Button to Run Inbox Pipeline
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⚡ Scan & Process Inbox Files", type="primary", use_container_width=True):
        with st.spinner("Scanning inbox and running extraction & indexing pipeline..."):
            results = inbox_runner.run()
            if results:
                st.success(f"Processed {len(results)} files successfully!")
                for r in results:
                    st.write(f"- `{Path(r['path']).name}`: **{r.get('status')}** ({r.get('chunks', 0)} chunks indexed)")
            else:
                st.info("Inbox is clean. No pending files to process.")
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")

    # 4. SHA-256 Manifest Explorer
    st.markdown("### 📑 Ingestion Manifest Audit Log (SHA-256 Hashes)")
    with db_manager.session() as conn:
        manifest_rows = conn.execute(
            """SELECT file_hash, original_filename, file_type, detected_entity_type, 
                      summary, processed_file_path, ingested_timestamp 
               FROM inbox_ingestion_manifest ORDER BY ingested_timestamp DESC LIMIT 50"""
        ).fetchall()

    if manifest_rows:
        df_manifest = pd.DataFrame([dict(r) for r in manifest_rows])
        st.dataframe(
            df_manifest,
            use_container_width=True,
            height=300,
            column_config={
                "file_hash": st.column_config.TextColumn("SHA-256 Hash"),
                "original_filename": "Filename",
                "file_type": "Format",
                "summary": "Indexing Summary",
                "ingested_timestamp": "Timestamp"
            }
        )
    else:
        st.info("No files currently recorded in the SHA-256 inbox manifest table.")
