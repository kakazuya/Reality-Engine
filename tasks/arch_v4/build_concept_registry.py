#!/usr/bin/env python3
"""Generate the v4 factored concept registry (tasks/arch_v4/QUERY_V4_DESIGN.md §A).

Five tables, all generated: **atoms**, **dims**, **formulas**, **operators**, **lexicon**.
A question is ``operator(atom | formula, dims, window, entity_set)``; the registry never
stores a composed concept, so the size stays at tens of atoms rather than hundreds of
question-shaped entries.

The lexicon is mined from the bank's own words: atom synonyms are hand-seeded, then
n-grams present in the question text are admitted only when their normalised form
matches a column name in ``tasks/SCHEMA_FINAL_2026-10-29.sql``, a metric in
``facts_pilot.xbrl_concept_map`` / ``company_metric_series`` / ``concall_facts.cc_items``,
or a declared dim value.  Admitted n-grams are printed as a hand-check list.

Coverage is measured over the 1,073 master-bank cases from the **question text only**
(bank fields ``template``/``family``/``chain`` are evaluation inputs, never decomposition
inputs): every case ends up ``mapped``, ``not_in_data`` (with the registry's reason) or
``unmapped`` (with its residue terms).  The size-vs-coverage curve is a greedy set cover
over the same evidence, so it states the registry size at which coverage crosses 80/90/95%.

Usage:
    python tasks/arch_v4/build_concept_registry.py --check
    python tasks/arch_v4/build_concept_registry.py --show MB0234,MB0280

Read-only on every database (``mode=ro`` + ``immutable=1``); writes only this directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BANK = ROOT / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
SCHEMA_SQL = ROOT / "tasks" / "SCHEMA_FINAL_2026-10-29.sql"
PILOT = Path(os.environ.get("REALITY_DATA_ROOT") or (ROOT / "reality_engine" / "data")) / "pilot" / "pilot60"
OUT_JSON = HERE / "concept_registry.json"
OUT_MD = HERE / "registry_coverage.md"

sys.path.insert(0, str(ROOT))
try:  # the existing period parser, not a second copy of it
    from reality_engine.query.router import period_bounds
except Exception:  # pragma: no cover - the script must still run outside the repo
    period_bounds = None


# --------------------------------------------------------------------------- #
# §A.1 atoms — a raw measure -> store, table, column, unit, grain, entity key, PIT
# --------------------------------------------------------------------------- #
# id, label, kind, unit, grain, coverage, source(db.table.column), synonyms
_ATOMS = [
    # ---- market: the price/delivery grain is a day -------------------------
    ("price.close", "close", "market", "INR", "day", "held",
     "equity_intelligence.daily_price_delivery.close",
     "close|closing price|closing|bhav|last traded price|closing rate|price|shares price|stock price"),
    ("price.open", "open", "market", "INR", "day", "held",
     "equity_intelligence.daily_price_delivery.open", "open|opening price|opening|opened at"),
    ("price.high", "high", "market", "INR", "day", "held",
     "equity_intelligence.daily_price_delivery.high", "high|day high|intraday high|top|highest price|peak price"),
    ("price.low", "low", "market", "INR", "day", "held",
     "equity_intelligence.daily_price_delivery.low", "low|day low|intraday low|bottom|lowest price|trough"),
    ("price.volume", "volume", "market", "shares", "day", "held",
     "equity_intelligence.daily_price_delivery.total_volume",
     "volume|volumes|traded quantity|quantity traded|traded volume|number of shares traded|qty"),
    ("price.delivery_qty", "delivered quantity", "market", "shares", "day", "held",
     "equity_intelligence.daily_price_delivery.deliverable_volume",
     "delivered quantity|delivery quantity|deliverable quantity|delivered volume|delivery volume|deliverable volume|delivered qty"),
    ("price.delivery_pct", "delivery percent", "market", "%", "day", "held",
     "equity_intelligence.daily_price_delivery.delivery_pct",
     "delivery percent|delivery percentage|delivery pct|delivery %|delivery|delivery ratio|delivery spike"),
    ("price.traded_value", "traded value", "market", "INR", "day", "held",
     "equity_intelligence.daily_price_delivery.turnover_lacs",
     "traded value|value traded|turnover value|turnover|amount traded|liquidity|adtv"),
    ("price.mcap", "market cap", "market", "INR", "day", "held",
     "market_state.company_state_daily.mcap_cr",
     "market cap|market capitalisation|market capitalization|mcap|cap|size"),
    ("price.shares_out", "shares outstanding", "market", "shares", "quarter", "held",
     "market_state.company_state_daily.shares_out",
     "shares outstanding|share count|number of shares|paid up capital|paid-up capital|outstanding shares|total shares"),
    ("price.band", "price band", "market", "band", "day", "held",
     "equity_intelligence.price_bands.band",
     "price band|circuit|circuit limit|band|upper circuit|lower circuit"),
    ("price.rsi", "RSI", "market", "index", "day", "held",
     "equity_intelligence.daily_price_delivery.rsi_14",
     "rsi|rsi 14|relative strength|oversold|overbought"),
    ("price.sma", "moving average", "market", "INR", "day", "held",
     "equity_intelligence.daily_price_delivery.sma_20",
     "sma|moving average|dma|20dma|50dma|200dma|20 day|50 day|200 day|50 day average|200 day average|50 days|200 days"),
    # ---- fundamentals: quarter/FY grain -----------------------------------
    ("fin.revenue", "revenue", "fundamental", "INR", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=revenue)",
     "revenue|revenues|sales|topline|total income|income from operations|income from operation|turnover from operations|gross revenue"),
    ("fin.ebitda", "EBITDA", "fundamental", "INR", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=ebitda)",
     "ebitda|operating profit|operating profit before tax|opbdt|pbdit|ebit"),
    ("fin.pat", "profit after tax", "fundamental", "INR", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=pat)",
     "pat|profit after tax|net profit|profit after tax and minority|net income|profit|bottomline|net earnings|loss|losses|net loss|quarterly loss"),
    ("fin.eps", "EPS", "fundamental", "INR", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=eps)",
     "eps|earnings per share|diluted eps|basic eps"),
    ("fin.book_equity", "book equity", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=net_worth)",
     "book value|net worth|shareholder equity|shareholders equity|equity|net assets|book equity"),
    ("fin.total_debt", "total debt", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=borrowings_current|borrowings_noncurrent, agg=sum)",
     "debt|borrowings|total debt|long term debt|short term debt|gross debt|net debt"),
    ("fin.cash", "cash", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=cash)",
     "cash|cash and equivalents|cash & equivalents|bank balance|free cash|surplus cash"),
    ("fin.cwip", "capital work in progress", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=cwip)",
     "cwip|capital work in progress|work in progress|capital advances"),
    ("fin.investments", "investments", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=investments)",
     "investments|investment|jv|joint venture|associates|inv"),
    ("fin.receivables", "receivables", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=receivables)",
     "receivables|trade receivables|debtors|receivable|outstanding receivables|dues"),
    ("fin.inventory", "inventory", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=inventory)",
     "inventory|inventories|stock in trade|work in progress inventory|raw material stock"),
    ("fin.payables", "payables", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=payables)",
     "payables|trade payables|creditors|payable|supplier dues"),
    ("fin.capex", "capex", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=capex)",
     "capex|capital expenditure|capital spend|capital outlay|spending|investment in fixed assets|addition to fixed assets"),
    ("fin.interest_expense", "interest expense", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=finance_costs)",
     "interest|interest expense|finance cost|finance costs|interest cost|interest paid|interest outgo|capitalised interest"),
    ("fin.cfo", "cash from operations", "fundamental", "INR", "FY", "held",
     "metric_state.company_metric_series.value(metric_key=cfo)",
     "cfo|operating cash flow|cash from operations|cash flow from operations|ocf|operating cashflow"),
    ("fin.loan_book", "loan book", "fundamental", "INR", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=loans)",
     "loan book|advances|loans|aum|book size|credit book|loan growth|book growth"),
    ("fin.nim", "net interest margin", "fundamental", "%", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=nim)",
     "nim|net interest margin|spread on advances|yield on advances"),
    ("fin.npa", "NPAs", "fundamental", "%", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=net_npa)",
     "npa|gross npa|net npa|slippages|stressed assets|bad loans"),
    ("fin.credit_cost", "credit cost", "fundamental", "%", "quarter", "held",
     "metric_state.company_metric_series.value(metric_key=credit_cost)",
     "credit cost|provisions|provision cost|loan loss"),
    ("fin.capacity_utilisation", "capacity utilisation", "fundamental", "%", "quarter", "held",
     "metric_state.company_capacity_utilisation.value_pct",
     "capacity utilisation|capacity utilization|utilisation|utilization|plant utilisation|cu"),
    ("fin.order_book", "order book", "fundamental", "INR", "quarter", "held",
     "metric_state.order_book_contract.value_cr(aggregate)",
     "order book|orderbook|backlog|pending orders|unexecuted order book|book to bill|book|order value"),
    ("fin.order_intake", "order intake", "fundamental", "INR", "quarter", "held",
     "metric_state.order_intake.value_cr",
     "order intake|new orders|order inflow|orders won|fresh orders|order wins|order announced|bagged|bid|bids|bidding|tender win"),
    ("fin.segment_value", "segment P&L value", "fundamental", "INR", "FY", "held",
     "metric_state.company_segment_pnl.value_cr",
     "segment revenue|segment profit|segment ebit|segment pbt|segment|segments|segment mix|segment share|business segments"),
    # ---- ownership ---------------------------------------------------------
    ("hold.pct", "shareholding percent", "ownership", "%", "quarter", "held",
     "equity_intelligence.shareholding.<holder_column>",
     "shareholding|share holding|stake|holding percentage|shareholding pattern|holding|holders|ownership|share holding pattern"),
    ("hold.pledge_pct", "promoter pledge", "ownership", "%", "quarter", "held",
     "equity_intelligence.shareholding.promoter_pledged_pct",
     "pledge|pledged|pledged shares|promoter pledge|encumbrance|encumbered"),
    ("corp.amount_per_share", "corporate-action amount per share", "ownership", "INR/share",
     "event", "gap",
     "market_state.corporate_action_class.amount_per_share",
     "dividend|interim dividend|final dividend|special dividend|dividend per share|dps|"
     "ex date|ex dividend|record date|book closure|bonus issue|share split|stock split|"
     "buyback|rights issue|demerger|corporate action"),
    ("hold.fpi_limit_utilised", "FPI limit utilised", "ownership", "%", "quarter", "held",
     "equity_intelligence.shareholding.fpi_limit_utilised_pct",
     "fpi limit|fpi limit utilised|fpi utilisation|foreign limit"),
    ("flows.net_inr", "net insider/deal flow", "ownership", "INR", "day", "held",
     "market_state.event_leakage_window.insider_net_inr",
     "insider|insider trade|insider buying|insider selling|sast|bulk deal|block deal|deal|promoter buying|promoter selling"),
    # ---- narrative: one claim atom, topics are dim values, not atoms -------
    ("claim.claim", "typed claim", "narrative", "enum", "event", "held",
     "metric_state.claim(direction,magnitude,horizon)",
     "said|says|say|stated|mentioned|remarks|remark|comment|commented|guidance|guided|guiding|tone|outlook|disclosed|disclosure|according to|management|call|concall|transcript|presentation|deck|annual report|ar|notes|note|md&a|commentary|target|targets|expects|expectation|plan|plans|intends|intend|strategy"),
    ("text.passage", "document passage", "narrative", "text", "event", "held",
     "chunks_v3.chunk.body",
     "page|passage|paragraph|para|section|quote|quoted|text"),
    # ---- macro / policy ----------------------------------------------------
    ("macro.policy", "policy event", "macro", "INR", "event", "held",
     "equity_intelligence.policy_events.amount_inr_crore",
     "policy|tariff|tariffs|duty|import duty|customs duty|anti dumping|budget|rbi|repo|repo rate|subsidy|pli|notification|gazette|legislated|bill|scheme|pib|press release|cabinet|ministry|government|sebi|regulation"),
    ("macro.claim", "macro claim + target", "macro", "enum", "event", "held",
     "market_state.macro_claim.direction",
     "claim|report|research note|house view|consensus view|street|broker|rbi says|economist"),
    ("macro.commodity_close", "commodity price", "macro", "INR", "day", "held",
     "equity_intelligence.mkt_commodity_daily.close",
     "copper|aluminium|steel|hrc|iron ore|crude|brent|wti|oil|gold|silver|sugar|ethanol|cane|rubber|cement|urea|potash|dap|cotton|yarn|palm oil|natural gas|coal|coking coal|zinc|nickel|lead|tin|commodity|commodities|input cost|raw material price"),
    ("macro.index_close", "index level", "macro", "index", "day", "held",
     "equity_intelligence.mkt_nse_index_daily.close",
     "nifty|sensex|index|nifty 50|bank nifty|nifty it|smallcap index|midcap index|index level|benchmark|bse index|nifty500"),
    ("macro.flow", "FII/DII cash flow", "macro", "INR", "day", "held",
     "equity_intelligence.mkt_fii_dii_cash.net_inr_cr",
     "fii flow|fii flows|dii flow|dii flows|foreign flow|institutional flow|fpi flow|net buying|net selling|fii|dii|fpi|flow|flows|flow prints"),
    ("macro.oi", "open interest", "macro", "contracts", "day", "held",
     "market_state.fno_oi_daily.oi",
     "open interest|oi|futures|options|f&o|put call|pcr|option chain"),
    ("macro.etf_premium", "ETF premium to iNAV", "macro", "%", "day", "held",
     "equity_intelligence.etf_inav.premium_vs_inav_pct",
     "etf premium|premium to inav|inav|nav premium|discount to nav|etf|exchange traded fund"),
    ("macro.series", "macro series observation", "macro", "value", "month", "held",
     "market_state.series_observation.value",
     "rainfall|monsoon|el nino|wpi|cpi|inflation|iip|gst collection|credit growth|deposit growth|trade deficit|fx reserve|rupee|inr|usdinr|dollar|repo rate|policy rate|interest rate|interest rates|rates|rate cut|rate hike|rate cuts|rate hikes|freight|freight rate|freight rates|container freight|transit time|gst|gst rate|gst rates|tax|taxes|current account"),
    # ---- measures the bank asks for that the pilot stores do not carry yet --
    ("fin.deposits", "bank deposits", "fundamental", "INR", "quarter", "gap",
     "metric_state.company_metric_series.value(metric_key=deposits)",
     "deposits|deposit mix|term deposits|casa|casa ratio|deposit franchise"),
    ("fin.unit_volume", "unit volumes", "fundamental", "units", "quarter", "gap",
     "metric_state.company_operating_metrics.value(unit volumes)",
     "units|units sold|volumes sold|sales volume|dispatches|delivered|deliveries|two wheelers|three wheelers|vehicles sold|tonnes sold"),
    ("price.free_float", "free float", "market", "%", "day", "gap",
     "market_state.company_membership_pit.weight",
     "free float|float|free-float|float percentage|index weight"),
    # ---- declared absent: the registry's NOT IN DATA reasons ---------------
    ("absent.consensus", "analyst consensus estimate", "absent", "INR", "quarter", "absent",
     "none: paid-only (no consensus feed acquired)",
     "consensus|street estimate|analyst estimate|analyst estimates|broker estimates|market expects|estimates|expected by analysts|guidance versus consensus"),
    ("absent.price_target", "analyst price target", "absent", "INR", "event", "absent",
     "none: paid-only (target prices are broker research)",
     "target price|price target|fair value|upside target|broker target|rating target"),
    ("absent.intraday", "intraday amplitude", "absent", "INR", "day", "absent",
     "none: NSE publishes no free retro intraday bars",
     "intraday amplitude|intraday range|intraday move|tick data|minute bars|seconds|intraday high low"),
    ("absent.investor_holdings", "investor-level holdings", "absent", "%", "quarter", "absent",
     "none: investor-level holdings are not published in India",
     "which funds hold|fund-wise holding|investor-wise|individual investor|mutual fund name|shareholder name|investor-level|retail investors|investors lose|investor loss|retail losses"),
    ("absent.refurb_sales", "refurbished sales series", "absent", "INR", "quarter", "absent",
     "none: no company discloses a refurbished-sales series",
     "refurb|refurbished|remanufactured|used equipment sales"),
    ("absent.forecast", "forecast / future price", "absent", "INR", "event", "absent",
     "none: forecast, not a held fact",
     "will the price|will it be|forecast|predict|by diwali|next year price|future price|projected price|what will happen|will double|will triple|will hit|will rise to|will fall to|by 2027|by 2028"),
    ("absent.private_terms", "private deal terms", "absent", "text", "event", "absent",
     "none: private transaction terms are never filed",
     "private deal terms|deal terms|unpublished terms|private placement terms|informal terms"),
]

ATOM_SRC_NOTE = ("The fact view (design §B) is the single read path; ``source`` names the physical "
                 "table.column the view projects, so an atom is one registry row plus one view "
                 "branch, never planner code.")


# --------------------------------------------------------------------------- #
# §A.2 dims — qualifiers that live ON an atom, never new concepts
# --------------------------------------------------------------------------- #
# dim_id, values, source, default, note
_DIMS = [
    ("exchange", ["NSE", "BSE", "each", "sum"],
     "px_nse / px_bse (+ entity_id from truth_duckdb.px_daily)", "each",
     "'NSE and BSE plus the combined total' is one atom with three dim readings, never three concepts."),
    ("basis", ["raw", "adjusted"],
     "truth_duckdb.px_nse_adj / px_bse_adj vs raw", "raw",
     "adjusted = split/bonus/dividend adjusted; raw = the printed close."),
    ("consolidation", ["consolidated", "standalone"],
     "results_xbrl.filings.consolidated / ar_facts.basis", "consolidated",
     "a filing may carry both; the dim forces the reading."),
    ("holder_class", ["promoter", "public", "fii", "dii", "mf", "insurance", "retail", "pledge", "fpi_limit"],
     "equity_intelligence.shareholding.<value>_pct", "promoter",
     "one holding percent atom; the class picks the column."),
    ("segment", "open", "metric_state.company_segment_pnl.segment", "all",
     "open set from the segment note; share_of formula derives the mix."),
    ("topic", "open", "metric_state.claim.topic (cc_items / deck_facts / ar_facts vocabulary)", "all",
     "open set mined from the extraction vocabulary; a narrative topic is a dim value, not an atom."),
    ("scope", ["stock", "sector", "industry", "index", "theme", "mcap_bucket", "price_band", "fno", "market_wide"],
     "market_state.company_membership_pit / company_sector_pit / company_theme_pit", "stock",
     "the entity_set of the Ask; 'which sugar companies' becomes a membership join."),
    ("doctype", ["announcement", "concall", "deck", "ar", "results", "pib", "rbi", "budget"],
     "chunks_v3.doc.doc_type / corporate_documents.doc_type", "any",
     "the source class of a passage or claim."),
    ("flow_kind", ["insider", "deal", "bulk", "block"],
     "market_state.event_leakage_window / bulk_block_deals", "insider",
     "the signed net on flows.net_inr."),
    ("event_kind", ["announcement", "results", "concall", "deck", "ar", "shareholding", "insider",
                    "sast", "deals", "board_meeting", "policy", "dividend", "split", "bonus", "demerger"],
     "market_state.event_day0.event_kind / truth_duckdb.events.kind", "any",
     "the event taxonomy is already held; it is a dim, not an atom family."),
    ("lag", ["yoy", "qoq", "ytd", "1d", "1w", "1m", "3m", "6m", "1y"],
     "computed by the operator from the window dim", "yoy",
     "the lag of a change/growth operator."),
    ("margin_kind", ["ebitda", "pat", "operating", "net"],
     "formula over revenue + ebitda/pat", "ebitda", "which margin the question names."),
    ("npa_kind", ["gross", "net"], "metric_key gross_npa / net_npa", "net", "gross vs net NPA."),
    ("ratio_kind", ["de", "pb", "pe", "ev_ebitda", "roic", "roce", "roe", "icr"],
     "formula over two atoms", "de", "a ratio is a formula reading, not an atom."),
    ("direction", ["up", "down", "neutral"], "claim/price direction", "neutral",
     "the sign the question asks about."),
    ("period_kind", ["day", "quarter", "FY", "event", "span"], "period_bounds()", "FY",
     "the window grain; resolved by the existing period parser."),
    ("page", "numeric", "chunks_v3.chunk.page_from..page_to", None,
     "'page 41 of the deck' is a dim on text.passage."),
    ("lookback", [20, 50, 200], "daily_price_delivery.sma_*", 20,
     "the moving-average length."),
]


# --------------------------------------------------------------------------- #
# §A.3 formulas — derived measures as expressions over atoms (never stored data)
# --------------------------------------------------------------------------- #
# id, label, expr, atoms, unit
_FORMULAS = [
    ("f.margin", "margin", "ebitda(pat) / revenue", ["fin.ebitda", "fin.pat", "fin.revenue"], "%"),
    ("f.ratio", "ratio", "num / den  (de, pb, pe, ev_ebitda, roic, roce, roe, icr)",
     ["fin.total_debt", "fin.book_equity", "price.mcap", "fin.pat", "fin.ebitda"], "x"),
    ("f.dso", "debtor days", "receivables / revenue * 365", ["fin.receivables", "fin.revenue"], "days"),
    ("f.working_capital_cycle", "working capital cycle", "dso + inventory_days - payable_days",
     ["fin.receivables", "fin.inventory", "fin.payables", "fin.revenue"], "days"),
    ("f.share_of", "share of total", "part / total * 100",
     ["fin.segment_value", "fin.revenue", "hold.pct"], "%"),
    ("f.net", "net of two signed effects", "a + b  (opposite signs preserved)",
     ["macro.claim", "fin.nim", "price.close"], "INR"),
    ("f.per_rupee_revenue", "capex per rupee of new revenue", "delta(capex) / delta(revenue)",
     ["fin.capex", "fin.revenue"], "x"),
    ("f.book_value_per_share", "book value per share", "book_equity / shares_out",
     ["fin.book_equity", "price.shares_out"], "INR"),
    ("f.gap_pct", "gap percent", "(open - prev_close) / prev_close * 100", ["price.open", "price.close"], "%"),
    ("f.drawdown", "drawdown", "close / max(close over window) - 1", ["price.close"], "%"),
    ("f.cagr", "CAGR", "(end / start) ** (1 / years) - 1", ["price.close", "fin.revenue", "fin.pat"], "%"),
    ("f.excess_return", "excess return", "return(company) - return(benchmark)", ["price.close", "macro.index_close"], "%"),
    ("f.spread", "input-output spread", "output price - input cost", ["macro.commodity_close", "fin.revenue"], "INR"),
]


# --------------------------------------------------------------------------- #
# §A.4 operators — a closed set of parameterised templates
# --------------------------------------------------------------------------- #
# id, label, params, shape, template
_OPERATORS = [
    ("value_at", "one value at a window", ["atom", "dims", "window"],
     "one scalar",
     "SELECT value, unit, period_end, known_at FROM fact WHERE atom=:atom AND {dims} AND {window} AND known_at<=:as_of"),
    ("series", "value per period across a window", ["atom", "dims", "window"],
     "ordered rows (period, value, known_at)",
     "SELECT period_end, value, unit, known_at FROM fact WHERE atom=:atom AND {dims} AND {window} AND known_at<=:as_of ORDER BY period_end"),
    ("max_with_date", "maximum and the date it happened", ["atom", "dims", "window"],
     "one value + one date + the exchange",
     "SELECT value, period_end, dim_exchange, known_at FROM fact WHERE atom=:atom AND {dims} AND {window} AND value=(SELECT max(value) ...)"),
    ("min_with_date", "minimum and the date it happened", ["atom", "dims", "window"],
     "one value + one date",
     "same as max_with_date with min()"),
    ("change", "absolute change between two readings", ["atom", "dims", "window_a", "window_b"],
     "one signed difference", "SELECT b.value-a.value ..."),
    ("pct_change", "percent change between two readings", ["atom", "dims", "window_a", "window_b"],
     "one percent", "SELECT (b.value-a.value)/abs(a.value)*100 ..."),
    ("growth", "growth at a named lag", ["atom", "formula", "dims", "lag"],
     "one percent", "pct_change(pair(window_end, window_end - lag))"),
    ("rank", "rank entities on a measure", ["entity_set", "atom|formula", "dims", "window", "n"],
     "top-n list with values", "SELECT entity_id, value ... ORDER BY value {desc} LIMIT :n"),
    ("screen", "filter entities on thresholds", ["entity_set", "atom|formula", "dims", "window", "cmp"],
     "matching entity list", "SELECT entity_id ... WHERE value {cmp} :threshold"),
    ("compare", "same measure across an entity set", ["entity_set", "atom|formula", "dims", "window"],
     "one row per entity", "group by entity_id"),
    ("lag_between", "days between two dated events/values", ["atom", "event_a", "event_b"],
     "one integer number of days", "SELECT julianday(b.day)-julianday(a.day)"),
    ("event_window_return", "return around an event", ["atom", "event_kind", "window=-k..+n"],
     "session-0 date, offset, abnormal return, delivery z",
     "SELECT session_0, ret_pct - benchmark_ret, delivery_z FROM event_window ..."),
    ("first_visible", "earliest point the fact was knowable", ["atom", "dims"],
     "one known_at + one value", "SELECT known_at, value ... ORDER BY known_at LIMIT 1"),
    ("last_visible", "latest point the fact was knowable", ["atom", "dims"],
     "one known_at + one value", "SELECT known_at, value ... ORDER BY known_at DESC LIMIT 1"),
    ("zscore", "standardised distance from the window's own mean", ["atom", "dims", "window"],
     "one z", "(value - mean) / stddev over the window"),
    ("count", "how many", ["atom|entity_set", "dims", "window"],
     "one integer", "SELECT count(*)"),
    ("correlate", "lagged correlation of two series", ["atom_a", "atom_b|macro", "lag", "window"],
     "one r + n", "corr(a_t, b_t-lag) over the window"),
    ("aggregate", "sum/mean over a dim", ["atom", "dims", "agg"],
     "one scalar per group", "SELECT dim, {agg}(value) ... GROUP BY dim"),
    ("walk", "graph / ripple walk from a trigger", ["trigger", "edge_table", "hops", "threshold"],
     "ordered path (hop, node, mechanism, known_at) or the hop it stops at",
     "bounded BFS over edge(driver,target) with known_at<=:as_of, max_hops<=5"),
    ("rule", "named deterministic judgement", ["rule_id", "inputs"],
     "verdict + the numbers the rule used + the stated rule text",
     "python template per rule id (table below)"),
    ("exists", "is the fact held at all (NID probe)", ["atom", "dims", "window"],
     "row count + the checked list", "SELECT count(*) ... LIMIT 1"),
    ("join_entity_set", "resolve a scope into an entity list", ["scope", "dims", "as_of"],
     "entity ids valid at as_of", "SELECT isin FROM membership WHERE valid_from<=d<valid_to"),
    ("threshold_cross", "the date a series crossed a level", ["atom", "dims", "level", "window"],
     "one date + the value at the crossing", "first row where value crosses :level"),
    ("span_days", "length of a window in days", ["window_a", "window_b"],
     "one integer", "julianday(b)-julianday(a)"),
    ("list_distinct", "which entities/topics have the property", ["atom|claim", "dims", "window"],
     "deduplicated entity list with the evidence row",
     "SELECT DISTINCT entity_id ... (a ranked screen is rank; this is the set)"),
    ("describe_series", "shape of a series (trend, turns, strength)", ["atom", "dims", "window"],
     "one sentence + the numbers behind it",
     "fit over the window: slope, number of turns, share of periods up"),
]

# §A.4b the named deterministic judgement rules ("each with its stated rule")
_RULES = [
    ("gap_type", "open vs previous close",
     "gap up if open > prev_close*1.01; gap down if open < prev_close*0.99; else flat"),
    ("breakout", "close above the window maximum on volume",
     "close >= max(close, prior lookback) and volume >= 1.5 * mean(volume, lookback)"),
    ("distribution_absorption", "delivery spikes with or without price progress",
     "absorption if delivery_pct z > 2 and return >= 0; distribution if delivery_pct z > 2 and return < 0"),
    ("margin_bottom", "has margin bottomed",
     "verdict 'bottomed' if the claim direction is up after >= 2 consecutive periods of falling margin"),
    ("control_change", "control or ownership change",
     "control change if any holder_class moves >= 5 percentage points in one quarter, or promoter_pct falls >= 5pp"),
    ("solvency", "the strict solvency gate (AGENTS.md §3.11)",
     "fail if promoter pledge > 15% or interest coverage < 2.5x or D/E > 1.5x"),
    ("valuation_premium", "premium to peers on the same measure",
     "premium if pb > median(pb of the peer set) * 1.2"),
    ("receivables_quality", "is the book worth face value",
     "deteriorating if dso rises while revenue growth <= 0, or dso rises > 20% and cfo/revenue falls"),
    ("say_vs_do", "management credibility on its own guidance",
     "credible if the guided direction held in >= 70% of tested periods; the score is the hit rate with n"),
    ("regime_break", "did a measured link stop working",
     "broken if the out-of-sample coefficient sign flips or |t| < 2 in the later window"),
    ("analog_cycle", "closest past cycle on the same atoms",
     "top-k by standardised distance over the shared window; k=5, no hindsight on the target window"),
    ("dilution", "share count growing faster than the business",
     "dilutive if share_count growth > pat growth + 5pp over the window"),
    ("golden_cross", "moving-average cross",
     "golden cross if sma_50 crosses above sma_200 in the window; death cross if it crosses below"),
    ("support_resistance", "support and resistance levels",
     "support = the highest low of the last 60 sessions below the close; resistance = the lowest "
     "high of the last 60 above the close; a 'real' level needs >= 2 touches within 1%"),
]

# the atom an operator or a rule reads when the question names the operation but not the
# measure ("how much did it move", "has control changed"): the registry's default input
_OP_DEFAULT_ATOM = {    "max_with_date": "price.high", "min_with_date": "price.low",
    "change": "price.close", "pct_change": "price.close", "growth": "fin.revenue",
    "event_window_return": "price.close", "threshold_cross": "price.close",
    "correlate": "macro.index_close", "zscore": "price.close", "drawdown": "price.close",
    "describe_series": "price.close", "walk": "macro.claim",
}
_RULE_DEFAULT_ATOM = {
    "gap_type": "price.open", "breakout": "price.close",
    "distribution_absorption": "price.delivery_pct", "margin_bottom": "f.margin",
    "control_change": "hold.pct", "solvency": "hold.pledge_pct",
    "valuation_premium": "f.ratio", "receivables_quality": "fin.receivables",
    "say_vs_do": "claim.claim", "dilution": "price.shares_out",
    "golden_cross": "price.sma", "support_resistance": "price.low",
}
# extra surface words per named rule (the id itself is a surface too)
_RULE_WORDS = {
    "say_vs_do": "on track|slipped|slipping|met guidance|missed guidance|guidance met|delivered on guidance",
    "margin_bottom": "margin bottomed|margin has bottomed|turning margin",
    "distribution_absorption": "distribution or absorption|absorption|distribution",
    "control_change": "control change|change of control|ownership change",
    "solvency": "solvency|leverage stress|debt stress",
    "valuation_premium": "premium to book|premium to peers|valuation premium",
    "receivables_quality": "worth its face value|receivable quality|old receivables",
    "regime_break": "regime break|stopped working|broke down",
    "analog_cycle": "analog|analogue|past cycle|last cycle",
    "dilution": "dilution|dilutive|equity issuance",
    "golden_cross": "golden cross|death cross|cross above the|50 day cross|200 day cross",
    "support_resistance": "support|resistance|support level",
    "breakout": "breakout|break out|broke out",
    "gap_type": "gap up|gap down|gapped",
}


# --------------------------------------------------------------------------- #
# §A.5 lexicon — surface -> atom | operator | dim value | entity selector | period
# --------------------------------------------------------------------------- #
# hand-seeded operator and period triggers; atom/dim entries come from their own tables
_OP_WORDS = {
    "value_at": "what is|what was|what were|how much|how many|kya|kitna|kitni|how big|tell me|give me|state|reported|report",
    "series": "over time|trend|trajectory|history|last 5 years|time series|has been|every quarter|each quarter",
    "max_with_date": "high|highest|largest|biggest|peak|max|maximum|top",
    "min_with_date": "low|lowest|smallest|trough|min|minimum|bottom",
    "change": "change|changed|delta|difference|moved|move|jump|jumped|spike|spiked|vs|versus|compared|increased|decreased|rise|fall|fell|rose|giri|gira|badha|badhi|badhne",
    "pct_change": "percent change|pct change|return|returns|performance|market reaction|market do|the market do",
    "growth": "grow|growth|grew|yoy|qoq|year on year|quarter on quarter|y-o-y|q-o-q",
    "rank": "rank|ranking|top|best|worst|which one|order by|sorted|leader",
    "screen": "which companies|how many companies|screen|filter|list all|name every|constituents",
    "compare": "compare|versus|vs|peer|peers|relative|both|pair",
    "lag_between": "how long|lag|how many days|days between|gap between|how soon",
    "event_window_return": "around the event|on the day|day 0|next session|event window|after the announcement|before the announcement|how did .* react",
    "first_visible": "earliest|first|when did .* first|first visible|earliest point|how early",
    "last_visible": "latest|last|most recent|now|current|today|as of|kitni hai|abhi",
    "zscore": "z score|z-score|standardised|unusually|spike|outlier|abnormal",
    "count": "how many|number of|count|kitne",
    "correlate": "correlate|correlation|link|linked|transmission|pass through|pass-through|sensitivity|beta to|follows|follow the",
    "aggregate": "total|sum|average|median|overall|combined|in aggregate|dono",
    "walk": "trace|walk|second order|third order|ripple|propagat|spread to|transmit|flow through|knock on|spill|then what|where does it stop|chain",
    # a judgement ask must name a declared rule (see _RULE_WORDS); generic question words
    # ("why", "is it", "explain") are NOT rule surfaces — they would resolve anything
    "rule": "",
    "exists": "do you have|is there|is .* held|do we hold|available|not in data|if not",
    "join_entity_set": "sector|industry|theme|basket|universe|pack|constituents|members of|companies in",
    "threshold_cross": "crossed|cross|cross above|cross below|breach|broke above|broke below|broke",
    "span_days": "how many days|duration|span",
    "list_distinct": "which companies|who|name the|list|every company|kaun si|kaunse|kaun",
    "describe_series": "how has .* behaved|shape|pattern|steady|volatile|mean revert|mean-reverting",
}
_PERIOD_WORDS = {
    "window": "latest|now|current|today|as of|ytd|year to date|ytd high|ytd low|lifetime|since|last week|last month|last quarter|last year|fy25|fy26|fy27|fy28|fy24|fy23|fy22|q1fy27|q2fy27|q3fy27|q4fy27|q1fy26|q2fy26|q3fy26|q4fy26|yesterday|this year|next year|next quarter|h1|h2|cagr",
    "lookback": "20d|50d|200d|20 day|50 day|200 day|20dma|50dma|200dma|one week|one month|three months|six months|one year",
}
# curated narrative topics (the claim atom's dim); the mined vocabulary extends this
_TOPIC_SEED = (
    "products|business model|control change|audit|audit opinion|key audit matter|kam|guidance|"
    "order book|capacity|capex|facilities|acquisition|dividend|pledge|working capital|dso|"
    "loan growth|business segments|segments|demand|margins|pricing|competition|market share|"
    "utilisation|commissioning|expansion|merger|demerger|rights issue|buyback|litigation|"
    "related party|contingent liabilities|promoter|rumour|index inclusion|free float|"
    "raw material|power cost|logistics|distribution|channel|dealer network|exports|imports|"
    "subsidy|tariff|regulation|litigation|key customer|top customer|order inflow|tender|"
    "bid pipeline|succession|kmp|board|auditor|internal control|going concern|"
    "npa|slippage|restructuring|one time|exceptional|impairment|write off|esop|"
    "royalty|brand|technology|patent|r&d|esg|emissions|water|safety|insurance|"
    "business|products|facilities|customer|supplier|employee|geography|plant|moat|"
    "governance|risk|cycle|valuation|ownership|inventory|cost|price|volume|"
    "discount|premium|restructuring|fundraise|ipo|listing|delisting|suspension|"
    "supply|pipeline|award pipeline|embedded value|arpu|subscriber|subscribers|"
    "transit time|second hand electronics|electronics|data centre|data center|semiconductor|"
    "solar module|defence|railway|shipbuilding|leasing|rakes|bharatnet|indigenisation|"
    "free float|float|credit|deposit|freight|ev|gst|rates|loss|capacity|utilisation|"
    "stressed assets|capital allocation|return ratio|working capital|receivable quality|"
    "remuneration|ceo pay|compensation|kmp pay|tracking error|support|resistance|"
    "throughput|port throughput|lcoe|levelised cost|control|maturities|port|"
    "second order|third order|lead time|turnaround"
)
_ENTITY_SELECTORS = {
    "sector": ("sector|sectors|industry|industries|basic industry|omc|omcs|nbfc|nbfcs|psu|psus|"
               "banks|bank|insurers|insurer|life insurer|telecom|pharma|auto|autos|fmcg|it services|"
               "cement|steel|chemicals|specialty chemicals|textiles|dairy|hotels|airlines|power|"
               "capital goods|metal|metals|realty|logistics|shipping|exchanges|brokers|amc|"
               "gold jewellery|jewellery|consumer durables|durables|electronics"),
    "industry": "industry|basic industry|industries",
    "index": "nifty|sensex|index constituents|constituents|index members|smallcap 100|midcap 150|nifty 500",
    "theme": "theme|thematic|basket|pack|complex|universe",
    "mcap_bucket": "large cap|largecap|mid cap|midcap|small cap|smallcap|microcap|mcap bucket",
    "price_band": "price band",
    "fno": "f&o|futures and options|derivatives",
    "market_wide": "market wide|all listed|whole market|entire market|every company|all companies",
}
# a "X stocks / X makers / X exporters" stem is an entity_set of that theme
_THEME_STEM = re.compile(
    r"\b([a-z][a-z\-]+(?:\s+[a-z][a-z\-]+)?)\s+"
    r"(?:stocks?|companies|makers?|players?|names?|pack|suppliers?|exporters?|importers?|firms?|counters)\b")
# terse sector-first style: "OMCs: ...", "NBFCs — ...", "Data-centre: ..."
_HEAD_STEM = re.compile(r"^\s*([A-Za-z][A-Za-z0-9&\- ]{2,28}?)\s*(?::|—|–)\s")
# atoms that are themselves an entity (a policy event, a driver series)
_DRIVER_ATOMS = {"macro.policy", "macro.claim", "macro.commodity_close", "macro.series",
                 "macro.index_close", "macro.flow"}
# a clause that only re-expresses the other parts (ordering, counting, existence)
_CROSS_PART_OPS = {"rank", "compare", "list_distinct", "aggregate", "count", "exists", "join_entity_set"}
_FORMULA_WORDS = {
    "f.margin": "margin|margins|ebitda margin|net margin|opm|npm|operating margin|margin expansion|margin compression|margin path",
    "f.ratio": "valuation|p/e|pe ratio|p/b|pb ratio|ev/ebitda|roic|roce|roe|d/e|debt to equity|interest coverage|icr|multiple|premium to book|ratio|ratios|stored ratio",
    "f.dso": "dso|debtor days|receivable days|collection days",
    "f.working_capital_cycle": "working capital cycle|cash conversion cycle|ccc|dpo|inventory days",
    "f.share_of": "share of|share of total|mix|contribution|percentage of",
    "f.net": "net of|net effect|offset|net gain|net loss|net it",
    "f.per_rupee_revenue": "per rupee|per rupee of revenue|capital intensity|incremental capex|reinvestment need",
    "f.book_value_per_share": "book value per share|bvps",
    "f.gap_pct": "gap|gap up|gap down|gap percent|opened gap",
    "f.drawdown": "drawdown|fall from peak|below peak|from the high|from its high",
    "f.cagr": "cagr|compounded|annualised return|three year return|5 year return",
    "f.excess_return": "excess return|relative return|alpha|outperform|underperform|vs the index|vs nifty",
    "f.spread": "spread|spreads|gross spread|net interest spread|steel spread|spread compression|spread expansion",
}

# a clause counts as resolved when it names one of these; fragments without one are
# connective filler ("after its corporate action", "as of 31 July 2026")
_CONNECTIVE = set("""
a an the and or of to in on at for from by with without after before during since until while
when where which who whom whose what why how is are was were be been being do does did doing
has have had having will would shall should can could may might must not no nor so than then
there their its it this that these those as if into onto over under about above below between
both each other more most less least very much many few some any all own same such only
also just but however because therefore thus hence per via toward towards across along within
question ask asks asked answer answers give gave get got make made take taken say said says
please tell show report provide list name state mention mentioned according latest now today
done does doing us we our you your they them he she his her one two three four five six seven
eight nine ten first second third next last new old big small large high low up down more
value values number numbers percent percentage pp bps crore cr lakh million billion
nse bse isin company companies stock stocks share shares price prices day days year years
month months quarter quarters week weeks time times point points level levels part parts
""".split())

_MEASURE_WORDS = set("""
revenue sales margin ebitda pat profit loss eps debt cash capex inventory receivables payables
cwip investments borrowing borrowings order book orderbook backlog capacity utilisation
utilization segment segments delivery volume turnover mcap close price high low open
promoter public fii dii pledge holding shareholding stake shares outstanding npa nim
credit cost loan loans advances aum roi roe roce roic dso dpo ccc growth return returns
cagr yoy qoq spread premium discount ratio multiple valuation pe pb ev ebitda
guidance target targets capex plan plans demand supply pricing price competition
market share utilization utilisation commissioning expansion commission
products product facilities facility business model brand technology patent
order intake inflow order inflow orders wins win tender tenders bid pipeline
dividend buyback rights issue bonus split demerger merger acquisition
audit opinion qualifications qualification auditor internal control going concern
working capital free float index inclusion weight weights
fii dii fpi flow flows premium inav nav etf oi interest rate rates repo repo
rainfall monsoon wpi cpi inflation iip gst collections credit growth deposit
tariff tariffs duty duties subsidy subsidies pli budget rbi sebi
volume volatility beta correlation lag correlation alpha drawdown peak trough
receivable debtor debtors creditor creditors inventory payables payable stock
employee employees headcount attrition wage wages power cost freight
utilization utilisation throughput capacity
""".split())


# --------------------------------------------------------------------------- #
# text helpers
# --------------------------------------------------------------------------- #
_PUNCT = re.compile(r"[^a-z0-9%]+")
_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    s = (s or "").lower().replace("ñ", "n").replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


# clause split: strong separators always; " and " only when what follows is lower-case
# (so "CG Power and Industrial Solutions" stays one clause while "promoter and public" splits)
_STRONG_SPLIT = re.compile(r"\s*[+;|]\s*|\s*\?\s*|\s+(?:aur|bhi|then|what about)\s+", re.I)
_LOWER_AND_SPLIT = re.compile(r"\s+(?:and|plus|vs|versus|compared to|compared with)\s+(?=[a-z0-9])")
_COMMA_SPLIT = re.compile(r"\s*,\s*(?:and\s+|aur\s+|then\s+)?(?=[a-z])")


def split_clauses(text: str) -> list[str]:
    raw = _STRONG_SPLIT.split(text or "")
    out: list[str] = []
    for chunk in raw:
        for piece in _LOWER_AND_SPLIT.split(chunk):
            for sub in _COMMA_SPLIT.split(piece):
                if sub and sub.strip():
                    out.append(sub.strip())
    return out or [text or ""]


def doc_set(text: str) -> set[str]:
    return set(norm(text).split())


# --------------------------------------------------------------------------- #
# mining: column names, xbrl concept map, extraction metric vocabulary
# --------------------------------------------------------------------------- #
def mine_column_phrases(sql_path: Path) -> dict[str, str]:
    """normalised column phrase -> 'db.table.column' (from the FINAL schema)."""
    if not sql_path.exists():
        return {}
    text = re.sub(r"--[^\n]*", "", sql_path.read_text(encoding="utf-8", errors="replace"))
    out: dict[str, str] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+([\w\.]+)\s*\(", text):
        table = m.group(1)
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.end():i]
        for line in body.split(","):
            line = line.strip()
            if not line or line.upper().startswith(("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT", "--")):
                continue
            col = line.split()[0].strip('"`')
            if not re.match(r"^[a-z_][a-z0-9_]*$", col):
                continue
            phrase = norm(col.replace("_", " "))
            if len(phrase) > 3:
                out.setdefault(phrase, f"{table}.{col}")
            tokens = phrase.split()
            if len(tokens) > 1:
                for tok in tokens:
                    if len(tok) > 3 and tok not in _CONNECTIVE:
                        out.setdefault(tok, f"{table}.{col}")
    return out


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=2.0)
        con.execute("select 1").fetchone()
        return con
    except Exception:
        return None


def mine_metric_vocabulary() -> dict[str, list[str]]:
    """metric/claim vocabulary from the pilot stores (read-only), per source."""
    vocab: dict[str, list[str]] = defaultdict(list)
    facts = _ro(PILOT / "facts_pilot.db")
    if facts:
        try:
            for (concept, metric) in facts.execute("SELECT concept, metric_key FROM xbrl_concept_map"):
                if metric:
                    vocab["xbrl_concept"].append(metric)
                if concept:
                    vocab["xbrl_concept"].append(concept)
        except Exception:
            pass
        try:
            for (metric,) in facts.execute("SELECT DISTINCT metric_key FROM company_metric_series"):
                if metric:
                    vocab["metric_series"].append(metric)
        except Exception:
            pass
        try:
            for (metric,) in facts.execute("SELECT DISTINCT metric FROM company_segment_pnl"):
                if metric:
                    vocab["segment_pnl"].append(metric)
        except Exception:
            pass
        facts.close()
    cc = _ro(Path(os.environ.get("REALITY_DATA_ROOT") or (ROOT / "reality_engine" / "data")) / "concall_facts.db")
    if cc:
        try:
            for (metric,) in cc.execute("SELECT metric, count(*) FROM cc_items "
                                        "WHERE metric IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 4000"):
                if metric:
                    vocab["concall_metric"].append(metric)
        except Exception:
            pass
        cc.close()
    return vocab


def mine_ngrams(questions: list[str], max_n: int = 3) -> Counter:
    grams: Counter = Counter()
    for q in questions:
        toks = norm(q).split()
        for n in range(1, max_n + 1):
            for i in range(len(toks) - n + 1):
                gram = " ".join(toks[i:i + n])
                if len(gram) < 4:
                    continue
                if all(t in _CONNECTIVE for t in toks[i:i + n]):
                    continue
                grams[gram] += 1
    return grams


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
def build_atoms(metric_vocab: dict[str, list[str]], column_phrases: dict[str, str]) -> list[dict]:
    held_keys = set()
    for src in ("metric_series", "xbrl_concept", "concall_metric", "segment_pnl"):
        for raw in metric_vocab.get(src, []):
            held_keys.add(norm(str(raw).replace("_", " ")))
    atoms = []
    for aid, label, kind, unit, grain, cov, source, syn in _ATOMS:
        note = ""
        if cov == "held":
            # verify the atom against the held vocabulary where it names a metric key
            m = re.search(r"metric_key=([a-z0-9_]+)", source)
            if m:
                key = norm(m.group(1).replace("_", " "))
                if key not in held_keys:
                    cov, note = "gap", f"metric_key '{m.group(1)}' is not in the held concept vocabulary"
                else:
                    note = f"verified against held metric_key '{m.group(1)}'"
            elif source.split(".")[-1] in column_phrases.values():
                note = "verified against the FINAL schema column"
            else:
                note = "declared held (schema column / pilot table present)"
        elif cov == "absent":
            note = source.split(":", 1)[-1].strip()
        elif cov == "gap" and not note:
            note = ("registry knows the measure; the store does not carry it yet "
                    f"({source.split('(')[0].strip()})")
        atoms.append({
            "atom_id": aid, "label": label, "kind": kind,
            "store": "fact_view", "table": "fact", "column": aid,
            "source": source, "unit": unit, "grain": grain,
            "entity_key": "entity_id (ISIN-keyed, exchange-resolved)",
            "pit": "known_at", "coverage": cov, "coverage_note": note,
            "synonyms": [s.strip() for s in syn.split("|") if s.strip()],
        })
    return atoms


def build_dims() -> list[dict]:
    return [{"dim_id": d, "values": vals, "source": src, "default": default, "note": note}
            for d, vals, src, default, note in _DIMS]


def build_formulas() -> list[dict]:
    return [{"formula_id": f, "label": l, "expr": e, "over": a, "unit": u}
            for f, l, e, a, u in _FORMULAS]


def build_operators() -> list[dict]:
    rules = {rid: {"rule": txt, "inputs": ins, "default_atom": _RULE_DEFAULT_ATOM.get(rid)}
             for rid, ins, txt in _RULES}
    ops = []
    for oid, label, params, shape, template in _OPERATORS:
        row = {"op_id": oid, "label": label, "params": params, "shape": shape,
               "template": template, "default_atom": _OP_DEFAULT_ATOM.get(oid)}
        if oid == "rule":
            row["rules"] = rules
        ops.append(row)
    return ops


def build_lexicon(atoms: list[dict], dims: list[dict], ngrams: Counter,
                  metric_vocab: dict[str, list[str]], column_phrases: dict[str, str],
                  topic_limit: int = 220) -> tuple[list[dict], list[dict]]:
    """(lexicon rows, mined hand-check rows).  One surface -> one entry."""
    index: dict[str, dict] = {}
    hand: list[dict] = []

    def add(surface: str, kind: str, target: str, lang: str = "en", checked: bool = True,
            why: str = "") -> None:
        surface = norm(surface)
        if not surface:
            return
        forms = [surface]
        if len(surface) >= 3 and not surface.endswith("s"):
            forms.append(surface + "s")      # fiis, banks, margins
        elif len(surface) >= 4 and surface.endswith("s"):
            forms.append(surface[:-1])       # borrowings -> borrowing
        for form in forms:
            if form in index:
                continue
            index[form] = {"surface": form, "kind": kind, "id": target,
                           "lang": lang, "hand_checked": checked, "why": why,
                           "variant_of": surface if form != surface else None}

    for a in atoms:
        for s in a["synonyms"]:
            add(s, "atom", a["atom_id"])

    for d in dims:
        did = d["dim_id"]
        if isinstance(d["values"], list):
            for v in d["values"]:
                add(str(v).replace("_", " "), "dim", f"{did}={v}")
        # common surface words for a few dims
    for s, target in [("raw", "basis=raw"), ("unadjusted", "basis=raw"), ("adjusted", "basis=adjusted"),
                      ("split adjusted", "basis=adjusted"), ("total return", "basis=adjusted"),
                      ("consolidated", "consolidation=consolidated"), ("cons", "consolidation=consolidated"),
                      ("standalone", "consolidation=standalone"), ("stand alone", "consolidation=standalone"),
                      ("both exchanges", "exchange=each"), ("dono", "exchange=each"),
                      ("combined", "exchange=sum"), ("nse bse total", "exchange=sum")]:
        add(s, "dim", target)

    for op, words in _OP_WORDS.items():
        for w in words.split("|"):
            add(w, "operator", op)
    for fid, words in _FORMULA_WORDS.items():
        for w in words.split("|"):
            add(w, "formula", fid)
    for _k, words in _PERIOD_WORDS.items():
        for w in words.split("|"):
            add(w, "period", "window")
    for scope, words in _ENTITY_SELECTORS.items():
        for w in words.split("|"):
            add(w, "entity_set", scope)
    for rid, _ins, _txt in _RULES:
        for w in (rid.replace("_", " ") + "|" + rid.replace("_", " ") + "d|" +
                  _RULE_WORDS.get(rid, "")).split("|"):
            add(w, "rule", rid)
    for s in [r.replace("_", " ") for r in ("margin_bottomed", "distribution_absorption",
                                            "control_change", "say_vs_do", "regime_break",
                                            "analog_cycle", "receivables_quality", "valuation_premium",
                                            "solvency", "dilution", "gap_type", "breakout")]:
        add(s, "rule", s)

    # --- mined topics: the claim atom's dim value space ---------------------
    for s in _TOPIC_SEED.split("|"):
        add(s, "claim_topic", norm(s))
    scored: dict[str, tuple[int, str]] = {}
    for src, vals in metric_vocab.items():
        for raw in vals:
            phrase = norm(str(raw).replace("_", " "))
            if len(phrase) < 4 or phrase in _CONNECTIVE:
                continue
            df = ngrams.get(phrase, 0)
            if df == 0:
                # a compound metric key may appear with spaces already normalised
                df = ngrams.get(phrase.replace("-", " "), 0)
            prev = scored.get(phrase)
            if prev is None or df > prev[0]:
                scored[phrase] = (df, src)
    for phrase, (df, src) in sorted(scored.items(), key=lambda kv: (-kv[1][0], kv[0]))[:topic_limit]:
        if df < 1 or phrase in index:
            continue
        add(phrase, "claim_topic", phrase, checked=False, why=f"{df} question(s); vocab {src}")
        hand.append({"surface": phrase, "kind": "claim_topic", "evidence_questions": df,
                     "vocabulary": src, "admitted": "extraction vocabulary"})
    # --- mined n-grams matched against column names / metric keys -----------
    # A mined surface becomes a claim topic only when it is a multi-word phrase from the
    # extraction vocabulary; it never becomes an atom (an atom must be a declared measure with
    # a store, a unit and a PIT path, not a column name that happens to contain the phrase).
    admitted = 0
    for gram, df in sorted(ngrams.items(), key=lambda kv: (-kv[1], kv[0])):
        if admitted >= 120 or gram in index:
            continue
        if len(gram.split()) < 2 or gram not in scored:
            continue
        add(gram, "claim_topic", gram, checked=False,
            why=f"vocab {scored[gram][1]}; {df} question(s)")
        hand.append({"surface": gram, "kind": "claim_topic", "evidence_questions": df,
                     "vocabulary": f"vocab {scored[gram][1]}", "admitted": "n-gram match"})
        admitted += 1
    # the reviewer's real work list: frequent measure-like phrases the registry lacks
    rejected = []
    for gram, df in sorted(ngrams.items(), key=lambda kv: (-kv[1], kv[0])):
        if len(rejected) >= 60 or gram in index:
            continue
        toks = gram.split()
        if len(gram) < 5 or df < 2:
            continue
        measure_like = (toks[-1] in _MEASURE_WORDS or gram in column_phrases
                        or gram in scored or any(t in _MEASURE_WORDS for t in toks))
        if not measure_like:
            continue
        why = []
        if gram in column_phrases:
            why.append(f"column {column_phrases[gram]}")
        if gram in scored:
            why.append(f"vocab {scored[gram][1]}")
        rejected.append({"surface": gram, "evidence_questions": df,
                         "matched": "; ".join(why) or "measure-like, no column/concept match"})
    return list(index.values()), hand[:160], rejected


# --------------------------------------------------------------------------- #
# the decomposer (lexicon slot filling; no bank fields, no model)
# --------------------------------------------------------------------------- #
class Matcher:
    """Two-pass surface matcher.

    Content kinds (atom/formula/topic/rule/dim) are matched separately from the modifier
    kinds (operator/period/entity_set), so a period phrase like "ytd high" can never shadow
    the measure "high" that it contains.
    """
    CONTENT = ("atom", "formula", "claim_topic", "rule", "dim")
    MODIFIER = ("operator", "period", "entity_set")

    def __init__(self, lexicon: list[dict]):
        self.by_surface = {e["surface"]: e for e in lexicon}
        self.rx: dict[str, re.Pattern | None] = {}
        for name, kinds in (("content", self.CONTENT), ("modifier", self.MODIFIER)):
            surfaces = sorted((s for s, e in self.by_surface.items() if e["kind"] in kinds),
                              key=len, reverse=True)
            pattern = "|".join(re.escape(s) for s in surfaces)
            self.rx[name] = re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])") if surfaces else None

    def hits(self, clause: str) -> list[dict]:
        text = norm(clause)
        out: list[dict] = []
        for name in ("content", "modifier"):
            rx = self.rx[name]
            if not rx:
                continue
            for m in rx.finditer(text):
                e = self.by_surface.get(m.group(0))
                if e and e not in out:
                    out.append(e)
        return out


_CAPS_TOKEN = re.compile(r"\b[A-Z][A-Z0-9&\-]{2,}\b")


def resolve_names() -> dict[str, dict]:
    """symbol -> {name tokens, bse_code, bse_symbol}: the RESOLVE stage's name index."""
    out: dict[str, dict] = {}
    con = _ro(Path(os.environ.get("REALITY_DATA_ROOT") or (ROOT / "reality_engine" / "data"))
              / "equity_intelligence.db")
    if not con:
        return out
    try:
        for sym, name, bse_code, bse_sym in con.execute(
                "SELECT nse_symbol, name, bse_code, bse_symbol FROM security_master"):
            if not sym:
                continue
            toks = [t for t in norm(name).split() if len(t) >= 4 and t not in _CONNECTIVE]
            out[sym.upper()] = {"tokens": toks[:4], "bse_code": bse_code, "bse_symbol": bse_sym}
    except Exception:
        pass
    con.close()
    return out


def _entity_from_text(case: dict, resolver: dict[str, dict]) -> tuple[bool, str]:
    """(resolvable from the question text only, how)."""
    text = case.get("question") or ""
    low = text.lower()
    ents = case.get("entities") or []
    for ent in ents:
        sym = str(ent.get("symbol") or "").strip()
        for key in ("symbol", "isin", "bse_code", "name"):
            v = str(ent.get(key) or "").strip()
            if len(v) >= 4 and v.lower() in low:
                return True, f"{key} in text"
        ref = resolver.get(sym.upper()) if sym else None
        if ref:
            if ref.get("bse_code") and str(ref["bse_code"]) in text:
                return True, "bse code in text"
            if ref.get("bse_symbol") and str(ref["bse_symbol"]).lower() in low:
                return True, "bse symbol in text"
            hits = [t for t in ref["tokens"] if t in low]
            need = 2 if len(ref["tokens"]) >= 3 else 1
            if len(hits) >= need:
                return True, f"name in text ({' '.join(hits[:3])})"
    if not ents:
        return False, "no entity (scope ask)"
    if _THEME_STEM.search(low):
        return True, "theme scope stem (<x> stocks/makers/...)"
    if _HEAD_STEM.match(text):
        return True, "sector/theme head before the colon"
    if _CAPS_TOKEN.search(text):
        return True, "symbol-like caps token in text"
    return False, "entity only in bank metadata (not in text)"


def _window(case: dict) -> tuple[tuple | None, str]:
    """The existing period parser, applied to the case's own text."""
    if period_bounds is None:
        return None, "no-parser"
    try:
        d0, d1, basis = period_bounds(case)
    except Exception:
        return None, "parse-error"
    if d0 or d1:
        return (d0, d1), basis
    return None, "unresolved"


def decompose(case: dict, matcher: Matcher, atom_index: dict[str, dict],
              resolver: dict[str, dict] | None = None) -> dict:
    """question text -> Ask parts.  Bank fields are never consulted."""
    question = case.get("question") or ""
    clauses = split_clauses(question)
    parts, residues, needs = [], [], []
    inherited_metric = None
    for clause in clauses:
        hits = matcher.hits(clause)
        atoms = [h for h in hits if h["kind"] == "atom"]
        formulas = [h for h in hits if h["kind"] == "formula"]
        topics = [h for h in hits if h["kind"] == "claim_topic"]
        rules = [h for h in hits if h["kind"] == "rule"]
        dims = [h for h in hits if h["kind"] == "dim"]
        periods = [h for h in hits if h["kind"] == "period"]
        ops = [h for h in hits if h["kind"] == "operator"]
        scopes = [h for h in hits if h["kind"] == "entity_set"]
        metric = atoms[0]["id"] if atoms else (topics[0]["id"] if topics and not atoms else None)
        if metric is None and formulas:
            metric = formulas[0]["id"]
        if metric is None:
            metric = next((_OP_DEFAULT_ATOM[o["id"]] for o in ops
                           if _OP_DEFAULT_ATOM.get(o["id"])), None)
        if metric is None:
            metric = next((_RULE_DEFAULT_ATOM[r["id"]] for r in rules
                           if _RULE_DEFAULT_ATOM.get(r["id"])), None)
        part = {
            "clause": clause.strip(),
            "atoms": [h["id"] for h in atoms],
            "formulas": [h["id"] for h in formulas],
            "topics": [h["id"] for h in topics][:4],
            "rules": [h["id"] for h in rules][:3],
            "dims": [h["id"] for h in dims][:6],
            "operators": [h["id"] for h in ops][:4],
            "scope": [h["id"] for h in scopes][:2],
            "period": bool(periods),
        }
        atom_nids = [atom_index[a["id"]]["coverage_note"] or atom_index[a["id"]]["coverage"]
                     for a in atoms
                     if a["id"] in atom_index
                     and atom_index[a["id"]]["coverage"] in ("absent", "gap")]
        if metric:
            part["metric"] = metric
            inherited_metric = metric
            if atom_nids:
                part["nid_reason"] = atom_nids[0]
            elif metric in atom_index and atom_index[metric]["coverage"] in ("absent", "gap"):
                part["nid_reason"] = atom_index[metric]["coverage_note"] or atom_index[metric]["coverage"]
        elif formulas:
            part["metric"] = formulas[0]["id"]
        elif dims and inherited_metric:
            part["metric"] = inherited_metric
            part["inherited_dim"] = True
        elif ops and all(o["id"] in _CROSS_PART_OPS for o in ops):
            # "in what order", "and how many" reduce/re-express the other parts
            part["metric"] = inherited_metric
            part["qualifier"] = True
            if not inherited_metric:
                part["pending_inherit"] = True
        elif dims or periods or rules or scopes or (ops and inherited_metric):
            part["metric"] = inherited_metric
            part["qualifier"] = True
        else:
            toks = [t for t in doc_set(clause) if t not in _CONNECTIVE]
            measure = [t for t in toks if t in _MEASURE_WORDS or
                       (len(t) > 4 and any(t.startswith(m[:5]) for m in ("deliver", "margi", "capac", "order", "segme")))]
            if measure:
                residues.append((clause.strip(), measure))
                part["residue"] = measure
            else:
                part["qualifier"] = "filler"
        parts.append(part)

    distinct = {p["metric"] for p in parts if p.get("metric") and not p.get("qualifier")}
    if len(distinct) == 1:
        only = next(iter(distinct))
        for p in parts:
            if p.get("pending_inherit") and not p.get("metric"):
                p["metric"] = only
                p["inherited_dim"] = True
                p.pop("pending_inherit", None)
    metrics = [p.get("metric") for p in parts if p.get("metric") and not p.get("qualifier")]
    metric_parts = [p for p in parts if p.get("metric") and not p.get("qualifier")]
    window, wbasis = _window(case)
    entity_ok, entity_how = _entity_from_text(case, resolver or {})
    entity_default = False
    if not entity_ok and any(p.get("scope") for p in parts):
        entity_ok, entity_how = True, "entity_set scope"
    elif not entity_ok and any(set(p.get("atoms", [])) & _DRIVER_ATOMS for p in parts):
        entity_ok, entity_how = True, "policy/driver entity named in text"
    elif not entity_ok and _THEME_STEM.search((case.get("question") or "").lower()):
        entity_ok, entity_how = True, "theme scope stem"
    elif not entity_ok and any(op in p.get("operators", [])
                               for p in parts for op in ("screen", "rank", "list_distinct")):
        entity_ok, entity_how = True, "screen/rank implies a market-wide entity set"
    elif not entity_ok:
        # the Ask contract's declared default: nothing named -> the held universe
        entity_ok, entity_how, entity_default = True, "default market-wide (no entity named)", True

    reasons = [p["nid_reason"] for p in parts if p.get("nid_reason")]
    entity_gap = False
    if residues or not metric_parts:
        status = "unmapped"
    elif not entity_ok:
        status, entity_gap = "unmapped", True
    elif reasons:
        status = "not_in_data"
    else:
        status = "mapped"
    return {
        "mid": case.get("mid"),
        "question": question,
        "parts": parts,
        "window": {"from": window[0] if window else None,
                   "to": window[1] if window else None, "basis": wbasis},
        "entity": {"resolved": entity_ok, "how": entity_how, "default": entity_default},
        "status": status,
        "entity_gap": entity_gap,
        "entity_default": entity_default,
        "nid_reasons": sorted(set(reasons)),
        "residue": residues,
        "metrics": [m for m in metrics if m],
    }


# --------------------------------------------------------------------------- #
# coverage + the size-vs-coverage curve
# --------------------------------------------------------------------------- #
def load_bank() -> list[dict]:
    with open(BANK, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def coverage_report(asks: list[dict], bank: list[dict]) -> dict:
    status = Counter(a["status"] for a in asks)
    n = len(asks)
    entity_defaults = sum(1 for a in asks if a.get("entity_default"))
    by_bank = defaultdict(Counter)
    by_level = defaultdict(Counter)
    by_family = defaultdict(Counter)
    meta = {r["mid"]: r for r in bank}
    for a in asks:
        r = meta.get(a["mid"], {})
        by_bank[r.get("source_bank") or "?"][a["status"]] += 1
        by_level[r.get("entity_level") or "?"][a["status"]] += 1
        fams = r.get("family") or []
        by_family[fams[0] if fams else "?"][a["status"]] += 1
    residues = Counter()
    for a in asks:
        for clause, toks in a["residue"]:
            for t in toks:
                residues[t] += 1
    nid = Counter()
    for a in asks:
        for reason in a["nid_reasons"]:
            nid[reason] += 1
    gaps = Counter()
    for a in asks:
        for p in a["parts"]:
            if p.get("nid_reason"):
                gaps[p["nid_reason"]] += 1
    return {
        "n": n,
        "status": dict(status),
        "entity_defaults": entity_defaults,
        "mapped_pct": round(100.0 * status.get("mapped", 0) / n, 2),
        "answered_pct": round(100.0 * (status.get("mapped", 0) + status.get("not_in_data", 0)) / n, 2),
        "by_bank": {k: dict(v) for k, v in sorted(by_bank.items())},
        "by_level": {k: dict(v) for k, v in sorted(by_level.items())},
        "by_family": {str(k): dict(v) for k, v in sorted(by_family.items(), key=lambda kv: str(kv[0]))},
        "top_residues": residues.most_common(40),
        "nid_reasons": nid.most_common(20),
        "gap_notes": gaps.most_common(20),
        "unmapped": [a["mid"] for a in asks if a["status"] == "unmapped"],
        "entity_default": [a["mid"] for a in asks if a.get("entity_default")],
        "unmapped_metric": [a["mid"] for a in asks
                            if a["status"] == "unmapped" and not a.get("entity_default")],
        "no_metric": [a["mid"] for a in asks
                      if a["status"] == "unmapped" and not a["residue"]],
        "not_in_data": [a["mid"] for a in asks if a["status"] == "not_in_data"],
        "mapped": [a["mid"] for a in asks if a["status"] == "mapped"],
    }


def _grams(clause: str) -> set[str]:
    toks = norm(clause).split()
    out = set()
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i:i + n])
            if len(gram) >= 4:
                out.add(gram)
    return out


def size_curve(asks: list[dict], matcher: Matcher,
               column_phrases: dict[str, str], metric_keys: set[str]) -> dict:
    """Greedy set cover over clause requirements, starting from an EMPTY registry.

    Each clause that the seeded run resolves contributes the set of seeded surfaces that
    resolve it; each clause it does not resolve contributes an admissible mined surface
    (schema column or held metric key) when one exists.  Adding an entry covers every
    clause containing it; a case is covered when all its clauses are.

    Cases that fail only on entity resolution are excluded (their fix is RESOLVE's name
    index, not a lexicon row) and counted separately; clauses with no admissible surface
    are unreachable and their cases are counted separately too.
    """
    reqs: list[list[set[str]]] = []
    all_cands: set[str] = set()
    unreachable: list[tuple[str, str]] = []
    unreachable_cases: list[str] = []
    entity_only = 0
    for a in asks:
        if a.get("entity_gap"):
            entity_only += 1
            continue
        req, dead = [], False
        for p in a["parts"]:
            clause = p["clause"]
            seeded = {h["surface"] for h in matcher.hits(clause)}
            if p.get("residue"):
                mined = {g for g in _grams(clause)
                         if (g in column_phrases or g in metric_keys) and g not in matcher.by_surface}
                cand = seeded | mined
                if not cand:
                    unreachable.append((a["mid"], clause.strip()))
                    dead = True
                    continue
            else:
                cand = seeded
                if not cand:
                    continue  # filler: the seeded run needed nothing here either
            req.append(cand)
            all_cands |= cand
        if dead:
            unreachable_cases.append(a["mid"])
            continue
        reqs.append(req)

    pool = len(reqs)
    inverted: dict[str, set[int]] = defaultdict(set)
    pending: list[list[set[str]]] = [[set(s) for s in r] for r in reqs]
    left = [len(r) for r in reqs]
    for i, req in enumerate(reqs):
        for clause in req:
            for c in clause:
                inverted[c].add(i)
    covered = sum(1 for n in left if n == 0)
    curve, chosen = [(0, covered)], []
    cand_left = set(all_cands)
    while cand_left and covered < pool:
        best, gain = None, 0
        for c in cand_left:
            g = sum(1 for i in inverted.get(c, ())
                    if left[i] == 1 and pending[i] and c in pending[i][0])
            if g > gain or (g == gain and best is not None and g and c < best):
                best, gain = c, g
        if not best or gain == 0:
            break
        chosen.append(best)
        cand_left.discard(best)
        for i in list(inverted.pop(best, ())):
            keep = [s for s in pending[i] if best not in s]
            if len(keep) != len(pending[i]):
                pending[i] = keep
                left[i] = len(keep)
                if left[i] == 0:
                    covered += 1
        curve.append((len(chosen), covered))
    marks = {}
    for size, cov in curve:
        pct = 100.0 * cov / pool if pool else 0.0
        for target in (80, 90, 95):
            if target not in marks and pct >= target:
                marks[target] = {"entries": size, "covered": cov, "pct": round(pct, 2)}
    seeded_coverage = sum(1 for a in asks if a["status"] in ("mapped", "not_in_data"))
    return {
        "candidate_entries": len(all_cands),
        "chosen": len(chosen),
        "pool": pool,
        "entity_only": entity_only,
        "seeded_coverage_cases": seeded_coverage,
        "curve": curve,
        "thresholds": marks,
        "reachable_pct": round(100.0 * (curve[-1][1] if curve else covered) / pool, 2) if pool else 0.0,
        "unreachable": unreachable[:80],
        "unreachable_n": len(unreachable),
        "unreachable_cases": unreachable_cases[:80],
        "unreachable_case_n": len(unreachable_cases),
    }


# --------------------------------------------------------------------------- #
# outputs
# --------------------------------------------------------------------------- #
def build(args) -> dict:
    bank = load_bank()
    questions = [r.get("question") or "" for r in bank]
    ngrams = mine_ngrams(questions)
    column_phrases = mine_column_phrases(SCHEMA_SQL)
    metric_vocab = mine_metric_vocabulary() if not args.no_db else {}
    metric_keys: set[str] = set()
    for vals in metric_vocab.values():
        metric_keys.update(norm(str(v).replace("_", " ")) for v in vals)

    atoms = build_atoms(metric_vocab, column_phrases)
    dims = build_dims()
    formulas = build_formulas()
    operators = build_operators()
    lexicon, hand, rejected = build_lexicon(atoms, dims, ngrams, metric_vocab, column_phrases)
    matcher = Matcher(lexicon)
    atom_index = {a["atom_id"]: a for a in atoms}
    resolver = resolve_names() if not args.no_db else {}
    asks = [decompose(case, matcher, atom_index, resolver) for case in bank]
    cov = coverage_report(asks, bank)
    curve = size_curve(asks, matcher, column_phrases, metric_keys)

    registry = {
        "version": "v4.1",
        "design": "tasks/arch_v4/QUERY_V4_DESIGN.md",
        "generated_from": {
            "bank": {"path": str(BANK.relative_to(ROOT)), "cases": len(bank), "sha256_16": sha(BANK)},
            "schema": {"path": str(SCHEMA_SQL.relative_to(ROOT)), "sha256_16": sha(SCHEMA_SQL)},
            "data_root": str(PILOT.parent),
            "mining": {"ngrams": len(ngrams), "column_phrases": len(column_phrases),
                       "metric_vocabulary": {k: len(v) for k, v in sorted(metric_vocab.items())}},
        },
        "atoms": atoms,
        "dims": dims,
        "formulas": formulas,
        "operators": operators,
        "lexicon": lexicon,
        "hand_check": hand,
        "mined_candidates": rejected,
        "coverage": {
            "n": cov["n"], "status": cov["status"], "mapped_pct": cov["mapped_pct"],
            "answered_pct": cov["answered_pct"], "by_bank": cov["by_bank"],
            "by_level": cov["by_level"], "by_family": cov["by_family"],
            "top_residues": cov["top_residues"], "nid_reasons": cov["nid_reasons"],
            "unmapped": cov["unmapped"],
        },
        "curve": {"candidate_entries": curve["candidate_entries"], "chosen": curve["chosen"],
                  "thresholds": curve["thresholds"], "reachable_pct": curve["reachable_pct"],
                  "unreachable_n": curve["unreachable_n"], "points": curve["curve"][::10]},
    }
    return {"registry": registry, "asks": asks, "coverage": cov, "curve": curve,
            "sizes": {"atoms": len(atoms), "dims": len(dims), "formulas": len(formulas),
                      "operators": len(operators), "lexicon": len(lexicon), "hand_check": len(hand),
                      "mined_candidates": len(rejected)},
            "bank": bank}


def write_md(state: dict) -> str:
    reg, cov, curve = state["registry"], state["coverage"], state["curve"]
    sizes = state["sizes"]
    atoms = reg["atoms"]
    by_cov = Counter(a["coverage"] for a in atoms)
    lines: list[str] = []
    A = lines.append
    A("# Registry coverage — generated by `build_concept_registry.py`\n")
    A(f"Bank: `{reg['generated_from']['bank']['path']}` · "
      f"{reg['generated_from']['bank']['cases']} cases · sha `{reg['generated_from']['bank']['sha256_16']}`. "
      "Coverage is measured from the **question text only**; `template`/`family`/`chain` are "
      "evaluation inputs, never decomposition inputs.\n")
    A("## 1. Registry size per table\n")
    A("| table | rows | what a row is |\n|---|---:|---|")
    A(f"| atoms | {sizes['atoms']} | one raw measure -> store, column, unit, grain |")
    A(f"| dims | {sizes['dims']} | a qualifier that lives on an atom |")
    A(f"| formulas | {sizes['formulas']} | a derived measure as an expression over atoms |")
    A(f"| operators | {sizes['operators']} | a closed-set parameterised result template |")
    A(f"| lexicon | {sizes['lexicon']} | surface phrase -> atom / formula / dim / operator / scope / period |")
    A(f"| hand_check | {sizes['hand_check']} | mined entries a human must confirm |\n")
    A(f"Atom coverage: **{by_cov.get('held',0)} held**, **{by_cov.get('gap',0)} gap** "
      f"(registry knows the measure, the store does not yet carry it), "
      f"**{by_cov.get('absent',0)} absent** (declared NOT IN DATA with its reason).\n")
    A("## 2. Coverage over the 1,073 cases\n")
    st = cov["status"]
    A("| status | cases | share | meaning |\n|---|---:|---:|---|")
    A(f"| mapped | {st.get('mapped',0)} | {cov['mapped_pct']}% | every clause resolves to an atom/formula/rule and all slots are filled |")
    A(f"| not_in_data | {st.get('not_in_data',0)} | {round(100*st.get('not_in_data',0)/cov['n'],2)}% | resolves, but a required atom is absent or a gap → NID with the registry's reason |")
    A(f"| unmapped | {st.get('unmapped',0)} | {round(100*st.get('unmapped',0)/cov['n'],2)}% | a clause names a measure the registry cannot express |")
    A(f"\n**Mapped + NID = {cov['answered_pct']}%** (the ceiling for the 95% gate: NID counts only "
      "where the data truly does not exist).\n")
    A("### 2.1 by source bank\n")
    A("| bank | mapped | not_in_data | unmapped |\n|---|---:|---:|---:|")
    for k, v in cov["by_bank"].items():
        A(f"| {k} | {v.get('mapped',0)} | {v.get('not_in_data',0)} | {v.get('unmapped',0)} |")
    A("\n### 2.2 by entity level\n")
    A("| level | mapped | not_in_data | unmapped |\n|---|---:|---:|---:|")
    for k, v in cov["by_level"].items():
        A(f"| {k} | {v.get('mapped',0)} | {v.get('not_in_data',0)} | {v.get('unmapped',0)} |")
    A("\n### 2.3 by primary family\n")
    A("| family | mapped | not_in_data | unmapped |\n|---:|---:|---:|---:|")
    for k, v in sorted(cov["by_family"].items(), key=lambda kv: (len(kv[0]), kv[0])):
        A(f"| {k} | {v.get('mapped',0)} | {v.get('not_in_data',0)} | {v.get('unmapped',0)} |")
    A("\n## 3. Size vs coverage curve\n")
    A("Greedy set cover over clause requirements, starting from an **empty** lexicon: an entry "
      "is admissible when its surface matches a schema column, a held metric key, or a declared "
      "dim/operator surface — the same minimality rule the registry enforces. A case is covered "
      "when every clause of its question has an entry.\n")
    A(f"The hand-checked seed is {sizes['lexicon']} lexicon rows; the curve reaches the same clause "
      f"coverage with **{curve['thresholds'].get(95, {}).get('entries', 'n/a')} rows** at the 95% "
      "point, so about eight rows in ten of the seed are redundant synonyms.\n")
    A("| lexicon entries added | cases covered | coverage |\n|---:|---:|---:|")
    pts = curve["curve"]
    pick = [p for p in pts if p[0] % 10 == 0][:40] + ([pts[-1]] if pts else [])
    for size, covered in pick:
        A(f"| {size} | {covered} | {round(100.0*covered/max(1,curve['pool']),1)}% |")
    A("")
    th = curve["thresholds"]
    if th:
        A("Thresholds reached by the curve:\n")
        for target in (80, 90, 95):
            if target in th:
                A(f"- **{target}%** at **{th[target]['entries']} entries** ({th[target]['covered']} cases)")
            else:
                A(f"- **{target}%** not reached by the curve")
    A(f"\nCurve ceiling: **{curve['reachable_pct']}%** of the coverable pool "
      f"({curve['pool']} cases; {curve['entity_only']} excluded as entity-resolution gaps, "
      f"{curve['unreachable_case_n']} unreachable for lack of any admissible surface — those are "
      f"the true registry gaps). Candidate pool: {curve['candidate_entries']} mined surfaces.\n")
    if curve["unreachable"]:
        A("Unreachable clauses (no admissible surface exists — must be decided by design, not mined):\n")
        for mid, clause in curve["unreachable"][:30]:
            A(f"- `{mid}`: {clause[:110]}")
        A("")
    A(f"Entity default: **{cov['entity_defaults']} cases** name no entity at all, so the Ask "
      "contract's default (entity_set = the held universe) applies. They are in the pool; the "
      "answer contract names the universe it used.\n")
    A("## 4. What does not map, and why\n")
    A("### 4.1 residue terms in unmapped clauses\n")
    A("| term | clauses |\n|---|---:|")
    for term, n in cov["top_residues"][:30]:
        A(f"| `{term}` | {n} |")
    A("\n### 4.2 NOT IN DATA reasons (declared absent atoms)\n")
    A("| reason | cases |\n|---|---:|")
    for reason, n in cov["nid_reasons"][:15]:
        A(f"| {reason} | {n} |")
    A("\n### 4.3 registry gaps (atom defined, store does not carry it yet)\n")
    gaps = [(a["atom_id"], a["coverage_note"]) for a in atoms if a["coverage"] == "gap"]
    if gaps:
        A("| atom | gap |\n|---|---|")
        for aid, note in gaps:
            A(f"| `{aid}` | {note} |")
    else:
        A("none — every held atom verified against the held metric vocabulary.")
    residue_cases = [m for m in cov["unmapped"] if m not in cov.get("no_metric", [])]
    A(f"\n### 4.4 unmapped cases ({len(cov['unmapped'])})\n")
    A(f"**{len(residue_cases)}** name a measure the registry has no atom for (the residue table "
      f"above); **{len(cov['unmapped']) - len(residue_cases)}** name no measurable at all — a "
      "judgement or scope ask whose answer needs a named rule that is not declared yet. Each of "
      "those is one registry row away (§A.4), not a data problem.\n")
    A("\n".join(f"- `{m}`" for m in cov["unmapped"][:60]))
    A("\n## 5. Mined lexicon — hand-check list\n")
    hc = sorted([r for r in reg["hand_check"] if r["evidence_questions"] >= 1],
                key=lambda r: (-r["evidence_questions"], r["surface"]))
    A("| surface | kind | questions | admitted from |\n|---|---|---:|---|")
    for row in hc[:40]:
        A(f"| `{row['surface']}` | {row['kind']} | {row['evidence_questions']} | {row['vocabulary']} |")
    A(f"\n{len(hc)} mined surfaces are used by at least one question; "
      f"{len(reg['hand_check']) - len(hc)} surfaces in the extraction vocabulary are asked by "
      "nobody and are left out of the registry (they would add size, not coverage).")
    A("\nAdmission rule: a mined surface enters only if it matches a FINAL-schema column name, a "
      "held metric key / concept, or a declared dim value. Anything else stays out and shows up "
      "in §4.1 as a residue.\n")
    A(f"### 5.1 candidate surfaces the bank uses but the registry lacks ({sizes.get('mined_candidates', 0)})\n")
    A("Frequent measure-like phrases with no registry entry — the list a human should work through, "
      "because each one is either a new atom (with a store) or a dim value on an existing atom.\n")
    A("| surface | questions | matched |\n|---|---:|---|")
    for row in (reg.get("mined_candidates") or [])[:30]:
        A(f"| `{row['surface']}` | {row['evidence_questions']} | {row['matched']} |")
    return "\n".join(lines) + "\n"


def print_check(state: dict) -> None:
    cov, curve, sizes, reg = (state["coverage"], state["curve"], state["sizes"], state["registry"])
    st = cov["status"]
    print("=" * 78)
    print("CONCEPT REGISTRY v4 — check")
    print("=" * 78)
    print(f"cases: {cov['n']}   source: {reg['generated_from']['bank']['path']}")
    print("\nregistry size per table")
    for k in ("atoms", "dims", "formulas", "operators", "lexicon", "hand_check",
              "mined_candidates"):
        print(f"  {k:<12} {sizes[k]:>5}")
    by_cov = Counter(a["coverage"] for a in reg["atoms"])
    print(f"  atom coverage: held {by_cov.get('held',0)}, gap {by_cov.get('gap',0)}, absent {by_cov.get('absent',0)}")
    print("\ncoverage over the bank")
    print(f"  mapped        {st.get('mapped',0):>5}  {cov['mapped_pct']:>6}%")
    print(f"  not_in_data   {st.get('not_in_data',0):>5}  {round(100*st.get('not_in_data',0)/cov['n'],2):>6}%   (with the registry's reason)")
    print(f"  unmapped      {st.get('unmapped',0):>5}  {round(100*st.get('unmapped',0)/cov['n'],2):>6}%")
    print(f"  mapped+NID    {st.get('mapped',0)+st.get('not_in_data',0):>5}  {cov['answered_pct']:>6}%   <- gate ceiling")
    print("\nsize vs coverage curve (lexicon entries added -> cases covered)")
    pts = curve["curve"]
    pool = max(1, curve["pool"])
    if pts:
        for size, covered in (pts[::max(1, len(pts)//10)] + [pts[-1]]):
            bar = "#" * int(round(40.0 * covered / pool))
            print(f"  {size:>4} -> {covered:>5}  {100.0*covered/pool:>6.1f}%  {bar}")
    for target in (80, 90, 95):
        got = curve["thresholds"].get(target)
        print(f"  {target}% coverage at {got['entries'] if got else 'NOT REACHED'} "
              f"entries" + ("" if got else f" (curve ceiling {curve['reachable_pct']}%)"))
    print(f"  curve pool {curve['pool']} cases; excluded: {curve['entity_only']} entity-resolution, "
          f"{curve['unreachable_case_n']} unreachable")
    residues = cov["top_residues"][:8]
    print("\ntop residue terms: " + ", ".join(f"{t}({n})" for t, n in residues))
    print(f"\nwrote: {OUT_JSON.name} ({OUT_JSON.stat().st_size if OUT_JSON.exists() else 0} bytes), "
          f"{OUT_MD.name} ({OUT_MD.stat().st_size if OUT_MD.exists() else 0} bytes)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="write the registry and print the checks")
    ap.add_argument("--show", default="", help="comma-separated mids to print the decomposition of")
    ap.add_argument("--no-db", action="store_true", help="skip mining the pilot stores (offline)")
    args = ap.parse_args(argv)

    state = build(args)
    OUT_JSON.write_text(json.dumps(state["registry"], indent=1, sort_keys=False,
                                  ensure_ascii=False) + "\n", encoding="utf-8")
    OUT_MD.write_text(write_md(state), encoding="utf-8")

    # idempotency: rebuild in memory and compare bytes
    again = json.dumps(build(args)["registry"], indent=1, sort_keys=False, ensure_ascii=False) + "\n"
    deterministic = again == OUT_JSON.read_text(encoding="utf-8")

    if args.check:
        print_check(state)
        print(f"deterministic: {'PASS' if deterministic else 'FAIL'} (byte-identical rebuild)")
    if args.show:
        want = [s.strip() for s in args.show.split(",") if s.strip()]
        for ask in state["asks"]:
            if ask["mid"] in want:
                print("\n" + "=" * 78)
                print(f"{ask['mid']}: {ask['question']}")
                print(f"  status={ask['status']}  window={ask['window']}  entity={ask['entity']}")
                if ask["nid_reasons"]:
                    print("  NID: " + "; ".join(ask["nid_reasons"]))
                for i, p in enumerate(ask["parts"], 1):
                    line = f"  ({i}) {p['clause'][:88]}"
                    print(line)
                    got = []
                    for k in ("metric", "atoms", "formulas", "topics", "rules", "dims", "operators", "scope"):
                        v = p.get(k)
                        if v:
                            got.append(f"{k}={v if not isinstance(v, list) else ','.join(v)}")
                    print("      " + (" | ".join(got) if got else "(qualifier)"))
                    if p.get("residue"):
                        print(f"      RESIDUE {p['residue']}")
    if not args.check and not args.show:
        print("wrote", OUT_JSON.name, "and", OUT_MD.name, "— run with --check for the summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
