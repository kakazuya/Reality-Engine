"""pilot3 lookups: the databases the reality-data server serves through the ``pilot3_*`` tools (T-049 F).

``pilot3.db`` is built by scripts (``python -m reality_engine.pilot3.build``): dated page text of every held
document, KPI series, reported and derived financial lines, ratios, shareholding, management statements.
``REALITY_PILOT3_STORES`` names a registry of store paths (``python -m reality_engine.scripts.store_registry``);
each call resolves its symbol against the stores IN THE REGISTRY'S ORDER and opens the first one that holds it
(T-203).  ``REALITY_PILOT3_DB`` still pins one store (the tests and A/B runs do this) and switches routing off.
The companies the tools accept are the ones the chosen store's ``company`` table holds (T-090: the covered
universe, never a fixed list of three); a database built before the table existed falls back to the bundled
pilot3 companies.  These tools answer from the store first; the raw files are touched only when a tool says
NOT IN DATA.

Read-only (``connect_ro``), small replies, and every row carries ``provenance`` = table, source (document +
page, or store table + row) and ``known_at``.  ``as_of`` drops rows whose ``known_at`` is after that day, and
rows without a ``known_at`` (a row that cannot prove it was public is never shown to a point-in-time question).
"""
from __future__ import annotations

import contextvars
import datetime as dt
import difflib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import yaml

import core
from core import DataError
from reality_engine.pilot3 import preferred as p3_preferred
from reality_engine.pilot3.guidance import current_rows as _guidance_current_rows
from reality_engine.pilot3.lender import filed_lender

_MAIN = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot3\pilot3.db")
MAX_LIMIT = 50
QUOTE_CHARS = 600
_lock = threading.Lock()
_conns: dict[Path, sqlite3.Connection] = {}          # one read-only connection per store path
_STORE: contextvars.ContextVar[Path | None] = contextvars.ContextVar("pilot3_store", default=None)
_SYMBOL: contextvars.ContextVar[str | None] = contextvars.ContextVar("pilot3_symbol", default=None)

_DOC_TYPES = {
    "deck": "deck", "decks": "deck", "presentation": "deck", "investor presentation": "deck",
    "transcript": "transcript", "transcripts": "transcript", "concall": "transcript", "call": "transcript",
    "ar": "annual_report", "annual report": "annual_report", "annual_report": "annual_report",
    "announcement": "announcement", "announcements": "announcement", "filing": "announcement",
    "results": "results", "result": "results", "press release": "press_release", "press_release": "press_release",
    "audio_link": "audio_link",
}


# --- the store registry (T-203) ---------------------------------------------------------------------
def stores() -> list[dict[str, Any]]:
    """The registered stores in priority order (``REALITY_PILOT3_STORES``, else the generated
    ``D:/RealityEngine/stores.json``); ``[]`` when no registry is configured or readable."""
    try:
        from reality_engine.scripts.store_registry import load_registry
        return load_registry()
    except Exception:  # no registry, bad JSON, or a launch without the checkout root on sys.path
        return []


def routing_enabled() -> bool:
    """Does a symbol get answered from whichever registered store holds it?  A pinned ``REALITY_PILOT3_DB``
    switches routing off: that store and no other is read (tests, A/B runs)."""
    return not os.environ.get("REALITY_PILOT3_DB") and bool(stores())


def _pinned() -> Path | None:
    env = os.environ.get("REALITY_PILOT3_DB")
    return Path(env) if env else None


def _default_path() -> Path:
    here = core.DATA / "pilot3" / "pilot3.db"
    return here if here.is_file() else _MAIN


def db_path() -> Path:
    """The store the current call reads: the pinned env var, the store ``resolve_symbol`` chose, else the
    repo's own pilot3 build."""
    pin = _pinned()
    if pin is not None:
        return pin
    return _STORE.get() or _default_path()


def _open(path: Path) -> sqlite3.Connection:
    """One cached read-only connection per store path (thread-safe; a store is never written)."""
    with _lock:
        con = _conns.get(path)
        if con is not None:
            return con
        if not path.is_file():
            raise DataError("pilot3_db_missing", f"pilot3.db not found at {path}; build it with "
                            "python -m reality_engine.pilot3.build, or fix the store registry "
                            "(REALITY_PILOT3_STORES)")
        con = core.connect_pilot3(path, timeout_s=core.READ_TIMEOUT_S)
        con.row_factory = sqlite3.Row
        _conns[path] = con
        return con


def connect() -> sqlite3.Connection:
    return _open(db_path())


def close() -> None:
    with _lock:
        for con in _conns.values():
            con.close()
        _conns.clear()


def select_store(store: str) -> Path:
    """Select a registered store by name / path (or any store file) for the rest of this call."""
    text = str(store or "").strip()
    if not text:
        raise DataError("bad_store", "store is required")
    entries = stores()
    for row in entries:
        names = {row["name"].lower(), row["path"].name.lower(), row["path"].stem.lower(), str(row["path"]).lower()}
        if text.lower() in names:
            _STORE.set(row["path"])
            return row["path"]
    path = Path(text).expanduser()
    if path.is_file():
        _STORE.set(path)
        return path
    raise DataError("bad_store", f"unknown pilot3 store {store!r}; registered stores: "
                    + (", ".join(row["name"] for row in entries) or "none (set REALITY_PILOT3_STORES)"))


def reset_store() -> None:
    """Forget the store a previous call in this context resolved: a call that names no symbol reads the default."""
    _STORE.set(None)
    _SYMBOL.set(None)


def store_listing(hint: str | None = None) -> dict[str, Any]:
    """The registered stores, for a call that names neither a symbol nor a store."""
    entries = stores()
    rows = [{"name": row["name"], "path": str(row["path"]), "built": row["built"],
             "companies": len(row["symbols"]), "sample": list(row["symbols"][:3])} for row in entries]
    return {"stores": rows, "n": len(rows),
            "hint": hint or ("pass symbol= to answer from the store that holds it, or store= to query that store "
                             "directly; REALITY_PILOT3_DB pins a single store")}


def _q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        return connect().execute(sql, params).fetchall()
    except core.QueryTimeout as exc:
        raise DataError("query_timeout", str(exc))
    except sqlite3.DatabaseError as exc:
        raise DataError("sql_error", f"{type(exc).__name__}: {exc}")


def _is_lender(sym: str) -> bool:
    """A bank, NBFC or insurer reports interest / premium income, so EV/EBITDA has no meaning for it."""
    return filed_lender(connect(), sym)


# --- symbols, periods, dates ------------------------------------------------------------------------
def pilot_symbols() -> tuple[str, ...]:
    """Every company the database holds: its ``company`` table (T-090).  A build that predates the table serves
    no company (the table is the only source of coverage; T-094 removed the old three-symbol fallback)."""
    try:
        return tuple(row[0] for row in _q("SELECT DISTINCT symbol FROM company WHERE symbol IS NOT NULL AND symbol<>'' "
                                          "ORDER BY symbol"))
    except DataError:
        return ()


def _symbols_in(path: Path) -> tuple[str, ...]:
    """Every company one store's ``company`` table holds (empty for an unreadable / old build)."""
    try:
        rows = _open(path).execute("SELECT DISTINCT symbol FROM company WHERE symbol IS NOT NULL AND symbol<>'' "
                                   "ORDER BY symbol").fetchall()
        return tuple(row[0] for row in rows)
    except (DataError, sqlite3.DatabaseError):
        return ()


def _match_in(path: Path, text: str, symbols: tuple[str, ...] | None = None) -> str | None:
    """The company one store holds under ``text`` (symbol, ISIN, BSE code or name); ``None`` when it holds none."""
    key = text.upper()
    held = symbols if symbols is not None else _symbols_in(path)
    if key in held:
        return key
    try:
        row = _open(path).execute("SELECT symbol FROM company WHERE isin=? OR bse_code=? OR upper(name) LIKE ? "
                                  "LIMIT 1", (key, text, f"%{key}%")).fetchone()
    except (DataError, sqlite3.DatabaseError):
        return None
    return str(row[0]).upper() if row and row[0] else None


def _spellings(text: str) -> list[str]:
    """The shared resolver's NSE/BSE spellings for a name like BAJAJ FINANCE (empty when it knows none)."""
    try:
        ident = core.resolve_one(text)
    except Exception:
        return []
    return [str(cand).upper() for cand in (ident.get("nse_symbol"), ident.get("bse_symbol")) if cand]


def resolve_symbol(symbol: str) -> str:
    """A symbol / BSE code / ISIN / name of a company one registered store holds; the store that holds it is
    selected for the rest of this call.  A pinned ``REALITY_PILOT3_DB`` searches that store only."""
    text = (symbol or "").strip()
    if not text:
        raise DataError("bad_symbol", "symbol is required")
    pin = _pinned()
    entries = [] if pin is not None else stores()
    if pin is not None:
        candidates: list[tuple[Path, tuple[str, ...] | None]] = [(pin, None)]
    elif entries:
        candidates = [(row["path"], tuple(row["symbols"])) for row in entries]
    else:
        candidates = [(db_path(), None)]
    chosen: Path | None = None
    key: str | None = None
    for path, held in candidates:
        found = _match_in(path, text, held)
        if found:
            key, chosen = found, path
            break
    if key is None:  # a name only the shared resolver spells (BAJAJ FINANCE -> BAJFINANCE)
        for spelling in _spellings(text):
            for path, held in candidates:
                if spelling in (held if held is not None else _symbols_in(path)):
                    key, chosen = spelling, path
                    break
            if key:
                break
    if key is None:
        if entries:
            where = ", ".join(f"{row['name']} ({row['path']})" for row in entries)
            message = (f"{symbol!r} is not a company any of the {len(entries)} registered pilot3 stores holds: "
                       f"{where}; use the general tools (facts, docs, search_docs) for a company they do not hold")
        else:
            message = (f"{symbol!r} is not a company this pilot database holds: its company table lists "
                       f"{len(_symbols_in(candidates[0][0]))} companies; use the general tools (facts, docs, "
                       "search_docs) for a company it does not hold")
        raise DataError("not_pilot3", message)
    _STORE.set(chosen)
    _SYMBOL.set(key)
    return key


def _day(value: str | None, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise DataError("bad_date", f"{field} must be YYYY-MM-DD, got {value!r}")


def _fy2(text: str) -> str:
    return text[-2:]


def norm_period(period: str | None) -> tuple[str | None, str | None]:
    """``(kind, label)``: Q2FY26 / H1FY26 / FY26 labels the tables use; ``kind`` is Q, H1, FY or None.
    Accepts Q2FY26, Q2 FY2026, FY2025-26, 2025-26, FY26, H1FY26 and a date (its fiscal quarter)."""
    if period in (None, ""):
        return None, None
    text = str(period).strip().upper().replace(" ", "")
    m = re.fullmatch(r"Q([1-4])-?FY?(\d{2}|\d{4})", text)
    if m:
        return "Q", f"Q{m[1]}FY{_fy2(m[2])}"
    m = re.fullmatch(r"H([12])-?FY?(\d{2}|\d{4})", text)
    if m:
        return "H" + m[1], f"H{m[1]}FY{_fy2(m[2])}"
    m = re.fullmatch(r"(?:FY)?(\d{4})-(\d{2}|\d{4})", text)
    if m:
        return "FY", f"FY{_fy2(m[2])}"
    m = re.fullmatch(r"(?:FY|YEAR)?-?(\d{2}|\d{4})", text)
    if m:
        return "FY", f"FY{_fy2(m[1])}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        year, month = int(m[1]), int(m[2])
        fy = year + 1 if month >= 4 else year
        q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[month]
        return "Q", f"Q{q}FY{str(fy)[-2:]}"
    return None, text


def _asof(as_of: str | None, col: str = "known_at") -> tuple[str, tuple]:
    day = _day(as_of, "as_of")
    return (f" AND {col} IS NOT NULL AND substr({col},1,10) <= ?", (day,)) if day else ("", ())


def _cap(limit: Any, default: int = 10) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


# --- coverage, paging and read-next (T-197) ---------------------------------------------------------
# A reply says what it searched, what it could not see and what it cut, so a cheap model never reads a partial
# reply as the whole store and never has to guess the next call.  Every rule here is a property of the reply
# shape: no company, sector or question is special-cased.
MAX_OFFSET = 5000                 # a paging loop is bounded; the reply says the exact next offset
COVERAGE_DOCUMENTS = 40           # documents listed per reply; more are summarised by type and month
REPLY_BYTES = 19_000              # every text reply is trimmed below this (the hard cap is 20 kB)
_DOC_LABELS = {"transcript": "calls", "deck": "decks", "annual_report": "annual reports", "results": "results",
               "press_release": "filings", "announcement": "filings", "audio_link": "audio links"}
_TEXT_STORES = ("transcript_statement (tagged statements)", "doc_page (every held document's dated page text)")


def _window(limit: Any, offset: Any, default: int = 10) -> tuple[int, int]:
    """(cap, offset): the page of the matched set a reply shows."""
    try:
        start = max(0, min(int(offset or 0), MAX_OFFSET))
    except (TypeError, ValueError):
        start = 0
    return _cap(limit, default), start


def _hidden_documents(symbol: str, day: str | None) -> dict[str, Any]:
    """The documents a point-in-time question cannot see yet: how many, which and on what dates (T-197 step 5)."""
    if not day:
        return {}
    rows = _q("SELECT doc_key, doc_type, COALESCE(known_at, filing_date) AS filed FROM doc WHERE symbol=? "
              "AND known_at IS NOT NULL AND substr(known_at,1,10)>? ORDER BY known_at DESC", (symbol, day))
    if not rows:
        return {"hidden_after_as_of": 0}
    dates = sorted({str(r["filed"])[:10] for r in rows if r["filed"]})
    out = {"hidden_after_as_of": len(rows),
           "hidden_documents": [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "known_at": r["filed"]}
                                for r in rows[:10]]}
    if dates:
        out["hidden_dates"] = {"first": dates[0], "last": dates[-1]}
    return out


def _documents_index(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """EVERY document a reply matched: key, type, date, title, matching pages and match count, so a document whose
    items were cut is still named.  More than ``COVERAGE_DOCUMENTS``: the first 40 are listed and the rest are
    summed by type and month (a reply never grows past what a model can read)."""
    by: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry.get("doc_key")
        if not key:
            continue
        doc = by.get(key)
        if doc is None:
            doc = by[key] = {"doc_key": key, "doc_type": entry.get("doc_type"),
                             "date": (entry.get("date") or "")[:10] or None,
                             "title": _trim(entry.get("title"), 60), "pages": [], "matches": 0}
        doc["matches"] += int(entry.get("matches") or 1)
        page = entry.get("page")
        if page not in (None, "") and page not in doc["pages"] and len(doc["pages"]) < 3:
            doc["pages"].append(page)
        doc["doc_type"] = doc["doc_type"] or entry.get("doc_type")
        doc["date"] = doc["date"] or (entry.get("date") or "")[:10] or None
        doc["title"] = doc["title"] or _trim(entry.get("title"), 60)
    listed = sorted(by.values(), key=lambda d: (d["date"] or "", d["doc_key"]), reverse=True)
    out: dict[str, Any] = {"documents": listed[:COVERAGE_DOCUMENTS], "matched_documents": len(listed)}
    summary: dict[tuple[str, str], int] = {}
    for doc in listed[COVERAGE_DOCUMENTS:]:
        key = (str(doc["doc_type"] or "?"), (doc["date"] or "")[:7])
        summary[key] = summary.get(key, 0) + doc["matches"]
    if summary:
        cells = [{"doc_type": kind, "month": month or None, "matches": count}
                 for (kind, month), count in sorted(summary.items())]
        if len(cells) > 12:      # a two-year history would spend the reply's bytes on the summary itself
            cells.sort(key=lambda cell: -int(cell["matches"]))
            out["summarised_documents"] = cells[:12]
            out["summarised_cells"] = len(cells)
        else:
            out["summarised_documents"] = cells
    return out


def _scope_line(matched: int, shown: int, cut: int, offset: int, documents: list[dict[str, Any]],
                doc_count: int, parts: str | None = None) -> str:
    """The honest first line of every text reply: how much matched, in how many documents, how much is shown and
    the exact next call (T-197 step 1)."""
    kinds: dict[str, int] = {}
    seen: set[str] = set()
    for doc in documents:
        key = str(doc.get("doc_key") or "")
        if key in seen:
            continue
        seen.add(key)
        raw = str(doc.get("doc_type") or "")
        label = _DOC_LABELS.get(raw, raw or "other")
        kinds[label] = kinds.get(label, 0) + 1
    text = f"{matched} match(es)" + (f" ({parts})" if parts else "") + f" in {doc_count} document(s)"
    if kinds:
        text += " (" + ", ".join(f"{count} {label}" for label, count in
                                 sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))) + ")"
    text += f"; {shown} shown"
    if cut:
        text += f"; {cut} cut by the limit - call again with offset={offset + shown} or read the listed pages"
    return text


def _coverage(tool: str, searched: list[str], not_searched: list[str], matched_total: int, shown: int, cut: int,
              offset: int = 0, documents: list[dict[str, Any]] | None = None, document_total: int | None = None,
              outside: list[dict[str, Any]] | None = None, hidden: dict[str, Any] | None = None) -> dict[str, Any]:
    """The coverage block every text reply carries (T-197 step 1)."""
    cov: dict[str, Any] = {"searched": list(searched), "not_searched": [s for s in not_searched if s],
                           "matched_total": matched_total, "shown": shown, "cut": cut, "offset": offset}
    if documents is not None:
        cov.update(_documents_index(documents))
        if document_total is not None:
            cov["matched_documents"] = document_total
    if outside:
        cov["outside_date_filter"] = outside
    if hidden:
        cov.update(hidden)
    if cut and shown:
        cov["next"] = {"tool": f"pilot3_{tool}", "offset": offset + shown,
                       "text": f"call pilot3_{tool} again with offset={offset + shown} for the next page"}
    return cov


def _read_next(entries: list[dict[str, Any]], per: int = 12) -> list[dict[str, Any]]:
    """The page a reply quoted and its neighbours (page-1, page, page+1): the table beside a headline figure is one
    read away instead of invisible (T-197 step 4)."""
    pairs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for entry in entries:
        doc_key, page = entry.get("doc_key"), entry.get("page")
        try:
            number = int(page) if page not in (None, "") else None
        except (TypeError, ValueError):
            number = None
        if doc_key and number is not None and (doc_key, number) not in seen:
            seen.add((doc_key, number))
            pairs.append((doc_key, number))
    if not pairs:
        return []
    keys = list(dict.fromkeys(key for key, _page in pairs))
    last = {r["doc_key"]: int(r["pages"] or 0) for r in _q(
        f"SELECT doc_key, pages FROM doc WHERE doc_key IN ({','.join('?' * len(keys))})", tuple(keys))}
    out: list[dict[str, Any]] = []
    shown: set[tuple[str, int]] = set()
    for doc_key, page in pairs:
        highest = last.get(doc_key) or page + 1
        for neighbour, reason in ((page - 1, "page before the quoted one"), (page, "the quoted page"),
                                  (page + 1, "page after the quoted one")):
            if 1 <= neighbour <= highest and (doc_key, neighbour) not in shown:
                shown.add((doc_key, neighbour))
                out.append({"doc_key": doc_key, "page": neighbour, "reason": reason})
                if len(out) >= per:
                    return out
    return out


def _trim(text: str | None, n: int = QUOTE_CHARS) -> str | None:
    if text is None:
        return None
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def _prov(table: str, source: str, known_at: str | None, **extra: Any) -> dict[str, Any]:
    return {"table": table, "source": source, "known_at": known_at, **{k: v for k, v in extra.items() if v is not None}}


def _db_prov(**extra: Any) -> dict[str, Any]:
    path = db_path()
    built = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime)) if path.exists() else None
    out: dict[str, Any] = {"db": "pilot3", "path": str(path), "read_only": True, "built": built}
    entries = [] if _pinned() is not None else stores()
    symbol = _SYMBOL.get()
    for row in entries:
        if row["path"] == path:
            out["store"] = row["name"]
        elif symbol and symbol in set(row["symbols"]):
            out.setdefault("also_held_in", []).append(str(row["path"]))
    return {**out, **extra}


def _reply(symbol: str, rows: list[dict], tool: str, **extra: Any) -> dict[str, Any]:
    out = {"found": bool(rows), "symbol": symbol, "tool": tool, "n": len(rows), "rows": rows, **extra,
           "provenance": _db_prov()}
    if extra.get("as_of"):
        # one shared point-in-time report (T-197 step 5): every tool that serves document-derived rows says which
        # documents the passed as_of hid and on what dates, so a miss after a date is never read as "not held".
        hidden = _hidden_documents(symbol, extra.get("as_of"))
        for key, value in hidden.items():
            out.setdefault(key, value)
    if not rows:
        out.setdefault("hint", "NOT IN DATA of pilot3 for these arguments: check the 'available' list, widen the "
                       "period or as_of, try pilot3_search; only then fall back to the raw tools.")
    return out


def _available(table: str, col: str, symbol: str, like: str | None = None, extra: str = "", n: int = 40) -> list[str]:
    sql = f"SELECT {col}, COUNT(*) c FROM {table} WHERE symbol=?{extra}"
    args: list[Any] = [symbol]
    if like:
        sql += f" AND {col} LIKE ?"
        args.append(f"%{like}%")
    sql += f" GROUP BY {col} ORDER BY c DESC LIMIT {n}"
    return [r[0] for r in _q(sql, tuple(args)) if r[0]]


def _pick(table: str, col: str, symbol: str, name: str, extra: str = "") -> tuple[list[str], list[str]]:
    """Names to match for a user's metric word: the exact one, else every name containing it (spaces as _)."""
    key = re.sub(r"[\s\-]+", "_", name.strip().lower())
    names = _available(table, col, symbol, extra=extra, n=500)
    if key in names:
        return [key], names
    near = [n for n in names if key in n]
    return near[:8], names


# --- pilot3_kpi -------------------------------------------------------------------------------------
_DOC_JOIN = ("LEFT JOIN doc d ON d.doc_key = COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=k.symbol "
             "AND a.alias_key=k.doc_key), k.doc_key)")
# The words an investor uses for a KPI the store files under a longer metric name (T-165).  "NIM" alone already
# matches nim_pct by substring; "net interest margin", "losses and provisions to assets" and "cost of borrowings"
# did not.  One-word mappings only: a metric name the store holds still wins because it is tried first elsewhere.
_KPI_WORDS = {
    "net_interest_margin": "nim", "net_interest_margins": "nim", "nims": "nim",
    "losses_and_provisions_to_assets": "credit_cost", "provisions_to_assets": "credit_cost",
    "credit_costs": "credit_cost", "cost_of_borrowings": "cost_of_funds", "cost_of_borrowing": "cost_of_funds",
    "cost_of_fund": "cost_of_funds",
}


# --- pilot3_kpi ---------------------------------------------------------------------------------------
# T-192: a company that prints its own EBITDA states which measure it is.  The operating definition (the one the
# derived F_EBITDA formula matches) excludes only non-operating items ("EBITDA (before forex and other income)");
# a label that also strips an operating cost ("EBITDA before R&D") is a different measure and never outranks it.
_NON_OPERATING = re.compile(r"forex|foreign exchange|\bfx\b|other income|exceptional|one[- ]?time|non[- ]?operating",
                            re.I)
_EBITDA_LABEL = re.compile(r"ebitda\s*(?:\(|before|excluding|ex-)\s*([^\n)]{0,50})", re.I)


def _ebitda_rank(row: dict[str, Any]) -> int:
    """0 for the operating EBITDA, 1 for a measure that strips an operating cost as well."""
    text = f"{row.get('raw_label') or ''} {row.get('quote') or ''}"
    m = re.search(r"ebitda\s*(?:before|excluding|ex-)\s*([^\n,;)]{0,40})", text, re.I)
    if m:
        return 0 if _NON_OPERATING.search(m.group(1)) else 1
    m = re.search(r"ebitda\s*\(([^)]{0,60})\)", text, re.I)
    if m and re.search(r"before|excluding|ex-", m.group(1), re.I):
        return 0 if _NON_OPERATING.search(m.group(1)) else 1
    return 0


def _definition_rank(row: dict[str, Any], key: str) -> int:
    return _ebitda_rank(row) if key == "ebitda" else 0


def kpi(symbol: str, kpi: str, period: str | None = None, as_of: str | None = None,
        dimension: str | None = None, basis: str | None = None, limit: int = 10,
        include_quarantined: bool = False) -> dict[str, Any]:
    """A company-stated KPI (order book, AUM, EBITDA/tonne, NIM ...) from decks, results, releases, transcripts."""
    sym = resolve_symbol(symbol)
    metric_asked = kpi
    kpi = _KPI_WORDS.get(re.sub(r"[\s\-]+", "_", str(kpi).strip().lower()), kpi)
    # the metric NAME is not hidden by a quarantine: the row-level filter below hides the rows and the empty
    # reply says they are held but quarantined (T-165: CHOLAFIN Q2FY27 NIM 7.9 is the only row of its period)
    names, allnames = _pick("kpi_series", "metric", sym, kpi)
    if not names:
        return _reply(sym, [], "pilot3_kpi", available=allnames[:40], metric_asked=metric_asked)
    kind, label = norm_period(period)
    where, args = f"k.symbol=? AND k.metric IN ({','.join('?' * len(names))})", [sym, *names]
    if label:
        where += " AND k.fiscal_period=?"
        args.append(label)
    if dimension:
        where += " AND lower(k.dimension)=?"
        args.append(dimension.strip().lower())
    if basis:
        where += " AND k.basis=?"
        args.append(basis.strip().lower())
    join, check_sel, hide = _check_cols("kpi_series", "k.id")
    visible_where = where          # without the quarantine clause: the "held but hidden" note needs it
    if not include_quarantined:
        where += hide
    extra, eargs = _asof(as_of, "k.known_at")
    rows = _q(f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.scale, k.fiscal_period, k.period_type, "
              f"k.as_of_date, k.basis, k.entity, k.doc_key, k.page, k.quote, k.known_at, k.conf_rank, k.raw_label, "
              f"d.doc_key AS dk, d.title, d.doc_type{check_sel} FROM kpi_series k {_DOC_JOIN}{join} WHERE {where}{extra} "
              # best evidence first: the extractor's confidence, then a deck/results/filing before a call remark.
              # The window must reach past a measure's duplicates (one value restated in many filings): at 3x the
              # reply size, a restated measure filled it and its lower-confidence period series never arrived (T-049,
              # 4 Nov 2026: Bajaj's quarterly GNPA and KEC's order-intake trend came back as old annual rows only).
              f"ORDER BY k.conf_rank DESC, "
              f"CASE d.doc_type WHEN 'deck' THEN 0 WHEN 'results' THEN 1 WHEN 'press_release' THEN 2 "
              f"WHEN 'annual_report' THEN 3 WHEN 'transcript' THEN 4 ELSE 5 END, "
              # the group statement before standalone when both are filed (as pilot3_fin does): HINDUNILVR Q2FY27
              # Beauty & Wellbeing EBIT came back standalone 1,242 first (filed later) for consolidated 1,235 (8 Nov)
              f"(k.dimension='total') DESC, (k.basis='consolidated') DESC, k.known_at DESC, k.id LIMIT ?",
              (*args, *eargs, _cap(limit) * 30))
    out, seen = [], set()
    for r in rows:
        basis = r["basis"] if r["basis"] in _REPORTING_BASES else "not_stated"
        entity = _entity_of(r, sym)
        dimension = "total" if r["dimension"] in ("consolidated", "standalone") else r["dimension"]
        sig = (r["metric"], entity, dimension, r["fiscal_period"], r["value"], r["unit"])
        if sig in seen:      # the same figure printed again by another filing: one row, best evidence first
            continue
        seen.add(sig)
        out.append(_add_check({"metric": r["metric"], "dimension": dimension, "value": r["value"],
                               "unit": r["unit"], "period": r["fiscal_period"], "period_type": r["period_type"],
                               "as_of_date": r["as_of_date"], "basis": basis, "entity": entity,
                               "raw_label": r["raw_label"],
                               "quote": _trim(r["quote"], 300),
                               "provenance": _prov("kpi_series", f"{r['dk'] or r['doc_key']} p{r['page']}",
                                                   r["known_at"], doc_type=r["doc_type"], title=r["title"],
                                                   row_id=r["id"])}, r))
    # the company's own rows first (T-088), then the operating definition of a measure that has several (T-192)
    out.sort(key=lambda row: (0 if row["entity"] == sym else 1, _definition_rank(row, str(row["metric"]))))
    out = out[: _cap(limit)]
    held = None
    held_hidden = None
    if not out:  # the metric exists: say which periods / dimensions hold it, so the next call can be exact
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT fiscal_period, dimension, COUNT(*) FROM kpi_series WHERE symbol=? AND metric IN "
            f"({','.join('?' * len(names))}){_visible('kpi_series')} "
            f"GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
        # A figure the row check quarantined is still held (T-113): say so, or the caller reads a deliberate hide
        # as "not in data" (CHOLAFIN Q2FY27 NIM 7.9 is exactly this, T-165).
        if not include_quarantined and _has_table("row_check"):
            q_where = (visible_where + " AND EXISTS (SELECT 1 FROM row_check rc WHERE rc.tbl='kpi_series' "
                       "AND rc.row_id=k.id AND rc.status='quarantined')")
            held_hidden = [f"{r[0]} / {r[1]} ({r[2]} rows; the row check quarantined them: "
                           f"include_quarantined=true shows them)" for r in _q(
                f"SELECT k.fiscal_period, k.dimension, COUNT(*) FROM kpi_series k WHERE {q_where} "
                f"GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20", tuple(args))]
    return _reply(sym, out, "pilot3_kpi", metrics_matched=names, held_period_dimension=held,
                  held_quarantined=held_hidden, as_of=_day(as_of, "as_of"))


# --- pilot3_cells ------------------------------------------------------------------------------------
def cells(symbol: str, terms: str, period: str | None = None, as_of: str | None = None,
          include_unverified: bool = True, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Figures read from table and chart pages (decks, results, annual reports) by the page reader: one cell per
    printed figure with its row label, column header, table title and status. ``verified`` means the position check
    settled the cell; ``unverified`` is served and labelled (that is how T-189 keeps recall); ``quarantined`` is
    never served. ``as_of`` drops cells whose document was not known by then; ``offset`` pages a cut reply.
    A row whose value cell the reader stored separately carries the values printed beside it (``values``), so a
    label-only row is never served as if the table held no figure."""
    sym = resolve_symbol(symbol)
    if not _has_table("page_cell"):
        return {"found": False, "symbol": sym, "tool": "pilot3_cells", "reason": "no page_cell table",
                "provenance": _db_prov()}
    day = _day(as_of, "as_of")
    words = [w for w in re.split(r"[^\w%]+", str(terms or "").lower()) if len(w) >= 2]
    where = ["c.symbol=?", "COALESCE(c.status,'')<>'quarantined'"]
    args: list[Any] = [sym]
    for word in words:
        where.append("lower(COALESCE(c.row_label,'')||' '||COALESCE(c.col_header,'')||' '||"
                     "COALESCE(c.table_title,'')) LIKE ?")
        args.append(f"%{word}%")
    if not include_unverified:
        where.append("c.status='verified'")
    extra, eargs = "", []
    if day:
        extra = " AND substr(COALESCE(d.known_at, c.known_at),1,10) <= ?"
        eargs.append(day)
    kind, label = norm_period(period)
    cap, start = _window(limit, offset, 20)
    rows = _q(
        "SELECT c.doc_key, c.page, c.symbol, c.reader, c.table_title, c.row_label, c.col_header, c.value_text, "
        "c.unit_text, c.status, c.conflict, COALESCE(d.title,'') AS title, COALESCE(d.doc_type,'') AS doc_type, "
        "COALESCE(d.known_at, c.known_at) AS filed_at "
        "FROM page_cell c LEFT JOIN doc d ON d.doc_key=c.doc_key "
        f"WHERE {' AND '.join(where)}{extra} "
        "ORDER BY CASE c.status WHEN 'verified' THEN 0 WHEN 'unverified' THEN 1 ELSE 2 END, "
        "filed_at DESC, c.page LIMIT ?", (*args, *eargs, max(400, (start + cap) * 10)))
    matched: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    starts = [re.compile(r"(?<![a-z0-9])" + re.escape(w)) for w in words]   # a term starts a word: 'us' != 'business'
    for r in rows:
        text = " ".join((r["row_label"] or "", r["col_header"] or "", r["table_title"] or ""))
        if not all(p.search(text.lower()) for p in starts):
            continue
        if label and not _period_in(text, label):
            continue
        sig = (r["doc_key"], r["page"], r["row_label"], r["col_header"], r["value_text"], r["unit_text"])
        if sig in seen:
            continue
        seen.add(sig)
        matched.append({
            "value_text": r["value_text"], "unit_text": r["unit_text"],
            "row_label": _trim(r["row_label"], 120), "col_header": _trim(r["col_header"], 80),
            "table_title": _trim(r["table_title"], 80),
            "status": r["status"] or "unverified", "conflict": r["conflict"] or "",
            "doc_key": r["doc_key"], "doc_type": _DOC_TYPES.get((r["doc_type"] or "").lower(), r["doc_type"] or ""),
            "title": _trim(r["title"], 60), "page": r["page"], "known_at": r["filed_at"], "reader": r["reader"],
            "provenance": _prov("page_cell", f"p{r['page']}", r["filed_at"]),
        })
    # a printed figure is the value cell, not the label cell: serve value-bearing cells first, and give a
    # label-only row the values its table printed beside it (the reader stores them as separate cells) (T-197).
    matched.sort(key=lambda row: 0 if str(row.get("value_text") or "").strip() else 1)
    page = matched[start:start + cap]
    for row in [r for r in page if not str(r.get("value_text") or "").strip()][:5]:
        siblings = _q("SELECT col_header, value_text, unit_text FROM page_cell WHERE doc_key=? AND page=? "
                      "AND COALESCE(status,'')<>'quarantined' AND COALESCE(value_text,'')<>'' "
                      "AND COALESCE(table_title,'')=COALESCE(?,'') ORDER BY rowid LIMIT 8",
                      (row["doc_key"], row["page"], row["table_title"]))
        if siblings:
            row["values"] = [{"column": s["col_header"], "value": s["value_text"], "unit": s["unit_text"]}
                             for s in siblings]
            row["value_missing_note"] = ("the reader stored this row's label and its values as separate cells: "
                                         "read the page for the columns")
    held = None
    if not matched:
        held = [f"{r[0]} ({r[1]} cells)" for r in _q(
            "SELECT row_label, COUNT(*) FROM page_cell WHERE symbol=? AND COALESCE(status,'')<>'quarantined' "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 20", (sym,))]
    cut = max(0, len(matched) - len(page))
    docs = [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "date": r["known_at"], "title": r["title"],
             "page": r["page"]} for r in matched]
    text = _scope_line(len(matched), len(page), cut, start, docs, len({d["doc_key"] for d in docs}))
    reply = _reply(sym, page, "pilot3_cells", terms=terms, period=period, held_labels=held,
                   include_unverified=include_unverified, as_of=day, text=text,
                   coverage=_coverage("cells", ["page_cell (table and chart cells of decks, results, annual reports)",
                                                "doc (document type, title, filing date)"],
                                      ["documents whose pages the page reader never parsed",
                                       "transcript and announcement page text (pilot3_search / pilot3_topic)"],
                                      len(matched), len(page), cut, start, documents=docs,
                                      hidden=_hidden_documents(sym, day)),
                   read_next=_read_next(page))

    def labels(width: int) -> None:
        for row in reply["rows"]:
            row["row_label"] = _trim(row.get("row_label"), width)
            row["table_title"] = _trim(row.get("table_title"), width)

    def values_cut(keep: int) -> None:
        for row in reply["rows"]:
            if isinstance(row.get("values"), list) and len(row["values"]) > keep:
                row["values"] = row["values"][:keep]

    return _shrink(reply, [
        ("row labels cut to 80 characters", lambda: labels(80)),
        ("each label-only row cut to its first 4 values", lambda: values_cut(4)),
        ("the list cut to the first 10 cells", lambda: reply["rows"].__delitem__(slice(10, None))),
        ("row labels cut to 50 characters", lambda: labels(50)),
    ])


# --- pilot3_fin -------------------------------------------------------------------------------------
def fin(symbol: str, measure: str, period: str | None = None, basis: str | None = None,
        definition: str | None = None, as_of: str | None = None, limit: int = 12) -> dict[str, Any]:
    """Reported / derived / company-stated financial lines: annual (FY26, H1FY26) and quarterly (Q2FY26), one
    preferred figure per measure, period and basis (the newest filing's restatement wins, alternatives listed);
    the same election the ``preferred_from`` / ``preferred_to`` columns and ``fin_quarter_current`` hold."""
    sym = resolve_symbol(symbol)
    kind, label = norm_period(period)
    use_q = kind in (None, "Q")
    use_a = kind in (None, "FY", "H1", "H2")
    out: list[dict] = []
    avail: list[str] = []
    cap = _cap(limit)
    bas = basis.strip().lower() if basis else None
    if use_a:
        names, allnames = _pick("fin_annual_line", "line_item", sym, measure)
        avail += allnames
        if names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(names))})", [sym, *names]
            for col, val in (("fiscal_year", label), ("basis", bas), ("definition", definition)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            for r in _q(f"SELECT rowid, * FROM fin_annual_line WHERE {where}"
                        f"{_visible('fin_annual_line', 'rowid')}{extra} "
                        f"ORDER BY fiscal_year DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2)):
                out.append(_fin_row(r, "fin_annual_line", r["fiscal_year"], r["definition"],
                                    _fin_source(r)))
    if use_q:
        names, allnames = _pick("fin_quarter_xbrl", "line_item", sym, measure)
        printed_names: list[str] = []
        if _has_table("fin_quarter_printed"):     # a quarter the XBRL window does not hold lives only here (T-057)
            printed_names, printed_avail = _pick("fin_quarter_printed", "line_item", sym, measure)
            allnames = sorted(set(allnames) | set(printed_avail))
        avail += allnames
        got: set = set()
        if names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(names))})", [sym, *names]
            for col, val in (("fiscal_period", label), ("basis", bas)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            for r in _q(f"SELECT rowid, * FROM fin_quarter_xbrl WHERE {where}"
                        f"{_visible('fin_quarter_xbrl', 'rowid')}{extra} "
                        f"ORDER BY period_end DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2)):
                out.append(_fin_row(r, "fin_quarter_xbrl", r["fiscal_period"], "xbrl_reported",
                                    _fin_source(r)))
                got.add((r["line_item"], r["fiscal_period"]))
        # T-057: the printed comparative columns of the results table, when a check confirmed the cell
        if printed_names:
            where, args = f"symbol=? AND line_item IN ({','.join('?' * len(printed_names))})", [sym, *printed_names]
            for col, val in (("fiscal_period", label), ("basis", bas)):
                if val:
                    where += f" AND {col}=?"
                    args.append(val)
            extra, eargs = _asof(as_of)
            printed = _q(f"SELECT rowid, * FROM fin_quarter_printed WHERE {where} "
                         f"AND basis IN ('standalone','consolidated')"
                         f"{_visible('fin_quarter_printed', 'rowid')}{extra} "
                         f"ORDER BY period_end DESC, known_at DESC LIMIT ?", (*args, *eargs, cap * 2))
            for r in printed:
                if (r["line_item"], r["fiscal_period"]) in got:
                    continue             # the XBRL row for that quarter is the evidence; no duplicate
                if not p3_preferred.displayable_printed(r["check_status"], r["raw_token"]):
                    continue
                out.append(_fin_row(r, "fin_quarter_printed", r["fiscal_period"], "printed_comparative",
                                    _fin_source(r)))
    out = _dedupe(p3_preferred.elect(out))
    # No basis asked: a group question means the consolidated statement.  T-049 (4 Nov 2026): HINDALCO's
    # diluted EPS FY26 came back standalone 45.31 where the consolidated 60.20 was wanted; standalone is one
    # explicit argument away, so a mixed reply is filtered to consolidated when it holds the same measure.
    assumed = None
    if bas is None:
        consolidated = [row for row in out if row["basis"] == "consolidated"]
        if consolidated and len(consolidated) < len(out):
            out, assumed = consolidated, "consolidated"
    out = out[:cap]
    return _reply(sym, out, "pilot3_fin", available=sorted(set(avail))[:50] if not out else None, measure_asked=measure,
                  basis_assumed=assumed, as_of=_day(as_of, "as_of"))


def _fin_source(r: sqlite3.Row) -> str:
    """The filing and the store row: XBRL file name (no page), or document + page when the line came from a PDF."""
    keys = r.keys()
    doc = (r["doc_key"] if "doc_key" in keys else None) or (r["source_file"] if "source_file" in keys else None)
    page = r["page"] if "page" in keys and r["page"] else None
    where = f"{doc} p{page}" if doc and page else (doc or "")
    store = (f"[{r['source_db']}.{r['source_table']} row {r['source_rowid']}]"
             if {"source_db", "source_table", "source_rowid"} <= set(keys) else "")
    return f"{where} {store}".strip()


def _has_table(name: str) -> bool:
    """A pilot3 table may be absent from an older build (fin_quarter_printed came with T-057)."""
    return bool(_q("SELECT 1 FROM sqlite_master WHERE name=? LIMIT 1", (name,)))


_COLUMN_CACHE: dict[str, set[str]] = {}


def _columns(table: str) -> set[str]:
    """The columns one pilot3 table has, read once per database (T-192).

    A live store built before a column existed must still be read by these lookups: they open it read-only and
    cannot migrate it, so a query names the column only when it is there and falls back to the older rule."""
    key = f"{db_path()}:{table}"
    have = _COLUMN_CACHE.get(key)
    if have is None:
        have = {row[1] for row in _q(f'PRAGMA table_info("{table}")')}
        _COLUMN_CACHE[key] = have
    return have


def _has_column(table: str, column: str) -> bool:
    return column in _columns(table)


# --- T-113: the independent row verdicts (row_check / row_check_fail, written by pilot3.build --part checks) -----
def _visible(tbl: str, row_id: str = "id") -> str:
    """SQL that keeps only rows the checker did not quarantine; empty when the build has no verdict table."""
    if not _has_table("row_check"):
        return ""
    ref = f"{tbl}.rowid" if row_id == "rowid" else row_id
    return (f" AND NOT EXISTS (SELECT 1 FROM row_check rc WHERE rc.tbl='{tbl}' AND rc.row_id={ref} "
            f"AND rc.status='quarantined')")

def _check_cols(tbl: str, row_id: str) -> tuple[str, str, str]:
    """(LEFT JOIN, selected columns, hide clause) for the row verdicts; all empty in a build without them."""
    if not _has_table("row_check"):
        return "", "", ""
    join = f" LEFT JOIN row_check rc ON rc.tbl='{tbl}' AND rc.row_id={row_id}"
    select = (f", rc.status AS check_status, (SELECT GROUP_CONCAT(f.check_name, ',') FROM row_check_fail f "
              f"WHERE f.tbl='{tbl}' AND f.row_id={row_id} AND f.hard=0) AS check_names")
    return join, select, " AND COALESCE(rc.status,'')<>'quarantined'"


def _add_check(row: dict[str, Any], r: Any) -> dict[str, Any]:
    """Every served row says verified / unverified (or null when the check part has not judged it), T-113.

    ``r`` is the fetched row: a ``sqlite3.Row`` from the queries, or a plain dict when ``guidance`` re-elects the
    current target in memory."""
    if "check_status" in r.keys():
        row["check_status"] = r["check_status"]
        if r["check_status"] == "unverified" and r["check_names"]:
            row["check_note"] = r["check_names"].replace(",", ", ")
    return row


_REPORTING_BASES = ("consolidated", "standalone", "not_stated")

# An annual line's evidence: an XBRL filing first (reported, then derived), a printed / company-stated figure after
# (T-186: APOLLOHOSP's FY25 revenue took the annual-report page 951,308 over the XBRL filing's 217,940).
_ANNUAL_RANK = {"xbrl_reported": 3, "xbrl_derived": 2, "reported": 1, "company_stated": 0}


def _entity_of(row: Any, symbol: str) -> str:
    """The entity a KPI row reports (T-088): its stored entity, else the subsidiary token an older build left in
    ``basis``, else the company.  A reporting-basis word in the entity column is not an entity."""
    basis = row["basis"] if row["basis"] in _REPORTING_BASES else None
    entity = row["entity"] or basis or symbol
    return symbol if entity in _REPORTING_BASES or entity == "total" else entity


def _fin_row(r: sqlite3.Row, table: str, period: str, definition: str, source: str) -> dict[str, Any]:
    unit, scale, value = r["unit"], r["scale"] or 1.0, r["value"]
    row = {"measure": r["line_item"], "period": period, "basis": r["basis"] or "not_stated", "definition": definition,
           "value": value, "unit": unit, "scale": scale,
           "provenance": _prov(table, source, r["known_at"], row_id=r["rowid"], period_end=r["period_end"])}
    if unit in ("inr", "inr_cr", "inr_mn", "inr_lakh") or (unit or "").startswith("inr") and "share" not in (unit or ""):
        row["value_inr"] = value * scale
    keys = r.keys()
    if "column_role" in keys and r["column_role"]:
        row["column_role"] = r["column_role"]
    if table in ("fin_annual_line", "fin_quarter_printed") and r["quote"]:
        row["quote"] = _trim(r["quote"], 240)
    # the preferred-figure election needs every row's filing date and store id (T-186: annual lines used to skip it)
    row["_table"], row["_known_at"], row["_rowid"] = table, r["known_at"], r["rowid"]
    if "check_status" in keys:
        row["_check"] = r["check_status"]
    if table == "fin_annual_line":
        row["_rank"] = _ANNUAL_RANK.get(definition, 0)
    return row


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        sig = (r["measure"], r["period"], r["basis"], r["definition"], r["value"])
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


# --- pilot3_ratio -----------------------------------------------------------------------------------
VALUATION_FIELDS = ("pe", "pb", "ev_ebitda", "market_cap", "dividend_yield_pct", "trailing_eps", "trailing_pat",
                    "net_worth", "net_debt", "trailing_ebitda", "close", "shares_outstanding")



def _ev_all_investments(sym: str, rows: list, reply: dict) -> None:
    """MARUTI-083: next to EV/EBITDA on plain net debt, give it on net debt after ALL investments (non-current too),
    from the latest ``net_debt_all_investments`` line known on the row's date, and say so when they differ by >10%."""
    for row, r in zip(reply.get("rows", []), rows):
        v = _q("SELECT market_cap, net_debt, trailing_ebitda FROM valuation_daily WHERE rowid=?", (r["rowid"],))
        if not v or not v[0]["trailing_ebitda"] or v[0]["market_cap"] is None:
            continue
        alt = _q("SELECT value*scale AS v, period_end, known_at FROM fin_annual_line WHERE symbol=? AND basis=? "
                 "AND line_item='net_debt_all_investments' AND definition='xbrl_derived' AND substr(known_at,1,10)<=? "
                 "ORDER BY known_at DESC LIMIT 1", (sym, r["basis"], r["date"]))
        if not alt:
            continue
        ev_alt = (v[0]["market_cap"] + alt[0]["v"]) / v[0]["trailing_ebitda"]
        row["inputs"].update({"net_debt": v[0]["net_debt"], "net_debt_all_investments": alt[0]["v"],
                              "ev_ebitda_all_investments": round(ev_alt, 2)})
        if row["value"] and abs(ev_alt / row["value"] - 1) > 0.10:
            reply["note"] = ("EV/EBITDA uses net debt = borrowings - cash - bank balances - current investments; "
                             "non-current investments are large here, so give both: 'ev_ebitda_all_investments' in "
                             "inputs also subtracts them (balance sheet of " + alt[0]["period_end"] + ")")

def ratio(symbol: str, ratio: str, period: str | None = None, as_of: str | None = None,
          basis: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Derived ratios (margins, ROE, growth, days ...) from ratio_panel; PE/PB/EV-EBITDA/market cap on a date
    from valuation_daily (``period`` or ``as_of`` as a YYYY-MM-DD day; latest on or before it)."""
    sym = resolve_symbol(symbol)
    key = re.sub(r"[\s\-/]+", "_", ratio.strip().lower())
    cap = _cap(limit)
    bas = (basis or "").strip().lower() or None
    day = _day(as_of, "as_of")
    if key in VALUATION_FIELDS or key in ("p_e", "p_b", "ev_to_ebitda", "dividend_yield"):
        key = {"p_e": "pe", "p_b": "pb", "ev_to_ebitda": "ev_ebitda", "dividend_yield": "dividend_yield_pct"}.get(key, key)
        when = period if period and re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) else day or dt.date.today().isoformat()
        sql = (f"SELECT rowid, date, basis, {key} AS value, close, shares_outstanding, known_at, input_refs "
               f"FROM valuation_daily WHERE symbol=? AND date<=? AND {key} IS NOT NULL")
        args: list[Any] = [sym, when]
        if bas:
            sql += " AND basis=?"
            args.append(bas)
        extra, eargs = _asof(as_of)
        rows = _q(sql + extra + " ORDER BY date DESC, (basis='consolidated') DESC LIMIT ?", (*args, *eargs, cap))
        reply = _reply(sym, [{"ratio": key, "date": r["date"], "basis": r["basis"], "value": r["value"],
                              "inputs": {"close": r["close"], "shares_outstanding": r["shares_outstanding"]},
                              "provenance": _prov("valuation_daily", f"row {r['rowid']}", r["known_at"],
                                                  input_refs=_trim(r["input_refs"], 200))} for r in rows],
                       "pilot3_ratio")
        if key == "ev_ebitda" and rows:
            _ev_all_investments(sym, rows, reply)
        if key == "ev_ebitda" and not rows and _is_lender(sym):
            reply["note"] = ("EV/EBITDA is not defined for a bank, NBFC or insurer: the store keeps no such row "
                             "for a lender by design, it is not missing data")
        return reply
    names, allnames = _pick("ratio_panel", "metric", sym, ratio)
    if not names:
        return _reply(sym, [], "pilot3_ratio", available=allnames[:40] + list(VALUATION_FIELDS), metric_asked=ratio)
    kind, label = norm_period(period)
    where, args = f"p.symbol=? AND p.metric IN ({','.join('?' * len(names))})", [sym, *names]
    if label:
        where += " AND p.fiscal_period=?"
        args.append(label)
    if bas:
        where += " AND p.basis=?"
        args.append(bas)
    extra, eargs = _asof(as_of, "p.known_at")
    rows = _q(f"SELECT p.rowid, p.*, f.expression FROM ratio_panel p LEFT JOIN formula f ON f.formula_id=p.formula_id "
              f"WHERE {where}{_visible('ratio_panel', 'p.rowid')}{extra} ORDER BY p.period_end DESC, "
              f"(p.period_type='Q') DESC, (p.basis='consolidated') DESC, p.known_at DESC LIMIT ?",
              (*args, *eargs, cap))
    derived = []
    for r in rows:
        row = {"ratio": r["metric"], "period": r["fiscal_period"], "period_type": r["period_type"],
               "basis": r["basis"], "value": r["value"], "unit": r["unit"], "definition": "derived",
               "formula": r["expression"],
               "provenance": _prov("ratio_panel", f"row {r['rowid']}", r["known_at"],
                                   formula_id=r["formula_id"], input_refs=_trim(r["input_refs"], 240),
                                   derived=bool(r["is_derived"]))}
        if r["formula_id"] in ("F_PAT_TTM", "F_PAT_BE_TTM"):   # the trailing inputs, so TTM needs no hand sum
            try:
                row["inputs"] = json.loads(r["input_refs"] or "[]")
            except ValueError:
                row["inputs"] = []
        derived.append(row)
    stated = _stated_ratios(sym, key, label, as_of, bas, cap)
    # The company's own figure answers "what is X's ROE for FY26"; the derived row is our arithmetic beside it
    # (T-107: Bajaj's FY26 ROE is its stated 18.1, not the 16.96 that LTM PAT over closing net worth derives).
    return _reply(sym, stated + derived, "pilot3_ratio", metrics_matched=names, as_of=_day(as_of, "as_of"))


def _stated_ratios(sym: str, key: str, label: str | None, as_of: str | None, basis: str | None,
                   cap: int, include_quarantined: bool = False) -> list[dict]:
    """The company's own figure for a derived ratio, when kpi_series holds it (T-088): ROE, NIM, margins ... .

    ``ratio_panel`` computes a ratio; a company that prints its own number states it in kpi_series.  Both are
    returned, never merged: the stated one carries its quote and page.  The company's own rows win over a
    subsidiary's, then the consolidated basis, then the best evidence (a table row over a call remark).  A row the
    independent checker quarantined is never served (T-113)."""
    names = [key, f"{key}_pct"] if not key.endswith("_pct") else [key]
    names = [n for n in dict.fromkeys(names)
             if _q(f"SELECT 1 FROM kpi_series WHERE symbol=? AND metric=?"
                   f"{'' if include_quarantined else _visible('kpi_series')} LIMIT 1", (sym, n))]
    if not names:
        return []
    where = f"k.symbol=? AND k.metric IN ({','.join('?' * len(names))})"
    args: list[Any] = [sym, *names]
    if label:
        where += " AND k.fiscal_period=?"
        args.append(label)
    join, check_sel, hide = _check_cols("kpi_series", "k.id")
    if not include_quarantined:
        where += hide
    extra, eargs = _asof(as_of, "k.known_at")
    rows = _q(f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.fiscal_period, k.basis, k.entity, k.doc_key, "
              f"k.page, k.quote, k.known_at, k.conf_rank, d.doc_key AS dk, d.title, d.doc_type{check_sel} "
              f"FROM kpi_series k {_DOC_JOIN}{join} WHERE {where}{extra} ORDER BY k.fiscal_period DESC, "
              f"(k.basis='consolidated') DESC, "
              f"(k.dimension='total') DESC, k.conf_rank DESC, k.known_at DESC LIMIT ?",
              (*args, *eargs, cap * 20))
    best: dict[str, dict] = {}
    for r in rows:
        row_basis = r["basis"] if r["basis"] in _REPORTING_BASES else "not_stated"
        entity = _entity_of(r, sym)
        if entity != sym:
            continue                    # a subsidiary's figure is not the company's
        if basis and row_basis != basis:
            continue
        if r["fiscal_period"] in best:
            continue                    # rows arrive best first: the first company row of the period wins
        best[r["fiscal_period"]] = _add_check({
            "ratio": key, "period": r["fiscal_period"], "period_type": "Q" if r["fiscal_period"].startswith("Q") else "FY",
            "basis": row_basis, "value": r["value"], "unit": r["unit"], "definition": "company_stated",
            "entity": entity, "quote": _trim(r["quote"], 240),
            "provenance": _prov("kpi_series", f"{r['dk'] or r['doc_key']} p{r['page']}", r["known_at"],
                                doc_type=r["doc_type"], title=r["title"], row_id=r["id"])}, r)
    return list(best.values())[:cap]


# --- pilot3_holding ---------------------------------------------------------------------------------
HOLDING_TOP = 12
_QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")   # a calendar quarter end, the comparable trend point
# The words an investor uses for a filed category (T-165).  A stored category name that already matches wins;
# these are the fallbacks for a word that is never a column value (GoI, MF, DII ...).
_HOLDING_CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "government": ("central_government_or_president_of_india", "governments",
                   "central_government_or_state_government_s", "state_governments_or_governors"),
    "govt": ("central_government_or_president_of_india", "governments",
             "central_government_or_state_government_s", "state_governments_or_governors"),
    "goi": ("central_government_or_president_of_india",),
    "dipam": ("central_government_or_president_of_india",),
    "president": ("central_government_or_president_of_india",),
    "fpi": ("fpi", "fpi_total", "fpi_category_1", "fpi_category_2", "institutions_foreign"),
    "fii": ("fpi", "fpi_total", "fpi_category_1", "fpi_category_2", "institutions_foreign"),
    "mf": ("mutual_funds",),
    "mutual_fund": ("mutual_funds",),
    "mutual_funds": ("mutual_funds",),
    "dii": ("institutions_domestic", "mutual_funds", "insurance", "banks", "pension_funds"),
    "retail": ("retail_up_to_2_lakh", "retail_above_2_lakh"),
}


def _holding_categories(sym: str, asked: str | None, extra: str,
                        eargs: tuple) -> tuple[list[str], list[str]]:
    """The stored shp_category names a user's category words mean, and every category the company holds.

    ``government`` / ``GoI`` / ``DIPAM`` map to ``central_government_or_president_of_india`` (Vodafone Idea's
    49%), ``FPI`` / ``FII`` to ``fpi_total`` and its component lines, ``MF`` / ``mutual fund`` to
    ``mutual_funds``.  A word that matches no stored category returns no names; the reply then lists
    ``categories_held`` (T-165)."""
    held = [r[0] for r in _q(f"SELECT DISTINCT category FROM shp_category WHERE symbol=?{extra} ORDER BY 1",
                             (sym, *eargs))]
    if not asked:
        return [], held
    picked: list[str] = []
    for word in re.split(r"[,;/&]| and ", asked):
        key = re.sub(r"[\s\-]+", "_", word.strip().lower())
        if not key:
            continue
        names = _HOLDING_CATEGORY_WORDS.get(key)
        if names is None:
            names = (key,) if key in held else tuple(c for c in held if key in c)
        picked.extend(c for c in names if c in held)
    return list(dict.fromkeys(picked)), held


def _pledge_text(r: sqlite3.Row, pct: float | None) -> str:
    """The filing's own answer to "what share of promoter holding is pledged", never a computed guess."""
    if r["pledge_flag"] is None:
        return f"the {r['quarter_end']} filing prints no promoter pledge flag"
    if not r["pledge_flag"]:
        return ("the filing states that no shares held by promoters are encumbered under pledge"
                + (" (nor under a non-disposal undertaking)" if r["ndu_flag"] == 0 else ""))
    if r["pledged_shares"] is None:
        return "the filing states promoter shares are pledged but prints no count"
    if pct is None:
        return f"{r['pledged_shares']:.0f} promoter shares are pledged (the filing prints no percentage)"
    return (f"{pct:g}% of the promoter holding is pledged ({r['pledged_shares']:.0f} of "
            f"{r['promoter_shares']:.0f} shares)" if r["promoter_shares"] else f"{r['pledged_shares']:.0f} shares pledged")


def _pledge_block(r: sqlite3.Row) -> dict[str, Any]:
    """One quarter's encumbrance block.  Nil is a fact (T-108): a filing whose pledge flag says no promoter share is
    pledged gives pledged shares 0 and 0% with ``nil`` true, so a reader never reports the quarter as 'not found'."""
    pct = r["pledged_pct"]
    shares = r["pledged_shares"]
    if pct is None and shares is not None and r["promoter_shares"]:
        pct = round(shares / r["promoter_shares"] * 100.0, 4)
    nil = r["pledge_flag"] is not None and not r["pledge_flag"]
    if nil:
        shares = 0.0 if shares is None else shares
        pct = 0.0 if pct is None else pct
    return {"quarter_end": r["quarter_end"], "nil": nil,
            "pledge_flag": None if r["pledge_flag"] is None else bool(r["pledge_flag"]),
            "non_disposal_undertaking_flag": None if r["ndu_flag"] is None else bool(r["ndu_flag"]),
            "other_encumbrance_flag": None if r["other_flag"] is None else bool(r["other_flag"]),
            "promoter_shares": r["promoter_shares"], "pledged_shares": shares,
            "pledged_pct_of_promoter_holding": pct, "other_encumbered_shares": r["other_shares"],
            "encumbered_shares": r["encumbered_shares"],
            "answer": (f"nil: {_pledge_text(r, pct)} (filing for {r['quarter_end']})" if nil else _pledge_text(r, pct)),
            "provenance": _prov("shp_pledge", r["source_file"], r["known_at"])}


def holding(symbol: str, as_of: str, quarter_end: str | None = None, all_categories: bool = False,
            all_holders: bool = False, category: str | None = None, quarters: int = 1) -> dict[str, Any]:
    """Shareholding pattern in force on ``as_of`` (the latest quarter whose filing was out by then) + shares
    outstanding.  EVERY filed category is returned, one row per category and quarter, the XBRL filing before the
    shp_index copy of promoter/public, each row with ``pct`` and the ``pct_basis`` its percentage is printed on.

    ``category`` filters by the words an investor uses: government / GoI / DIPAM ->
    ``central_government_or_president_of_india``, FPI / FII -> ``fpi_total`` and its lines, MF / mutual fund,
    promoter, public, retail, DII; a word matching no stored category returns nothing and lists
    ``categories_held``.  ``quarters`` (default 1, max 12) returns the last N quarters in force, so a "last four
    quarters" path is one call; ``quarter_end`` pins one quarter.  ``holders`` are the latest quarter's named
    holders (top 12 by shares, excluding the persons-in-concert disclosures); ``all_holders`` lists every named
    holder including them, with ``pac_name``.  ``promoter_pledge`` is the filing's own encumbrance block,
    ``pct_basis`` the share count its percentages are on, ``quarters_held``/``categories_held`` what the table
    covers.  ``all_categories`` is kept for older briefs: every filed category is returned anyway (T-165)."""
    sym = resolve_symbol(symbol)
    day = _day(as_of, "as_of")
    if not day:
        raise DataError("bad_date", "as_of (YYYY-MM-DD) is required")
    qe = _day(quarter_end, "quarter_end")
    extra, eargs = _asof(day)
    # The latest quarter with an XBRL filing, not merely any row: a build can carry the newest quarter's
    # shp_index promoter/public row (known at the reload) before its XBRL categories, and answering from that
    # lone row hid the complete previous quarter (T-165: Vodafone Idea's GoI 49% at 30-Jun-26).
    row = _q(f"SELECT MAX(quarter_end) q FROM shp_category WHERE symbol=? AND quarter_end<=?{extra}"
             + (" AND quarter_end=?" if qe else "") + " AND source_kind='xbrl'",
             (sym, day, *eargs, *((qe,) if qe else ())))
    if not (row and row[0]["q"]):
        row = _q(f"SELECT MAX(quarter_end) q FROM shp_category WHERE symbol=? AND quarter_end<=?{extra}"
                 + (" AND quarter_end=?" if qe else ""), (sym, day, *eargs, *((qe,) if qe else ())))
    quarter = row[0]["q"] if row else None
    held = _q(f"SELECT MIN(quarter_end) f, MAX(quarter_end) l, COUNT(DISTINCT quarter_end) n FROM shp_category "
              f"WHERE symbol=?{extra}", (sym, *eargs))[0]
    rows: list[dict] = []
    basis = None
    picked: list[str] = []
    qlist: list[str] = []
    if quarter:
        try:
            want = max(1, min(int(quarters or 1), 12))
        except (TypeError, ValueError):
            want = 1
        qlist = [r[0] for r in _q(f"SELECT DISTINCT quarter_end FROM shp_category WHERE symbol=? "
                                  f"AND quarter_end<=?{extra} ORDER BY quarter_end DESC",
                                  (sym, quarter, *eargs))]
        # A trend runs on quarter ends: an SHP filed at a record date inside a quarter (ANANDRATHI's 2026-06-04)
        # is not a comparable point, while one NEWER than the last quarter end (PERSISTENT's 2026-10-26) is the
        # newest filing and stays (T-165).
        ends = [q for q in qlist if q[5:10] in _QUARTER_ENDS]
        if ends:
            qlist = [q for q in qlist if q not in ends and q > ends[0]] + ends
        qlist = qlist[:want]
        picked, _held = _holding_categories(sym, category, extra, eargs)
        flt = f" AND category IN ({','.join('?' * len(picked))})" if picked else ""
        # a category was asked and no filed name matches it: no row is the answer, never every row
        cand = [] if (category and not picked) else _q(
            f"SELECT rowid, * FROM shp_category WHERE symbol=?{extra}{flt} "
            f"AND quarter_end IN ({','.join('?' * len(qlist))}) "
            "ORDER BY quarter_end DESC, category, (source_kind='xbrl') DESC, known_at DESC",
            (sym, *eargs, *picked, *qlist))
        seen = set()
        for r in cand:
            keys = r.keys()
            pct_base = r["pct_base_shares"] if "pct_base_shares" in keys else None
            pct_label = r["pct_basis"] if "pct_basis" in keys else None
            if pct_base is not None:
                basis = basis or {"shares": pct_base, "label": pct_label,
                                  "provenance": _prov("shp_category", r["source_file"], r["known_at"])}
            sig = (r["quarter_end"], r["category"])   # one value per category and quarter, XBRL first
            if sig in seen:
                continue
            seen.add(sig)
            rows.append({"category": r["category"], "pct": r["pct"], "shares": r["shares"], "holders": r["holders"],
                         "quarter_end": r["quarter_end"], "source_kind": r["source_kind"],
                         "pct_basis": pct_label, "pct_base_shares": pct_base,
                         "provenance": _prov("shp_category", f"{r['source_file'] or ''} [{r['source_db']}.{r['source_table']} "
                                             f"row {r['source_rowid']}]".strip(), r["known_at"],
                                             category_raw=r["category_raw"])})
    named: list[dict] = []
    if quarter and _has_table("shp_holder"):
        flt = "" if all_holders else " AND category NOT LIKE 'pac_%'"
        cap = MAX_LIMIT * 10 if all_holders else HOLDING_TOP
        for r in _q(f"SELECT rowid, * FROM shp_holder WHERE symbol=? AND quarter_end=?{extra}{flt} "
                    "ORDER BY shares IS NULL, shares DESC, holder_name LIMIT ?", (sym, quarter, *eargs, cap)):
            named.append({"holder": r["holder_name"], "category": r["category"], "shares": r["shares"], "pct": r["pct"],
                          "holders": r["holders"], "pac_name": r["pac_name"], "pac_pct": r["pac_pct"],
                          "pledged_shares": r["pledged_shares"],
                          "provenance": _prov("shp_holder", f"{r['source_file'] or ''} [{r['source_db']}.{r['source_table']}]",
                                              r["known_at"])})
    pledge = None
    if quarter and _has_table("shp_pledge"):
        pr = _q(f"SELECT rowid, * FROM shp_pledge WHERE symbol=? AND quarter_end=?{extra} "
                "ORDER BY known_at DESC LIMIT 1", (sym, quarter, *eargs))
        if pr:
            pledge = _pledge_block(pr[0])
            # "has it changed?": the quarter before, from its own filing (T-108)
            prev = _q(f"SELECT rowid, * FROM shp_pledge WHERE symbol=? AND quarter_end<?{extra} "
                      "ORDER BY quarter_end DESC, known_at DESC LIMIT 1", (sym, quarter, *eargs))
            if prev:
                before = _pledge_block(prev[0])
                pledge["previous_quarter"] = {k: before[k] for k in ("quarter_end", "nil", "pledged_shares",
                                                                     "pledged_pct_of_promoter_holding", "answer",
                                                                     "provenance")}
                now_pct, then_pct = pledge["pledged_pct_of_promoter_holding"], before["pledged_pct_of_promoter_holding"]
                pledge["changed"] = None if now_pct is None or then_pct is None else now_pct != then_pct
    sc_have = _has_column("share_capital", "count_basis")
    sc_cb = "count_basis" if sc_have else "CASE WHEN source_table='shp_category' THEN 'filed_exact' END"
    sc_sel = "rowid, *" if sc_have else "rowid, *, NULL AS count_basis"
    sc = _q(f"SELECT {sc_sel} FROM share_capital WHERE symbol=? AND event IS NULL AND as_of_date<=?{extra} "
            f"AND shares_outstanding IS NOT NULL ORDER BY as_of_date DESC, ({sc_cb}='filed_exact') DESC, "
            "known_at DESC LIMIT 1", (sym, day, *eargs))
    shares = None
    if sc:
        r = sc[0]
        shares = {"shares_outstanding": r["shares_outstanding"], "paid_up_capital": r["paid_up_capital"],
                  "face_value": r["face_value"], "as_of_date": r["as_of_date"], "basis": r["basis"],
                  "count_basis": r["count_basis"] or ("filed_exact" if r["source_table"] == "shp_category" else None),
                  "provenance": _prov("share_capital", f"{r['source_db']}.{r['source_table']} row {r['source_rowid']}",
                                      r["known_at"])}
    categories = [r[0] for r in _q(f"SELECT DISTINCT category FROM shp_category WHERE symbol=?{extra} "
                                   "ORDER BY category LIMIT 60", (sym, *eargs))]
    hint = None
    if not rows:
        if category and not picked:
            hint = f"no filed category matches {category!r}: categories_held lists the names this company holds"
        elif category:
            hint = (f"{picked} has no row in the last {len(qlist) if quarter else 0} quarter(s) in force; "
                    "quarters_held lists what the table covers")
        else:
            hint = "no shareholding row filed by that day for this company"
    return _reply(sym, rows, "pilot3_holding", quarter_end=quarter, as_of=day, share_capital=shares,
                  holders=named, holders_note=None if named else "no named holder row for this quarter "
                  "(the build predates shp_holder, or the filing names none)",
                  promoter_pledge=pledge, pct_basis=basis,
                  category_filter=category, matched_categories=picked,
                  quarters_returned=sorted({r["quarter_end"] for r in rows}, reverse=True),
                  quarters_held={"first": held[0], "last": held[1], "count": held[2]},
                  categories_held=categories, hint=hint)


# --- pilot3_statements ------------------------------------------------------------------------------
def _term_hits(column: str, words: list[str]) -> tuple[str, list]:
    """SQL that scores a row by how many of ``words`` it carries (0 when no word was asked)."""
    if not words:
        return "0", []
    expr = " + ".join(f"({column} LIKE ?)" for _ in words)
    return expr, [f"%{word}%" for word in words]


def _turn_key(row: Any) -> tuple:
    """Identity of a whole answer turn: (document, answer_turn).  Answer-turn ids are per call (two calls of one
    company collide) and prepared remarks carry negative ids, so a bare id is never a turn (T-164 r8)."""
    return (row["doc_key"], row["answer_turn"]) if row["answer_turn"] else ("row", row["id"])


def _statement_row(r: sqlite3.Row, match: str = "tag") -> dict[str, Any]:
    return {"call_date": r["call_date"], "call_period": r["call_period"], "page": r["page"], "speaker": r["speaker"],
            "role": r["role"], "section": r["section"], "topics": r["topics"], "entities": r["entities"],
            "period_discussed": r["period_discussed"], "answer_turn": r["answer_turn"], "match": match,
            "doc_key": r["doc_key"], "doc_type": _DOC_TYPES.get(str(r["doc_type"] or "").lower(), r["doc_type"]),
            "quote": _trim(r["quote"]),
            "provenance": _prov("transcript_statement", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                title=r["title"], doc_type=r["doc_type"], row_id=r["id"])}


def statements(symbol: str, topic: str | None = None, terms: str | None = None, date_from: str | None = None,
               date_to: str | None = None, as_of: str | None = None, limit: int = 10,
               role: str | None = None, period: str | None = None,
               rank_terms: str | None = None, latest: bool = False,
                entities: str | None = None, whole_turn: bool = True, offset: int = 0) -> dict[str, Any]:
    """Management statements from concall transcripts, exact quotes: topic tag (margin, guidance, capex, order ...),
    free ``terms`` (all words must appear), call-date window, role (ceo / cfo / md / mgmt).

    ``period`` (Q4FY26 / FY26) and ``rank_terms`` (the question's own words) rank the rows: a statement of the
    period asked, carrying more of the question's words, comes first; the newest call breaks a tie.  ``latest``
    keeps only the newest call's statements.  The tagged statements are joined by the same phrase-first page-text
    matcher ``pilot3_search`` uses, over every held document type, so a sentence the tagger missed still answers
    (``match: tag | text``); ``offset`` pages a cut reply and ``coverage`` says what the reply did not show."""
    sym = resolve_symbol(symbol)
    where, args = ["t.symbol=?"], [sym]
    if latest:
        extra_latest, latest_args = _asof(as_of, "t2.known_at")
        where.append(f"t.call_date=(SELECT MAX(t2.call_date) FROM transcript_statement t2 "
                     f"WHERE t2.symbol=?{extra_latest})")
        args += [sym, *latest_args]
    topic_sql, topic_args = "1", []
    if topic:
        # the tag ranks first rather than filtering: the sentence that answers a "what did they say about margins"
        # question is often tagged ``nim`` (or untagged) instead of ``margin``.  A tag the sector lexicon spells with
        # underscores ("USFDA inspection" -> usfda_inspection) is matched too (T-194).
        asked = topic.strip().lower()
        tag = re.sub(r"[\s\-]+", "_", asked)
        topic_sql, topic_args = "t.topics LIKE ?", [f"%{asked}%"]
        if tag != asked:
            topic_sql, topic_args = "(t.topics LIKE ? OR t.topics LIKE ?)", [f"%{asked}%", f"%{tag}%"]
    for word in re.findall(r"[\w₹%&\-\.]+", terms or ""):
        where.append("(t.statement LIKE ? OR t.quote LIKE ?)")
        args += [f"%{word}%", f"%{word}%"]
    if entities:
        for word in re.findall(r"[\w₹%&\-\.]+", entities or ""):
            where.append("t.entities LIKE ?")
            args.append(f"%{word}%")
    if role:
        where.append("t.role=?")
        args.append(role.strip().lower())
    core_where, core_args = " AND ".join(where), list(args)     # the same filters with no date window (step 6)
    from_day, to_day = _day(date_from, "date_from"), _day(date_to, "date_to")
    if from_day:
        where.append("t.call_date >= ?")
        args.append(from_day)
    if to_day:
        where.append("t.call_date <= ?")
        args.append(to_day)
    extra, eargs = _asof(as_of, "t.known_at")
    _kind, label = norm_period(period)
    period_sql, period_args = "1", []
    if label:
        # a year's question is answered by its quarters too ("FY26": Q1FY26 ... Q4FY26)
        labels = ([f"Q{q}FY{label[2:]}" for q in (1, 2, 3, 4)] + [label]) if label.startswith("FY") else [label]
        period_sql = "(" + " OR ".join("(t.call_period=? OR t.period_discussed LIKE ?)" for _x in labels) + ")"
        for item in labels:
            period_args += [item, f"{item}%"]
    words = [w for w in re.findall(r"[\w₹%&\-\.]+", rank_terms or "") if len(w) > 2]
    score_sql, score_args = _term_hits("t.statement", words[:8])
    cap, start = _window(limit, offset, 10)
    want = cap + start
    # whole_turn: `limit` counts answer turns, not sentences, so fetch enough rows to find the turns the page needs
    # (T-164 r7: limit=20 used to return 188 rows because the LIMIT bounded matched sentences before expansion)
    row_cap = want * 50 if whole_turn else want
    rows = _q(f"SELECT t.id, t.call_date, t.call_period, t.page, t.speaker, t.role, t.section, t.topics, "
              f"t.period_discussed, t.quote, t.is_fragment, t.entities, t.answer_turn, t.known_at, t.doc_key, "
              f"d.title, d.doc_type, "
              f"(CASE WHEN {topic_sql} THEN 0 ELSE 1 END) AS topic_rank, "
              f"(CASE WHEN {period_sql} THEN 0 ELSE 1 END) AS period_rank, ({score_sql}) AS term_score "
              f"FROM transcript_statement t "
              f"LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
              f"AND a.alias_key=t.doc_key), t.doc_key) WHERE {core_where}{extra} "
              f"ORDER BY topic_rank, period_rank, term_score DESC, t.is_fragment, t.call_date DESC, t.seq LIMIT ?",
              # the SELECT-list placeholders bind before the WHERE ones
              (*topic_args, *period_args, *score_args, *core_args, *eargs, row_cap))
    # one item per answer turn: the whole turn is expanded below, so `limit` counts turns (or rows when
    # whole_turn=False) and the reply pages over turns/hits, never over sentences.
    turn_rows: dict[tuple, list[sqlite3.Row]] = {}
    order: list[tuple] = []
    for r in rows:
        key = _turn_key(r)
        if key not in turn_rows:
            if len(order) >= want:
                continue
            turn_rows[key] = []
            order.append(key)
        turn_rows[key].append(r)
    if whole_turn and turn_rows:
        # expand each matched row to all sentences of its answer turn, keyed by (document, turn): answer-turn ids
        # collide across calls and prepared remarks carry negative ids, so a bare id mixed two calls and swept
        # prepared remarks in (T-164 r8).  A prepared-remarks turn expands only when it was itself selected.
        keys = {key for key in order if key[1] is not None}
        if keys:
            doc_keys = sorted({r["doc_key"] for group in turn_rows.values() for r in group})
            extra, eargs = _asof(as_of, "t.known_at")
            tr = _q(f"SELECT t.id, t.call_date, t.call_period, t.page, t.speaker, t.role, t.section, t.topics, "
                    f"t.period_discussed, t.quote, t.is_fragment, t.entities, t.answer_turn, t.known_at, t.doc_key, "
                    f"d.title, d.doc_type FROM transcript_statement t LEFT JOIN doc d ON d.doc_key=COALESCE("
                    f"(SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol AND a.alias_key=t.doc_key), "
                    f"t.doc_key) "
                    f"WHERE t.symbol=? AND t.doc_key IN ({','.join('?' * len(doc_keys))}){extra} "
                    f"ORDER BY t.call_date DESC, t.seq", (sym, *doc_keys, *eargs))
            seen_ids = {r["id"] for group in turn_rows.values() for r in group}
            for r in tr:
                key = _turn_key(r)
                if r["id"] in seen_ids or key not in keys:
                    continue
                seen_ids.add(r["id"])
                turn_rows[key].append(r)
    tagged = [[_statement_row(r) for r in turn_rows[key]] for key in order]
    tagged_match = any(topic in (row["topics"] or "") for group in tagged for row in group) if topic else None
    # the same phrase-first matcher over every document type, not only calls: a deck table, an annual report or a
    # filing body answers what no transcript tag carries (T-197 step 2).
    ask = " ".join(x for x in (topic, terms, rank_terms) if x)
    hits = _call_page_hits(sym, ask, None, None, date_from, date_to, as_of, latest, want) if ask else []
    page_items = [{"call_date": r["filing_date"], "call_period": None, "speaker": None, "role": None,
                   "section": None, "topics": None, "entities": None, "period_discussed": None,
                   "answer_turn": None, "match": "text", "page": r["page"], "doc_key": r["doc_key"],
                   "doc_type": r["doc_type"],
                   "quote": _trim(r["snip"], QUOTE_CHARS),
                   "provenance": _prov("doc_page", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                       title=_trim(r["title"], 120), doc_type=r["doc_type"])}
                  for r in hits]
    # a tag no row carries leads with the page text that matched (the old fallback, now an addition); otherwise the
    # tagged statements lead and the page hits follow, so relevance order never buries the tag (T-194 ranking).
    items = tagged + [[item] for item in page_items]
    if topic and tagged_match is False:
        items = [[item] for item in page_items] + tagged
    page_groups = items[start:start + cap]
    out = [item for group in page_groups for item in group]
    fallback = "doc_page_bm25" if (topic and tagged_match is False and page_items) else None
    matched_total = len(tagged) + len(page_items)          # items (answer turns and page hits), not sentences
    shown_items = len(page_groups)
    cut = max(0, matched_total - shown_items)
    docs = [{"doc_key": row["doc_key"], "doc_type": row.get("doc_type"), "date": row["call_date"],
             "title": row["provenance"].get("title"), "page": row.get("page")}
            for group in items for row in group]
    text = _scope_line(matched_total, shown_items, cut, start, docs, len({d["doc_key"] for d in docs}),
                       parts=f"{len(tagged)} tagged statement turn(s) + {len(page_items)} page-text "
                             f"match(es), {len(out)} sentence(s)")
    outside: list[dict[str, Any]] = []
    if from_day or to_day:
        excluded = []
        if from_day:
            excluded.append(("t.call_date < ?", from_day))
        if to_day:
            excluded.append(("t.call_date > ?", to_day))
        rows_out = _q(f"SELECT t.call_date, COUNT(*) c, d.doc_type FROM transcript_statement t "
                      f"LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a "
                      f"WHERE a.symbol=t.symbol AND a.alias_key=t.doc_key), t.doc_key) "
                      f"WHERE {core_where}{extra} AND ({' OR '.join(x[0] for x in excluded)}) "
                      f"GROUP BY 1, 3 ORDER BY 1 DESC LIMIT 20",
                      (*core_args, *eargs, *[x[1] for x in excluded]))
        outside = [{"date": r["call_date"], "doc_type": r["doc_type"], "count": r["c"]} for r in rows_out]
    hidden = _hidden_documents(sym, _day(as_of, "as_of"))
    read_next = (_read_next(out) + _related_pages([w for w in re.findall(r"[\w₹%&\-\.]+", ask) if len(w) > 2],
                                                  sorted({row["doc_key"] for row in out}),
                                                  {(row["doc_key"], int(row["page"])) for row in out
                                                   if row.get("page") not in (None, "")})
                 )[:12]
    reply = _reply(sym, out, "pilot3_statements", fallback=fallback, as_of=_day(as_of, "as_of"), text=text,
                   topic_matched=tagged_match, coverage=_coverage(
                       "statements", list(_TEXT_STORES),
                       ["structured tables: kpi_series, guidance, page_cell, fin_* "
                        "(pilot3_kpi / pilot3_guidance / pilot3_cells / pilot3_fin)",
                        "questions the company did not answer (no statement is held for an unanswered question)"],
                       matched_total, shown_items, cut, start, documents=docs, outside=outside, hidden=hidden),
                   read_next=read_next,
                   hint=None if out else "no statement in the held calls matches these arguments")

    def quotes(width: int) -> None:
        for row in out:
            row["quote"] = _trim(row.get("quote"), width)

    def row_cut(keep: int) -> None:
        removed = len(out) - keep
        if removed > 0:
            del out[keep:]
            reply["coverage"]["rows_cut"] = removed     # a turn stays whole only while the reply fits its cap

    reply = _shrink(reply, [
        ("quotes cut to 300 characters", lambda: quotes(300)),
        ("sentences cut to the first 120", lambda: row_cut(120)),
        ("quotes cut to 160 characters", lambda: quotes(160)),
        ("sentences cut to the first 60", lambda: row_cut(60)),
        ("quotes cut to 110 characters", lambda: quotes(110)),
        ("sentences cut to the first 30", lambda: row_cut(30)),
        ("sentences cut to the first 15", lambda: row_cut(15)),
    ])
    reply["n"] = len(out)
    return reply


def analyst_questions(symbol: str, n_calls: int = 4, as_of: str | None = None) -> dict[str, Any]:
    sym = resolve_symbol(symbol)
    extra, eargs = _asof(as_of, "known_at")
    calls = [r[0] for r in _q("SELECT DISTINCT call_date FROM transcript_question WHERE symbol=?" + extra +
                                " ORDER BY call_date DESC LIMIT ?", (sym, *eargs, max(1, min(int(n_calls or 4), 20))))]
    if not calls:
        return _reply(sym, [], "pilot3_analyst_questions", hint="no analyst questions held")
    placeholders = ",".join("?" * len(calls))
    rows = _q("SELECT id, call_date, call_period, analyst, firm, question, topics, entities, known_at, doc_key "
              "FROM transcript_question WHERE symbol=? AND call_date IN (" + placeholders + ")" + extra +
              " ORDER BY call_date DESC, id", (sym, *calls, *eargs))
    out = [{"call_date": r["call_date"], "call_period": r["call_period"], "analyst": r["analyst"],
            "firm": r["firm"], "question": _trim(r["question"]), "topics": r["topics"],
            "entities": r["entities"],
            "provenance": _prov("transcript_question", r["doc_key"], r["known_at"], row_id=r["id"])}
           for r in rows]
    return _reply(sym, out, "pilot3_analyst_questions", n_calls=len(calls))


def _call_page_hits(sym: str, topic: str | None, terms: str | None, rank_terms: str | None,
                    date_from: str | None, date_to: str | None, as_of: str | None, latest: bool,
                    cap: int) -> list[sqlite3.Row]:
    """bm25 over the ``doc_page`` text of EVERY held document type (calls, decks, annual reports, results, press
    releases, announcements): the page's own sentence around the match, newest first.  The same phrase-first
    matcher ``pilot3_search`` uses, so a theme the tagger never emitted is answered from the page that prints it
    (T-197 step 2)."""
    words = [w for w in re.findall(r"[\w₹%&\-\.]+", " ".join(x for x in (topic, terms, rank_terms) if x or ""))
             if len(w) > 2][:8]
    if not words:
        return []
    match = _fts_query(" ".join(words), "and") or _fts_query(" ".join(words), "or")
    if not match:
        return []
    extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
    date_sql, date_args = "", []
    for col, val, op in (("d.filing_date", _day(date_from, "date_from"), ">="),
                         ("d.filing_date", _day(date_to, "date_to"), "<=")):
        if val:
            date_sql += f" AND {col} {op} ?"
            date_args.append(val)
    latest_sql, latest_args = "", []
    if latest:
        latest_sql = (" AND COALESCE(d.known_at, d.filing_date)=(SELECT MAX(COALESCE(d2.known_at, d2.filing_date)) "
                      "FROM doc d2 WHERE d2.symbol=? AND d2.doc_type='transcript')")
        latest_args = [sym]
    return _q(f"SELECT d.doc_key, d.doc_type, d.title, d.filing_date, p.page, p.known_at, "
              f"snippet(doc_page_fts, 0, '[', ']', ' … ', 40) snip FROM doc_page_fts f "
              f"JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
              f"WHERE doc_page_fts MATCH ? AND p.symbol=?{date_sql}{latest_sql}{extra} "
              f"ORDER BY d.filing_date DESC, rank LIMIT ?",
              (match, sym, *date_args, *latest_args, *eargs, cap))


def _related_pages(words: list[str], doc_keys: list[str], exclude: set[tuple[str, int]],
                   per: int = 4) -> list[dict[str, Any]]:
    """Other pages of the documents a reply quoted that print the same words: a call's Q&A page or the slide beside
    a table is named, so "stop at the first hit" becomes "here is where the rest is" (T-197 step 4)."""
    if not words or not doc_keys:
        return []
    words = words[:6]
    cond = " OR ".join("p.text LIKE ?" for _ in words)
    rows = _q(f"SELECT p.doc_key, p.page FROM doc_page p WHERE p.doc_key IN "
              f"({','.join('?' * len(doc_keys))}) AND ({cond}) ORDER BY p.doc_key, p.page LIMIT 60",
              (*doc_keys, *[f"%{word}%" for word in words]))
    out: list[dict[str, Any]] = []
    for r in rows:
        if (r["doc_key"], r["page"]) in exclude:
            continue
        out.append({"doc_key": r["doc_key"], "page": r["page"], "reason": "another page with the same words"})
        if len(out) >= per:
            break
    return out


# --- pilot3_guidance --------------------------------------------------------------------------------
GUIDANCE_METRICS = ("revenue_growth", "ebitda_margin", "order_intake", "nim", "credit_cost", "aum_growth",
                    "capex", "cost_of_production", "interest_cost", "ebitda_per_tonne", "new_loans",
                    "new_customers", "opex_to_nti", "other")


def guidance(symbol: str, metric: str | None = None, period: str | None = None, as_of: str | None = None,
             limit: int = 12, history: bool = False, include_quarantined: bool = False) -> dict[str, Any]:
    """Rule-extracted forward guidance: the CURRENT target of each metric and target period, newest first, with
    the row it revised (``revision_of`` and the previous low/high/date, so "did the guidance change between the
    two calls" is one call).  An older row of the same metric+period that a later document replaced is dropped and
    the kept row says how many (``superseded_rows``); ``history=true`` returns every row as stored.  ``low`` and
    ``high`` are NULL on a target said in words ("high single-digit", "in the 70s, mid-70s or higher"): the
    direction and the quote carry it.  A row the independent checker quarantined is hidden unless
    ``include_quarantined=True``, and every row says ``check_status`` verified or unverified (T-113).  A target
    stated for a named subsidiary, segment or investee is stored with that ``entity`` and never returned here: only
    the group's own guidance is served (T-192)."""
    sym = resolve_symbol(symbol)
    names, allnames = ([], list(GUIDANCE_METRICS))
    if metric:
        names, allnames = _pick("guidance", "metric", sym, metric,
                                extra="" if include_quarantined else _visible("guidance"))
        if not names:
            return _reply(sym, [], "pilot3_guidance", available=allnames[:40], metric_asked=metric)
    kind, label = norm_period(period)
    # only the group's own targets: a target stated for a named subsidiary, associate, joint venture or acquired
    # company carries its ``entity`` and is never served as the company's (T-192).  A store built before the column
    # existed has no entity rows at all, so every row it holds is the group's and is served (T-192 round 4).
    g_entity = _has_column("guidance", "entity")
    g_unsure = _has_column("guidance", "entity_unsure")
    where, args = "g.symbol=?", [sym]
    if g_entity:
        where += " AND COALESCE(g.entity,'')=''"
    if names:
        where += f" AND g.metric IN ({','.join('?' * len(names))})"
        args += names
    if kind and label:
        where += " AND g.target_period=?"
        args.append(label)
    join, check_sel, hide = _check_cols("guidance", "g.id")
    if not include_quarantined:
        where += hide
    extra, eargs = _asof(as_of, "g.known_at")
    ent_sel = (", COALESCE(g.entity,'') AS entity" if g_entity else ", '' AS entity") + \
              (", COALESCE(g.entity_unsure,0) AS entity_unsure" if g_unsure else ", 0 AS entity_unsure")
    rows = _q(f"SELECT g.id, g.metric, g.target_period, g.low, g.high, g.unit, g.direction, g.said_on, g.doc_key, "
              f"g.page, g.quote, g.speaker, g.known_at, g.revision_of, g.extractor_rule, d.title, d.doc_type, "
              f"pv.low prev_low, pv.high prev_high, pv.said_on prev_said_on, pv.direction prev_direction"
              f"{ent_sel}{check_sel} "
              f"FROM guidance g LEFT JOIN doc d ON d.doc_key=g.doc_key "
              f"LEFT JOIN guidance pv ON pv.id=g.revision_of{join} WHERE {where}{extra} "
              f"ORDER BY COALESCE(g.known_at, g.said_on) DESC, g.id DESC LIMIT 400", (*args, *eargs))
    out = []
    kept = [dict(r) for r in rows]
    if not history:
        kept = _guidance_current_rows(kept)   # the current target per metric+period, with its dropped-row count
    for r in kept[:_cap(limit)]:
        previous = None
        if r["revision_of"] is not None:
            previous = {"row_id": r["revision_of"], "low": r["prev_low"], "high": r["prev_high"],
                        "said_on": r["prev_said_on"], "direction": r["prev_direction"]}
        item = {"metric": r["metric"], "period": r["target_period"], "low": r["low"],
                "high": r["high"], "unit": r["unit"], "direction": r["direction"],
                "said_on": r["said_on"], "quote": _trim(r["quote"]), "speaker": r["speaker"],
                "revision_of": r["revision_of"], "previous": previous,
                "changed": bool(previous and (previous["low"], previous["high"]) != (r["low"], r["high"])),
                "superseded_rows": 0 if history else r["superseded_rows"],
                "provenance": _prov("guidance", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                    doc_type=r["doc_type"], title=_trim(r["title"], 120),
                                    row_id=r["id"])}
        if r["entity_unsure"]:
            item["entity_unsure"] = True    # the text named a candidate the store cannot prove is a subsidiary
        out.append(_add_check(item, r))
    held = None
    if not out:   # say what the table does hold, so the next call can be exact
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT metric, target_period, COUNT(*) FROM guidance WHERE symbol=?"
            + (f" AND metric IN ({','.join('?' * len(names))})" if names else "")
            + _visible("guidance") + " GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
    return _reply(sym, out, "pilot3_guidance", metrics_matched=names or None, history=True if history else None,
                  held_options=held, as_of=_day(as_of, "as_of"))


# --- pilot3_docs ------------------------------------------------------------------------------------
def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None, date_to: str | None = None,
         as_of: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """The documents pilot3 holds for a company, newest first (known_at = filing record), with page counts.
    ``offset`` pages a cut list; the reply says how many documents match, which are shown and what is cut."""
    sym = resolve_symbol(symbol)
    day = _day(as_of, "as_of")
    where, args = "symbol=?", [sym]
    if doc_type:
        dtype = _DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower())
        where += " AND doc_type=?"
        args.append(dtype)
    for val, op in ((_day(date_from, "date_from"), ">="), (_day(date_to, "date_to"), "<=")):
        if val:
            where += f" AND substr(COALESCE(known_at, filing_date),1,10) {op} ?"
            args.append(val)
    extra, eargs = _asof(as_of)
    cap, start = _window(limit, offset, 20)
    rows = _q(f"SELECT doc_key, doc_type, title, filing_date, known_at, pages, source, source_key FROM doc "
              f"WHERE {where}{extra} ORDER BY known_at DESC, doc_key LIMIT 400", (*args, *eargs))
    counts = {r[0]: r[1] for r in _q(f"SELECT doc_type, COUNT(*) FROM doc WHERE {where}{extra} GROUP BY doc_type",
                                     (*args, *eargs))}
    total = sum(counts.values())
    page = rows[start:start + cap]
    entries = [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "date": r["known_at"] or r["filing_date"],
                "title": r["title"]} for r in rows]
    cut = max(0, total - start - len(page))
    text = _scope_line(total, len(page), cut, start, entries, total)
    reply = _reply(sym, [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "title": _trim(r["title"], 100),
                          "filing_date": r["filing_date"], "pages": r["pages"],
                          "provenance": _prov("doc", _trim(r["source_key"] or r["source"], 140) or "", r["known_at"])}
                         for r in page],
                   "pilot3_docs", counts_by_type=counts, as_of=day, text=text,
                   coverage=_coverage("docs", ["doc (the document register: type, title, filing date, page count)"],
                                      ["documents the build never collected (they are not in this store)",
                                       "page text and tables (pilot3_search / pilot3_cells / pilot3_topic)"],
                                      total, len(page), cut, start, documents=entries,
                                      hidden=_hidden_documents(sym, day)))

    def titles(width: int) -> None:
        for row in reply["rows"]:
            row["title"] = _trim(row.get("title"), width)

    def documents_cut(keep: int) -> None:
        listed = reply["coverage"].get("documents") or []
        if len(listed) > keep:
            del listed[keep:]
            reply["coverage"]["documents_not_listed"] = reply["coverage"]["matched_documents"] - keep

    return _shrink(reply, [
        ("document titles cut to 60 characters", lambda: titles(60)),
        ("the list cut to the first 10 documents", lambda: reply["rows"].__delitem__(slice(10, None))),
        ("document titles cut", lambda: [doc.pop("title", None) for doc in reply["coverage"]["documents"]]),
        ("document list cut to the first 20", lambda: documents_cut(20)),
    ])


# --- pilot3_topic (T-194): a theme across every call and document, in one call ----------------------
TOPIC_LIMIT = 20             # items in a reply (a 20-item reply stays near 16 kB); the reply says what the limit cut
TOPIC_PER_DOC = {"statement": 4, "guidance": 3, "kpi": 2, "cell": 2, "event": 2, "page": 2}
TOPIC_QUOTE_CHARS = 220      # the quote shown per item; the page itself is named in read_next
TOPIC_REPLY_BYTES = 18_000   # the reply is trimmed in a fixed order until it fits (never below matched/shown/cut)


def _lex_topics() -> list[dict[str, Any]]:
    """Every topic tag the lexicon defines: ``topics.yaml`` plus each sector family's own ``topics:`` list."""
    from reality_engine.pilot3.transcripts import LEX_DIR
    out: list[dict[str, Any]] = []
    for path in sorted(LEX_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for item in doc.get("topics") or []:
            if item.get("tag") and item.get("patterns"):
                out.append(item)
    return out


def _topic_plan(topic: str) -> dict[str, Any]:
    """The words a topic is asked with, the lexicon tags they select, and every pattern of those tags: a question
    about "USFDA inspection" also finds OAI, VAI, Form 483 and warning letters, which the ask never printed.
    ``terms`` are the plain words of the same patterns, for the full-text seed over every held page (T-197)."""
    words = [w for w in re.findall(r"[\w&-]+", (topic or "").lower()) if len(w) > 2 or w.isdigit()]
    tags: list[str] = []
    sources: list[str] = [re.escape(w) for w in words]
    for item in _lex_topics():
        tag_words = [t for t in re.split(r"[_\s]+", str(item["tag"]).lower()) if len(t) >= 4]
        if any(t == w or t.startswith(w) or w.startswith(t) for t in tag_words for w in words if len(w) >= 4):
            tags.append(item["tag"])
            sources += [str(p) for p in item["patterns"]]
    terms = [token.lower() for source in sources for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", source)]
    return {"words": words, "tags": tags, "regexes": [re.compile(s, re.I) for s in dict.fromkeys(sources)],
            "terms": list(dict.fromkeys(terms))[:24]}


def _topic_hit(plan: dict[str, Any], *texts: Any) -> bool:
    blob = " ".join(str(t) for t in texts if t)
    return any(rx.search(blob) for rx in plan["regexes"])


def _topic_snippet(text: str | None, plan: dict[str, Any], width: int = 320) -> str | None:
    """The page's own sentence around the first lexicon match, so a page-text item carries the words it matched."""
    if not text:
        return None
    for rx in plan["regexes"]:
        found = rx.search(text)
        if found:
            start = max(0, found.start() - 120)
            return _trim(re.sub(r"\s+", " ", text[start:start + width]).strip(), width)
    return _trim(text, width)


def _reply_bytes(reply: dict[str, Any]) -> int:
    return len(json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"))


def _shrink(reply: dict[str, Any], cuts: list[tuple[str, Any]], where: str = "coverage") -> dict[str, Any]:
    """Apply the cuts in order until the reply fits its byte cap, and say which cuts it took: a heavy theme is
    summarised, never served past the cap and never silently (T-197 step 1)."""
    applied: list[str] = []
    if _reply_bytes(reply) <= REPLY_BYTES:
        return reply
    for label, cut in cuts:
        cut()
        applied.append(label)
        if _reply_bytes(reply) <= REPLY_BYTES:
            break
    if applied and isinstance(reply.get(where), dict):
        reply[where]["detail"] = "; ".join(applied) + " to keep the reply within its byte cap"
    return reply


def _trim_topic_reply(reply: dict[str, Any]) -> dict[str, Any]:
    """Keep a topic reply under its byte cap by cutting the optional detail in a fixed order -- the counts, the
    honest scope line and the document keys are never cut (T-197 step 1)."""
    if _reply_bytes(reply) <= TOPIC_REPLY_BYTES:
        return reply
    groups = reply.get("groups") or []
    docs = (reply.get("coverage") or {}).get("documents") or []

    def quotes(width: int) -> None:
        for group in groups:
            for item in group.get("items") or []:
                item["quote"] = _trim(item.get("quote"), width)

    def bodies(width: int) -> None:
        for group in groups:
            for item in group.get("items") or []:
                if item.get("body_excerpt"):
                    item["body_excerpt"] = _trim(item["body_excerpt"], width)

    cuts = [
        ("read_next cut to four pages", lambda: reply.__setitem__("read_next", (reply.get("read_next") or [])[:4])),
        ("quotes cut to 160 characters", lambda: quotes(160)),
        ("event body excerpts cut to 300 characters", lambda: bodies(300)),
        # the cheapest cut for what the model loses: the cut documents keep their type, date and match count in
        # the type+month summary, and matched_documents still states how many there were
        ("document list cut to the first 20, the rest summarised by type", lambda: docs.__delitem__(
            slice(20, None)) if len(docs) > 20 else None),
        ("document titles cut", lambda: [doc.pop("title", None) for doc in docs]),
        ("document page lists cut", lambda: [doc.pop("pages", None) for doc in docs]),
        ("quotes cut to 110 characters", lambda: quotes(110)),
        ("event body excerpts cut to 180 characters", lambda: bodies(180)),
        ("quotes cut to 70 characters", lambda: quotes(70)),
        ("group titles cut", lambda: [group.pop("title", None) for group in groups]),
    ]
    reply = _shrink(reply, cuts)
    if reply["coverage"].get("matched_documents", 0) > len(docs):
        reply["coverage"]["documents_not_listed"] = reply["coverage"]["matched_documents"] - len(docs)
    return reply


def topic(symbol: str, topic: str, as_of: str | None = None, limit: int = TOPIC_LIMIT,
          date_from: str | None = None, date_to: str | None = None, offset: int = 0) -> dict[str, Any]:
    """Everything the store holds on one theme up to ``as_of``, across every call and document in ONE call, grouped
    by document date: management's statements verbatim, the related guidance rows, company-stated KPI rows, page
    cells, event rows (an inspection, dividend, buyback, acquisition or merger) AND the word-level page text of
    every held document type (an untagged Q&A page, a deck table, a filing body -- ``match: tag | text``).  The
    ask's own words expand to the lexicon's sector vocabulary ("USFDA inspection" also finds OAI, Form 483, warning
    letters).  ``coverage`` says what was searched, what the tool cannot see, how much matched, how much is shown,
    what a date filter excluded and what ``as_of`` hid; ``offset`` pages a cut reply; ``read_next`` names the page
    beside each quoted one."""
    sym = resolve_symbol(symbol)
    if not (topic or "").strip():
        raise DataError("bad_topic", "topic is required: the words the question is about (e.g. 'Pen-G', 'China plant', "
                        "'USFDA inspection')")
    plan = _topic_plan(topic)
    day = _day(as_of, "as_of")
    start_day, end_day = _day(date_from, "date_from"), _day(date_to, "date_to")
    cap, start = _window(limit, offset, TOPIC_LIMIT)
    items: list[dict[str, Any]] = []
    counts = {"statement": 0, "guidance": 0, "kpi": 0, "cell": 0, "event": 0, "page": 0}
    outside: dict[tuple[str, str], int] = {}
    candidates = {"fetched": 0, "truncated": False}

    def keep(kind: str, date: str | None, doc_key: str, page: Any, quote: str | None, **fields: Any) -> None:
        if start_day and (date or "") < start_day or end_day and (date or "") > end_day:
            key = ((date or "")[:10], str(fields.get("doc_type") or "?"))
            outside[key] = outside.get(key, 0) + 1
            return
        counts[kind] += 1
        items.append({"kind": kind, "date": (date or "")[:10] or None, "doc_key": doc_key, "page": page,
                      "match": fields.pop("match", "tag"), "quote": _trim(quote, TOPIC_QUOTE_CHARS), **fields})

    extra, eargs = _asof(as_of, "t.known_at")
    stmt_doc = ("LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
                "AND a.alias_key=t.doc_key), t.doc_key)")
    for r in _q(f"SELECT t.id, t.doc_key, t.call_date, t.call_period, t.page, t.speaker, t.role, t.topics, t.quote, "
                f"t.known_at, d.title, d.doc_type FROM transcript_statement t {stmt_doc} "
                f"WHERE t.symbol=?{extra} ORDER BY t.call_date DESC, t.seq LIMIT 8000", (sym, *eargs)):
        if not _topic_hit(plan, r["quote"], r["topics"]):
            continue
        keep("statement", r["call_date"], r["doc_key"], r["page"], r["quote"], call_period=r["call_period"],
             speaker=r["speaker"], role=r["role"], topics=r["topics"], doc_type=r["doc_type"],
             title=_trim(r["title"], 120),
             provenance=_prov("transcript_statement", f"p{r['page']}", r["known_at"], row_id=r["id"]))

    extra, eargs = _asof(as_of, "g.known_at")
    for r in _q(f"SELECT g.id, g.metric, g.target_period, g.low, g.high, g.unit, g.direction, g.said_on, g.doc_key, "
                f"g.page, g.quote, g.known_at, d.title, d.doc_type FROM guidance g "
                f"LEFT JOIN doc d ON d.doc_key=g.doc_key WHERE g.symbol=?{extra}{_visible('guidance', 'g.id')} "
                f"ORDER BY COALESCE(g.known_at, g.said_on) DESC LIMIT 400", (sym, *eargs)):
        if not _topic_hit(plan, r["quote"], r["metric"], r["target_period"]):
            continue
        keep("guidance", r["said_on"], r["doc_key"], r["page"], r["quote"], metric=r["metric"],
             period=r["target_period"], low=r["low"], high=r["high"], unit=r["unit"], direction=r["direction"],
             doc_type=r["doc_type"], title=_trim(r["title"], 120),
             provenance=_prov("guidance", f"p{r['page']}", r["known_at"], row_id=r["id"]))

    extra, eargs = _asof(as_of, "k.known_at")
    kpi_doc = ("LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=k.symbol "
               "AND a.alias_key=k.doc_key), k.doc_key)")
    for r in _q(f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.fiscal_period, k.as_of_date, k.doc_key, "
                f"k.page, k.quote, k.known_at, d.title, d.doc_type FROM kpi_series k {kpi_doc} WHERE k.symbol=?"
                f"{extra} {_visible('kpi_series', 'k.id')} ORDER BY COALESCE(k.known_at, k.as_of_date) DESC "
                f"LIMIT 2000", (sym, *eargs)):
        if not _topic_hit(plan, r["quote"], r["metric"], r["dimension"]):
            continue
        keep("kpi", r["as_of_date"] or r["known_at"], r["doc_key"], r["page"], r["quote"], metric=r["metric"],
             dimension=r["dimension"], value=r["value"], unit=r["unit"], period=r["fiscal_period"],
             doc_type=r["doc_type"], title=_trim(r["title"], 120),
             provenance=_prov("kpi_series", f"p{r['page']}", r["known_at"], row_id=r["id"]))

    if _has_table("page_cell"):
        extra, eargs = _asof(as_of, "known_at")
        for r in _q(f"SELECT doc_key, page, known_at, row_label, col_header, table_title, value_text, unit_text "
                    f"FROM page_cell WHERE symbol=?{extra} AND status IN ('verified','unverified') "
                    f"ORDER BY known_at DESC LIMIT 4000", (sym, *eargs)):
            if not _topic_hit(plan, r["row_label"], r["table_title"], r["col_header"]):
                continue
            keep("cell", r["known_at"], r["doc_key"], r["page"], r["row_label"],
                 value=r["value_text"], unit=r["unit_text"], column=r["col_header"], table=r["table_title"],
                 provenance=_prov("page_cell", f"p{r['page']}", r["known_at"]))

    if _has_table("event"):
        extra, eargs = _asof(as_of, "e.known_at")
        # T-197: an event row carries the sentences that state its outcome, observations, classification, impact
        # or amount, its document type and title -- the title alone is not the answer.  A store built before the
        # columns existed still serves the old shape (NULLs), never a missing row.
        body = "e.body_excerpt" if _has_column("event", "body_excerpt") else "NULL"
        stored_type = "e.doc_type" if _has_column("event", "doc_type") else "NULL"
        stored_title = "e.title" if _has_column("event", "title") else "NULL"
        for r in _q(f"SELECT e.kind, e.event_date, e.end_date, e.announced, e.unit, e.outcome, e.subject, "
                    f"e.doc_key, e.page, e.quote, e.known_at, {body} AS body_excerpt, {stored_type} AS event_type, "
                    f"{stored_title} AS event_title, d.doc_type, d.title FROM event e "
                    f"LEFT JOIN doc d ON d.doc_key=e.doc_key WHERE e.symbol=?{extra} "
                    f"ORDER BY COALESCE(e.event_date, e.announced) DESC", (sym, *eargs)):
            if not _topic_hit(plan, r["subject"], r["quote"], r["unit"], r["outcome"], r["kind"],
                             r["body_excerpt"]):
                continue
            keep("event", r["event_date"] or r["announced"], r["doc_key"], r["page"], r["quote"] or r["subject"],
                 event=r["kind"], end_date=r["end_date"], unit=r["unit"], outcome=r["outcome"],
                 subject=_trim(r["subject"], 200), body_excerpt=_trim(r["body_excerpt"], 600),
                 doc_type=r["doc_type"] or r["event_type"], title=_trim(r["title"] or r["event_title"], 120),
                 provenance=_prov("event", f"p{r['page']}", r["known_at"], kind=r["kind"]))

    # T-197 step 2: the same words over the dated text of EVERY held page, so an untagged call page, a deck table,
    # an annual-report note or a filing body answers a theme no structured row carries.
    seed = _fts_query(" ".join(plan.get("terms") or plan["words"]), "or")
    if seed:
        extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
        pages = _q(f"SELECT p.doc_key, p.page, p.text, COALESCE(p.known_at, d.known_at) AS filed, d.filing_date, "
                   f"d.doc_type, d.title FROM doc_page_fts f JOIN doc_page p ON p.rowid=f.rowid "
                   f"JOIN doc d ON d.doc_key=p.doc_key WHERE doc_page_fts MATCH ? AND p.symbol=?{extra} "
                   f"ORDER BY rank LIMIT 3000", (seed, sym, *eargs))
        candidates = {"fetched": len(pages), "truncated": len(pages) >= 3000}
        for r in pages:
            if not _topic_hit(plan, r["text"]):
                continue
            keep("page", r["filing_date"] or r["filed"], r["doc_key"], r["page"],
                 _topic_snippet(r["text"], plan), match="text", doc_type=r["doc_type"],
                 title=_trim(r["title"], 120),
                 provenance=_prov("doc_page", f"p{r['page']}", r["filed"]))

    matched = len(items)
    # deterministic order: document date desc, then doc key and page, so an offset walk sees every item once
    items.sort(key=lambda item: (item["date"] or "", item["doc_key"], str(item.get("page") or "")), reverse=True)
    display: list[dict[str, Any]] = []
    per: dict[tuple, int] = {}
    for item in items:
        key = (item["doc_key"], item["kind"])
        if per.get(key, 0) >= TOPIC_PER_DOC.get(item["kind"], 3):
            continue
        per[key] = per.get(key, 0) + 1
        display.append(item)
    shown_items = display[start:start + cap]
    groups: dict[tuple, dict[str, Any]] = {}
    for item in shown_items:
        key = (item["date"] or "", item["doc_key"])
        group = groups.get(key)
        if group is None:
            group = groups[key] = {"date": item["date"], "doc_key": item["doc_key"],
                                   "doc_type": item.get("doc_type"), "title": item.get("title"), "items": []}
        group["doc_type"] = group["doc_type"] or item.get("doc_type")
        group["title"] = group["title"] or item.get("title")
        # the group already carries the date, document and title, and the provenance carries the page: an item
        # repeats none of them, or a 25-item reply costs more than the answer needs
        group["items"].append({k: v for k, v in item.items()
                               if k not in ("date", "doc_key", "page", "doc_type", "title")})
    ordered = sorted(groups.values(), key=lambda g: (g["date"] or "", g["doc_key"]), reverse=True)
    shown = len(shown_items)
    cut = max(0, matched - shown)
    docs = [{"doc_key": item["doc_key"], "doc_type": item.get("doc_type"), "date": item["date"],
             "title": item.get("title"), "page": item.get("page")} for item in items]
    doc_total = len({item["doc_key"] for item in items})
    tags_text = (", ".join(plan["tags"]) if plan["tags"] else "no lexicon tag matched the words")
    text = _scope_line(matched, shown, cut, start, docs, doc_total,
                       parts=f"{counts['statement']} tagged statement(s) + {counts['page']} page-text match(es)")
    outside_list = [{"date": date, "doc_type": dtype, "count": number}
                    for (date, dtype), number in sorted(outside.items(), reverse=True)][:20]
    hidden = _hidden_documents(sym, day)
    ask_words = [w for w in re.findall(r"[A-Za-z0-9&-]{3,}", " ".join(plan.get("terms") or plan["words"]))]
    read_next = (_read_next(shown_items, per=8) + _related_pages(
        ask_words, sorted({item["doc_key"] for item in shown_items}),
        {(item["doc_key"], int(item["page"])) for item in shown_items
         if item.get("page") not in (None, "")}))[:8]
    return _trim_topic_reply({
            "found": bool(shown), "symbol": sym, "tool": "pilot3_topic", "topic": topic, "as_of": day,
            "tags_matched": plan["tags"], "text": text, "n": shown,
            "counts": {**counts, "matched": matched, "shown": shown, "cut": cut},
            "groups": ordered, "read_next": read_next,
            "coverage": _coverage("topic", list(_TEXT_STORES) + [
                "guidance (forward targets)", "kpi_series (company-stated KPIs)",
                "page_cell (table and chart cells)", "event (inspection, dividend, buyback, acquisition, merger)"],
                ["pages the build holds no text for (OCR never read them, audio/video links)",
                 *[name for name in ("page_cell", "event", "guidance", "kpi_series") if not _has_table(name)]],
                matched, shown, cut, start, documents=docs, document_total=doc_total, outside=outside_list,
                hidden=hidden),
            "candidate_pages": candidates, **hidden,
            "as_of_note": f"documents first known after {day} are not used" if day else None,
            "hint": None if shown else "NOT IN DATA of pilot3 for this topic: try the words management uses, a wider "
                                       "date_from/date_to, or pilot3_search for the wording; only then the raw tools.",
            "provenance": _db_prov()})


# --- pilot3_search ----------------------------------------------------------------------------------
def _fts_query(text: str, mode: str) -> str:
    words = [w for w in re.findall(r"[\w₹%]+", text or "") if len(w) > 1 or w.isdigit()]
    return (" AND " if mode == "and" else " OR ").join(f'"{w}"' for w in words[:12])


_FY_TEXT = re.compile(r"(Q[1-4]|H[12])?\s*FY\s*'?\s*(\d{2,4})", re.I)


def _period_labels(text: str) -> list[str]:
    """['Q1FY27', 'FY26'] for the fiscal periods printed in a query ("Q1 FY27 results")."""
    out: list[str] = []
    for match in _FY_TEXT.finditer(text or ""):
        kind = (match.group(1) or "FY").upper()
        label = f"{kind}FY{match.group(2)[-2:]}"
        if label not in out:
            out.append(label)
    return out[:3]


def _period_in(text: str, label: str) -> bool:
    """Does a page print the period ("Q1FY27": Q1 FY27, Q1FY27, Q1 FY '27, Q1 FY2027; "FY26": FY26, FY '26, FY2026)?"""
    match = re.fullmatch(r"(Q[1-4]|H[12]|FY)FY(\d{2})", label or "")
    if not match:
        return False
    kind = match.group(1)
    year = f"(?:{match.group(2)}|20{match.group(2)})"
    pattern = rf"(?:\b{kind}\s*FY\s*'?\s*{year}\b)" if kind != "FY" else rf"\bFY\s*'?\s*{year}\b"
    return bool(re.search(pattern, text or "", re.I))


def _rank_hits(rows: list[sqlite3.Row], exact: set[int], or_ids: set[int], period: str | None,
               date_from: str | None, date_to: str | None, dtype: str | None,
               phrase: set[int] | None = None, short: set[int] | None = None) -> list[sqlite3.Row]:
    """bm25 order with a boost for an exact-phrase match (then its short-scale printing), an all-word match, the
    period asked, the filing window and the document type.

    bm25's own scale is not comparable across queries, so it is normalised inside the OR candidate set (1 = best
    match, the only set every row's rank comes from) and the boosts are added to that: the page that prints the
    quarter and was filed in the window the question names outranks a page that only happens to repeat its words.
    """
    ranks = [row["rank"] for row in rows if row["rid"] in or_ids]
    low = min(ranks) if ranks else 0.0
    scored = []
    for index, row in enumerate(rows):
        if row["rid"] in or_ids:
            # bm25's scale is not comparable across queries: the best hit is 1.0 and the rest keep their distance
            # from it as a ratio, so a boost means the same thing whatever the query's size.
            score = row["rank"] / low if low else 1.0
        else:
            score = 1.0                                   # an all-word hit outside the OR top
        if phrase and row["rid"] in phrase:
            score += 1.00                                    # the exact phrase the question printed (T-194)
        elif short and row["rid"] in short:
            score += 0.40                                    # the same amount printed short ("2 bn")
        if row["rid"] in exact:
            score += 0.20                                    # every query word is on the page
        day = str(row["filing_date"] or row["pk"] or row["dk"] or "")[:10]
        if date_from and date_to and date_from <= day <= date_to:
            score += 0.35                                    # filed inside the window the question names
        if period and _period_in(row["text"], period):
            score += 0.35                                    # the page prints the period asked
        if dtype and row["doc_type"] == dtype:
            score += 0.20                                    # the document type the question names
        scored.append((score, index, row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _score, _index, row in scored]


_SCALE_WORDS = {"bn": "billion", "billion": "billion", "cr": "crore", "crore": "crore", "crores": "crore",
                "mn": "million", "million": "million", "trn": "trillion", "trillion": "trillion", "k": "thousand",
                "lakh": "lakh", "lakhs": "lakh"}
_SHORT_SCALE = {"billion": "bn", "crore": "cr", "million": "mn", "trillion": "trn", "thousand": "k", "lakh": "lakh"}
_MONEY_RX = re.compile(r"(?:(?:us\$|usd|inr|rs\.?|₹|\$)\s*)?(\d[\d,.]*)\s*"
                       r"(bn|billion|cr|crores?|mn|million|trn|trillion|lakhs?|k)\b", re.I)


def _phrase_terms(query: str) -> tuple[list[str], list[str]]:
    """The exact phrases a question prints, and the short-scale printing of its money amounts: "2 billion" is the
    exact phrase, "2 bn" is the same amount printed short and ranks after it (T-194)."""
    words = [w for w in re.findall(r"[\w₹%]+", query or "") if len(w) > 1 or w.isdigit()]
    exact = [" ".join(words)] if len(words) > 1 else []
    short: list[str] = []
    for match in _MONEY_RX.finditer(query or ""):
        number = match.group(1).rstrip(".,")
        scale = _SCALE_WORDS.get(match.group(2).lower().rstrip("s")) or _SCALE_WORDS.get(match.group(2).lower())
        if not scale:
            continue
        for term in (f"{number} {scale}", f"{number} {scale} dollars"):
            if term not in exact:
                exact.append(term)
        short_term = f"{number} {_SHORT_SCALE.get(scale, scale)}"
        if short_term not in exact and short_term not in short:
            short.append(short_term)
    return exact[:6], short[:4]


def search(symbol: str, query: str, as_of: str | None = None, limit: int = 10,
           doc_type: str | None = None, period: str | None = None,
           date_from: str | None = None, date_to: str | None = None, offset: int = 0) -> dict[str, Any]:
    """Full-text search over every held page (FTS5 bm25, ranked): the exact phrase first, then the words; a money
    amount is normalised ("US$2 bn" = "$2 billion" = "2 billion").  The reply says how many pages match, how many
    are shown and what is cut, and lists EVERY matching document (not only the ones on this page).  ``period``
    (Q1FY27 / FY26), ``date_from``+``date_to`` and ``doc_type`` boost the pages that print the period / were filed
    in the window / are of that document type; ``offset`` pages a cut reply; ``as_of`` never returns a document
    first known after that day and says how many matches it hid."""
    sym = resolve_symbol(symbol)
    day = _day(as_of, "as_of")
    extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
    dflt, dargs = "", ()
    dtype = _DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower()) if doc_type else None
    if dtype:
        dflt, dargs = " AND d.doc_type=?", (dtype,)
    start_day, end_day = _day(date_from, "date_from"), _day(date_to, "date_to")
    cap, start = _window(limit, offset, 10)
    # the period the caller names is normalised to the label the pages print (FY27, Q1FY27), never prefixed twice:
    # norm_period('FY27') is ('FY', 'FY27'), so the reply can only ever echo a canonical label.
    kind, label = norm_period(period)
    labels = [label] if kind else _period_labels(query)
    period = labels[0] if labels else None
    select = (f"SELECT p.rowid rid, p.doc_key, p.page, p.text, p.known_at pk, d.known_at dk, d.doc_type, "
              f"d.title, d.filing_date, rank, snippet(doc_page_fts, 0, '[', ']', ' … ', 40) snip "
              f"FROM doc_page_fts f JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
              f"WHERE doc_page_fts MATCH ? AND p.symbol=?{dflt}{extra} ORDER BY rank LIMIT ?")
    count = ("SELECT COUNT(*), COUNT(DISTINCT p.doc_key) FROM doc_page_fts f "
             "JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
             f"WHERE doc_page_fts MATCH ? AND p.symbol=?{dflt}{extra}")
    and_query, or_query = _fts_query(query, "and"), _fts_query(query, "or")
    if not or_query:
        raise DataError("bad_query", "query needs at least one word")
    exact_terms, short_terms = _phrase_terms(query)
    phrase_query = " OR ".join(f'"{term}"' for term in exact_terms)
    short_query = " OR ".join(f'"{term}"' for term in short_terms)
    found: dict[int, sqlite3.Row] = {}
    phrase_ids: set[int] = set()
    if phrase_query:
        for row in _q(select, (phrase_query, sym, *dargs, *eargs, (start + cap) * 20)):
            found[row["rid"]] = row
            phrase_ids.add(row["rid"])
    short_ids: set[int] = set()
    if short_query:
        for row in _q(select, (short_query, sym, *dargs, *eargs, (start + cap) * 20)):
            if row["rid"] not in phrase_ids:
                short_ids.add(row["rid"])
                found.setdefault(row["rid"], row)
    and_rows = _q(select, (and_query, sym, *dargs, *eargs, (start + cap) * 20)) \
        if and_query and and_query not in (phrase_query, short_query) else []
    and_ids = {row["rid"] for row in and_rows}
    for row in and_rows:
        found.setdefault(row["rid"], row)
    or_rows = [] if or_query in (and_query, phrase_query, short_query) else \
        _q(select, (or_query, sym, *dargs, *eargs, (start + cap) * 20))
    or_ids = {row["rid"] for row in or_rows} | set(found)
    for row in or_rows:
        found.setdefault(row["rid"], row)
    ranked_all = _rank_hits(list(found.values()), and_ids, or_ids, period, start_day, end_day, dtype,
                            phrase_ids, short_ids)
    ranked = ranked_all[start:start + cap]
    match_mode = ("phrase" if phrase_ids else
                  "and" if any(row["rid"] in and_ids for row in ranked) else "or")
    count_query = phrase_query if phrase_ids else (and_query if and_ids else or_query)
    pages_matched, documents_matched = _q(count, (count_query, sym, *dargs, *eargs))[0]
    pages_short = 0
    if short_query and phrase_query:
        pages_short = max(0, _q(count, (f"({short_query}) NOT ({phrase_query})", sym, *dargs, *eargs))[0][0])
    pages_like = None
    if phrase_ids:   # a substring scan is wider than the phrase: it also counts "22 billion" for "2 billion"
        raw = " ".join(w for w in re.findall(r"[\w₹%]+", query or "") if len(w) > 1 or w.isdigit())
        if raw:
            pages_like = _q(f"SELECT COUNT(*) FROM doc_page p JOIN doc d ON d.doc_key=p.doc_key "
                            f"WHERE p.text LIKE ? AND p.symbol=?{dflt}{extra}", (f"%{raw}%", sym, *dargs, *eargs))[0][0]
            pages_like = pages_like if pages_like > pages_matched + pages_short else None
    hidden = 0
    if day:
        hidden = max(0, _q(count.replace(extra, ""), (count_query, sym, *dargs))[0][0] - pages_matched)
    # EVERY matching document, not only the ones on this page: the documents whose hits the limit cut are named in
    # `coverage`, so a page of ten hits is never read as everything the store holds (T-197 step 1).
    doc_rows = _q(f"SELECT d.doc_key, d.doc_type, d.title, d.filing_date, p.page FROM doc_page_fts f "
                  f"JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
                  f"WHERE doc_page_fts MATCH ? AND p.symbol=?{dflt}{extra} "
                  f"ORDER BY d.filing_date DESC, p.page LIMIT 800", (count_query, sym, *dargs, *eargs))
    documents: list[dict[str, Any]] = []
    by_doc: dict[str, dict[str, Any]] = {}
    for r in ranked:                    # the documents this page's rows came from (the full list is in coverage)
        group = by_doc.get(r["doc_key"])
        if group is None:
            group = by_doc[r["doc_key"]] = {"doc_key": r["doc_key"], "doc_type": r["doc_type"],
                                            "title": _trim(r["title"], 60), "filing_date": r["filing_date"],
                                            "pages": []}
            documents.append(group)
        if r["page"] not in group["pages"] and len(group["pages"]) < 3:
            group["pages"].append(r["page"])
    cut = max(0, pages_matched - start - len(ranked))
    text = (f"{pages_matched} page(s) match {query!r} ({match_mode} match) in {documents_matched} document(s)"
            + (f"; {pages_short} more print it short" if pages_short else "")
            + (f"; a substring scan counts {pages_like} (it also counts a longer number)" if pages_like else "")
            + (f" first known on or before {day}; {hidden} hidden by as_of" if day else "")
            + f"; {len(ranked)} shown"
            + (f"; {cut} cut - call again with offset={start + len(ranked)}" if cut else ""))
    entries = [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "date": r["filing_date"], "title": r["title"],
                "page": r["page"]} for r in doc_rows]
    coverage = _coverage("search", ["doc_page (FTS5 over the dated page text of every held document type)"],
                         ["pages the build holds no text for (scanned pages the OCR never read, audio/video links)",
                          "structured tables: kpi_series, guidance, page_cell, fin_*, event "
                          "(pilot3_kpi / pilot3_guidance / pilot3_cells / pilot3_fin / pilot3_topic)"],
                         pages_matched, len(ranked), cut, start, documents=entries,
                         document_total=documents_matched, hidden=_hidden_documents(sym, day))
    if start_day or end_day:
        coverage["date_filter_effect"] = ("date_from/date_to rank the pages filed in the window; this tool never "
                                          "excludes a page by date")
    if len(doc_rows) >= 800:
        coverage["documents_truncated"] = True
    reply = _reply(sym, [{"doc_type": r["doc_type"], "title": _trim(r["title"], 60), "filing_date": r["filing_date"],
                          "page": r["page"], "snippet": _trim(r["snip"], 320),
                          "provenance": _prov("doc_page", f"{r['doc_key']} p{r['page']}", r["pk"] or r["dk"])}
                         for r in ranked], "pilot3_search", match_mode=match_mode, period=period, text=text,
                   pages_matched=pages_matched, documents_matched=documents_matched, shown=len(ranked),
                   documents=documents, as_of=day, hidden_after_as_of=hidden, pages_short=pages_short,
                   pages_like=pages_like, coverage=coverage,
                   read_next=_read_next([{"doc_key": r["doc_key"], "page": r["page"]} for r in ranked]))

    def snippets(width: int) -> None:
        for row in reply["rows"]:
            row["snippet"] = _trim(row.get("snippet"), width)

    def documents_cut(keep: int) -> None:
        listed = reply["coverage"].get("documents") or []
        if len(listed) > keep:
            del listed[keep:]
            reply["coverage"]["documents_not_listed"] = reply["coverage"]["matched_documents"] - keep

    return _shrink(reply, [
        ("snippets cut to 200 characters", lambda: snippets(200)),
        ("document titles cut", lambda: [doc.pop("title", None) for doc in reply["coverage"]["documents"]]),
        ("snippets cut to 120 characters", lambda: snippets(120)),
        ("document list cut to the first 20 of the rank", lambda: documents_cut(20)),
    ])


# --- pilot3_sql -------------------------------------------------------------------------------------
SQL_TEXT_CHARS = 400          # the per-cell cut the answer tools have always used
SQL_MAX_TEXT_CHARS = 8000     # hard cap: long page text must be asked for, never returned by default


def _as_of_connection(day: str) -> sqlite3.Connection:
    """A private read-only connection on which every table with a ``known_at`` column (and ``doc_page`` through
    its ``doc``) is shadowed by a TEMP view holding only rows known on or before ``day`` (T-156: answers read
    transcripts filed after the question date through sql)."""
    con = core.connect_ro(db_path(), timeout_s=core.READ_TIMEOUT_S, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=0")   # TEMP views only; the main file stays mode=ro, so nothing can be written
    _cur = con.execute("SELECT name FROM main.sqlite_master WHERE type='table' "
                       "AND name NOT LIKE '%fts%' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in ((_cur.fetchall() or []) if _cur is not None else [])]
    for table in tables:
        if table == "doc_page":
            con.execute(f"CREATE TEMP VIEW doc_page AS SELECT p.* FROM main.doc_page p JOIN main.doc d "
                        f"ON d.doc_key = p.doc_key WHERE substr(COALESCE(p.known_at, d.known_at), 1, 10) <= '{day}'")
            continue
        _cur = con.execute(f'PRAGMA main.table_info("{table}")')
        cols = {r[1] for r in ((_cur.fetchall() or []) if _cur is not None else [])}
        if "known_at" in cols:
            con.execute(f'CREATE TEMP VIEW "{table}" AS SELECT * FROM main."{table}" '
                        f"WHERE known_at IS NOT NULL AND substr(known_at, 1, 10) <= '{day}'")
    con.execute("PRAGMA query_only=1")
    return con


def sql(query: str, limit: int = 100, timeout_seconds: float = 5.0,
        max_chars: int = SQL_TEXT_CHARS, as_of: str | None = None,
        store: str | None = None, symbol: str | None = None) -> dict[str, Any]:
    """Bounded, read-only SELECT/WITH over ONE pilot3 store, chosen by ``store`` (a registered store's name or
    path) or by its ``symbol`` (the store that holds it, T-203); with neither, and a store registry configured,
    the registered stores are listed instead of guessing.  ``REALITY_PILOT3_DB`` pins one store and switches
    routing off.

    Financial figures: ``fin_quarter_current`` gives the one preferred line per (symbol, fiscal_period, basis,
    line_item) now, and ``preferred_from`` / ``preferred_to`` on ``fin_quarter_xbrl`` and ``fin_quarter_printed``
    elect it at any past day (preferred when ``preferred_from <= day`` and (``preferred_to IS NULL`` or
    ``preferred_to > day``)); ``pilot3_fin`` returns the same figure.  The raw tables hold every filing's printing
    of the same line, so a sum over them counts a restatement and its original twice.
    Text cells are cut at ``max_chars`` (default 400, hard cap 8000): a question about wording, a whole
    paragraph or a long quote passes ``max_chars`` explicitly, otherwise the page text is truncated.
    ``as_of`` (YYYY-MM-DD): every table with a ``known_at`` column, and ``doc_page`` through its document, shows
    only rows known on or before that day (T-156); pass it for any dated question.  ``doc_page_fts`` is not
    filtered itself, so join its hits to ``doc_page``."""
    if store:
        select_store(store)
    elif symbol:
        resolve_symbol(symbol)
    elif _pinned() is None and stores():
        return store_listing("pilot3_sql names no store and no symbol, so it cannot pick one; pass symbol= (the "
                             "store that holds it answers) or store= (a registered store's name or path)")
    text = core._strip_sql(query or "")
    if not text:
        raise DataError("bad_query", "pilot3_sql needs a SELECT or WITH query")
    if len(core._statements(text)) != 1:
        raise DataError("not_select", "only one read-only statement is allowed")
    if not re.match(r"^(SELECT|WITH)\b", text, re.IGNORECASE):
        raise DataError("not_select", "only SELECT / WITH queries are allowed")
    if core._WRITE_WORDS.search(text):
        raise DataError("not_select", "write/DDL keywords are not allowed")
    limit = max(1, min(int(limit), 500))
    try:
        chars = max(1, min(int(max_chars), SQL_MAX_TEXT_CHARS))
    except (TypeError, ValueError):
        raise DataError("bad_max_chars", f"max_chars must be an integer 1..{SQL_MAX_TEXT_CHARS}")
    started = time.perf_counter()
    day = _day(as_of, "as_of") if as_of else None
    con = _as_of_connection(day) if day else connect()
    wrapped = f"SELECT * FROM ({text}) AS _q LIMIT {limit + 1}"
    try:
        cur = con.execute(wrapped)
        columns = [d[0] for d in cur.description]
        raw = cur.fetchall()
    except core.QueryTimeout as exc:
        raise DataError("query_timeout", str(exc))
    except sqlite3.DatabaseError as exc:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%fts%'")]
        raise DataError("sql_error", f"{type(exc).__name__}: {exc}. Tables: {', '.join(tables)}")
    finally:
        if day:
            con.close()
    rows = [[core._jsonable(v) if not isinstance(v, str) else _trim(v, chars) for v in r] for r in raw[:limit]]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": len(raw) > limit, "as_of": day,
            "as_of_note": (f"rows known after {day} are filtered out through TEMP views (every table with a known_at "
                           "column, and doc_page through its document); doc_page_fts itself is not filtered, so join "
                           "its hits to doc_page") if day else None,
            "max_chars": chars, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "provenance": _db_prov(note="read-only SELECT/WITH, row-limited")}


# --- pilot3_fact (T-186): one answer-ready lookup ---------------------------------------------------
# The answering model asks one question for one number: the value with its unit and scale, the period, the basis,
# the source document and page, known_at, and -- for a figure the store computes -- the formula and its input rows.
# The routing and every election reuse the existing lookups, so fact and fin/ratio/kpi/holding never disagree.
_FACT_VALUATION = ("pe", "p_b", "pb", "ev_ebitda", "market_cap", "dividend_yield", "dividend_yield_pct",
                   "trailing_eps", "close")
_FACT_RATIO_NAMES = {"roe", "roce", "roa", "debt_to_equity", "interest_coverage", "current_ratio",
                     "book_value_per_share", "dividend_payout", "nim", "net_debt_to_ebitda",
                     "net_debt_to_equity", "pat_ttm", "eps_ttm", "working_capital_days", "nwc_days"}
_FACT_RATIO_SUFFIXES = ("_pct", "_margin", "_growth", "_days", "_ratio", "_coverage", "_payout", "_per_share",
                        "_ttm")
_FACT_SHARES = ("share_count", "shares_outstanding", "share_capital", "shares", "equity_shares")
_FACT_HOLDING_WORDS = set(_HOLDING_CATEGORY_WORDS) | {"promoter", "promoters", "shareholder", "shareholders",
                                                     "shareholding"}
_FACT_UNIT_WORDS = {
    "inr": "rupee", "inr_cr": "crore", "inr_crore": "crore", "inr_mn": "million", "inr_million": "million",
    "inr_lakh": "lakh", "inr_bn": "billion", "inr_per_share": "rupee per share", "rs/share": "rupee per share",
    "pct": "percent", "bps": "basis points", "x": "times", "days": "days", "ratio": "ratio", "count": "count",
    "count_mn": "million count", "usd_mn": "million USD", "shares": "shares",
}
_FACT_VALUATION_COLUMNS = {"close": "close", "shares_outstanding": "shares_outstanding", "market_cap": "market_cap",
                           "net_worth": "net_worth", "net_debt": "net_debt", "trailing_ebitda": "trailing_ebitda",
                           "eps_basic": "trailing_eps", "pat": "trailing_pat"}
_FACT_SCALE_WORDS = ((1e12, "lakh crore"), (1e9, "billion"), (1e7, "crore"), (1e6, "million"), (1e5, "lakh"),
                     (1e3, "thousand"))


def _metric_key(name: str) -> str:
    """A user's metric word as the tables spell it: spaces / dashes / slashes / '%' become underscores."""
    return re.sub(r"[%\s\-/]+", "_", str(name or "").strip().lower()).strip("_")


def _scale_word(unit: str | None, scale: float | None) -> str:
    """The word that reads ``value`` in ``unit``: crore, million, percent ... (the store's unit first)."""
    key = str(unit or "").strip().lower()
    if key in _FACT_UNIT_WORDS:
        return _FACT_UNIT_WORDS[key]
    try:
        size = float(scale or 1.0)
    except (TypeError, ValueError):
        size = 1.0
    for step, word in _FACT_SCALE_WORDS:
        if size >= step:
            return word
    return "unit"


def _split_source(prov: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    """(table, document key, page) from a row's provenance: ``doc p3``, ``doc [store row]`` or ``row 12``."""
    table = prov.get("table")
    source = str(prov.get("source") or "").strip()
    match = re.fullmatch(r"(.*?)(?: p(\d+))?(?: \[[^\]]*\])?", source)
    doc = ((match.group(1) if match else source) or "").strip() or None
    page = int(match.group(2)) if match and match.group(2) else None
    if doc and (re.fullmatch(r"row \d+", doc) or table in ("ratio_panel", "valuation_daily", "share_capital")):
        doc = None                      # a store row, not a document: the table and known_at carry it
    return table, doc, page


def _fact_value(row: dict[str, Any]) -> tuple[Any, str | None, float]:
    if "quarter_end" in row and "pct" in row:          # shp_category
        return row.get("pct"), "pct", 1.0
    if "shares_outstanding" in row:                    # share_capital
        return row.get("shares_outstanding"), "shares", 1.0
    return row.get("value"), row.get("unit"), row.get("scale") or 1.0


def _fact_alt(row: dict[str, Any], period: str | None = None) -> dict[str, Any]:
    value, unit, _scale = _fact_value(row)
    table, doc, page = _split_source(row.get("provenance") or {})
    return {"value": value, "unit": unit,
            "period": period or row.get("period") or row.get("date") or row.get("quarter_end"),
            "basis": row.get("basis"), "table": table, "doc_key": doc, "page": page,
            "definition": row.get("definition")}


def _fact_mismatch(asked_period: str | None, asked_basis: str | None, row: dict[str, Any]) -> str | None:
    """The period or basis the answer came back for, when it is not the one asked (T-186).

    A holding / share-count / valuation route holds dates, not fiscal labels: answering the latest one for a
    ``FY25`` ask without saying so reads as the wrong period.  ``FY25`` is the March quarter of that year; a date
    ask is the quarter end it names.
    """
    parts: list[str] = []
    basis = row.get("basis") or "not_stated"
    if asked_basis and basis != asked_basis:
        parts.append(f"asked {asked_basis}, returned {basis}")
    kind, label = norm_period(asked_period)
    if label:
        returned = row.get("period") or row.get("date") or row.get("quarter_end") or row.get("as_of_date")
        same = str(returned) == label
        if not same:
            _rk, rlabel = norm_period(returned)
            same = rlabel == (f"Q4{label[2:]}" if kind == "FY" else label)
        if not same:
            parts.append(f"asked {label}, returned quarter {returned}")
    return "; ".join(parts) or None


def _fact_check_status(row: dict[str, Any]) -> str | None:
    """The row check's verdict for the answer's row, so a served figure says verified / unverified (T-113, T-186)."""
    status = row.get("check_status")
    if status is not None:
        return status
    prov = row.get("provenance") or {}
    table, row_id = prov.get("table"), prov.get("row_id")
    if table and row_id and _has_table("row_check"):
        got = _q("SELECT status FROM row_check WHERE tbl=? AND row_id=? LIMIT 1", (table, int(row_id)))
        if got:
            return got[0]["status"]
    return None


def _fact_prefer_xbrl_annual(row: dict[str, Any], day: str | None) -> dict[str, Any] | None:
    """For an annual line, prefer an XBRL filing (reported, then derived) over a printed / company-stated figure.

    ``fin`` keeps the newest-filing election, so a later annual-report page (e.g. APOLLOHOSP's FY25 revenue 951,308)
    can replace the XBRL filing's number (217,940).  ``fact`` re-elects here: the best XBRL printing wins when one
    exists, and the displaced printing is kept as an alternative with its source.  Returns None when no re-election
    applies (not an annual line, or no XBRL printing exists), so the caller keeps the original row.
    """
    if (row.get("provenance") or {}).get("table") != "fin_annual_line":
        return None
    definition = str(row.get("definition") or "")
    if definition.startswith("xbrl"):
        return None
    alts = row.get("alternatives") or []
    xbrl_alts = [a for a in alts if str(a.get("definition") or "").startswith("xbrl")
                 and (a.get("provenance") or {}).get("table") == "fin_annual_line"]
    if not xbrl_alts:
        return None
    # reported before derived
    best = min(xbrl_alts, key=lambda a: 0 if a.get("definition") == "xbrl_reported" else 1)
    prov = best.get("provenance") or {}
    table, row_id = prov.get("table"), prov.get("row_id")
    if not table or not row_id:
        return None
    try:
        r = _q(f"SELECT rowid, * FROM {table} WHERE rowid=?", (int(row_id),))[0]
    except (IndexError, ValueError, TypeError):
        return None
    if not _pit_ok(r["known_at"], day):
        return None
    period_val = r["fiscal_year"] if "fiscal_year" in r.keys() else r["fiscal_period"]
    new_row = _fin_row(r, table, period_val, r["definition"], _fin_source(r))
    # rebuild alternatives: the displaced preferred printing first, then the rest
    new_alts: list[dict[str, Any]] = []
    orig_alt = {"value": row.get("value"), "unit": row.get("unit"), "scale": row.get("scale"),
                "filing_date": str((row.get("provenance") or {}).get("known_at") or "")[:10],
                "role": row.get("column_role") or "xbrl", "definition": row.get("definition"),
                "provenance": row.get("provenance")}
    new_alts.append(orig_alt)
    for a in alts:
        if a is best:
            continue
        new_alts.append(a)
    new_row["alternatives"] = new_alts
    return new_row


def _fact_answer(row: dict[str, Any], as_of_used: str | None, computed: dict | None,
                 asked_period: str | None = None, asked_basis: str | None = None) -> dict[str, Any]:
    value, unit, scale = _fact_value(row)
    prov = row.get("provenance") or {}
    table, doc, page = _split_source(prov)
    period = row.get("period") or row.get("date") or row.get("quarter_end") or row.get("as_of_date")
    answer = {"value": value, "unit": unit, "scale_word": _scale_word(unit, scale), "period": period,
              "basis": row.get("basis"), "as_of_used": as_of_used,
              "source": {"table": table, "doc_key": doc, "page": page, "quote": _trim(row.get("quote"), 600)},
              "known_at": prov.get("known_at") or row.get("known_at"), "computed": computed}
    mismatch = _fact_mismatch(asked_period, asked_basis, row)
    if mismatch:
        answer["mismatch"] = mismatch
    status = _fact_check_status(row)
    if status:
        answer["check_status"] = status
    return answer


def _fact_why(path: str, row: dict[str, Any]) -> str:
    if path == "fin":
        return (f"the preferred {row.get('definition') or 'reported'} figure for {row.get('period')}; the newest "
                "filing's restatement wins and an older printing is in alternatives")
    if path == "ratio":
        if row.get("definition") == "company_stated":
            return "the company's own stated figure, which the store serves ahead of its derived ratio"
        if row.get("date"):
            return f"the store's valuation on {row['date']}, the latest one known on or before the day asked"
        return "the store's derived ratio for that period and basis, from its own formula and input rows"
    if path == "kpi":
        return "the company-stated KPI with the best evidence for the period (a deck table before a call remark)"
    if path == "holding":
        return f"the filing in force on {row.get('quarter_end')}: its own printed percentage, never a sum of lines"
    return "the filing's share count nearest the day asked"


def _kpi_covers(symbol: str, names: list[str], period: str | None) -> bool:
    """Does ``kpi_series`` hold this metric for the period asked?  The company's own EBITDA is preferred only for
    a period it actually states; another period must fall through to the derived ratio (T-192 round 4)."""
    if not names:
        return False
    kind, label = norm_period(period)
    if not label:
        return True
    return bool(_q(f"SELECT 1 FROM kpi_series WHERE symbol=? AND metric IN ({','.join('?' * len(names))}) "
                   "AND fiscal_period=? LIMIT 1", (symbol, *names, label)))


def _fact_route(key: str, symbol: str, period: str | None = None) -> tuple[str | None, dict[str, list[str]], dict[str, list[str]]]:
    """Which lookup owns a metric word (T-186 step 1): names matched per table, and every name each table holds."""
    rnames, rall = _pick("ratio_panel", "metric", symbol, key)
    qnames, qall = _pick("fin_quarter_xbrl", "line_item", symbol, key)
    anames, aall = _pick("fin_annual_line", "line_item", symbol, key)
    knames, kall = _pick("kpi_series", "metric", symbol, _KPI_WORDS.get(key, key))
    fnames = list(dict.fromkeys(qnames + anames))
    found = {"ratio_panel": rnames, "fin": fnames, "kpi_series": knames}
    allnames = {"ratio_panel": rall, "fin": list(dict.fromkeys(qall + aall)), "kpi_series": kall}
    words = set(key.split("_"))
    if key in _FACT_SHARES:
        return "shares", found, allnames
    if key.endswith("holding") or key.endswith("shareholding") or words & _FACT_HOLDING_WORDS:
        return "holding", found, allnames
    # T-192: a company's own EBITDA / EBITDA margin is the definition it means; the derived ratio is returned as a
    # second, labelled alternative.  Two derivations of one line disagreeing is exactly what sent a grader wrong.
    # Only a period the KPI rows cover takes that route: an earlier or later year still answers from the derived
    # ratio, never from a different period's company figure.
    if key in ("ebitda", "ebitda_margin", "ebitda_margin_pct") and found["kpi_series"] \
            and _kpi_covers(symbol, found["kpi_series"], period):
        return "kpi", found, allnames
    # a ratio word first: a margin / return / growth / valuation is computed or stated, not a balance line.  The
    # plain lines ratio_panel also mirrors (pat, revenue_from_operations) are not ratio words and go to fin.
    ratio_word = (key in _FACT_VALUATION or key in _FACT_RATIO_NAMES or key.endswith(_FACT_RATIO_SUFFIXES))
    if ratio_word and (key in rnames or f"{key}_pct" in rnames or key in _FACT_VALUATION):
        return "ratio", found, allnames
    if fnames:
        return "fin", found, allnames
    if knames:
        return "kpi", found, allnames
    if rnames:
        return "ratio", found, allnames
    return None, found, allnames


def _fact_holding_word(symbol: str, key: str, day: str | None = None) -> str | None:
    """The word a filed shp_category answers, so ``promoter holding`` asks for ``promoter``."""
    extra, eargs = _asof(day)
    held = [r[0] for r in _q(f"SELECT DISTINCT category FROM shp_category WHERE symbol=?{extra} ORDER BY 1",
                             (symbol, *eargs))]
    for word in key.split("_"):
        if word in _FACT_HOLDING_WORDS or word in held or any(word in name for name in held):
            return word
    return None


def _fact_paths(path: str, found: dict[str, list[str]]) -> list[str]:
    """The lookup that owns the metric, then the other tables that hold a name for it (T-186 fallback)."""
    table_of = {"fin": "fin", "ratio": "ratio_panel", "kpi": "kpi_series"}
    order = {"fin": ("fin", "ratio", "kpi"), "ratio": ("ratio", "fin", "kpi"),
             "kpi": ("kpi", "fin", "ratio"), "holding": ("holding",), "shares": ("shares",)}[path]
    return [candidate for candidate in order if candidate == path or found.get(table_of[candidate])]


def _fact_rows(path: str, symbol: str, key: str, period: str | None, basis: str | None, day: str | None,
               limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The rows one existing lookup returns for the metric (never reshaped), so fact keeps its election."""
    if path == "fin":
        reply = fin(symbol, key, period=period, basis=basis, as_of=day, limit=limit)
    elif path == "ratio":
        reply = ratio(symbol, key, period=period, as_of=day, basis=basis, limit=limit)
    elif path == "kpi":
        reply = kpi(symbol, key, period=period, as_of=day, basis=basis, limit=limit)
    elif path in ("holding", "shares"):
        quarter = period if period and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(period)) else None
        reply = holding(symbol, day or dt.date.today().isoformat(), quarter_end=quarter,
                        category=_fact_holding_word(symbol, key, day) if path == "holding" else None)
    else:
        return [], {}
    if path == "shares":
        block = reply.get("share_capital")
        return ([block] if block else []), reply
    return (reply.get("rows") or []), reply


def _fact_second(path: str, found: dict[str, list[str]]) -> str | None:
    """The next lookup that also holds the metric, so the answer says what the other table says (max 3)."""
    for candidate, table in (("kpi", "kpi_series"), ("ratio", "ratio_panel"), ("fin", "fin")):
        if candidate != path and found.get(table):
            return candidate
    return None


def _pit_ok(known_at: str | None, day: str | None) -> bool:
    """Is a row's filing record public on ``day``? (T-186: no computed input may be known after as_of.)"""
    return not day or not known_at or str(known_at)[:10] <= day


def _ref_input(symbol: str, ref: str, basis: str | None, cutoff: str | None) -> dict[str, Any]:
    """One input the store's own ``input_refs`` names (``fa:…``, ``fq:…``, ``sc:…``) with its value and source.

    ``cutoff`` is the as_of day, else the figure's own filing: a rowid / date the ref names is read only when it
    satisfies the cutoff, and a row that fails it is reported as ``pit_hidden`` so the computed figure is not served
    (T-186).
    """
    out: dict[str, Any] = {"name": ref, "value": None, "unit": None, "period": None, "source": None}
    parts = str(ref).split(":", 4)
    if len(parts) == 3 and parts[0] == "sc":                       # sc:SYM:date -> the share count used
        cb = ("count_basis" if _has_column("share_capital", "count_basis")
              else "CASE WHEN source_table='shp_category' THEN 'filed_exact' END")
        rows = _q(f"SELECT shares_outstanding, as_of_date, known_at, source_table FROM share_capital "
                  f"WHERE symbol=? AND as_of_date=? AND event IS NULL ORDER BY ({cb}='filed_exact') DESC, "
                  "known_at DESC LIMIT 5", (symbol, parts[2]))
        row = next((r for r in rows if _pit_ok(r["known_at"], cutoff)), None)
        if row is None and rows:
            out["pit_hidden"] = True
            return out
        if row:
            out.update(name="shares_outstanding", value=row["shares_outstanding"], unit="shares",
                       period=row["as_of_date"], source={"table": "share_capital", "doc_key": None, "page": None})
        return out
    if len(parts) != 5 or parts[0] not in ("fa", "fq"):
        return out
    kind, period, bas, item = parts[0], parts[2], parts[3], parts[4]
    when = None
    if "@" in item:                                               # fq:…:ltm:…:pat@2024-03-31
        item, _, when = item.partition("@")
    rowid = None
    if "#" in item:                                               # fa:…:net_worth#2069
        item, _, rowid = item.partition("#")
    out["name"] = item
    extra, eargs = _asof(cutoff)
    if kind == "fa":
        if rowid:
            rows = _q("SELECT value, unit, fiscal_year, doc_key, page, known_at FROM fin_annual_line WHERE rowid=?",
                      (rowid,))
            if rows and not _pit_ok(rows[0]["known_at"], cutoff):
                out["pit_hidden"] = True
                return out
        else:
            rows = _q(f"SELECT value, unit, fiscal_year, doc_key, page FROM fin_annual_line WHERE symbol=? "
                      f"AND fiscal_year=? AND basis=? AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1",
                      (symbol, period, bas, item, *eargs))
        if rows:
            out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=rows[0]["fiscal_year"],
                       source={"table": "fin_annual_line", "doc_key": rows[0]["doc_key"], "page": rows[0]["page"]})
        return out
    if period == "ltm":
        trailing = f"{item}_ttm"
        rows = _q(f"SELECT rowid, value, unit, fiscal_period FROM ratio_panel WHERE symbol=? AND metric=? "
                  f"AND period_end=? AND basis=?{_asof(cutoff)[0]} ORDER BY known_at DESC LIMIT 1",
                  (symbol, trailing, when or cutoff, bas, *_asof(cutoff)[1]))
        if rows:
            out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=rows[0]["fiscal_period"],
                       source={"table": "ratio_panel", "doc_key": None, "page": None})
            return out
        rows = _q(f"SELECT value, unit, scale, fiscal_period FROM fin_quarter_xbrl WHERE symbol=? AND line_item=? "
                  f"AND basis=? AND period_end<=?{extra} ORDER BY period_end DESC, known_at DESC LIMIT 12",
                  (symbol, item, bas, when or cutoff or "9999-12-31", *eargs))
        seen, total, unit = set(), 0.0, None
        for r in rows:
            if r["fiscal_period"] in seen:
                continue
            seen.add(r["fiscal_period"])
            total += (r["value"] or 0.0) * (r["scale"] or 1.0)
            unit = unit or r["unit"]
        if len(seen) == 4:                                        # a trailing twelve months, no fewer
            out.update(value=total, unit=unit, period=f"LTM to {when or cutoff}",
                       source={"table": "fin_quarter_xbrl", "doc_key": None, "page": None})
        return out
    rows = _q(f"SELECT value, unit, source_file FROM fin_quarter_xbrl WHERE symbol=? AND fiscal_period=? "
              f"AND basis=? AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1",
              (symbol, period, bas, item, *eargs))
    if rows:
        out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=period,
                   source={"table": "fin_quarter_xbrl", "doc_key": rows[0]["source_file"], "page": None})
        return out
    # a quarter the XBRL window does not hold is mirrored in ratio_panel by the derived-quarter part (T-129)
    rows = _q(f"SELECT rowid, value, unit FROM ratio_panel WHERE symbol=? AND metric=? AND fiscal_period=? "
              f"AND basis=?{_asof(cutoff, 'known_at')[0]} ORDER BY known_at DESC LIMIT 1",
              (symbol, item, period, bas, *_asof(cutoff, "known_at")[1]))
    if rows:
        out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=period,
                   source={"table": "ratio_panel", "doc_key": None, "page": None})
    return out


def _formula_inputs(symbol: str, metric: str | None, period: str | None, basis: str | None,
                    day: str | None) -> list[dict[str, Any]]:
    """A formula's own input names valued for the same period and basis: ratio_panel, then the quarter, then the year."""
    formula = _q("SELECT inputs FROM formula WHERE metric=? LIMIT 1", (metric,))
    if not formula:
        return []
    extra, eargs = _asof(day)
    inputs = []
    for name in [n.strip() for n in (formula[0]["inputs"] or "").split(",") if n.strip()][:6]:
        store, rows = "ratio_panel", _q(f"SELECT value, unit FROM ratio_panel WHERE symbol=? AND metric=? "
                                        f"AND fiscal_period=? AND basis=?{extra} ORDER BY known_at DESC LIMIT 1",
                                        (symbol, name, period, basis, *eargs))
        if not rows:
            store = "fin_quarter_xbrl"
            rows = _q(f"SELECT value, unit FROM fin_quarter_xbrl WHERE symbol=? AND line_item=? AND fiscal_period=? "
                      f"AND basis=?{extra} ORDER BY known_at DESC LIMIT 1", (symbol, name, period, basis, *eargs))
        if not rows:
            store = "fin_annual_line"
            rows = _q(f"SELECT value, unit FROM fin_annual_line WHERE symbol=? AND line_item=? AND fiscal_year=? "
                      f"AND basis=?{extra} ORDER BY known_at DESC LIMIT 1", (symbol, name, period, basis, *eargs))
        inputs.append({"name": name, "value": rows[0]["value"] if rows else None,
                       "unit": rows[0]["unit"] if rows else None, "period": period,
                       "source": {"table": store, "doc_key": None, "page": None}})
    return inputs


def _fact_ratio_computed(symbol: str, row: dict[str, Any], day: str | None) -> dict[str, Any] | None:
    prov = row.get("provenance") or {}
    known = str(prov.get("known_at") or "")[:10] or day
    cutoff = day or known          # an input must be public by as_of; else by the figure's own filing
    if row.get("date"):                         # valuation_daily: PE / PB / EV-EBITDA / market cap on a day
        formula = _q("SELECT expression, inputs FROM formula WHERE metric=? LIMIT 1", (row.get("ratio"),))
        if not formula:
            return None
        match = re.search(r"row (\d+)", str(prov.get("source") or ""))
        columns = ", ".join(dict.fromkeys(_FACT_VALUATION_COLUMNS.values()))
        values = []
        if match:
            got = _q(f"SELECT {columns}, known_at FROM valuation_daily WHERE rowid=?", (match.group(1),))
            if got and not _pit_ok(got[0]["known_at"], cutoff):
                return None                 # the valuation row itself is not public at as_of
            values = got[:1]
        inputs = []
        for name in [n.strip() for n in (formula[0]["inputs"] or "").split(",") if n.strip()][:6]:
            column = _FACT_VALUATION_COLUMNS.get(name)
            inputs.append({"name": name, "value": values[0][column] if values and column in values[0].keys() else None,
                           "unit": None, "period": row.get("date"),
                           "source": {"table": "valuation_daily", "doc_key": None, "page": None}})
        return {"formula": formula[0]["expression"], "inputs": inputs}
    try:
        refs = json.loads(prov.get("input_refs") or "[]")
    except ValueError:
        refs = []
    refs = refs if isinstance(refs, list) else [refs]
    if not row.get("formula"):
        return None                     # the store did not record the formula: no computed block is invented
    if not refs:                        # an older build keeps the input names in formula.inputs only
        inputs = _formula_inputs(symbol, row.get("ratio"), row.get("period"), row.get("basis"), cutoff)
    else:
        inputs = [_ref_input(symbol, str(ref), row.get("basis"), cutoff) for ref in refs[:6]]
    if any(item.get("pit_hidden") for item in inputs):
        return None                     # an input is not public at as_of: the computed figure is not served
    return {"formula": row.get("formula"), "inputs": inputs}


def _fact_fin_computed(symbol: str, row: dict[str, Any], day: str | None) -> dict[str, Any] | None:
    """A derived annual line's formula and its same-period inputs (the store's ``formula`` table names them)."""
    formula = _q("SELECT expression, inputs FROM formula WHERE metric=? LIMIT 1", (row.get("measure"),))
    if not formula:
        return None                     # a derived line whose formula the store does not hold is not guessed at
    cutoff = day or str((row.get("provenance") or {}).get("known_at") or "")[:10] or None
    inputs = []
    for name in [n.strip() for n in (formula[0]["inputs"] or "").split(",") if n.strip()][:6]:
        rows = _q(f"SELECT value, unit, doc_key, page, known_at FROM fin_annual_line WHERE symbol=? AND fiscal_year=? "
                  f"AND basis=? AND line_item=? ORDER BY known_at DESC LIMIT 5",
                  (symbol, row.get("period"), row.get("basis"), name))
        pick = next((r for r in rows if _pit_ok(r["known_at"], cutoff)), None)
        if pick is None and rows:
            return None                 # an input is not public at as_of: the computed figure is not served
        inputs.append({"name": name, "value": pick["value"] if pick else None,
                       "unit": pick["unit"] if pick else None, "period": row.get("period"),
                       "source": {"table": "fin_annual_line", "doc_key": pick["doc_key"] if pick else None,
                                  "page": pick["page"] if pick else None}})
    return {"formula": formula[0]["expression"], "inputs": inputs}


def _fact_computed(path: str, symbol: str, row: dict[str, Any], day: str | None) -> dict[str, Any] | None:
    if path == "ratio":
        return _fact_ratio_computed(symbol, row, day)
    if path == "fin" and "derived" in str(row.get("definition") or ""):
        return _fact_fin_computed(symbol, row, day)
    return None


def _fact_sample(table: str, name: str, symbol: str, day: str | None) -> dict[str, Any] | None:
    """One latest row of a metric name, for the not-found reply's ``nearest`` list."""
    extra, eargs = _asof(day)
    if table == "fin":
        rows = _q(f"SELECT line_item AS metric, fiscal_year AS period, basis, value, unit, doc_key, page, known_at "
                  f"FROM fin_annual_line WHERE symbol=? AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1",
                  (symbol, name, *eargs))
        store = "fin_annual_line"
        if not rows:
            store = "fin_quarter_xbrl"
            rows = _q(f"SELECT line_item AS metric, fiscal_period AS period, basis, value, unit, "
                      f"source_file AS doc_key, NULL AS page, known_at FROM fin_quarter_xbrl WHERE symbol=? "
                      f"AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1", (symbol, name, *eargs))
    elif table == "ratio":
        store = "ratio_panel"
        rows = _q(f"SELECT metric, fiscal_period AS period, basis, value, unit, NULL AS doc_key, NULL AS page, "
                  f"known_at FROM ratio_panel WHERE symbol=? AND metric=?{extra} ORDER BY known_at DESC LIMIT 1",
                  (symbol, name, *eargs))
    else:
        store = "kpi_series"
        rows = _q(f"SELECT metric, fiscal_period AS period, basis, value, unit, doc_key, page, known_at "
                  f"FROM kpi_series WHERE symbol=? AND metric=?{extra} ORDER BY known_at DESC LIMIT 1",
                  (symbol, name, *eargs))
    if not rows:
        return None
    r = rows[0]
    return {"nearest": True, "table": store, "metric": r["metric"], "value": r["value"], "unit": r["unit"],
            "period": r["period"], "basis": r["basis"], "known_at": r["known_at"],
            "source": {"table": store, "doc_key": r["doc_key"], "page": r["page"]}}


def _fact_not_found(symbol: str, metric: str, key: str, found: dict[str, list[str]],
                    allnames: dict[str, list[str]], day: str | None, note: str | None = None) -> dict[str, Any]:
    searched = [{"table": table, "names_matched": names[:8]} for table, names in found.items()]
    owner: dict[str, str] = {}
    for table, names in allnames.items():
        for name in names:
            owner.setdefault(name, table)
    nearest = []
    for name in difflib.get_close_matches(key, sorted(owner), n=3, cutoff=0.4):
        table = owner[name]
        row = _fact_sample("ratio" if table == "ratio_panel" else table, name, symbol, day)
        if row:
            nearest.append(row)
    hint = ("NOT IN DATA of pilot3 for these arguments: try a name in nearest, a wider period, or pilot3_search; "
            "only then fall back to the raw tools.")
    if note:
        hint = f"{note} {hint}"
    return {"found": False, "symbol": symbol, "tool": "pilot3_fact", "metric_asked": metric, "searched": searched,
            "nearest": nearest, "hint": hint, "provenance": _db_prov()}


def _fact_held_quarantined(symbol: str, found: dict[str, list[str]], day: str | None) -> list[str]:
    """Rows the independent checker quarantined for this metric, so a hidden figure is reported, not read as absent.

    ``fin`` and ``ratio`` filter their rows but do not say what they hid (T-186); ``kpi`` reports its own.
    """
    if not _has_table("row_check"):
        return []
    specs = (("fin_annual_line", "line_item", found.get("fin") or []),
             ("fin_quarter_xbrl", "line_item", found.get("fin") or []),
             ("ratio_panel", "metric", found.get("ratio_panel") or []))
    extra, eargs = _asof(day)
    out: list[str] = []
    for table, col, names in specs:
        if not names:
            continue
        placeholders = ",".join("?" * len(names))
        rows = _q(f"SELECT t.{col} AS name, COUNT(*) c FROM row_check rc JOIN {table} t ON t.rowid=rc.row_id "
                  f"WHERE rc.status='quarantined' AND rc.tbl=? AND t.symbol=? AND t.{col} IN ({placeholders}){extra} "
                  f"GROUP BY 1 ORDER BY 2 DESC LIMIT 10", (table, symbol, *names, *eargs))
        out += [f"{table} / {r['name']} ({r['c']} rows; the row check quarantined them)" for r in rows]
    return out


_FACT_CHECK_ORDER = ("verified", "unverified", "quarantined")


def _fact_is_derived(path: str, row: dict[str, Any]) -> bool:
    """Is the served figure the store's own computation, not a filing and not the company's statement?"""
    definition = str(row.get("definition") or "")
    if path == "ratio":
        return definition != "company_stated"
    if path == "fin":
        return "derived" in definition
    return False


def _fact_company_stated(symbol: str, names: list[str], period: str | None, basis: str | None,
                         day: str | None) -> dict[str, Any] | None:
    """The company's own printed figure for the same metric / period / basis, whatever the row check made of it.

    T-198: when the answer is a derived figure, a company-stated row of the same key may exist (a deck table or a
    call remark) and the old reply called itself "the preferred" figure without naming it.  A quarantined row is
    still the company's own statement, so it is returned here, labelled with its check status and why the store
    did not serve it — never silently dropped."""
    if not names or not _has_table("kpi_series"):
        return None
    _kind, label = norm_period(period)
    where = ["k.symbol=?"]
    args: list[Any] = [symbol]
    if label:
        where.append("k.fiscal_period=?")
        args.append(label)
    if basis:
        where.append("k.basis=?")
        args.append(basis)
    if day:
        where.append("(k.known_at IS NULL OR k.known_at<=?)")
        args.append(day)
    judged = _has_table("row_check")
    extra = (", rc.status AS check_status, (SELECT GROUP_CONCAT(f.check_name, ',') FROM row_check_fail f "
             "WHERE f.tbl='kpi_series' AND f.row_id=k.id AND f.hard=1) AS check_hard") if judged \
        else ", NULL AS check_status, NULL AS check_hard"
    join = " LEFT JOIN row_check rc ON rc.tbl='kpi_series' AND rc.row_id=k.id" if judged else ""
    marks = ",".join("?" * len(names))
    rows = _q("SELECT k.value, k.unit, k.scale, k.fiscal_period, k.basis, k.doc_key, k.page, k.known_at, "
              f"k.raw_label{extra} FROM kpi_series k{join} WHERE " + " AND ".join(where)
              + f" AND k.metric IN ({marks}) ORDER BY COALESCE(k.known_at,'') DESC LIMIT 8", (*args, *names))
    if not rows:
        return None
    best = sorted(rows, key=lambda r: _FACT_CHECK_ORDER.index(r["check_status"])
                  if r["check_status"] in _FACT_CHECK_ORDER else 3)[0]
    status = best["check_status"]
    if status == "quarantined":
        why = "the independent row check quarantined it" + \
            (f" ({best['check_hard'].replace(',', ', ')})" if best["check_hard"] else "")
    elif status == "unverified":
        why = "the independent row check could not pin it to a second source"
    elif status == "verified":
        why = "the row check verified it, but the store's election kept the derived figure"
    else:
        why = "no row check has judged it yet"
    return {"value": best["value"], "unit": best["unit"], "scale_word": _scale_word(best["unit"], best["scale"]),
            "period": best["fiscal_period"], "basis": best["basis"], "definition": best["raw_label"],
            "source": {"table": "kpi_series", "doc_key": best["doc_key"], "page": best["page"]},
            "known_at": best["known_at"], "check_status": status, "why_not_preferred": why}


def _fact_cells(sym: str, metric: str, period: str | None, day: str | None) -> dict[str, Any] | None:
    """T-189: the page reader's cells when no other table holds the metric; ``source: page_cell`` labels it."""
    reply = cells(sym, metric, period=period, as_of=day, limit=3)
    rows = reply.get("rows") or []
    if not rows:
        return None
    row = rows[0]
    answer = {"value": row["value_text"], "unit": row["unit_text"], "period": row["col_header"] or period,
              "basis": None, "as_of_used": day,
              "source": {"table": "page_cell", "doc_key": row["doc_key"], "page": row["page"],
                         "quote": _trim(f"{row['row_label']} | {row['col_header']}: {row['value_text']}", 600)},
              "known_at": row["known_at"], "check_status": row["status"], "computed": None}
    alternatives = [{"value": alt["value_text"], "unit": alt["unit_text"], "period": alt["col_header"],
                     "table": "page_cell", "doc_key": alt["doc_key"], "page": alt["page"],
                     "note": f"read from the page, {alt['status']}"} for alt in rows[1:]]
    return {"found": True, "symbol": sym, "metric": metric, "route": "cells", "answer": answer,
            "alternatives": alternatives[:3],
            "why_this_one": "no other pilot3 table holds this metric; the page reader read the figure from a "
                            "table/chart page, and the status says whether the position check confirmed it",
            "provenance": _db_prov()}


def fact(symbol: str, metric: str, period: str | None = None, basis: str | None = None,
         as_of: str | None = None) -> dict[str, Any]:
    """The ONE preferred figure for a (company, metric, period, basis), answer-ready in a single call (T-186).

    Routing: a financial line -> ``fin`` (the preferred-figure election); a ratio / margin / growth / valuation ->
    ``ratio``; a company-stated KPI -> ``kpi``; a holding category -> ``holding``; a share count -> ``share_capital``.
    Returns ``answer`` = value, unit and scale word, period, basis, as_of used, source {table, document, page, quote},
    known_at, and ``computed`` {formula, inputs} for a figure the store derives; up to three ``alternatives`` from
    another table or filing, and ``why_this_one``.  Nothing matching returns ``found: false`` with the tables and
    names searched and up to three nearest rows."""
    sym = resolve_symbol(symbol)
    key = _metric_key(metric)
    if not key:
        raise DataError("bad_metric", "metric is required (a financial line, ratio, KPI, holding category or share "
                        "count)")
    day = _day(as_of, "as_of")
    bas = (basis or "").strip().lower() or None
    path, found, allnames = _fact_route(key, sym, period)
    if path is None:
        from_cells = _fact_cells(sym, metric, period, day)
        if from_cells:
            return from_cells
        return _fact_not_found(sym, metric, key, found, allnames, day)
    # the owning lookup first; a table that also holds the metric answers when the owner has no row for the period
    rows: list[dict[str, Any]] = []
    used = path
    replies: dict[str, dict[str, Any]] = {}
    for candidate in _fact_paths(path, found):
        rows, reply = _fact_rows(candidate, sym, key, period, bas, day, 5)
        replies[candidate] = reply
        if rows:
            used = candidate
            break
    if not rows:
        from_cells = _fact_cells(sym, metric, period, day)
        if from_cells:
            return from_cells
        note = None
        if day:                     # say plainly when as_of, not the store, is what hides the figure
            for candidate in _fact_paths(path, found):
                later, _reply = _fact_rows(candidate, sym, key, period, bas, None, 1)
                if later:
                    note = f"a row is held but was filed after {day}: call without as_of, or with a later as_of."
                    break
        out = _fact_not_found(sym, metric, key, found, allnames, day, note=note)
        held = [line for reply in replies.values()
                for line in (reply.get("held_quarantined") or reply.get("held_options") or [])]
        held += _fact_held_quarantined(sym, found, day)
        if held:
            out["held_quarantined"] = held[:10]
        return out
    row = rows[0]
    if used == "fin":
        row = _fact_prefer_xbrl_annual(row, day) or row
    alternatives: list[dict[str, Any]] = []
    if used == "fin":
        for alt in (row.get("alternatives") or [])[:3]:
            table, doc, page = _split_source(alt.get("provenance") or {})
            alternatives.append({"value": alt.get("value"), "unit": alt.get("unit"), "period": row.get("period"),
                                 "basis": row.get("basis"), "table": table, "doc_key": doc, "page": page,
                                 "definition": alt.get("definition"), "filing_date": alt.get("filing_date"),
                                 "note": "another filing's printing of the same figure"})
    for other in rows[1:4]:
        if len(alternatives) >= 3:
            break
        alternatives.append(_fact_alt(other))
    second = _fact_second(used, found)
    if second and len(alternatives) < 3:
        alt_rows, _reply = _fact_rows(second, sym, key, period, bas, day, 3)
        if used == "kpi":   # the company's own figure is the answer: the second row is the store's computation,
            alt_rows = [r for r in alt_rows if r.get("definition") != "company_stated"] or alt_rows
        if alt_rows:
            alternative = _fact_alt(alt_rows[0])
            alternative["note"] = f"the same metric as the {second} lookup holds it"
            alternatives.append(alternative)
    answer = _fact_answer(row, day, _fact_computed(used, sym, row, day), period, bas)
    why = _fact_why(used, row)
    company_stated = None
    if _fact_is_derived(used, row):
        # T-198: never call a derived figure "the preferred" one without naming what the company itself states
        company_stated = _fact_company_stated(sym, found.get("kpi_series") or [], period, bas, day)
    if company_stated:
        label = _trim(company_stated.get("definition"), 60)
        why = (f"{why}; the company itself states {company_stated['value']} {company_stated['unit']}"
               f"{' (' + label + ')' if label else ''} for the same period, and that figure is not preferred here "
               f"— {company_stated['why_not_preferred']}")
    return {"found": True, "symbol": sym, "metric": metric, "route": used, "answer": answer,
            "alternatives": alternatives[:3], "why_this_one": why, "provenance": _db_prov(),
            **({"company_stated": company_stated} if company_stated else {})}
