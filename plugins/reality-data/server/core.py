"""Data access core for the reality-data MCP server.

Read-only by construction: the DuckDB snapshot is opened with ``read_only=True``
and every SQLite connection uses ``mode=ro`` plus ``PRAGMA query_only=ON``.
Connections are opened once and kept warm; ``sql()`` uses a guarded, bounded
escape hatch only.

Sources
-------
* ``truth_duckdb``       point-in-time snapshot: identity, prices, events, docs
* ``ar_facts``           annual-report facts (indexed by isin)
* ``results_xbrl``       XBRL results facts (indexed by isin/file)
* ``deck_figures``       investor-presentation facts (isin -> sha256 -> facts)
* ``concall_facts``      concall guidance/KPI items (indexed by isin)
* ``equity_intelligence`` search layer, quarantine keys, corporate document URLs
* ``bse_announcements``  BSE announcement feed
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import duckdb  # type: ignore
except ImportError:  # pragma: no cover - the pinned interpreter has duckdb
    duckdb = None

# ``REALITY_DATA_ROOT`` is the data directory (the search_docs.py contract);
# ``REALITY_DATA_REPO_ROOT`` is the checkout root.  Both default from this file,
# so the server also works with no environment at all.
ROOT = Path(os.environ.get("REALITY_DATA_REPO_ROOT") or Path(__file__).resolve().parents[3])
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or ROOT / "reality_engine" / "data")

try:
    from reality_engine.db.readonly import QueryTimeout, connect_ro
except ModuleNotFoundError:  # a script launch may not have the checkout root on sys.path
    sys.path.append(str(ROOT))
    from reality_engine.db.readonly import QueryTimeout, connect_ro

READ_TIMEOUT_S = 30.0

DB_FILES: dict[str, Path] = {
    "equity_intelligence": DATA / "equity_intelligence.db",
    "ar_facts": DATA / "ar_facts.db",
    "deck_figures": DATA / "deck_figures.db",
    "concall_facts": DATA / "concall_facts.db",
    "results_xbrl": DATA / "results_xbrl.db",
    "bse_announcements": DATA / "bse_announcements.db",
}
DUCK_KEY = "truth_duckdb"
DB_ALIASES = {
    "truth": DUCK_KEY, "snapshot": DUCK_KEY, "duck": DUCK_KEY, "duckdb": DUCK_KEY,
    "truth_duckdb": DUCK_KEY, "main": "equity_intelligence", "equity": "equity_intelligence",
    "equity_intelligence": "equity_intelligence", "ar": "ar_facts", "ar_facts": "ar_facts",
    "deck": "deck_figures", "deck_figures": "deck_figures", "concall": "concall_facts",
    "concall_facts": "concall_facts", "results": "results_xbrl", "results_xbrl": "results_xbrl",
    "bse": "bse_announcements", "bse_announcements": "bse_announcements",
}

KIND_ALIASES = {
    "segment": "segments", "segments": "segments", "segment revenue": "segments",
    "segmental": "segments", "revenue mix": "segments",
    "financial": "financials", "financials": "financials", "fundamental": "financials",
    "fundamentals": "financials", "pl": "financials", "pnl": "financials",
    "kpi": "kpis", "kpis": "kpis", "operational": "kpis",
    "guidance": "guidance", "outlook": "guidance", "target": "guidance",
    "result": "results", "results": "results", "xbrl": "results", "quarterly": "results",
    "annual report": "ar", "annual_report": "ar", "ar": "ar",
    "deck": "deck", "decks": "deck", "presentation": "deck", "investor presentation": "deck",
    "concall": "concall", "con-call": "concall", "transcript": "concall",
}
SOURCE_FOR_KIND = {
    "segments": ("ar", "results", "deck"),
    "financials": ("ar", "results", "deck"),
    "results": ("results",),
    "kpis": ("ar", "deck", "concall"),
    "guidance": ("ar", "deck", "concall"),
    "ar": ("ar",), "deck": ("deck",), "concall": ("concall",),
    None: ("ar", "results", "deck", "concall"),
}
NOTABLE_AR = (
    "(lower(category) LIKE '%segment%' OR lower(item) LIKE '%segment%' "
    "OR lower(item) LIKE '%revenue%' OR lower(item) LIKE '%profit%' "
    "OR lower(item) LIKE '%ebitda%' OR lower(item) LIKE '%margin%' "
    "OR lower(item) LIKE '%eps%' OR lower(item) LIKE '%capacity%' "
    "OR lower(item) LIKE '%volume%' OR lower(item) LIKE '%guidance%' "
    "OR lower(category) LIKE '%financial%' OR lower(category) LIKE '%ratio%')"
)
RESULT_CONCEPTS = (
    "RevenueFromOperations", "Income", "OtherIncome", "ProfitBeforeTax",
    "ProfitLossForPeriod", "ProfitOrLossAttributableToOwnersOfParent",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "PaidUpValueOfEquityShareCapital", "FaceValueOfEquityShareCapital",
)
SEGMENT_CONCEPTS = (
    "SegmentRevenue", "SegmentRevenueFromOperations", "SegmentProfitBeforeTax",
    "SegmentProfitLossBeforeTaxAndFinanceCosts", "SegmentAssets", "SegmentLiabilities",
    "NetSegmentAssets", "NetSegmentLiabilities",
)

_lock = threading.RLock()
_duck_conn = None
_sqlite_conns: dict[str, sqlite3.Connection] = {}
_quarantine: dict[str, set[str]] | None = None
_doc_url_cache: dict[int, str | None] = {}


class DataError(Exception):
    """Expected tool failure: a stable code and a human-readable message."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# Paths and connections
# ---------------------------------------------------------------------------
def snapshot_path() -> Path:
    override = os.environ.get("REALITY_DATA_SNAPSHOT")
    if override:
        return Path(override)
    return _cached_snapshot_path()


@functools.lru_cache(maxsize=1)
def _cached_snapshot_path() -> Path:
    # Glob over the snapshots directory is ~0.12 s; every provenance() call
    # would otherwise repeat it (doc_find calls provenance up to 3 times).
    candidates = sorted((DATA / "snapshots").glob("truth_*.duckdb"))
    if not candidates:
        raise DataError("snapshot_missing", f"no truth_*.duckdb under {DATA / 'snapshots'}")
    return max(candidates, key=lambda p: (p.name, p.stat().st_mtime))


def db_path(key: str) -> Path:
    if key == DUCK_KEY:
        return snapshot_path()
    try:
        return DB_FILES[key]
    except KeyError:
        raise DataError("unknown_db", f"unknown db {key!r}; choose from {sorted(DB_ALIASES)}")


def connect_duck():
    global _duck_conn
    with _lock:
        if _duck_conn is None:
            if duckdb is None:
                raise DataError("duckdb_missing", "duckdb is not installed for this interpreter")
            path = snapshot_path()
            _duck_conn = duckdb.connect(str(path), read_only=True)
        return _duck_conn


def connect_sqlite(key: str):
    with _lock:
        con = _sqlite_conns.get(key)
        if con is not None:
            return con
        path = db_path(key)
        if not path.exists():
            raise DataError("db_missing", f"{key} database missing: {path}")
        con = connect_ro(path, timeout_s=READ_TIMEOUT_S, check_same_thread=False,
                         cache_size_kib=-131072)
        con.row_factory = sqlite3.Row
        for pragma in ("PRAGMA busy_timeout=30000", "PRAGMA mmap_size=268435456"):
            try:
                con.execute(pragma)
            except sqlite3.DatabaseError:
                pass
        _sqlite_conns[key] = con
        return con


def warm() -> dict[str, Any]:
    """Open every read-only connection and load the quarantine set."""
    opened = []
    for key in [DUCK_KEY, *DB_FILES]:
        if key == DUCK_KEY:
            connect_duck().execute("select 1").fetchone()
        else:
            if db_path(key).exists():
                connect_sqlite(key).execute("select 1").fetchone()
        opened.append(key)
    q = quarantine()
    return {"warmed": opened, "quarantine_tables": {k: len(v) for k, v in q.items() if v}}


def close_all() -> None:
    global _duck_conn, _quarantine
    with _lock:
        if _duck_conn is not None:
            try:
                _duck_conn.close()
            except Exception:
                pass
            _duck_conn = None
        for con in _sqlite_conns.values():
            try:
                con.close()
            except Exception:
                pass
        _sqlite_conns.clear()
        _quarantine = None


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def _jsonable(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


def _run_duck(sql: str, params: Sequence[Any] = (), timeout: float = 15.0) -> tuple[list[str], list[tuple]]:
    con = connect_duck()
    with _lock:
        timer = threading.Timer(timeout, con.interrupt)
        timer.daemon = True
        timer.start()
        try:
            cur = con.execute(sql, params)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            return columns, [tuple(_jsonable(v) for v in row) for row in rows]
        except Exception as exc:
            if "Interrupt" in type(exc).__name__ or "interrupted" in str(exc).lower():
                raise DataError("query_timeout", f"query exceeded {timeout:.1f}s")
            raise
        finally:
            timer.cancel()


def _run_sqlite(key: str, sql: str, params: Sequence[Any] = (), timeout: float = 15.0) -> list[sqlite3.Row]:
    con = connect_sqlite(key)
    with _lock:
        con.set_timeout(timeout)
        try:
            return con.execute(sql, params).fetchall()
        except QueryTimeout as exc:
            raise DataError("query_timeout", str(exc)) from exc
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise DataError("query_timeout", f"query exceeded {timeout:.1f}s") from exc
            raise
        finally:
            con.set_timeout(READ_TIMEOUT_S)


def _in_clause(values: Iterable[str]) -> tuple[str, list[str]]:
    vals = [str(v) for v in dict.fromkeys(values) if v]
    if not vals:
        return "(NULL)", []
    return "(" + ",".join("?" for _ in vals) + ")", vals


def provenance(db_key: str, tables: Sequence[str], **extra: Any) -> dict[str, Any]:
    path = db_path(db_key)
    out = {
        "db": db_key,
        "path": str(path),
        "tables": list(tables),
        "read_only": True,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if db_key == DUCK_KEY:
        out["snapshot"] = path.name
        out["snapshot_built"] = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Quarantine (AGENTS.md rule 13)
# ---------------------------------------------------------------------------
def quarantine() -> dict[str, set[str]]:
    """Materialized key set from ``substrate_quarantine`` (empty if absent)."""
    global _quarantine
    with _lock:
        if _quarantine is not None:
            return _quarantine
        out: dict[str, set[str]] = {}
        try:
            rows = connect_sqlite("equity_intelligence").execute(
                "select table_name, row_key from substrate_quarantine"
            ).fetchall()
            for row in rows:
                out.setdefault(str(row[0]), set()).add(str(row[1]))
        except (sqlite3.DatabaseError, DataError):
            out = {}
        _quarantine = out
        return out


def quarantined_doc_ids() -> set[int]:
    ids = set()
    for key in quarantine().get("ar_facts", set()):
        try:
            ids.add(int(key))
        except ValueError:
            continue
    return ids


def _synthetic_isin(isin: str) -> bool:
    return str(isin or "").upper().startswith("INE_AUTO")


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------
_ID_COLS = ("isin, issuer, name, nse_symbol, bse_code, bse_symbol, bse_status, segment, "
            "nse_listing_date, first_trade, last_trade, last_seen_nse, last_seen_bse, in_master_companies")


def _identity_rows(where: str, params: Sequence[Any], limit: int = 20) -> list[dict[str, Any]]:
    sql = f"SELECT {_ID_COLS} FROM security_master WHERE {where} ORDER BY in_master_companies DESC, name LIMIT ?"
    cols, rows = _run_duck(sql, [*params, limit])
    return [dict(zip(cols, row)) for row in rows]


def _nse_row(where: str, params: Sequence[Any], limit: int = 10) -> list[dict[str, Any]]:
    cols, rows = _run_duck(
        f"SELECT symbol, isin, name, segment FROM nse_master WHERE {where} LIMIT ?", [*params, limit]
    )
    return [dict(zip(cols, row)) for row in rows]


def _bse_row(where: str, params: Sequence[Any], limit: int = 10) -> list[dict[str, Any]]:
    cols, rows = _run_duck(
        f"SELECT sc_code, isin, bse_symbol, name, status FROM bse_master WHERE {where} LIMIT ?", [*params, limit]
    )
    return [dict(zip(cols, row)) for row in rows]


def _fund_kind(name: str) -> str:
    return "etf" if "ETF" in str(name or "").upper() else "mf"


def _fund_matches(query: str) -> list[dict[str, Any]]:
    """ETF / mutual-fund identity from etf_master, fund_nav and BSE INF* codes.

    Their INF* ISINs never reach ``security_master``, so the equity path cannot see
    them.  Every match already carries ``kind`` (etf|mf); equity matches default to
    ``equity`` in ``_merge_match``.
    """
    qu = query.strip().upper()
    out: list[dict[str, Any]] = []

    def push(isin, symbol, name, kind, match_type, score, first="", last="", code=""):
        if not isin or _synthetic_isin(str(isin)):
            return
        out.append({
            "isin": str(isin), "name": name or "", "nse_symbol": symbol or "",
            "bse_symbol": symbol or "", "bse_code": str(code or ""), "segment": kind.upper(),
            "status": "", "listing_date": first or "", "first_trade": first or "",
            "last_trade": last or "", "last_seen_nse": last or "", "last_seen_bse": last or "",
            "aliases": [], "isin_history": [], "isin_changed": False,
            "match_type": match_type, "score": score, "kind": kind,
        })

    # BSE master covers exchange-listed ETFs and funds (INF* ISINs only).
    try:
        _, rows = _run_duck(
            "SELECT sc_code, isin, bse_symbol, name FROM bse_master "
            "WHERE isin LIKE 'INF%' AND (upper(bse_symbol) = ? OR upper(isin) = ? OR sc_code = ? "
            "OR upper(COALESCE(name, '')) LIKE ?) LIMIT 10",
            [qu, qu, query.strip(), f"%{qu}%"],
        )
    except DataError:
        rows = []
    for sc, isin, sym, name in rows:
        score = (98 if str(isin).upper() == qu else
                 95 if str(sym).upper() == qu else
                 93 if str(sc) == query.strip() else 66)
        push(isin, sym, name, _fund_kind(name), "bse_master", score, code=sc)

    # ETF master (equity_intelligence) has the trading symbol + scheme name.
    try:
        etf_rows = _run_sqlite(
            "equity_intelligence",
            "SELECT isin, symbol, scheme_name, first_date, last_date FROM etf_master "
            "WHERE upper(isin) = ? OR upper(symbol) = ? OR upper(COALESCE(scheme_name, '')) LIKE ? LIMIT 10",
            [qu, qu, f"%{qu}%"],
        )
    except sqlite3.DatabaseError:
        etf_rows = []
    for row in etf_rows:
        score = (98 if str(row["isin"]).upper() == qu else
                 95 if str(row["symbol"]).upper() == qu else
                 90 if str(row["scheme_name"] or "").upper() == qu else 68)
        push(row["isin"], row["symbol"], row["scheme_name"], "etf", "etf_master", score,
             row["first_date"], row["last_date"])

    # Open-ended MF / ETF scheme names + scheme codes (AMFI feed).  A single OR
    # over 322k rows is slow, so pick the narrow predicate for the query shape.
    # Only ask when nothing else matched: fund_nav has no index on scheme_code, and
    # an equity code / exchange symbol already short-circuits on its own match.
    want_nav = not out
    if want_nav:
        if qu.isdigit():
            nav_where, nav_params = "scheme_code = ?", [query.strip()]
        elif qu.startswith("INF"):
            nav_where, nav_params = "upper(isin) = ?", [qu]
        else:
            nav_where, nav_params = ("upper(COALESCE(scheme_name, '')) LIKE ? OR upper(isin) = ?",
                                     [f"%{qu}%", qu])
        try:
            nav_rows = _run_sqlite(
                "equity_intelligence",
                f"SELECT isin, scheme_code, scheme_name FROM fund_nav WHERE {nav_where} LIMIT 20",
                nav_params,
            )
        except sqlite3.DatabaseError:
            nav_rows = []
        for row in nav_rows:
            name = row["scheme_name"] or ""
            score = (98 if str(row["isin"]).upper() == qu else
                     92 if str(row["scheme_code"] or "") == query.strip() else
                     90 if name.upper() == qu else 66)
            push(row["isin"], "", name, _fund_kind(name), "fund_nav", score,
                 code=row["scheme_code"])

    return out


def _history(isin: str = "", symbol: str = "") -> list[dict[str, Any]]:
    clauses, params = [], []
    if isin:
        clauses.append("isin = ?")
        params.append(isin)
    if symbol:
        clauses.append("upper(symbol) = ?")
        params.append(symbol.upper())
    if not clauses:
        return []
    cols, rows = _run_duck(
        "SELECT exchange, symbol, isin, first_date, last_date, n_days FROM symbol_isin_history "
        f"WHERE {' OR '.join(clauses)} ORDER BY first_date",
        params,
    )
    return [dict(zip(cols, row)) for row in rows]


def _merge_match(base: dict[str, Any], match_type: str, score: int) -> dict[str, Any]:
    isin = str(base.get("isin") or "")
    name = base.get("name") or base.get("company_name") or ""
    nse = base.get("nse_symbol") or base.get("symbol") or ""
    bse = base.get("bse_symbol") or ""
    hist = _history(isin, nse or bse)
    aliases = sorted({h["symbol"] for h in hist if h.get("symbol")})
    isins = sorted({h["isin"] for h in hist if h.get("isin")} | ({isin} if isin else set()))
    return {
        "isin": isin,
        "name": name,
        "nse_symbol": nse,
        "bse_symbol": bse,
        "bse_code": str(base.get("bse_code") or base.get("sc_code") or ""),
        "segment": base.get("segment") or "",
        "status": base.get("bse_status") or base.get("status") or "",
        "listing_date": base.get("nse_listing_date") or "",
        "first_trade": base.get("first_trade") or "",
        "last_trade": base.get("last_trade") or "",
        "last_seen_nse": base.get("last_seen_nse") or "",
        "last_seen_bse": base.get("last_seen_bse") or "",
        "aliases": aliases,
        "isin_history": hist,
        "isin_changed": len(isins) > 1,
        "match_type": match_type,
        "score": score,
        "kind": base.get("kind") or "equity",
    }


def resolve(query: str) -> dict[str, Any]:
    """Symbol, company name or ISIN -> company identity, ISIN-history aware."""
    q = (query or "").strip()
    if not q:
        raise DataError("bad_query", "resolve() needs a symbol, company name or ISIN")
    if len(q) > 200:
        raise DataError("bad_query", "query is longer than 200 characters")
    matches: dict[str, dict[str, Any]] = {}

    def add(base: dict[str, Any], match_type: str, score: int) -> None:
        m = _merge_match(base, match_type, score)
        if not m["isin"] or _synthetic_isin(m["isin"]):
            return
        old = matches.get(m["isin"])
        if old is None or m["score"] > old["score"]:
            matches[m["isin"]] = m

    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", q.upper()):
        for row in _identity_rows("upper(isin) = ?", [q.upper()]):
            add(row, "isin", 100)

    for row in _identity_rows("upper(nse_symbol) = ? OR upper(bse_symbol) = ?", [q.upper(), q.upper()]):
        add(row, "symbol", 95)

    for row in _identity_rows("upper(name) = ?", [q.upper()]):
        add(row, "name", 90)

    # Old symbol: symbol_isin_history maps it to its ISIN(s).
    for h in _history(symbol=q):
        for row in _identity_rows("upper(isin) = ?", [str(h["isin"]).upper()]):
            add(row, "symbol_history", 85)

    if not any(m["score"] >= 85 for m in matches.values()):
        like = f"%{q.upper()}%"
        for row in _identity_rows(
            "(upper(name) LIKE ? OR upper(nse_symbol) LIKE ? OR upper(bse_symbol) LIKE ?) "
            "AND isin NOT LIKE 'INE_AUTO%'",
            [like, like, like],
            20,
        ):
            add(row, "fuzzy", 70)

    # ETF / mutual funds: their INF* ISINs live in etf_master, fund_nav and the
    # BSE master, never in security_master, so add them as first-class matches.
    for fund in _fund_matches(q):
        old = matches.get(fund["isin"])
        if old is None or fund["score"] > old["score"]:
            matches[fund["isin"]] = fund

    # Fallbacks for names that exist only in an exchange master.
    if not matches:
        for row in _nse_row("upper(symbol) = ? OR upper(name) LIKE ? OR upper(isin) = ?", [q.upper(), like, q.upper()]):
            add(row, "nse_master", 60)
        for row in _bse_row("upper(bse_symbol) = ? OR upper(name) LIKE ? OR upper(isin) = ?", [q.upper(), like, q.upper()]):
            add(row, "bse_master", 55)
    if not matches:
        for h in _history(symbol=q):
            isin = str(h.get("isin") or "")
            if isin and not _synthetic_isin(isin):
                matches[isin] = {
                    "isin": isin, "name": "", "nse_symbol": h.get("symbol") or q.upper(),
                    "bse_symbol": "", "bse_code": "", "segment": "", "status": "history_only",
                    "aliases": [h.get("symbol") or ""], "isin_history": _history(isin=isin),
                    "isin_changed": False, "match_type": "symbol_history", "score": 50,
                    "kind": "equity",
                }

    ranked = sorted(matches.values(), key=lambda m: (-m["score"], m["name"]))
    return {
        "query": q,
        "count": len(ranked),
        "ambiguous": len(ranked) > 1,
        "matches": ranked[:10],
        "provenance": provenance(
            DUCK_KEY, ["security_master", "symbol_isin_history", "nse_master", "bse_master"],
            funds=provenance("equity_intelligence", ["etf_master", "fund_nav"]),
        ),
    }


def resolve_one(query: str) -> dict[str, Any]:
    result = resolve(query)
    if not result["matches"]:
        raise DataError("not_found", f"no listed company matches {query!r}")
    return result["matches"][0]


def _identity_isins(identity: dict[str, Any]) -> list[str]:
    vals = [identity.get("isin")] + [h.get("isin") for h in identity.get("isin_history", [])]
    return [str(v) for v in dict.fromkeys(vals) if v and not _synthetic_isin(str(v))]


def _identity_symbols(identity: dict[str, Any], query: str = "") -> list[str]:
    vals = [identity.get("nse_symbol"), identity.get("bse_symbol"), query]
    vals += [h.get("symbol") for h in identity.get("isin_history", [])]
    return [str(v).upper() for v in dict.fromkeys(vals) if v]


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------
def _parse_date(value: str | dt.date | None, field: str) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        raise DataError("bad_date", f"{field} must be YYYY-MM-DD, got {value!r}")


def _price_table(table: str, isins: list[str], symbols: list[str], start: dt.date, end: dt.date, limit: int):
    isin_clause, isin_params = _in_clause(isins)
    sym_clause, sym_params = _in_clause(symbols)
    where = []
    params: list[Any] = []
    if isins:
        where.append(f"isin IN {isin_clause}")
        params.extend(isin_params)
    if symbols:
        where.append(f"upper(symbol) IN {sym_clause}")
        params.extend(sym_params)
    if not where:
        return [], []
    cols, rows = _run_duck(
        f"SELECT * FROM {table} WHERE ({' OR '.join(where)}) AND date >= ? AND date <= ? "
        "ORDER BY date LIMIT ?",
        [*params, start, end, limit + 1],
    )
    return cols, [dict(zip(cols, row)) for row in rows]


def price(symbol: str, start: str, end: str | None = None, adjusted: bool = False) -> dict[str, Any]:
    """OHLCV, delivery quantity/percent and traded value for one date range."""
    identity = resolve_one(symbol)
    start_d = _parse_date(start, "start")
    end_d = _parse_date(end, "end") if end else start_d
    if start_d is None or end_d is None:
        raise DataError("bad_date", "start is required")
    if end_d < start_d:
        raise DataError("bad_range", f"end {end_d} is before start {start_d}")
    if (end_d - start_d).days > 3660:
        raise DataError("bad_range", "date range is longer than 10 years; narrow it")

    isins = _identity_isins(identity)
    symbols = _identity_symbols(identity, symbol)
    chosen_table = ""
    rows: list[dict[str, Any]] = []
    for table, exchange in (("px_nse_adj", "NSE"), ("px_bse_adj", "BSE"),
                            ("px_nse", "NSE"), ("px_bse", "BSE")):
        _, candidate = _price_table(table, isins, symbols, start_d, end_d, 5000)
        if candidate:
            chosen_table, rows = table, candidate
            break
    exchange = "NSE" if chosen_table.startswith("px_nse") else "BSE" if chosen_table else ""

    out_rows = []
    for row in rows[:5000]:
        close = row.get("close")
        adj_close = row.get("adj_close")
        selected = (adj_close if adjusted and adj_close is not None else close)
        out_rows.append({
            "date": row.get("date"),
            "open": row.get("open"), "high": row.get("high"), "low": row.get("low"),
            "close": close, "prev_close": row.get("prev_close"),
            "adj_open": row.get("adj_open"), "adj_high": row.get("adj_high"),
            "adj_low": row.get("adj_low"), "adj_close": adj_close,
            "volume": row.get("volume"), "value_inr": row.get("value_inr"),
            "value_cr": round(row["value_inr"] / 1e7, 4) if row.get("value_inr") is not None else None,
            "num_trades": row.get("num_trades"),
            "deliverable_qty": row.get("deliverable_qty"),
            "delivery_pct": row.get("delivery_pct"),
            "cum_price_factor": row.get("cum_price_factor"),
            "cum_div_factor": row.get("cum_div_factor"),
            "tr_close": row.get("tr_close"),
            "selected_close": selected,
        })
    summary = None
    if out_rows:
        first, last = out_rows[0], out_rows[-1]
        a, b = first.get("selected_close"), last.get("selected_close")
        summary = {
            "from": first["date"], "to": last["date"],
            "first_close": a, "last_close": b,
            "change_pct": round((b / a - 1) * 100, 3) if a not in (None, 0) and b is not None else None,
            "rows": len(out_rows),
        }
    return {
        "symbol": identity["nse_symbol"] or symbol.upper(),
        "company": identity["name"],
        "isin": identity["isin"],
        "exchange": exchange,
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "adjusted": bool(adjusted),
        "close_used": "adj_close" if adjusted else "close",
        "rows": out_rows,
        "summary": summary,
        "provenance": provenance(DUCK_KEY, [chosen_table or "px_nse_adj", "px_bse_adj"],
                                 exchange=exchange, price_isin_history=identity["isin_history"]),
    }


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
def _normalise_kind(kind: str | None) -> str | None:
    if not kind:
        return None
    text = str(kind).strip().lower()
    return KIND_ALIASES.get(text, text)


def _period_tokens(period: str) -> tuple[set[int], str]:
    """Return candidate 4-digit years and a compact upper-case token."""
    p = str(period or "").strip().upper().replace(" ", "")
    years: set[int] = set()
    for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", p):
        years.add(int(m.group(1)))
    for m in re.finditer(r"FY'?(\d{2,4})", p):
        y = m.group(1)
        years.add(int("20" + y) if len(y) == 2 else int(y))
    return years, p


def _period_clause(period: str | None, columns: Sequence[str]) -> tuple[str, list[Any]]:
    """A permissive period filter for fact-period strings (FY25, Q4 FY26, dates)."""
    if not period:
        return "", []
    years, token = _period_tokens(period)
    clauses, params = [], []
    for col in columns:
        clauses.append(f"replace(upper(COALESCE({col},'')),' ','') LIKE ?")
        params.append(f"%{token}%")
    if years:
        for col in columns:
            for year in years:
                clauses.append(f"upper(COALESCE({col},'')) LIKE ?")
                params.append(f"%{year}%")
    return "(" + " OR ".join(clauses) + ")", params


def _ar_where(identity: dict[str, Any], kind: str | None, period: str | None,
              quarantine_ids: set[int], by_symbol: bool = False,
              doc_ids: Sequence[int] | None = None) -> tuple[str, list[Any], str]:
    isins = _identity_isins(identity)
    symbols = _identity_symbols(identity)
    if doc_ids is not None:
        # Indexed by ar_facts_doc(doc_id, piece); the only always-safe owner
        # path for old rows whose isin column is blank.
        clause, clause_params = _in_clause([int(i) for i in doc_ids])
        where = [f"doc_id IN {clause}"]
    elif by_symbol:
        clause, clause_params = _in_clause(symbols)
        where = [f"upper(symbol) IN {clause}"]
    else:
        clause, clause_params = _in_clause(isins)
        where = [f"isin IN {clause}"]
    params: list[Any] = list(clause_params)
    if quarantine_ids:
        q_clause, q_params = _in_clause([str(i) for i in quarantine_ids])
        where.append(f"CAST(doc_id AS TEXT) NOT IN {q_clause}")
        params.extend(q_params)
    kind_clause = ""
    if kind == "segments":
        kind_clause = ("(lower(category) LIKE '%segment%' OR lower(item) LIKE '%segment%' "
                       "OR lower(item) LIKE '%revenue mix%' OR lower(item) LIKE '%geographic%')")
    elif kind == "financials":
        kind_clause = ("(lower(category) LIKE '%financial%' OR lower(category) LIKE '%p_and_l%' "
                       "OR lower(category) LIKE '%balance%' OR lower(category) LIKE '%cash_flow%' "
                       "OR lower(category) LIKE '%ratio%' OR lower(item) LIKE '%revenue%' "
                       "OR lower(item) LIKE '%profit%' OR lower(item) LIKE '%ebitda%' "
                       "OR lower(item) LIKE '%margin%' OR lower(item) LIKE '%eps%' "
                       "OR lower(item) LIKE '%debt%')")
    elif kind == "kpis":
        kind_clause = ("(lower(category) LIKE '%capacity%' OR lower(category) LIKE '%sales_volume%' "
                       "OR lower(category) LIKE '%operational%' OR lower(category) LIKE '%ratio%' "
                       "OR lower(item) LIKE '%capacity%' OR lower(item) LIKE '%volume%' "
                       "OR lower(item) LIKE '%utilisation%')")
    elif kind == "guidance":
        kind_clause = ("(lower(category) LIKE '%guidance%' OR lower(item) LIKE '%guidance%' "
                       "OR lower(item) LIKE '%outlook%' OR lower(item) LIKE '%target%')")
    elif kind != "ar":
        kind_clause = NOTABLE_AR
    if kind_clause:
        where.append(kind_clause)
    p_clause, p_params = _period_clause(period, ("period", "fiscal_year"))
    if p_clause:
        where.append(p_clause)
        params.extend(p_params)
    return " AND ".join(where), params, "ar_facts"


def _fact_from_ar(row: sqlite3.Row, doc_path: str | None = None) -> dict[str, Any]:
    category = (row["category"] or "").lower()
    item = row["item"] or ""
    low = item.lower()
    if "segment" in category or "segment" in low or "revenue mix" in low:
        kind = "segments"
    elif "capacity" in category or "volume" in low or "utilisation" in low or "operational" in category:
        kind = "kpis"
    elif "guidance" in category or "guidance" in low or "outlook" in low:
        kind = "guidance"
    else:
        kind = "financials"
    value = row["value"]
    unit = row["unit"] or ""
    unit_low = unit.lower()
    if value is None:
        value_cr = None
    elif "lakh" in unit_low:
        value_cr = round(value / 100, 3)
    elif unit_low in ("inr", "rs", "rupees"):
        value_cr = round(value / 1e7, 3)
    elif "crore" in unit_low or unit_low in ("cr", "cr.", "crores"):
        value_cr = round(value, 3)
    else:
        value_cr = None
    return {
        "source": "ar_facts", "kind": kind, "item": item, "value": value,
        "value_raw": row["value_raw"], "unit": unit, "value_cr": value_cr,
        "period": row["period"], "period_end": row["fiscal_year"], "basis": row["basis"],
        "context": None, "doc_id": row["doc_id"], "doc_type": "ANNUAL_REPORT",
        "page": row["page"], "date": row["filed_at"], "url": None,
        "doc_path": doc_path, "quote": (row["quote"] or "")[:600],
        "known_at": row["filed_at"],
    }


def _lookup_doc_urls(doc_ids: Sequence[int]) -> dict[int, str]:
    ids = [int(i) for i in dict.fromkeys(doc_ids) if i is not None]
    missing = [i for i in ids if i not in _doc_url_cache]
    if missing:
        try:
            clause, params = _in_clause([str(i) for i in missing])
            rows = _run_sqlite("equity_intelligence",
                               f"SELECT id, source_url FROM corporate_documents WHERE id IN {clause}",
                               params, timeout=10.0)
            found = {int(r["id"]): r["source_url"] for r in rows}
            for i in missing:
                _doc_url_cache[i] = found.get(i)
        except (sqlite3.DatabaseError, DataError):
            for i in missing:
                _doc_url_cache[i] = None
    return {i: _doc_url_cache.get(i) for i in ids if _doc_url_cache.get(i)}


def _ar_symbol_doc_ids(identity: dict[str, Any], as_of: str | None = None) -> list[int]:
    """AR doc ids for a symbol, bounded by the PIT cut (ar_docs is 34k rows)."""
    symbols = _identity_symbols(identity)
    if not symbols:
        return []
    clause, params = _in_clause([s.upper() for s in symbols])
    sql = f"SELECT doc_id FROM ar_docs WHERE upper(symbol) IN {clause}"
    args: list[Any] = list(params)
    if as_of:
        sql += " AND COALESCE(filed_at,'') <> '' AND substr(filed_at,1,10) <= ?"
        args.append(str(as_of)[:10])
    try:
        return [int(r["doc_id"]) for r in _run_sqlite("ar_facts", sql, args, timeout=10.0)]
    except (sqlite3.DatabaseError, DataError):
        return []


def _ar_pit(as_of: str | None) -> tuple[str, list[Any]]:
    """SQL point-in-time guard on the AR row's own filing date."""
    if not as_of:
        return "", []
    return (" AND substr(COALESCE(filed_at,''),1,10) <> ''"
            " AND substr(filed_at,1,10) <= ?"), [str(as_of)[:10]]


def _facts_ar(identity: dict[str, Any], kind: str | None, period: str | None,
              limit: int, as_of: str | None = None) -> list[dict[str, Any]]:
    if kind in ("results", "deck", "concall"):
        return []
    select = ("SELECT doc_id, page, fiscal_year, filed_at, category, item, value_raw, value, unit, "
              "period, basis, quote FROM ar_facts ")
    order = ("ORDER BY CASE "
             "WHEN lower(category) LIKE '%segment%' OR lower(item) LIKE '%segment%' "
             "OR lower(item) LIKE '%revenue mix%' THEN 0 "
             "WHEN lower(item) LIKE '%revenue%' OR lower(item) LIKE '%profit%' "
             "OR lower(item) LIKE '%ebitda%' THEN 1 ELSE 2 END, "
             "fiscal_year DESC, page ASC, doc_id DESC LIMIT ?")
    where, params, _ = _ar_where(identity, kind, period, quarantined_doc_ids())
    pit, pit_params = _ar_pit(as_of)
    rows = _run_sqlite("ar_facts", select + f"WHERE {where}{pit} " + order,
                       [*params, *pit_params, limit])
    if not rows:
        # Old ISINs / rows whose isin column is blank: go through ar_docs so the
        # fact fetch stays on ar_facts_doc(doc_id, piece).  Previously this used
        # `upper(symbol) IN (...)`, a 32M-row scan (15.5 s on a miss).
        doc_ids = _ar_symbol_doc_ids(identity, as_of)
        if doc_ids:
            where, params, _ = _ar_where(identity, kind, period, quarantined_doc_ids(),
                                         doc_ids=doc_ids)
            rows = _run_sqlite("ar_facts", select + f"WHERE {where}{pit} " + order,
                               [*params, *pit_params, limit])
    docs = _lookup_doc_urls([r["doc_id"] for r in rows])
    out = []
    for row in rows:
        fact = _fact_from_ar(row)
        fact["url"] = docs.get(int(row["doc_id"])) if row["doc_id"] is not None else None
        out.append(fact)
    return out


def _fy_bounds(period: str) -> tuple[str, str] | None:
    years, _ = _period_tokens(period)
    if not years:
        return None
    year = max(years)
    return f"{year - 1}-04-01", f"{year}-03-31"


def _facts_results(identity: dict[str, Any], kind: str | None, period: str | None,
                   limit: int, as_of: str | None = None) -> list[dict[str, Any]]:
    if kind in ("ar", "deck", "concall"):
        return []
    isins = _identity_isins(identity)
    clause, params = _in_clause(isins)
    where = [f"fi.isin IN {clause}"]
    if period:
        years, _ = _period_tokens(period)
        if years:
            year = max(years)
            where.append("f.period_end BETWEEN ? AND ?")
            params.extend([f"{year - 1}-04-01", f"{year}-03-31"])
    if as_of:
        where.append("COALESCE(f.dissem_ts, f.broadcast_ts, f.filing_ts) <> ''"
                     " AND substr(COALESCE(f.dissem_ts, f.broadcast_ts, f.filing_ts),1,10) <= ?")
        params.append(str(as_of)[:10])
    sql = (
        "SELECT f.file, f.symbol, f.period_start, f.period_end, f.fy_start, f.consolidated, "
        "f.audited, f.xbrl_url, COALESCE(f.dissem_ts, f.broadcast_ts, f.filing_ts) AS known_at_src, fi.isin "
        "FROM filings f JOIN filings_isin fi ON fi.file = f.file "
        f"WHERE {' AND '.join(where)} ORDER BY f.period_end DESC LIMIT 25"
    )
    filings = _run_sqlite("results_xbrl", sql, params, timeout=15.0)
    if not filings:
        return []
    by_file = {r["file"]: r for r in filings}
    file_clause, file_params = _in_clause(list(by_file))
    concepts = SEGMENT_CONCEPTS if kind == "segments" else (
        RESULT_CONCEPTS + SEGMENT_CONCEPTS if kind in (None, "financials") else RESULT_CONCEPTS)
    concept_clause, concept_params = _in_clause(concepts)
    rows = _run_sqlite(
        "results_xbrl",
        "SELECT file, concept, context, period_start, period_end, instant, value, unit FROM facts "
        f"WHERE file IN {file_clause} AND concept IN {concept_clause} AND value IS NOT NULL "
        "ORDER BY CASE concept WHEN 'RevenueFromOperations' THEN 0 WHEN 'Income' THEN 1 "
        "WHEN 'ProfitBeforeTax' THEN 2 WHEN 'ProfitLossForPeriod' THEN 3 ELSE 4 END, "
        "context, file LIMIT ?",
        [*file_params, *concept_params, limit * 3],
        timeout=20.0,
    )
    out = []
    for row in rows:
        filing = by_file.get(row["file"])
        if not filing:
            continue
        context = row["context"] or ""
        if kind == "financials" and context not in ("FourD", "OneD", "OneI", ""):
            continue
        if kind == "segments" and "Segment" not in (row["concept"] or ""):
            continue
        concept = row["concept"] or ""
        label = {
            "RevenueFromOperations": "Revenue from operations",
            "Income": "Total income",
            "ProfitBeforeTax": "Profit before tax",
            "ProfitLossForPeriod": "Profit for the period",
            "ProfitOrLossAttributableToOwnersOfParent": "Profit attributable to owners",
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "EPS (basic)",
            "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "EPS (diluted)",
            "SegmentRevenue": "Segment revenue",
            "SegmentRevenueFromOperations": "Segment revenue from operations",
            "SegmentProfitBeforeTax": "Segment profit before tax",
            "SegmentProfitLossBeforeTaxAndFinanceCosts": "Segment PBT before finance costs",
            "SegmentAssets": "Segment assets",
            "SegmentLiabilities": "Segment liabilities",
        }.get(concept, concept)
        is_annual = context == "FourD"
        period_label = period or (f"FY{str(filing['period_end'])[:4]}" if is_annual else filing["period_end"])
        value = row["value"]
        unit = row["unit"] or ""
        out.append({
            "source": "results_xbrl", "kind": "segments" if "Segment" in concept else "financials",
            "item": label, "value": value, "value_raw": None, "unit": unit,
            "value_cr": round(value / 1e7, 4) if unit == "INR" and value is not None else None,
            "period": period_label, "period_end": filing["period_end"],
            "basis": f"{filing['consolidated'] or ''} {filing['audited'] or ''}".strip(),
            "context": context, "doc_id": row["file"], "doc_type": "XBRL_RESULTS",
            "page": None, "date": filing["known_at_src"], "url": filing["xbrl_url"],
            "doc_path": None,
            "quote": (f"{concept} ({context}) = {value:g} {unit}" if isinstance(value, (int, float)) else None),
            "known_at": filing["known_at_src"],
        })
    return out


def _facts_deck(identity: dict[str, Any], kind: str | None, period: str | None,
                limit: int, as_of: str | None = None) -> list[dict[str, Any]]:
    if kind in ("ar", "results", "concall"):
        return []
    isins = _identity_isins(identity)
    clause, params = _in_clause(isins)
    where = [f"s.isin IN {clause}"]
    if as_of:
        where.append("COALESCE(s.known_at,'') <> '' AND substr(s.known_at,1,10) <= ?")
        params.append(str(as_of)[:10])
    if kind == "segments":
        where.append("(lower(f.metric) LIKE '%share%' OR lower(f.metric) LIKE '%mix%' OR lower(f.metric) LIKE '%segment%')")
    elif kind in ("financials", None):
        where.append("(lower(f.metric) LIKE '%revenue%' OR lower(f.metric) LIKE '%profit%' "
                     "OR lower(f.metric) LIKE '%ebitda%' OR lower(f.metric) LIKE '%margin%' "
                     "OR lower(f.metric) LIKE '%debt%' OR lower(f.metric) LIKE '%order%' "
                     "OR lower(f.metric) LIKE '%capacity%' OR lower(f.metric) LIKE '%volume%')")
    elif kind == "guidance":
        where.append("(lower(f.metric) LIKE '%guidance%' OR lower(f.metric) LIKE '%outlook%' "
                     "OR lower(f.metric) LIKE '%target%')")
    elif kind == "kpis":
        where.append("(f.value IS NOT NULL)")
    p_clause, p_params = _period_clause(period, ("f.period",))
    if p_clause:
        where.append(p_clause)
    rows = _run_sqlite(
        "deck_figures",
        "SELECT f.sha256, f.page_no, f.metric, f.period, f.raw_number, f.value, f.unit, "
        "f.is_final, s.url, s.known_at, s.title FROM deck_sources s "
        "JOIN facts f ON f.sha256 = s.sha256 "
        f"WHERE {' AND '.join(where)} ORDER BY s.known_at DESC, f.page_no, f.line_no LIMIT ?",
        [*params, *p_params, limit * 2],
        timeout=15.0,
    )
    out, seen = [], set()
    for row in rows:
        metric = row["metric"] or ""
        key = (row["sha256"], row["page_no"], metric, row["period"], row["value"])
        if key in seen:
            continue
        seen.add(key)
        low = metric.lower()
        fkind = "segments" if ("share" in low or "mix" in low or "segment" in low) else (
            "guidance" if ("guidance" in low or "outlook" in low or "target" in low) else "kpis")
        value = row["value"]
        out.append({
            "source": "deck_figures", "kind": fkind, "item": metric, "value": value,
            "value_raw": row["raw_number"], "unit": row["unit"] or "",
            "value_cr": None, "period": row["period"], "period_end": None, "basis": "presentation",
            "context": row["title"], "doc_id": row["sha256"], "doc_type": "INVESTOR_PRESENTATION",
            "page": row["page_no"], "date": row["known_at"], "url": row["url"], "doc_path": None,
            "quote": None, "known_at": row["known_at"],
        })
    return out


def _facts_concall(identity: dict[str, Any], kind: str | None, period: str | None,
                   limit: int, as_of: str | None = None) -> list[dict[str, Any]]:
    if kind in ("ar", "results", "deck"):
        return []
    isins = _identity_isins(identity)
    clause, params = _in_clause(isins)
    where = [f"i.isin IN {clause}"]
    if as_of:
        where.append("COALESCE(d.filed_at,'') <> '' AND substr(d.filed_at,1,10) <= ?")
        params.append(str(as_of)[:10])
    if kind == "guidance":
        where.append("(lower(i.list_name) LIKE '%guid%' OR lower(i.list_name) LIKE '%management%' "
                     "OR lower(i.metric) LIKE '%guid%' OR lower(i.metric) LIKE '%outlook%')")
    p_clause, p_params = _period_clause(period, ("i.period",))
    if p_clause:
        where.append(p_clause)
    rows = _run_sqlite(
        "concall_facts",
        "SELECT i.doc_id, i.list_name, i.idx, i.metric, i.value, i.unit, i.period, i.basis, "
        "i.direction, i.firmness, i.signal, i.quote, d.filed_at, d.status, d.period_discussed "
        "FROM cc_items i LEFT JOIN cc_docs d ON d.doc_id = i.doc_id "
        f"WHERE {' AND '.join(where)} ORDER BY d.filed_at DESC, i.list_name, i.idx LIMIT ?",
        [*params, *p_params, limit * 2],
        timeout=15.0,
    )
    out = []
    for row in rows:
        list_low = (row["list_name"] or "").lower()
        fkind = "guidance" if "guid" in list_low else (
            "kpis" if kind == "kpis" or list_low in ("kpi", "operational", "metrics", "order_book") else "concall")
        out.append({
            "source": "concall_facts", "kind": fkind,
            "item": row["metric"], "value": row["value"], "value_raw": row["value"],
            "unit": row["unit"] or "", "value_cr": None, "period": row["period"],
            "period_end": row["period_discussed"], "basis": row["basis"] or "",
            "context": row["list_name"], "doc_id": row["doc_id"], "doc_type": "CONCALL_TRANSCRIPT",
            "page": None, "date": row["filed_at"], "url": None, "doc_path": None,
            "quote": (row["quote"] or "")[:600], "known_at": row["filed_at"],
            "direction": row["direction"], "firmness": row["firmness"], "signal": row["signal"],
        })
    return out


def _fact_rank(fact: dict[str, Any]) -> tuple:
    years, _ = _period_tokens(str(fact.get("period") or ""))
    year = max(years) if years else 0
    if not year and fact.get("period_end"):
        try:
            year = int(str(fact["period_end"])[:4])
        except ValueError:
            year = 0
    source_rank = {"ar_facts": 0, "results_xbrl": 1, "deck_figures": 2, "concall_facts": 3}
    kind_rank = {"segments": 0, "financials": 1, "results": 2, "kpis": 3, "guidance": 4, "concall": 5}
    return (-year, source_rank.get(fact.get("source"), 9), kind_rank.get(fact.get("kind"), 9),
            str(fact.get("date") or ""))


def facts(symbol: str, kind: str | None = None, period: str | None = None, limit: int = 80,
          as_of: str | None = None) -> dict[str, Any]:
    """Structured fundamentals, segments and KPIs from all four fact stores.

    ``as_of`` (``YYYY-MM-DD``) is a point-in-time cut: every source row must
    carry its own filing timestamp on or before that day.  Rows with no such
    timestamp are dropped rather than guessed at.
    """
    identity = resolve_one(symbol)
    canonical = _normalise_kind(kind)
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        raise DataError("bad_limit", "limit must be an integer between 1 and 500")
    as_of = str(as_of)[:10] if as_of else None
    sources = SOURCE_FOR_KIND.get(canonical, ("ar", "results", "deck", "concall"))
    collected: list[dict[str, Any]] = []
    per_source_limit = max(40, min(200, limit * 2))
    if "ar" in sources:
        collected += _facts_ar(identity, canonical, period, per_source_limit, as_of)
    if "results" in sources:
        collected += _facts_results(identity, canonical, period, per_source_limit, as_of)
    if "deck" in sources:
        collected += _facts_deck(identity, canonical, period, per_source_limit, as_of)
    if "concall" in sources:
        collected += _facts_concall(identity, canonical, period, per_source_limit, as_of)

    # Free-text kind (not a known alias) is a filter over items/metrics.
    if canonical and canonical not in SOURCE_FOR_KIND:
        needle = canonical.lower()
        collected = [f for f in collected
                     if needle in str(f.get("item") or "").lower()
                     or needle in str(f.get("kind") or "").lower()
                     or needle in str(f.get("context") or "").lower()]
    if canonical and canonical in ("segments", "financials", "kpis", "guidance"):
        collected = [f for f in collected if f.get("kind") == canonical or canonical == "financials"]

    # De-duplicate the same figure repeated in consecutive annual reports.
    if as_of:
        ranked_guard = []
        for fact in collected:
            stamp = str(fact.get("known_at") or fact.get("date") or "")[:10]
            if stamp and stamp <= as_of:
                ranked_guard.append(fact)
        collected = ranked_guard
    dedup: dict[tuple, dict[str, Any]] = {}
    for fact in sorted(collected, key=_fact_rank):
        key = (fact.get("source"), str(fact.get("item") or "").strip().lower(),
               str(fact.get("period") or "").strip().lower(), str(fact.get("value") or ""))
        if key not in dedup:
            dedup[key] = fact
    ranked = sorted(dedup.values(), key=_fact_rank)
    # A broad "facts(symbol)" call must not let a wall of FY26 XBRL lines hide
    # the FY25 segment split the caller actually asked about.
    if canonical is None:
        segments = [f for f in ranked if f.get("kind") == "segments"]
        if segments:
            ranked = segments[:20] + [f for f in ranked if f.get("kind") != "segments"]
    # For a focused fundamentals/segment answer, interleave sources so one store
    # (e.g. 80 AR rows) cannot hide the XBRL confirmation on the same figure.
    if canonical in ("financials", "segments") and len(sources) > 1:
        order = list(sources)
        buckets = {src: [f for f in ranked if f.get("source") ==
                         {"ar": "ar_facts", "results": "results_xbrl", "deck": "deck_figures",
                          "concall": "concall_facts"}.get(src)] for src in order}
        for src in order:
            buckets[src].sort(key=lambda f: (f.get("kind") != canonical, _fact_rank(f)))
        merged = []
        pos = 0
        while len(merged) < len(ranked):
            added = False
            for src in order:
                if pos < len(buckets[src]):
                    merged.append(buckets[src][pos])
                    added = True
            pos += 1
            if not added:
                break
        ranked = merged
    counts: dict[str, int] = {}
    for fact in ranked:
        counts[fact["source"]] = counts.get(fact["source"], 0) + 1
    used_dbs = [db for db, src in (("ar_facts", "ar"), ("results_xbrl", "results"),
                                   ("deck_figures", "deck"), ("concall_facts", "concall")) if src in sources]
    return {
        "symbol": identity["nse_symbol"] or symbol.upper(),
        "company": identity["name"],
        "isin": identity["isin"],
        "kind": canonical,
        "period": period,
        "as_of": as_of,
        "facts": ranked[:limit],
        "counts": {"by_source": counts, "total_matched": len(ranked), "truncated": len(ranked) > limit},
        "quarantine": {"ar_doc_ids_excluded": len(quarantined_doc_ids())},
        "provenance": {
            "identity": provenance(DUCK_KEY, ["security_master", "symbol_isin_history"]),
            "facts": [provenance(db, [db]) for db in used_dbs],
        },
    }


# ---------------------------------------------------------------------------
# Read-only SQL escape hatch
# ---------------------------------------------------------------------------
_WRITE_WORDS = re.compile(
    r"\b(ATTACH|DETACH|COPY|EXPORT|IMPORT|INSTALL|LOAD|PRAGMA|CALL|SET|CREATE|INSERT|UPDATE|"
    r"DELETE|DROP|ALTER|TRUNCATE|VACUUM|CHECKPOINT|EXECUTE|REPLACE\s+INTO|MERGE)\b",
    re.IGNORECASE,
)


def _strip_sql(sql: str) -> str:
    text = sql.strip()
    while text.startswith("--"):
        text = text.split("\n", 1)[1].strip() if "\n" in text else ""
    return text.rstrip().rstrip(";").strip()


def _statements(sql: str) -> list[str]:
    """Split on top-level semicolons, ignoring quoted strings and comments."""
    parts, buf, i = [], [], 0
    quote = None
    while i < len(sql):
        ch = sql[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    buf.append(sql[i + 1]); i += 2; continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch; buf.append(ch); i += 1; continue
        if ch == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
            end = sql.find("\n", i)
            end = len(sql) if end < 0 else end
            buf.append(sql[i:end]); i = end; continue
        if ch == "/" and i + 1 < len(sql) and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            end = len(sql) if end < 0 else end + 2
            buf.append(sql[i:end]); i = end; continue
        if ch == ";":
            parts.append("".join(buf)); buf = []; i += 1; continue
        buf.append(ch); i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def sql(query: str, db: str = "truth", limit: int = 200, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Bounded, read-only SELECT/WITH escape hatch over any registered database."""
    text = _strip_sql(query or "")
    if not text:
        raise DataError("bad_query", "sql() needs a SELECT or WITH query")
    statements = _statements(text)
    if len(statements) != 1:
        raise DataError("not_select", "only one read-only statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b", statements[0], re.IGNORECASE):
        raise DataError("not_select", "only SELECT / WITH queries are allowed")
    if _WRITE_WORDS.search(text):
        raise DataError("not_select", "write/DDL keywords are not allowed")
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        raise DataError("bad_limit", "limit must be an integer between 1 and 1000")
    try:
        timeout_seconds = max(0.5, min(float(timeout_seconds), 30.0))
    except (TypeError, ValueError):
        raise DataError("bad_timeout", "timeout_seconds must be a number")

    key = DB_ALIASES.get(str(db or "").strip().lower())
    if key is None:
        raise DataError("unknown_db", f"unknown db {db!r}; choose from {sorted(set(DB_ALIASES.values()))}")
    wrapped = f"SELECT * FROM ({text}) AS _reality_q LIMIT {limit + 1}"
    started = time.perf_counter()
    if key == DUCK_KEY:
        # A dedicated read-only connection keeps a slow escape-hatch query away
        # from the warm catalog/price connection.
        con = duckdb.connect(str(snapshot_path()), read_only=True)
        timer = threading.Timer(timeout_seconds, con.interrupt)
        timer.daemon = True
        timer.start()
        try:
            cur = con.execute(wrapped)
            columns = [d[0] for d in cur.description]
            rows = [[_jsonable(v) for v in row] for row in cur.fetchall()]
        except Exception as exc:
            if "Interrupt" in type(exc).__name__ or "interrupted" in str(exc).lower():
                raise DataError("query_timeout", f"query exceeded {timeout_seconds:.1f}s")
            raise DataError("sql_error", f"{type(exc).__name__}: {exc}")
        finally:
            timer.cancel()
            con.close()
    else:
        try:
            raw = _run_sqlite(key, wrapped, timeout=timeout_seconds)
        except DataError:
            raise
        except sqlite3.DatabaseError as exc:
            raise DataError("sql_error", f"{type(exc).__name__}: {exc}")
        columns = list(raw[0].keys()) if raw else []
        rows = [[_jsonable(v) for v in row] for row in raw]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "db": key,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
        "provenance": provenance(key, [], note="read-only SELECT/WITH, row-limited"),
    }
