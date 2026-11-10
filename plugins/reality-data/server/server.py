"""reality-data MCP server (stdio).

One call should be enough to learn where the data lives; a few calls should be
enough to answer a company question.  Every tool is read-only and returns
provenance.  ``search_docs`` is imported from the co-located ``search_docs.py``
module when that module is present.
"""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
# search_docs.py imports reality_engine.search.*; a script launch does not put
# the checkout root on sys.path, so add the explicit env root (or derive it).
_REPO_ROOT = Path(os.environ.get("REALITY_DATA_REPO_ROOT") or SERVER_DIR.parents[2]).resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

import catalog as catalog_mod
import core

INSTRUCTIONS = """Local reality-engine data search. The data is read-only and every answer carries provenance.

PILOT3 FIRST: the pilot3_* tools hold every company in their database's company table -- the whole NSE+BSE universe the build covers (thousands of companies), never a sample of three: check coverage with pilot3_sql ('SELECT COUNT(*) FROM company') instead of assuming a company is absent. For any company in that table (symbol, BSE code, ISIN or name) every question goes to the pilot3_* tools before any other tool. They read one script-built database (dated page text of every held document, KPI series, reported and derived financial lines, ratios, shareholding, management statements, forward guidance) and every row carries provenance (table, source document + page or store row, known_at). Route: any forward-looking target (revenue growth, EBITDA margin, order-intake target, NIM, credit cost, AUM growth, capex, cost of production/tonne, interest-cost cut; "what guidance/outlook/target/corridor did they give", "did the guidance change between calls") -> pilot3_guidance FIRST (one row per target with period, low/high, unit, direction and the row it revised); company-stated KPI (order book, AUM, EBITDA/tonne, NIM, shipments) -> pilot3_kpi; reported or derived financial line (revenue, PAT, net debt, borrowings, capex, EPS; FY26, H1FY26, Q2FY26; standalone/consolidated) -> pilot3_fin; margin, ROE, ROCE, growth, days, PE, PB, EV/EBITDA, market cap -> pilot3_ratio; promoter/FPI/MF/insurance/government (GoI) holding or a four-quarter shareholding path -> pilot3_holding(symbol, as_of, category=..., quarters=4) -- every filed shp_category row comes back with pct and pct_basis; share count on a date -> pilot3_holding(symbol, as_of).share_capital; what management said in a call (margins, capex, outlook, other commentary) -> pilot3_statements (falls back to the call page text when no statement carries the topic); price reaction to a filing, gaps, RSI, moving averages, volume spikes, range position -> pilot3_tech; list documents -> pilot3_docs; anything else in the text -> pilot3_search; arbitrary table query -> pilot3_sql (tables: company, kpi_series, fin_annual_line, fin_quarter_xbrl, fin_quarter_printed, ratio_panel, valuation_daily, shp_category, shp_holder, shp_pledge, share_capital, dividend_event, price_delivery, bulk_block_deal, insider_trade, index_price, transcript_statement, guidance, doc, doc_page; view fin_quarter_current: the one preferred financial line per symbol, fiscal_period, basis and line_item now, and the quarter tables' preferred_from / preferred_to columns elect the same figure at any past day -- read them or pilot3_fin, never a hand sum over both tables). Pass as_of (YYYY-MM-DD) for any question dated in the past: rows known after it are dropped. A company the database does not hold returns {"found": false} (or error code not_pilot3): only then use the raw tools below or say NOT IN DATA. A {"found": false} answer for a company it does hold lists what is available; read that list and retry. pilot3_fin defaults to the consolidated statement and labels the basis on every row; standalone is an explicit argument. pilot3_sql cuts text cells at max_chars (default 400): pass max_chars=8000 for long page text or a full quote. Do not open raw PDFs or the large databases when a pilot3 tool answers.

ROUTE BY QUESTION SHAPE FIRST (other companies, or after pilot3 says not found) — one call each, before any sql():
- delivery / delivered quantity on a date (NSE+BSE) -> delivery(symbol, dates)
- high / low / YTD extreme -> price_extreme(symbol, start, end, kind)
- promoter holding, share count -> holding(symbol, as_of)
- "what documents / latest deck / latest transcript" -> docs(symbol, doc_type, date_from, date_to)
- "page N of the <date> presentation" -> doc_page(symbol, date, page)
- "what did they say about X in the <date> transcript/deck/AR" -> doc_find(symbol, terms, doc_type, date)
- financial numbers, segments, guidance -> facts(symbol, kind, period); OHLCV range -> price(...)
Symbols, BSE codes, ISINs and names all resolve inside each tool. A {"found": false} answer lists what was checked and the nearest documents: follow its hint, then say NOT IN DATA; do not hand-write SQL over the same tables. Filing dates can be the evening of, or a day after, the date a user names. Exact share counts come from filings; XBRL paid-up capital / face value is rounded.

Use catalog() when you need the map: one line per database by default, with db= for that database's tables and query= for a word search across them (db='pilot3' lists the pilot3 store). schema(table, db) gives one table's columns, types, row count, indexes and sample keys — use it instead of PRAGMA/sqlite_master probes. For a specific company go straight to the data tools; resolve is optional because price/facts resolve the symbol themselves. resolve(query) turns a symbol, company name or ISIN into the canonical identity (ISIN history included). price(symbol, start, end=None, adjusted=False) returns OHLCV, delivery quantity/percent and traded value; close is raw unless adjusted=True. facts(symbol, kind=None, period=None, include_model_read=False) returns filed XBRL results first; the annual-report, deck and call extractions are model-read by AI and unverified, withheld unless include_model_read=true or kind is ar/deck/concall, and every row says extraction=filed_xbrl|model_read; kind accepts segments, financials, kpis, guidance, results, deck, concall, ar, or free text; period accepts FY25, Q4FY26 or a date. search_docs(query, symbol=None, doc_types=None, date_from=None, date_to=None, top_k=10, as_of=None, include_model_read=False) returns text passages (as_of drops documents published after that date, and undated ones); its annual-report model-read quotes are withheld unless include_model_read=true; sql(query, db) is a bounded read-only escape hatch.

Examples: price("PPL", "2026-03-30"); facts("PPL", kind="segments", period="FY25"); facts("PPL") for a broad fundamentals answer. Provenance names the database, table and snapshot; quarantine keys are applied to annual-report facts and demo tables are never presented as data."""

server = MCPServer(name="reality-data", version="0.1.0", instructions=INSTRUCTIONS)

_SEARCH_MODULE = None
_SEARCH_ERROR: str | None = None
_SEARCH_LOADED = False


def _safe(call) -> dict[str, Any]:
    try:
        return call()
    except core.DataError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except NotImplementedError as exc:
        return {"ok": False, "error": {"code": "not_implemented", "message": str(exc)}}
    except Exception as exc:  # never turn a data error into an MCP protocol failure
        return {"ok": False, "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}}


def _load_search() -> Any:
    global _SEARCH_MODULE, _SEARCH_ERROR, _SEARCH_LOADED
    if _SEARCH_LOADED:
        return _SEARCH_MODULE
    _SEARCH_LOADED = True
    try:
        import search_docs as mod  # type: ignore
        _SEARCH_MODULE = mod
    except Exception as exc:  # module not merged yet, or import failure
        _SEARCH_MODULE = None
        _SEARCH_ERROR = f"{type(exc).__name__}: {exc}"
    return _SEARCH_MODULE


def _warm_search() -> None:
    # 2026-10-28: every dsh worker starts its own server, and warming the vector index costs ~1 GB each, which
    # capped parallel workers at 3-4 on 16 GB. Inside a worker (or with REALITY_DATA_NO_WARM=1) the index loads
    # lazily on the first search instead.
    # 2026-10-29: the worker check did not hold (every server sat at 1.2 GB private), so preloading is now
    # opt-in everywhere: set REALITY_DATA_WARM_SEARCH=1 to warm at start.
    if os.environ.get("REALITY_DATA_WARM_SEARCH") != "1":
        return

    def run() -> None:
        mod = _load_search()
        if mod is None:
            return
        try:
            warm = getattr(mod, "warm", None)
            if callable(warm):
                warm()
        except Exception:
            pass
    threading.Thread(target=run, name="reality-data-search-warm", daemon=True).start()


@server.tool(
    name="catalog",
    description=(
        "The data map, compact by default: one line per database (key, kind, table "
        "count, description) plus the vector indexes. Narrow it with db='<key>' "
        "(that database's tables: description, key columns, row count, coverage) or "
        "query='<word>' (tables matching the word anywhere). schema(table, db) is the "
        "per-table tool. refresh=true re-introspects the live files (slower)."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def catalog(refresh: bool = False, db: str | None = None,
            query: str | None = None) -> dict[str, Any]:
    return _safe(lambda: catalog_mod.catalog_view(db=db, query=query, refresh=refresh))


@server.tool(
    name="schema",
    description=(
        "One table's shape in one call: columns with types, row count, indexes, date "
        "coverage and up to three sample rows of its key columns. Resolved from the "
        "catalog cache, so it is fast and needs no warm search index; a miss returns "
        "the nearest table names. Use it instead of PRAGMA/sqlite_master probes."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def schema(table: str, db: str | None = None) -> dict[str, Any]:
    return _safe(lambda: catalog_mod.get_schema(table, db=db))


@server.tool(
    name="resolve",
    description=(
        "Resolve a symbol, company name or ISIN to the canonical company identity. "
        "ISIN-history aware: returns the current ISIN, NSE/BSE symbols/codes, status, "
        "listing dates and every symbol/ISIN validity window. PPL -> INE050001010."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def resolve(query: str) -> dict[str, Any]:
    return _safe(lambda: core.resolve(query))


@server.tool(
    name="price",
    description=(
        "Daily OHLCV, delivery quantity/percent, traded value (INR and crore) and "
        "split/dividend adjustment factors for one date range. end defaults to start "
        "(single day). Raw and adjusted closes are both returned; adjusted=True selects "
        "adj_close for the summary. NSE first, BSE fallback."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def price(symbol: str, start: str, end: str | None = None, adjusted: bool = False) -> dict[str, Any]:
    return _safe(lambda: core.price(symbol, start, end=end, adjusted=adjusted))


@server.tool(
    name="facts",
    description=(
        "Structured fundamentals, segments and KPIs for a company: filed XBRL "
        "results first; annual-report, deck and call extractions are model-read by "
        "AI and unverified, so they are withheld unless include_model_read=true or "
        "kind is ar/deck/concall, and every row is labelled extraction=filed_xbrl "
        "or model_read. model_read_withheld counts the rows a default call left out. "
        "kind: segments | financials | "
        "kpis | guidance | results | deck | concall | ar | free text. period: FY25, "
        "Q4FY26, 2025-03-31, or omitted. as_of (YYYY-MM-DD) keeps only facts whose own "
        "filing timestamp is on or before that day. Each fact carries source, doc id, page, "
        "period, basis, quote and URL/local path where available."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def facts(symbol: str, kind: str | None = None, period: str | None = None,
          limit: int = 80, as_of: str | None = None,
          include_model_read: bool = False) -> dict[str, Any]:
    return _safe(lambda: core.facts(symbol, kind=kind, period=period, limit=limit, as_of=as_of,
                                    include_model_read=include_model_read))


# --- lookups: market ---
import lookups_market  # noqa: E402  (kept inside this block so the diff stays one hunk)


@server.tool(
    name="delivery",
    description=(
        "Deliverable quantity and delivery % per exchange for one or more dates, in "
        "one call. NSE + BSE rows, the sum, traded volume and delivery % per exchange, "
        "plus a total. Always the raw (unadjusted) px_nse/px_bse tables. A date with no "
        "row returns status 'no_trading' when the market was shut (no px_nse rows at "
        "all) or 'missing_for_symbol' naming the exchanges missing. dates is a list "
        '(["2026-04-13","2026-04-14"]) or one date; with end it becomes a span.'
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def delivery(symbol: str, dates: list[str] | str, end: str | None = None) -> dict[str, Any]:
    return _safe(lambda: lookups_market.delivery(symbol, dates, end=end))


@server.tool(
    name="price_extreme",
    description=(
        "Highest high and/or lowest low (with date and exchange) across NSE and BSE "
        "for one window, and which exchange holds the overall extreme. Default window "
        "is calendar YTD of the snapshot's last date; the answer states that snapshot "
        "end date (data freshness). kind: high | low | both. adjusted=True reads the "
        "split/dividend-adjusted tables."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def price_extreme(symbol: str, start: str | None = None, end: str | None = None,
                  kind: str = "high", adjusted: bool = False) -> dict[str, Any]:
    return _safe(lambda: lookups_market.price_extreme(symbol, start=start, end=end,
                                                      kind=kind, adjusted=adjusted))


@server.tool(
    name="holding",
    description=(
        "Promoter %, public %, total shares and every share-count candidate found, for "
        "the latest shp_index quarter <= as_of (default today). share_count_candidates "
        "lists ar_facts exact counts and the results_xbrl paid-up/face-value division "
        "(which is rounded); best_share_count prefers the exact filing figure and "
        "xbrl_rounded flags when the XBRL-derived figure differs."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def holding(symbol: str, as_of: str | None = None) -> dict[str, Any]:
    return _safe(lambda: lookups_market.holding(symbol, as_of=as_of))
# --- end lookups: market ---


@server.tool(
    name="search_docs",
    description=(
        "Hybrid vector + FTS search over concalls, presentations, annual reports, "
        "announcements, RBI, government/budget/PIB documents. Filters: symbol, doc_types, "
        "date_from, date_to, as_of (point-in-time; rows dated later are dropped and "
        "counted in hidden_after_as_of). Each hit carries text, doc_id, doc_type, symbol, "
        "isin, date, page, url, score and source (fts, local_dense, seed_dense or "
        "paid_dense; '+' when fused). Degrades to FTS when no dense path is available "
        "(reported by the search module's warm/status). Annual-report model-read quotes "
        "are withheld unless include_model_read=true, then labelled extraction=model_read. "
        "Results are quarantine-filtered."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def search_docs(query: str, symbol: str | None = None, doc_types: list[str] | None = None,
                date_from: str | None = None, date_to: str | None = None,
                top_k: int = 10, as_of: str | None = None,
                include_model_read: bool = False) -> dict[str, Any]:
    def call() -> dict[str, Any]:
        mod = _load_search()
        if mod is None:
            raise NotImplementedError(
                "search_docs.py is not present in this checkout yet "
                f"({_SEARCH_ERROR or 'module missing'}); resolve/price/facts/catalog/sql still work"
            )
        fn = getattr(mod, "search_docs", None)
        if not callable(fn):
            raise NotImplementedError("search_docs.py does not expose search_docs(...)")
        try:
            top = max(1, min(int(top_k), 50))
        except (TypeError, ValueError):
            raise core.DataError("bad_limit", "top_k must be an integer between 1 and 50")
        # "PPL segment revenue" should resolve to Prakash Pipes, not PPLPHARMA:
        # an explicit uppercase ticker token in the query is a strong scope hint.
        inferred = None
        if not symbol:
            for token in re.findall(r"\b[A-Z][A-Z0-9&.-]{1,14}\b", query)[:4]:
                try:
                    hit = core.resolve(token)["matches"][0]
                except (core.DataError, IndexError):
                    continue
                if hit.get("match_type") in ("symbol", "isin") and hit.get("score", 0) >= 95:
                    inferred = hit.get("nse_symbol") or hit.get("bse_symbol") or hit.get("isin")
                    break
        hidden = 0
        results_as_of = as_of
        try:
            results = fn(query, symbol=symbol or inferred, doc_types=doc_types, date_from=date_from,
                         date_to=date_to, top_k=top, as_of=as_of,
                         include_model_read=include_model_read)
        except ValueError as exc:
            raise core.DataError("bad_request", str(exc))
        if isinstance(results, dict):
            hidden = int(results.get("hidden_after_as_of") or 0)
            results_as_of = results.get("as_of", as_of)
            results = results.get("results", [])
        results = list(results or [])
        qids = core.quarantined_doc_ids()
        if qids:
            filtered = []
            for hit in results:
                try:
                    doc_id = int((hit or {}).get("doc_id"))
                except (TypeError, ValueError):
                    filtered.append(hit)
                    continue
                if doc_id not in qids:
                    filtered.append(hit)
            results = filtered
        payload = {
            "query": query,
            "symbol_scope": symbol or inferred,
            "count": len(results),
            "results": results,
            "provenance": {
                "module": "search_docs.py",
                "vector_index": "search_docs.py-managed; see its warm()/status() for the active index",
                "read_only": True,
                "quarantine_doc_ids_excluded": len(qids),
            },
        }
        if as_of is not None:
            payload["as_of"] = results_as_of
            payload["hidden_after_as_of"] = hidden
        return payload
    return _safe(call)


@server.tool(
    name="sql",
    description=(
        "Read-only escape hatch for arbitrary SELECT/WITH queries. db: truth (DuckDB "
        "snapshot), equity_intelligence, ar_facts, deck_figures, concall_facts, "
        "results_xbrl, bse_announcements, pilot3. Single statement only, row-limited (default "
        "200, max 1000), 5 s timeout. Write/DDL keywords are rejected."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def sql(query: str, db: str = "truth", limit: int = 200,
        timeout_seconds: float = 5.0) -> dict[str, Any]:
    return _safe(lambda: core.sql(query, db=db, limit=limit, timeout_seconds=timeout_seconds))


# --- lookups: universe ---
import universe as _universe  # noqa: E402  (co-located module, same import style)


@server.tool(
    name="universe",
    description=(
        "Point-in-time theme members: companies in a theme (gold_jewellery_finance, "
        "omc_refining, housing_finance, dairy, data_centres, defence, "
        "specialty_chemicals, textiles_exporters, ...) on a date, sorted by weight, "
        "each with method, since, evidence_id and pivot. stale_days is the age of the "
        "last build; an unknown theme returns the closest themes."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def universe(theme: str, as_of: str | None = None, min_weight: float = 0.01) -> dict[str, Any]:
    return _safe(lambda: _universe.universe(theme, as_of=as_of, min_weight=min_weight))
# --- end lookups: universe ---


# --- lookups: docs ---
import lookups_docs as _lookups_docs  # noqa: E402  (co-located module, same import style)


@server.tool(
    name="docs",
    description=(
        "List one company's documents across every store, newest first: decks, concall "
        "transcripts, annual reports and announcements. Each entry carries the filing date, "
        "title, page count, the store keys (sha256 / doc_id / NEWSID) and has_text / "
        "has_facts per store. Filters: doc_type (deck|transcript|ar|announcement), "
        "date_from, date_to, as_of (never list a document first known after that day). "
        "Answers 'what is the latest X'."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None,
         date_to: str | None = None, limit: int = 20,
         as_of: str | None = None) -> dict[str, Any]:
    return _safe(lambda: _lookups_docs.docs(symbol, doc_type=doc_type, date_from=date_from,
                                            date_to=date_to, limit=limit, as_of=as_of))


@server.tool(
    name="doc_page",
    description=(
        "Pick the document of the requested type nearest a date (±3 days, says which and why) "
        "and return one page's full text plus the facts extracted on that page and the page "
        "count ('page 21 of 79'). Text comes from the stored chunks, the local PDF (PyMuPDF) "
        "or a Drive fetch by sha256 (fetched=true when downloaded); for decks whose PDF is "
        "gone it falls back to the stored page extraction. as_of (YYYY-MM-DD) refuses a "
        "document first known after that day."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def doc_page(symbol: str, date: str, page: int, doc_type: str | None = None,
             as_of: str | None = None) -> dict[str, Any]:
    return _safe(lambda: _lookups_docs.doc_page(symbol, date, page, doc_type=doc_type,
                                                as_of=as_of))


@server.tool(
    name="doc_find",
    description=(
        "Lexical search (LIKE over bounded per-document rows, plus deck PDF text) inside one "
        "company's documents, optionally restricted to one doc_type and one filing date "
        "(±3 days). Returns passages with doc type, date, page (when the page is in the text) "
        "and the exact quote. This is the 'what did they say about X in the Y transcript' tool. "
        "as_of (YYYY-MM-DD) is pushed into every store's SQL; later passages never come back."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def doc_find(symbol: str, terms: str, doc_type: str | None = None, date: str | None = None,
             top_k: int = 8, as_of: str | None = None) -> dict[str, Any]:
    return _safe(lambda: _lookups_docs.doc_find(symbol, terms, doc_type=doc_type, date=date,
                                                top_k=top_k, as_of=as_of))
# --- end lookups: docs ---


# --- lookups: pilot3 (every company the pilot database's company table holds) ---
import lookups_pilot3 as _p3  # noqa: E402
import lookups_ratings as _ratings  # noqa: E402
import lookups_tech as _tech  # noqa: E402

_RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


@server.tool(
    name="pilot3_kpi",
    description=(
        "Company-stated KPI series for every company the pilot database holds, from decks, results, press "
        "releases, transcripts and annual reports: order book, order intake, AUM, GNPA, EBITDA per tonne, shipments, "
        "net debt/EBITDA ... kpi = metric name (a word is enough; a miss lists the metrics held). The words "
        "investors use resolve too: NIM / net interest margin -> nim_pct, credit cost / losses and provisions to "
        "assets -> credit_cost_bps, cost of funds / cost of borrowings -> cost_of_funds_pct. period: Q2FY26, "
        "FY26, H1FY26 or a date. dimension (segment/product; total first), basis, as_of. Each row: value, "
        "unit, period, quote, provenance (document, page, known_at). A row whose independent check failed is "
        "quarantined and hidden (include_quarantined=true returns it); every row carries check_status = verified or "
        "unverified (unverified rows add check_note, the soft checks that did not pin them): prefer verified rows "
        "and say 'unverified' when quoting an unverified one."
    ),
    annotations=_RO,
)
def pilot3_kpi(symbol: str, kpi: str, period: str | None = None, as_of: str | None = None,
               dimension: str | None = None, basis: str | None = None, limit: int = 10,
               include_quarantined: bool = False) -> dict[str, Any]:
    return _safe(lambda: _p3.kpi(symbol, kpi, period=period, as_of=as_of, dimension=dimension, basis=basis,
                                 limit=limit, include_quarantined=include_quarantined))


@server.tool(
    name="pilot3_fin",
    description=(
        "Reported / derived / company-stated financial lines for every company the pilot database holds: annual "
        "(FY26, H1FY26) from XBRL results and annual reports, quarterly (Q2FY26) from XBRL. One preferred figure per "
        "measure, period and basis (the newest filing's restatement wins; the alternatives are listed), the same "
        "election held by the fin_quarter_current view and the preferred_from / preferred_to columns. measure e.g. "
        "revenue_from_operations, pat, ebitda, net_debt, total_borrowings, eps_basic, capex_payments, "
        "cash_flow_from_operations (a miss lists the lines held). basis = standalone | consolidated; when omitted it "
        "defaults to consolidated (the group statement) and every row states its basis; definition = xbrl_reported | "
        "xbrl_derived | company_stated | reported (annual only). Rows carry value, unit, scale (value_inr for rupee "
        "lines), definition and provenance."
    ),
    annotations=_RO,
)
def pilot3_fin(symbol: str, measure: str, period: str | None = None, basis: str | None = None,
               definition: str | None = None, as_of: str | None = None, limit: int = 12) -> dict[str, Any]:
    return _safe(lambda: _p3.fin(symbol, measure, period=period, basis=basis, definition=definition,
                                 as_of=as_of, limit=limit))


@server.tool(
    name="pilot3_ratio",
    description=(
        "Derived ratios with their formula: ebitda_margin_pct, pat_margin_pct, roe, roa, roce, debt_to_equity, "
        "interest_coverage, revenue_growth_yoy_pct, book_value_per_share, dividend_payout_pct, receivable/"
        "inventory/payable days, opex_to_net_total_income_pct (a lender's operating cost over net total income, "
        "annual and with the input rows) ... per quarter or fiscal year (ratio_panel); and PE, PB, EV/EBITDA, "
        "market cap, dividend yield on a date (valuation_daily: give period or as_of as YYYY-MM-DD). Provenance "
        "names the formula and its input rows."
    ),
    annotations=_RO,
)
def pilot3_ratio(symbol: str, ratio: str, period: str | None = None, as_of: str | None = None,
                 basis: str | None = None, limit: int = 8) -> dict[str, Any]:
    return _safe(lambda: _p3.ratio(symbol, ratio, period=period, as_of=as_of, basis=basis, limit=limit))


@server.tool(
    name="pilot3_holding",
    description=(
        "Shareholding pattern in force on as_of (the latest quarter whose XBRL filing was out by then): EVERY "
        "filed category row -- promoter, public, mutual_funds, fpi_total, insurance, banks, foreign, "
        "central_government_or_president_of_india (GoI) ... -- with pct and the pct_basis its percentage is "
        "printed on, one row per category and quarter (the XBRL parse before the shp_index copy); plus shares "
        "outstanding / paid-up capital / face value on that day. category filters by the words investors use: "
        "government / GoI / DIPAM -> central_government_or_president_of_india, FPI / FII -> fpi_total and its "
        "lines, MF / mutual fund, promoter, public, retail, DII (a no-match reply lists categories_held). "
        "quarters=N (default 1, max 12) returns the last N quarters so a 'last four quarters' trend is one call; "
        "quarter_end pins one. all_categories is kept for older briefs (every filed category is returned anyway). "
        "holders = the quarter's named shareholders (top 12 by shares; the persons-in-concert disclosures are "
        "skipped, all_holders=true lists every named holder including them with pac_name). promoter_pledge = the "
        "filing's own pledge / non-disposal / other-encumbrance flags with the pledged shares and its printed "
        "percentage of the promoter holding ('what share of promoter holding is pledged'); nil=true means the filing states NO pledge (0 shares, 0%): answer 'nil, per the filing', never 'not found'; previous_quarter and changed answer 'has it changed'. pct_basis = the share "
        "count the printed percentages are on (a depository-receipt issuer's excludes the shares under DR "
        "custody). quarters_held and categories_held say what the table covers for the company."
    ),
    annotations=_RO,
)
def pilot3_holding(symbol: str, as_of: str, quarter_end: str | None = None,
                   all_categories: bool = False, all_holders: bool = False,
                   category: str | None = None, quarters: int = 1) -> dict[str, Any]:
    return _safe(lambda: _p3.holding(symbol, as_of, quarter_end=quarter_end, all_categories=all_categories,
                                     all_holders=all_holders, category=category, quarters=quarters))


@server.tool(
    name="pilot3_statements",
    description=(
        "Management statements from concall transcripts as exact quotes with speaker, role and call date. "
        "topic = tag (margin, guidance, capex, order, demand, debt ...) that ranks the tagged statements first, "
        "terms = words that must all appear, date_from/date_to on the call date, role = ceo | cfo | md | mgmt, "
        "as_of. period (Q4FY26 / FY26) and rank_terms (the question's own words) put the statements of that "
        "period, carrying those words, first; the newest call breaks a tie. latest=true keeps only the newest "
        "call. topic_matched=false says no statement carries that tag; the call page text is then searched "
        "(bm25, newest call first) and fallback='doc_page_bm25' marks those rows."
    ),
    annotations=_RO,
)
def pilot3_statements(symbol: str, topic: str | None = None, terms: str | None = None,
                      date_from: str | None = None, date_to: str | None = None, as_of: str | None = None,
                      limit: int = 10, role: str | None = None, period: str | None = None,
                      rank_terms: str | None = None, latest: bool = False) -> dict[str, Any]:
    return _safe(lambda: _p3.statements(symbol, topic=topic, terms=terms, date_from=date_from, date_to=date_to,
                                        as_of=as_of, limit=limit, role=role, period=period,
                                        rank_terms=rank_terms, latest=latest))


@server.tool(
    name="pilot3_guidance",
    description=(
        "Forward guidance for every company the pilot database holds: the current target of each metric and target "
        "period management gave, from transcripts, decks, results and press releases (rule-extracted, exact "
        "quote). metric: revenue_growth, ebitda_margin, order_intake, nim, credit_cost, aum_growth, capex, "
        "cost_of_production, interest_cost, ebitda_per_tonne, new_loans, new_customers, opex_to_nti, other (a word "
        "is enough; a miss lists the metrics held). period: FY27, Q2FY27, H1FY26, or a horizon (medium_term, "
        "long_term). By default an older row of the same metric+period that a later document replaced is dropped "
        "(the kept row carries superseded_rows = how many) and history=true returns every row as stored. Each row: "
        "target period, low/high, unit (pct, bps, mn, inr_cr, usd_per_tonne ...), direction (up/down/flat), "
        "said_on, speaker, quote, and revision_of + previous (the earlier row of the same metric+period and its "
        "values), so 'did the guidance change between the two calls' answers from one call. Newest first; as_of "
        "drops rows known after that day (a row the day could not see never supersedes one it could). A row whose "
        "independent check failed is quarantined and hidden (include_quarantined=true returns it); every row "
        "carries check_status = verified or unverified (unverified rows add check_note): prefer verified rows and "
        "say 'unverified' when quoting an unverified one. Ask this "
        "before pilot3_statements or pilot3_search for any question about guidance, outlook, targets or corridors."
    ),
    annotations=_RO,
)
def pilot3_guidance(symbol: str, metric: str | None = None, period: str | None = None,
                    as_of: str | None = None, limit: int = 12, history: bool = False,
                    include_quarantined: bool = False) -> dict[str, Any]:
    return _safe(lambda: _p3.guidance(symbol, metric=metric, period=period, as_of=as_of, limit=limit,
                                      history=history, include_quarantined=include_quarantined))


@server.tool(
    name="pilot3_docs",
    description=(
        "Documents held for a company the pilot database covers (every deck, transcript, annual report, results "
        "file, press release, announcement the build holds for it), newest first with filing date, page count and "
        "known_at; counts_by_type tells what exists. doc_type: deck | transcript | annual_report | results | "
        "press_release | announcement."
    ),
    annotations=_RO,
)
def pilot3_docs(symbol: str, doc_type: str | None = None, date_from: str | None = None,
                date_to: str | None = None, as_of: str | None = None, limit: int = 20) -> dict[str, Any]:
    return _safe(lambda: _p3.docs(symbol, doc_type=doc_type, date_from=date_from, date_to=date_to,
                                  as_of=as_of, limit=limit))


@server.tool(
    name="pilot3_search",
    description=(
        "Full-text search (FTS5 bm25, ranked) over the dated text of every held document page of a company the "
        "pilot database covers. Returns the exact snippet around the match with document, page, filing date "
        "and known_at. Use after the structured pilot3 tools, or when the question is about wording. period "
        "(Q1FY27 / FY26), date_from+date_to (filing window) and doc_type boost the pages that print the period, "
        "were filed in the window, or are of that type. as_of drops later pages."
    ),
    annotations=_RO,
)
def pilot3_search(symbol: str, query: str, as_of: str | None = None, limit: int = 10,
                  doc_type: str | None = None, period: str | None = None,
                  date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    return _safe(lambda: _p3.search(symbol, query, as_of=as_of, limit=limit, doc_type=doc_type, period=period,
                                    date_from=date_from, date_to=date_to))


@server.tool(
    name="pilot3_semantic",
    description=(
        "Meaning-based (embedding) page search over one company's held documents: transcripts, decks, results, "
        "press releases and annual reports known from 2025-04-01 (text only). Use when pilot3_search's keywords "
        "miss because the page words it differently (\"why did margins fall\", \"what changed in the "
        "strategy\"). Returns the closest pages with up to `chars` of page text, score, filing date and "
        "known_at; as_of drops later pages, doc_type and date_from+date_to narrow the pool. coverage says how "
        "many of the company's pages carry a vector. Each new query text costs a paid embedding (gated)."
    ),
    annotations=_RO,
)
def pilot3_semantic(symbol: str, query: str, as_of: str | None = None, limit: int = 8,
                    doc_type: str | None = None, date_from: str | None = None, date_to: str | None = None,
                    chars: int = 1500) -> dict[str, Any]:
    import lookups_semantic as _sem
    return _safe(lambda: _sem.semantic(symbol, query, as_of=as_of, limit=limit, doc_type=doc_type,
                                       date_from=date_from, date_to=date_to, chars=chars))


@server.tool(
    name="pilot3_tech",
    description=(
        "Price reaction and technicals computed in code, never hand-computed. kind='reaction': the market reaction "
        "to the last `limit` filings of `doc_type` (default results) before as_of (or in an explicit start/end "
        "range); day 0 is the filing date only when known_at is at or before the 15:30 IST close and that date is "
        "a trading session, else the NEXT session. Per filing: known_at, day0, day0_rule, and rows for day 0 "
        "through day `sessions` with close-to-close % vs the previous session close, cumulative % vs the close "
        "before day 0, volume, volume multiple vs the mean of the 20 sessions BEFORE day 0, delivery %, the index's "
        "same-day %, plus cum_1d_pct, cum_5s_pct (the 5th session counted from day 0) and cum_window_pct. "
        "kind='gaps': sessions in [start,end] (default the last 365 days) with |open/prev_close-1| >= threshold "
        "(default 0.03): gap %, close vs previous close %, held = (close-prev_close)/(open-prev_close) with its "
        "fill date (first later session whose low/high touches prev_close), delivery % vs its trailing 250-session "
        "mean. kind='rsi': Wilder 14 on adjusted close, today's value, the last `window` (default 30) sessions and "
        "the two lowest/two highest closes in it with the RSI at each and bullish/bearish divergence. kind='ma': "
        "SMA 50 and 200 on adjusted close at as_of, value, % above/below and the last close-vs-SMA cross date and "
        "direction (insufficient_history when the SMA lacks its window). kind='volume_spikes': sessions in the "
        "last 365 days with volume >= threshold (default 3) x the mean volume of the PRIOR 20 sessions, with the "
        "multiple, close-to-close % and delivery %. kind='range': 52-week high/low of close with dates, position "
        "= (close-low)/(high-low), % above low, % below high. Sessions are price_delivery NSE rows; as_of drops "
        "later sessions; rows carry provenance (table, 'NSE <date>', known_at)."
    ),
    annotations=_RO,
)
def pilot3_tech(symbol: str, kind: str, as_of: str | None = None, start: str | None = None,
                end: str | None = None, sessions: int = 5, threshold: float | None = None,
                window: int | None = None, doc_type: str = "results", limit: int = 10) -> dict[str, Any]:
    return _safe(lambda: _tech.tech(symbol, kind, as_of=as_of, start=start, end=end, sessions=sessions,
                                    threshold=threshold, window=window, doc_type=doc_type, limit=limit))


@server.tool(
    name="pilot3_ratings",
    description=(
        "Credit-rating actions and the agency's own rationale text for one company, from the fetched CARE / ICRA / "
        "CRISIL rationale notes (outside-doc store, REALITY_RATINGS_DB). Returns every instrument action printed, "
        "known by `as_of`: agency, rating date, instrument, rating, outlook, action (reaffirmed / assigned / "
        "upgraded / downgraded / withdrawn / revised) and amount_crore when printed, plus each rationale's key "
        "sections verbatim (rationale, strengths, weaknesses, sensitivities/triggers, liquidity, outlook) with "
        "provenance (agency, url, rating date, known_at). Point in time on known_at (the press-release date the "
        "rationale was public, never earlier than its index date): a later action never appears in an earlier "
        "answer. Use it for 'what is the rating and what would change it', rating triggers and what the agency "
        "said about strengths/weaknesses. `agency` filters CARE/ICRA/CRISIL, `section` one of rationale, drivers, "
        "strengths, weaknesses, sensitivities, liquidity, outlook. A company without a fetched rationale returns "
        "found=false with the coverage it does hold; the rating announcement in pilot3_docs is separate."
    ),
    annotations=_RO,
)
def pilot3_ratings(symbol: str, as_of: str | None = None, agency: str | None = None,
                   section: str | None = None, limit: int = 20) -> dict[str, Any]:
    return _safe(lambda: _ratings.ratings(symbol, as_of=as_of, agency=agency, section=section, limit=limit))


@server.tool(
    name="pilot3_sql",
    description=(
        "Bounded read-only SELECT/WITH over the pilot3 database (REALITY_PILOT3_DB names another build; limit "
        "enforced, default 100, max 500). Tables: company (every company the build covers -- count it, never assume "
        "a sample), doc, doc_page, doc_alias, kpi_series, fin_annual_line, fin_quarter_xbrl, fin_quarter_printed, "
        "ratio_panel, formula, valuation_daily, shp_category, shp_holder, shp_pledge, share_capital, dividend_event, "
        "price_delivery, bulk_block_deal, insider_trade, index_price, transcript_statement, guidance, rating_event, concentration, related_party_txn. Views: "
        "fin_quarter_current (the one preferred financial line per symbol, fiscal_period, basis and line_item now). "
        "Financial figures: read fin_quarter_current, or add preferred_from / preferred_to on fin_quarter_xbrl and "
        "fin_quarter_printed (preferred when preferred_from <= '<day>' and (preferred_to IS NULL or preferred_to > "
        "'<day>')), or call pilot3_fin -- the same election, so plain SQL gets the same number. The raw quarter "
        "tables hold every filing's printing of a line, so summing them counts a restatement and its original twice. "
        "Every fact table has symbol and known_at: pass as_of='<day>' for any dated question -- every table with "
        "known_at, and doc_page through its document, then shows only rows known by that day (doc_page_fts hits must "
        "be joined to doc_page). "
        "Text cells are cut at max_chars (default 400, hard cap 8000): pass max_chars=8000 when the answer needs "
        "long page text, a whole paragraph or a full quote."
    ),
    annotations=_RO,
)
def pilot3_sql(query: str, limit: int = 100, max_chars: int = 400, as_of: str | None = None) -> dict[str, Any]:
    return _safe(lambda: _p3.sql(query, limit=limit, max_chars=max_chars, as_of=as_of))
# --- end lookups: pilot3 ---


# --- calculator (T-072: a worker's head sum and its ten-times unit slip were 31 of the 120 misses) ---
import calc as _calc  # noqa: E402  (co-located module, same import style)


@server.tool(
    name="pilot3_calc",
    description=(
        "Arithmetic you can trust: USE THIS FOR EVERY NUMBER YOU DID NOT COPY STRAIGHT FROM A TOOL ROW. A head "
        "sum, a ratio, a margin, a growth, a crore/million conversion and a market cap are all this tool's job -- "
        "31 of the 120 answer misses in the 600-answer run were a wrong sum or a ten-times unit slip in a number "
        "the data had right. expression: + - * / ** and parentheses over named inputs, plus sum(a, b, ...), "
        "avg(...), min(...), max(...), round(x, 2). inputs: {name: value with an optional unit}, e.g. "
        "{\"pat\": \"493 crore\", \"shares\": \"622.39 crore shares\", \"rate\": \"9 percent\"}; units are rupees "
        "(bare number = plain; a currency prefix with no scale word is rupees, so \"Rs 349.45\" is 349.45 rupees and "
        "\"Rs 5 crore\" is still 5 crore), crore, lakh, lakh crore, million, billion, shares/count, percent. "
        "Answers come "
        "back exact (value, exact fraction) with unit: money also in rupees, crore, lakh crore and Indian digit "
        "grouping; percent also in bps; one percentage minus another comes back in percentage points (pp) with the relative change beside it -- write 'pp', never '%', for such a move. A unit mistake is an error with a message, never a number: subtracting "
        "shares from rupees or multiplying two rupee amounts fails. Check the crore/lakh_crore field before you "
        "write a number into an answer."
    ),
    annotations=_RO,
)
def pilot3_calc(expression: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return _safe(lambda: _calc.evaluate(expression, inputs))


# --- named calc catalog (T-135): the standard investor formulas, run by code, refusing mismatched periods ---
import calc_catalog as _catalog  # noqa: E402


@server.tool(
    name="pilot3_calc_catalog",
    description=(
        "Named investor formulas, run by code: call this instead of building the formula yourself. name=list "
        "prints every id with its inputs. Ids: GROWTH, TTM_SUM, TTM_GROWTH (refuses a TTM against a fiscal year it "
        "overlaps), Q_FROM_CUMULATIVE (FY-9M=Q4, 9M-H1=Q3, H1-Q1=Q2), SHARE, CONTRIBUTION_TO_INCREASE, "
        "CASH_CONVERSION (OCF/PAT and OCF/EBITDA), INCREMENTAL_ROCE, RANGE_POSITION, FAIR_PB, IMPLIED_ROE, "
        "IMPLIED_GROWTH_PE, ANNUALISE (always labelled annualised), SAME_SPAN_GROWTH (refuses a six-month balance "
        "change against year-on-year revenue), PROFIT_BRIDGE_MARGIN (EBITDA margin needed for a PAT target, after "
        "tax, depreciation and finance cost). inputs: {name: value with unit}, e.g. {\"now\": \"22,067 crore\", "
        "\"before\": \"19,332 crore\"}. Price maths (RSI, gaps, volume spikes, range, moving averages) is "
        "pilot3_tech."
    ),
    annotations=_RO,
)
def pilot3_calc_catalog(name: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return _safe(lambda: _catalog.run({"name": name, "inputs": inputs or {}}))


# --- project context (T-125: rulings and live state are served on demand, not pasted into prompts) ---
def _project() -> Any:
    from reality_engine.scripts import project_context

    return project_context


@server.tool(
    name="project_rules",
    description=(
        "Shivam's binding rulings for this project; call before deciding scope, briefing a worker "
        "or reporting. No topic returns the section index (name and the first 120 characters of "
        "every bullet); a topic returns, whole, every bullet that contains all of its words (3+ "
        "characters, case-insensitive) with its section; a miss returns that index and found=false."
    ),
    annotations=_RO,
)
def project_rules(topic: str | None = None) -> dict[str, Any]:
    return _safe(lambda: _project().rules(topic, root=_REPO_ROOT))


@server.tool(
    name="project_state",
    description=(
        "The live project state and next action: tasks/STATE.md sections, '## Now' and "
        "'## Next action' always whole, the other sections up to 6000 characters, plus the ticket "
        "card. Use it for the current step, blockers and running jobs before acting on them."
    ),
    annotations=_RO,
)
def project_state() -> dict[str, Any]:
    return _safe(lambda: _project().state(_REPO_ROOT))


def _warm_data() -> None:
    # 2026-10-24: warming before server.run delayed the initialize reply past the client's version probe (6.5 s
    # cold start); warm in the background so the handshake is answered at once. Tools still lazy-open on first use.
    def run() -> None:
        try:
            core.warm()
            catalog_mod.get_catalog()  # load the cache before the first model call
        except Exception:
            pass
    threading.Thread(target=run, name="reality-data-warm", daemon=True).start()


def _lifecycle(event: str) -> None:
    # one line per start/exit, so a dropped session shows whether the client closed stdin or the server died
    try:
        import datetime
        log = SERVER_DIR / ".cache" / "lifecycle.log"
        log.parent.mkdir(exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} pid={os.getpid()} {event}\n")
    except Exception:
        pass


def main() -> int:
    _lifecycle("start")
    _warm_data()
    _warm_search()
    reason = "stdin closed by client"
    try:
        server.run("stdio")
    except KeyboardInterrupt:
        reason = "KeyboardInterrupt"
        return 0
    except BrokenPipeError:
        reason = "BrokenPipeError"
        return 0
    except BaseException as exc:
        reason = f"crash {type(exc).__name__}: {exc}"
        raise
    finally:
        _lifecycle(f"exit ({reason})")
        core.close_all()
        _p3.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
