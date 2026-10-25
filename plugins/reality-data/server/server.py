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

ROUTE BY QUESTION SHAPE FIRST — one call each, before any sql():
- delivery / delivered quantity on a date (NSE+BSE) -> delivery(symbol, dates)
- high / low / YTD extreme -> price_extreme(symbol, start, end, kind)
- promoter holding, share count -> holding(symbol, as_of)
- "what documents / latest deck / latest transcript" -> docs(symbol, doc_type, date_from, date_to)
- "page N of the <date> presentation" -> doc_page(symbol, date, page)
- "what did they say about X in the <date> transcript/deck/AR" -> doc_find(symbol, terms, doc_type, date)
- financial numbers, segments, guidance -> facts(symbol, kind, period); OHLCV range -> price(...)
Symbols, BSE codes, ISINs and names all resolve inside each tool. A {"found": false} answer lists what was checked and the nearest documents: follow its hint, then say NOT IN DATA; do not hand-write SQL over the same tables. Filing dates can be the evening of, or a day after, the date a user names. Exact share counts come from filings; XBRL paid-up capital / face value is rounded.

Use catalog() when you need the map: every database, table, one-line description, key columns, row count and date coverage. For a specific company go straight to the data tools; resolve is optional because price/facts resolve the symbol themselves. resolve(query) turns a symbol, company name or ISIN into the canonical identity (ISIN history included). price(symbol, start, end=None, adjusted=False) returns OHLCV, delivery quantity/percent and traded value; close is raw unless adjusted=True. facts(symbol, kind=None, period=None) returns annual-report segments/financials/KPIs, XBRL results, deck figures and concall guidance in one call; kind accepts segments, financials, kpis, guidance, results, deck, concall, ar, or free text; period accepts FY25, Q4FY26 or a date. search_docs(query, symbol=None, doc_types=None, date_from=None, date_to=None, top_k=10, as_of=None) returns text passages (as_of drops documents published after that date, and undated ones); sql(query, db) is a bounded read-only escape hatch.

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
        "Return the whole data map in one call: every database, its tables, one-line "
        "descriptions, key columns, row counts and date coverage. Curated descriptions "
        "are merged when catalog_descriptions.yaml is present. refresh=true re-introspects "
        "the live files (slower)."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def catalog(refresh: bool = False) -> dict[str, Any]:
    return _safe(lambda: catalog_mod.get_catalog(refresh=refresh))


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
        "Structured fundamentals, segments and KPIs for a company from ar_facts, "
        "results_xbrl, deck_figures and concall_facts. kind: segments | financials | "
        "kpis | guidance | results | deck | concall | ar | free text. period: FY25, "
        "Q4FY26, 2025-03-31, or omitted. Each fact carries source, doc id, page, period, "
        "basis, quote and URL/local path where available."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def facts(symbol: str, kind: str | None = None, period: str | None = None,
          limit: int = 80) -> dict[str, Any]:
    return _safe(lambda: core.facts(symbol, kind=kind, period=period, limit=limit))


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
        "(reported by the search module's warm/status). Results are quarantine-filtered."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def search_docs(query: str, symbol: str | None = None, doc_types: list[str] | None = None,
                date_from: str | None = None, date_to: str | None = None,
                top_k: int = 10, as_of: str | None = None) -> dict[str, Any]:
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
                         date_to=date_to, top_k=top, as_of=as_of)
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
        "results_xbrl, bse_announcements. Single statement only, row-limited (default "
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
        "date_from, date_to. Answers 'what is the latest X'."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None,
         date_to: str | None = None, limit: int = 20) -> dict[str, Any]:
    return _safe(lambda: _lookups_docs.docs(symbol, doc_type=doc_type, date_from=date_from,
                                            date_to=date_to, limit=limit))


@server.tool(
    name="doc_page",
    description=(
        "Pick the document of the requested type nearest a date (±3 days, says which and why) "
        "and return one page's full text plus the facts extracted on that page and the page "
        "count ('page 21 of 79'). Text comes from the stored chunks, the local PDF (PyMuPDF) "
        "or a Drive fetch by sha256 (fetched=true when downloaded); for decks whose PDF is "
        "gone it falls back to the stored page extraction."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def doc_page(symbol: str, date: str, page: int, doc_type: str | None = None) -> dict[str, Any]:
    return _safe(lambda: _lookups_docs.doc_page(symbol, date, page, doc_type=doc_type))


@server.tool(
    name="doc_find",
    description=(
        "Lexical search (LIKE over bounded per-document rows, plus deck PDF text) inside one "
        "company's documents, optionally restricted to one doc_type and one filing date "
        "(±3 days). Returns passages with doc type, date, page (when the page is in the text) "
        "and the exact quote. This is the 'what did they say about X in the Y transcript' tool."
    ),
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
)
def doc_find(symbol: str, terms: str, doc_type: str | None = None, date: str | None = None,
             top_k: int = 8) -> dict[str, Any]:
    return _safe(lambda: _lookups_docs.doc_find(symbol, terms, doc_type=doc_type, date=date,
                                                top_k=top_k))
# --- end lookups: docs ---


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
