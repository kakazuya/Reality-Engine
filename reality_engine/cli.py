"""
Reality Engine CLI Tool
Unified Command-Line Interface for running data ingestion pipelines, quantitative screening,
causal macro graph analysis, agent synthesis, panic monitoring, concall search, and Streamlit dashboard.
"""

from __future__ import annotations

import sys
import json
import argparse
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

logger = logging.getLogger("reality_engine.cli")

# Add project root to Python path
ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.repository import repo
from reality_engine.ingestion.master_sync import master_sync
from reality_engine.ingestion.fundamentals_client import fundamentals_client
from reality_engine.pipeline.backfill import backfill_manager
from reality_engine.pipeline.phase1_runner import phase1_runner
from reality_engine.pipeline.panic_monitor import panic_monitor
from reality_engine.pipeline.inbox_runner import InboxRunner
from reality_engine.pipeline.bootstrap import bootstrap_manager, BootstrapManager
from reality_engine.processing.composite_screener import composite_screener
from reality_engine.processing.causal_engine import causal_engine
from reality_engine.processing.macro_simulator import macro_simulator
from reality_engine.processing.distillation_engine import distillation_engine
from reality_engine.search.hybrid_search import HybridSearchEngine
from reality_engine.agent.orchestrator import AgentOrchestrator
from reality_engine.reporting.writer import ReportWriter
from reality_engine.ingestion.telegram_client import TelegramListener, telegram_listener
from reality_engine.processing.event_graph import cmd_spawn_event_graph
from reality_engine.processing.eod_corrector import cmd_correct_eod, cmd_correct_event, cmd_noise_floor


# ====================================================================
# Command Handlers
# ====================================================================

def cmd_run_phase1(args):
    """Executes the complete Phase 1 pipeline."""
    print("\n" + "=" * 75)
    print("  LAUNCHING REALITY ENGINE PHASE 1 PIPELINE")
    print("=" * 75)
    result = phase1_runner.run_phase1_pipeline(
        bhavcopy_sessions=args.days,
        target_universe_count=args.top,
        max_workers=args.workers
    )
    print("\n>>> PIPELINE EXECUTION SUMMARY <<<")
    print(f"Total Execution Time    : {result['execution_time_seconds']}s")
    print(f"Master Companies Stored : {result['master_companies_count']}")
    print(f"Bhavcopy Rows Ingested  : {result['bhavcopy_rows']}")
    print(f"Quarterly Financials    : {result['quarterly_financials_rows']}")
    print(f"Annual Financials       : {result['annual_financials_rows']}")
    print(f"Forensic Solvency Health: {result['forensic_records_count']}")
    print(f"SEBI PIT Insider Trades : {result['insider_trades_count']}")
    print(f"Checkpoint Passed       : {result['checkpoint']['checkpoint_passed']}")
    print(f"Report Generated at     : {result['checkpoint']['exported_csv_report']}")


def cmd_screen(args):
    """Runs composite multi-factor screener or crisis bargain screener."""
    date_str = args.date or repo.get_latest_price_delivery_date()
    universe = getattr(args, "universe", "nifty200")
    
    if getattr(args, "crisis", False):
        print(f"\nRunning Panic & Crisis Bargain Scanner for date: {date_str}...\n")
        res = panic_monitor.evaluate(session_date=date_str)
        print("=" * 75)
        print(f"  PANIC MONITOR STATUS: {'TRIGGERED (PANIC DETECTED)' if res['triggered'] else 'NORMAL (NO PANIC)'}")
        print("=" * 75)
        if res["triggers"]:
            print(f"\nActive Drawdown Triggers ({len(res['triggers'])}):")
            for t in res["triggers"]:
                print(f"  - {t}")
        bargains = res["crisis_bargain_list"]
        if not bargains.empty:
            print(f"\n>>> CRISIS BARGAIN LIST ({len(bargains)} candidates) <<<")
            cols = [
                "composite_rank", "symbol", "close", "change_pct", "delivery_pct",
                "delivery_spike_ratio", "technical_score", "fundamental_score",
                "causal_resilience_score", "smart_money_score", "composite_score"
            ]
            avail_cols = [c for c in cols if c in bargains.columns]
            pd.set_option("display.max_columns", 15)
            pd.set_option("display.width", 1000)
            print(bargains[avail_cols].to_string(index=False))
        else:
            print("\nNo crisis bargain candidates found meeting absorption & solvency criteria.")
        return

    top_down = getattr(args, "top_down", False)
    ensemble = getattr(args, "ensemble", False)
    dry_run = getattr(args, "dry_run", False)

    # Wave D4: all-peers weighted ensemble screen (Σ w_lens * norm(lens_score) + per-scrip noise floor).
    if ensemble:
        print(f"\nRunning All-Peers Weighted Ensemble Screener (MoE blend) for date: {date_str} "
              f"(Universe: {universe.upper()}, Top {args.top})...\n")
        df_screened = composite_screener.ensemble_screen(target_date=date_str, top_n=args.top, universe=universe)
        if df_screened.empty:
            print("No ensemble candidates cleared the per-scrip learned noise floor for date:", date_str)
            return
        cols = [
            "composite_rank", "symbol", "close", "ensemble_composite",
            "weight_factor_statistical", "weight_business_quality",
            "weight_policy_macro", "weight_supply_chain",
            "noise_floor", "clears_noise_floor", "is_solvency_approved",
        ]
        avail_cols = [c for c in cols if c in df_screened.columns]
        pd.set_option("display.max_columns", 15)
        pd.set_option("display.width", 1000)
        print(df_screened[avail_cols].to_string(index=False))
        return

    mode_label = "TOP-DOWN" if top_down else "LEGACY"
    print(f"\nRunning Quantitative Multi-Factor Screener [{mode_label}] for date: {date_str} (Universe: {universe.upper()}, Top {args.top})...\n")
    if top_down:
        df_screened = composite_screener.top_down_screen(target_date=date_str, top_n=args.top, universe=universe, dry_run=dry_run)
        if not df_screened.empty and dry_run:
            print(f"Top-down dry-run enriched {len(df_screened)} rows (metrics annotated, no funnel filters). Sample columns: secular_growth_score, total_moat_score, policy_agg_eni, roic_wacc_spread")
    else:
        df_screened = composite_screener.run_screener(target_date=date_str, top_n=args.top, universe=universe)

    if df_screened.empty:
        print("No screening candidates found for date:", date_str)
        return

    cols = [
        "composite_rank", "symbol", "close", "change_pct", "delivery_pct",
        "delivery_spike_ratio", "delivery_conviction_score", "technical_score",
        "fundamental_score", "composite_score", "yoy_revenue_growth_pct",
        "yoy_pat_growth_pct", "is_solvency_approved"
    ]
    avail_cols = [c for c in cols if c in df_screened.columns]
    df_display = df_screened[avail_cols]
    pd.set_option("display.max_columns", 15)
    pd.set_option("display.width", 1000)
    print(df_display.to_string(index=False))


def cmd_inspect_stock(args):
    """Displays comprehensive terminal stock dossier for a symbol."""
    symbol = args.symbol.upper().strip()
    company = repo.get_company_by_symbol(symbol)
    if not company:
        print(f"Company {symbol} not found in master database.")
        return

    print("\n" + "=" * 75)
    print(f"  STOCK INTELLIGENCE DOSSIER: {symbol} - {company['company_name']}")
    print("=" * 75)
    print(f"ISIN: {company['isin']} | BSE Code: {company.get('bse_code')} | Industry: {company.get('industry')} | Tier: {company.get('market_cap_tier')}")
    print(f"Nifty 50: {bool(company.get('is_nifty50'))} | Nifty 200: {bool(company.get('is_nifty200'))} | Nifty 500: {bool(company.get('is_nifty500'))}")

    # Technicals
    df_price = repo.get_price_history(symbol, limit=20)
    if not df_price.empty:
        latest = df_price.iloc[-1]
        print("\n--- LATEST TECHNICAL & DELIVERY PROFILE ---")
        print(f"Date: {latest['date']} | CMP: INR {latest['close']} ({latest['change_pct']}%)")
        print(f"Deliverable Volume: {int(latest['deliverable_volume']):,} | Delivery %: {latest['delivery_pct']}%")
        print(f"Delivery Spike Ratio: {latest.get('delivery_spike_ratio')}x | Conviction Score: {latest.get('delivery_conviction_score')}")
        print(f"SMA 20: INR {latest.get('sma_20')} | SMA 50: INR {latest.get('sma_50')} | SMA 200: INR {latest.get('sma_200')}")
        print(f"RSI (14): {latest.get('rsi_14')} | 52W High: INR {latest.get('high_52w')} (Dist: {latest.get('distance_from_52w_high_pct')}%)")

    # Fundamentals
    df_q = repo.get_quarterly_financials_history(symbol, quarters=4)
    if not df_q.empty:
        q = df_q.iloc[0]
        print("\n--- LATEST QUARTERLY FINANCIALS ---")
        print(f"Period: {q['financial_year']} ({q['quarter_end_date']})")
        print(f"Revenue: INR {q['revenue_inr_cr']:,.2f} Cr (YoY Growth: {q['yoy_revenue_growth_pct']}%, QoQ: {q['qoq_revenue_growth_pct']}%)")
        print(f"EBITDA: INR {q['ebitda_inr_cr']:,.2f} Cr (Margin: {q['ebitda_margin_pct']}%)")
        print(f"Net Profit (PAT): INR {q['net_profit_inr_cr']:,.2f} Cr (YoY Growth: {q['yoy_pat_growth_pct']}%, Margin: {q['pat_margin_pct']}%)")
        print(f"EPS: INR {q['eps_inr']}")

    # Solvency Health
    df_f = repo.get_forensic_health(symbol)
    if not df_f.empty:
        f = df_f.iloc[-1]
        print("\n--- FORENSIC SOLVENCY & GOVERNANCE GATES ---")
        print(f"Solvency Status: {'APPROVED' if f['is_solvency_approved'] == 1 else 'REJECTED'}")
        print(f"Promoter Holding: {f['promoter_holding_pct']}% | Promoter Pledge: {f['promoter_pledge_pct']}%")
        print(f"FII Holding: {f['fii_holding_pct']}% | DII Holding: {f['dii_holding_pct']}% | Public: {f['public_holding_pct']}%")
        print(f"Interest Coverage: {f['interest_coverage_ratio']}x | Debt to Equity: {f['debt_to_equity_ratio']}x")
        print(f"Market Cap: INR {f['market_cap_inr_cr']:,.2f} Cr | P/E: {f['pe_ratio']} | P/B: {f['pb_ratio']}")
        if f.get("solvency_disqualification_reasons"):
            print(f"Disqualification Notes: {f['solvency_disqualification_reasons']}")

    # Distilled Parameters
    distilled_params = distillation_engine.get_distilled_parameters(symbol)
    if distilled_params:
        print("\n--- DISTILLED COMPANY PARAMETERS ---")
        for dp in distilled_params:
            pkey = dp.get("parameter_key")
            pval = dp.get("value")
            print(f"\n  [{pkey.upper()}] (Confidence: {dp.get('confidence_score', 1.0)*100:.0f}%)")
            if isinstance(pval, dict):
                for k, v in pval.items():
                    print(f"    - {k}: {v}")
            else:
                print(f"    {pval}")

    # Concall transcripts / guidance hits
    searcher = HybridSearchEngine()
    hits = searcher.search(query="guidance order book capex margin expansion", symbol=symbol, top_k=2)
    if hits:
        print("\n--- CONCALL & INVESTOR GUIDANCE EXCERPTS ---")
        for h in hits:
            print(f"\n  * Citation: {h.citation} (Score: {h.score:.4f})")
            print(f"    \"{h.text[:220]}...\"")


def cmd_rank_models(args):
    """Shows per-stock / per-investor-majority MoE lens rankings (Wave D sparse MoE)."""
    symbol = args.symbol.upper().strip()
    investor = (args.investor_majority or "all").lower()
    if investor not in ("promoter", "fii", "dii", "retail", "all"):
        investor = "all"

    from reality_engine.processing.ensemble_ranker import EnsembleRanker
    ranker = EnsembleRanker()
    rows = ranker.rank_models(symbol, investor)

    print("\n" + "=" * 75)
    print(f"  MoE LENS RANKINGS: {symbol} (investor_majority={investor})")
    print("=" * 75)
    if not rows:
        print("No learned model_explainer_rankings for this symbol/investor context yet.")
        print("Seed rankings via the ensemble_ranker API, then re-run.")
        return
    for r in rows:
        print(
            f"  #{r['rank']}  {r['lens_family']:<22} "
            f"explain_power={float(r['explain_power']):.4f} "
            f"p_value={r['p_value']} weight={float(r['weight']):.4f}"
        )
    # Surface the most recent MoE activation audit for this context, if any.
    log = [e for e in ranker.get_activation_log(limit=20)
           if e.get("context_parsed", {}).get("stock") == symbol
           and str(e.get("context_parsed", {}).get("investor_majority", "all")).lower() == investor]
    if log:
        latest = log[0]
        print(f"\n  Last MoE activation (log_id={latest['log_id']}, temp={latest['temperature']}): "
              f"fired {latest['fired_lenses_parsed']}")


def cmd_run_daily_alpha(args):
    """Synthesizes high-conviction daily alpha theses and exports multi-format reports."""
    date_str = args.date or repo.get_latest_price_delivery_date()
    universe = getattr(args, "universe", "nifty200")
    top_n = getattr(args, "top", 20)
    top_theses_count = getattr(args, "top_theses", 5)

    top_down = getattr(args, "top_down", False)
    ensemble = getattr(args, "ensemble", False)
    investor_majority = (getattr(args, "investor_majority", "all") or "all").lower()
    if investor_majority not in ("promoter", "fii", "dii", "retail", "all"):
        investor_majority = "all"
    temperature = float(getattr(args, "temperature", 0.4) or 0.4)

    mode_tag = "[TOP-DOWN]" if top_down else ("[ENSEMBLE MoE]" if ensemble else "")
    print("\n" + "=" * 75)
    print(f"  SYNTHESIZING DAILY ALPHA REPORT FOR {date_str} ({universe.upper()}) {mode_tag}")
    print("=" * 75)

    orchestrator = AgentOrchestrator()
    report = orchestrator.synthesize_daily_alpha_report(
        target_date=date_str,
        universe=universe,
        top_n=top_theses_count,
        screener_pool_size=top_n,
        use_top_down=top_down,
        use_ensemble=ensemble,
        investor_majority=investor_majority,
        temperature=temperature,
    )

    writer = ReportWriter()
    exported = writer.export_daily_alpha_report(report)

    mb = report.market_breadth
    print(f"\nMarket Regime       : {mb.market_regime}")
    print(f"Advance/Decline     : {mb.advance_decline_ratio:.2f}")
    print(f"Top Sectors         : {', '.join(mb.top_performing_sectors[:3])}")
    print(f"Solvency Filtered   : {report.disqualified_solvency_count} disqualified")

    # Wave D4: surface ensemble metadata summary when present.
    ems = getattr(report, "ensemble_metadata", None)
    if ems is not None:
        print(f"Ensemble Mode       : {ems.get('mode')} | investor={ems.get('investor_majority')} | temp={ems.get('temperature')}")
        print(f"Avg Lenses Fired    : {ems.get('avg_n_fired')} | fired-weight-sum={ems.get('avg_fired_weight_sum')}")

    print("\n" + "-" * 75)
    print("  HIGH-CONVICTION ALPHA THESES")
    print("-" * 75)
    theses_data = []
    for t in report.high_conviction_theses:
        act = getattr(t, "ensemble_activation", None)
        conv = t.conviction_level
        if act is not None:
            conv = f"{conv} [MoE:{','.join(act.get('fired_lenses', []))}]"
        theses_data.append({
            "Rank": f"#{t.composite_rank}",
            "Symbol": t.symbol,
            "CMP (INR)": f"{t.current_market_price:,.2f}",
            "Entry Range": t.recommended_entry_range,
            "Target (INR)": f"{t.target_price:,.2f}",
            "SL (INR)": f"{t.stop_loss:,.2f}",
            "R:R": f"{t.risk_reward_ratio:.1f}x",
            "Conviction": conv,
        })
    df_theses = pd.DataFrame(theses_data)
    pd.set_option("display.width", 1000)
    print(df_theses.to_string(index=False))

    print("\n" + "=" * 75)
    print("  REPORTS EXPORTED SUCCESSFULLY")
    print("=" * 75)
    print(f"  - JSON Report : {exported['json']}")
    print(f"  - Markdown    : {exported['markdown']}")
    print(f"  - HTML Report : {exported['html']}")


def cmd_trace_causal_chain(args):
    """Traces multi-hop causal transmission paths from a starting node."""
    node_id = args.node.strip()
    max_hops = args.max_hops
    impact_filter = args.impact

    print("\n" + "=" * 75)
    print(f"  CAUSAL TRANSMISSION TRACE: {node_id}")
    print(f"  Hops: {max_hops} | Filter: {impact_filter}")
    print("=" * 75)

    traces = causal_engine.trace_causal_chain(
        start_node_id=node_id,
        max_hops=max_hops,
        impact_filter=impact_filter
    )

    if not traces:
        print(f"No causal transmission paths found starting from node '{node_id}'.")
        print("Tip: Run `python reality_engine/cli.py seed-ontologies` to ensure the canonical causal graph is seeded.")
        return

    table_data = []
    for t in traces:
        impact_val = t.get("cumulative_impact", 0.0)
        direction_label = "BENEFICIARY" if impact_val > 0 else ("VICTIM" if impact_val < 0 else "NEUTRAL")
        table_data.append({
            "Depth": f"Hop {t.get('depth')}",
            "Node ID": t.get("node_id"),
            "Name": t.get("name"),
            "Type": t.get("node_type"),
            "Direction": direction_label,
            "Cumulative Elasticity": f"{impact_val:+.2f}x",
            "Transmission Mechanisms": t.get("mechanisms") or "Direct"
        })

    df_traces = pd.DataFrame(table_data)
    pd.set_option("display.max_columns", 10)
    pd.set_option("display.width", 1000)
    print(df_traces.to_string(index=False))


def cmd_simulate_macro_shock(args):
    """Simulates a macro shock across companies and displays beneficiaries vs victims."""
    shock = args.shock.strip()
    sector = getattr(args, "sector", "ALL")

    print("\n" + "=" * 75)
    print(f"  MACRO SHOCK PROPAGATION SIMULATION")
    print(f"  Shock Scenario : {shock} | Sector Filter: {sector}")
    print("=" * 75)

    result = macro_simulator.simulate_macro_shock(shock_scenario=shock, sector_filter=sector)

    companies = result.get("companies", [])
    if not companies:
        print(f"No exposed companies found for macro shock '{shock}'.")
        print("Tip: Run `python reality_engine/cli.py seed-ontologies` to load canonical macro graph relationships.")
        return

    beneficiaries = result.get("beneficiaries", [])
    victims = result.get("victims", [])

    print(f"\nTotal Exposed Entities : {len(companies)}")
    print(f"Direct Beneficiaries   : {len(beneficiaries)}")
    print(f"Impaired / Victims     : {len(victims)}")

    if beneficiaries:
        print("\n>>> BENEFICIARIES (POSITIVE ELASTICITY) <<<")
        b_data = [{
            "Symbol": b["symbol"],
            "Hop Depth": b["depth"],
            "Impact Elasticity": f"+{b['impact']:.2f}x",
            "Transmission Mechanism": b["mechanisms"]
        } for b in beneficiaries]
        print(pd.DataFrame(b_data).to_string(index=False))

    if victims:
        print("\n>>> VICTIMS / IMPAIRED (NEGATIVE ELASTICITY) <<<")
        v_data = [{
            "Symbol": v["symbol"],
            "Hop Depth": v["depth"],
            "Impact Elasticity": f"{v['impact']:.2f}x",
            "Transmission Mechanism": v["mechanisms"]
        } for v in victims]
        print(pd.DataFrame(v_data).to_string(index=False))


def cmd_panic_monitor(args):
    """Evaluates panic drawdown triggers and outputs crisis bargains."""
    date_str = args.date or repo.get_latest_price_delivery_date()
    print(f"\nEvaluating Panic Monitor & Crisis Bargain Scanner for date: {date_str}...\n")
    res = panic_monitor.evaluate(session_date=date_str)
    print("=" * 75)
    print(f"  PANIC MONITOR STATUS: {'TRIGGERED (PANIC DETECTED)' if res['triggered'] else 'NORMAL (NO PANIC)'}")
    print("=" * 75)
    if res["triggers"]:
        print(f"\nActive Drawdown Triggers ({len(res['triggers'])}):")
        for t in res["triggers"]:
            print(f"  - {t}")
    else:
        print("\nNo drawdown triggers activated.")

    bargains = res["crisis_bargain_list"]
    if not bargains.empty:
        print(f"\n>>> CRISIS BARGAIN LIST ({len(bargains)} candidates) <<<")
        cols = [
            "composite_rank", "symbol", "close", "change_pct", "delivery_pct",
            "delivery_spike_ratio", "technical_score", "fundamental_score",
            "causal_resilience_score", "smart_money_score", "composite_score"
        ]
        avail_cols = [c for c in cols if c in bargains.columns]
        pd.set_option("display.max_columns", 15)
        pd.set_option("display.width", 1000)
        print(bargains[avail_cols].to_string(index=False))
    elif res["triggered"]:
        print("\nNo resilient crisis bargain candidates met the strict absorption and solvency criteria.")


def cmd_process_inbox(args):
    """Scans and ingests local drop-in files from ./reality_engine/data/inbox/."""
    inbox_dir = args.inbox_dir if hasattr(args, "inbox_dir") and args.inbox_dir else None
    runner = InboxRunner(inbox_dir=inbox_dir)
    print("\n" + "=" * 75)
    print(f"  PROCESSING LOCAL INBOX AT: {runner.inbox}")
    print("=" * 75)

    results = runner.run()
    if not results:
        print("\nInbox is empty. Place PDF, PNG/JPG images, or TXT documents into:")
        print(f"  - {runner.inbox / 'pdfs'}")
        print(f"  - {runner.inbox / 'images'}")
        print(f"  - {runner.inbox / 'text'}")
        return

    processed = [r for r in results if r.get("status") == "processed"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    failed = [r for r in results if r.get("status") == "failed"]

    print(f"\nTotal Files Scanned : {len(results)}")
    print(f"Successfully Indexed: {len(processed)}")
    print(f"Skipped (Duplicate) : {len(skipped)}")
    print(f"Failed Ingestion    : {len(failed)}")

    for r in processed:
        print(f"  [OK] {Path(r['path']).name} -> Indexed {r.get('chunks', 0)} chunks (Hash: {r.get('hash', '')[:12]}...)")
    for r in failed:
        print(f"  [FAIL] {Path(r['path']).name} -> Error: {r.get('error')}")


def cmd_seed_ontologies(args):
    """Seeds dynamic parameter ontologies, canonical causal graph, and distilled parameters."""
    print("\n" + "=" * 75)
    print("  SEEDING ONTOLOGIES & CANONICAL CAUSAL GRAPH")
    print("=" * 75)

    n_defs = distillation_engine.seed_ontology_definitions()
    graph_res = macro_simulator.seed_canonical_causal_graph()
    params_res = distillation_engine.seed_canonical_company_parameters()

    print(f"Dynamic Ontology Definitions : {n_defs} definitions seeded")
    print(f"Canonical Graph Nodes        : {graph_res['nodes']} nodes")
    print(f"Canonical Graph Edges        : {graph_res['edges']} edges")
    print(f"Company Distilled Parameters : {params_res.get('parameters_seeded', 0)} parameters seeded")
    print(f"Concall Transcripts Indexed  : {params_res.get('concall_chunks_seeded', 0)} chunks indexed")
    print("\nKnowledge base successfully initialized.")


def cmd_search_concall(args):
    """Performs hybrid lexical + vector search over concall transcripts."""
    query = args.query.strip()
    symbol = args.symbol.upper().strip() if args.symbol else None
    top_k = args.top_k

    print("\n" + "=" * 75)
    print(f"  HYBRID CONCALL SEARCH: \"{query}\"")
    if symbol:
        print(f"  Symbol Filter: {symbol}")
    print("=" * 75)

    searcher = HybridSearchEngine()
    hits = searcher.search(query=query, symbol=symbol, top_k=top_k)

    if not hits:
        print("No matching concall chunks or investor presentation passages found.")
        return

    print(f"\nRetrieved {len(hits)} matching passages:\n")
    for idx, hit in enumerate(hits, 1):
        print(f"--- [Result #{idx}] {hit.citation} (RRF Score: {hit.score:.4f} | Dense: {hit.vector_score:.4f}) ---")
        print(f"{hit.text}\n")


def cmd_dashboard(args):
    """Launches the Streamlit Equity Intelligence Dashboard."""
    dashboard_path = ENGINE_DIR / "ui" / "dashboard.py"
    port = getattr(args, "port", 8501)
    host = getattr(args, "host", "localhost")

    print("\n" + "=" * 75)
    print(f"  LAUNCHING REALITY ENGINE STREAMLIT DASHBOARD")
    print(f"  URL: http://{host}:{port}")
    print("=" * 75)

    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(dashboard_path),
        "--server.port", str(port),
        "--server.address", str(host)
    ]
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")


def cmd_sync_master(args):
    """Syncs master companies from NSE and BSE."""
    print("Synchronizing Master Companies across NSE and BSE...")
    res = master_sync.sync_all()
    print("Master Sync Results:", json.dumps(res, indent=2))


def cmd_backfill(args):
    """Backfills Bhavcopy and computes rolling technicals."""
    print(f"Backfilling {args.days} historical Bhavcopy sessions...")
    count = backfill_manager.backfill_bhavcopy_history(days_count=args.days)
    print(f"Backfilled {count} total price delivery records.")


def cmd_fetch_fundamentals(args):
    """Bulk-fetches 5y fundamentals with a rate-limited worker pool (resilient)."""
    if args.universe == "nifty200":
        companies = repo.get_nifty200_companies()
    else:
        companies = repo.get_all_companies(active_only=True)
    if args.top:
        companies = companies[:args.top]

    print(
        f"Fetching fundamentals for {len(companies)} companies "
        f"(workers={args.workers}, rate_limit={args.rate_limit}s, persist={not args.no_persist})..."
    )
    result = fundamentals_client.fetch_all_fundamentals(
        companies,
        max_workers=args.workers,
        rate_limit_sec=args.rate_limit,
        max_companies=(None if args.top <= 0 else args.top),
        persist=not args.no_persist,
    )
    summary = {k: v for k, v in result.items() if k != "failed_symbols"}
    print(json.dumps(summary, indent=2, default=str))
    if result["failed_symbols"]:
        print(f"\nFailed {result['failed']} symbol(s) (first 20 shown):")
        for f in result["failed_symbols"][:20]:
            print(f"  - {f.get('symbol')}: {f.get('error')}")
    if result["failed"]:
        print(f"\nWARNING: {result['failed']} company(ies) failed — see logs for full tracebacks.")


def cmd_discover_filings(args):
    """Discover raw official NSE/BSE filing links via Screener (link discovery only)."""
    from reality_engine.ingestion.filing_discovery import filing_discovery_client
    from reality_engine.db.repository import repo as _repo

    if args.symbol:
        companies = [{"nse_symbol": args.symbol, "bse_code": args.bse_code}]
    else:
        # Ingest-wide scope: default to the FULL active universe, never a filtered subset.
        companies = _repo.get_all_companies(active_only=True)
        if args.sample:
            # Safe smoke-test slice drawn from outside the Nifty 200 by default.
            non_nifty200 = [c for c in companies if not c.get("is_nifty200")]
            companies = (non_nifty200 if non_nifty200 else companies)[: args.sample]

    print(f"Discovering raw official filing links for {len(companies)} symbol(s) "
          f"(rate_limit={args.rate_limit}s)...")
    discoveries = []
    for c in companies:
        sym = (c.get("nse_symbol") or c.get("symbol") or "").strip().upper()
        if not sym:
            continue
        disc = filing_discovery_client.discover_filings(
            sym, bse_code=c.get("bse_code"), consolidated=not args.standalone
        )
        discoveries.append(disc)
        n = len(disc.get("links", []))
        flag = "ERROR" if disc.get("error") else "ok"
        print(f"  {sym}: {n} official link(s) [{flag}]")
        for ln in disc.get("links", [])[:5]:
            print(f"      - {ln['doc_type']:20s} {ln['source']:16s} {ln['source_url']}")

    if args.persist:
        # Register discovered links into corporate_documents (no file download yet).
        recs = []
        for d in discoveries:
            for ln in d.get("links", []):
                recs.append({
                    "isin": None, "symbol": d["symbol"], "doc_type": ln["doc_type"],
                    "title": ln["doc_type"], "doc_date": d.get("discovered_at", "1970-01-01"),
                    "source_url": ln["source_url"], "source": ln["source"],
                    "discovery_source": ln["discovery_source"],
                    "local_file_path": None, "file_size_bytes": 0,
                    "sha256_hash": None, "is_processed": 0,
                })
        # Resolve ISIN where possible for FK integrity.
        sym_to_isin = {c.get("nse_symbol"): c.get("isin") for c in companies if c.get("nse_symbol")}
        for r in recs:
            r["isin"] = sym_to_isin.get(r["symbol"])
        n = _repo.upsert_corporate_documents(recs)
        print(f"\nPersisted {n} discovered filing link record(s) to corporate_documents.")

    total_links = sum(len(d.get("links", [])) for d in discoveries)
    print(f"\nSUMMARY: {len(discoveries)} symbol(s) -> {total_links} raw official filing link(s) discovered.")
    print("NOTE: Screener tables were NOT copied. Only raw bseindia.com / nseindia.com URLs were harvested.")


def cmd_fetch_filings(args):
    """Download & archive the raw official NSE/BSE filings discovered for a symbol/universe."""
    from reality_engine.ingestion.filing_discovery import filing_discovery_client
    from reality_engine.ingestion.official_filing_client import official_filing_client
    from reality_engine.db.repository import repo as _repo

    # Bulk mode: archive already-discovered links directly from corporate_documents.
    if args.from_db:
        print(f"Archiving discovered links from DB (doc_type={args.doc_type or 'ALL'}, "
              f"max_links={args.max_links or 'unlimited'}, workers={args.workers}, "
              f"rate_limit={args.rate_limit}s)...")
        with _repo.db.session() as conn:
            q = (
                "SELECT symbol, doc_type, source_url, source, discovery_source, isin "
                "FROM corporate_documents WHERE discovery_source='screener_discovery' "
                "AND local_file_path IS NULL"
            )
            if args.doc_type:
                q += f" AND doc_type='{args.doc_type}'"
            q += " ORDER BY id"
            if args.max_links:
                q += f" LIMIT {int(args.max_links)}"
            rows = conn.execute(q).fetchall()
        discoveries = []
        for r in rows:
            discoveries.append({
                "symbol": r["symbol"],
                "bse_code": None,
                "links": [{
                    "source_url": r["source_url"],
                    "doc_type": r["doc_type"],
                    "source": r["source"] or "bse_official",
                    "discovery_source": r["discovery_source"] or "screener_discovery",
                }],
            })
        result = official_filing_client.archive_many(
            discoveries, max_workers=args.workers, progress=True
        )
        print(json.dumps({k: v for k, v in result.items() if k != "per_symbol"}, indent=2))
        if args.persist:
            # Update each archived row's local path + hash by source_url.
            updated = 0
            with _repo.db.session() as conn:
                for sym_res in result.get("per_symbol", []):
                    for r in sym_res.get("results", []):
                        if r.get("ok") and r.get("local_file_path"):
                            conn.execute(
                                "UPDATE corporate_documents SET local_file_path=?, file_size_bytes=?, "
                                "sha256_hash=?, is_processed=1 WHERE source_url=?",
                                (r["local_file_path"], r.get("file_size_bytes", 0),
                                 r.get("sha256_hash"), r["source_url"]),
                            )
                            updated += 1
                conn.commit()
            print(f"\nUpdated {updated} archived filing record(s) in corporate_documents.")
        return

    if args.symbol:
        companies = [{"nse_symbol": args.symbol, "bse_code": args.bse_code}]
    else:
        companies = _repo.get_all_companies(active_only=True)
        if args.sample:
            non_nifty200 = [c for c in companies if not c.get("is_nifty200")]
            companies = (non_nifty200 if non_nifty200 else companies)[: args.sample]

    print(f"Discovering + archiving raw official filings for {len(companies)} symbol(s) "
          f"(workers={args.workers}, rate_limit={args.rate_limit}s)...")
    discoveries = []
    for c in companies:
        sym = (c.get("nse_symbol") or c.get("symbol") or "").strip().upper()
        if not sym:
            continue
        disc = filing_discovery_client.discover_filings(
            sym, bse_code=c.get("bse_code"), consolidated=not args.standalone
        )
        discoveries.append(disc)

    result = official_filing_client.archive_many(
        discoveries, max_workers=args.workers, progress=True
    )
    print(json.dumps({k: v for k, v in result.items() if k != "per_symbol"}, indent=2))
    if args.persist:
        recs = []
        for sym_res in result.get("per_symbol", []):
            sym = sym_res.get("symbol")
            for r in sym_res.get("results", []):
                recs.append({
                    "isin": None, "symbol": sym, "doc_type": r.get("doc_type"),
                    "title": r.get("doc_type"), "doc_date": "1970-01-01",
                    "source_url": r.get("source_url"), "source": r.get("source"),
                    "discovery_source": r.get("discovery_source"),
                    "local_file_path": r.get("local_file_path"),
                    "file_size_bytes": r.get("file_size_bytes", 0),
                    "sha256_hash": r.get("sha256_hash"),
                    "is_processed": 1 if r.get("ok") else 0,
                })
        # Resolve ISIN for FK integrity.
        sym_to_isin = {c.get("nse_symbol"): c.get("isin") for c in companies if c.get("nse_symbol")}
        for rr in recs:
            rr["isin"] = sym_to_isin.get(rr["symbol"])
        n = _repo.upsert_corporate_documents(recs)
        print(f"\nPersisted {n} filing record(s) (archived + provenance) to corporate_documents.")


def cmd_fetch_corporate_actions(args):
    """Ingest NSE corporate actions (bonus/split/rights/buyback/merger/demerger/dividend) for full universe."""
    from reality_engine.ingestion.corporate_actions_client import corporate_actions_client
    from reality_engine.db.repository import repo as _repo

    print(f"Fetching NSE corporate actions from {args.from_date} to today "
          f"(slice_days={args.slice_days}, persist={not args.no_persist})...")
    result = corporate_actions_client.fetch_range(args.from_date, datetime.now().strftime("%Y-%m-%d"))
    print(f"  slices={result['slices']} raw_records={result['raw_records']} "
          f"normalized={len(result['normalized'])} slice_errors={result['errors']}")

    if not args.no_persist:
        n = _repo.upsert_corporate_actions(result["normalized"])
        print(f"  persisted {n} corporate action record(s) to corporate_actions.")
    else:
        # Print a small sample of normalized types.
        from collections import Counter
        c = Counter(r["action_type"] for r in result["normalized"])
        for k, v in c.most_common():
            print(f"    {k}: {v}")

    print("NOTE: Delisting is NOT covered by the NSE corporate-actions feed; "
          "a separate delisting source is required and must not be fabricated.")


def cmd_fetch_corporate_status(args):
    """Compose delisting / NCLT (insolvency) status flags from derived + announcement-scan signals."""
    from reality_engine.ingestion.delisting_nclt_client import delisting_nclt_client

    print("Building delisting / NCLT status flags (derived + announcement-scan)...")
    result = delisting_nclt_client.build_flags()
    print(f"  official feed (reachable): {result['counts']['official']}")
    print(f"  derived delisted (is_active=0): {result['counts']['derived_delisted']}")
    print(f"  announcement-scan NCLT/CIRP/suspend hits: {result['counts']['scanned']}")
    print(f"  TOTAL flags: {result['counts']['total']}")
    if not args.no_persist:
        n = delisting_nclt_client.persist_flags()
        print(f"  persisted {n} flag record(s) to corporate_status_flags.")
    else:
        # Show a few examples.
        for f in result["all"][:8]:
            print(f"    {f['symbol']:14s} {f['status_type']:12s} {f['source']:20s} {f['detail'][:50]}")


def cmd_bootstrap(args):
    """Executes deterministic database initialization and test-data fixture bootstrapping."""
    print("\n" + "=" * 75)
    print("  LAUNCHING REALITY ENGINE DETERMINISTIC BOOTSTRAP")
    print("=" * 75)
    target_db = getattr(args, "target_db", None)
    days = getattr(args, "days", 25)
    top = getattr(args, "top", 200)
    force = getattr(args, "force", False)
    verify = not getattr(args, "no_verify", False)
    sample_only = getattr(args, "sample_only", False)

    mgr = BootstrapManager(db_path=target_db) if target_db else bootstrap_manager
    res = mgr.bootstrap(days=days, top=top, force=force, verify=verify, sample_only=sample_only)

    print("\n>>> BOOTSTRAP EXECUTION SUMMARY <<<")
    print(f"Status                  : {res['status']}")
    print(f"Execution Time          : {res['execution_time_seconds']}s")
    print(f"Target Database         : {res['database_path']}")
    print(f"Master Companies Seeding: {res['master_companies_count']} records")
    print(f"Bhavcopy Sessions Rows  : {res['bhavcopy_rows_count']} rows")
    print(f"Quarterly Financials    : {res['fundamentals']['quarterly_financials']} rows")
    print(f"Annual Financials       : {res['fundamentals']['annual_financials']} rows")
    print(f"Forensic Solvency Health: {res['fundamentals']['forensic_health']} rows")
    print(f"Insider Trades          : {res['smart_money']['insider_trades']} rows")
    print(f"Bulk / Block Deals      : {res['smart_money']['bulk_block_deals']} rows")
    print(f"Ontology Definitions    : {res['ontologies']['ontology_definitions']} definitions")
    print(f"Distilled Parameters    : {res['ontologies']['company_parameters']} parameters")
    print(f"Causal Graph            : {res['causal_graph']['graph_nodes']} nodes, {res['causal_graph']['graph_edges']} edges")
    if res.get("checkpoint"):
        print(f"Checkpoint Validation   : {'PASSED' if res['checkpoint'].get('checkpoint_passed') else 'FAILED'}")
        print(f"Technical Complete      : {res['checkpoint'].get('technical_data_complete_count')}/{res['checkpoint'].get('target_universe_count')}")
        print(f"Fundamental Complete    : {res['checkpoint'].get('fundamental_data_complete_count')}/{res['checkpoint'].get('target_universe_count')}")


def cmd_verify_checkpoint(args):
    """Validates the Top 200 data checkpoint."""
    print("\nValidating Top 200 Reality Data Checkpoint...")
    summary = phase1_runner.validate_top_200_checkpoint()
    print("\n" + "=" * 75)
    print("  CHECKPOINT AUDIT RESULT")
    print("=" * 75)
    print(json.dumps(summary, indent=2))


def cmd_audit_data(args):
    """Runs the read-only data pipeline readiness audit."""
    from reality_engine.pipeline.data_audit import main as audit_main

    argv: List[str] = []
    if getattr(args, "net", False):
        argv.append("--net")
    if getattr(args, "json", False):
        argv.append("--json")
    rc = audit_main(argv)
    if rc != 0:
        # Non-zero means at least one CRITICAL section; surface it to the shell.
        raise SystemExit(rc)


def cmd_listen_telegram(args):
    """Starts Telegram MTProto listener (live or mock) and reports status."""
    import asyncio
    channels = getattr(args, "channels", None)
    duration = getattr(args, "duration", 2.0)
    use_mock = getattr(args, "mock", False)
    api_id = getattr(args, "api_id", None)
    api_hash = getattr(args, "api_hash", None)

    print("\n" + "=" * 75)
    print("  TELEGRAM LISTENER")
    print("=" * 75)
    if use_mock:
        print("Mode: MOCK (offline simulation)")
    else:
        print("Mode: LIVE (requires TELEGRAM_API_ID/HASH)")

    listener = TelegramListener(
        api_id=api_id,
        api_hash=api_hash,
        target_channels=channels,
        mock_mode=use_mock,
    )
    if use_mock and not listener._mock_queue:
        # Enqueue a demonstrative mock message if queue empty
        listener.enqueue_mock_message({
            "id": 999,
            "chat_id": (channels.split(",")[0].strip() if channels else "mock_channel"),
            "channel_title": "Mock Demo Channel",
            "text": "Demo breakout on RELIANCE above 2950. Target 3100 SL 2880",
            "date": "2026-08-14T10:30:00Z",
        })
        print(f"Enqueued demo mock message (queue size {len(listener._mock_queue)})")

    print(f"Target channels: {listener.target_channels or 'ALL (no filter)'}")
    print(f"Available: {listener.is_available()} | Mock: {listener.mock_mode}")
    print(f"Duration: {duration}s | Session: {listener.session_path}")

    result = asyncio.run(listener.start_listening(duration_seconds=duration))
    print("\n" + "-" * 75)
    print("  LISTENER RESULT")
    print("-" * 75)
    print(json.dumps(result, indent=2, default=str))

    # Show recent telegram posts if any
    try:
        posts = listener.get_channel_stats(limit=5)
        if posts:
            print(f"\nRecent telegram_posts in DB: {len(posts)}")
            for p in posts[:3]:
                print(f" - {p.get('id')}: {str(p.get('raw_message_text',''))[:60]} | symbols={p.get('detected_symbols_json')}")
    except Exception as exc:
        print(f"Note fetching telegram posts: {exc}")


def cmd_simulate_telegram(args):
    """Simulates a single Telegram incoming message (text + optional media) for testing."""
    text = getattr(args, "text", "")
    chat_id = getattr(args, "chat_id", "mock_channel")
    channel_title = getattr(args, "channel_title", "Mock Channel")
    message_id = getattr(args, "message_id", 1)
    thread_id = getattr(args, "thread_id", 0)
    media_path = getattr(args, "media_path", None)

    print("\n" + "=" * 75)
    print("  SIMULATE TELEGRAM MESSAGE")
    print("=" * 75)
    listener = TelegramListener(mock_mode=True, inbox_dir=getattr(args, "inbox_dir", None))
    result = listener.simulate_incoming_message(
        text=text,
        chat_id=chat_id,
        channel_title=channel_title,
        message_id=message_id,
        thread_topic_id=thread_id,
        media_path=media_path,
        date=getattr(args, "date", None),
    )
    print(json.dumps(result, indent=2, default=str))
    print("\nDetected symbols:", result.get("detected_symbols"))
    print("Targets:", result.get("price_targets"), "SL:", result.get("stop_losses"))


def cmd_telegram_stats(args):
    """Shows telegram post statistics grouped by channel."""
    print("\n" + "=" * 75)
    print("  TELEGRAM POST STATISTICS")
    print("=" * 75)
    listener = TelegramListener(mock_mode=True)
    posts = listener.get_channel_stats(limit=getattr(args, "limit", 50))
    if not posts:
        print("No telegram posts found in database.")
        return
    # Aggregate by channel
    from collections import Counter
    channel_counts = Counter(p.get("channel_id") for p in posts)
    print(f"Total posts (up to limit): {len(posts)}")
    for ch, cnt in channel_counts.most_common():
        print(f" - {ch}: {cnt} posts")
    print("\nLatest 5 posts:")
    for p in posts[:5]:
        txt = str(p.get('raw_message_text', ''))[:80]
        txt_safe = txt.encode("ascii", "replace").decode("ascii")
        print(f"  [{p.get('post_timestamp')}] {p.get('channel_id')}#{p.get('message_id')} - {txt_safe!r}")


def cmd_telegram_threads(args):
    """Lists forum topics/threads in a Telegram supergroup (title, id, message count)."""
    import asyncio
    from telethon.errors import FloodWaitError as _FWThreads
    from telethon.tl import functions

    channels = getattr(args, "channels", None)
    print("\n" + "=" * 75)
    print("  TELEGRAM FORUM THREADS")
    print("=" * 75)
    listener = TelegramListener(target_channels=channels)
    if not listener.is_available():
        print("Credentials unavailable.")
        return
    async def _run():
        from telethon import TelegramClient as _TGC
        client = _TGC(str(listener.session_path), int(listener.api_id), str(listener.api_hash))
        try:
            await client.start()
            for ch in listener.target_channels:
                try:
                    ent = await client.get_entity(ch)
                    name = getattr(ent, "title", None) or getattr(ent, "username", None) or str(ent)
                    print(f"= {name} | group_id={ent.id}")
                    from telethon.tl.functions.messages import GetForumTopicsRequest as _GFT
                    topic_info = await client(_GFT(
                        peer=ent,
                        offset_date=None,
                        offset_id=0,
                        offset_topic=0,
                        limit=100,
                        q="",
                    ))
                    print(f"  Found {len(topic_info.topics)} topics:")
                    for t in topic_info.topics:
                        print(f"    topic_id={t.id} | title={t.title!r} | messages={t.top_message} | "
                              f"date={t.date} | pinned={getattr(t, 'pinned', 0)}")
                    await asyncio.sleep(1.0)
                except _FWThreads as fw:
                    print(f"  FloodWait {getattr(fw, 'seconds', 30)}s - backing off")
                    await asyncio.sleep(int(getattr(fw, 'seconds', 30)) + 2)
                except Exception as exc:
                    print(f"  Not accessible: {exc}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
    asyncio.run(_run())


def cmd_telegram_backfill(args):
    """Fetches thread history (or whole forum topic) from target Telegram channels and ingests posts."""
    import asyncio
    from telethon.errors import FloodWaitError as _FloodWaitError

    channels = getattr(args, "channels", None)
    limit = getattr(args, "limit", 50)
    thread_id = getattr(args, "thread_id", None)
    thread_name = getattr(args, "thread_name", None)
    # -1 = whole thread (until flood/limit cap); N = latest N only; 0 = general chat
    walk_all = getattr(args, "all", False)
    max_exists = getattr(args, "max_exists", 30)
    safety_cap = getattr(args, "safety_cap", 300)

    print("\n" + "=" * 75)
    print("  TELEGRAM HISTORY BACKFILL")
    print("=" * 75)
    listener = TelegramListener(target_channels=channels)
    if not listener.is_available():
        print("Credentials unavailable. Set TELEGRAM_API_ID / TELEGRAM_API_HASH.")
        return
    if not listener.target_channels:
        print("No target channels provided (--channels '-1002413883243' etc).")
        return

    print(f"Channels: {listener.target_channels} | Limit/run: {limit} | "
          f"Thread: {thread_name or thread_id or 'ALL'} | Whole-thread walk: {walk_all or 'NO'}")
    print(f"Session: {listener.session_path}")

    async def _run() -> Dict[str, Any]:
        from telethon import TelegramClient as _TGClient
        client = _TGClient(str(listener.session_path), int(listener.api_id), str(listener.api_hash))
        fetched_total = 0
        results: List[Dict[str, Any]] = []
        try:
            await client.start()
            me = await client.get_me()
            print(f"Authenticated as: {me.first_name} {me.last_name or ''}")
            for ch in listener.target_channels:
                try:
                    entity = await client.get_entity(ch)
                    # Resolve thread id from topic title if provided
                    resolved_thread_id = int(thread_id) if thread_id else None
                    if thread_name and resolved_thread_id is None:
                        from telethon.tl.functions.messages import GetForumTopicsRequest as _GFT2
                        topic_info = await client(_GFT2(
                            peer=entity, q=thread_name, offset_date=None, offset_id=0,
                            offset_topic=0, limit=20,
                        ))
                        for t in topic_info.topics:
                            if t.title and thread_name.lower() in t.title.lower():
                                resolved_thread_id = t.id
                                print(f"Resolved thread '{t.title}' -> topic_id={t.id}")
                                break
                        if resolved_thread_id is None and topic_info.topics:
                            t0 = topic_info.topics[0]
                            resolved_thread_id = t0.id
                            print(f"Fuzzy-resolved thread '{t0.title}' -> topic_id={t0.id}")

                    walk_count = 0
                    max_id: Optional[int] = None  # oldest seen; walk downward
                    last_fetched_any = False
                    while True:
                        if walk_count >= safety_cap if walk_all else walk_count >= 1:
                            break
                        kwargs: Dict[str, Any] = {"limit": limit}
                        if resolved_thread_id:
                            kwargs["reply_to"] = resolved_thread_id
                        if max_id:
                            kwargs["max_id"] = max_id - 1
                        try:
                            msgs = await client.get_messages(ch, **kwargs)
                        except _FloodWaitError as _fw:
                            wait = int(getattr(_fw, "seconds", 30)) + 2
                            print(f"FloodWait for {ch}: backing off {wait}s (account safety)")
                            await asyncio.sleep(wait)
                            continue
                        if not msgs:
                            break
                        last_fetched_any = True
                        fetched = 0
                        for m in msgs:
                            if not getattr(m, "id", None):
                                continue
                            try:
                                res = await listener.handle_incoming_message(m)
                                results.append(res)
                                fetched += 1
                            except Exception as m_exc:
                                print(f"  skip msg {getattr(m,'id','?')}: {m_exc}")
                        fetched_total += fetched
                        walk_count += 1
                        oldest = msgs[-1].id
                        max_id = oldest
                        print(f"  page {walk_count}: {fetched} msgs from {ch} (down to {oldest})")
                        if not walk_all:
                            break
                        await asyncio.sleep(1.2)  # polite spacing between pages
                    if not last_fetched_any:
                        print(f"  No messages found from {ch} in this thread/window.")
                except _FloodWaitError as _fw:
                    wait = int(getattr(_fw, "seconds", 30)) + 2
                    print(f"FloodWait for {ch}: backing off {wait}s (account safety)")
                    await asyncio.sleep(wait)
                except Exception as exc:
                    print(f"Error reading {ch}: {exc}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        return {"fetched_total": fetched_total, "results": results}

    result = asyncio.run(_run())
    print("\n" + "-" * 75)
    print("  BACKFILL RESULT")
    print("-" * 75)
    print(f"Processed: {result['fetched_total']} messages")
    print(f"Summaries (latest {max_exists}):")
    for r in result["results"][:max_exists]:
        txt = str(r.get("raw_message_text", ""))[:90]
        txt_safe = txt.encode("ascii", "replace").decode("ascii")
        buttons = r.get("button_links") or []
        btn_str = f" buttons={[b['url'] for b in buttons]}" if buttons else ""
        print(f"  [{str(r.get('post_timestamp',''))[:19]}] {r.get('channel_id')}#{r.get('message_id')} "
              f"symbols={r.get('detected_symbols')} tgt={r.get('price_targets')} sl={r.get('stop_losses')}"
              f"{btn_str} text={txt_safe!r}")


def cmd_telegram_scan(args):
    """Probes channels without ingesting: lists chat name, ID, and recent thread/msg count."""
    import asyncio
    from telethon.errors import FloodWaitError as _FloodWaitError2

    channels = getattr(args, "channels", None)
    print("\n" + "=" * 75)
    print("  TELEGRAM CHANNEL SCAN")
    print("=" * 75)
    listener = TelegramListener(target_channels=channels)
    if not listener.is_available():
        print("Credentials unavailable.")
        return
    async def _run():
        from telethon import TelegramClient as _TGClient2
        client = _TGClient2(str(listener.session_path), int(listener.api_id), str(listener.api_hash))
        try:
            await client.start()
            for ch in listener.target_channels:
                try:
                    ent = await client.get_entity(ch)
                    name = getattr(ent, "title", None) or getattr(ent, "username", None) or str(ent)
                    print(f"= {name} | input_id={ent.id} | is_channel={getattr(ent, 'broadcast', False)} | is_group={getattr(ent, 'megagroup', False)}")
                    try:
                        msgs = await client.get_messages(ent, limit=3)
                        for m in msgs:
                            print(f"   msg#{m.id} thread={getattr(m, 'reply_to_msg_id', 0)} date={m.date} text={str(m.text)[:80]!r}")
                    except Exception as exc:
                        print(f"   (messages note: {exc})")
                    await asyncio.sleep(1.0)
                except _FloodWaitError2 as fw2:
                    print(f"FloodWait {getattr(fw2, 'seconds', 30)}s - backing off")
                    await asyncio.sleep(int(getattr(fw2, 'seconds', 30)) + 2)
                except Exception as exc:
                    print(f" Not accessible: {exc}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
    asyncio.run(_run())


def cmd_prune_decayed_signals(args):
    """Prune decayed signals — SQLite fallback compatible (prune_decayed_signals procedure)."""
    from reality_engine.processing.pruning_engine import prune_decayed_signals, get_decayed_significance_rows
    dry = getattr(args, "dry_run", False)
    res = prune_decayed_signals(dry_run=dry)
    print(json.dumps(res, indent=2, default=str))
    if getattr(args, "show_decayed", False):
        rows = get_decayed_significance_rows(limit=getattr(args, "limit", 10))
        print("\n--- v_ripple_decayed (decayed_significance) ---")
        for r in rows[:getattr(args, "limit", 10)]:
            print(json.dumps(r, indent=2, default=str))
    # Also show cold export count
    if getattr(args, "show_cold", False):
        from reality_engine.processing.pruning_engine import cold_export_rows
        cold = cold_export_rows(months=36)
        print(f"\nCold-tier >36m rows that would be parquet-exported: {len(cold)}")


def cmd_run_distillation(args):
    """Monthly distillation: 20 YouTube +4 Concall -> moat -> purge 24 vectors -> log distillation_runs."""
    from reality_engine.processing.distillation_pruner import run_monthly_distillation
    symbol = getattr(args, "symbol", "HAL").upper()
    res = run_monthly_distillation(symbol, youtube_n=getattr(args, "youtube", 20), concall_n=getattr(args, "concall", 4))
    print(json.dumps(res, indent=2, default=str))
    # Show latest distillation_runs
    try:
        from reality_engine.db.database import db_manager
        with db_manager.session() as conn:
            row = conn.execute("SELECT * FROM distillation_runs ORDER BY run_id DESC LIMIT 1").fetchone()
            if row:
                print("\nLatest distillation_runs row:")
                print(json.dumps(dict(row), indent=2, default=str))
    except Exception as exc:
        print(f"Note fetching distillation_runs: {exc}")


def cmd_fetch_macro(args):
    """Fetch macro-policy PDFs (Central/State Budgets, PIB circulars, RBI reports).

    Second-tier peer data below core company data. Writes to raw_documents audit
    trail via the repository; gracefully skips browser-only hosts when the Playwright
    fallback is unavailable. Supports --dry-run (plan only, no download/DB write).
    """
    from reality_engine.ingestion.macro_pdf_fetcher import MacroPDFFetcher

    source = (getattr(args, "source", "all") or "all").lower()
    years = getattr(args, "years", None) or ["2024-25", "2025-26"]
    if isinstance(years, str):
        years = [y.strip() for y in years.split(",") if y.strip()]
    state_filter = getattr(args, "state_filter", None)
    if state_filter:
        state_filter = [s.strip() for s in state_filter.split(",") if s.strip()]
    workers = getattr(args, "workers", 4)
    dry_run = getattr(args, "dry_run", False)
    pib_limit = getattr(args, "pib_limit", 10)
    since_date = getattr(args, "since_date", None)
    rate_limit = getattr(args, "rate_limit", 1.0)
    ingest = getattr(args, "ingest", False)

    print("\n" + "=" * 75)
    print("  MACRO PDF FETCHER (second-tier peer data)")
    print("=" * 75)
    print(f"  Source : {source}")
    print(f"  Years  : {', '.join(years)}")
    if state_filter:
        print(f"  States : {', '.join(state_filter)}")
    print(f"  Dry-run: {dry_run}")

    fetcher = MacroPDFFetcher(rate_limit_sec=rate_limit)

    if dry_run:
        plan = fetcher.plan(source=source, years=years, states=state_filter)
        total = plan.pop("_total", 0)
        print(f"\nPlanned {total} URL(s) for source='{source}':")
        for grp, items in plan.items():
            print(f"  - {grp}: {len(items)}")
            for it in items[:25]:
                print(f"      * [{it.get('source_type')}] {it.get('url')}")
        print("\nDRY-RUN: no downloads or database writes performed.")
        return

    summary: Dict[str, Any] = {}
    if source in ("central", "all"):
        summary["central"] = fetcher.fetch_central_budgets(years=years)
    if source in ("states", "all"):
        summary["states"] = fetcher.fetch_state_budgets(states=state_filter, years=years)
    if source in ("pib", "all"):
        summary["pib"] = fetcher.fetch_pib_circulars(limit=pib_limit, since_date=since_date)
    if source in ("rbi", "all"):
        summary["rbi"] = fetcher.fetch_rbi_reports(years=years)

    # Optional dense-substrate ingestion of freshly downloaded macro PDFs.
    ingested_total = 0
    if ingest and not dry_run:
        from reality_engine.ingestion.pdf_ingestor import PDFIngestor

        ingestor = PDFIngestor()
        for grp, res in summary.items():
            if not isinstance(res, dict):
                continue
            for d in res.get("details", []):
                p = d.get("path")
                if not p:  # failed download / no local file -> nothing to ingest
                    continue
                try:
                    meta = {
                        "source_type": d.get("source_type"),
                        "title": d.get("title"),
                        "fiscal_period": d.get("fiscal_period"),
                        "source_url": d.get("source_url"),
                        "published_date": d.get("published_date"),
                        "creator_or_ministry": d.get("creator_or_ministry"),
                    }
                    r = ingestor.ingest_macro_file(Path(p), **meta)
                    ingested_total += 1 if r.get("status") == "ingested" else 0
                    logger.info("Ingested macro PDF %s -> %s (chunks=%s)", p, r.get("status"), r.get("chunks"))
                except Exception as exc:
                    logger.warning("Ingest failed for %s: %s", p, exc)
        print(f"\nIngested {ingested_total} macro PDF(s) into document_chunks (TEXT/FTS).")

    print("\n" + "-" * 75)
    print("  MACRO PDF FETCH SUMMARY")
    print("-" * 75)
    grand = {"total": 0, "fetched": 0, "skipped": 0, "failed": 0}
    for grp, res in summary.items():
        if not isinstance(res, dict):
            continue
        print(f"  {grp:>10s}: total={res.get('total', 0)} fetched={res.get('fetched', 0)} "
              f"skipped={res.get('skipped', 0)} failed={res.get('failed', 0)}")
        for k in grand:
            grand[k] += res.get(k, 0)
    print(f"  {'TOTAL':>10s}: total={grand['total']} fetched={grand['fetched']} "
          f"skipped={grand['skipped']} failed={grand['failed']}")
    if grand["failed"]:
        print(f"\nNOTE: {grand['failed']} fetch(es) skipped/failed (e.g. JS/TSPD-blocked host "
              "without browser fallback) — these are logged and do NOT crash the run.")


def cmd_process_macro(args):
    """Scan MACRO_PDFS_DIR recursively for *.pdf and ingest any not yet in the substrate.

    Idempotent via sha256: files already present in raw_documents/document_chunks are
    skipped. Reuses metadata from the raw_documents audit row when available (written by
    fetch-macro), otherwise derives a best-effort source_type from the category folder.
    """
    from reality_engine.ingestion.pdf_ingestor import PDFIngestor
    from reality_engine.config import MACRO_PDFS_DIR

    ingestor = PDFIngestor()
    dry_run = getattr(args, "dry_run", False)
    directory = getattr(args, "directory", None)
    scan_dir = Path(directory) if directory else MACRO_PDFS_DIR

    print("\n" + "=" * 75)
    print("  PROCESS MACRO PDFs (scan + ingest into dense substrate)")
    print("=" * 75)
    print(f"  Scan dir: {scan_dir}")
    print(f"  Dry-run : {dry_run}")

    results = ingestor.ingest_macro_directory(scan_dir, recursive=True, dry_run=dry_run)

    ingested = [r for r in results if r.get("status") == "ingested"]
    skipped = [r for r in results if r.get("status") == "skipped_duplicate"]
    failed = [r for r in results if r.get("status") == "failed"]
    would = [r for r in results if r.get("status") == "would_ingest"]

    print(f"\nTotal PDFs scanned : {len(results)}")
    if dry_run:
        print(f"Would ingest       : {len(would)}")
    else:
        print(f"Freshly ingested  : {len(ingested)}")
        print(f"Skipped (exists)  : {len(skipped)}")
        print(f"Failed            : {len(failed)}")

    shown = would if dry_run else ingested
    for r in shown:
        try:
            print(f"  [OK] {Path(r['path']).name} -> {r.get('chunks')} chunks "
                  f"(source_type={r.get('source_type')})")
        except Exception:
            pass
    for r in failed:
        print(f"  [FAIL] {Path(r['path']).name} -> {r.get('error')}")


# --------------------------------------------------------------------
# Peer substrate runners (lane-code-cli): subprocess delegation to
# reality_engine/scripts/run_*.py so script-level argparse/env is reused.
# --------------------------------------------------------------------

def _peer_script_path(script_name: str) -> Path:
    """Resolve a peer runner script path relative to cli.py."""
    return Path(__file__).parent / "scripts" / script_name


def _run_peer_subprocess(script_name: str, extra_args: List[str]) -> int:
    """Run a peer script via subprocess, forwarding extra_args.

    Uses [sys.executable, script_path, *extra_args] so script-level argparse
    is reused. Streams stdout/stderr directly (no capture) so unknown-arg
    failures print the script's stderr clearly. Returns exit code.
    """
    script_path = _peer_script_path(script_name)
    cmd = [sys.executable, str(script_path)] + list(extra_args or [])
    print(f"\n>>> Running {script_name} {' '.join(extra_args) if extra_args else ''} ...")
    try:
        result = subprocess.run(cmd)
        return result.returncode
    except Exception as exc:
        print(f"[FAIL] {script_name} exception: {exc}", file=sys.stderr)
        return 1


def cmd_seed_quality_peer(args):
    """Delegate to reality_engine/scripts/run_quality_peer.py (subprocess)."""
    extra: List[str] = []
    if getattr(args, "universe", None) is not None:
        extra += ["--universe", str(args.universe)]
    if getattr(args, "include_derived", False):
        extra += ["--include-derived"]
    if getattr(args, "limit", None) is not None:
        extra += ["--limit", str(args.limit)]
    rc = _run_peer_subprocess("run_quality_peer.py", extra)
    if rc != 0:
        print(f"[FAIL] run_quality_peer.py exited with code {rc}", file=sys.stderr)
        raise SystemExit(rc)
    print("[OK] run_quality_peer.py completed successfully")


def cmd_seed_policy_peer(args):
    """Delegate to reality_engine/scripts/run_policy_peer.py (subprocess)."""
    extra: List[str] = []
    if getattr(args, "universe", None) is not None:
        extra += ["--universe", str(args.universe)]
    if getattr(args, "include_derived", False):
        extra += ["--include-derived"]
    if getattr(args, "limit", None) is not None:
        extra += ["--limit", str(args.limit)]
    rc = _run_peer_subprocess("run_policy_peer.py", extra)
    if rc != 0:
        print(f"[FAIL] run_policy_peer.py exited with code {rc}", file=sys.stderr)
        raise SystemExit(rc)
    print("[OK] run_policy_peer.py completed successfully")


def cmd_seed_factor_peer(args):
    """Delegate to reality_engine/scripts/run_factor_peer.py (subprocess)."""
    extra: List[str] = []
    if getattr(args, "universe", None) is not None:
        extra += ["--universe", str(args.universe)]
    if getattr(args, "include_derived", False):
        extra += ["--include-derived"]
    if getattr(args, "limit", None) is not None:
        extra += ["--limit", str(args.limit)]
    rc = _run_peer_subprocess("run_factor_peer.py", extra)
    if rc != 0:
        print(f"[FAIL] run_factor_peer.py exited with code {rc}", file=sys.stderr)
        raise SystemExit(rc)
    print("[OK] run_factor_peer.py completed successfully")


def cmd_seed_supply_peer(args):
    """Delegate to reality_engine/scripts/run_supply_peer.py (subprocess)."""
    extra: List[str] = []
    if getattr(args, "universe", None) is not None:
        extra += ["--universe", str(args.universe)]
    if getattr(args, "limit", None) is not None:
        extra += ["--limit", str(args.limit)]
    rc = _run_peer_subprocess("run_supply_peer.py", extra)
    if rc != 0:
        print(f"[FAIL] run_supply_peer.py exited with code {rc}", file=sys.stderr)
        raise SystemExit(rc)
    print("[OK] run_supply_peer.py completed successfully")


def cmd_run_moe_eod(args):
    """Delegate to reality_engine/scripts/run_moe_eod.py (subprocess).

    Accepts --universe {nifty200,nifty500,all} (default nifty200), --limit,
    and --all-investor-cohorts (opt-in full 20 rows/symbol for every active
    master symbol). Preserves no-argument backward compatibility: default
    invocation still seeds the legacy MIN_SEED_SYMBOLS + EOD universe set.
    Full-universe path is triggered when --universe != nifty200 or
    --all-investor-cohorts / --include-derived is set. Subprocess stderr is
    surfaced on failure.
    """
    present = set(vars(args).keys())
    filtered: List[str] = []
    if "universe" in present and getattr(args, "universe", None) is not None:
        filtered += ["--universe", str(args.universe)]
    # Forward the opt-in full-cohort flag (support both dest names for compat)
    if "all_investor_cohorts" in present and getattr(args, "all_investor_cohorts", False):
        filtered += ["--all-investor-cohorts"]
    elif "include_derived" in present and getattr(args, "include_derived", False):
        filtered += ["--all-investor-cohorts"]
    if "limit" in present and getattr(args, "limit", None) is not None:
        filtered += ["--limit", str(args.limit)]
    rc = _run_peer_subprocess("run_moe_eod.py", filtered)
    if rc != 0:
        print(f"[FAIL] run_moe_eod.py exited with code {rc}", file=sys.stderr)
        raise SystemExit(rc)
    print("[OK] run_moe_eod.py completed successfully")


def cmd_seed_peers(args):
    """Orchestrator: supply -> quality -> policy -> factor -> moe, try/except isolated."""
    skip_raw = getattr(args, "skip", "") or ""
    # Normalize --skip a,b,c (comma-separated, case-insensitive, aliases)
    if isinstance(skip_raw, (list, tuple)):
        skip_tokens = [str(s).strip() for s in skip_raw if str(s).strip()]
    else:
        skip_tokens = [s.strip() for s in str(skip_raw).split(",") if s.strip()]
    alias = {
        "supply": "supply", "seed-supply-peer": "supply", "run_supply_peer": "supply", "run-supply-peer": "supply",
        "quality": "quality", "seed-quality-peer": "quality",
        "policy": "policy", "seed-policy-peer": "policy",
        "factor": "factor", "seed-factor-peer": "factor",
        "moe": "moe", "run-moe-eod": "moe", "run_moe_eod": "moe", "moe-eod": "moe",
    }
    skip_set = set()
    for tok in skip_tokens:
        key = tok.lower().strip()
        skip_set.add(alias.get(key, key))

    # Build per-step extra args from shared CLI options (if present)
    universe = getattr(args, "universe", None)
    limit = getattr(args, "limit", None)
    include_derived = getattr(args, "include_derived", False)

    def _args_for_supply() -> List[str]:
        extra: List[str] = []
        if universe is not None:
            extra += ["--universe", str(universe)]
        if limit is not None:
            extra += ["--limit", str(limit)]
        return extra

    def _args_for_quality_policy_factor() -> List[str]:
        extra: List[str] = []
        if universe is not None:
            extra += ["--universe", str(universe)]
        if include_derived:
            extra += ["--include-derived"]
        if limit is not None:
            extra += ["--limit", str(limit)]
        return extra

    def _args_for_moe() -> List[str]:
        extra: List[str] = []
        if universe is not None:
            extra += ["--universe", str(universe)]
        if limit is not None:
            extra += ["--limit", str(limit)]
        # seed-peers --include-derived forwards as MoE full-cohort flag;
        # also any non-default universe implicitly triggers full-universe in the runner
        if include_derived:
            extra += ["--all-investor-cohorts"]
        return extra

    steps = [
        ("supply", "run_supply_peer.py", _args_for_supply),
        ("quality", "run_quality_peer.py", _args_for_quality_policy_factor),
        ("policy", "run_policy_peer.py", _args_for_quality_policy_factor),
        ("factor", "run_factor_peer.py", _args_for_quality_policy_factor),
        ("moe", "run_moe_eod.py", _args_for_moe),
    ]

    results: Dict[str, str] = {}
    print("\n" + "=" * 75)
    print("  SEED-PEERS ORCHESTRATOR (supply -> quality -> policy -> factor -> moe)")
    print("=" * 75)
    if skip_set:
        print(f"  Skip filter: {', '.join(sorted(skip_set))}")
    if universe is not None:
        print(f"  Shared args: --universe {universe}  --limit {limit}  --include-derived {include_derived}")

    for name, script, args_fn in steps:
        if name in skip_set:
            print(f"\n[SKIP] {name} ({script}) -- skipped via --skip")
            results[name] = "SKIPPED"
            continue
        extra = args_fn()
        script_path = _peer_script_path(script)
        cmd = [sys.executable, str(script_path)] + extra
        print(f"\n[seed-peers] Step: {name} -> {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd)
            rc = result.returncode
            if rc == 0:
                print(f"[OK] {name} ({script}) completed successfully")
                results[name] = "OK"
            else:
                print(f"[FAIL] {name} ({script}) exited with code {rc}", file=sys.stderr)
                results[name] = f"FAIL:{rc}"
        except Exception as exc:
            print(f"[FAIL] {name} ({script}) exception: {exc}", file=sys.stderr)
            results[name] = "FAIL:exception"

    # Final summary
    print("\n" + "=" * 75)
    print("  SEED-PEERS SUMMARY")
    print("=" * 75)
    for name, script, _ in steps:
        status = results.get(name, "UNKNOWN")
        print(f"  {name:10s} ({script:22s}) : {status}")
    ok = sum(1 for v in results.values() if v == "OK")
    skipped = sum(1 for v in results.values() if v == "SKIPPED")
    failed = sum(1 for v in results.values() if isinstance(v, str) and v.startswith("FAIL"))
    print(f"\nTotal: {len(steps)} | OK: {ok} | FAILED: {failed} | SKIPPED: {skipped}")
    if ok == 0 and failed > 0:
        active = len(steps) - skipped
        if failed == active and active > 0:
            print("All active steps FAILED -- orchestrator exiting with error", file=sys.stderr)
            raise SystemExit(1)
    elif failed > 0:
        print(f"{failed} step(s) failed but at least one succeeded -- continuing with OK")


# ====================================================================
# CLI Parser Setup
# ====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Reality Engine CLI - Indian Equity Reality & Quant Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 1. run-phase1
    p1 = subparsers.add_parser("run-phase1", help="Execute complete Phase 1 ingestion and quant pipeline")
    p1.add_argument("--days", type=int, default=25, help="Number of Bhavcopy sessions to backfill (default: 25)")
    p1.add_argument("--top", type=int, default=200, help="Universe size for fundamentals (default: 200)")
    p1.add_argument("--workers", type=int, default=8, help="Concurrent worker threads (default: 8)")
    p1.set_defaults(func=cmd_run_phase1)

    # 2. screen
    p_scr = subparsers.add_parser("screen", help="Run composite multi-factor screener")
    p_scr.add_argument("--universe", type=str, default="nifty200", choices=["nifty200", "all", "nifty500", "nifty50"], help="Universe to screen (default: nifty200)")
    p_scr.add_argument("--top", type=int, default=20, help="Top N candidates (default: 20)")
    p_scr.add_argument("--crisis", action="store_true", default=False, help="Run crisis bargain panic screener")
    p_scr.add_argument("--date", type=str, default=None, help="Target valuation date YYYY-MM-DD")
    p_scr.add_argument("--top-down", action="store_true", default=False, dest="top_down", help="Use top-down funnel Industry≥4 → Moat≥3.5 → ENI≥0 → ROIC>WACC (Phase 6 vertical slice)")
    p_scr.add_argument("--ensemble", action="store_true", default=False, dest="ensemble", help="Use all-peers weighted ensemble (MoE blend Σ w*norm) + per-scrip learned noise floor (Wave D4)")
    p_scr.add_argument("--dry-run", action="store_true", default=False, help="Top-down dry-run: enrich with metrics but skip filters (diagnostic)")
    p_scr.set_defaults(func=cmd_screen)

    # 3. inspect-stock
    p_ins = subparsers.add_parser("inspect-stock", help="Inspect full dossier for a stock")
    p_ins.add_argument("symbol", type=str, help="Stock symbol e.g. HAL, TITAGARH, KAYNES, PIDILITIND")
    p_ins.set_defaults(func=cmd_inspect_stock)

    # 4. run-daily-alpha
    p_rda = subparsers.add_parser("run-daily-alpha", help="Run Agent orchestrator and export JSON/MD/HTML reports")
    p_rda.add_argument("--universe", type=str, default="nifty200", help="Screened universe (default: nifty200)")
    p_rda.add_argument("--top", type=int, default=20, help="Number of candidates to evaluate (default: 20)")
    p_rda.add_argument("--top-theses", type=int, default=5, help="Number of top theses to synthesize (default: 5)")
    p_rda.add_argument("--date", type=str, default=None, help="Valuation date YYYY-MM-DD")
    p_rda.add_argument("--top-down", action="store_true", default=False, dest="top_down", help="Use top-down funnel + Policy→Transmission→Moat→Verdict template (Phase 6)")
    p_rda.add_argument("--ensemble", action="store_true", default=False, dest="ensemble", help="Use all-peers weighted ensemble (MoE blend) + per-candidate MoE activation (Wave D4)")
    p_rda.add_argument("--investor-majority", type=str, default="all", dest="investor_majority",
                       choices=["promoter", "FII", "DII", "retail", "all"],
                       help="Investor-majority cohort that drives price (default: all)")
    p_rda.add_argument("--temperature", type=float, default=0.4, dest="temperature",
                       help="MoE gating temperature 0=exploit .. 1=explore (default: 0.4)")
    p_rda.set_defaults(func=cmd_run_daily_alpha)

    # 5. trace-causal-chain
    p_tc = subparsers.add_parser("trace-causal-chain", help="Trace multi-hop causal graph transmission walk")
    p_tc.add_argument("--node", type=str, required=True, help="Start node ID e.g. UNION_BUDGET_2026_RAIL_CAPEX")
    p_tc.add_argument("--max-hops", type=int, default=3, help="Max hops transmission depth (default: 3)")
    p_tc.add_argument("--impact", type=str, default="ALL", choices=["ALL", "BENEFICIARIES_ONLY", "VICTIMS_ONLY"], help="Impact filter (default: ALL)")
    p_tc.set_defaults(func=cmd_trace_causal_chain)

    # 6. simulate-macro-shock
    p_sms = subparsers.add_parser("simulate-macro-shock", help="Simulate macro shock propagation across companies")
    p_sms.add_argument("--shock", type=str, required=True, help="Shock scenario node ID e.g. UNION_BUDGET_2026_RAIL_CAPEX")
    p_sms.add_argument("--sector", type=str, default="ALL", help="Sector filter (default: ALL)")
    p_sms.set_defaults(func=cmd_simulate_macro_shock)

    # 7. monitor-panic
    p_pm = subparsers.add_parser("monitor-panic", help="Run drawdown panic monitor and output crisis bargains")
    p_pm.add_argument("--date", type=str, default=None, help="Target valuation date YYYY-MM-DD")
    p_pm.set_defaults(func=cmd_panic_monitor)

    # Alias: panic-monitor
    p_pm_alias = subparsers.add_parser("panic-monitor", help="Alias for monitor-panic")
    p_pm_alias.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    p_pm_alias.set_defaults(func=cmd_panic_monitor)

    # 8. process-inbox
    p_pi = subparsers.add_parser("process-inbox", help="Scan and ingest local drop-in inbox files")
    p_pi.add_argument("--inbox-dir", type=str, default=None, help="Custom inbox folder path")
    p_pi.set_defaults(func=cmd_process_inbox)

    # 9. seed-ontologies
    p_so = subparsers.add_parser("seed-ontologies", help="Seed dynamic parameter ontologies and canonical causal graph")
    p_so.set_defaults(func=cmd_seed_ontologies)

    # 10. search-concall
    p_sc = subparsers.add_parser("search-concall", help="Hybrid lexical + vector search over concall transcripts")
    p_sc.add_argument("--query", type=str, required=True, help="Search query string")
    p_sc.add_argument("--symbol", type=str, default=None, help="Stock symbol filter e.g. HAL, TITAGARH")
    p_sc.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")
    p_sc.set_defaults(func=cmd_search_concall)

    # 11. dashboard
    p_dash = subparsers.add_parser("dashboard", help="Launch Streamlit financial terminal dashboard")
    p_dash.add_argument("--port", type=int, default=8501, help="Port to bind dashboard (default: 8501)")
    p_dash.add_argument("--host", type=str, default="localhost", help="Host address (default: localhost)")
    p_dash.set_defaults(func=cmd_dashboard)

    # 12. bootstrap
    p_boot = subparsers.add_parser("bootstrap", help="Deterministically bootstrap database with clean test fixtures")
    p_boot.add_argument("--target-db", type=str, default=None, help="Target SQLite database path")
    p_boot.add_argument("--days", type=int, default=25, help="Number of Bhavcopy sessions to ingest (default: 25)")
    p_boot.add_argument("--top", type=int, default=200, help="Universe size for fundamentals (default: 200)")
    p_boot.add_argument("--force", action="store_true", default=False, help="Force overwrite existing database")
    p_boot.add_argument("--no-verify", action="store_true", default=False, help="Skip Top 200 checkpoint verification")
    p_boot.add_argument("--sample-only", action="store_true", default=False, help="Bootstrap lightweight sample dataset")
    p_boot.set_defaults(func=cmd_bootstrap)

    # Utilities
    p_sync = subparsers.add_parser("sync-master", help="Sync NSE & BSE Master Companies")
    p_sync.set_defaults(func=cmd_sync_master)

    p_bf = subparsers.add_parser("backfill", help="Backfill historical Bhavcopy & delivery data")
    p_bf.add_argument("--days", type=int, default=25, help="Number of sessions (default: 25)")
    p_bf.set_defaults(func=cmd_backfill)

    # bulk fundamentals fetch
    p_ff = subparsers.add_parser(
        "fetch-fundamentals",
        help="Bulk-fetch 5y fundamentals for a universe via rate-limited worker pool",
    )
    p_ff.add_argument("--top", type=int, default=200, help="Max companies to fetch (default: 200)")
    p_ff.add_argument("--workers", type=int, default=4, help="Concurrent worker threads (default: 4)")
    p_ff.add_argument("--rate-limit", type=float, default=0.5, help="Seconds to sleep between submissions (default: 0.5)")
    p_ff.add_argument("--universe", type=str, default="all", choices=["all", "nifty200"], help="Company universe (default: all)")
    p_ff.add_argument("--no-persist", action="store_true", default=False, help="Fetch but do not write to DB")
    p_ff.set_defaults(func=cmd_fetch_fundamentals)

    # bulk raw official filing discovery (Screener link discovery layer only)
    p_df = subparsers.add_parser(
        "discover-filings",
        help="Discover raw official NSE/BSE filing links via Screener (NO table copying; only official URLs)",
    )
    p_df.add_argument("--symbol", type=str, default=None, help="Single symbol e.g. RELIANCE")
    p_df.add_argument("--bse-code", type=str, default=None, help="BSE scrip code (optional, speeds BSE match)")
    p_df.add_argument("--sample", type=int, default=0, help="Safe smoke-test: process N symbols (drawn from outside Nifty200 by default)")
    p_df.add_argument("--standalone", action="store_true", default=False, help="Use Screener standalone (non-consolidated) page")
    p_df.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between Screener requests (default: 1.0)")
    p_df.add_argument("--persist", action="store_true", default=False, help="Register discovered links into corporate_documents")
    p_df.set_defaults(func=cmd_discover_filings)

    # bulk raw official filing download + archive
    p_fch = subparsers.add_parser(
        "fetch-filings",
        help="Discover AND archive raw official NSE/BSE filings (PDF/XBRL) with provenance",
    )
    p_fch.add_argument("--symbol", type=str, default=None, help="Single symbol e.g. RELIANCE")
    p_fch.add_argument("--bse-code", type=str, default=None, help="BSE scrip code (optional)")
    p_fch.add_argument("--sample", type=int, default=0, help="Safe smoke-test: process N symbols (outside Nifty200 by default)")
    p_fch.add_argument("--standalone", action="store_true", default=False, help="Use Screener standalone (non-consolidated) page")
    p_fch.add_argument("--workers", type=int, default=4, help="Concurrent download threads (default: 4)")
    p_fch.add_argument("--rate-limit", type=float, default=0.8, help="Seconds between requests (default: 0.8)")
    p_fch.add_argument("--persist", action="store_true", default=False, help="Persist archived filings + provenance to corporate_documents")
    p_fch.add_argument("--from-db", action="store_true", default=False,
                       help="Bulk mode: archive already-discovered links from corporate_documents (no re-discovery)")
    p_fch.add_argument("--max-links", type=int, default=0, help="Bulk mode cap: max links to archive (0=unlimited)")
    p_fch.add_argument("--doc-type", type=str, default=None,
                       help="Bulk mode filter: ANNUAL_REPORT | CONCALL_TRANSCRIPT | INVESTOR_PRESENTATION | FINANCIAL_RESULT | OTHER_FILING")
    p_fch.set_defaults(func=cmd_fetch_filings)

    # bulk NSE corporate actions ingestion
    p_ca = subparsers.add_parser(
        "fetch-corporate-actions",
        help="Ingest NSE corporate actions (bonus/split/rights/buyback/merger/demerger/dividend) for full universe",
    )
    p_ca.add_argument("--from-date", type=str, default="2023-01-01", help="Start date YYYY-MM-DD (default: 2023-01-01)")
    p_ca.add_argument("--slice-days", type=int, default=180, help="Date-range slice size to avoid API limits (default: 180)")
    p_ca.add_argument("--no-persist", action="store_true", default=False, help="Fetch but do not write to DB")
    p_ca.set_defaults(func=cmd_fetch_corporate_actions)

    # corporate status flags (delisting / NCLT / suspension)
    p_cs = subparsers.add_parser(
        "fetch-corporate-status",
        help="Compose delisting / NCLT (insolvency) status flags from derived + announcement-scan signals",
    )
    p_cs.add_argument("--no-persist", action="store_true", default=False, help="Build but do not write to DB")
    p_cs.set_defaults(func=cmd_fetch_corporate_status)

    p_chk = subparsers.add_parser("verify-checkpoint", help="Validate Top 200 reality checkpoint")
    p_chk.set_defaults(func=cmd_verify_checkpoint)

    p_audit = subparsers.add_parser("audit-data", help="Read-only data pipeline readiness audit (freshness, coverage, gaps, funnel tables)")
    p_audit.add_argument("--net", action="store_true", default=False, help="Also probe NSE/BSE ingestion reachability")
    p_audit.add_argument("--json", action="store_true", default=False, dest="json", help="Emit machine-readable JSON")
    p_audit.set_defaults(func=cmd_audit_data)

    # 13. listen-telegram
    p_tg_listen = subparsers.add_parser("listen-telegram", help="Start Telegram MTProto listener (live or mock)")
    p_tg_listen.add_argument("--channels", type=str, default=None, help="Comma-separated channel usernames/IDs (e.g. '@alpha,@beta,-100123')")
    p_tg_listen.add_argument("--duration", type=float, default=2.0, help="Duration in seconds to listen (default: 2.0)")
    p_tg_listen.add_argument("--mock", action="store_true", default=False, help="Run in mock offline mode (no Telethon credentials needed)")
    p_tg_listen.add_argument("--api-id", type=str, default=None, help="Telegram API ID override")
    p_tg_listen.add_argument("--api-hash", type=str, default=None, help="Telegram API Hash override")
    p_tg_listen.set_defaults(func=cmd_listen_telegram)

    # 14. simulate-telegram
    p_tg_sim = subparsers.add_parser("simulate-telegram", help="Simulate a single Telegram message for testing")
    p_tg_sim.add_argument("--text", type=str, default="Strong breakout on RELIANCE above 2950. Target: 3100 SL 2880", help="Message text")
    p_tg_sim.add_argument("--chat-id", type=str, default="mock_channel", help="Chat/channel ID")
    p_tg_sim.add_argument("--channel-title", type=str, default="Mock Channel", help="Channel title")
    p_tg_sim.add_argument("--message-id", type=int, default=1, help="Message ID")
    p_tg_sim.add_argument("--thread-id", type=int, default=0, help="Forum thread topic ID")
    p_tg_sim.add_argument("--media-path", type=str, default=None, help="Path to image file to attach")
    p_tg_sim.add_argument("--date", type=str, default=None, help="ISO timestamp")
    p_tg_sim.add_argument("--inbox-dir", type=str, default=None, help="Custom inbox dir")
    p_tg_sim.set_defaults(func=cmd_simulate_telegram)

    # 15. telegram-stats
    p_tg_stats = subparsers.add_parser("telegram-stats", help="Show telegram post statistics")
    p_tg_stats.add_argument("--limit", type=int, default=50, help="Max posts to aggregate (default: 50)")
    p_tg_stats.set_defaults(func=cmd_telegram_stats)

    # 16. telegram-backfill
    p_tg_bf = subparsers.add_parser("telegram-backfill", help="Fetch recent thread history from Telegram channels and ingest posts")
    p_tg_bf.add_argument("--channels", type=str, default=None, help="Comma-separated channel IDs/usernames e.g. '-1002413883243'")
    p_tg_bf.add_argument("--limit", type=int, default=50, help="Max messages per page (default: 50)")
    p_tg_bf.add_argument("--thread-id", type=int, default=None, help="Forum topic/thread ID filter (reply_to)")
    p_tg_bf.add_argument("--thread-name", type=str, default=None, help="Forum topic title (resolved via GetForumTopicsRequest)")
    p_tg_bf.add_argument("--all", action="store_true", default=False, help="Walk entire thread history (paginated, safety-capped)")
    p_tg_bf.add_argument("--safety-cap", type=int, default=300, help="Max pages when --all (default: 300)")
    p_tg_bf.add_argument("--max-exists", type=int, default=30, help="Max summary rows to print (default: 30)")
    p_tg_bf.set_defaults(func=cmd_telegram_backfill)

    # 17. telegram-scan
    p_tg_scan = subparsers.add_parser("telegram-scan", help="Probe channels and list chat meta without persisting")
    p_tg_scan.add_argument("--channels", type=str, default=None, help="Comma-separated channel IDs/usernames")
    p_tg_scan.set_defaults(func=cmd_telegram_scan)

    # 18. telegram-threads
    p_tg_thr = subparsers.add_parser("telegram-threads", help="List forum topics/threads in a supergroup")
    p_tg_thr.add_argument("--channels", type=str, default=None, help="Comma-separated channel IDs/usernames")
    p_tg_thr.set_defaults(func=cmd_telegram_threads)

    # 19. prune-decayed-signals (Phase 5 Pillar 3B)
    p_prune = subparsers.add_parser("prune-decayed-signals", help="Prune decayed signals: drop embeddings >12m (retain Milestone), delete ghost ripples, archive macro >24m (SQLite fallback, PG procedure)")
    p_prune.add_argument("--dry-run", action="store_true", default=False, help="Count without deleting")
    p_prune.add_argument("--show-decayed", action="store_true", default=False, help="Also show v_ripple_decayed rows")
    p_prune.add_argument("--show-cold", action="store_true", default=False, help="Also show cold-tier >36m export count")
    p_prune.add_argument("--limit", type=int, default=10, help="Limit for decayed view when --show-decayed")
    p_prune.set_defaults(func=cmd_prune_decayed_signals)
    # alias prune
    p_prune2 = subparsers.add_parser("prune", help="Alias for prune-decayed-signals")
    p_prune2.add_argument("--dry-run", action="store_true", default=False, help="Count without deleting")
    p_prune2.add_argument("--show-decayed", action="store_true", default=False, help="Also show v_ripple_decayed")
    p_prune2.add_argument("--show-cold", action="store_true", default=False, help="Also show cold-tier")
    p_prune2.add_argument("--limit", type=int, default=10, help="Limit for decayed view")
    p_prune2.set_defaults(func=cmd_prune_decayed_signals)

    # 20. run-distillation (Phase 5 Pillar 4)
    p_dist = subparsers.add_parser("run-distillation", help="Monthly distillation batch 20 YouTube+4 Concall -> UPDATE moat_evaluations -> purge 24 vectors -> log distillation_runs")
    p_dist.add_argument("symbol", nargs="?", default="HAL", help="Ticker symbol to distill (default HAL)")
    p_dist.add_argument("--youtube", type=int, default=20, help="YouTube chunks (default 20)")
    p_dist.add_argument("--concall", type=int, default=4, help="Concall chunks (default 4)")
    p_dist.set_defaults(func=cmd_run_distillation)
    # alias distill
    p_dist2 = subparsers.add_parser("distill", help="Alias for run-distillation")
    p_dist2.add_argument("symbol", nargs="?", default="HAL", help="Ticker symbol")
    p_dist2.add_argument("--youtube", type=int, default=20, help="YouTube chunks")
    p_dist2.add_argument("--concall", type=int, default=4, help="Concall chunks")
    p_dist2.set_defaults(func=cmd_run_distillation)

    # 21. fetch-macro (second-tier macro PDF peer data)
    p_fm = subparsers.add_parser(
        "fetch-macro",
        help="Fetch macro-policy PDFs (Central/State Budgets, PIB circulars, RBI reports) into raw_documents",
    )
    p_fm.add_argument("--source", type=str, default="all",
                      choices=["central", "states", "pib", "rbi", "all"],
                      help="Macro source subset (default: all)")
    p_fm.add_argument("--years", type=str, default="2024-25,2025-26",
                      help="Comma-separated fiscal years (default: 2024-25,2025-26)")
    p_fm.add_argument("--state-filter", type=str, default=None,
                      help="Comma-separated state codes (UP,Tamil_Nadu,Maharashtra,Karnataka,Telangana,Gujarat,Haryana,Andhra_Pradesh)")
    p_fm.add_argument("--workers", type=int, default=4, help="Reserved (sequential fetch; rate-limited)")
    p_fm.add_argument("--pib-limit", type=int, default=10, help="Max PIB circulars to fetch")
    p_fm.add_argument("--since-date", type=str, default=None, help="PIB since-date filter YYYY-MM-DD")
    p_fm.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between requests (default 1.0)")
    p_fm.add_argument("--dry-run", action="store_true", default=False,
                      help="Plan URLs and report counts without downloading or writing to DB")
    p_fm.add_argument("--ingest", action="store_true", default=False,
                      help="After download, ingest each PDF into document_chunks + FTS (dense substrate). "
                           "Ignored when --dry-run is set.")
    p_fm.set_defaults(func=cmd_fetch_macro)

    # Alias: fetch-headless (AGENTS.md compat — headless macro feed fetch)
    p_fh = subparsers.add_parser(
        "fetch-headless",
        help="Alias for fetch-macro (headless macro PDF feeds: budgets/PIB/RBI)",
    )
    p_fh.add_argument("--source", type=str, default="all",
                      choices=["central", "states", "pib", "rbi", "all"],
                      help="Macro source subset (default: all)")
    p_fh.add_argument("--years", type=str, default="2024-25,2025-26",
                      help="Comma-separated fiscal years (default: 2024-25,2025-26)")
    p_fh.add_argument("--state-filter", type=str, default=None, help="Comma-separated state codes")
    p_fh.add_argument("--workers", type=int, default=4, help="Reserved (sequential fetch)")
    p_fh.add_argument("--pib-limit", type=int, default=10, help="Max PIB circulars to fetch")
    p_fh.add_argument("--since-date", type=str, default=None, help="PIB since-date filter YYYY-MM-DD")
    p_fh.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between requests")
    p_fh.add_argument("--dry-run", action="store_true", default=False,
                      help="Plan URLs and report counts without downloading or writing to DB")
    p_fh.add_argument("--ingest", action="store_true", default=False,
                      help="After download, ingest each PDF into document_chunks + FTS (dense substrate). "
                           "Ignored when --dry-run is set.")
    p_fh.set_defaults(func=cmd_fetch_macro)

    # 22. process-macro (scan MACRO_PDFS_DIR and ingest into dense substrate)
    p_pm = subparsers.add_parser(
        "process-macro",
        help="Scan MACRO_PDFS_DIR recursively for *.pdf and ingest into document_chunks + FTS (idempotent)",
    )
    p_pm.add_argument("--dry-run", action="store_true", default=False,
                     help="List files that would be ingested without ingesting")
    p_pm.add_argument("--directory", type=str, default=None,
                      help="Custom macro PDF directory to scan (default: MACRO_PDFS_DIR)")
    p_pm.set_defaults(func=cmd_process_macro)

    # 23. rank-models (Wave D sparse MoE per-stock / per-investor-majority lens rankings)
    p_rm = subparsers.add_parser(
        "rank-models",
        help="Show per-stock / per-investor-majority MoE lens rankings (model_explainer_rankings)",
    )
    p_rm.add_argument("--symbol", type=str, required=True, help="Ticker symbol, e.g. HAL")
    p_rm.add_argument(
        "--investor-majority", type=str, default="all",
        choices=["promoter", "FII", "DII", "retail", "all"],
        help="Investor majority cohort that drives price (default: all)",
    )
    p_rm.set_defaults(func=cmd_rank_models)

    # 24. spawn-event-graph (Wave D2 transient event-graph spawner)
    p_seg = subparsers.add_parser(
        "spawn-event-graph",
        help="Spawn a transient macro/event graph (macro_events + ripple_effects DAG) into the dense substrate",
    )
    p_seg.add_argument("--event", type=str, default="US_TARIFF_TEXTILE_RELIEF",
                       help="Transient event id to spawn (default: US_TARIFF_TEXTILE_RELIEF)")
    p_seg.add_argument("--max-hops", type=int, default=3, dest="max_hops",
                       help="Max ripple depth to trace after spawn (default: 3)")
    p_seg.set_defaults(func=cmd_spawn_event_graph)

    # 25. correct-eod (Wave D3 continuous self-correction: EOD batch)
    p_ce = subparsers.add_parser(
        "correct-eod",
        help="Run EOD self-correction batch (learned noise floor + MoE lens re-rank + substrate drift)",
    )
    p_ce.add_argument("--universe", type=str, default="nifty200", help="Universe selector (default: nifty200)")
    p_ce.add_argument("--date", type=str, default=None, help="Closed-session EOD date YYYY-MM-DD (default: latest)")
    p_ce.add_argument("--dry-run", action="store_true", default=False, dest="dry_run", help="Compute but do not persist corrections")
    p_ce.add_argument("--update-substrate", action="store_true", default=False, dest="update_substrate", help="Nudge moat trajectory toward realized regime on drift")
    p_ce.add_argument("--symbols", type=str, default=None, help="Comma-separated symbol override (default: whole universe)")
    p_ce.set_defaults(func=cmd_correct_eod)

    # 26. correct-event (Wave D3 event-driven correction)
    p_cv = subparsers.add_parser(
        "correct-event",
        help="Run event-driven self-correction (refresh transient graph + re-rank impacted lenses)",
    )
    p_cv.add_argument("--event", type=str, required=True, help="Event id e.g. US_TARIFF_TEXTILE_RELIEF")
    p_cv.add_argument("--symbols", type=str, default=None, help="Comma-separated impacted symbols override")
    p_cv.add_argument("--dry-run", action="store_true", default=False, dest="dry_run", help="Compute but do not persist corrections")
    p_cv.set_defaults(func=cmd_correct_event)

    # 27. noise-floor (Wave D3 per-scrip learned noise floor)
    p_nf = subparsers.add_parser(
        "noise-floor",
        help="Show the vol/liquidity-adaptive per-scrip learned noise floor for a symbol",
    )
    p_nf.add_argument("--symbol", type=str, required=True, help="Ticker symbol e.g. TITAGARH")
    p_nf.add_argument("--turnover", type=float, default=None, help="Turnover (lacs) override for the adaptive stub")
    p_nf.add_argument("--change", type=float, default=None, help="Change %% override for the adaptive stub")
    p_nf.set_defaults(func=cmd_noise_floor)

    # 28. seed-quality-peer (lane-code-cli: Business Quality peer via run_quality_peer.py)
    p_qp = subparsers.add_parser(
        "seed-quality-peer",
        help="Seed Business Quality peer (moat_evaluations + business_model_profiles) via run_quality_peer.py",
    )
    p_qp.add_argument("--universe", type=str, default="nifty200", choices=["nifty200", "nifty500", "all"],
                      help="Universe to seed (default: nifty200)")
    p_qp.add_argument("--include-derived", action="store_true", default=False, dest="include_derived",
                      help="Include derived industry-arch mapping (forwarded to script)")
    p_qp.add_argument("--limit", type=int, default=None, help="Limit symbols to seed (forwarded to script)")
    p_qp.set_defaults(func=cmd_seed_quality_peer)

    # 29. seed-policy-peer (lane-code-cli: Policy Macro peer via run_policy_peer.py)
    p_pp = subparsers.add_parser(
        "seed-policy-peer",
        help="Seed Policy Macro peer (regulatory_political_risks + ENI) via run_policy_peer.py",
    )
    p_pp.add_argument("--universe", type=str, default="nifty200", choices=["nifty200", "nifty500", "all"],
                      help="Universe to seed (default: nifty200)")
    p_pp.add_argument("--include-derived", action="store_true", default=False, dest="include_derived",
                      help="Include derived mapping (forwarded to script)")
    p_pp.add_argument("--limit", type=int, default=None, help="Limit symbols to seed (forwarded to script)")
    p_pp.set_defaults(func=cmd_seed_policy_peer)

    # 30. seed-factor-peer (lane-code-cli: Factor/Statistical peer via run_factor_peer.py)
    p_fp = subparsers.add_parser(
        "seed-factor-peer",
        help="Seed Factor/Statistical peer (financial_metrics) via run_factor_peer.py",
    )
    p_fp.add_argument("--universe", type=str, default="nifty200", choices=["nifty200", "nifty500", "all"],
                      help="Universe to seed (default: nifty200)")
    p_fp.add_argument("--include-derived", action="store_true", default=False, dest="include_derived",
                      help="Include derived mapping (forwarded to script)")
    p_fp.add_argument("--limit", type=int, default=None, help="Limit symbols to seed (forwarded to script)")
    p_fp.set_defaults(func=cmd_seed_factor_peer)

    # 31. seed-supply-peer (lane-code-cli: Supply Chain peer via run_supply_peer.py)
    p_sp = subparsers.add_parser(
        "seed-supply-peer",
        help="Seed Supply Chain peer (geographic_exposure + ripple_effects) via run_supply_peer.py",
    )
    p_sp.add_argument("--universe", type=str, default="nifty200", choices=["nifty200", "nifty500", "all"],
                      help="Universe to seed (default: nifty200)")
    p_sp.add_argument("--limit", type=int, default=None, help="Limit symbols to seed (forwarded to script)")
    p_sp.set_defaults(func=cmd_seed_supply_peer)

    # 32. run-moe-eod (lane-code-cli: MoE seeding & EOD correction via run_moe_eod.py)
    p_moe = subparsers.add_parser(
        "run-moe-eod",
        help="Run MoE seeding & EOD correction loop (model_explainer_rankings + lens_activation_log) via run_moe_eod.py",
    )
    p_moe.add_argument("--universe", type=str, default="nifty200", choices=["nifty200", "nifty500", "all"],
                       help="Universe to seed (default: nifty200)")
    p_moe.add_argument("--limit", type=int, default=None, help="Limit symbols to seed (forwarded to script)")
    p_moe.add_argument("--all-investor-cohorts", action="store_true", default=False, dest="all_investor_cohorts",
                       help="Seed all 5 investor cohorts for every symbol (full-universe MoE, 20 rows/symbol)")
    # Alias for seed-peers forwarding compatibility (maps to --all-investor-cohorts)
    p_moe.add_argument("--include-derived", action="store_true", default=False, dest="include_derived", help=argparse.SUPPRESS)
    p_moe.set_defaults(func=cmd_run_moe_eod)

    # 33. seed-peers orchestrator (lane-code-cli: supply -> quality -> policy -> factor -> moe)
    p_peers = subparsers.add_parser(
        "seed-peers",
        help="Orchestrator: seed supply -> quality -> policy -> factor -> moe (subprocess, per-step OK/FAIL, continue on failure)",
    )
    p_peers.add_argument("--universe", type=str, default="nifty200", choices=["nifty200", "nifty500", "all"],
                         help="Universe forwarded to peers (default: nifty200)")
    p_peers.add_argument("--include-derived", action="store_true", default=False, dest="include_derived",
                         help="Forward --include-derived to quality/policy/factor steps")
    p_peers.add_argument("--limit", type=int, default=None, help="Forward --limit to peers")
    p_peers.add_argument("--skip", type=str, default="",
                         help="Comma-separated steps to skip: supply,quality,policy,factor,moe (e.g. --skip supply,moe)")
    p_peers.set_defaults(func=cmd_seed_peers)

    parsed_args = parser.parse_args()
    if not parsed_args.command:
        parser.print_help()
    else:
        parsed_args.func(parsed_args)


if __name__ == "__main__":
    main()
