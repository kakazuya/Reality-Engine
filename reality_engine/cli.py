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
def cmd_fetch_offer_docs(args):
    """Discover SEBI DRHP/Prospectus filings and archive the offer PDFs.

    Discovery via ``sebi_offer_client`` (ajax listing search, no browser);
    archival reuses ``official_filing_client`` unchanged — the discovery record
    matches the ``filing_discovery`` shape. Persist gated by ``--persist`` like
    the sibling fetch commands. ``--doc-date`` falls back to the listing date
    carried on each link; unknown dates persist as NULL (never 1970-01-01).
    """
    from reality_engine.ingestion.sebi_offer_client import sebi_offer_client
    from reality_engine.ingestion.official_filing_client import official_filing_client
    from reality_engine.db.repository import repo as _repo

    stage = (getattr(args, "stage", "both") or "both").lower()
    company_arg = (getattr(args, "company_name", None) or "").strip() or None
    symbol_arg = (getattr(args, "symbol", None) or "").strip().upper() or None
    if symbol_arg or company_arg:
        companies = [{
            "nse_symbol": symbol_arg or company_arg.upper().replace(" ", "_")[:32],
            "company_name": company_arg,
        }]
    else:
        companies = _repo.get_all_companies(active_only=True)
        if getattr(args, "sample", None):
            non_nifty200 = [c for c in companies if not c.get("is_nifty200")]
            companies = (non_nifty200 if non_nifty200 else companies)[: args.sample]

    print(f"Discovering SEBI offer documents for {len(companies)} symbol(s) (stage={stage})...")
    discoveries = []
    for c in companies:
        sym = (c.get("nse_symbol") or c.get("symbol") or "").strip().upper()
        if not sym:
            continue
        name = c.get("company_name") or c.get("companyName")
        disc = sebi_offer_client.discover_offer_documents(
            sym, company_name=name, stage=stage, max_results=getattr(args, "max_results", 10),
        )
        discoveries.append(disc)
        flag = "ERROR" if disc.get("error") else "ok"
        print(f"  {sym}: {len(disc.get('links', []))} offer doc(s) [{flag}]")
        for ln in disc.get("links", [])[:5]:
            print(f"      - {ln.get('offer_stage', '?'):5s} {ln.get('title', '')[:80]}")

    result = official_filing_client.archive_many(
        discoveries, max_workers=getattr(args, "workers", 2), progress=True
    )
    print(json.dumps({k: v for k, v in result.items() if k != "per_symbol"}, indent=2))
    if args.persist:
        recs = []
        for sym_res in result.get("per_symbol", []):
            sym = sym_res.get("symbol")
            for r in sym_res.get("results", []):
                recs.append({
                    "isin": None, "symbol": sym, "doc_type": r.get("doc_type"),
                    "title": r.get("title") or r.get("doc_type"),
                    "doc_date": r.get("doc_date"),
                    "source_url": r.get("source_url"), "source": r.get("source"),
                    "discovery_source": r.get("discovery_source"),
                    "local_file_path": r.get("local_file_path"),
                    "file_size_bytes": r.get("file_size_bytes", 0),
                    "sha256_hash": r.get("sha256_hash"),
                    "is_processed": 1 if r.get("ok") else 0,
                })
        sym_to_isin = {c.get("nse_symbol"): c.get("isin") for c in companies if c.get("nse_symbol")}
        for rr in recs:
            rr["isin"] = sym_to_isin.get(rr["symbol"])
        n = _repo.upsert_corporate_documents(recs)
        print(f"\nPersisted {n} offer document record(s) to corporate_documents.")
    else:
        print("Dry run: pass --persist to write to corporate_documents.")
def cmd_offer_backfill(args):
    """Run the SEBI DRHP/Prospectus bulk backfill (crawl -> match -> archive -> ingest -> distill)."""
    from reality_engine.pipeline.offer_backfill import run_once
    from pathlib import Path as _P
    stage_arg = getattr(args, "stage", "both") or "both"
    stages = ("final", "draft") if stage_arg == "both" else (stage_arg,)
    result = run_once(
        loop_dir=_P(args.loop_dir) if getattr(args, "loop_dir", None) else None,
        dry_run=not getattr(args, "apply", False),
        stages=stages,
        max_pages=getattr(args, "max_pages", 0) or 0,
        max_archive=getattr(args, "max_archive", 0) or 0,
        max_workers=getattr(args, "workers", 8) or 8,
    )
    print(json.dumps(result, indent=2, default=str))


def cmd_embed_setup(args):
    """Download the ONNX embedding model (bge-small-en-v1.5) into data/models."""
    from reality_engine.ingestion.onnx_embedder import onnx_embedder
    ok = onnx_embedder.ensure_downloaded()
    print(json.dumps({"ok": ok, **onnx_embedder.status()}, indent=2))


def cmd_embed_status(args):
    """Show ONNX embedding backend status (provider, files, dimension)."""
    from reality_engine.ingestion.onnx_embedder import embed_status
    print(json.dumps(embed_status(), indent=2))


def cmd_reembed_chunks(args):
    """Re-embed document_chunks rows with the ONNX backend (batched, idempotent).

    Default scope is OFFER_DOCUMENT rows whose embedding is missing or looks
    like the 384-dim hash fallback. --all extends to every chunk row.
    --limit caps rows per run; re-runs resume (completed rows are skipped).
    """
    import json as _json
    from reality_engine.db.database import db_manager
    from reality_engine.db.vector_store import VectorStoreManager
    limit = int(getattr(args, "limit", 0) or 0)
    scope_all = bool(getattr(args, "all", False))
    batch = int(getattr(args, "batch", 64) or 64)
    vs = VectorStoreManager()
    where = "" if scope_all else "WHERE rd.source_type = 'OFFER_DOCUMENT'"
    with db_manager.session() as conn:
        rows = conn.execute(
            "SELECT dc.chunk_id, dc.content FROM document_chunks dc "
            "JOIN raw_documents rd ON dc.doc_id = rd.doc_id "
            f"{where} ORDER BY dc.chunk_id",  # nosec - where is a static literal
        ).fetchall()
    todo = []
    for cid, content in rows:
        if not content:
            continue
        todo.append((cid, content))
        if limit and len(todo) >= limit:
            break
    done, skipped, total = 0, 0, len(todo)
    for i in range(0, len(todo), batch):
        sl = todo[i : i + batch]
        vecs = vs.embed_many([t for _, t in sl])
        with db_manager.session() as conn:
            for (cid, _), vec in zip(sl, vecs):
                try:
                    conn.execute(
                        "UPDATE document_chunks SET embedding=? WHERE chunk_id=?",
                        (_json.dumps(vec), cid),
                    )
                    done += 1
                except Exception:
                    skipped += 1
            conn.commit()
    print(_json.dumps({"total": total, "reembedded": done, "skipped": skipped,
                       "provider": vs.embed("probe") is not None}, indent=2))


LLM_SERVER_PROC_NAME = "llama-server"
LLM_DEFAULT_PORT = 8080
LLM_REPO_ID = "prism-ml/Ternary-Bonsai-2-27B-gguf"
LLM_FILENAME = "Ternary-Bonsai-2-27B-PQ2_0.gguf"


def _llm_paths():
    """llama-server binary + GGUF model locations (data dir, git-ignored)."""
    from pathlib import Path as _P
    from reality_engine import config as _cfg
    bindir = _P(_cfg.DATA_DIR) / "llama-bonsai"
    modeldir = _P(_cfg.DATA_DIR) / "models" / "bonsai-27b"
    server = bindir / "llama-server.exe"
    gguf = modeldir / LLM_FILENAME
    cached = list(modeldir.glob(f"**/{LLM_FILENAME}"))
    if not gguf.exists() and cached:
        gguf = cached[0]
    return server, gguf


def cmd_llm_setup(args):
    """Download the Bonsai PQ2_0 GGUF model (~6.7 GB) into data/models (resumable)."""
    from huggingface_hub import hf_hub_download
    from pathlib import Path as _P
    from reality_engine import config as _cfg
    dest = _P(_cfg.DATA_DIR) / "models" / "bonsai-27b"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / LLM_FILENAME
    if target.exists() and target.stat().st_size > 5_000_000_000:
        print(json.dumps({"ok": True, "path": str(target), "cached": True}, indent=2))
        return
    got = hf_hub_download(repo_id=LLM_REPO_ID, filename=LLM_FILENAME,
                          local_dir=str(dest))
    got_p = _P(got)
    if got_p.resolve() != target.resolve() and got_p.exists():
        try:
            got_p.replace(target)
        except OSError:
            target = got_p
    print(json.dumps({"ok": target.exists(), "path": str(target)}, indent=2))


def cmd_llm_serve(args):
    """Start llama-server (Vulkan, full GPU offload) as a supervised process."""
    from reality_engine import config as _cfg
    server, gguf = _llm_paths()
    if not server.exists():
        print(json.dumps({"ok": False, "error": f"missing {server}; see docs for the b11064 vulkan build"}, indent=2))
        return
    if not gguf.exists():
        print(json.dumps({"ok": False, "error": f"missing model; run `cli.py llm-setup` first"}, indent=2))
        return
    port = int(getattr(args, "port", LLM_DEFAULT_PORT) or LLM_DEFAULT_PORT)
    ctx = max(32768, int(getattr(args, "ctx", 32768) or 32768))
    import subprocess
    log_path = _llm_paths()[0].parent / f"llama-server-{port}.log"
    with open(log_path, "ab") as logfh:
        proc = subprocess.Popen(
            [str(server), "--model", str(gguf), "--host", "127.0.0.1",
             "--port", str(port), "--ctx-size", str(ctx), "--n-gpu-layers", "99",
             "--device", "Vulkan0", "--jinja", "--threads", "-1",
             "--load-mode", "mmap", "--reasoning-budget", "512",
             "--temp", "0.5", "--top-p", "0.85", "--top-k", "20", "--min-p", "0.0"],
            stdout=logfh, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    from reality_engine.ingestion.llm_lens_client import LensLLMClient
    import time
    client = LensLLMClient(base_url=f"http://127.0.0.1:{port}")
    ready = False
    for _ in range(120):
        if client.health():
            ready = True
            break
        time.sleep(2)
    print(json.dumps({"ok": ready, "pid": proc.pid, "port": port,
                      "model": str(gguf), "log": str(log_path)}, indent=2))


def cmd_llm_status(args):
    """Probe the running llama-server (/health + a 1-token generation)."""
    from reality_engine.ingestion.llm_lens_client import LensLLMClient
    port = int(getattr(args, "port", LLM_DEFAULT_PORT) or LLM_DEFAULT_PORT)
    client = LensLLMClient(base_url=f"http://127.0.0.1:{port}")
    ok = client.health()
    print(json.dumps({"ok": ok, "base_url": client.base_url}, indent=2))


def cmd_lens_extract(args):
    """Run one lens pass over stored chunks (macro or moat) via the local LLM.

    ``--kind macro`` distills one OFFER_DOCUMENT raw doc into macro_events +
    ripple_effects; ``--kind moat`` synthesizes one symbol's moat deltas.
    Dry-run (default) prints the lens dict without writing; ``--apply`` writes.
    """
    from reality_engine.db.database import db_manager
    from reality_engine.ingestion.llm_lens_client import LensLLMClient
    port = int(getattr(args, "port", LLM_DEFAULT_PORT) or LLM_DEFAULT_PORT)
    client = LensLLMClient(base_url=f"http://127.0.0.1:{port}")
    kind = (getattr(args, "kind", "moat") or "moat").lower()
    apply = bool(getattr(args, "apply", False))
    if kind == "macro":
        from reality_engine.processing.distillation_engine import DistillationEngine
        doc_id = getattr(args, "doc_id", None)
        if doc_id is None:
            with db_manager.session() as conn:
                row = conn.execute("SELECT doc_id FROM raw_documents WHERE source_type='OFFER_DOCUMENT' ORDER BY doc_id LIMIT 1").fetchone()
            if not row:
                print(json.dumps({"ok": False, "error": "no OFFER_DOCUMENT rows"}, indent=2))
                return
            doc_id = int(row[0] if isinstance(row, tuple) else row["doc_id"])
        if not apply:
            raw = DistillationEngine().repo.get_raw_document_by_id(doc_id)
            chunks = DistillationEngine().repo.get_document_chunks_for_doc(doc_id, limit=6)
            out = client.extract_macro("\n".join(chunks), raw or {})
            print(json.dumps({"ok": True, "doc_id": doc_id, "lens": out}, indent=2, default=str))
            return
        res = DistillationEngine().distill_macro_document(int(doc_id), llm_client=client)
        print(json.dumps({"ok": True, **res}, indent=2, default=str))
        return
    symbol = (getattr(args, "symbol", None) or "HAL").upper()
    if not apply:
        with db_manager.session() as conn:
            rows = conn.execute("SELECT dc.content FROM document_chunks dc JOIN raw_documents rd ON dc.doc_id=rd.doc_id "
                                "WHERE dc.symbol=? AND rd.source_type='OFFER_DOCUMENT' ORDER BY dc.chunk_index LIMIT 6",
                                (symbol,)).fetchall()
        texts = [r[0] for r in rows if r and r[0]]
        if not texts:
            print(json.dumps({"ok": False, "error": f"no OFFER_DOCUMENT chunks for {symbol}"}, indent=2))
            return
        out = client.synthesize(symbol, texts)
        print(json.dumps({"ok": True, "symbol": symbol, "lens": out}, indent=2, default=str))
        return
    from reality_engine.processing.distillation_pruner import synthesize_and_update
    res = synthesize_and_update(symbol, [], manager=db_manager, llm_client=client)
    print(json.dumps({"ok": True, **res}, indent=2, default=str))


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


def cmd_nightly(args):
    """Run the Wave A unattended nightly chain (fetch -> predict -> correct)."""
    from reality_engine.pipeline.nightly_alpha import run_nightly

    summary = run_nightly(
        dry_run=bool(getattr(args, "dry_run", False)),
        part=getattr(args, "part", "all"),
        date_str=getattr(args, "date", None),
        universe=getattr(args, "universe", "nifty200"),
        top_n=int(getattr(args, "top", 20) or 20),
    )
    rc = int(summary.get("exit_code", 0))
    if rc != 0:
        raise SystemExit(rc)


# ====================================================================
# News-feed v1 (Tier-0 + Tier-1): read-only explain + lazy slice imports
# ====================================================================

def cmd_fetch_announcements(args):
    """Fetch NSE announcements for a date window (persist gated by --persist)."""
    from_date = getattr(args, "from_date", None)
    to_date = getattr(args, "to_date", None)
    index = getattr(args, "index", "equities") or "equities"
    persist = bool(getattr(args, "persist", False))
    try:
        from reality_engine.ingestion.news_announcements_client import news_announcements_client
        raw = news_announcements_client.fetch_window(from_date, to_date, index=index)
        records, stats = news_announcements_client.normalize(raw)
    except Exception as exc:
        print(f"fetch-announcements miss ({from_date}..{to_date}): {exc}")
        return
    skipped = (stats or {}).get("skipped", 0) if isinstance(stats, dict) else 0
    print(f"Fetched {len(raw)} raw announcement(s), {len(records)} normalized, {skipped} skipped.")
    if persist:
        try:
            n = news_announcements_client.persist(records)
            print(f"Persisted {n} announcement record(s) to corporate_documents.")
        except Exception as exc:
            print(f"fetch-announcements persist miss: {exc}")
    else:
        print("Dry run: pass --persist to write to corporate_documents.")


def cmd_fetch_deals(args):
    """Fetch NSE bulk + block deals for today (persist gated by --persist)."""
    persist = bool(getattr(args, "persist", False))
    try:
        from reality_engine.ingestion.deals_client import deals_client
        all_records = []
        total_skipped = 0
        for kind in ("BULK", "BLOCK"):
            try:
                text = deals_client.fetch_csv(kind)
                records, stats = deals_client.normalize(text, kind)
            except Exception as exc:
                print(f"fetch-deals miss for {kind}: {exc}")
                continue
            skipped = (stats or {}).get("skipped", 0) if isinstance(stats, dict) else 0
            total_skipped += skipped
            all_records.extend(records)
            print(f"  {kind}: {len(records)} normalized, {skipped} skipped.")
    except Exception as exc:
        print(f"fetch-deals miss: {exc}")
        return
    print(f"Fetched {len(all_records)} deal record(s), {total_skipped} skipped.")
    if persist:
        try:
            from reality_engine.ingestion.deals_client import deals_client as _dc
            n = _dc.persist(all_records)
            print(f"Persisted {n} deal record(s) to bulk_block_deals.")
        except Exception as exc:
            print(f"fetch-deals persist miss: {exc}")
    else:
        print("Dry run: pass --persist to write to bulk_block_deals.")


def cmd_explain_move(args):
    """Explain a symbol's move on a date from Tier-0 tables (read-only)."""
    from reality_engine.processing.news_explainer import explain_move
    symbol = str(getattr(args, "symbol", "") or "").upper()
    date = getattr(args, "date", None)
    window = int(getattr(args, "window", 2) or 2)
    out = explain_move(symbol, date, window_days=window)
    verdict = out.get("verdict", {}) or {}
    print(f"{out.get('symbol')} @ {out.get('target_date')}: {verdict.get('severity', 'LOW')}")
    for d in verdict.get("drivers", []) or []:
        print(f"  - {d}")
    price = out.get("price")
    if price is None:
        print("Price: n/a (no daily_price_delivery row)")
    else:
        print(f"Price: close={price.get('close')} prev={price.get('prev_close')} "
              f"chg%={price.get('change_pct')} del_spike={price.get('delivery_spike_ratio')}")
    print(f"Announcements ({len(out.get('announcements', []))}):")
    for a in out.get("announcements", []) or []:
        print(f"  [{a.get('doc_date')}] {a.get('title')} ({a.get('source_url')})")
    print(f"Corporate actions ({len(out.get('corp_actions', []))}):")
    for c in out.get("corp_actions", []) or []:
        print(f"  [{c.get('ex_date')}] {c.get('action_type')}: {c.get('subject')}")
    print(f"Deals ({len(out.get('deals', []))}):")
    for t in out.get("deals", []) or []:
        print(f"  [{t.get('deal_date')}] {t.get('deal_type')} {t.get('buy_sell')} "
              f"{t.get('client_name')} {t.get('quantity')} @ {t.get('trade_price')}")


def cmd_search_intel(args):
    """Tier-filtered search over intelligence_fts (fail-closed if module absent)."""
    try:
        from reality_engine.search.intel_search import search_intel
    except Exception as exc:
        print(f"search-intel unavailable: {exc}")
        return
    tiers_raw = getattr(args, "tiers", "0,1") or "0,1"
    try:
        tiers = tuple(int(t.strip()) for t in str(tiers_raw).split(",") if t.strip() != "")
    except ValueError:
        print(f"search-intel: bad --tiers value {tiers_raw!r}, expected e.g. 0,1")
        return
    hits = search_intel(
        getattr(args, "query", ""),
        symbol=getattr(args, "symbol", None),
        since=getattr(args, "since", None),
        tiers=tiers or (0, 1),
        top_k=int(getattr(args, "top_k", 10) or 10),
    )
    if not hits:
        print("No intelligence hits.")
        return
    for h in hits:
        print(f"[{h.get('tier')}] {h.get('source_type')} {h.get('symbol')} "
              f"{h.get('document_date')} score={h.get('score'):.3f} :: {h.get('chunk_id')}")
        print(f"  {(h.get('text') or '')[:300]}")

# ====================================================================
# News-feed Tier-2 (rumor corroboration) + Tier-3 (attention digest):
# read-only, lazy slice imports, fail-closed.
# ====================================================================

def cmd_rumor_scan(args):
    """Tier-2 rumor scan: corroborate telegram claims for a symbol (read-only)."""
    try:
        from reality_engine.processing.rumor_scorer import corroborate
    except Exception as exc:
        print(f"rumor-scan unavailable: {exc}")
        return
    try:
        rows = corroborate(
            symbol=getattr(args, "symbol", None),
            since=getattr(args, "since", None),
            window_hours=int(getattr(args, "window_hours", 72) or 72),
            min_confirm=int(getattr(args, "min_confirm", 2) or 2),
        )
    except Exception as exc:
        print(f"rumor-scan miss: {exc}")
        return
    if not rows:
        print("No corroborated rumors.")
        return
    for r in rows:
        print(f"[{r.get('status')}] {r.get('symbol')} n={r.get('n_sources')} "
              f"tier0={r.get('tier0_hit')} first={r.get('first_seen')} :: {(r.get('claim') or '')[:200]}")
        for s in r.get("sources", []) or []:
            print(f"    - {s}")


def cmd_rumor_resolve(args):
    """Tier-2 rumor resolve: confirmed/unconfirmed claims for a symbol on a date (read-only)."""
    try:
        from reality_engine.processing.rumor_scorer import score_rumor
    except Exception as exc:
        print(f"rumor-resolve unavailable: {exc}")
        return
    try:
        out = score_rumor(
            getattr(args, "symbol", None),
            getattr(args, "date", None),
        )
    except Exception as exc:
        print(f"rumor-resolve miss: {exc}")
        return
    rumors = (out or {}).get("rumors", []) or []
    print(f"{out.get('symbol')} @ {out.get('target_date')}: "
          f"{out.get('n_confirmed', 0)} confirmed, {out.get('n_unconfirmed', 0)} unconfirmed")
    for r in rumors:
        print(f"  [{r.get('status')}] n={r.get('n_sources')} :: {(r.get('claim') or '')[:200]}")


def cmd_attention_rank(args):
    """Tier-3 attention ranking for a date (read-only)."""
    try:
        from reality_engine.processing.attention_ranker import rank_attention
    except Exception as exc:
        print(f"attention-rank unavailable: {exc}")
        return
    try:
        rows = rank_attention(
            getattr(args, "date", None),
            top_n=int(getattr(args, "top", 10) or 10),
        )
    except Exception as exc:
        print(f"attention-rank miss: {exc}")
        return
    if not rows:
        print("No attention rows.")
        return
    for r in rows:
        comps = r.get("components", {}) or {}
        comp_str = " ".join(f"{k}={v}" for k, v in comps.items())
        print(f"  {r.get('symbol')}: score={r.get('score')} {comp_str}")


def cmd_morning_digest(args):
    """Tier-3 morning digest text for a date (read-only)."""
    try:
        from reality_engine.processing.attention_ranker import morning_digest
    except Exception as exc:
        print(f"morning-digest unavailable: {exc}")
        return
    try:
        text = morning_digest(getattr(args, "date", None))
    except Exception as exc:
        print(f"morning-digest miss: {exc}")
        return
    print(text or "No digest.")


# ====================================================================
# News-feed ingestion v2: official outlet RSS (Mint, Business Standard,
# BusinessLine, Economic Times, NDTV Profit) + brief + retention.
# Read-only except fetch-news --persist / prune-news --apply; lazy slice
# imports, per-outlet fail-closed, no tracebacks.
# ====================================================================

def cmd_fetch_news(args):
    """Fetch OFFICIAL outlet RSS feeds, normalize to raw_documents records.

    Per feed: items (entries the outlet published), fetched (entries kept by
    --limit), normalized (records built), skipped (undated), dupes (in-feed
    repeats). Persistence only with --persist; one bad feed never aborts the rest.
    --images additionally OCRs each article's infographics through news_vision
    after the persist step; those bitmaps are unlinked once their OCR chunk and
    artifact row are written unless --keep-images is passed.
    """
    try:
        from reality_engine.ingestion import news_feed_client as nfc
    except Exception as exc:
        print(f"fetch-news unavailable: {exc}")
        return
    feeds_raw = getattr(args, "feeds", None) or ",".join(nfc.FEEDS.keys())
    keys = [k.strip() for k in str(feeds_raw).split(",") if k.strip()]
    unknown = [k for k in keys if k not in nfc.FEEDS]
    if unknown:
        print(f"fetch-news: unknown feed(s) {','.join(unknown)}; "
              f"known: {','.join(nfc.FEEDS)}")
        return
    limit = int(getattr(args, "limit", 40) or 40)
    persist = bool(getattr(args, "persist", False))
    all_records: List[Dict[str, Any]] = []
    totals = {"items": 0, "fetched": 0, "normalized": 0, "skipped": 0, "dupes": 0}
    for key in keys:
        try:
            raw = nfc.fetch_feed(nfc.FEEDS[key]) or []
            items = raw[:limit] if limit > 0 else raw
            records, stats = nfc.normalize(items, key)
        except Exception as exc:
            print(f"  {key}: miss ({exc})")
            continue
        stats = stats or {}
        skipped = int(stats.get("skipped_no_date", 0) or 0)
        dupes = int(stats.get("duplicates", 0) or 0)
        print(f"  {key}: items={len(raw)} fetched={len(items)} normalized={len(records)} "
              f"skipped={skipped} dupes={dupes}")
        totals["items"] += len(raw)
        totals["fetched"] += len(items)
        totals["normalized"] += len(records)
        totals["skipped"] += skipped
        totals["dupes"] += dupes
        all_records.extend(records)
    print(f"Totals over {len(keys)} feed(s): items={totals['items']} "
          f"fetched={totals['fetched']} normalized={totals['normalized']} "
          f"skipped={totals['skipped']} dupes={totals['dupes']}")
    if not persist:
        print("Dry run: pass --persist to write to raw_documents.")
        return
    if not all_records:
        print("fetch-news: nothing to persist.")
        return
    try:
        out = nfc.persist(all_records, repo=repo) or {}
    except Exception as exc:
        print(f"fetch-news persist miss: {exc}")
        return
    print(f"Persisted {out.get('raw_written', 0)} new raw_document(s), "
          f"{out.get('raw_updated', 0)} updated, "
          f"{out.get('fts_written', 0)} FTS chunk(s).")
    if bool(getattr(args, "images", False)):
        _capture_news_images(
            all_records,
            limit=int(getattr(args, "image_limit", 20) or 20),
            keep_files=bool(getattr(args, "keep_images", False)),
            label="fetch-news images",
        )


def cmd_news_brief(args):
    """Rank recent official-outlet news rows (raw_documents news_*) into a brief.

    Read-only. Windows by published_date; ranks by extractor importance.
    """
    try:
        from reality_engine.processing.news_extractor import (
            build_brief, extract_item, rank_importance,
        )
    except Exception as exc:
        print(f"news-brief unavailable: {exc}")
        return
    days = int(getattr(args, "days", 3) or 3)
    top = int(getattr(args, "top", 15) or 15)
    as_json = bool(getattr(args, "json", False))
    from datetime import date as _date, timedelta
    cutoff = (_date.today() - timedelta(days=days)).isoformat()
    try:
        tag_by_doc = {}
        with repo.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_documents WHERE source_type LIKE 'news_%' "
                "AND published_date >= ? ORDER BY published_date DESC, doc_id DESC",
                (cutoff,),
            ).fetchall()
            # Symbol tags live on the FTS chunk (raw_documents has no symbols
            # column); attach them so the brief can show which scrips a
            # headline names.
            for r in conn.execute(
                "SELECT chunk_id, symbol FROM intelligence_fts "
                "WHERE source_type LIKE 'news_%' AND symbol != ''"
            ).fetchall():
                cid = str(r[0] or "")
                parts = cid.split(":")
                if len(parts) >= 3 and parts[-2].isdigit():
                    tag_by_doc[int(parts[-2])] = str(r[1])
        rows = [dict(r) for r in rows]
        for r in rows:
            sym = tag_by_doc.get(int(r.get("doc_id") or 0))
            if sym:
                r["symbols"] = [sym]
    except Exception as exc:
        print(f"news-brief miss: {exc}")
        return
    if not rows:
        print(f"No recent news since {cutoff} (days={days}).")
        return
    try:
        items = rank_importance([extract_item(r) for r in rows])[:top]
        brief = build_brief(items, top_n=top)
    except Exception as exc:
        print(f"news-brief miss: {exc}")
        return
    if as_json:
        print(json.dumps({"cutoff": cutoff, "days": days, "top": top,
                          "count": len(items), "items": items, "brief": brief},
                         indent=2, default=str))
        return
    print(f"News brief since {cutoff}: {len(items)} item(s) of {len(rows)} row(s) "
          f"(days={days}, top={top}).")
    print(brief or "No brief.")


def cmd_prune_news(args):
    """Prune aged news raw_documents rows per the retention rule (dry-run default).

    Retention rule: news rows older than --before-days are prunable only once
    extracted; structural (never-extracted) rows are retained. --apply performs
    the delete; --delete-files also removes each pruned row's local file.
    """
    try:
        from reality_engine.pipeline.news_retention import prune_news
    except Exception as exc:
        print(f"prune-news unavailable: {exc}")
        return
    before_days = int(getattr(args, "before_days", 30) or 30)
    apply_change = bool(getattr(args, "apply", False))
    delete_files = bool(getattr(args, "delete_files", False))
    try:
        counts = prune_news(
            before_days=before_days,
            dry_run=not apply_change,
            delete_files=delete_files,
        ) or {}
    except Exception as exc:
        print(f"prune-news miss: {exc}")
        return
    print(f"prune-news [{'APPLIED' if apply_change else 'DRY RUN - pass --apply to delete'}]: "
          f"before_days={before_days} delete_files={delete_files}")
    for key, value in counts.items():
        if key == "errors":
            print(f"  errors: {len(value or [])}")
            for err in value or []:
                print(f"    - {err}")
        else:
            print(f"  {key}: {value}")


# --------------------------------------------------------------------
# News infographics (the INFOGRAPHIC layer of the daily feeds).
#
# An article's chart/table is a bitmap whose numbers never appear in the RSS
# text. news_vision downloads it, OCRs it with FinancialOCREngine and writes
# two dense records: the OCR text as an intelligence_fts chunk
# ('<source_type>:<doc_id>:img') and an artifact row (ocr_text + media_url).
# At ~2 MB per bitmap the file itself is the disposable part, so the CLI
# default is to unlink it right after those writes; --keep-images opts out.
# Note raw_documents does NOT store media_url, so re-capturing an
# already-persisted article requires re-fetching the feed (see news-images).
# --------------------------------------------------------------------

def _print_news_image_counts(title: str, counts: Dict[str, Any]) -> None:
    """Print a news_vision / prune_news_images counts dict (errors expanded)."""
    print(title)
    for key, value in (counts or {}).items():
        if key == "errors":
            errors = value or []
            print(f"  errors: {len(errors)}")
            for err in errors:
                print(f"    - {err}")
        else:
            print(f"  {key}: {value}")


def _capture_news_images(records: List[Dict[str, Any]], limit: int, keep_files: bool,
                         label: str = "news-images") -> None:
    """OCR + persist infographics for ``records`` via news_vision (fail-closed).

    ``keep_files=False`` (the CLI default) unlinks each bitmap right after its
    OCR chunk + artifact row are written; news_vision only deletes after those
    writes succeed and only inside DATA_DIR, so the numbers survive in
    intelligence_fts and the image stays re-fetchable from media_url.
    """
    try:
        from reality_engine.processing import news_vision as nv
    except Exception as exc:
        print(f"{label} unavailable: {exc}")
        return
    try:
        counts = nv.capture_images(
            records, repo=repo, limit=limit, keep_files=keep_files
        ) or {}
    except Exception as exc:
        print(f"{label} miss: {exc}")
        return
    _print_news_image_counts(
        f"{label} [{'bitmaps kept' if keep_files else 'bitmaps deleted after OCR'}]: "
        f"limit={limit} records={len(records)}",
        counts,
    )


def cmd_news_images(args):
    """Re-capture infographics for RECENT news rows by re-fetching the feeds.

    media_url is not stored in raw_documents, so re-fetching the outlet RSS is
    the only source of an image URL for an already-persisted article: recent
    news rows (published_date >= today - --days) are selected first, then only
    re-fetched records matching one of them are handed to news_vision. Per feed
    fail-closed; the counts dict is always printed.
    """
    try:
        from reality_engine.ingestion import news_feed_client as nfc
    except Exception as exc:
        print(f"news-images unavailable: {exc}")
        return
    from datetime import date as _date, timedelta
    days = int(getattr(args, "days", 3) or 3)
    limit = int(getattr(args, "limit", 20) or 20)
    keep_files = bool(getattr(args, "keep_images", False))
    cutoff = (_date.today() - timedelta(days=days)).isoformat()
    try:
        with repo.db.session() as conn:
            rows = conn.execute(
                "SELECT sha256_hash FROM raw_documents "
                "WHERE LOWER(source_type) LIKE 'news_%' AND published_date >= ?",
                (cutoff,),
            ).fetchall()
    except Exception as exc:
        print(f"news-images miss: {exc}")
        return
    recent = {str(r[0]) for r in rows if r[0]}
    print(f"news-images: {len(recent)} recent news row(s) since {cutoff} (days={days}); "
          f"re-fetching {len(nfc.FEEDS)} feed(s) for media_url.")
    records: List[Dict[str, Any]] = []
    for key in nfc.FEEDS:
        try:
            raw = nfc.fetch_feed(nfc.FEEDS[key]) or []
            feed_records, _stats = nfc.normalize(raw, key)
        except Exception as exc:
            print(f"  {key}: miss ({exc})")
            continue
        kept = [r for r in (feed_records or [])
                if str((r or {}).get("sha256_hash") or "") in recent]
        print(f"  {key}: fetched={len(raw)} recent={len(kept)}")
        records.extend(kept)
    if not records:
        print("news-images: no recent news row matched the re-fetched feeds; "
              "nothing captured.")
        return
    _capture_news_images(records, limit=limit, keep_files=keep_files)


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

    # SEBI DRHP / Prospectus offer-document discovery + archive
    p_od = subparsers.add_parser(
        "fetch-offer-docs",
        help="Discover SEBI DRHP/Prospectus filings and archive the offer PDFs with provenance",
    )
    p_od.add_argument("--symbol", type=str, default=None, help="Single symbol e.g. AIRFLOA (company-name search preferred)")
    p_od.add_argument("--company-name", type=str, default=None, help="Full company name for SEBI title search e.g. 'Airfloa Rail Technology Limited'")
    p_od.add_argument("--stage", type=str, default="both", choices=["draft", "final", "both"],
                      help="Offer stage: draft (DRHP) | final (Prospectus/RHP) | both (default)")
    p_od.add_argument("--sample", type=int, default=0, help="Safe smoke-test: process N symbols (outside Nifty200 by default)")
    p_od.add_argument("--max-results", type=int, default=10, help="Max listing hits per stage/query (default: 10)")
    p_od.add_argument("--workers", type=int, default=2, help="Concurrent download threads (default: 2, SEBI WAF is stricter than BSE)")
    p_od.add_argument("--persist", action="store_true", default=False, help="Persist archived offer docs + provenance to corporate_documents")
    p_od.set_defaults(func=cmd_fetch_offer_docs)

    # SEBI DRHP bulk backfill: crawl -> match -> archive -> ingest -> distill
    p_ob = subparsers.add_parser(
        "offer-backfill",
        help="Bulk SEBI DRHP/Prospectus backfill: crawl listings, match universe, archive, ingest, distill",
    )
    p_ob.add_argument("--apply", action="store_true", default=False, help="DELIBERATE: run archive -> ingest -> distill writes (default: dry-run crawl+match)")
    p_ob.add_argument("--stage", type=str, default="both", choices=["draft", "final", "both"])
    p_ob.add_argument("--max-pages", type=int, default=0, help="Cap listing pages per stage (0=all, ~63 final + ~89 draft)")
    p_ob.add_argument("--max-archive", type=int, default=0, help="Cap PDFs archived this run (0=all matched; resume-safe)")
    p_ob.add_argument("--workers", type=int, default=8, help="Concurrent download threads (default: 8; resolve pool = 2x, ingest pool = min(8, 2x))")
    p_ob.add_argument("--loop-dir", type=str, default=None, help="Override backfill state dir")
    p_ob.set_defaults(func=cmd_offer_backfill)

    # local ONNX embeddings (DirectML) + chunk re-embedding
    p_es = subparsers.add_parser(
        "embed-setup",
        help="Download the bge-small-en-v1.5 ONNX model into data/models",
    )
    p_es.set_defaults(func=cmd_embed_setup)
    p_est = subparsers.add_parser(
        "embed-status",
        help="Show ONNX embedding backend status (provider, files, dimension)",
    )
    p_est.set_defaults(func=cmd_embed_status)
    p_re = subparsers.add_parser(
        "reembed-chunks",
        help="Re-embed document_chunks with the ONNX backend (batched, resume-safe)",
    )
    p_re.add_argument("--all", action="store_true", default=False, help="All chunks (default: OFFER_DOCUMENT only)")
    p_re.add_argument("--limit", type=int, default=0, help="Cap rows per run (0=all)")
    p_re.add_argument("--batch", type=int, default=64, help="ONNX batch size (default: 64)")
    p_re.set_defaults(func=cmd_reembed_chunks)

    # local LLM lens backend (llama.cpp Vulkan server + GGUF model)
    p_ls = subparsers.add_parser(
        "llm-setup",
        help="Download the Bonsai PQ2_0 GGUF model (~6.7 GB) into data/models",
    )
    p_ls.set_defaults(func=cmd_llm_setup)
    p_srv = subparsers.add_parser(
        "llm-serve",
        help="Start llama-server (Vulkan, full GPU offload) as a supervised process",
    )
    p_srv.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    p_srv.add_argument("--ctx", type=int, default=32768, help="Context size (floor: 32768)")
    p_srv.set_defaults(func=cmd_llm_serve)
    p_st = subparsers.add_parser(
        "llm-status",
        help="Probe the running llama-server health endpoint",
    )
    p_st.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    p_st.set_defaults(func=cmd_llm_status)
    p_lx = subparsers.add_parser(
        "lens-extract",
        help="Run one macro/moat lens pass over stored chunks via the local LLM (dry-run default)",
    )
    p_lx.add_argument("--kind", type=str, default="moat", choices=["macro", "moat"])
    p_lx.add_argument("--symbol", type=str, default=None, help="Symbol for --kind moat (default: HAL)")
    p_lx.add_argument("--doc-id", type=int, default=None, help="raw_documents id for --kind macro (default: first OFFER_DOCUMENT)")
    p_lx.add_argument("--apply", action="store_true", default=False, help="Write to the dense substrate (default: print only)")
    p_lx.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    p_lx.set_defaults(func=cmd_lens_extract)

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

    # 34. nightly (Wave A: unattended fetch -> predict -> correct chain)
    p_nightly = subparsers.add_parser(
        "nightly",
        help="Run Wave A unattended nightly chain (master sync -> backfill -> fundamentals -> checkpoint gate -> screens -> daily-alpha -> EOD correct)",
    )
    p_nightly.add_argument("--dry-run", action="store_true", default=False, help="Resolve dates, print planned stages, zero DB/network writes")
    p_nightly.add_argument("--part", type=str, default="all", choices=["fetch_predict", "correct_validate", "all"],
                           help="Split work across slots: fetch_predict (19:45) | correct_validate (23:00) | all (default: all)")
    p_nightly.add_argument("--date", type=str, default=None, help="Override IST run date YYYY-MM-DD")
    p_nightly.add_argument("--universe", type=str, default="nifty200", help="EOD correction universe (default: nifty200). Screens always run full-universe.")
    p_nightly.add_argument("--top", type=int, default=20, help="Top N for both screens (default: 20)")
    p_nightly.set_defaults(func=cmd_nightly)

    # 35. fetch-announcements (news-feed v1 Tier-0)
    p_fa = subparsers.add_parser(
        "fetch-announcements",
        help="Fetch NSE corporate announcements for a date window",
    )
    p_fa.add_argument("--from", type=str, required=True, dest="from_date", help="Start date YYYY-MM-DD")
    p_fa.add_argument("--to", type=str, required=True, dest="to_date", help="End date YYYY-MM-DD")
    p_fa.add_argument("--index", type=str, default="equities", help="NSE index filter (default: equities)")
    p_fa.add_argument("--persist", action="store_true", default=False, help="Persist to corporate_documents")
    p_fa.set_defaults(func=cmd_fetch_announcements)

    # 36. fetch-deals (news-feed v1 Tier-0)
    p_fd = subparsers.add_parser(
        "fetch-deals",
        help="Fetch NSE bulk + block deals",
    )
    p_fd.add_argument("--persist", action="store_true", default=False, help="Persist to bulk_block_deals")
    p_fd.set_defaults(func=cmd_fetch_deals)

    # 37. explain-move (news-feed v1 read-only explainer)
    p_em = subparsers.add_parser(
        "explain-move",
        help="Explain a symbol's move on a date from Tier-0 tables",
    )
    p_em.add_argument("--symbol", type=str, required=True, help="Ticker symbol e.g. RELIANCE")
    p_em.add_argument("--date", type=str, required=True, help="Target date YYYY-MM-DD")
    p_em.add_argument("--window", type=int, default=2, help="Lookback window in days (default: 2)")
    p_em.set_defaults(func=cmd_explain_move)

    # 38. search-intel (news-feed v1 FTS)
    p_si = subparsers.add_parser(
        "search-intel",
        help="Tier-filtered search over intelligence FTS",
    )
    p_si.add_argument("--query", type=str, required=True, help="Search query string")
    p_si.add_argument("--symbol", type=str, default=None, help="Symbol filter")
    p_si.add_argument("--since", type=str, default=None, help="Earliest document date YYYY-MM-DD")
    p_si.add_argument("--tiers", type=str, default="0,1", help="Comma-separated tiers (default: 0,1)")
    p_si.add_argument("--top-k", type=int, default=10, dest="top_k", help="Max hits (default: 10)")
    p_si.set_defaults(func=cmd_search_intel)

    # 39. rumor-scan (news-feed Tier-2 rumor corroboration)
    p_rs = subparsers.add_parser(
        "rumor-scan",
        help="Tier-2 rumor scan: corroborate telegram claims for a symbol",
    )
    p_rs.add_argument("--symbol", type=str, required=True, help="Ticker symbol e.g. RELIANCE")
    p_rs.add_argument("--since", type=str, default=None, help="Earliest post date YYYY-MM-DD")
    p_rs.add_argument("--window-hours", type=int, default=72, dest="window_hours",
                      help="Corroboration window in hours (default: 72)")
    p_rs.add_argument("--min-confirm", type=int, default=2, dest="min_confirm",
                      help="Min independent sources to confirm (default: 2)")
    p_rs.set_defaults(func=cmd_rumor_scan)

    # 40. rumor-resolve (news-feed Tier-2 rumor resolution)
    p_rr = subparsers.add_parser(
        "rumor-resolve",
        help="Tier-2 rumor resolve: confirmed/unconfirmed claims for a symbol on a date",
    )
    p_rr.add_argument("--symbol", type=str, required=True, help="Ticker symbol e.g. RELIANCE")
    p_rr.add_argument("--date", type=str, required=True, help="Target date YYYY-MM-DD")
    p_rr.set_defaults(func=cmd_rumor_resolve)

    # 41. attention-rank (news-feed Tier-3 attention digest)
    p_ar = subparsers.add_parser(
        "attention-rank",
        help="Tier-3 attention ranking for a date",
    )
    p_ar.add_argument("--date", type=str, required=True, help="Target date YYYY-MM-DD")
    p_ar.add_argument("--top", type=int, default=10, help="Top N symbols (default: 10)")
    p_ar.set_defaults(func=cmd_attention_rank)

    # 42. morning-digest (news-feed Tier-3 attention digest)
    p_md = subparsers.add_parser(
        "morning-digest",
        help="Tier-3 morning digest text for a date",
    )
    p_md.add_argument("--date", type=str, required=True, help="Target date YYYY-MM-DD")
    p_md.set_defaults(func=cmd_morning_digest)

    # 43. fetch-news (official outlet RSS ingestion -> raw_documents)
    p_fn = subparsers.add_parser(
        "fetch-news",
        help="Fetch OFFICIAL outlet RSS feeds (Mint, Business Standard, BusinessLine, "
             "Economic Times, NDTV Profit)",
    )
    p_fn.add_argument(
        "--feeds", type=str, default=None,
        help="Comma-separated outlet keys, default all official outlets: "
             "livemint,livemint_co,bs,businessline,et,ndtvprofit",
    )
    p_fn.add_argument("--limit", type=int, default=40,
                      help="Max RSS entries kept per outlet (default: 40)")
    p_fn.add_argument("--persist", action="store_true",
                      help="Write normalized records to raw_documents (default: dry run)")
    p_fn.add_argument(
        "--images", action="store_true",
        help="After persisting, OCR each article's infographics via news_vision into "
             "intelligence_fts (chunk_id '<source_type>:<doc_id>:img')",
    )
    p_fn.add_argument("--image-limit", type=int, default=20, dest="image_limit",
                      help="Max infographic images OCR'd per run (default: 20)")
    p_fn.add_argument(
        "--keep-images", action="store_true", dest="keep_images",
        help="Keep the downloaded bitmaps (~2 MB each) under DATA_DIR/news_images. "
             "DEFAULT is to unlink each bitmap right after its OCR chunk + artifact "
             "row are written: the OCR text lives in intelligence_fts and the "
             "artifact row keeps ocr_text + media_url, so the image is re-fetchable "
             "from the publisher CDN at any time",
    )
    p_fn.set_defaults(func=cmd_fetch_news)

    # 44. news-brief (ranked brief over recent official-outlet news)
    p_nb = subparsers.add_parser(
        "news-brief",
        help="Rank recent OFFICIAL outlet RSS news rows (raw_documents news_*) into a brief",
    )
    p_nb.add_argument("--days", type=int, default=3,
                      help="Lookback window in days over published_date (default: 3)")
    p_nb.add_argument("--top", type=int, default=15,
                      help="Top-N ranked items in the brief (default: 15)")
    p_nb.add_argument("--json", action="store_true",
                      help="Emit JSON (items + brief) instead of text")
    p_nb.set_defaults(func=cmd_news_brief)

    # 45. prune-news (news retention: age out extracted news rows)
    p_pn = subparsers.add_parser(
        "prune-news",
        help="Prune news raw_documents by retention rule: older than --before-days "
             "AND already extracted (structural rows retained)",
    )
    p_pn.add_argument("--before-days", type=int, default=30, dest="before_days",
                      help="Retention window: news rows older than N days are prunable (default: 30)")
    p_pn.add_argument("--apply", action="store_true",
                      help="Delete for real (default: dry run, counts only)")
    p_pn.add_argument("--delete-files", action="store_true", dest="delete_files",
                      help="Also delete each pruned row's local_file_path file")
    p_pn.set_defaults(func=cmd_prune_news)

    # 46. news-images (re-capture infographics for recent news rows)
    p_ni = subparsers.add_parser(
        "news-images",
        help="Re-capture infographic images for recent news rows by RE-FETCHING the "
             "outlet RSS feeds: raw_documents stores no media_url, so a re-fetch is "
             "the only source of the image URL for an already-persisted article",
    )
    p_ni.add_argument("--days", type=int, default=3,
                      help="Lookback window in days over published_date; re-fetched "
                           "records are matched against those recent news rows "
                           "(default: 3)")
    p_ni.add_argument("--limit", type=int, default=20,
                      help="Max infographic images OCR'd per run (default: 20)")
    p_ni.add_argument(
        "--keep-images", action="store_true", dest="keep_images",
        help="Keep the downloaded bitmaps (~2 MB each). DEFAULT is to unlink each "
             "bitmap right after its OCR chunk '<source_type>:<doc_id>:img' + "
             "artifact row are written; the artifact row keeps ocr_text + media_url, "
             "so the image is re-fetchable from the publisher CDN at any time",
    )
    p_ni.set_defaults(func=cmd_news_images)

    parsed_args = parser.parse_args()
    if not parsed_args.command:
        parser.print_help()
    else:
        parsed_args.func(parsed_args)


if __name__ == "__main__":
    main()
