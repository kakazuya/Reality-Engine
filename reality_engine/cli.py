"""
Reality Engine CLI Tool
Unified Command-Line Interface for running data ingestion pipelines, quantitative screening,
causal macro graph analysis, agent synthesis, panic monitoring, concall search, and Streamlit dashboard.
"""

from __future__ import annotations

import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

# Add project root to Python path
ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.repository import repo
from reality_engine.ingestion.master_sync import master_sync
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

    print(f"\nRunning Quantitative Multi-Factor Screener for date: {date_str} (Universe: {universe.upper()}, Top {args.top})...\n")
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


def cmd_run_daily_alpha(args):
    """Synthesizes high-conviction daily alpha theses and exports multi-format reports."""
    date_str = args.date or repo.get_latest_price_delivery_date()
    universe = getattr(args, "universe", "nifty200")
    top_n = getattr(args, "top", 20)
    top_theses_count = getattr(args, "top_theses", 5)

    print("\n" + "=" * 75)
    print(f"  SYNTHESIZING DAILY ALPHA REPORT FOR {date_str} ({universe.upper()})")
    print("=" * 75)

    orchestrator = AgentOrchestrator()
    report = orchestrator.synthesize_daily_alpha_report(
        target_date=date_str,
        universe=universe,
        top_n=top_theses_count,
        screener_pool_size=top_n
    )

    writer = ReportWriter()
    exported = writer.export_daily_alpha_report(report)

    mb = report.market_breadth
    print(f"\nMarket Regime       : {mb.market_regime}")
    print(f"Advance/Decline     : {mb.advance_decline_ratio:.2f}")
    print(f"Top Sectors         : {', '.join(mb.top_performing_sectors[:3])}")
    print(f"Solvency Filtered   : {report.disqualified_solvency_count} disqualified")

    print("\n" + "-" * 75)
    print("  HIGH-CONVICTION ALPHA THESES")
    print("-" * 75)
    theses_data = []
    for t in report.high_conviction_theses:
        theses_data.append({
            "Rank": f"#{t.composite_rank}",
            "Symbol": t.symbol,
            "CMP (INR)": f"{t.current_market_price:,.2f}",
            "Entry Range": t.recommended_entry_range,
            "Target (INR)": f"{t.target_price:,.2f}",
            "SL (INR)": f"{t.stop_loss:,.2f}",
            "R:R": f"{t.risk_reward_ratio:.1f}x",
            "Conviction": t.conviction_level,
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

    p_chk = subparsers.add_parser("verify-checkpoint", help="Validate Top 200 reality checkpoint")
    p_chk.set_defaults(func=cmd_verify_checkpoint)

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

    parsed_args = parser.parse_args()
    if not parsed_args.command:
        parser.print_help()
    else:
        parsed_args.func(parsed_args)


if __name__ == "__main__":
    main()
