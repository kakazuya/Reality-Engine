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

T-239: a lookup that finds no row adds ``nearest`` -- up to three page hits and three stored statements for the
caller's words, labelled "not a stored row: read the page" -- and the text tools widen the words through the
committed ``synonyms.json`` (an expansion is OR-ed, never required).  A derived ratio row names its definition,
numerator, denominator and input rows, and P/B / book value per share are computed on the latest balance sheet known
at ``as_of`` and name it.
"""
from __future__ import annotations

import contextvars
import datetime as dt
import difflib
import functools
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
from reality_engine.pilot3 import schema as p3_schema
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


def _day_span(day: str, days: int = 3) -> tuple[str, str]:
    """The window ``days`` either side of a named call date (T-242 fix 4): a transcript's printed call date and the
    document's filing date can differ by a few days (called 2026-08-10, filed 2026-08-13)."""
    at = dt.date.fromisoformat(day)
    return (at - dt.timedelta(days=days)).isoformat(), (at + dt.timedelta(days=days)).isoformat()


def _near_day(day: str, want: dt.date, days: int = 3) -> bool:
    """Is ``day`` within ``days`` of ``want``?  A malformed or absent day is never near."""
    try:
        return abs((dt.date.fromisoformat(str(day)[:10]) - want).days) <= days
    except ValueError:
        return False


def _named_call_docs(sym: str, day: str, days: int = 3) -> list[str]:
    """The documents one named call is served from (T-242 fix 5): a document matches when the call date its
    transcript prints (``MAX(transcript_statement.call_date)`` per resolved doc key) OR its filing date is within
    ``days`` of the day named.  A filing-date window alone dropped the statements and page hits of every call filed
    more than 3 days after it was held (11 of the 16 calls sampled in retrieval audit 5)."""
    if not _has_table("doc"):
        return []
    want = dt.date.fromisoformat(day)
    matched: set[str] = set()
    for r in _q("SELECT doc_key, filing_date FROM doc WHERE symbol=?", (sym,)):
        if r["doc_key"] and _near_day(str(r["filing_date"] or ""), want, days):
            matched.add(str(r["doc_key"]))
    if _has_table("transcript_statement"):
        for r in _q("SELECT d.doc_key AS dk, MAX(t.call_date) AS cd FROM transcript_statement t "
                    "JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
                    "AND a.alias_key=t.doc_key), t.doc_key) WHERE t.symbol=? GROUP BY 1", (sym,)):
            if r["dk"] and _near_day(str(r["cd"] or ""), want, days):
                matched.add(str(r["dk"]))
    return sorted(matched)


def _named_call_dates(sym: str, docs: list[str]) -> dict[str, dict[str, str]]:
    """Per document of a named call: its ``filed`` date and the call date its transcript prints (T-242 fix 6).

    Keyed by the resolved doc_key AND every alias key the store maps to it, because obs_fact and transcript rows
    are held under either one.  A document with no transcript keeps an empty ``printed``."""
    out: dict[str, dict[str, str]] = {}
    if not docs or not _has_table("doc"):
        return out
    marks = ",".join("?" * len(docs))
    filed: dict[str, str] = {}
    for r in _q(f"SELECT doc_key, filing_date FROM doc WHERE symbol=? AND doc_key IN ({marks})", (sym, *docs)):
        if r["doc_key"]:
            filed[str(r["doc_key"])] = str(r["filing_date"] or "")[:10]
    printed: dict[str, str] = {}
    if _has_table("transcript_statement"):
        for r in _q("SELECT d.doc_key AS dk, MAX(t.call_date) AS cd FROM transcript_statement t "
                    "JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
                    "AND a.alias_key=t.doc_key), t.doc_key) WHERE t.symbol=? GROUP BY 1", (sym,)):
            if r["dk"] and str(r["dk"]) in filed:
                printed[str(r["dk"])] = str(r["cd"] or "")[:10]
    for key, day in filed.items():
        out[key] = {"filed": day, "printed": printed.get(key, "")}
    if _has_table("doc_alias"):
        for r in _q("SELECT doc_key, alias_key FROM doc_alias WHERE symbol=?", (sym,)):
            if str(r["doc_key"]) in out and r["alias_key"]:
                out[str(r["alias_key"])] = out[str(r["doc_key"])]
    return out


def _fy2(text: str) -> str:
    return text[-2:]


_MONTH_NAMES = "january february march april may june july august september october november december".split()


def _month_num(word: str) -> int | None:
    low = str(word or "").strip().lower()
    if len(low) < 3:
        return None
    for i, name in enumerate(_MONTH_NAMES, 1):
        if name.startswith(low):
            return i
    return None


def _natural_date(text: str | None) -> tuple[dt.date | None, tuple[int, int] | None]:
    """``(day, (year, month))`` when ``text`` prints a calendar period: '2026-05-27', 'September 30, 2026',
    '30th Jun'25', '30-Jun-25', 'Mar-26'.  ``day`` is None for a month and year alone (T-242)."""
    raw = str(text or "").strip().lower()
    if not raw:
        return None, None
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])), None
        except ValueError:
            return None, None
    for rx, dmy in ((r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/,]+([a-z]{3,9})\.?[\s\-/,’']*(\d{2,4})\b", True),
                    (r"\b([a-z]{3,9})\.?[\s\-/,]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-/,’']*(\d{2,4})\b", False)):
        m = re.search(rx, raw)
        if not m:
            continue
        day, month = (int(m[1]), _month_num(m[2])) if dmy else (int(m[2]), _month_num(m[1]))
        if not month:
            continue
        year = int(m[3])
        try:
            return dt.date(year + (2000 if year < 100 else 0), month, day), None
        except ValueError:
            return None, None
    m = re.search(r"\b([a-z]{3,9})\.?[\s\-/,’']*(\d{2}|\d{4})\b", raw)
    if m:
        month = _month_num(m[1])
        if month:
            year = int(m[2])
            return None, (year + (2000 if year < 100 else 0), month)
    return None, None


def _period_key(text: str | None) -> str:
    """A period label as one key: letters and digits only, upper ('September 30, 2026' -> 'SEPTEMBER302026')."""
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _period_norm_sql(col: str) -> str:
    """SQL that keys a stored period the way ``_period_key`` does (T-242): punctuation and spaces removed."""
    for ch in (" ", "-", ",", ".", "/", "(", ")", "’"):
        col = f"REPLACE({col},'{ch}','')"
    col = f"REPLACE({col},char(39),'')"
    return f"UPPER({col})"


def _natural_period_forms(text: str | None) -> set[str]:
    """The spellings a natural date is printed as in ``obs_fact.period`` ('September 30, 2026', '30-Sep-2026',
    'Sep-26', 'Mar-2026'), already keyed by ``_period_key`` (T-242)."""
    day, ym = _natural_date(text)
    if day is not None:
        year, month = day.year, day.month
    elif ym is not None:
        year, month = ym
    else:
        return set()
    name, abbr = _MONTH_NAMES[month - 1], _MONTH_NAMES[month - 1][:3]
    out = {f"{year}-{month:02d}", f"{name}{year}", f"{name}{year % 100:02d}", f"{abbr}{year}",
           f"{abbr}{year % 100:02d}", f"{month:02d}{year}", f"{year}{month:02d}"}
    if day:
        out |= {f"{day.day}{month:02d}{year}", f"{day.day}{name}{year}", f"{day.day}{abbr}{year}",
                f"{day.day:02d}{abbr}{year % 100:02d}", f"{year}{month:02d}{day.day:02d}",
                f"{year}-{month:02d}-{day.day:02d}", f"{name}{day.day}{year}", f"{abbr}{day.day}{year}",
                f"{name}{day.day:02d}{year % 100:02d}", f"{abbr}{day.day:02d}{year % 100:02d}",
                f"{month:02d}{day.day:02d}{year}"}
        for suffix in ("ST", "ND", "RD", "TH"):     # the printed label keeps its ordinal: "30th Jun'25"
            out |= {f"{day.day}{suffix}{abbr}{year}", f"{day.day}{suffix}{abbr}{year % 100:02d}",
                    f"{day.day}{suffix}{name}{year}", f"{day.day}{suffix}{name}{year % 100:02d}",
                    f"{abbr}{day.day}{suffix}{year % 100:02d}", f"{name}{day.day}{suffix}{year % 100:02d}"}
    return {_period_key(form) for form in out}


def _period_matches(stored: str | None, asked: str | None) -> bool:
    """Does a stored period label answer the period asked (T-242 fix 6)?

    A fiscal label matches itself ('Q2FY27'); a printed natural date ('As on 30th Sept, 2026', 'Quarter ended
    September 30, 2026') matches by its date keys, allowing the words a label prefixes or suffixes to it."""
    _kind, label = norm_period(asked)
    if not label:
        return True
    key = _period_key(stored)
    if not key:
        return False
    keys = {_period_key(label)}
    day, _ym = _natural_date(asked)
    if day is not None:
        day_keys = _natural_period_forms(asked) | {_period_key(asked)}
        keys |= day_keys
        full = {k for k in day_keys if len(k) >= 12}       # a full printed day, never a bare month/year
        return any(key == k or (k in full and (key.endswith(k) or key.startswith(k))) for k in keys)
    return key == _period_key(label)


def _text_day(*texts: str | None) -> dt.date | None:
    """The calendar day a question names ('In the 2026-05-27 call ...'), so a named call ranks first (T-242)."""
    for text in texts:
        day, _ym = _natural_date(text)
        if day:
            return day
    return None


def norm_period(period: str | None) -> tuple[str | None, str | None]:
    """``(kind, label)``: Q2FY26 / H1FY26 / FY26 labels the tables use; ``kind`` is Q, H1, FY or None.
    Accepts Q2FY26, Q2 FY2026, FY2025-26, 2025-26, FY26, H1FY26, an ISO date and a printed natural date
    ('September 30, 2026', '30th Jun'25', 'Mar-26') -- its fiscal quarter (T-242)."""
    if period in (None, ""):
        return None, None
    day, ym = _natural_date(str(period))
    if day is not None or ym is not None:
        if day is not None:
            year, month = day.year, day.month
        else:
            assert ym is not None
            year, month = ym
        fy = year + 1 if month >= 4 else year
        q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[month]
        return "Q", f"Q{q}FY{str(fy)[-2:]}"
    text = re.sub(r"['’]", "", str(period)).strip().upper().replace(" ", "")
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
COVERAGE_DOCUMENTS = 40           # documents listed when a caller passes no limit-scaled cap (T-204)
DOCUMENTS_PER_ITEM = 3            # coverage.documents lists at most max(limit*3, 10) documents by default
DOCUMENTS_MIN = 10
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


def _doc_cap(documents: Any, limit: int) -> int | None:
    """How many matched documents ``coverage.documents`` lists: ``documents='all'`` names every one, otherwise at
    most max(limit*3, 10), so a two-item reply does not pay for forty documents (T-204)."""
    if str(documents or "").strip().lower() == "all":
        return None
    return max(int(limit) * DOCUMENTS_PER_ITEM, DOCUMENTS_MIN)


def _documents_index(entries: list[dict[str, Any]],
                     cap: int | None = COVERAGE_DOCUMENTS) -> dict[str, Any]:
    """EVERY document a reply matched: key, type, date, title, matching pages and match count, so a document whose
    items were cut is still named.  Only the first ``cap`` are listed (``None`` = every one); the rest are summed by
    type and month and counted in ``documents_not_listed`` (a reply never grows past what a model can read)."""
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
    shown = listed if cap is None else listed[:cap]
    out: dict[str, Any] = {"documents": shown, "matched_documents": len(listed)}
    if len(listed) > len(shown):
        out["documents_not_listed"] = len(listed) - len(shown)
    summary: dict[tuple[str, str], int] = {}
    for doc in listed[len(shown):]:
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
              offset: int = 0, documents: list[dict[str, Any]] | None = None,
              doc_cap: int | None = COVERAGE_DOCUMENTS, document_total: int | None = None,
              outside: list[dict[str, Any]] | None = None, hidden: dict[str, Any] | None = None) -> dict[str, Any]:
    """The coverage block every text reply carries (T-197 step 1)."""
    cov: dict[str, Any] = {"searched": list(searched), "not_searched": [s for s in not_searched if s],
                           "matched_total": matched_total, "shown": shown, "cut": cut, "offset": offset}
    if documents is not None:
        cov.update(_documents_index(documents, doc_cap))
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


def _trim_around(text: str | None, words: list[str], n: int) -> str | None:
    """The ``n``-character window that keeps the most asked words, so trimming a long quote keeps the match
    (T-242 fix 6: one sentence of a long observation, not the first asked word in it)."""
    if text is None:
        return None
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= n:
        return text
    low = text.lower()
    words = [w for w in words if w]
    spots: set[int] = set()
    for w in words:
        needle = w.lower()
        for needle in [needle] + ([needle[:5]] if len(needle) >= 5 else []):
            at = low.find(needle)
            while at >= 0:
                spots.add(at)
                at = low.find(needle, at + 1)
    if not spots:
        return text[:n].rstrip() + " …"
    best: tuple[int, int, int] | None = None
    for at in sorted(spots):
        start = max(0, at - n // 3)
        piece = low[start:start + n]
        exact = sum(1 for w in words if w.lower() in piece)
        stem = sum(1 for w in words if len(w) >= 5 and w.lower()[:5] in piece)
        key = (-exact, -stem, at)         # a window holding the literal words before one holding only their stems
        if best is None or key < best:
            best = key
    start = max(0, best[2] - n // 3) if best else max(0, min(spots) - n // 3)
    piece = text[start:start + n].strip()
    if start + n < len(text) and text[start + n - 1].isalnum():
        tail = re.match(r"\S*", text[start + n:start + n + 40])      # never cut the asked word in half
        if tail and tail.group(0):
            piece = (piece + tail.group(0)).strip()
    return ("… " if start else "") + piece.rstrip() + " …"


def _prov(table: str, source: str, known_at: str | None, **extra: Any) -> dict[str, Any]:
    return {"table": table, "source": source, "known_at": known_at, **{k: v for k, v in extra.items() if v is not None}}


def _db_prov(**extra: Any) -> dict[str, Any]:
    path = db_path()
    built = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime)) if path.exists() else None
    have = store_version()
    out: dict[str, Any] = {"db": "pilot3", "path": str(path), "read_only": True, "built": built,
                           "schema_version": have}
    if have < p3_schema.LATEST:   # T-202: say it plainly instead of quietly serving the older rule
        out["schema_note"] = (f"store schema v{have}, latest v{p3_schema.LATEST}: a lookup falls back to the older "
                              "rule for a column this build lacks; migrate a copy with python -m "
                              "reality_engine.pilot3.schema --db <store> --migrate")
    entries = [] if _pinned() is not None else stores()
    symbol = _SYMBOL.get()
    for row in entries:
        if row["path"] == path:
            out["store"] = row["name"]
        elif symbol and symbol in set(row["symbols"]):
            out.setdefault("also_held_in", []).append(str(row["path"]))
    return {**out, **extra}


_INR_UNIT_MULTIPLIER = {
    "inr": 1.0, "rs": 1.0, "rupee": 1.0, "rupees": 1.0,
    "inr_thousand": 1e3, "inr_k": 1e3,
    "inr_lakh": 1e5, "inr_lakhs": 1e5, "inr_lac": 1e5, "inr_lacs": 1e5,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "inr_mn": 1e6, "inr_million": 1e6, "inr_millions": 1e6,
    "inr_cr": 1e7, "inr_crore": 1e7, "inr_crores": 1e7,
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "inr_bn": 1e9, "inr_billion": 1e9, "inr_billions": 1e9,
    "inr_lakh_crore": 1e12,
}


def _money_inr_cr(value: Any, unit: str | None, scale: Any = None) -> tuple[float, float | None] | None:
    """Return ``(value_inr, value_cr)`` for an INR money figure, else None for non-money / per-share / FX units.

    ``value_cr`` is omitted (``None``) when the magnitude is under 0.01 crore (Rs. 1 lakh) so tiny rupee figures do
    not round to ``0.0``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    u = re.sub(r"[\s\-]+", "_", str(unit or "").strip().lower()).strip("_")
    if not u or "share" in u or "per_" in u or "/" in u:
        return None
    unit_mult = _INR_UNIT_MULTIPLIER.get(u)
    if unit_mult is None:
        # T-242 fix 7: the same money spelled "₹ in Crs.", "Rs. in Crs.", "₹ crore" or "Rs. mn" (the printings the
        # unit map does not spell) is still INR money; a non-rupee unit ("USD Mn") is never converted here.
        low = str(unit or "").lower()
        if not any(tok in low for tok in ("₹", "inr", "rs", "rupee")):
            return None
        if "lakh crore" in low or "lakh cr" in low:
            unit_mult = 1e12
        elif "crore" in low or re.search(r"\bcrs?\b", low):
            unit_mult = 1e7
        elif "lakh" in low or re.search(r"\blacs?\b", low):
            unit_mult = 1e5
        elif "billion" in low or re.search(r"\bbn\b", low):
            unit_mult = 1e9
        elif "million" in low or re.search(r"\bmn\b", low):
            unit_mult = 1e6
        elif "thousand" in low:
            unit_mult = 1e3
        else:
            unit_mult = 1.0
    try:
        sc = float(scale) if scale not in (None, "", 0) else None
    except (TypeError, ValueError):
        sc = None
    mult = sc if (sc is not None and sc != 1.0) else unit_mult
    inr = num * mult
    cr = round(inr / 1e7, 2) if abs(inr) >= 1e5 else None
    return inr, cr


def _money_base(value: Any, unit: str | None, scale: Any = None) -> float | None:
    """A money value on one base (rupees) whatever the store's unit spelling, else the bare number.

    Some filings print "Rs. Crore", "Rs. in Crs." or "Rs. Cr", which ``_INR_UNIT_MULTIPLIER`` does not spell; two
    such printings still describe the same money (T-242 fix 6: a filed value and a call remark are compared)."""
    pair = _money_inr_cr(value, unit, scale)
    if pair is not None:
        return pair[0]
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    try:
        sc = float(scale) if scale not in (None, "", 0) else 1.0
    except (TypeError, ValueError):
        sc = 1.0
    if sc not in (1.0, 0.0):
        return num * sc
    low = re.sub(r"[^a-z]+", " ", str(unit or "").lower())
    if "crore" in low or re.search(r"\bcr\b", low):
        return num * 1e7
    if "million" in low or re.search(r"\bmn\b", low):
        return num * 1e6
    if "billion" in low or re.search(r"\bbn\b", low):
        return num * 1e9
    if "lakh" in low:
        return num * 1e5
    return num


def _add_money(row: dict[str, Any], value: Any, unit: str | None, scale: Any = None) -> dict[str, Any]:
    """Attach ``value_inr`` (and ``value_cr`` when >= 0.01 crore) in place when ``(value, unit, scale)`` is INR."""
    pair = _money_inr_cr(value, unit, scale)
    if pair is not None:
        row["value_inr"] = pair[0]
        if pair[1] is not None:
            row["value_cr"] = pair[1]
    return row


# T-242 fix 9: the digits a row's own quote prints are evidence the store's value must reproduce.  AYE's deck card
# prints "AUM Sep-26 INR 7,597" while the store holds 75.97 crore (the extractor dropped the hundreds), so that row
# is never elected first beside the filing rows that print 7,597 crore.
_QUOTE_MONEY = re.compile(
    r"(?<![\w.])(?:₹|rs\.?|inr|usd|\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(crores?|crs?|lakhs?|lacs?|millions?|mn|billions?|bn|thousand)?(?![\w.])",
    re.I)
_QUOTE_MONEY_MULT = {"crore": 1e7, "crores": 1e7, "cr": 1e7, "crs": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
                     "lacs": 1e5, "million": 1e6, "millions": 1e6, "mn": 1e6, "billion": 1e9, "billions": 1e9,
                     "bn": 1e9, "thousand": 1e3}


def _quote_scale_mismatch(value: Any, unit: str | None, scale: Any, quote: str | None) -> bool:
    """T-242 fix 9: can the money figure the row's own quote prints reproduce the row's value in its unit?

    Only an INR money row is checked, and a quote that prints no money figure is never demoted on a guess.  The
    comparison is the row's own currency base, so "7,597 crore", "7,597" (in a crore row) and "70.44 billion" all
    reproduce their value."""
    pair = _money_inr_cr(value, unit, scale)
    unit_pair = _money_inr_cr(1.0, unit)
    if pair is None or unit_pair is None or not str(quote or "").strip():
        return False
    saved, unit_mult = pair[0], unit_pair[0]
    if not saved:
        return False
    tol = max(abs(saved) * 0.01, 1e-9)
    seen = False
    for match in _QUOTE_MONEY.finditer(str(quote)):
        try:
            number = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        word = (match.group(2) or "").lower().rstrip(".")
        seen = True
        if abs(number * _QUOTE_MONEY_MULT.get(word, unit_mult) - saved) <= tol:
            return False
    return seen



# --- T-239: model-free query expansion, and the pages to read when a lookup has no row ------------------
SYNONYMS_PATH = Path(__file__).with_name("synonyms.json")


@functools.lru_cache(maxsize=1)
def _synonym_groups() -> tuple[tuple[str, ...], ...]:
    """The committed thesaurus (``synonyms.json``): each group is one question word and the words the held pages
    print for it.  Built from the trial-2 failures, so every pair has a measured miss behind it."""
    try:
        data = json.loads(SYNONYMS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    out = []
    for group in data.get("groups") or ():
        terms = tuple(dict.fromkeys(str(t).strip().lower() for t in group.get("terms") or () if str(t).strip()))
        if len(terms) > 1:
            out.append(terms)
    return tuple(out)


def _expansion(text: str | None) -> tuple[list[str], list[str]]:
    """(expansions, matched): the other terms of every synonym group the text names, and the terms it named.

    An expansion stands in for the word it belongs to, so a caller OR-s it in and never adds it as a requirement."""
    low = " " + re.sub(r"[^a-z0-9%]+", " ", str(text or "").lower()) + " "
    extra: list[str] = []
    matched: list[str] = []
    for group in _synonym_groups():
        hits = [t for t in group if f" {t} " in low]
        if not hits:
            continue
        matched.extend(hits)
        extra.extend(t for t in group if t not in hits and t not in extra)
    return extra[:16], list(dict.fromkeys(matched))[:8]


def _synonyms_for(word: str) -> list[str]:
    """The other terms of the one group ``word`` belongs to (empty when it belongs to none)."""
    w = str(word or "").strip().lower()
    for group in _synonym_groups():
        if w in group:
            return [t for t in group if t != w]
    return []


def _fts_any(terms: list[str]) -> str:
    """FTS5 OR over terms; a multi-word term stays one phrase ("capital outlay").  Every term is optional."""
    clean = [re.sub(r'"', " ", str(t)).strip() for t in terms if str(t).strip()]
    return " OR ".join(f'"{t}"' for t in clean[:16])


def _fts_groups(words: list[str], mode: str = "and") -> str:
    """FTS5 with each word OR its synonyms: ``(w OR s1 OR s2) AND (...)``, so an expansion is an alternative to its
    word and never an extra requirement (T-239).  ``mode='or'`` is the old fallback for a query nothing matches."""
    joiner = " AND " if mode == "and" else " OR "
    groups = []
    for word in words[:10]:
        alts = [word] + _synonyms_for(word)
        groups.append("(" + " OR ".join(f'"{re.sub(chr(34), " ", a)}"' for a in alts) + ")")
    return joiner.join(groups)


def _word_groups(words: list[str], cols: list[str]) -> tuple[str, list[Any], list[str]]:
    """SQL ``(word OR its synonyms) AND (...)`` over LIKE columns: an expansion is an alternative, never a must."""
    clause: list[str] = []
    args: list[Any] = []
    used: list[str] = []
    for word in words:
        alts = [word] + _synonyms_for(word)
        if len(alts) > 1:
            used.append(word)
        clause.append("(" + " OR ".join(f"{col} LIKE ?" for _alt in alts for col in cols) + ")")
        args.extend(f"%{alt}%" for alt in alts for _col in cols)
    return " AND ".join(clause), args, used


def _expansions_hit(words: str | None, rows: Any) -> list[str]:
    """The synonym expansions that actually appear in the rows a reply serves, so the reply says which one matched."""
    expansions, _named = _expansion(words)
    if not expansions:
        return []
    blob = " ".join(str(row) for row in rows).lower()
    return [t for t in expansions if t in blob][:6]


def _nearest(symbol: str, words: str | None, as_of: str | None = None, cap: int = 3) -> list[dict[str, Any]]:
    """The pages and statements to READ when a lookup holds no row for the words (T-239).

    Top ``cap`` FTS page hits and top ``cap`` ``obs_fact`` statements, as_of-cut, each labelled so the answer says
    "the store has no row for those words; read this page" instead of "not disclosed".  Snippets only, never a page
    dump, and a query expansion widens the search without ever being required."""
    text = str(words or "").strip()
    if not text or not _has_table("doc_page"):
        return []
    expansions, matched = _expansion(text)
    out: list[dict[str, Any]] = []
    day = _day(as_of, "as_of")
    asql, aargs = _asof(day, "COALESCE(p.known_at, d.known_at)")
    question = [w for w in re.findall(r"[\w₹%]+", text) if len(w) > 1 or w.isdigit()][:8]
    pages: list[sqlite3.Row] = []
    if _has_table("doc_page_fts"):
        # a page carrying every question word (or its synonym) first; OR over all terms only when none does
        for match in (_fts_groups(question, "and"), _fts_any(question + expansions)):
            if not match:
                continue
            pages = _q(f"SELECT d.doc_key, d.doc_type, d.title, d.filing_date, p.page, p.known_at, "
                       f"snippet(doc_page_fts, 0, '[', ']', ' … ', 24) snip FROM doc_page_fts f "
                       f"JOIN doc_page p ON p.rowid=f.rowid JOIN doc d ON d.doc_key=p.doc_key "
                       f"WHERE doc_page_fts MATCH ? AND p.symbol=?{asql} ORDER BY rank LIMIT ?",
                       (match, symbol, *aargs, cap))
            if pages:
                break
    for r in pages:
        out.append({"kind": "page", "doc_key": r["doc_key"], "doc_type": r["doc_type"],
                    "title": _trim(r["title"], 60), "filing_date": r["filing_date"], "page": r["page"],
                    "known_at": r["known_at"], "snippet": _trim(r["snip"], 300),
                    "matched": matched or None, "note": "not a stored row: read the page"})
    word_list = [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2][:6]
    non_period = [w for w in word_list if not re.fullmatch(r"(?:q[1-4]|h[12])?fy\d{2,4}", w)]
    if non_period:
        word_list = non_period
    cols = [c for c in ("statement", "measure", "printed_label", "segment", "series_title")
            if _has_column("obs_fact", c)] if _has_table("obs_fact") else []
    if word_list and cols:
        extra, eargs = _asof(day, "o.known_at")
        opt_cols = [c for c in ("value", "value_high", "unit", "scale", "printed_label", "segment")
                    if _has_column("obs_fact", c)]
        opt_sql = (", " + ", ".join(f"o.{c}" for c in opt_cols)) if opt_cols else ""
        where, wargs, _used = _word_groups(word_list, [f"o.{c}" for c in cols])
        obs_near = _q(f"SELECT o.measure, o.record_type, o.period, o.statement, o.doc_key, o.page, o.known_at, "
                      f"o.status{opt_sql} FROM obs_fact o WHERE o.symbol=? AND o.status IN ('verified','unverified') "
                      f"AND ({where}){extra} ORDER BY (o.status='verified') DESC, o.known_at DESC LIMIT ?",
                      (symbol, *wargs, *eargs, cap))
        if not obs_near and len(word_list) >= 2:
            or_parts, or_args = [], []
            score_parts, score_args = [], []
            for w in word_list:
                alts = [w] + _synonyms_for(w)
                sub = " OR ".join(f"o.{c} LIKE ?" for c in cols for _ in alts)
                or_parts.append(f"({sub})")
                for _ in cols:
                    for a in alts:
                        or_args.append(f"%{a}%")
                score_parts.append(f"(CASE WHEN ({sub}) THEN 1 ELSE 0 END)")
                for _ in cols:
                    for a in alts:
                        score_args.append(f"%{a}%")
            obs_near = _q(f"SELECT o.measure, o.record_type, o.period, o.statement, o.doc_key, o.page, o.known_at, "
                          f"o.status{opt_sql}, ({' + '.join(score_parts)}) AS hit_score FROM obs_fact o "
                          f"WHERE o.symbol=? AND o.status IN ('verified','unverified') AND ({' OR '.join(or_parts)})"
                          f"{extra} ORDER BY hit_score DESC, (o.status='verified') DESC, o.known_at DESC LIMIT ?",
                          (*score_args, symbol, *or_args, *eargs, cap))
        for r in obs_near:
            keys = set(r.keys())
            g = lambda k: (r[k] if k in keys else None)
            if r["record_type"] == "number":
                item: dict[str, Any] = {
                    "kind": "number", "measure": r["measure"], "record_type": r["record_type"],
                    "value": g("value"), "unit": g("unit"), "period": r["period"],
                    "printed_label": _trim(g("printed_label"), 200), "status": r["status"],
                    "doc_key": r["doc_key"], "page": r["page"], "known_at": r["known_at"],
                    "matched": matched or None,
                    "note": "an obs_fact number row, not an exact match for the words asked: check label and period",
                }
                if g("value_high") is not None:
                    item["value_high"] = g("value_high")
                if g("segment"):
                    item["segment"] = g("segment")
                _add_money(item, g("value"), g("unit"), g("scale"))
                out.append(item)
            else:
                out.append({"kind": "statement", "measure": r["measure"], "record_type": r["record_type"],
                            "period": r["period"], "statement": _trim(r["statement"], 300),
                            "status": r["status"], "doc_key": r["doc_key"], "page": r["page"],
                            "known_at": r["known_at"], "matched": matched or None,
                            "note": "a stored statement, not a row for the words asked: read the page"})
    return out


def _reply(symbol: str, rows: list[dict], tool: str, nearest: str | None = None,
           nearest_as_of: str | None = None, **extra: Any) -> dict[str, Any]:
    out = {"found": bool(rows), "symbol": symbol, "tool": tool, "n": len(rows), "rows": rows,
           "nearest": _nearest(symbol, nearest, nearest_as_of or extra.get("as_of")) if (nearest and not rows) else [],
           **extra, "provenance": _db_prov()}
    if not out["nearest"]:
        out.pop("nearest")          # an empty reply keeps its old shape when there is nothing to read either
    if extra.get("as_of"):
        # one shared point-in-time report (T-197 step 5): every tool that serves document-derived rows says which
        # documents the passed as_of hid and on what dates, so a miss after a date is never read as "not held".
        hidden = _hidden_documents(symbol, extra.get("as_of"))
        covered = set(out.get("coverage") or {})
        for key, value in hidden.items():
            if key not in covered:      # a text reply carries the point-in-time block inside coverage only (T-204)
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


_MEASURE_ALIASES = {
    "pbt": "profit_before_tax",
    "gwp": "gross_written_premium",
    "capacity_utilisation": "capacity.utilisation",
    "capacity_utilization": "capacity.utilisation",
    # T-242 fix 6: the words investors use for a line the store files under its short code.  One map serves every
    # route (`_pick` is used by fact, fin, kpi, guidance, ratio and obs), so "profit after tax" resolves wherever
    # "PAT" does, and "installed capacity" reaches the point-in-time capacity.total row.
    "profit_after_tax": "pat",
    "net_profit": "pat",
    "installed_capacity": "capacity.total",
    # T-242 fix 8: a line the store files as "capex" is also asked for as "capital expenditure" (audit 8: ALKEM's
    # AR p330 "capital expenditure of Rs 10,360 Million" was held in kpi_series and unreachable through fact/fin).
    "capital_expenditure": "capex",
    "capital_expenditures": "capex",
    "capital_outlay": "capex",
    # T-242 fix 9: the spelled-out name of a ratio / KPI the store files under its short code (audit 9: ARCIL
    # "return on equity" was found=false while "ROE" answered 18.1%, AIAENG "earnings per share" vs "EPS" 26.76).
    "return_on_equity": "roe",
    "return_on_capital_employed": "roce",
    "return_on_assets": "roa",
    "earnings_per_share": "eps",
    "net_interest_margin": "nim",
    "gross_non_performing_assets": "gnpa",
    "assets_under_management": "aum",
}


def _norm_measure(name: str) -> str:
    """Normalize a measure name for matching: strip leading 'NEW:' and split/join on [_.\\s-]+."""
    clean = re.sub(r"^new:", "", str(name or "").strip(), flags=re.I).strip("<>")
    norm = re.sub(r"[_.\s\-]+", "_", clean.lower()).strip("_")
    return norm.replace("utilization", "utilisation")


def _same_series(name: str, key: str) -> bool:
    """Does ``name`` belong to the same series as ``key``?  A token match over [_.], stripping 'NEW:'."""
    low = _norm_measure(name)
    k = _norm_measure(key)
    if not k:
        return False
    return (low == k or k in low.split("_") or low.startswith(k + "_") or low.endswith("_" + k)
            or low == f"{k}_pct")


# T-242: the tokens a measure code may append to a printed label and still BE that label's row.  A page prints
# "Water withdrawal 7.17% YoY" -> label "Water withdrawal", measure NEW:water_withdrawal_reduction_yoy; the words
# after the label are the movement the page reports, not a different measure.
_MOVEMENT_TOKENS = {"growth", "yoy", "qoq", "pct", "pp", "change", "delta", "reduction", "reductions", "increase",
                    "decrease", "improvement", "improvements", "decline", "grew", "grow", "rise", "rose", "fall",
                    "fell", "up", "down"}


def _label_covers(label: str, measure: str) -> bool:
    """Do the label's words name this measure code?  Every label token of 3+ letters appears in the code, and every
    extra code token is a movement word ('Dependence on third-party water' ->
    NEW:third_party_water_dependence_reduction_yoy)."""
    toks = {t for t in _norm_measure(label).split("_") if len(t) > 2}
    mtoks = set(_norm_measure(measure).split("_")) - {""}
    return bool(toks) and toks <= mtoks and not ((mtoks - toks) - _MOVEMENT_TOKENS)


def _pick(table: str, col: str, symbol: str, name: str, extra: str = "") -> tuple[list[str], list[str]]:
    """Names to match for a user's metric word: exact first, then [_.]/NEW: normalized, else series/alias."""
    key = re.sub(r"[\s\-]+", "_", name.strip().lower())
    names = _available(table, col, symbol, extra=extra, n=5000)
    if key in names:
        return [key], names
    nk = _norm_measure(key)
    alias = _MEASURE_ALIASES.get(nk) or _KPI_WORDS.get(key) or ""
    cand_keys = list(dict.fromkeys(x for x in (nk, _norm_measure(alias)) if x))
    exacts = list(dict.fromkeys(n for ck in cand_keys for n in names if _norm_measure(n) == ck))
    if exacts:
        return exacts, names
    for cand_key in cand_keys:
        near = [n for n in names if _same_series(n, cand_key)]
        if near:
            near.sort(key=lambda n: (
                0 if not str(n).upper().startswith("NEW:") else 1,
                0 if _norm_measure(n) in (f"{cand_key}_value", f"{cand_key}_pct",
                                          f"{cand_key}_from_operations", f"{cand_key}_total") else 1,
            ))
            return near[:16], names
    return [], names


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
    "opex_to_net_total_income": "opex_to_nti", "opex_to_net_interest_income": "opex_to_nti",
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


def _atom_matches(metric: str, label: str) -> bool:
    """Does a printed row label name the metric the caller asked for (the metric key, or its investor alias)?"""
    key = _metric_key(metric)
    alias = _KPI_WORDS.get(key, key)
    norm = _metric_key(label or "")
    return bool(key) and (norm == key or norm == alias or norm.startswith(key + "_") or key in norm)


@functools.lru_cache(maxsize=1)
def _metric_units() -> dict[str, str]:
    """metric -> the unit its own definition already carries: the KPI lexicon's entries (what ``kpi_series`` is
    extracted with) and the ratio formulas behind ``ratio_panel`` (T-199 round 2)."""
    from reality_engine.pilot3 import kpi as p3_kpi
    from reality_engine.pilot3 import ratios as p3_ratios
    units = {entry.metric: entry.unit for entry in p3_kpi.load_lexicon()[0] if entry.unit}
    units.update({formula[1]: formula[4] for formula in p3_ratios.FORMULAS})
    return units


def _unit_family(unit: str | None) -> str:
    """pct / x / days / count / money / '' for a unit a metric definition or an atom carries."""
    key = str(unit or "").strip().lower()
    if key in ("%", "pct", "percent", "per cent", "bps", "basis_points", "basis points"):
        return "pct"
    if key in ("x", "ratio", "multiple", "times"):
        return "x"
    if key.startswith("days"):
        return "days"
    if key.startswith("count") or key in ("mn", "million"):
        return "count"
    if (key.startswith(("inr", "usd", "money")) or "crore" in key or re.search(r"\bcrs?\b", key)
            or "₹" in key or key.startswith("rs")):
        return "money"
    return ""


def _metric_family(metric: str) -> str:
    """The unit family the metric's own definition carries; '' when no definition names the metric."""
    key = _metric_key(metric)
    units = _metric_units()
    for name in (key, _KPI_WORDS.get(key, key), f"{key}_pct"):
        if name in units:
            return _unit_family(units[name])
    for name, unit in units.items():
        if name.startswith(key + "_") or key in name:
            return _unit_family(unit)
    return ""


def _atom_unit_fits(metric: str, unit: str | None, scale: float | None) -> bool:
    """T-199 round 2: is this atom's unit the family the metric's own definition carries?

    A ``change`` atom is never a level; a metric whose definition is known takes only an atom of the same family
    (a margin pct/bps, a revenue or a PAT inr/usd with a scale, a ratio x, a days KPI days).  A metric no
    definition names is not filtered: only a definition can prove a unit is the wrong one."""
    if str(unit or "") == "change":
        return False
    want = _metric_family(metric)
    if not want:
        return True
    return _unit_family(unit) == want and (want != "money" or bool(scale))


def _kpi_atoms(sym: str, metric: str, period: str | None, day: str | None, limit: int) -> list[dict[str, Any]]:
    """T-199: the resolved printed figures for a KPI no extractor table holds, served as ``page_atom`` rows.

    Only an atom whose row label names the KPI and whose unit fits the metric's own definition is served: a pct
    atom never answers an amount KPI, nor an inr atom a ratio (T-199 round 2)."""
    if not _has_table("page_atom"):
        return []
    words = [w for w in re.split(r"[^a-z0-9%]+", str(metric or "").lower()) if len(w) >= 2]
    if not words:
        return []
    where = ["a.symbol=?", "COALESCE(a.unit,'')<>'change'"]
    args: list[Any] = [sym]
    for word in words:
        where.append("lower(COALESCE(a.row_label,'')||' '||COALESCE(a.table_title,'')) LIKE ?")
        args.append(f"%{word}%")
    _kind, label = norm_period(period)
    if label:
        where.append("lower(COALESCE(a.period,''))=lower(?)")
        args.append(label)
    extra, eargs = _asof(day, "a.known_at")
    rows = _q(
        "SELECT a.doc_key, a.page, a.known_at, a.row_label, a.col_header, a.period, a.basis, a.value, a.unit, "
        "a.scale, a.value_text, a.check_status, a.check_reasons, COALESCE(d.doc_type,'') AS doc_type, "
        f"COALESCE(d.title,'') AS title FROM page_atom a LEFT JOIN doc d ON d.doc_key=a.doc_key "
        f"WHERE {' AND '.join(where)}{extra} "
        "ORDER BY CASE COALESCE(a.check_status,'') WHEN 'verified' THEN 0 ELSE 1 END, "
        "substr(COALESCE(a.known_at,''),1,10) DESC, a.page LIMIT 40", (*args, *eargs))
    out: list[dict[str, Any]] = []
    for r in rows:
        if not _atom_matches(metric, r["row_label"]):
            continue
        if not _atom_unit_fits(metric, r["unit"], r["scale"]):     # T-199 r2: a pct atom is never the amount
            continue
        out.append(_add_money({
            "metric": _metric_key(r["row_label"]), "dimension": "total", "value": r["value"],
            "unit": r["unit"], "scale": r["scale"], "period": r["period"] or label,
            "period_type": None, "as_of_date": None,
            "basis": r["basis"] if r["basis"] in _REPORTING_BASES else "not_stated",
            "entity": sym, "raw_label": r["row_label"],
            "quote": f"{r['row_label']} | {r['col_header']}: {r['value_text']} {r['unit']}".strip(),
            "check_status": r["check_status"], "check_reasons": r["check_reasons"], "source": "page_atom",
            "provenance": _prov("page_atom", f"p{r['page']}", r["known_at"], doc_type=r["doc_type"],
                                title=r["title"])}, r["value"], r["unit"], r["scale"]))
    return out[: _cap(limit)]


def kpi(symbol: str, kpi: str, period: str | None = None, as_of: str | None = None,
        dimension: str | None = None, basis: str | None = None, limit: int = 10,
        include_quarantined: bool = False) -> dict[str, Any]:
    """A company-stated KPI (order book, AUM, EBITDA/tonne, NIM ...) from decks, results, releases, transcripts."""
    sym = resolve_symbol(symbol)
    metric_asked = kpi
    kpi = _KPI_WORDS.get(re.sub(r"[\s\-]+", "_", str(kpi).strip().lower()), kpi)
    bas_flt = basis.strip().lower() if basis else None
    obs_rows = (_obs_kpi_rows(sym, kpi, period, as_of, _cap(limit), basis=bas_flt)
                if _has_table("obs_fact") else [])
    # the metric NAME is not hidden by a quarantine: the row-level filter below hides the rows and the empty
    # reply says they are held but quarantined (T-165: CHOLAFIN Q2FY27 NIM 7.9 is the only row of its period)
    names, allnames = _pick("kpi_series", "metric", sym, kpi)
    if not names:
        if obs_rows:
            return _reply(sym, obs_rows[: _cap(limit)], "pilot3_kpi", metrics_matched=[kpi], source="obs_fact",
                          as_of=_day(as_of, "as_of"))
        atom_rows = _kpi_atoms(sym, kpi, period, _day(as_of, "as_of"), limit)
        if atom_rows:
            return _reply(sym, atom_rows, "pilot3_kpi", metrics_matched=[kpi], source="page_atom",
                          as_of=_day(as_of, "as_of"))
        return _reply(sym, [], "pilot3_kpi", available=allnames[:40], metric_asked=metric_asked,
                      nearest=f"{metric_asked} {period or ''}".strip(), nearest_as_of=as_of)
    kind, label = norm_period(period)
    natural, _ym = _natural_date(period)
    where, args = f"k.symbol=? AND k.metric IN ({','.join('?' * len(names))})", [sym, *names]
    if label and natural is None:
        where += " AND k.fiscal_period=?"
        args.append(label)
    if dimension:
        where += " AND lower(k.dimension)=?"
        args.append(dimension.strip().lower())
    if bas_flt:
        where += " AND k.basis=?"
        args.append(bas_flt)
    join, check_sel, hide = _check_cols("kpi_series", "k.id")
    visible_where = where          # without the quarantine clause: the "held but hidden" note needs it
    if not include_quarantined:
        where += hide
    extra, eargs = _asof(as_of, "k.known_at")
    sel = (f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.scale, k.fiscal_period, k.period_type, "
           f"k.as_of_date, k.basis, k.entity, k.doc_key, k.page, k.quote, k.known_at, k.conf_rank, k.raw_label, "
           f"d.doc_key AS dk, d.title, d.doc_type{check_sel} FROM kpi_series k {_DOC_JOIN}{join} ")
    # best evidence first: the extractor's confidence, then a deck/results/filing before a call remark.
    # The window must reach past a measure's duplicates (one value restated in many filings): at 3x the
    # reply size, a restated measure filled it and its lower-confidence period series never arrived (T-049,
    # 4 Nov 2026: Bajaj's quarterly GNPA and KEC's order-intake trend came back as old annual rows only).
    q_tail = ("ORDER BY k.conf_rank DESC, "
              "CASE d.doc_type WHEN 'deck' THEN 0 WHEN 'results' THEN 1 WHEN 'press_release' THEN 2 "
              "WHEN 'annual_report' THEN 3 WHEN 'transcript' THEN 4 ELSE 5 END, "
              # the group statement before standalone when both are filed (as pilot3_fin does): HINDUNILVR Q2FY27
              # Beauty & Wellbeing EBIT came back standalone 1,242 first (filed later) for consolidated 1,235 (8 Nov)
              "(k.dimension='total') DESC, (k.basis='consolidated') DESC, k.known_at DESC, k.id LIMIT ?")
    rows = _q(sel + f"WHERE {where}{extra} " + q_tail, (*args, *eargs, _cap(limit) * 30))
    if natural is not None:     # a printed point-in-time label answers the date it prints (T-242 fix 6)
        rows = [r for r in rows if _period_matches(r["fiscal_period"], period)]
    seen: set[tuple] = set()

    def _items(rows_in: list[Any]) -> list[dict[str, Any]]:
        items_out: list[dict[str, Any]] = []
        for r in rows_in:
            row_basis = r["basis"] if r["basis"] in _REPORTING_BASES else "not_stated"
            entity = _entity_of(r, sym)
            dim = "total" if r["dimension"] in ("consolidated", "standalone") else r["dimension"]
            sig = (r["metric"], entity, dim, r["fiscal_period"], r["value"], r["unit"])
            if sig in seen:  # the same figure printed again by another filing: one row, best evidence first
                continue
            seen.add(sig)
            item = _add_check(_add_money(
                {"metric": r["metric"], "dimension": dim, "value": r["value"],
                 "unit": r["unit"], "scale": r["scale"], "period": r["fiscal_period"],
                 "period_type": r["period_type"], "as_of_date": r["as_of_date"], "basis": row_basis,
                 "entity": entity, "raw_label": r["raw_label"],
                 "quote": _trim(r["quote"], 300), "source": "kpi_series",
                 "provenance": _prov("kpi_series", f"{r['dk'] or r['doc_key']} p{r['page']}",
                                     r["known_at"], doc_type=r["doc_type"], title=r["title"],
                                     row_id=r["id"])}, r["value"], r["unit"], r["scale"]), r)
            item.setdefault("status", item.get("check_status"))
            # T-242 fix 9: the quote's own digits say whether the stored value is the page's figure (AYE 75.97 vs
            # "INR 7,597"): a mismatched row is served later, labelled, never elected first.
            if _quote_scale_mismatch(r["value"], r["unit"], r["scale"], r["quote"]):
                item["scale_mismatch"] = True
            items_out.append(item)
        return items_out

    out = _items(rows)
    # the company's own rows first (T-088), then the operating definition of a measure that has several (T-192)
    out.sort(key=lambda row: (0 if row["entity"] == sym else 1, _definition_rank(row, str(row["metric"])),
                              1 if row.get("scale_mismatch") else 0))
    if obs_rows:
        combined = out + obs_rows
        combined.sort(key=lambda row: (
            *_ask_row_rank(row, kpi, period),          # T-242 fix 7: company / asked period / unit / no scope
            1 if row.get("scale_mismatch") else 0,     # T-242 fix 9: a value its own quote cannot reproduce
            0 if row.get("entity", sym) == sym else 1,
            0 if not row.get("segment") else 1,
            _definition_rank(row, str(row.get("metric") or "")),
            0 if row.get("source") == "kpi_series" else 1,
        ))
        out = combined[: _cap(limit)]
        top_src = out[0].get("source") if out else None
        return _reply(sym, out, "pilot3_kpi", metrics_matched=names,
                      source=top_src if top_src == "obs_fact" else None,
                      as_of=_day(as_of, "as_of"))
    out = out[: _cap(limit)]
    held = None
    held_hidden = None
    if not out:  # the metric exists: say which periods / dimensions hold it, so the next call can be exact
        atom_rows = _kpi_atoms(sym, kpi, period, _day(as_of, "as_of"), limit)
        if atom_rows:                      # T-199: a page atom answers when no extractor row has the period
            return _reply(sym, atom_rows, "pilot3_kpi", metrics_matched=names, source="page_atom",
                          as_of=_day(as_of, "as_of"))
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT fiscal_period, dimension, COUNT(*) FROM kpi_series WHERE symbol=? AND metric IN "
            f"({','.join('?' * len(names))}){_visible('kpi_series')} "
            f"GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
        # A figure the row check quarantined is still held (T-113): say so, or the caller reads a deliberate hide
        # as "not in data" (CHOLAFIN Q2FY27 NIM 7.9 is exactly this, T-165).
        if not out and not include_quarantined and _has_table("row_check"):
            q_where = (visible_where + " AND EXISTS (SELECT 1 FROM row_check rc WHERE rc.tbl='kpi_series' "
                       "AND rc.row_id=k.id AND rc.status='quarantined')")
            held_hidden = [f"{r[0]} / {r[1]} ({r[2]} rows; the row check quarantined them: "
                           f"include_quarantined=true shows them)" for r in _q(
                f"SELECT k.fiscal_period, k.dimension, COUNT(*) FROM kpi_series k WHERE {q_where} "
                f"GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20", tuple(args))]
    return _reply(sym, out, "pilot3_kpi", metrics_matched=names, held_period_dimension=held,
                  held_quarantined=held_hidden, as_of=_day(as_of, "as_of"),
                  nearest=f"{metric_asked} {period or ''}".strip(), nearest_as_of=as_of)


# --- pilot3_cells ------------------------------------------------------------------------------------
def _atoms_here(sym: str) -> bool:
    """Does this store serve resolved page atoms for the company?  A store migrated to v10 but not yet rebuilt by
    ``build --part atoms`` has the table and no rows: its ``page_cell`` rows still answer (T-199)."""
    return _has_table("page_atom") and bool(_q("SELECT 1 FROM page_atom WHERE symbol=? LIMIT 1", (sym,)))


def _cells_from_atoms(sym: str, terms: str | None, period: str | None, day: str | None,
                      include_unverified: bool, limit: int, offset: int,
                      documents: str | None) -> dict[str, Any]:
    """``pilot3_cells`` over ``page_atom``: the resolved period / basis / unit / scale / value of every figure."""
    words = [w for w in re.split(r"[^\w%]+", str(terms or "").lower()) if len(w) >= 2]
    where = ["a.symbol=?"]
    args: list[Any] = [sym]
    for word in words:
        where.append("lower(COALESCE(a.row_label,'')||' '||COALESCE(a.col_header,'')||' '||"
                     "COALESCE(a.table_title,'')) LIKE ?")
        args.append(f"%{word}%")
    if not include_unverified:
        where.append("a.check_status='verified'")
    _kind, label = norm_period(period)
    natural, _ym = _natural_date(period)
    if label and natural is None:
        where.append("lower(COALESCE(a.period,''))=lower(?)")
        args.append(label)
    extra, eargs = "", []
    if day:
        extra = " AND substr(COALESCE(a.known_at,''),1,10) <= ?"
        eargs.append(day)
    cap, start = _window(limit, offset, 20)
    rows = _q(
        "SELECT a.doc_key, a.page, a.symbol, a.reader, a.table_title, a.row_label, a.col_header, a.period, "
        "a.basis, a.unit, a.scale, a.value, a.value_text, a.check_status, a.check_reasons, "
        "COALESCE(d.title,'') AS title, COALESCE(d.doc_type,'') AS doc_type, a.known_at AS filed_at "
        "FROM page_atom a LEFT JOIN doc d ON d.doc_key=a.doc_key "
        f"WHERE {' AND '.join(where)}{extra} "
        "ORDER BY CASE COALESCE(a.check_status,'') WHEN 'verified' THEN 0 ELSE 1 END, "
        "substr(COALESCE(a.known_at,''),1,10) DESC, a.page LIMIT ?",
        (*args, *eargs, max(400, (start + cap) * 10)))
    matched: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    starts = [re.compile(r"(?<![a-z0-9])" + re.escape(w)) for w in words]   # a term starts a word: 'us' != 'business'
    for r in rows:
        if natural is not None and not _period_matches(r["period"], period):
            continue
        text = " ".join((r["row_label"] or "", r["col_header"] or "", r["table_title"] or ""))
        if not all(p.search(text.lower()) for p in starts):
            continue
        sig = (r["doc_key"], r["page"], r["row_label"], r["col_header"], r["value_text"], r["unit"])
        if sig in seen:
            continue
        seen.add(sig)
        matched.append(_add_money({
            "value": r["value"], "value_text": r["value_text"], "unit": r["unit"], "unit_text": r["unit"],
            "scale": r["scale"], "period": r["period"] or None, "basis": r["basis"] or None,
            "row_label": _trim(r["row_label"], 120), "col_header": _trim(r["col_header"], 80),
            "table_title": _trim(r["table_title"], 80),
            "status": r["check_status"] or "unverified", "check_reasons": r["check_reasons"] or "",
            "doc_key": r["doc_key"], "doc_type": _DOC_TYPES.get((r["doc_type"] or "").lower(), r["doc_type"] or ""),
            "title": _trim(r["title"], 60), "page": r["page"], "known_at": r["filed_at"], "reader": r["reader"],
            "provenance": _prov("page_atom", f"p{r['page']}", r["filed_at"]),
        }, r["value"], r["unit"], r["scale"]))
    page = matched[start:start + cap]
    held = None
    if not matched:
        held = [f"{r[0]} ({r[1]} atoms)" for r in _q(
            "SELECT row_label, COUNT(*) FROM page_atom WHERE symbol=? GROUP BY 1 ORDER BY 2 DESC LIMIT 20", (sym,))]
    cut = max(0, len(matched) - len(page))
    docs = [{"doc_key": r["doc_key"], "doc_type": r["doc_type"], "date": r["known_at"], "title": r["title"],
             "page": r["page"]} for r in matched]
    text = _scope_line(len(matched), len(page), cut, start, docs, len({d["doc_key"] for d in docs}))
    reply = _reply(sym, page, "pilot3_cells", terms=terms, period=period, held_labels=held,
                   include_unverified=include_unverified, as_of=day, text=text,
                   coverage=_coverage("cells", ["page_atom (one resolved atom per printed figure: period, basis, "
                                                "unit, scale, value)",
                                                "doc (document type, title, filing date)"],
                                      ["documents whose pages the page reader never parsed",
                                       "transcript and announcement page text (pilot3_search / pilot3_topic)",
                                       "page_cell (raw reader cells; served only while page_atom has no rows)"],
                                      len(matched), len(page), cut, start, documents=docs,
                                      doc_cap=_doc_cap(documents, cap),
                                      hidden=_hidden_documents(sym, day)),
                   read_next=_read_next(page))

    def labels(width: int) -> None:
        for row in reply["rows"]:
            row["row_label"] = _trim(row.get("row_label"), width)
            row["table_title"] = _trim(row.get("table_title"), width)

    return _shrink(reply, [
        ("row labels cut to 80 characters", lambda: labels(80)),
        ("the list cut to the first 10 cells", lambda: reply["rows"].__delitem__(slice(10, None))),
        ("row labels cut to 50 characters", lambda: labels(50)),
    ])


def cells(symbol: str, terms: str, period: str | None = None, as_of: str | None = None,
          include_unverified: bool = True, limit: int = 20, offset: int = 0,
          documents: str | None = None) -> dict[str, Any]:
    """Figures read from table pages, plus (T-227) ``script_rows``: the model-free script reader's cells of the
    store's results pages, each with its resolved period, basis, unit and the witness that verified it.  The two
    sources are served side by side and labelled; neither replaces the other (Shivam 20 Nov, option 1)."""
    reply = _cells_core(symbol, terms, period, as_of, include_unverified, limit, offset, documents)
    try:
        sym, day = resolve_symbol(symbol), _day(as_of, "as_of")
        script = _script_cells(sym, terms, period, day, include_unverified, min(max(int(limit or 20), 1), 20))
    except DataError:
        script = None
    if script is not None:
        reply["script_rows"] = script
        if script and reply.get("found") is False:
            reply["found"] = True
    return reply


_SCRIPT_PERIOD = {"Q1": ("06-30", -1, "quarter"), "Q2": ("09-30", -1, "quarter"), "Q3": ("12-31", -1, "quarter"),
                  "Q4": ("03-31", 0, "quarter"), "H1": ("09-30", -1, "half"), "H2": ("03-31", 0, "half"),
                  "FY": ("03-31", 0, "year")}


def _script_cells(sym: str, terms: str | None, period: str | None, day: str | None,
                  include_unverified: bool, cap: int) -> list[dict[str, Any]] | None:
    """``script_cell`` rows (T-227) matching every term in the row label or section; ``period`` (Q2FY26, H1FY26,
    FY26) maps to the period end of a March fiscal year.  None when the store has no ``script_cell`` table."""
    if not _has_table("script_cell"):
        return None
    words = [w for w in re.split(r"[^\w%]+", str(terms or "").lower()) if len(w) >= 2]
    where, args = ["symbol=?"], [sym]
    for word in words:
        where.append("lower(COALESCE(row_label,'')||' '||COALESCE(section,'')||' '||COALESCE(table_title,'')) LIKE ?")
        args.append(f"%{word}%")
    if not include_unverified:
        where.append("status='verified'")
    if day:
        where.append("substr(known_at,1,10) <= ?")
        args.append(day)
    _, label = norm_period(period)
    m = re.fullmatch(r"(Q[1-4]|H[12]|FY)FY(\d{2})", label or "")
    if m:
        mmdd, shift, kind = _SCRIPT_PERIOD[m.group(1)]
        where.append("period_end=? AND period_kind=?")
        args += [f"{2000 + int(m.group(2)) + shift}-{mmdd}", kind]
    rows = _q("SELECT doc_key, page, known_at, table_title, section, row_label, col_header, value_text, value, "
              "unit_scale, period_end, period_kind, basis, period_inferred, basis_inferred, status, witness "
              f"FROM script_cell WHERE {' AND '.join(where)} "
              "ORDER BY CASE status WHEN 'verified' THEN 0 ELSE 1 END, known_at DESC, page LIMIT ?", (*args, cap))
    return [{"value_text": r["value_text"], "value_rupees": r["value"], "unit_scale": r["unit_scale"],
             "row_label": _trim(r["row_label"], 120), "section": _trim(r["section"], 60),
             "col_header": _trim(r["col_header"], 80), "period_end": r["period_end"], "period_kind": r["period_kind"],
             "basis": r["basis"], "status": r["status"], "witness": r["witness"],
             "inferred": ",".join(k for k, v in (("period", r["period_inferred"]), ("basis", r["basis_inferred"]))
                                  if v),
             "doc_key": r["doc_key"], "page": r["page"], "known_at": r["known_at"], "reader": "script",
             "provenance": _prov("script_cell", f"p{r['page']}", r["known_at"])} for r in rows]


def _cells_core(symbol: str, terms: str, period: str | None = None, as_of: str | None = None,
                include_unverified: bool = True, limit: int = 20, offset: int = 0,
                documents: str | None = None) -> dict[str, Any]:
    """Figures read from table and chart pages (decks, results, annual reports) by the page reader: one cell per
    printed figure with its row label, column header, table title and status. ``verified`` means the position check
    settled the cell; ``unverified`` is served and labelled (that is how T-189 keeps recall); ``quarantined`` is
    never served. ``as_of`` drops cells whose document was not known by then; ``offset`` pages a cut reply.
    A row whose value cell the reader stored separately carries the values printed beside it (``values``), so a
    label-only row is never served as if the table held no figure.

    T-199: when the store has ``page_atom`` rows for the company, they answer instead: each row carries the
    resolved ``period`` / ``basis`` / ``unit`` / ``scale`` / numeric ``value`` beside the printed text, and the
    ``period`` argument filters the resolved column."""
    sym = resolve_symbol(symbol)
    day = _day(as_of, "as_of")
    if _atoms_here(sym):
        return _cells_from_atoms(sym, terms, period, day, include_unverified, limit, offset, documents)
    if not _has_table("page_cell"):
        return {"found": False, "symbol": sym, "tool": "pilot3_cells", "reason": "no page_cell table",
                "provenance": _db_prov()}
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
                                      doc_cap=_doc_cap(documents, cap),
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
        if _script_precedence():
            out = _script_quarters(sym, measure, label, bas, as_of, out, got, cap)
    if not out and _has_table("obs_fact"):
        out.extend(_obs_fin_rows(sym, measure, period, bas, as_of, cap))
    out = _dedupe(p3_preferred.elect(out))
    for row in out:
        for alt in row.get("alternatives") or ():
            _add_money(alt, alt.get("value"), alt.get("unit"), alt.get("scale"))
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
                  basis_assumed=assumed, as_of=_day(as_of, "as_of"),
                  nearest=f"{measure} {period or ''}".strip(), nearest_as_of=as_of)


def _script_precedence() -> bool:
    """T-227 option 2, arm B of the frozen-set answer test: verified script cells take precedence over printed
    comparative rows.  Off unless ``REALITY_SCRIPT_PRECEDENCE=1``; Shivam's go is needed before it is on by default."""
    return os.environ.get("REALITY_SCRIPT_PRECEDENCE") == "1"


def _script_quarters(sym: str, measure: str, label: str | None, bas: str | None, as_of: str | None,
                     out: list[dict], xbrl_held: set, cap: int) -> list[dict]:
    """Arm B: a verified ``script_cell`` quarter replaces a printed row of the same line, quarter and basis whose
    value differs, and fills a quarter that neither XBRL nor a printed row holds.  An XBRL row always stays."""
    if not _has_table("script_cell"):
        return out
    names, _ = _pick("script_cell", "line_item", sym, measure)
    if not names:
        return out
    where, args = (f"symbol=? AND status='verified' AND fiscal_period LIKE 'Q%' "
                   f"AND line_item IN ({','.join('?' * len(names))})"), [sym, *names]
    for col, val in (("fiscal_period", label), ("basis", bas)):
        if val:
            where += f" AND {col}=?"
            args.append(val)
    day = _day(as_of, "as_of")
    if day:
        where += " AND substr(known_at,1,10) <= ?"
        args.append(day)
    rows = _q(f"SELECT rowid, * FROM script_cell WHERE {where} ORDER BY period_end DESC, known_at DESC LIMIT ?",
              (*args, cap * 4))
    printed: dict[tuple, list[dict]] = {}
    for x in out:
        if x.get("_table") == "fin_quarter_printed":
            printed.setdefault((x["measure"], x["period"], x["basis"]), []).append(x)
    seen: set = set()
    for r in rows:
        key = (r["line_item"], r["fiscal_period"], r["basis"])
        if (r["line_item"], r["fiscal_period"]) in xbrl_held or key in seen or r["value"] is None:
            continue
        seen.add(key)
        olds = printed.get(key, [])
        tol = 0.5 * (r["unit_scale"] or 1.0)
        if any(o.get("value") is not None and abs(o["value"] * (o.get("scale") or 1.0) - r["value"]) <= tol
               for o in olds):
            continue                                        # a printed row says the same: keep the printed rows
        old = olds[0] if olds else None
        if olds:
            out = [x for x in out if not any(x is o for o in olds)]
        row = _add_money({"measure": r["line_item"], "period": r["fiscal_period"], "basis": r["basis"],
                          "definition": "script_verified", "value": r["value"], "unit": "inr", "scale": 1.0,
                          "witness": r["witness"], "printed": r["value_text"],
                          "provenance": _prov("script_cell", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                              row_id=r["rowid"], period_end=r["period_end"])},
                         r["value"], "inr", 1.0)
        if old is not None:
            row["replaced_printed"] = {"value": old.get("value"), "source": old["provenance"].get("source")}
        row["_table"], row["_known_at"], row["_rowid"] = "script_cell", r["known_at"], r["rowid"]
        out.append(row)
    return out


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
_VERSION_CACHE: dict[str, int] = {}


def store_version() -> int:
    """The schema version of the store these lookups serve (T-202), read once per routed store path.

    T-203 routes each call to the store that holds its symbol, so the cache key is the path ``db_path()`` returns,
    never the process.  A read-only connection never migrates: the version only decides which column a lookup may
    name, and a store that predates ``schema_meta`` (version 0) is still probed, so a live store built with the
    column keeps its current answer.  Every tool reply's provenance carries it."""
    key = str(db_path())
    have = _VERSION_CACHE.get(key)
    if have is None:
        try:
            have = p3_schema.version(connect())
        except (DataError, sqlite3.Error):
            have = 0
        _VERSION_CACHE[key] = have
    return have


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


# The first store version that carries a column a lookup falls back on (T-202): on a migrated store the version
# answers without a PRAGMA, and an older store is still probed, so the fallback stays exactly as it was.
_COLUMN_MIN_VERSION = {
    ("share_capital", "count_basis"): p3_schema.V_SHARE_COUNT_BASIS,
    ("guidance", "entity"): p3_schema.V_GUIDANCE_ENTITY,
    ("guidance", "entity_unsure"): p3_schema.V_GUIDANCE_ENTITY,
    ("event", "doc_type"): p3_schema.V_EVENT_BODY,
    ("event", "title"): p3_schema.V_EVENT_BODY,
    ("event", "body_excerpt"): p3_schema.V_EVENT_BODY,
}


def _has_column(table: str, column: str) -> bool:
    floor = _COLUMN_MIN_VERSION.get((table, column))
    if floor is not None and store_version() >= floor:
        return True
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


# --- T-242 fix 7: the company's own figure, the asked period and the asked scope ----------------------------------
# A verified row is not yet the company's own number: obs_fact carries entity_scope, and a question about a company
# answered with an industry / country / peer / customer figure is wrong whatever its status (audit 7: 13,031 observed
# rows carry another scope).  Scope is a sort key, never a filter, so the other figure is still shown as an
# alternative, labelled.
_SCOPE_LABELS = {"industry": "industry figure", "country": "country figure", "peer": "peer figure",
                 "competitor": "peer figure", "customer": "customer figure"}

_COMPONENT = re.compile(r"\b(?:division|segment|brand|proprietary|subsidiary|wos|joint venture|jv|plant|unit|"
                        r"facility|vertical|product|category|channel|geography|region|sub-segment|sale of)\b", re.I)
_SCOPE_COLUMNS = ("segment", "product", "plant", "customer")


def _scope_rank(row: dict[str, Any]) -> int:
    """0 for the company / group figure, 1 for a named subsidiary, 2 for an industry / country / peer / customer one.

    ``entity_scope`` is the store's own column (company, subsidiary, industry, country, peer, customer); a row that
    does not carry it (a kpi_series or fin row) is the company's."""
    scope = str(row.get("entity_scope") or "").strip().lower()
    if not scope or scope == "company":
        return 0
    return 1 if scope == "subsidiary" else 2


def _scope_label(row: dict[str, Any]) -> str | None:
    """How an alternative says whose figure it is ('industry figure', 'subsidiary figure (Unicommerce)'), None for the
    company's own.

    A subsidiary's row is a part of the group, never the company's own total (T-242 fix 7c: ACEVECTOR's 16.7 crore
    H1 FY27 'adjusted EBITDA' is Unicommerce's, deck p11 FAQ Q10; the group's consolidated figure is -26.9 crore, p4),
    so it says so when it is shown as an alternative.  The name the row carries (a segment / product column) says which
    part it is; a row without one still says it is a subsidiary's."""
    scope = str(row.get("entity_scope") or "").strip().lower()
    if scope == "subsidiary":
        part = str(row.get("segment") or row.get("product") or "").strip()
        return f"subsidiary figure ({part})" if part else "subsidiary figure"
    return _SCOPE_LABELS.get(scope)


def _component_scope(row: dict[str, Any]) -> bool:
    """Is this row a division / brand / plant / product figure rather than the company's whole one?

    A segment column says it outright; a deck's section title says it for a row whose segment column the reader left
    empty ('Q2FY27 Highlights from Sale of Ethanol' carries the 2% margin slide, not the company's 7%)."""
    if any(str(row.get(col) or "").strip() for col in _SCOPE_COLUMNS):
        return True
    text = " ".join(str(row.get(col) or "") for col in ("series_title", "group_path", "segment"))
    return bool(_COMPONENT.search(text))


def _asked_period_kind(period: str | None) -> str:
    """Q / H1 / H2 / FY / instant / '' for the kind of period a question asks."""
    if not period:
        return ""
    if _natural_date(period)[0] is not None:
        return "instant"
    kind, _label = norm_period(period)
    return kind or ""


def _row_period_kind(row: dict[str, Any]) -> str:
    """The kind of period a row actually reports, from its own label and the store's ``period_kind`` column."""
    text = str(row.get("period") or "")
    if str(row.get("period_kind") or "").lower() == "instant" or _natural_date(text)[0] is not None:
        return "instant"
    kind, _label = norm_period(text)
    return kind or ""


def _period_kind_rank(row: dict[str, Any], period: str | None) -> int:
    """1 when the row reports a different kind of period than the one asked (an H1 answer to a quarter ask)."""
    want, got = _asked_period_kind(period), _row_period_kind(row)
    return 0 if (not want or not got or want == got) else 1


def _unit_fits(metric: str | None, row: dict[str, Any]) -> bool:
    """Is the row's unit the family the metric's own definition carries ('AUM' is money, not the growth %)."""
    want = _metric_family(metric) if metric else ""
    return True if not want else _unit_family(row.get("unit")) == want


def _ask_row_rank(row: dict[str, Any], metric: str | None, period: str | None) -> tuple:
    """T-242 fix 7: the company's own figure of the asked period and unit, with no segment scope, first.

    In the brief's order: another scope's figure is never the first answer; then the asked period kind; then the
    measure's own unit family; then an unscoped row.  Every part is a stable sort key, so the store's own evidence
    order (verified, printed label, document type, newest) is kept wherever these do not differ."""
    return (0 if (row.get("status") or row.get("check_status")) == "verified" else 1,
            _scope_rank(row), 0 if _unit_fits(metric, row) else 1, _period_kind_rank(row, period),
            1 if _component_scope(row) else 0)


def _fin_row(r: sqlite3.Row, table: str, period: str, definition: str, source: str) -> dict[str, Any]:
    unit, scale, value = r["unit"], r["scale"] or 1.0, r["value"]
    row = _add_money(
        {"measure": r["line_item"], "period": period, "basis": r["basis"] or "not_stated", "definition": definition,
         "value": value, "unit": unit, "scale": scale,
         "provenance": _prov(table, source, r["known_at"], row_id=r["rowid"], period_end=r["period_end"])},
        value, unit, scale)
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

def _latest_book(sym: str, basis: str | None, day: str | None, on_day: str | None) -> dict[str, Any] | None:
    """The latest net-worth row public by ``day`` (today when no as_of) on a balance sheet filed before the price.

    ``on_day`` is the valuation row's own date: a balance sheet after it is look-ahead, while a book filed after
    the price date but before the caller's as_of is the current book (NSIL: the H1FY27 book filed 12 Nov on a
    9 Nov price)."""
    cutoff = day or dt.date.today().isoformat()
    for sql, source in (
            ("SELECT line_item, value*COALESCE(scale,1) AS nw, fiscal_year AS fiscal_period, period_end, doc_key, "
             "page, known_at FROM fin_annual_line WHERE symbol=? AND basis=? AND line_item IN "
             "('net_worth','total_equity') AND period_end<=? AND substr(known_at,1,10)<=? "
             "ORDER BY period_end DESC, (line_item='net_worth') DESC, known_at DESC LIMIT 1", "fin_annual_line"),
            ("SELECT line_item, value*COALESCE(scale,1) AS nw, fiscal_period, period_end, source_file AS doc_key, "
             "NULL AS page, known_at FROM fin_quarter_xbrl WHERE symbol=? AND basis=? AND line_item IN "
             "('net_worth','total_equity') AND period_end<=? AND substr(known_at,1,10)<=? "
             "ORDER BY period_end DESC, (line_item='net_worth') DESC, known_at DESC LIMIT 1", "fin_quarter_xbrl")):
        rows = _q(sql, (sym, basis, on_day or cutoff, cutoff))
        if rows:
            r = rows[0]
            return {"table": source, "line_item": r["line_item"], "value": r["nw"], "period": r["fiscal_period"],
                    "period_end": r["period_end"], "doc_key": r["doc_key"], "page": r["page"],
                    "known_at": r["known_at"]}
    return None


def _valuation_on_latest_book(sym: str, rows: list, reply: dict, day: str | None = None,
                              bvps: bool = False) -> None:
    """T-239: P/B and book value per share on the latest balance sheet known at the valuation date.

    ``valuation_daily`` can carry a P/B built on an earlier book (NSIL: 0.166 on the FY26 book where the H1FY27 book
    gives 0.148).  The row carries ``market_cap``, ``net_worth`` and the balance-sheet date in ``input_refs``; the
    store's own ``net_worth`` line of a later period is the latest book, so the figure is recomputed on it and the
    reply names the balance sheet it used."""
    for row, r in zip(reply.get("rows", []), rows):
        got = _q("SELECT market_cap, net_worth, shares_outstanding, input_refs FROM valuation_daily WHERE rowid=?",
                 (r["rowid"],))
        if not got:
            continue
        mc, nw, shares = got[0]["market_cap"], got[0]["net_worth"], got[0]["shares_outstanding"]
        if not mc or not nw:
            continue
        try:
            refs = json.loads(got[0]["input_refs"] or "{}")
        except ValueError:
            refs = {}
        book = refs.get("net_worth") if isinstance(refs, dict) else None
        printed = re.search(r"\d{4}-\d{2}-\d{2}", str(book or ""))
        book_value, book_label = nw, book
        book_source: dict[str, Any] = {"table": "valuation_daily"}
        latest = _latest_book(sym, r["basis"], day, r["date"])
        if latest and latest["value"] and (not printed or latest["period_end"] >= printed.group(0)):
            book_value = latest["value"]
            book_label = f"{latest['period']} balance sheet {latest['period_end']}"
            book_source = {"table": latest["table"], "doc_key": latest["doc_key"], "page": latest["page"],
                           "period_end": latest["period_end"], "known_at": latest["known_at"]}
        per_share = book_value / shares if shares else None
        if bvps and per_share:
            row["value"], row["ratio"] = round(per_share, 2), "book_value_per_share"
            row["definition_text"] = f"net worth / shares on {book_label or 'the latest balance sheet'}"
            row["definition"] = "derived: " + row["definition_text"]
            row["inputs"].update({"net_worth": book_value, "shares_outstanding": shares,
                                  "book_value_from": book_label, "book_source": book_source})
            continue
        pb = mc / book_value
        row["inputs"].update({"market_cap": mc, "net_worth": book_value, "book_value_from": book_label,
                              "book_source": book_source,
                              "book_value_per_share": round(per_share, 2) if per_share else None})
        if row["value"] and abs(pb / row["value"] - 1) > 0.01:
            row["stored_value"], row["value"] = row["value"], round(pb, 4)
        row["definition_text"] = f"market cap / net worth on {book_label or 'the latest balance sheet'}"
        row["definition"] = ("derived: " + row["definition_text"]
                             + (" (the stored P/B used an earlier book)" if row.get("stored_value") else ""))


def ratio(symbol: str, ratio: str, period: str | None = None, as_of: str | None = None,
          basis: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Derived ratios (margins, ROE, growth, days ...) from ratio_panel; PE/PB/EV-EBITDA/market cap on a date
    from valuation_daily (``period`` or ``as_of`` as a YYYY-MM-DD day; latest on or before it).  Every derived row
    names its ``definition_text``, ``numerator``/``denominator`` and ``inputs`` (each input's value, period and
    filing); P/B and book value per share use the latest balance sheet known at ``as_of`` and name it (T-239)."""
    sym = resolve_symbol(symbol)
    key = re.sub(r"[\s\-/]+", "_", ratio.strip().lower())
    cap = _cap(limit)
    bas = (basis or "").strip().lower() or None
    day = _day(as_of, "as_of")
    if key in VALUATION_FIELDS or key in ("p_e", "p_b", "ev_to_ebitda", "dividend_yield",
                                          "book_value_per_share", "bvps"):
        bvps = key in ("book_value_per_share", "bvps")
        key = {"p_e": "pe", "p_b": "pb", "ev_to_ebitda": "ev_ebitda", "dividend_yield": "dividend_yield_pct",
               "book_value_per_share": "pb", "bvps": "pb"}.get(key, key)
        when = period if period and re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) else day or dt.date.today().isoformat()
        sql = (f"SELECT rowid, date, basis, {key} AS value, close, shares_outstanding, known_at, input_refs "
               f"FROM valuation_daily WHERE symbol=? AND date<=? AND {key} IS NOT NULL")
        args: list[Any] = [sym, when]
        if bas:
            sql += " AND basis=?"
            args.append(bas)
        extra, eargs = _asof(as_of)
        rows = _q(sql + extra + " ORDER BY date DESC, (basis='consolidated') DESC LIMIT ?", (*args, *eargs, cap))
        val_rows = []
        for r in rows:
            item = {"ratio": key, "date": r["date"], "basis": r["basis"], "value": r["value"],
                    "inputs": {"close": r["close"], "shares_outstanding": r["shares_outstanding"]},
                    "provenance": _prov("valuation_daily", f"row {r['rowid']}", r["known_at"],
                                        input_refs=_trim(r["input_refs"], 200))}
            if key in ("market_cap", "net_worth", "net_debt", "trailing_pat", "trailing_ebitda"):
                _add_money(item, r["value"], "inr", 1.0)
            val_rows.append(item)
        reply = _reply(sym, val_rows, "pilot3_ratio", nearest=f"{ratio} {period or ''}".strip(),
                       nearest_as_of=as_of)
        if key == "pb" and rows:
            _valuation_on_latest_book(sym, rows, reply, day=day, bvps=bvps)     # T-239: the latest book, named
        if key == "ev_ebitda" and rows:
            _ev_all_investments(sym, rows, reply)
        if key == "ev_ebitda" and not rows and _is_lender(sym):
            reply["note"] = ("EV/EBITDA is not defined for a bank, NBFC or insurer: the store keeps no such row "
                             "for a lender by design, it is not missing data")
        return reply
    names, allnames = _pick("ratio_panel", "metric", sym, ratio)
    if not names:
        stated = _stated_ratios(sym, key, None, as_of, bas, cap)   # the company's own figure needs no derived panel
        if stated:
            return _reply(sym, stated, "pilot3_ratio", metrics_matched=[key], as_of=_day(as_of, "as_of"),
                          nearest=f"{ratio} {period or ''}".strip(), nearest_as_of=as_of)
        return _reply(sym, [], "pilot3_ratio", available=allnames[:40] + list(VALUATION_FIELDS), metric_asked=ratio,
                      nearest=f"{ratio} {period or ''}".strip(), nearest_as_of=as_of)
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
        row = _add_money(
            {"ratio": r["metric"], "period": r["fiscal_period"], "period_type": r["period_type"],
             "basis": r["basis"], "value": r["value"], "unit": r["unit"], "definition": "derived",
             "definition_text": r["expression"] or r["metric"],
             "formula": r["expression"],
             "provenance": _prov("ratio_panel", f"row {r['rowid']}", r["known_at"],
                                 formula_id=r["formula_id"], input_refs=_trim(r["input_refs"], 240),
                                 derived=bool(r["is_derived"]))},
            r["value"], r["unit"], r["scale"])
        try:
            refs: list = json.loads(r["input_refs"] or "[]")
        except ValueError:
            refs = []
        refs = refs if isinstance(refs, list) else [refs]
        if r["formula_id"] in ("F_PAT_TTM", "F_PAT_BE_TTM"):   # the trailing inputs, so TTM needs no hand sum
            row["inputs"] = refs
            row["numerator"] = refs[0] if refs else None
            row["denominator"] = refs[1] if len(refs) > 1 else None
        elif refs and all(isinstance(ref, str) for ref in refs):
            # T-239: the numerator and denominator rows with their own value, period and filing (ALICON: the base is
            # the stored Q2FY26 revenue 428.18, never a figure the answer recomputes or invents)
            cutoff = day or str(r["known_at"] or "")[:10] or None
            inputs = []
            for i, ref in enumerate(refs[:4]):
                item = _ref_input(sym, ref, r["basis"], cutoff)
                if item.get("value_inr") is not None and str(item.get("unit") or "").startswith("inr"):
                    item["value"], item["unit"] = item["value_inr"], "inr"   # the rupee amount, so no scale is misread
                item["role"] = "numerator" if i == 0 else "denominator" if i == 1 else "input"
                inputs.append(item)
            row["inputs"] = inputs
            row["numerator"] = inputs[0].get("name")
            row["denominator"] = inputs[1].get("name") if len(inputs) > 1 else None
        derived.append(row)
    stated = _stated_ratios(sym, key, label, as_of, bas, cap)
    # The company's own figure answers "what is X's ROE for FY26"; the derived row is our arithmetic beside it
    # (T-107: Bajaj's FY26 ROE is its stated 18.1, not the 16.96 that LTM PAT over closing net worth derives).
    return _reply(sym, stated + derived, "pilot3_ratio", metrics_matched=names, as_of=_day(as_of, "as_of"),
                  nearest=f"{ratio} {period or ''}".strip(), nearest_as_of=as_of)


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
    rows = _q(f"SELECT k.id, k.metric, k.dimension, k.value, k.unit, k.scale, k.fiscal_period, k.basis, k.entity, "
              f"k.doc_key, k.page, k.quote, k.known_at, k.conf_rank, d.doc_key AS dk, d.title, d.doc_type{check_sel} "
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
        best[r["fiscal_period"]] = _add_check(_add_money({
            "ratio": key, "metric": r["metric"], "period": r["fiscal_period"],
            "period_type": "Q" if r["fiscal_period"].startswith("Q") else "FY",
            "basis": row_basis, "value": r["value"], "unit": r["unit"], "definition": "company_stated",
            "entity": entity, "quote": _trim(r["quote"], 240),
            "provenance": _prov("kpi_series", f"{r['dk'] or r['doc_key']} p{r['page']}", r["known_at"],
                                doc_type=r["doc_type"], title=r["title"], row_id=r["id"])},
            r["value"], r["unit"], r["scale"]), r)
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


_HOLDING_TOP_CATEGORIES = frozenset({
    "promoter", "public", "shareholding_pattern", "fpi_total", "mutual_funds",
    "institutions_domestic", "institutions_foreign", "non_institutions",
    "central_government_or_president_of_india",
})
_HOLDING_PARENT = {
    "promoter_individuals": "promoter",
    "other_indian_shareholders": "promoter",
    "others_indian_shareholders": "promoter",
    "indian": "promoter",
    "fpi_category_1": "fpi_total",
    "fpi_category_2": "fpi_total",
    "institutions_foreign": "fpi_total",
    "mutual_funds": "institutions_domestic",
    "aif": "institutions_domestic",
    "banks": "institutions_domestic",
    "insurance": "institutions_domestic",
    "pension_funds": "institutions_domestic",
    "sovereign_wealth_funds_domestic": "institutions_domestic",
    "other_institutions_domestic": "institutions_domestic",
    "other_financial_institutions": "institutions_domestic",
    "retail_up_to_2_lakh": "public",
    "retail_above_2_lakh": "public",
    "bodies_corporate": "public",
    "nri": "public",
    "investor_education_and_protection_fund": "public",
    "other_non_institutions": "public",
    "non_institutions": "public",
    "pac_public": "public",
}


def _holding_part_of(hcat: str | None, cat_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Category total row(s) that a named holder belongs to (never a sum of holders)."""
    raw = str(hcat or "").strip()
    if not raw:
        return None
    norm = "other_" + raw[7:] if raw.startswith("others_") else raw
    matched = raw if raw in cat_by_name else (norm if norm in cat_by_name else None)
    parent = _HOLDING_PARENT.get(raw) or _HOLDING_PARENT.get(norm)
    if parent == "fpi_total" and parent not in cat_by_name and "institutions_foreign" in cat_by_name:
        parent = "institutions_foreign"
    if parent == "institutions_domestic" and parent not in cat_by_name and "public" in cat_by_name:
        parent = "public"
    if matched is None and parent and parent in cat_by_name:
        matched = parent
    if matched is None:
        return None
    crow = cat_by_name[matched]
    out: dict[str, Any] = {"category": matched, "pct": crow["pct"], "shares": crow["shares"]}
    if parent and parent != matched and parent in cat_by_name:
        prow = cat_by_name[parent]
        out["parent_category"] = parent
        out["parent_pct"] = prow["pct"]
        out["parent_shares"] = prow["shares"]
    return out


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
        q_order = {q: idx for idx, q in enumerate(qlist)}

        def _cat_rank(row: dict[str, Any]) -> tuple[int, int, str]:
            cat = row["category"]
            if not category:
                tier = (0 if cat == "promoter" else 1 if cat == "public"
                        else 2 if cat in _HOLDING_TOP_CATEGORIES else 3)
            else:
                tier = 0 if cat in _HOLDING_TOP_CATEGORIES else 1
            return (q_order.get(row["quarter_end"], 999), tier, cat)

        rows.sort(key=_cat_rank)
    named: list[dict] = []
    if quarter and _has_table("shp_holder"):
        cat_by_name: dict[str, dict[str, Any]] = {}
        if not category:
            cat_by_name = {r["category"]: r for r in rows if r["quarter_end"] == quarter}
        else:
            for cr in _q(f"SELECT category, pct, shares FROM shp_category WHERE symbol=? AND quarter_end=?{extra} "
                         "ORDER BY (source_kind='xbrl') DESC, known_at DESC", (sym, quarter, *eargs)):
                cat_by_name.setdefault(cr["category"], {"category": cr["category"], "pct": cr["pct"],
                                                        "shares": cr["shares"]})
        flt = "" if all_holders else " AND category NOT LIKE 'pac_%'"
        cap = MAX_LIMIT * 10 if all_holders else HOLDING_TOP
        for r in _q(f"SELECT rowid, * FROM shp_holder WHERE symbol=? AND quarter_end=?{extra}{flt} "
                    "ORDER BY shares IS NULL, shares DESC, holder_name LIMIT ?", (sym, quarter, *eargs, cap)):
            hrow = {"holder": r["holder_name"], "category": r["category"], "shares": r["shares"], "pct": r["pct"],
                    "holders": r["holders"], "pac_name": r["pac_name"], "pac_pct": r["pac_pct"],
                    "pledged_shares": r["pledged_shares"],
                    "provenance": _prov("shp_holder", f"{r['source_file'] or ''} [{r['source_db']}.{r['source_table']}]",
                                        r["known_at"])}
            part_of = _holding_part_of(r["category"], cat_by_name)
            if part_of is not None:
                hrow["part_of"] = part_of
            named.append(hrow)
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
# The grammar words a question is written with are not what its sentence answers: counting 'the', 'and', 'they',
# 'this' or 'will' as ask words let a long unrelated sentence win (T-242 fix 7).
_ASK_STOP = {"how", "what", "when", "why", "where", "which", "who", "whom", "whose", "the", "and", "for", "this",
             "that", "with", "from", "will", "would", "could", "should", "can", "may", "might", "must", "they",
             "them", "their", "there", "these", "those", "was", "were", "are", "has", "have", "had", "does", "did",
             "done", "much", "many", "more", "most", "some", "any", "all", "also", "just", "only", "than", "then",
             "into", "onto", "over", "under", "about", "after", "before", "between", "during", "each",
             "same", "both", "here", "very", "been", "being", "because", "while", "such", "its", "our", "your",
             "you", "we", "us", "me", "my", "he", "she", "his", "her", "not", "but", "off", "out", "up", "down",
             "per", "is", "be", "as", "at", "by", "in", "on", "of", "to", "or", "if", "no", "so", "do", "new"}


def _ask_tokens(*texts: str | None, stop: bool = True) -> list[str]:
    """The content words a statement question is asked with: topic, terms and rank_terms (T-242 fix 7)."""
    out: list[str] = []
    for text in texts:
        for word in re.findall(r"[\w₹%&\-\.]+", text or ""):
            low = word.lower()
            if len(low) > 2 and low not in out and (low not in _ASK_STOP or not stop):
                out.append(low)
    return out


def _proximity(text: str | None, words: list[str]) -> tuple[int, int]:
    """(ask words close together, how often they occur) for the best sentence -- the fix-6 tie-break (T-242)."""
    best = (0, 0)
    for sentence in _SENTENCE_SPLIT.split(str(text or "")):
        tokens = re.findall(r"[a-z0-9]+", sentence.lower())
        if not tokens:
            continue
        close = 0
        for start in range(max(0, len(tokens) - 1)):
            window = tokens[start:start + 4]
            if len({word for word in words if any(_token_matches(tok, word) for tok in window)}) >= 2:
                close = 1
                break
        occ = sum(1 for tok in tokens if any(_token_matches(tok, word) for word in words))
        if (close, occ) > best:
            best = (close, occ)
    return best


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# T-242 fix 7: the words a call prints for a measure an ask names in investor language, plus the committed
# thesaurus's expansion of the same words.  Structural (one measure word), never per company.
_ASK_SYNONYMS: dict[str, tuple[str, ...]] = {
    "capex": ("capital expenditure", "capital outlay", "project cost", "invest", "spend", "outlay"),
    "demand": ("volume", "offtake", "demand", "dispatch"),
    "margin": ("ebitda", "profitab", "margin"),
    "revenue": ("top line", "topline", "revenue", "sales", "income"),
    "order": ("order book", "order intake", "order inflow", "order"),
    "cost": ("cost", "expense", "price", "spend"),
    "capacity": ("capacity", "output", "production", "plant", "expansion"),
    "customer": ("customer", "client", "clientele", "attrition", "churn"),
    "operations": ("operat", "plant", "facility", "production", "commission", "ready"),
    "guidance": ("target", "expect", "outlook", "guide", "range"),
    # T-242 fix 8: the paraphrase an investor uses for a sentence the page prints in its own words.  Structural
    # (one investor word -> the words a call prints), never per company: "why are large enterprise deals taking
    # longer to close" -> "large contracts are taking longer to conclude as clients evaluate".
    "deal": ("contract", "contracts", "order", "orders", "agreement", "win"),
    "deals": ("contract", "contracts", "order", "orders", "agreement", "win"),
    "enterprise": ("large", "corporate", "business"),
    "enterprises": ("large", "corporate", "business"),
    "convert": ("conclude", "concluded", "closing", "close", "closure", "conversion"),
    "converting": ("conclude", "concluded", "closing", "close", "conversion"),
    "close": ("conclude", "concluded", "completion", "closure"),
    "closing": ("conclude", "concluded", "completion", "closure"),
    "consolidation": ("integrat", "consolidat", "combine"),
    "strength": ("strong", "discipline", "experience", "team"),
    "strengths": ("strong", "discipline", "experience", "team"),
    "change": ("transition", "newly created", "appoint", "leadership"),
    "changed": ("transition", "transitioned", "newly created", "appoint"),
    "poor": ("disappoint", "weak", "soft", "lower"),
    "fix": ("recover", "recovery", "improve", "confiden"),
    "fixed": ("recover", "recovery", "improve", "confiden"),
    "protect": ("protecting", "defend", "counter"),
    "fuel": ("cost", "cost pressure", "pricing"),
    "expensive": ("elevated", "high", "cost pressure"),
}
# a quantitative ask ("how much", "what is the target") is answered by a sentence that prints a figure and a period
_ASK_QUANT = re.compile(r"\bhow (?:much|many|big|large|long)|what (?:is|was|are|were)\b|target|guidance|size|"
                        r"number|outlook|expect", re.I)
_ASK_FIGURE = re.compile(r"(?:₹|rs\.?|inr|usd|\$)\s*\d[\d,]*(?:\.\d+)?|"
                         r"\d[\d,]*(?:\.\d+)?\s*(?:crores?|cr\b|lakhs?|millions?|mn\b|billions?|bn\b|%|per ?cent|"
                         r"bps|tons?|mtpa|megawatts?|mw\b)", re.I)
_ASK_PERIOD = re.compile(r"\b(?:fy\s?\d{2}|q[1-4]\s?fy|h[12]\s?fy|quarters?|half|years?|annual|annum|months?|"
                         r"full[- ]year|fy\d{2}|yrs?)\b", re.I)
_TIE_WIDEN = 15        # extra turns a named call may add while the rows at the 25-row window's edge are ties
# T-242 fix 7: 'this year' asks for the year's total; a sentence printing Q1/Q2 answers one quarter of it
_ASK_YEAR_SEARCH = re.compile(r"\byear\b|\bfy\s?\d{2}\b|annual|full[- ]year", re.I)
_QUARTER_WORD = re.compile(r"\bq[1-4]\b|\bquarter\b", re.I)


def _measure_words(*texts: str | None) -> list[str]:
    """The words a call prints for a measure an ask names in investor language (T-242 fix 7).

    "How much will they invest this year" must reach "during FY27, we estimate to spend around INR1,700 crores": the
    ask's own words never appear in that sentence, its measure's words do.  The committed thesaurus
    (``synonyms.json``) expands the same words, so one small table serves the asks and the pages."""
    out: list[str] = []
    for text in texts:
        for word in re.findall(r"[a-z]+", str(text or "").lower()):
            for term in _ASK_SYNONYMS.get(word, ()):
                if term not in out:
                    out.append(term)
            for term in _synonyms_for(word):
                low = term.lower()
                if low not in out:
                    out.append(low)
    return out


def _token_matches(token: str, word: str) -> bool:
    """A light stem match: the word, a word starting with it, or their shared first five letters."""
    return (token == word or token.startswith(word) or word.startswith(token)
            or (len(word) >= 5 and len(token) >= 5 and token[:5] == word[:5]))


def _ask_weights(items: list[list[dict[str, Any]]], words: list[str]) -> dict[str, float]:
    """Each ask word's weight in this reply: an IDF bucket, the rarest word weighing most (T-242 fixes 7, 8).

    A word the call prints once ('Bokaro', 'Jettings', 'salt') names the asked sentence and weighs 2.5; a word
    printed in at most a fifth of the served rows weighs 1.5; a word printed almost everywhere ('capacity',
    'increase', 'year') weighs 1.0, so one rare ask word outranks several common ones.  The corpus is the reply's
    own structured rows (the page-text hits are long snippets and would flood the frequency count), so no global
    table is kept and the weight is structural: read from the held pages, never from a company."""
    rows = [row for group in (items or []) for row in group]
    structured = [row for row in rows if str(row.get("match") or "") != "text"]
    rows = structured or rows
    n = len(rows) or 1
    token_cache = [set(re.findall(r"[a-z0-9]+", str(r.get("quote") or "").lower())) for r in rows]
    out: dict[str, float] = {}
    for word in words:
        df = sum(1 for toks in token_cache if any(_token_matches(tok, word) for tok in toks))
        out[word] = 2.5 if df == 1 else (1.5 if df and df * 5 <= n else 1.0)
    return out


def _sentence_hits(text: str | None, words: list[str], measures: list[str] | None = None,
                   quant: bool = False, weights: dict[str, float] | None = None) -> tuple[bool, float, int]:
    """Best sentence of ``text`` for an ask (T-242 fixes 6 and 7): (every ask word in ONE sentence, score, tokens).

    The sentence that answers the ask is ranked, not the blob around it and not the whole answer turn.  The score
    adds the ask words it carries (a word this reply prints once weighs more), a figure AND a period when the ask is
    quantitative, two ask words close together, the ask's measure words (the paraphrase: "how much will they invest"
    -> "we estimate to spend"), and takes a quarter as the answer to a year ask only after the full year itself."""
    weights = weights or {}
    best: tuple[bool, float, int] = (False, 0.0, 0)
    year_ask = bool(_ASK_YEAR_SEARCH.search(" ".join(words))) and not bool(_QUARTER_WORD.search(" ".join(words)))
    for sentence in _SENTENCE_SPLIT.split(str(text or "")):
        tokens = re.findall(r"[a-z0-9]+", sentence.lower())
        if not tokens:
            continue
        low = " " + " ".join(tokens) + " "
        found, score = 0, 0.0
        for word in words:
            if any(_token_matches(tok, word) for tok in tokens):
                found += 1
                # T-242 fix 7b: the rare-word weight rewards the asked word ITSELF being printed once in the reply;
                # a sentence that only carries an inflection of it ("running" -> "run at full gallop") is still
                # evidence, but not the same evidence, so it never earns the rarity bonus.
                score += weights.get(word, 1.0) if word in tokens else min(weights.get(word, 1.0), 1.0)
        measures_hit, phrases_hit = 0, 0
        for term in measures or ():
            if " " in term:
                if term in low:
                    measures_hit += 1
                    phrases_hit += 1
            elif any(tok.startswith(term) or _token_matches(tok, term) for tok in tokens):
                measures_hit += 1
        figure = 1 if (quant and _ASK_FIGURE.search(sentence) and _ASK_PERIOD.search(sentence)) else 0
        close = 0
        for start in range(max(0, len(tokens) - 1)):
            window = tokens[start:start + 4]
            distinct = {word for word in words if any(_token_matches(tok, word) for tok in window)}
            if len(distinct) >= 2:
                close = 1
                break
        # the measure words matter most when the ask's own words do not reach the sentence (the paraphrase); a
        # multi-word measure ("order book") still counts beside a word match, because it is the subject's own phrase
        score += 2.0 * figure + 0.5 * close + (0.5 * min(measures_hit, 2) if not found
                                               else 0.5 * min(phrases_hit, 1))
        if year_ask and _QUARTER_WORD.search(sentence):
            score -= 0.6        # the year's total, not one quarter of it
        cand = (bool(words) and found == len(words), round(score, 3), -len(tokens))
        if cand > best:
            best = cand
    return best[0], best[1], -best[2]


def _group_ask_rank(group: list[dict[str, Any]], words: list[str], measures: list[str] | None = None,
                     quant: bool = False, weights: dict[str, float] | None = None,
                     tie_words: list[str] | None = None, text: str | None = None) -> tuple[int, float, int, int]:
    """Every ask word in one sentence first, then the sentence's weighted score, then fix-6 proximity (T-242 fix 7).

    The proximity tie-break is the ``fix 6`` order (ask words close together, then how often) over the question's own
    words: two rows that score the same fall back to the ranking that was already proven, and only a real gain from
    the new sentence score outranks it.  The stable tie-break is the reply's existing order.  ``text`` (T-242 fix 9)
    is the group's pre-split text, so serving extra sentences never changes the rank the reply already had."""
    text = text if text is not None else " ".join(str(r.get("quote") or "") for r in group)
    all_hit, score, _tokens = _sentence_hits(text, words, measures, quant, weights)
    close, occ = _proximity(text, tie_words) if tie_words else (0, 0)
    return (0 if all_hit else 1, -score, -close, -occ)


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
               date_to: str | None = None, as_of: str | None = None, limit: int | None = None,
               role: str | None = None, period: str | None = None,
               rank_terms: str | None = None, latest: bool = False,
                entities: str | None = None, whole_turn: bool = True, offset: int = 0,
                documents: str | None = None, status: str | None = None) -> dict[str, Any]:
    """Management statements from concall transcripts, exact quotes: topic tag (margin, guidance, capex, order ...),
    free ``terms`` (all words must appear), call-date window, role (ceo / cfo / md / mgmt).

    For a question about one call ('In the 2026-05-27 call, what did management say about X?'), pass that call's
    date as ``date_from`` and ``date_to`` (both YYYY-MM-DD): only that call's statements are then served -- matched
    by the transcript's own printed call date or by the document's filing date within 3 days, so a call printed on
    2026-08-10 and filed on 2026-08-13 is the same call -- up to three sentences of one answer turn when they answer
    different ask words, best match first, and the window is 25 rows instead of 10.

    ``period`` (Q4FY26 / FY26) and ``rank_terms`` (the question's own words) rank the rows: a statement of the
    period asked, carrying more of the question's words, comes first; the newest call breaks a tie.  Inside a named
    call the sentence carrying EVERY ask word (topic, terms or rank_terms, light-stemmed and read per sentence, not
    per answer turn) ranks first, then the rarest ask word (2.5 when the reply prints it once, 1.5 when at most a
    fifth of its rows do, else 1.0) and the sentence carrying them closest together and most often; a
    prepared-remarks turn, a paragraph, serves the sentence that answers the ask rather than its first sentence and
    is admitted past the turn window.  Each named-call
    row carries ``call_date`` plus ``filed`` and ``call_date_printed`` where they differ.  ``latest``
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
    # T-242 fix 4: a named call is served from its own document only, matched by the transcript's PRINTED call date
    # or by the document's filing date within 3 days (a call on 2026-08-10 filed 2026-08-13 is that call).  Rows of
    # every other call are dropped, not merely ranked lower: audit 4 found 85 of 240 served rows from another call.
    named_day = from_day if from_day and from_day == to_day else None
    named_lo, named_hi = _day_span(named_day) if named_day else (None, None)
    # T-242 fix 5: the documents the named call is served from -- its printed call date OR its filing date within
    # 3 days.  The obs_fact statements and the doc_page hits are then fetched for these documents, not by a
    # filing-date window that loses every call filed more than 3 days after it was held.
    named_docs = _named_call_docs(sym, named_day) if named_day else []
    named_sql, named_args = "", []
    if named_day:
        named_sql = (" AND (t.call_date BETWEEN ? AND ? OR (d.filing_date IS NOT NULL "
                     "AND d.filing_date BETWEEN ? AND ?))")
        named_args = [named_lo, named_hi, named_lo, named_hi]
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
    # T-242 fix 3: one named call is a bounded set, so its window is 25 remarks (the quote on a long call is
    # often past the tenth); any other question keeps the 10-statement window.
    cap, start = _window(limit, offset, 25 if named_day else 10)
    # T-242 fix 7: a named call is a bounded set, so ranking may widen past the 25-row window when the rows at the
    # edge are ties; the next turns are fetched and every row tied with the last one shown is served.
    want = cap + start + (_TIE_WIDEN if named_day else 0)
    # whole_turn: `limit` counts answer turns, not sentences, so fetch enough rows to find the turns the page needs
    # (T-164 r7: limit=20 used to return 188 rows because the LIMIT bounded matched sentences before expansion)
    # T-242 fix 4: within a named call ONE statement per answer turn is served, so the 25-turn window arrives as 25
    # rows instead of the 123 sentences the whole-turn expansion made, which the 19 kB reply then trimmed to 15.
    one_per_turn = bool(named_day)
    row_cap = want * 50 if (whole_turn or one_per_turn) else want
    rows = _q(f"SELECT t.id, t.call_date, t.call_period, t.page, t.speaker, t.role, t.section, t.topics, "
              f"t.period_discussed, t.quote, t.is_fragment, t.entities, t.answer_turn, t.known_at, t.doc_key, "
              f"d.title, d.doc_type, "
              f"(CASE WHEN {topic_sql} THEN 0 ELSE 1 END) AS topic_rank, "
              f"(CASE WHEN {period_sql} THEN 0 ELSE 1 END) AS period_rank, ({score_sql}) AS term_score "
              f"FROM transcript_statement t "
              f"LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
              f"AND a.alias_key=t.doc_key), t.doc_key) WHERE {core_where}{extra}{named_sql} "
              f"ORDER BY topic_rank, period_rank, term_score DESC, t.is_fragment, t.call_date DESC, t.seq LIMIT ?",
              # the SELECT-list placeholders bind before the WHERE ones
              (*topic_args, *period_args, *score_args, *core_args, *eargs, *named_args, row_cap))
    # one item per answer turn: the whole turn is expanded below, so `limit` counts turns (or rows when
    # whole_turn=False) and the reply pages over turns/hits, never over sentences.
    turn_rows: dict[tuple, list[sqlite3.Row]] = {}
    order: list[tuple] = []
    for r in rows:
        key = _turn_key(r)
        if key not in turn_rows:
            # T-242 fix 8: a prepared-remarks turn is a paragraph and sits late in the topic-ordered window, so it
            # is admitted past the turn cap (ADSL's asked sentence is 12 sentences into the p4 prepared remarks);
            # the Q&A window and the page-text window keep their old size, so no new rival turn is added.
            if len(order) >= want and not (one_per_turn and str(r["section"] or "") == "prepared"):
                continue
            turn_rows[key] = []
            order.append(key)
        turn_rows[key].append(r)
    if whole_turn and not one_per_turn and turn_rows:
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
    obs_items: list[dict[str, Any]] = []
    if _has_table("obs_fact"):
        obs_items = _obs_statement_rows(sym, topic=topic, terms=terms, period=period, rank_terms=rank_terms,
                                        latest=latest, status=status, date_from=from_day, date_to=to_day,
                                        as_of=as_of, call_docs=named_docs)
    if obs_items:
        def _norm_sent(s: str | None) -> str:
            return re.sub(r"\s+", " ", (s or "")).strip().lower()

        obs_by_quote: dict[str, dict[str, Any]] = {}
        for item in obs_items:
            qn = _norm_sent(item.get("quote"))
            if qn:
                obs_by_quote.setdefault(qn, item)
        deduped_tagged: list[list[dict[str, Any]]] = []
        for group in tagged:
            kept_group = []
            for row in group:
                qn = _norm_sent(row.get("quote"))
                hit = obs_by_quote.get(qn) if qn else None
                if hit is None and len(qn) >= 25:
                    hit = next((obs for norm, obs in obs_by_quote.items() if qn in norm), None)
                if hit is not None:
                    # T-242: the obs row is the one served; fill its speaker from the transcript row when it has
                    # none, and fill the transcript row from obs_fact (a kept row) when the transcript has none.
                    if not hit.get("speaker"):
                        hit["speaker"] = row.get("speaker")
                    continue
                if not row.get("speaker") and qn:
                    near = next((obs for norm, obs in obs_by_quote.items()
                                 if norm and len(norm) >= 25 and norm in qn), None)
                    if near:
                        row["speaker"] = near.get("speaker")
                kept_group.append(row)
            if kept_group:
                deduped_tagged.append(kept_group)
        tagged = deduped_tagged
    # the same phrase-first matcher over every document type, not only calls: a deck table, an annual report or a
    # filing body answers what no transcript tag carries (T-197 step 2).  A named call widens its filing window by
    # the same 3 days, because the call's own document is often filed a few days after the date printed in it.
    ask = " ".join(x for x in (topic, terms, rank_terms) if x)
    page_from, page_to = (named_lo, named_hi) if named_day else (date_from, date_to)
    if named_docs:
        page_from, page_to = None, None
    hits = (_call_page_hits(sym, ask, None, None, page_from, page_to, as_of, latest, want,
                            doc_keys=named_docs or None) if ask else [])
    page_items = [{"call_date": r["filing_date"], "call_period": None, "speaker": None, "role": None,
                   "section": None, "topics": None, "entities": None, "period_discussed": None,
                   "answer_turn": None, "match": "text", "page": r["page"], "doc_key": r["doc_key"],
                   "doc_type": r["doc_type"],
                   "quote": _trim(r["snip"], QUOTE_CHARS),
                   "provenance": _prov("doc_page", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                       title=_trim(r["title"], 120), doc_type=r["doc_type"])}
                  for r in hits]
    # Merge obs_fact statements with transcript_statement BEFORE the row cut: verified obs_fact ranks first.
    obs_v = [item for item in obs_items if item.get("status") == "verified"]
    obs_u = [item for item in obs_items if item.get("status") != "verified"]
    if words:
        obs_v_hit = [[item] for item in obs_v if item.get("_term_score", 0) > 0]
        obs_v_miss = [[item] for item in obs_v if item.get("_term_score", 0) == 0]
        obs_u_hit = [[item] for item in obs_u if item.get("_term_score", 0) > 0]
        obs_u_miss = [[item] for item in obs_u if item.get("_term_score", 0) == 0]
        w_low = [w.lower() for w in words[:8]]

        def _grp_hit(group: list[dict[str, Any]]) -> bool:
            blob = " ".join(str(r.get("quote") or "") for r in group).lower()
            return any(w in blob for w in w_low)

        tagged_hit = [g for g in tagged if _grp_hit(g)]
        tagged_miss = [g for g in tagged if not _grp_hit(g)]
        merged_stmts = obs_v_hit + tagged_hit + obs_v_miss + obs_u_hit + tagged_miss + obs_u_miss
    else:
        merged_stmts = [[item] for item in obs_v] + tagged + [[item] for item in obs_u]
    for item in obs_items:
        item.pop("_term_score", None)
    # a tag no row carries leads with the page text that matched (unless verified obs_fact matched); otherwise
    # merged statements lead and the page hits follow, so relevance order never buries the tag (T-194 ranking).
    items = merged_stmts + [[item] for item in page_items]
    if topic and tagged_match is False and not obs_v:
        items = [[item] for item in page_items] + merged_stmts
    # T-242 fix 6: inside a named call the sentence that carries EVERY ask word comes first, then the one carrying
    # the most; fix 7 adds the ask's measure words (paraphrase) and a figure + period when the ask is quantitative.
    # The stable sort keeps the reply's existing order for ties (fix 3/4/5 stay as they were).
    ask_tokens = _ask_tokens(topic, terms, rank_terms) if named_day else []
    measures = _measure_words(topic, terms, rank_terms) if named_day else []
    quant = bool(named_day and _ASK_QUANT.search(" ".join(x for x in (rank_terms, terms, topic) if x)))
    weights = _ask_weights(items, ask_tokens) if ask_tokens else {}
    rank_weights = weights      # the reply's existing group order, unchanged by the sentence-selection boost below
    if weights:
        # T-242 fix 9: the question's own words (rank_terms / terms) weigh more than its coarse topic tag, so
        # "what happened to other expenses versus a year ago" (topic ``cost``) prefers the "other expenses"
        # sentence over a generic costs sentence of the same call.
        asked_words = set(_ask_tokens(rank_terms, terms))
        weights = {word: (value * 1.5 if word in asked_words else value) for word, value in weights.items()}
    tie_words = _ask_tokens(topic, terms, rank_terms, stop=False) if ask_tokens else []
    rank_text: dict[int, str] = {}
    if one_per_turn and ask_tokens:
        # T-242 fix 8/9: one row per answer turn is still served, but a prepared-remarks turn serves the sentence
        # that answers the ask.  A prepared-remarks turn is a paragraph: ADSL's p4 turn opens on revenue growth
        # and prints "large contracts are taking longer to conclude" 12 rows later, so the turn's first sentence
        # was never the asked one.
        # T-242 fix 9: an answer turn is not one sentence.  ARCIL's "Other expenses were INR25 crores compared to
        # INR18.3 crores" sits in the same paragraph as the employee-expenses sentence, and from obs_fact the whole
        # paragraph arrives as one long quote whose 600-character cut dropped the asked sentence entirely.  So every
        # sentence of the turn is scored and up to three are served, each carrying an ask word the earlier ones do
        # not; only an identical sentence is deduped, and the 25-row window below bounds the reply.
        def _sentences(row: dict[str, Any]) -> list[str]:
            # a PDF line wrap is not a sentence break ("we integrated \nOcclutech"): whitespace is normalised first
            text = re.sub(r"\s+", " ", str(row.get("quote") or "")).strip()
            if row.get("match") not in ("obs", "tag"):
                return [text] if text else []
            parts = [part.strip() for part in _SENTENCE_SPLIT.split(text) if len(part.strip()) > 12]
            return parts or ([text] if text else [])

        def _covers(sentence: str) -> set[str]:
            tokens = re.findall(r"[a-z0-9]+", sentence.lower())
            return {word for word in ask_tokens if any(_token_matches(tok, word) for tok in tokens)}

        def _best(rows: list[dict[str, Any]]) -> dict[str, Any]:
            return max(rows, key=lambda row: (
                *_sentence_hits(str(row.get("quote") or ""), ask_tokens, measures, quant, weights)[:2],
                -len(str(row.get("quote") or ""))))

        def _served_text(group: list[dict[str, Any]]) -> str:
            """The text the group's OLD order was ranked on, so fix 9 never reshuffles groups it did not touch."""
            if not group:
                return ""
            if id(group) in tagged_ids and str(group[0].get("section") or "") != "prepared":
                old = group[0]                      # a Q&A turn kept its first row
            elif id(group) in tagged_ids:
                old = _best(group)                  # a prepared turn kept its best sentence
            else:
                old = group[0]                      # an obs statement / page hit was one row
            return str(old.get("quote") or "")

        tagged_ids = {id(group) for group in tagged}
        for group in items:
            rank_text[id(group)] = _served_text(group)
        seen_sentences: set[str] = set()
        for group in items:
            candidates: list[dict[str, Any]] = []
            for row in group:
                for sentence in _sentences(row):
                    norm_sentence = re.sub(r"\s+", " ", sentence).strip().lower()
                    if not norm_sentence or norm_sentence in seen_sentences:
                        continue
                    seen_sentences.add(norm_sentence)
                    candidate = dict(row)
                    candidate["quote"] = sentence
                    candidates.append(candidate)
            if not candidates:
                group[:] = []
                continue
            # T-242 fix 9: the turn's best-scoring sentence answers it, whether the turn is prepared remarks or a
            # Q&A answer (a multi-part answer lists its figures across several sentences).
            if id(group) in tagged_ids and str(group[0].get("section") or "") != "prepared":
                primary = candidates[0]             # a Q&A turn keeps its first row, as before
            else:
                primary = _best(candidates)
            chosen = [primary]
            covered = _covers(str(primary.get("quote") or ""))
            rest = sorted((row for row in candidates if row is not primary),
                          key=lambda row: (*_sentence_hits(str(row.get("quote") or ""), ask_tokens, measures,
                                                           quant, weights)[:2],
                                           -len(str(row.get("quote") or ""))), reverse=True)
            for row in rest:
                if len(chosen) >= 3:
                    break
                extra_words = _covers(str(row.get("quote") or ""))
                if extra_words - covered:
                    chosen.append(row)
                    covered |= extra_words
            group[:] = chosen

    def _key(group: list[dict[str, Any]]) -> tuple:
        # T-242 fix 7: a question phrased with rank_terms is ranked by the sentence score; a bare topic search keeps
        # the fix-6 order (every ask word in one sentence, then close, then often) that already answers it.
        # T-242 fix 9: the group is ranked on the text it was ranked on BEFORE its sentences were split out, so a
        # turn that now serves three sentences never gains or loses rank for having done so.
        text = rank_text.get(id(group)) or " ".join(str(r.get("quote") or "") for r in group)
        if rank_terms:
            return _group_ask_rank(group, ask_tokens, measures, quant, rank_weights, tie_words, text=text)
        close, occ = _proximity(text, ask_tokens)
        return (0 if _sentence_hits(text, ask_tokens)[0] else 1, -close, -occ)

    if named_day and ask_tokens:
        items.sort(key=_key)
    show = cap
    if named_day and ask_tokens and len(items) > start + cap:
        # a tie at the window's edge is not a reason to cut the matched target: widen until the rank changes -- but
        # only while the byte cap can carry the extra rows, or the widened reply is cut back below the fix-4 window
        edge = _key(items[start + cap - 1])
        pending = sum(len(str(r.get("quote") or "")) + 160 for group in items[start:start + cap] for r in group)
        while (start + show < len(items) and show < cap + _TIE_WIDEN
               and _key(items[start + show]) == edge):
            row_bytes = sum(len(str(r.get("quote") or "")) + 160 for r in items[start + show])
            if pending + row_bytes > int(REPLY_BYTES * 0.9):
                break
            pending += row_bytes
            show += 1
    page_groups = items[start:start + show]
    out = [item for group in page_groups for item in group]
    if one_per_turn and len(out) > cap:
        # T-242 fix 9: a named call's window is 25 ROWS, not 25 turns; a turn may serve up to three sentences, so
        # the reply keeps the same row window and drops the rows past it (a group is kept whole when it fits).
        out = []
        kept_groups = 0
        for group in page_groups:
            if out and len(out) + len(group) > cap:
                break
            out.extend(group[: cap - len(out)])
            kept_groups += 1
        page_groups = page_groups[:kept_groups]
    fallback = "doc_page_bm25" if (topic and tagged_match is False and not obs_v and page_items) else None
    matched_total = len(merged_stmts) + len(page_items)    # items (answer turns, obs statements and page hits)
    shown_items = len(page_groups)
    cut = max(0, matched_total - shown_items)
    docs = [{"doc_key": row["doc_key"], "doc_type": row.get("doc_type"), "date": row["call_date"],
             "title": row["provenance"].get("title"), "page": row.get("page")}
            for group in items for row in group]
    text = _scope_line(matched_total, shown_items, cut, start, docs, len({d["doc_key"] for d in docs}),
                       parts=f"{len(tagged)} tagged statement turn(s) + {len(page_items)} page-text "
                             f"match(es), {len(out)} sentence(s)")
    outside: list[dict[str, Any]] = []
    if named_day:
        # T-242 fix 4: outside a named call is outside its 3-day window, by the call date or the filing date.
        outside_sql = ("NOT (t.call_date BETWEEN ? AND ? OR (d.filing_date IS NOT NULL "
                       "AND d.filing_date BETWEEN ? AND ?))")
        outside_args: list[Any] = [named_lo, named_hi, named_lo, named_hi]
    elif from_day or to_day:
        excluded = []
        if from_day:
            excluded.append(("t.call_date < ?", from_day))
        if to_day:
            excluded.append(("t.call_date > ?", to_day))
        outside_sql = " OR ".join(x[0] for x in excluded)
        outside_args = [x[1] for x in excluded]
    else:
        outside_sql, outside_args = "", []
    if outside_sql:
        rows_out = _q(f"SELECT t.call_date, COUNT(*) c, d.doc_type FROM transcript_statement t "
                      f"LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a "
                      f"WHERE a.symbol=t.symbol AND a.alias_key=t.doc_key), t.doc_key) "
                      f"WHERE {core_where}{extra} AND ({outside_sql}) "
                      f"GROUP BY 1, 3 ORDER BY 1 DESC LIMIT 20",
                      (*core_args, *eargs, *outside_args))
        outside = [{"date": r["call_date"], "doc_type": r["doc_type"], "count": r["c"]} for r in rows_out]
    hidden = _hidden_documents(sym, _day(as_of, "as_of"))
    read_next = (_read_next(out) + _related_pages([w for w in re.findall(r"[\w₹%&\-\.]+", ask) if len(w) > 2],
                                                  sorted({row["doc_key"] for row in out}),
                                                  {(row["doc_key"], int(row["page"])) for row in out
                                                   if row.get("page") not in (None, "")})
                 )[:12]
    if named_day:
        # T-242 fix 4: a named call serves one document, so a per-row document key, a repeated title and every
        # empty field are exactly the weight the 19 kB reply cannot afford (25 rows did not fit, 15 were served).
        # coverage.documents still names every document; provenance keeps table, page, known_at and row id, and now
        # only a row whose document is not the call's main transcript names its doc_key (T-242 fix 6: that key is
        # ~100 bytes on every row of a 25-row reply).
        counts: dict[str, int] = {}
        for row in out:
            if row.get("doc_key"):
                counts[str(row["doc_key"])] = counts.get(str(row["doc_key"]), 0) + 1
        main_doc = max(counts, key=lambda key: counts[key]) if counts else None    # the call's own transcript, usually
        call_dates = _named_call_dates(sym, named_docs)
        for row in out:
            # T-242 fix 6: the call's printed date and the filing date sit on every row, so a model quotes the
            # right one (a call printed 2026-11-03 and filed 2026-11-10 is never quoted as one date).
            when = call_dates.get(str(row.get("doc_key") or ""))
            if when:
                # one extra date field per row keeps the 25-row window under the byte cap: a transcript row already
                # shows its printed call_date, an obs/page row already shows its filing date.
                today = str(row.get("call_date") or "")
                if when.get("filed") and when["filed"] != today:
                    row["filed"] = when["filed"]
                if when.get("printed") and when["printed"] != today:
                    row["call_date_printed"] = when["printed"]
            prov = row.get("provenance")
            if isinstance(prov, dict):
                prov.pop("title", None)
                if row.get("page") not in (None, ""):
                    prov["source"] = f"p{row['page']}"
            if main_doc and str(row.get("doc_key") or "") == main_doc:
                row.pop("doc_key", None)      # only a row of another document names its key; coverage lists them all
            for k in [k for k, v in row.items() if v in (None, "")]:
                row.pop(k)
    reply = _reply(sym, out, "pilot3_statements", fallback=fallback, as_of=_day(as_of, "as_of"), text=text,
                   nearest=" ".join(x for x in (topic, terms, rank_terms) if x), nearest_as_of=as_of,
                   expansions_matched=_expansions_hit(" ".join(x for x in (topic, terms, rank_terms) if x), out)
                   or None,
                   topic_matched=tagged_match, coverage=_coverage(
                       "statements", list(_TEXT_STORES),
                       ["structured tables: kpi_series, guidance, page_cell, fin_* "
                        "(pilot3_kpi / pilot3_guidance / pilot3_cells / pilot3_fin)",
                        "questions the company did not answer (no statement is held for an unanswered question)"],
                       matched_total, shown_items, cut, start, documents=docs,
                       doc_cap=_doc_cap(documents, cap), outside=outside, hidden=hidden),
                   read_next=read_next,
                   hint=None if out else "no statement in the held calls matches these arguments")

    def quotes(width: int) -> None:
        for row in out:
            row["quote"] = _trim(row.get("quote"), width)

    def quotes_around(width: int) -> None:
        # T-242 fix 4: the ask's words stay inside a shortened quote, so ranking and the reader's check survive
        for row in out:
            row["quote"] = _trim_around(row.get("quote"), ask_words, width)

    def row_cut(keep: int) -> None:
        removed = len(out) - keep
        if removed > 0:
            del out[keep:]
            reply["coverage"]["rows_cut"] = removed     # a turn stays whole only while the reply fits its cap

    ask_words = [w for w in re.findall(r"[\w₹%&\-\.]+", " ".join(x for x in (topic, terms, rank_terms) if x))
                 if len(w) > 2]
    cuts: list[tuple[str, Any]] = []
    if named_day:
        # a named call trims each quote around the ask before it drops any statement: the matched words are what the
        # call is asked about, and 25 short rows fit where 25 long ones did not (T-242 fix 4); a second, tighter trim
        # keeps the whole 25-row window under the cap when the matched set is wide (T-242 fix 6).
        cuts = [
            ("quotes cut to 240 characters around the match", lambda: quotes_around(240)),
            ("quotes cut to 170 characters around the match", lambda: quotes_around(170)),
            ("sentences cut to the first 20", lambda: row_cut(20)),
            ("quotes cut to 110 characters around the match", lambda: quotes_around(110)),
            ("sentences cut to the first 15", lambda: row_cut(15)),
        ]
    else:
        cuts = [
            ("quotes cut to 300 characters", lambda: quotes(300)),
            ("sentences cut to the first 120", lambda: row_cut(120)),
            ("quotes cut to 160 characters", lambda: quotes(160)),
            ("sentences cut to the first 60", lambda: row_cut(60)),
            ("quotes cut to 110 characters", lambda: quotes(110)),
            ("sentences cut to the first 30", lambda: row_cut(30)),
            ("sentences cut to the first 15", lambda: row_cut(15)),
        ]
    reply = _shrink(reply, cuts)
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
                    cap: int, doc_keys: list[str] | None = None) -> list[sqlite3.Row]:
    """bm25 over the ``doc_page`` text of EVERY held document type (calls, decks, annual reports, results, press
    releases, announcements): the page's own sentence around the match, newest first.  The same phrase-first
    matcher ``pilot3_search`` uses, so a theme the tagger never emitted is answered from the page that prints it
    (T-197 step 2)."""
    words = [w for w in re.findall(r"[\w₹%&\-\.]+", " ".join(x for x in (topic, terms, rank_terms) if x or ""))
             if len(w) > 2][:8]
    if not words:
        return []
    match = _fts_groups(words, "and") or _fts_groups(words, "or")   # T-239: a synonym is OR-ed, never required
    if not match:
        return []
    extra, eargs = _asof(as_of, "COALESCE(p.known_at, d.known_at)")
    date_sql, date_args = "", []
    for col, val, op in (("d.filing_date", _day(date_from, "date_from"), ">="),
                         ("d.filing_date", _day(date_to, "date_to"), "<=")):
        if val:
            date_sql += f" AND {col} {op} ?"
            date_args.append(val)
    if doc_keys:     # T-242 fix 5: a named call's own documents (printed call date OR filing date within 3 days)
        date_sql += f" AND d.doc_key IN ({','.join('?' * len(doc_keys))})"
        date_args.extend(doc_keys)
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


_GUIDANCE_BALANCE = re.compile(r"\b(?:balance|remaining)\b(?!\s+sheet)|\brest of the (?:year|period)\b|"
                               r"\bnext (?:two|three|four) quarters\b", re.I)

# T-242 fix 7: a target said for a wholly-owned subsidiary's board approval, a brand, a division or a segment is a
# component's number, never the group's own full-year target (audit 7: ARE&M's 2,320 cr ARACT approval came first
# while the call guides 1,700 cr for the group's FY27 capex).  Structural: the quote's own scope words.
_GUIDANCE_COMPONENT = re.compile(
    r"\b(?:w\s?o\s?s|wholly[- ]owned|subsidiary|board\s+of\s+[a-z0-9 .&,'-]{2,80}?\s+limited|"
    r"proprietary\s+brand|brand|division|segment|joint\s+venture|jv|associate|step[- ]down)\b", re.I)


# T-242 fix 9: a target whose own quote calls its value the PREVIOUS one ("exceeding our previously communicated
# FY27 consolidated revenue growth guidance of 12% to 14%") is stale beside the sibling the same filing elected
# against it ("delivering on our upgraded guidance of 15% to 17%").  Both markers are structural: the quote's own
# words, no company and no metric.
_GUIDANCE_STALE = re.compile(
    r"(?:exceed\w*|ahead of|higher than|beat\w*|surpass\w*|against|versus)\b[^.]{0,90}?"
    r"(?:previously|previous|earlier|last)\s+(?:communicated|guided|stated|given|indicated|shared)"
    r"|(?:previously|previous|earlier)\s+(?:communicated|guided|stated|given|indicated)\b"
    r"|\bguidance\s+(?:we|it)\s+(?:had\s+)?(?:given|stated|communicated)\b", re.I)
_GUIDANCE_UPGRADED = re.compile(
    r"\b(?:upgraded|raised|revised\s+upward|increased)\s+(?:our\s+)?(?:full[- ]year\s+)?"
    r"(?:revenue|ebitda|margin|earnings|profit|growth|aum|order|capex|consolidated\s+revenue)?\s*"
    r"(?:guidance|target|outlook)\b", re.I)


def _guidance_stale(row: dict[str, Any]) -> bool:
    """Does this row's own quote present its value as the previously communicated guidance being exceeded?"""
    return bool(_GUIDANCE_STALE.search(str(row.get("quote") or "")))


def _guidance_upgraded(row: dict[str, Any]) -> bool:
    """Does this row's own quote say the guidance it prints is the upgraded / raised one?  Such a row is the
    company's own target even when the same sentence goes on to name a segment ('our upgraded guidance of 15% to
    17% revenue growth for FY27 with Hotel segment growing from 17% to 19%' is still the FY27 consolidated target)."""
    return bool(_GUIDANCE_UPGRADED.search(str(row.get("quote") or "")))


# T-242 fix 9: a target the quote attributes to another named entity ("in line with Syngene's revised full year
# guidance") is that entity's, never the group's, even when the store left ``entity`` empty (BIOCON audit 9).  The
# name is read from the quote's own possessive, so no company list is hard-coded; the reporting company's own name
# is never foreign.
_GUIDANCE_FOREIGN = re.compile(
    r"\b((?:[A-Z][A-Za-z&.\-]{2,})(?:\s+[A-Z][A-Za-z&.\-]{1,}){0,3})['’]s\s+"
    r"(?:revised\s+)?(?:full[- ]year\s+)?(?:guidance|target|outlook)\b")
_GUIDANCE_GENERIC_NAME = {"company", "management", "board", "group", "business", "consolidated", "standalone",
                          "full", "year", "its", "their", "our", "the", "previous", "current"}


def _guidance_foreign_entity(row: dict[str, Any], own: list[str] | tuple[str, ...] = ()) -> str:
    """The other entity a target's own quote attributes the guidance to ('' when it is the company's own)."""
    match = _GUIDANCE_FOREIGN.search(str(row.get("quote") or ""))
    if not match:
        return ""
    name = match.group(1).strip()
    word = re.sub(r"[^a-z]", "", name.lower())
    if len(word) < 3 or word in _GUIDANCE_GENERIC_NAME:
        return ""
    if any(word in o or o in word for o in own if len(o) >= 3):
        return ""
    return name


def _guidance_group_target(row: dict[str, Any]) -> bool:
    """Is this target the company's / group's own, not a component's, a subsidiary approval's or another entity's?"""
    if _guidance_upgraded(row):
        return True
    if row.get("entity_quote"):
        return False
    return not _GUIDANCE_COMPONENT.search(str(row.get("quote") or ""))



# T-242 fix 8: a target the page itself disclaims or calls an aspiration ("it should be aspiring for 10% margin" on
# the same page as "no guidance at the moment ... get to 6.5%") is never elected first.  Structural: the quote's own
# words, no company list.
_GUIDANCE_DISCLAIMED = re.compile(
    r"\bno guidance\b|\bnot guid(?:ing|e|ed)\b|\baspir(?:e|es|ing|ation)\b|\bhope(?:s|d)? to\b|"
    r"\bwait and see\b|\btoo early to\b|\bdifficult to (?:project|guide)\b", re.I)


def _guidance_disclaimed(row: dict[str, Any]) -> bool:
    """Does this target's own quote disclaim guidance or call it an aspiration?"""
    return bool(_GUIDANCE_DISCLAIMED.search(str(row.get("quote") or "")))


# T-242 fix 8: a money ask ("capex") must not be answered by an allocation-share percentage rule noise
# (NEW:capex_allocation_share: 5% / 3% / 8% ... is how the store tagged a pie chart, not a capex plan).
_GUIDANCE_NOISE = re.compile(r"(?:^|_)(?:share|allocation)(?:_|$)")


def _guidance_noise_measure(metric: str | None) -> bool:
    """Is this measure a share / allocation / bare percentage, never an amount a money ask asks for?"""
    code = _norm_measure(str(metric or ""))
    return bool(_GUIDANCE_NOISE.search(code)) or code.endswith("_pct")


def _guidance_subject_words(metric: str | None) -> list[str]:
    """The subject words a guidance metric's own name carries ('aum_growth' -> aum, plus the thesaurus spelling).

    A movement token ("growth", "yoy") never counts: the row's quote must print the measure it claims to be, so a
    disbursement-growth remark tagged ``aum_growth`` (AYE audit 9) is not evidence of an AUM target."""
    code = _norm_measure(str(metric or ""))
    if not code or code.startswith("new:"):
        return []
    words = [t for t in code.split("_") if len(t) > 2 and t not in _MOVEMENT_TOKENS]
    out = list(words)
    for word in words:
        for term in _synonyms_for(word):
            low = term.lower()
            if low not in out:
                out.append(low)
    return out


def _guidance_quote_evidence(row: dict[str, Any]) -> bool:
    """Does the row's own quote print the measure's own subject word (AUM, revenue, EBITDA ...)?

    T-242 fix 9: a row whose quote never names the measure ("the disbursement for this quarter and growth of
    roughly 22%") is a looser sibling of one that does ("we are targeting an AUM growth ... between 25% to 30%"),
    and loses to it.  A row whose metric has no checkable subject keeps its place."""
    words = _guidance_subject_words(row.get("metric"))
    if not words:
        return True
    text = re.sub(r"[^a-z0-9]+", " ", str(row.get("quote") or "").lower())
    return any(word in text for word in words)


def _guidance_elect(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One current row per metric+period (T-242): the company's / group's own full-year target wins over a
    component's or subsidiary approval's ("ARACT, WOS, has approved a capex of Rs. 2,320 crores" is not the group's
    FY27 capex) and over the balance-of-year restatement of the same target ("INR80 crores for the year" over "the
    balance INR75 crores for the next three quarters"); otherwise the first row served (the table is newest first).
    T-242 fix 9 adds the row's own printed evidence: a quote that calls its value the previously communicated one
    loses to the upgraded sibling the same filing elected against it, a quote that prints the metric's subject
    word beats a looser growth sibling, and a target its quote attributes to another entity never wins.
    Returns (kept, alternatives)."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["metric"], row["target_period"], row.get("entity") or ""), []).append(row)
    kept_ids: set[int] = set()
    alternatives: list[dict[str, Any]] = []
    for group in groups.values():
        stale_any = any(_guidance_stale(row) for row in group)

        def _key(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
            return (1 if _guidance_stale(row) else 0,
                    0 if (stale_any and _guidance_upgraded(row)) else 1,
                    0 if _guidance_group_target(row) else 1,
                    0 if _guidance_quote_evidence(row) else 1,
                    1 if _GUIDANCE_BALANCE.search(str(row.get("quote") or "")) else 0)

        chosen = sorted(group, key=_key)[0]
        kept_ids.add(id(chosen))
        alternatives += [row for row in group if row is not chosen]
    return [row for row in rows if id(row) in kept_ids], alternatives



def _guidance_demote_components(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Hold back component / subsidiary-approval / disclaimed rows before the newest-document collapse (T-242 fix 7/8).

    ``current_rows`` keeps every row of the newest document for a metric+period, so a later WOS board approval
    replaces the group's own target before the election can choose (ARE&M: the ARACT WOS approval of 2,320 crores
    came from a later document than the call's 1,700-crore group estimate).  A component row is never the group's
    target, and a target its own page disclaims or calls an aspiration is never a guidance target either (audit 8:
    BLUESTARCO's "aspiring for 10%" over the same page's "no guidance at the moment ... get to 6.5%"): both go to
    the reply's alternatives, labelled, and the group's own clear rows go on to the normal election."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["metric"], row["target_period"]), []).append(row)
    kept_ids: set[int] = set()
    alternatives: list[dict[str, Any]] = []
    for group in groups.values():
        foreign = [row for row in group if row.get("entity_quote")]
        rest = [row for row in group if not row.get("entity_quote")]
        company = [row for row in rest if _guidance_group_target(row)]
        clear = [row for row in company if not _guidance_disclaimed(row)]
        if clear:
            kept_ids.update(id(row) for row in clear)
        elif company:
            pass        # every candidate group target is disclaimed / aspirational: none is the answer
        elif rest:
            # the old fallback: a group whose only rows are component-ish still answers (a build that names no
            # entity); another entity's target is never kept, however alone it is (T-242 fix 9).
            kept_ids.update(id(row) for row in rest)
        alternatives.extend(row for row in group if id(row) not in kept_ids)
    return [row for row in rows if id(row) in kept_ids], alternatives


def _guidance_alt(row: dict[str, Any]) -> dict[str, Any]:
    """A dropped current row, said plainly, so the reply shows the other target it elected against (T-242)."""
    balance = bool(_GUIDANCE_BALANCE.search(str(row.get("quote") or "")))
    entity = str(row.get("entity_quote") or "")
    component = not _guidance_group_target(row)
    disclaimed = _guidance_disclaimed(row)
    stale = _guidance_stale(row)
    if balance:
        why = "balance-of-year restatement of the full-year target"
    elif entity:
        why = f"another entity's target ({entity}), not the group's own full-year one"
    elif component:
        why = "a component / subsidiary target, not the group's own full-year one"
    elif disclaimed:
        why = "a target its own page disclaims or calls an aspiration, not a guidance target"
    elif stale:
        why = "a target its own quote calls the previously communicated one, which the filing's upgraded target supersedes"
    else:
        why = "an earlier target of the same metric and period"
    out = {"metric": row["metric"], "period": row["target_period"], "low": row["low"], "high": row["high"],
           "unit": row["unit"], "said_on": row["said_on"], "quote": _trim(row["quote"], 240),
           "why_not_preferred": why,
           "provenance": _prov("guidance", f"{row['doc_key']} p{row['page']}", row.get("known_at"),
                               doc_type=row.get("doc_type"), title=_trim(row.get("title"), 120),
                               row_id=row["id"])}
    if entity:
        out["entity"] = entity
    return out



def _guidance_held_quarantined(symbol: str, names: list[str], label: str | None,
                               day: str | None) -> list[str]:
    """Targets the row check quarantined for the metric asked, said plainly (T-242 fix 6).

    A hidden target is held, never absent: the block names the metric, period, value and page, and says that
    ``include_quarantined=true`` shows the row.  It is never returned as the answer."""
    if not _has_table("row_check") or not _has_table("guidance"):
        return []
    where = ["g.symbol=?", "rc.status='quarantined'"]
    args: list[Any] = [symbol]
    if names:
        where.append(f"g.metric IN ({','.join('?' * len(names))})")
        args.extend(names)
    if label:
        where.append("g.target_period=?")
        args.append(label)
    extra, eargs = _asof(day, "g.known_at")
    rows = _q(f"SELECT g.metric, g.target_period, g.low, g.high, g.unit, g.said_on, g.page "
              f"FROM guidance g JOIN row_check rc ON rc.tbl='guidance' AND rc.row_id=g.id "
              f"WHERE {' AND '.join(where)}{extra} ORDER BY COALESCE(g.known_at, g.said_on) DESC LIMIT 10",
              (*args, *eargs))
    out: list[str] = []
    for r in rows:
        low, high = r["low"], r["high"]
        span = (f"{low:g}" if isinstance(low, (int, float)) else str(low or "?")) + (
            f"-{high:g}" if isinstance(high, (int, float)) and high != low else "")
        out.append(f"guidance / {r['metric']} / {r['target_period']}: {span} {r['unit'] or ''}, "
                   f"said {r['said_on']} (p{r['page']}); the row check quarantined it: include_quarantined=true "
                   f"shows it")
    return out


def guidance(symbol: str, metric: str | None = None, period: str | None = None, as_of: str | None = None,
             limit: int = 12, history: bool = False, include_quarantined: bool = False) -> dict[str, Any]:
    """Rule-extracted forward guidance: the CURRENT target of each metric and target period, newest first, with
    the row it revised (``revision_of`` and the previous low/high/date, so "did the guidance change between the
    two calls" is one call).  An older row of the same metric+period that a later document replaced is dropped and
    the kept row says how many (``superseded_rows``); ``history=true`` returns every row as stored.  ``low`` and
    ``high`` are NULL on a target said in words ("high single-digit", "in the 70s, mid-70s or higher"): the
    direction and the quote carry it.  A row the independent checker quarantined is hidden unless
    ``include_quarantined=True``; when no served row matches, the quarantined targets for the metric and period are
    still reported under ``held_quarantined`` (with value, page and the way to show them), never as the answer, and a
    target held only in ``obs_fact`` ``record_type='guidance'`` is served with ``source='obs_fact'`` (its target
    period is the period asked when the call printed the range without a year, marked ``period_source='unstated'``).
    Every row says ``check_status`` verified or unverified (T-113).  A target its own quote disclaims or calls an
    aspiration is never elected first, and a money ask such as capex skips allocation-share / ``_pct`` measure
    noise.  A target the same filing's quote calls the previously communicated one loses to the upgraded sibling of
    its metric+period+date, a target its own quote attributes to another named entity never wins, and a row whose
    quote never prints the measure's own subject word loses to a sibling that does.
    A target
    stated for a named subsidiary, segment or investee is stored with that ``entity`` and never returned here: only
    the group's own guidance is served (T-192)."""
    def _served_metrics() -> list[str]:
        return _available("guidance", "metric", sym, extra="" if include_quarantined else _visible("guidance"))

    sym = resolve_symbol(symbol)
    has_obs = _has_table("obs_fact")
    # T-242 fix 6: the metric NAMES are resolved without the quarantine filter -- a target whose only rows the
    # checker quarantined still has a name, and the reply must say it is held (never serve it as the answer).
    names, _allnames = _pick("guidance", "metric", sym, metric) if metric else ([], list(GUIDANCE_METRICS))
    if metric and not names and not has_obs:
        return _reply(sym, [], "pilot3_guidance", available=_served_metrics(), metric_asked=metric,
                      nearest=f"{metric} {period or ''}".strip(), nearest_as_of=as_of)
    kind, label = norm_period(period)
    # only the group's own targets: a target stated for a named subsidiary, associate, joint venture or acquired
    # company carries its ``entity`` and is never served as the company's (T-192).  A store built before the column
    # existed has no entity rows at all, so every row it holds is the group's and is served (T-192 round 4).
    g_entity = _has_column("guidance", "entity")
    g_unsure = _has_column("guidance", "entity_unsure")
    kept: list[dict[str, Any]] = []
    if not metric or names:
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
        kept = [dict(r) for r in rows]
    # T-242 fix 9: the quote's own possessive names the entity a target belongs to ("in line with Syngene's revised
    # full year guidance"), which the store's empty ``entity`` cannot; the reporting company's own name is never
    # another entity's.
    own_words = [re.sub(r"[^a-z]", "", str(r[0] or "").lower())
                 for r in (_q("SELECT name FROM company WHERE symbol=?", (sym,)) if _has_table("company") else [])]
    for r in kept:
        r["entity_quote"] = _guidance_foreign_entity(r, own_words)
    # T-242 fix 8: a money ask ("capex") is never answered by an allocation-share percentage the store happens to
    # tag under the same word (AZTEC NEW:capex_allocation_share 5%/3%/8%: a pie chart's shares, not a capex plan).
    money_ask = bool(metric) and (_metric_family(metric or "") == "money"
                                  or _metric_key(metric or "") in ("capex", "capital_expenditure", "capital_outlay"))
    if money_ask:
        kept = [r for r in kept if not _guidance_noise_measure(r["metric"])]
    out = []

    def _g_when(row: dict[str, Any]) -> str:
        return str(row.get("known_at") or row.get("said_on") or "")

    latest_by_key: dict[tuple, dict[str, Any]] = {}
    for r in kept:
        gkey = (r["metric"], r["target_period"], r.get("entity") or "")
        cur = latest_by_key.get(gkey)
        if cur is None or (_g_when(r), r["id"]) > (_g_when(cur), cur["id"]):
            latest_by_key[gkey] = r
    for r in kept:
        gkey = (r["metric"], r["target_period"], r.get("entity") or "")
        newest = latest_by_key[gkey]
        if _g_when(r) == _g_when(newest):
            r["is_latest"] = True
            r["superseded_by"] = None
        else:
            r["is_latest"] = False
            r["superseded_by"] = {"row_id": newest["id"], "said_on": newest["said_on"], "known_at": newest["known_at"]}
    alternatives: list[dict[str, Any]] = []
    if not history:
        kept, component_alts = _guidance_demote_components(kept)   # T-242 fix 7: a component is never the group's
        kept = _guidance_current_rows(kept)   # the current target per metric+period, with its dropped-row count
        kept, dropped = _guidance_elect(kept)  # T-242: one row per metric+period; group over balance-of-year
        alternatives = [_guidance_alt(r) for r in component_alts + dropped][:12]
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
                "is_latest": r["is_latest"], "superseded_by": r["superseded_by"],
                "provenance": _prov("guidance", f"{r['doc_key']} p{r['page']}", r["known_at"],
                                    doc_type=r["doc_type"], title=_trim(r["title"], 120),
                                    row_id=r["id"])}
        low_money = _money_inr_cr(r["low"], r["unit"])
        if low_money is not None:
            item["low_inr"] = low_money[0]
            if low_money[1] is not None:
                item["low_cr"] = low_money[1]
        high_money = _money_inr_cr(r["high"], r["unit"])
        if high_money is not None:
            item["high_inr"] = high_money[0]
            if high_money[1] is not None:
                item["high_cr"] = high_money[1]
        if r["entity_unsure"]:
            item["entity_unsure"] = True    # the text named a candidate the store cannot prove is a subsidiary
        out.append(_add_check(item, r))
    if has_obs:
        obs_g = _obs_rows(sym, measure=metric, period=period, record_type="guidance", as_of=as_of,
                          limit=_cap(limit), measure_exact=True)
        if metric and not obs_g:
            # T-242 fix 6: a guidance observation filed under a longer measure ("revenue growth" ->
            # revenue_growth_yoy) is held with record_type='guidance'; the number route rejects a movement token, the
            # guidance route does not -- the ask itself named it.
            cands = _pick("obs_fact", "measure", sym, metric,
                          extra=" AND record_type='guidance' AND status IN ('verified','unverified')")[0]
            if cands:
                wanted = {_norm_measure(c) for c in cands}
                pool = _obs_rows(sym, period=period, record_type="guidance", as_of=as_of, limit=200)
                obs_g = [r for r in pool if _norm_measure(r["measure"]) in wanted][: _cap(limit)]
        if metric and not obs_g:
            # T-242 fix 7: a guidance observation filed under a placeholder measure
            # (NEW:<revenue_or_ebitda_growth_expectation>) names no metric a user's word can match; the ask's own
            # measure words inside the code do name it ("revenue growth" -> revenue + growth in the placeholder).
            want = [w for w in re.split(r"[^a-z0-9]+", str(metric).lower()) if len(w) > 2]
            if want:
                pool = _obs_rows(sym, period=period, record_type="guidance", as_of=as_of, limit=200)
                obs_g = [r for r in pool if all(w in _norm_measure(r["measure"]) for w in want)][: _cap(limit)]
        if metric and not obs_g and period:
            # T-242 fix 6: a guidance observation often prints the range but not the year it targets ("the range we
            # have always spoken is 65% to 67%").  Rows whose target period is unstated answer the period asked and
            # say so; a row of a DIFFERENT stated period is never borrowed.
            asked_kind, asked_label = norm_period(period)
            loose = _obs_rows(sym, measure=metric, period=None, record_type="guidance", as_of=as_of,
                              limit=_cap(limit) * 4, measure_exact=True)
            obs_g = [r for r in loose if not r.get("period")][: _cap(limit)]
            for r in obs_g:
                r["period"] = asked_label or period
                r["period_source"] = "unstated"
        if money_ask:
            obs_g = [r for r in obs_g if not _guidance_noise_measure(r["measure"])]
        for r in obs_g:
            item = {"metric": r["measure"], "period": r["period"], "low": r["value"], "high": r["value_high"],
                    "unit": r["unit"], "direction": r["direction"], "said_on": (r.get("known_at") or "")[:10],
                    "quote": _trim(r.get("statement"), 300), "speaker": r.get("speaker"), "revision_of": None,
                    "previous": None, "changed": False, "superseded_rows": 0, "is_latest": True,
                    "superseded_by": None, "status": r["status"], "check_status": r["status"],
                    "source": "obs_fact", "doc_key": r["doc_key"], "page": r["page"],
                    "entity_scope": r.get("entity_scope"), "provenance": r["provenance"]}
            if r.get("period_source") == "unstated":
                item["period_source"] = "unstated"       # the call printed the range, not the target year
            _add_money(item, r["value"], r["unit"], r["scale"])
            if _scope_rank(r) >= 2:
                # T-242 fix 7: another scope's target is never the company's answer; it is shown labelled
                item["scope"] = _scope_label(r)
                item["why_not_preferred"] = "a figure of another scope, not the company's own target"
                alternatives.append(item)
                continue
            out.append(item)
    if out:
        # T-242 fix 8: a disclaimed / aspirational target is never served first, whatever its check status
        out.sort(key=lambda row: (1 if _guidance_disclaimed({"quote": row.get("quote")}) else 0,
                                  0 if (row.get("status") or row.get("check_status")) == "verified" else 1))
    held = None
    held_hidden = None
    served_names = None
    if not out:   # say what the table does hold, so the next call can be exact
        held = [f"{r[0]} / {r[1]} ({r[2]} rows)" for r in _q(
            f"SELECT metric, target_period, COUNT(*) FROM guidance WHERE symbol=?"
            + (f" AND metric IN ({','.join('?' * len(names))})" if names else "")
            + _visible("guidance") + " GROUP BY 1, 2 ORDER BY MAX(known_at) DESC LIMIT 40", (sym, *names))]
        if not include_quarantined:     # T-242 fix 6: a quarantined target is held and hidden, not absent
            held_hidden = _guidance_held_quarantined(sym, names, label, _day(as_of, "as_of"))
        if metric:
            # T-242: a miss still lists metrics with served rows alongside held_quarantined (not quarantined-only ones)
            served_names = _served_metrics()
    return _reply(sym, out, "pilot3_guidance", metrics_matched=names or None, history=True if history else None,
                  alternatives=alternatives or None,
                  available=served_names,
                  metric_asked=metric if (metric and not out) else None,
                  nearest=f"{metric or ''} {period or ''}".strip(), nearest_as_of=as_of,
                  held_options=held, held_quarantined=held_hidden or None, as_of=_day(as_of, "as_of"))


# --- pilot3_docs ------------------------------------------------------------------------------------
def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None, date_to: str | None = None,
         as_of: str | None = None, limit: int = 20, offset: int = 0,
         documents: str | None = None) -> dict[str, Any]:
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
                                      doc_cap=_doc_cap(documents, cap),
                                      hidden=_hidden_documents(sym, day)))

    def titles(width: int) -> None:
        for row in reply["rows"]:
            row["title"] = _trim(row.get("title"), width)

    def documents_cut(keep: int) -> None:
        listed = reply["coverage"].get("documents") or []
        if len(listed) > keep:
            del listed[keep:]
            reply["coverage"]["documents_not_listed"] = reply["coverage"]["matched_documents"] - keep

    full_list = _doc_cap(documents, cap) is None      # documents='all': the explicit list outranks the byte cap
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
TOPIC_REPLY_BYTES = 18_000   # the largest a full (20-item) topic page may get
TOPIC_BYTES_PER_ITEM = 3_000  # a page is sized to its items: 2 items -> 6 kB, 20 -> the 18 kB cap (T-204)
TOPIC_MIN_BYTES = 6_000      # the coverage block (documents, hidden list, summary) needs about this much


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


def _shrink(reply: dict[str, Any], cuts: list[tuple[str, Any]], where: str = "coverage",
            cap: int = REPLY_BYTES) -> dict[str, Any]:
    """Apply the cuts in order until the reply fits its byte cap, and say which cuts it took: a heavy theme is
    summarised, never served past the cap and never silently (T-197 step 1)."""
    applied: list[str] = []
    if _reply_bytes(reply) <= cap:
        return reply
    for label, cut in cuts:
        cut()
        applied.append(label)
        if isinstance(reply.get(where), dict):
            # the note itself costs bytes, so it is written before the fit is measured, never after
            reply[where]["detail"] = "; ".join(applied) + " to keep the reply within its byte cap"
        if _reply_bytes(reply) <= cap:
            break
    return reply


def _topic_bytes(limit: int) -> int:
    """A topic page is sized to its items: a two-item page gets 6 kB, a full 20-item page the 18 kB cap (T-204)."""
    return min(TOPIC_REPLY_BYTES, max(TOPIC_MIN_BYTES, int(limit) * TOPIC_BYTES_PER_ITEM))


def _trim_topic_reply(reply: dict[str, Any], limit: int = TOPIC_LIMIT,
                      keep_documents: bool = False) -> dict[str, Any]:
    """Keep a topic reply under its byte cap by cutting the optional detail in a fixed order -- the counts, the
    honest scope line and the document keys are never cut (T-197 step 1).  ``keep_documents`` (the caller asked
    for ``documents='all'``) leaves the explicit document list whole; the other cuts still apply (T-204)."""
    cap = _topic_bytes(limit)
    if _reply_bytes(reply) <= cap:
        return reply
    groups = reply.get("groups") or []
    docs = (reply.get("coverage") or {}).get("documents") or []

    def hidden_documents_cut(keep: int) -> None:
        listed = (reply.get("coverage") or {}).get("hidden_documents") or []
        if len(listed) > keep:      # hidden_after_as_of still counts every hidden document
            del listed[keep:]

    def summaries_cut(keep: int) -> None:
        cells = (reply.get("coverage") or {}).get("summarised_documents") or []
        if len(cells) > keep:
            reply["coverage"]["summarised_cells"] = max(reply["coverage"].get("summarised_cells") or 0, len(cells))
            del cells[keep:]

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
        ("document list cut to the first 20, the rest summarised by type",
         lambda: None if keep_documents else (docs.__delitem__(slice(20, None)) if len(docs) > 20 else None)),
        ("document titles cut", lambda: [doc.pop("title", None) for doc in docs]),
        ("document page lists cut", lambda: [doc.pop("pages", None) for doc in docs]),
        ("the hidden-document list cut to the first five, its count kept", lambda: hidden_documents_cut(5)),
        ("the document summary cut to six type-month cells", lambda: summaries_cut(6)),
        ("quotes cut to 110 characters", lambda: quotes(110)),
        ("event body excerpts cut to 180 characters", lambda: bodies(180)),
        ("quotes cut to 70 characters", lambda: quotes(70)),
        ("group titles cut", lambda: [group.pop("title", None) for group in groups]),
    ]
    reply = _shrink(reply, cuts, cap=cap)
    if reply["coverage"].get("matched_documents", 0) > len(docs):
        reply["coverage"]["documents_not_listed"] = reply["coverage"]["matched_documents"] - len(docs)
    return reply


def topic(symbol: str, topic: str, as_of: str | None = None, limit: int = TOPIC_LIMIT,
          date_from: str | None = None, date_to: str | None = None, offset: int = 0,
          documents: str | None = None) -> dict[str, Any]:
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

    if _has_table("obs_fact"):
        extra, eargs = _asof(as_of, "o.known_at")
        for r in _q(f"SELECT o.* FROM obs_fact o WHERE o.symbol=? AND o.record_type='statement'{extra} "
                    f"ORDER BY o.known_at DESC LIMIT 2000", (sym, *eargs)):
            if not _topic_hit(plan, r["statement"], r["measure"]):
                continue
            keep("statement", (r["known_at"] or "")[:10], r["doc_key"], r["page"], r["statement"],
                 call_period=None, speaker=r["speaker"], role=None, topics=None, entities=None,
                 period_discussed=None, doc_type=r["doc_type"], title=_trim((r["series_title"] if "series_title" in r.keys() else None) or "", 120),
                 provenance=_prov("obs_fact", f"p{r['page']}", r["known_at"], row_id=r["observation_id"]),
                 match="obs")
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

    atoms_here = _has_table("page_atom") and bool(_q("SELECT 1 FROM page_atom WHERE symbol=? LIMIT 1", (sym,)))
    if atoms_here:
        # T-199: the resolved atoms are the figures; the raw cells are served only while the store holds no atoms
        extra, eargs = _asof(as_of, "a.known_at")
        for r in _q(f"SELECT a.doc_key, a.page, a.known_at, a.row_label, a.col_header, a.table_title, a.value, "
                    f"a.value_text, a.unit, a.scale, a.period, a.basis, a.check_status, a.check_reasons "
                    f"FROM page_atom a WHERE a.symbol=?{extra} ORDER BY a.known_at DESC LIMIT 4000", (sym, *eargs)):
            if not _topic_hit(plan, r["row_label"], r["table_title"], r["col_header"]):
                continue
            keep("cell", r["known_at"], r["doc_key"], r["page"], r["row_label"],
                 value=r["value"], value_text=r["value_text"], unit=r["unit"], scale=r["scale"],
                 period=r["period"], basis=r["basis"], column=r["col_header"], table=r["table_title"],
                 check_status=r["check_status"], source="page_atom",
                 provenance=_prov("page_atom", f"p{r['page']}", r["known_at"]))
    elif _has_table("page_cell"):
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

    if _has_table("filing_event"):
        extra, eargs = _asof(as_of, "e.known_at")
        for r in _q(f"SELECT e.* FROM filing_event e WHERE e.symbol=?{extra} "
                    f"ORDER BY COALESCE(e.filing_date, e.known_at) DESC", (sym, *eargs)):
            if not _topic_hit(plan, r["quote"], r["kind"], (r["customer"] if "customer" in r.keys() else None), (r["title"] if "title" in r.keys() else None)):
                continue
            keep("event", r["filing_date"] or r["known_at"], r["doc_key"], r["page"], r["quote"],
                 event=r["kind"], doc_type=None, title=_trim((r["title"] if "title" in r.keys() else None) or "", 120),
                 provenance=_prov("filing_event", f"p{r['page']}", r["known_at"], row_id=r["event_id"]))
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
    # T-204: a source goes in exactly one list -- one the build has no table for is not "searched".
    structured = [("guidance", "guidance (forward targets)"),
                  ("kpi_series", "kpi_series (company-stated KPIs)")]
    if _has_table("page_atom"):
        structured.append(("page_atom", "page_atom (resolved printed figures)"))
    skipped_sources: list[str] = []
    if atoms_here and _has_table("page_cell"):
        skipped_sources.append("page_cell (raw cells; page_atom served the resolved figures)")
    else:
        structured.append(("page_cell", "page_cell (table and chart cells)"))
    structured.append(("event", "event (inspection, dividend, buyback, acquisition, merger)"))
    missing = [name for name, _label in structured if not _has_table(name)]
    doc_cap = _doc_cap(documents, cap)
    return _trim_topic_reply({
            "found": bool(shown), "symbol": sym, "tool": "pilot3_topic", "topic": topic, "as_of": day,
            "tags_matched": plan["tags"], "text": text, "n": shown,
            "counts": {**counts, "matched": matched, "shown": shown, "cut": cut},
            "groups": ordered, "read_next": read_next,
            "coverage": _coverage("topic", list(_TEXT_STORES) + [
                label for name, label in structured if name not in missing],
                ["pages the build holds no text for (OCR never read them, audio/video links)", *missing,
                 *skipped_sources],
                matched, shown, cut, start, documents=docs, doc_cap=doc_cap,
                document_total=doc_total, outside=outside_list, hidden=hidden),
            "candidate_pages": candidates,
            "expansions_matched": _expansions_hit(topic, ordered + list(candidates or [])) or None,
            "as_of_note": f"documents first known after {day} are not used" if day else None,
            "hint": None if shown else "NOT IN DATA of pilot3 for this topic: try the words management uses, a wider "
                                       "date_from/date_to, or pilot3_search for the wording; only then the raw tools.",
            "provenance": _db_prov()}, limit=cap, keep_documents=doc_cap is None)


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
           date_from: str | None = None, date_to: str | None = None, offset: int = 0,
           documents: str | None = None) -> dict[str, Any]:
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
    expansions, _named = _expansion(query)   # T-239: a synonym widens the OR set, never the required words
    if expansions:
        or_query = f"({or_query}) OR ({_fts_any(expansions)})"
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
    page_documents: list[dict[str, Any]] = []
    by_doc: dict[str, dict[str, Any]] = {}
    for r in ranked:                    # the documents this page's rows came from (the full list is in coverage)
        group = by_doc.get(r["doc_key"])
        if group is None:
            group = by_doc[r["doc_key"]] = {"doc_key": r["doc_key"], "doc_type": r["doc_type"],
                                            "title": _trim(r["title"], 60), "filing_date": r["filing_date"],
                                            "pages": []}
            page_documents.append(group)
        if r["page"] not in group["pages"] and len(group["pages"]) < 3:
            group["pages"].append(r["page"])
    cut = max(0, pages_matched - start - len(ranked))
    expansions_hit = [term for term in expansions
                      if any(term in str(row["text"] or "").lower() for row in ranked)][:6]
    text = (f"{pages_matched} page(s) match {query!r} ({match_mode} match) in {documents_matched} document(s)"
            + (f"; {pages_short} more print it short" if pages_short else "")
            + (f"; a substring scan counts {pages_like} (it also counts a longer number)" if pages_like else "")
            + (f"; the synonym expansion also matched {', '.join(expansions_hit)}" if expansions_hit else "")
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
                         doc_cap=_doc_cap(documents, cap),
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
                   documents=page_documents, as_of=day, hidden_after_as_of=hidden, pages_short=pages_short,
                   pages_like=pages_like, coverage=coverage, expansions_matched=expansions_hit or None,
                   read_next=_read_next([{"doc_key": r["doc_key"], "page": r["page"]} for r in ranked]))

    def snippets(width: int) -> None:
        for row in reply["rows"]:
            row["snippet"] = _trim(row.get("snippet"), width)

    def documents_cut(keep: int) -> None:
        listed = reply["coverage"].get("documents") or []
        if len(listed) > keep:
            del listed[keep:]
            reply["coverage"]["documents_not_listed"] = reply["coverage"]["matched_documents"] - keep

    full_list = _doc_cap(documents, cap) is None      # documents='all': the explicit list outranks the byte cap
    return _shrink(reply, [
        ("snippets cut to 200 characters", lambda: snippets(200)),
        ("document titles cut", lambda: [doc.pop("title", None) for doc in reply["coverage"]["documents"]]),
        ("snippets cut to 120 characters", lambda: snippets(120)),
        ("document list cut to the first 20 of the rank", lambda: None if full_list else documents_cut(20)),
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
# T-242: a bare holder word is a shareholding question ("promoter", "FPI", "DII", "MF"); anything else needs the
# question to say holding / shareholding / stake / shareholders, so "retail deposits" is never the shp_category.
_FACT_HOLDING_ONLY = {"promoter", "promoters", "fpi", "fii", "dii", "mf", "mutual_funds", "shareholding"}
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
    value, unit, scale = _fact_value(row)
    table, doc, page = _split_source(row.get("provenance") or {})
    alt = _add_money({"value": value, "unit": unit,
                      "period": period or row.get("period") or row.get("date") or row.get("quarter_end"),
                      "basis": row.get("basis"), "table": table, "doc_key": doc, "page": page,
                      "definition": row.get("definition")}, value, unit, scale)
    scope = _scope_label(row)     # T-242 fix 7: an alternative says whose figure it is ('industry figure')
    if scope:
        alt["scope"] = scope
    if row.get("scale_mismatch"):
        # T-242 fix 9: the row's own quote cannot reproduce its value in its unit, so it is labelled, never the answer
        alt["scale_mismatch"] = True
        alt["note"] = "the row's own quote prints a different figure than the stored value (a scale/extraction defect)"
    return alt



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
    orig_alt = _add_money({"value": row.get("value"), "unit": row.get("unit"), "scale": row.get("scale"),
                           "filing_date": str((row.get("provenance") or {}).get("known_at") or "")[:10],
                           "role": row.get("column_role") or "xbrl", "definition": row.get("definition"),
                           "provenance": row.get("provenance")},
                          row.get("value"), row.get("unit"), row.get("scale"))
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
    answer = _add_money({"value": value, "unit": unit, "scale_word": _scale_word(unit, scale), "period": period,
                         "basis": row.get("basis"), "as_of_used": as_of_used,
                         "source": {"table": table, "doc_key": doc, "page": page, "quote": _trim(row.get("quote"), 600)},
                         "known_at": prov.get("known_at") or row.get("known_at"), "computed": computed},
                        value, unit, scale)
    mismatch = _fact_mismatch(asked_period, asked_basis, row)
    if mismatch:
        answer["mismatch"] = mismatch
    status = _fact_check_status(row)
    if status:
        answer["check_status"] = status
    return answer


def _fact_why(path: str, row: dict[str, Any]) -> str:
    if (row.get("provenance") or {}).get("table") == "obs_fact" or row.get("source") == "obs_fact":
        return (f"the {row.get('status') or row.get('check_status') or 'extracted'} obs_fact page read for "
                f"{row.get('period') or 'this metric'}")
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


def _obs_covers(symbol: str, names: list[str], period: str | None) -> bool:
    """Does ``obs_fact`` hold this number metric (for the period asked, if any)?"""
    if not names or not _has_table("obs_fact"):
        return False
    psql, pargs = _obs_period_clause(period)
    return bool(_q(f"SELECT 1 FROM obs_fact o WHERE o.symbol=? AND o.record_type='number' "
                   f"AND o.status IN ('verified','unverified') AND o.measure IN ({','.join('?' * len(names))})"
                   f"{psql} LIMIT 1", (symbol, *names, *pargs)))


def _fact_route(key: str, symbol: str, period: str | None = None) -> tuple[str | None, dict[str, list[str]], dict[str, list[str]]]:
    """Which lookup owns a metric word (T-186 step 1): names matched per table, and every name each table holds."""
    rnames, rall = _pick("ratio_panel", "metric", symbol, key)
    qnames, qall = _pick("fin_quarter_xbrl", "line_item", symbol, key)
    pnames, pall = (_pick("fin_quarter_printed", "line_item", symbol, key)
                    if _has_table("fin_quarter_printed") else ([], []))
    anames, aall = _pick("fin_annual_line", "line_item", symbol, key)
    knames, kall = _pick("kpi_series", "metric", symbol, _KPI_WORDS.get(key, key))
    onames, oall = (_pick("obs_fact", "measure", symbol, key,
                          extra=" AND record_type='number' AND status IN ('verified','unverified')")
                    if _has_table("obs_fact") else ([], []))
    fnames = list(dict.fromkeys(qnames + anames + pnames))
    found = {"ratio_panel": rnames, "fin": fnames, "kpi_series": knames, "obs_fact": onames}
    allnames = {"ratio_panel": rall, "fin": list(dict.fromkeys(qall + aall + pall)),
                "kpi_series": kall, "obs_fact": oall}
    if key in _FACT_SHARES:
        # T-242 fix 4: a label asked WITH a period ("Share Capital" as of Mar-25) is a printed line, not the latest
        # share count -- APEX Mar-25 is 313.0 Rs Mn while the share-count route answered 31,250,000 shares of
        # 2026-09-30.  The shares route answers only when no held table prints this label for that period; fact()
        # falls back to it when the printed-line election comes back empty.
        printed = (key == "share_capital" and bool(period)
                   and (bool(fnames) or (bool(knames) and _kpi_covers(symbol, knames, period))
                        or (bool(onames) and _obs_covers(symbol, onames, period))))
        if not printed:
            return "shares", found, allnames
    # T-242: route a filed shp_category only for a question about who holds the shares ("promoter holding",
    # "FPI stake", "retail shareholders"), never for a line whose word merely shares a category name
    # ("retail deposits"): that is a P&L / balance line, not the shareholding pattern.
    if re.search(r"\b(holding|holdings|shareholding|stake|shareholders?)\b", key.replace("_", " ")) \
            or key in _FACT_HOLDING_ONLY:
        return "holding", found, allnames
    # T-192: a company's own EBITDA / EBITDA margin is the definition it means; the derived ratio is returned as a
    # second, labelled alternative.  Two derivations of one line disagreeing is exactly what sent a grader wrong.
    # Only a period the KPI rows cover takes that route: an earlier or later year still answers from the derived
    # ratio, never from a different period's company figure.
    if key in ("ebitda", "ebitda_margin", "ebitda_margin_pct") and (
            (found["kpi_series"] and _kpi_covers(symbol, found["kpi_series"], period))
            or (found["obs_fact"] and _obs_covers(symbol, found["obs_fact"], period))):
        return "kpi", found, allnames
    # a ratio word first: a margin / return / growth / valuation is computed or stated, not a balance line.  The
    # plain lines ratio_panel also mirrors (pat, revenue_from_operations) are not ratio words and go to fin.
    ratio_word = (key in _FACT_VALUATION or key in _FACT_RATIO_NAMES or key.endswith(_FACT_RATIO_SUFFIXES))
    if ratio_word and (key in rnames or f"{key}_pct" in rnames or key in _FACT_VALUATION):
        return "ratio", found, allnames
    if fnames:
        return "fin", found, allnames
    if knames or onames:
        return "kpi", found, allnames
    if rnames:
        return "ratio", found, allnames
    if _has_table("obs_fact") and _obs_kpi_rows(symbol, key, period, None, 1):
        return "kpi", found, allnames
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
    order = {"fin": ("fin", "ratio", "kpi"), "ratio": ("ratio", "fin", "kpi"),
             "kpi": ("kpi", "fin", "ratio"), "holding": ("holding",), "shares": ("shares",)}[path]
    out: list[str] = []
    for candidate in order:
        if candidate == path:
            out.append(candidate)
        elif candidate == "fin" and found.get("fin"):
            out.append(candidate)
        elif candidate == "ratio" and found.get("ratio_panel"):
            out.append(candidate)
        elif candidate == "kpi" and (found.get("kpi_series") or found.get("obs_fact")):
            out.append(candidate)
    return out


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
    for candidate in ("kpi", "ratio", "fin"):
        if candidate == path:
            continue
        if candidate == "kpi" and (found.get("kpi_series") or found.get("obs_fact")):
            return candidate
        if candidate == "ratio" and found.get("ratio_panel"):
            return candidate
        if candidate == "fin" and found.get("fin"):
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
            rows = _q("SELECT value, unit, scale, fiscal_year, doc_key, page, known_at FROM fin_annual_line WHERE rowid=?",
                      (rowid,))
            if rows and not _pit_ok(rows[0]["known_at"], cutoff):
                out["pit_hidden"] = True
                return out
        else:
            rows = _q(f"SELECT value, unit, scale, fiscal_year, doc_key, page FROM fin_annual_line WHERE symbol=? "
                      f"AND fiscal_year=? AND basis=? AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1",
                      (symbol, period, bas, item, *eargs))
        if rows:
            out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=rows[0]["fiscal_year"],
                       source={"table": "fin_annual_line", "doc_key": rows[0]["doc_key"], "page": rows[0]["page"]})
            _add_money(out, rows[0]["value"], rows[0]["unit"], rows[0]["scale"])
        return out
    if period == "ltm":
        trailing = f"{item}_ttm"
        rows = _q(f"SELECT rowid, value, unit, scale, fiscal_period FROM ratio_panel WHERE symbol=? AND metric=? "
                  f"AND period_end=? AND basis=?{_asof(cutoff)[0]} ORDER BY known_at DESC LIMIT 1",
                  (symbol, trailing, when or cutoff, bas, *_asof(cutoff)[1]))
        if rows:
            out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=rows[0]["fiscal_period"],
                       source={"table": "ratio_panel", "doc_key": None, "page": None})
            _add_money(out, rows[0]["value"], rows[0]["unit"], rows[0]["scale"])
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
            ltm_unit = "inr" if _money_inr_cr(1.0, unit) is not None else unit
            out.update(value=total, unit=ltm_unit, period=f"LTM to {when or cutoff}",
                       source={"table": "fin_quarter_xbrl", "doc_key": None, "page": None})
            _add_money(out, total, ltm_unit, 1.0)
        return out
    rows = _q(f"SELECT value, unit, scale, source_file FROM fin_quarter_xbrl WHERE symbol=? AND fiscal_period=? "
              f"AND basis=? AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1",
              (symbol, period, bas, item, *eargs))
    if rows:
        out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=period,
                   source={"table": "fin_quarter_xbrl", "doc_key": rows[0]["source_file"], "page": None})
        _add_money(out, rows[0]["value"], rows[0]["unit"], rows[0]["scale"])
        return out
    # a quarter the XBRL window does not hold is mirrored in ratio_panel by the derived-quarter part (T-129)
    rows = _q(f"SELECT rowid, value, unit, scale FROM ratio_panel WHERE symbol=? AND metric=? AND fiscal_period=? "
              f"AND basis=?{_asof(cutoff, 'known_at')[0]} ORDER BY known_at DESC LIMIT 1",
              (symbol, item, period, bas, *_asof(cutoff, "known_at")[1]))
    if rows:
        out.update(value=rows[0]["value"], unit=rows[0]["unit"], period=period,
                   source={"table": "ratio_panel", "doc_key": None, "page": None})
        _add_money(out, rows[0]["value"], rows[0]["unit"], rows[0]["scale"])
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
        store, rows = "ratio_panel", _q(f"SELECT value, unit, scale FROM ratio_panel WHERE symbol=? AND metric=? "
                                        f"AND fiscal_period=? AND basis=?{extra} ORDER BY known_at DESC LIMIT 1",
                                        (symbol, name, period, basis, *eargs))
        if not rows:
            store = "fin_quarter_xbrl"
            rows = _q(f"SELECT value, unit, scale FROM fin_quarter_xbrl WHERE symbol=? AND line_item=? AND fiscal_period=? "
                      f"AND basis=?{extra} ORDER BY known_at DESC LIMIT 1", (symbol, name, period, basis, *eargs))
        if not rows:
            store = "fin_annual_line"
            rows = _q(f"SELECT value, unit, scale FROM fin_annual_line WHERE symbol=? AND line_item=? AND fiscal_year=? "
                      f"AND basis=?{extra} ORDER BY known_at DESC LIMIT 1", (symbol, name, period, basis, *eargs))
        item = {"name": name, "value": rows[0]["value"] if rows else None,
                "unit": rows[0]["unit"] if rows else None, "period": period,
                "source": {"table": store, "doc_key": None, "page": None}}
        if rows:
            _add_money(item, rows[0]["value"], rows[0]["unit"], rows[0]["scale"])
        inputs.append(item)
    return inputs


def _fact_ratio_computed(symbol: str, row: dict[str, Any], day: str | None) -> dict[str, Any] | None:
    prov = row.get("provenance") or {}
    known = str(prov.get("known_at") or "")[:10] or day
    cutoff = day or known          # an input must be public by as_of; else by the figure's own filing
    if row.get("date"):                         # valuation_daily: PE / PB / EV-EBITDA / market cap on a day
        inputs = row.get("inputs")
        if isinstance(inputs, dict) and inputs.get("book_source") is not None:
            # T-239: P/B and book value per share are computed on the balance sheet the row names, not on the
            # earlier one valuation_daily's own net worth column may carry (NSIL: H1FY27, not FY26)
            return {"formula": row.get("definition_text") or "market cap / net worth on the latest balance sheet",
                    "inputs": [{"name": name, "value": inputs.get(name), "period": inputs.get("book_value_from"),
                                "source": inputs.get("book_source")}
                               for name in ("market_cap", "net_worth", "shares_outstanding")
                               if inputs.get(name) is not None]}
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
            val = values[0][column] if values and column in values[0].keys() else None
            item = {"name": name, "value": val,
                    "unit": "inr" if name in ("market_cap", "net_worth", "net_debt", "trailing_ebitda", "pat") else None,
                    "period": row.get("date"),
                    "source": {"table": "valuation_daily", "doc_key": None, "page": None}}
            if item["unit"] == "inr":
                _add_money(item, val, "inr", 1.0)
            inputs.append(item)
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
        rows = _q(f"SELECT value, unit, scale, doc_key, page, known_at FROM fin_annual_line WHERE symbol=? AND fiscal_year=? "
                  f"AND basis=? AND line_item=? ORDER BY known_at DESC LIMIT 5",
                  (symbol, row.get("period"), row.get("basis"), name))
        pick = next((r for r in rows if _pit_ok(r["known_at"], cutoff)), None)
        if pick is None and rows:
            return None                 # an input is not public at as_of: the computed figure is not served
        item = {"name": name, "value": pick["value"] if pick else None,
                "unit": pick["unit"] if pick else None, "period": row.get("period"),
                "source": {"table": "fin_annual_line", "doc_key": pick["doc_key"] if pick else None,
                           "page": pick["page"] if pick else None}}
        if pick:
            _add_money(item, pick["value"], pick["unit"], pick["scale"])
        inputs.append(item)
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
        rows = _q(f"SELECT line_item AS metric, fiscal_year AS period, basis, value, unit, scale, doc_key, page, known_at "
                  f"FROM fin_annual_line WHERE symbol=? AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1",
                  (symbol, name, *eargs))
        store = "fin_annual_line"
        if not rows:
            store = "fin_quarter_xbrl"
            rows = _q(f"SELECT line_item AS metric, fiscal_period AS period, basis, value, unit, scale, "
                      f"source_file AS doc_key, NULL AS page, known_at FROM fin_quarter_xbrl WHERE symbol=? "
                      f"AND line_item=?{extra} ORDER BY known_at DESC LIMIT 1", (symbol, name, *eargs))
    elif table == "ratio":
        store = "ratio_panel"
        rows = _q(f"SELECT metric, fiscal_period AS period, basis, value, unit, scale, NULL AS doc_key, NULL AS page, "
                  f"known_at FROM ratio_panel WHERE symbol=? AND metric=?{extra} ORDER BY known_at DESC LIMIT 1",
                  (symbol, name, *eargs))
    else:
        store = "kpi_series"
        rows = _q(f"SELECT metric, fiscal_period AS period, basis, value, unit, scale, doc_key, page, known_at "
                  f"FROM kpi_series WHERE symbol=? AND metric=?{extra} ORDER BY known_at DESC LIMIT 1",
                  (symbol, name, *eargs))
    if not rows:
        return None
    r = rows[0]
    return _add_money({"nearest": True, "table": store, "metric": r["metric"], "value": r["value"], "unit": r["unit"],
                       "period": r["period"], "basis": r["basis"], "known_at": r["known_at"],
                       "source": {"table": store, "doc_key": r["doc_key"], "page": r["page"]}},
                      r["value"], r["unit"], r["scale"])


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
    nearest += _nearest(symbol, metric, day)     # T-239: the pages/statements to read when no table row matches
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
    return _add_money({"value": best["value"], "unit": best["unit"], "scale_word": _scale_word(best["unit"], best["scale"]),
                       "period": best["fiscal_period"], "basis": best["basis"], "definition": best["raw_label"],
                       "source": {"table": "kpi_series", "doc_key": best["doc_key"], "page": best["page"]},
                       "known_at": best["known_at"], "check_status": status, "why_not_preferred": why},
                      best["value"], best["unit"], best["scale"])


def _fact_filed_conflict(symbol: str, key: str, period: str | None, day: str | None,
                         row: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    """A transcript number a filed results / press-release figure contradicts by more than 20% (T-242 fix 6).

    A call remark is unverified until a filing matches it within 1% (Shivam, 24 Nov).  When the preferred row is such
    a transcript observation and a filed row of the same measure and period differs by more than 20%, the filed value
    is served first and the call remark is listed as an alternative with ``conflict: true``.  Returns
    ``(filed_row, note)`` or None."""
    prov = row.get("provenance") or {}
    if row.get("source") != "obs_fact" or str(prov.get("doc_type") or "").lower() != "transcript":
        return None
    measure = str(row.get("metric") or "").strip()
    if not measure:
        names = _pick("obs_fact", "measure", symbol, key, extra=" AND record_type='number'")[0]
        measure = names[0] if names else ""
    if not measure:
        return None
    filed = [r for r in _obs_rows(symbol, measure=measure, period=period, record_type="number", as_of=day,
                                  limit=20, measure_exact=True)
             if str(r.get("doc_type") or "").lower() in ("results", "press_release")
             and r.get("value") is not None]
    if not filed:
        return None
    best = filed[0]              # _obs_rows orders results before press release, newest first
    value, unit, scale = _fact_value(row)
    filed_value, filed_unit, filed_scale = _fact_value(best)
    transcript_pair = _money_inr_cr(value, unit, scale)
    filed_pair = _money_inr_cr(filed_value, filed_unit, filed_scale)
    transcript_num: float | None
    filed_num: float | None
    if transcript_pair is not None and filed_pair is not None:
        transcript_num, filed_num = transcript_pair[0], filed_pair[0]
    elif (transcript_pair is None) != (filed_pair is None):
        # one spelling the money parser does not know ("Rs. Crore"): compare through the wider parser
        transcript_num, filed_num = _money_base(value, unit, scale), _money_base(filed_value, filed_unit, filed_scale)
    elif _norm_measure(unit or "") == _norm_measure(filed_unit or ""):
        try:
            transcript_num, filed_num = float(value) * scale, float(filed_value) * filed_scale
        except (TypeError, ValueError):
            return None
    else:
        return None
    if transcript_num is None or filed_num is None:
        return None
    if not filed_num or abs(transcript_num - filed_num) <= 0.20 * abs(filed_num):
        return None
    doc_type = str(best.get("doc_type") or "").lower().replace("_", " ")
    note = (f"the call remark says {value} {unit or ''} for {row.get('period') or period}, while the filed "
            f"{doc_type} prints {filed_value} {filed_unit or ''} for the same measure and period; the filed value is "
            f"served first and the call remark is an alternative (`conflict: true`)")
    filed_row = dict(best)
    filed_row.setdefault("metric", measure)
    filed_row["definition"] = "observed"
    filed_row["source"] = "obs_fact"
    filed_row["status"] = best.get("status")
    filed_row["check_status"] = best.get("check_status") or best.get("status")
    return filed_row, note


def _fact_atoms(sym: str, metric: str, period: str | None, day: str | None) -> dict[str, Any] | None:
    """T-199: the resolved printed figure when no pilot3 table holds the metric; ``source: page_atom`` labels it.

    The atom's ``row_label`` is the company's own words, so it is compared as the metric key (spaces as _); a
    ``change`` atom (a growth column, or a ▲/▼ move with no column header) is never served as the metric's level,
    and neither is an atom whose unit is not the family the metric's own definition carries (T-199 round 2)."""
    if not _has_table("page_atom"):
        return None
    key = _metric_key(metric)
    alias = _KPI_WORDS.get(key, key)
    words = [w for w in re.split(r"[^a-z0-9%]+", str(metric or "").lower()) if len(w) >= 2]
    if not words or not key:
        return None
    where = ["a.symbol=?", "COALESCE(a.unit,'')<>'change'"]
    args: list[Any] = [sym]
    for word in words:
        where.append("lower(COALESCE(a.row_label,'')||' '||COALESCE(a.table_title,'')) LIKE ?")
        args.append(f"%{word}%")
    _kind, label = norm_period(period)
    natural, _ym = _natural_date(period)
    if label and natural is None:
        where.append("lower(COALESCE(a.period,''))=lower(?)")
        args.append(label)
    extra, eargs = _asof(day, "a.known_at")
    rows = _q(
        "SELECT a.doc_key, a.page, a.known_at, a.row_label, a.col_header, a.table_title, a.period, a.basis, "
        "a.value, a.unit, a.scale, a.value_text, a.check_status, a.check_reasons, "
        "COALESCE(d.doc_type,'') AS doc_type, COALESCE(d.title,'') AS title "
        "FROM page_atom a LEFT JOIN doc d ON d.doc_key=a.doc_key "
        f"WHERE {' AND '.join(where)}{extra} "
        "ORDER BY CASE COALESCE(a.check_status,'') WHEN 'verified' THEN 0 ELSE 1 END, "
        "substr(COALESCE(a.known_at,''),1,10) DESC, a.page LIMIT 12", (*args, *eargs))
    if natural is not None:     # a printed point-in-time label answers the date it prints (T-242 fix 6)
        rows = [r for r in rows if _period_matches(r["period"], period)]

    def matches(label_text: str) -> bool:
        norm = _metric_key(label_text or "")
        return norm == key or norm == alias or norm.startswith(key + "_") or key in norm

    rows = [r for r in rows if (matches(r["row_label"]) or matches(f"{r['row_label']} {r['table_title']}"))
            and _atom_unit_fits(metric, r["unit"], r["scale"])]      # T-199 r2: the unit family must fit
    if not rows:
        return None
    row = rows[0]
    answer = _add_money({"value": row["value"], "unit": row["unit"], "scale": row["scale"], "value_text": row["value_text"],
                         "period": row["period"] or period, "basis": row["basis"] or None, "as_of_used": day,
                         "source": {"table": "page_atom", "doc_key": row["doc_key"], "page": row["page"],
                                    "quote": _trim(f"{row['row_label']} | {row['col_header']}: {row['value_text']} "
                                                   f"{row['unit']}".strip(), 600)},
                         "known_at": row["known_at"], "check_status": row["check_status"], "computed": None},
                        row["value"], row["unit"], row["scale"])
    alternatives = [_add_money({"value": alt["value"], "unit": alt["unit"], "period": alt["period"], "table": "page_atom",
                                "doc_key": alt["doc_key"], "page": alt["page"],
                                "note": f"read from the page, {alt['check_status']}"},
                               alt["value"], alt["unit"], alt["scale"]) for alt in rows[1:4]]
    return {"found": True, "symbol": sym, "metric": metric, "route": "atoms", "answer": answer,
            "alternatives": alternatives[:3],
            "why_this_one": "no pilot3 table holds this metric for the period; the page reader copied the figure "
                            "from the company's own table/chart page and the atom resolver resolved its period, "
                            "unit and scale",
            "provenance": _db_prov()}


def _fact_cells(sym: str, metric: str, period: str | None, day: str | None) -> dict[str, Any] | None:
    """T-189/T-199: the resolved page atom, else the page reader's raw cells, when no other table holds the metric."""
    from_atoms = _fact_atoms(sym, metric, period, day)
    if from_atoms:
        return from_atoms
    reply = cells(sym, metric, period=period, as_of=day, limit=3)
    rows = [row for row in (reply.get("rows") or []) if row.get("unit") != "change"]   # never a level
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
    names searched and up to three nearest rows.  A metric word resolves through one alias map ("profit after tax"
    -> pat, "installed capacity" -> capacity.total, "capital expenditure" -> capex) and a printed point-in-time
    period ("As on 30th Sept, 2026")
    matches the row that prints that date; a transcript number a filed results / press-release figure contradicts by
    more than 20% is served filed-first, with the call remark as an alternative carrying ``conflict: true``."""
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
        if not from_cells and key in _MEASURE_ALIASES:
            from_cells = _fact_cells(sym, _MEASURE_ALIASES[key].replace("_", " ").replace(".", " "), period, day)
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
    if not rows and "kpi" not in replies and _has_table("obs_fact"):
        rows, reply = _fact_rows("kpi", sym, key, period, bas, day, 5)
        replies["kpi"] = reply
        if rows:
            used = "kpi"
    if not rows and key in _FACT_SHARES:
        # T-242 fix 4: the printed line the period named is not held, so the share count is the answer, said plainly.
        rows, reply = _fact_rows("shares", sym, key, period, bas, day, 5)
        replies["shares"] = reply
        if rows:
            used = "shares"
    if not rows:
        from_cells = _fact_cells(sym, metric, period, day)
        if not from_cells and key in _MEASURE_ALIASES:
            from_cells = _fact_cells(sym, _MEASURE_ALIASES[key].replace("_", " ").replace(".", " "), period, day)
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
    if _scope_rank(row) >= 2:
        # T-242 fix 7: another scope's figure (industry / country / peer / customer) is never the company's answer.
        # It is still held, so it comes back labelled in ``alternatives`` and the reply says why it is not served.
        label = _scope_label(row) or "another company's figure"
        out = _fact_not_found(sym, metric, key, found, allnames, day,
                              note=f"only a figure of another scope is held for this metric and period; the reply's "
                                   f"alternatives show it as a {label}, which is not the company's own number")
        out["alternatives"] = [_fact_alt(other) for other in rows[:3]]
        return out
    if used == "fin":
        row = _fact_prefer_xbrl_annual(row, day) or row
    conflict_alt = None
    conflict_note = None
    if used in ("kpi", "fin"):
        # T-242 fix 6: a transcript number a filed results / press-release figure contradicts by > 20% is never
        # served first -- the filed value answers and the call remark is labelled ``conflict: true``.
        conflict = _fact_filed_conflict(sym, key, period, day, row)
        if conflict:
            filed_row, conflict_note = conflict
            conflict_alt = _fact_alt(row)
            conflict_alt["conflict"] = True
            conflict_alt["note"] = conflict_note
            row = filed_row
    alternatives: list[dict[str, Any]] = []
    if used == "fin":
        for alt in (row.get("alternatives") or [])[:3]:
            table, doc, page = _split_source(alt.get("provenance") or {})
            alternatives.append(_add_money({"value": alt.get("value"), "unit": alt.get("unit"), "period": row.get("period"),
                                            "basis": row.get("basis"), "table": table, "doc_key": doc, "page": page,
                                            "definition": alt.get("definition"), "filing_date": alt.get("filing_date"),
                                            "note": "another filing's printing of the same figure"},
                                           alt.get("value"), alt.get("unit"), alt.get("scale")))
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
    if conflict_alt is not None:
        alternatives = ([conflict_alt] + alternatives)[:3]
        why = f"{conflict_note}; {why}"
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


def _obs_period_clause(period: str | None) -> tuple[str, list[Any]]:
    """SQL clause matching ``obs_fact.period`` across spacing/hyphenation variants ('H1FY27' == 'H1 FY27'), and a
    printed natural date ('September 30, 2026' == '30-Sep-2026' == 'Sep-26') by its date key (T-242)."""
    kind, label = norm_period(period) if period else (None, None)
    if not label:
        return "", []
    forms: set[str] = set()
    if kind in ("Q", "H1", "H2", "FY"):
        yy = label[-2:]
        forms = {label}
        if kind == "FY":
            prev = int(yy) - 1
            forms.update({f"FY {yy}", f"FY20{yy}", f"FY 20{yy}", f"20{prev}-{yy}", f"FY20{prev}-{yy}",
                          f"FY20{prev}-20{yy}", f"20{prev}{yy}", f"FY20{prev}{yy}"})
        else:
            q_part = label[:-4]
            forms.update({f"{q_part} FY{yy}", f"{q_part}FY20{yy}", f"{q_part} FY20{yy}", f"{q_part} FY {yy}"})
    forms |= _natural_period_forms(period)
    if period:
        forms.add(str(period))       # the label as printed: "As on 30th Sept, 2026" answers itself
    if not forms:
        return " AND UPPER(COALESCE(o.period,''))=UPPER(?)", [label]
    keys = sorted({_period_key(form) for form in forms if _period_key(form)})
    col = _period_norm_sql("COALESCE(o.period,'')")
    clause = f"({col} IN ({','.join('?' * len(keys))})"
    args: list[Any] = list(keys)
    day, _ym = _natural_date(period)
    if day is not None:
        # a label prefixes the date ("Quarter ended September 30, 2026", "As on 30th Sept, 2026"): the full printed
        # day keys are matched as a suffix/prefix too, so the prefix words a label adds never hide the row.
        for key in [k for k in keys if len(k) >= 12]:
            clause += f" OR {col} LIKE '%' || ?"
            args.append(key)
    return f" AND {clause})", args


def _obs_rows(sym: str, measure: str | None = None, terms: str | None = None,
              period: str | None = None, record_type: str | None = None, status: str | None = None,
              as_of: str | None = None, limit: int = 20, measure_exact: bool = False) -> list[dict[str, Any]]:
    if not _has_table("obs_fact"):
        return []
    day = _day(as_of, "as_of")
    where = ["o.symbol=?"]
    args: list[Any] = [sym]
    if measure:
        if measure_exact:
            ex = f" AND record_type='{record_type}'" if record_type else ""
            cands = _pick("obs_fact", "measure", sym, measure, extra=ex)[0] if _has_table("obs_fact") else []
            # a contained name is a different measure when it adds a derived token (revenue -> revenue_growth_yoy)
            derived_tokens = {"growth", "pct", "pp", "change", "yoy", "qoq", "margin", "share", "ratio", "delta"}
            m_norm = _norm_measure(measure)
            m_tokens = set(m_norm.split("_"))
            # T-242 fix 3 review (Wolf): a measure code with extra movement tokens is accepted only through the
            # printed-label path below (the row prints the words asked), never from the asked words alone
            # (revenue must not reach revenue_growth_yoy).
            cands = [c for c in cands if _norm_measure(c) == m_norm
                     or not ((set(_norm_measure(c).split("_")) & derived_tokens) - m_tokens)]
            if "mix" not in m_norm and "segment" not in m_norm:
                non_mix = [c for c in cands if not c.lower().endswith(".mix")]
                if non_mix:
                    cands = non_mix
            if _has_column("obs_fact", "printed_label"):
                # T-242: the row whose printed label is the words asked is a candidate even when its measure code
                # differs ('liquid cash' -> cash_and_cash_equivalents, not only NEW:net_liquid_cash).
                printed = _period_norm_sql("COALESCE(o.printed_label,'')")
                lab = _q(f"SELECT DISTINCT o.measure FROM obs_fact o WHERE o.symbol=? AND {printed}=? "
                         + ("AND o.record_type=? " if record_type else "")
                         + "AND o.status IN ('verified','unverified')",
                         (sym, _period_key(measure), *([record_type] if record_type else ())))
                # a label that names a movement ("PAT up") may legitimately be a growth measure; a level label
                # ("Total Revenue from Operations") shares its wording with an extractor's growth row, so a derived
                # measure is not added for it.
                movement = {"up", "down", "growth", "grew", "rise", "rising", "fall", "decline", "declined",
                            "increase", "increased", "decrease", "decreased", "improved", "improvement", "yoy", "qoq"}
                allow_derived = bool(m_tokens & movement)
                cands = list(dict.fromkeys(
                    cands + [r[0] for r in lab if r[0]
                             and (allow_derived or _label_covers(measure, r[0])
                                  or not ((set(_norm_measure(r[0]).split("_")) & derived_tokens) - m_tokens))]))
            if cands:
                where.append(f"o.measure IN ({','.join('?' * len(cands))})")
                args.extend(cands)
            else:
                where.append("LOWER(o.measure)=LOWER(?)")
                args.append(measure)
        else:
            where.append("o.measure LIKE ?")
            args.append(f"%{measure}%")
    if record_type:
        where.append("o.record_type=?")
        args.append(record_type)
    if status and status.lower() in ("verified", "unverified"):
        where.append("o.status=?")
        args.append(status.lower())
    else:
        where.append("o.status IN ('verified','unverified')")
    psql, pargs = _obs_period_clause(period)
    if psql:
        where.append(psql.removeprefix(" AND "))
        args.extend(pargs)
    # terms filter in SQL: every term must hit one of the text columns, its synonyms OR-ed in (T-239)
    term_words = [w for w in re.findall(r"\w+", terms or "") if len(w) > 1]
    text_cols = [c for c in ("statement", "printed_label", "question_context", "measure", "segment", "series_title")
                 if _has_column("obs_fact", c)]
    if not text_cols:
        text_cols = ["measure"]
    if term_words:
        clause, term_args, _used = _word_groups(term_words, [f"o.{c}" for c in text_cols])
        where.append(f"({clause})")
        args.extend(term_args)
    extra, eargs = _asof(as_of, "o.known_at")
    order_parts = ["(o.status='verified') DESC"]
    order_args: list[Any] = []
    if measure and _has_column("obs_fact", "printed_label"):
        # T-242: the row whose printed label is the words asked ('liquid cash') before a fuzzy measure match
        # ('NEW:net_liquid_cash'): exact label first, then a label carrying the words, then everything else.
        asked_label = _period_key(measure)
        printed = _period_norm_sql("COALESCE(o.printed_label,'')")
        order_parts.append(f"CASE WHEN {printed}=? THEN 0 WHEN {printed} LIKE ? THEN 1 ELSE 2 END")
        order_args += [asked_label, f"%{asked_label}%"]
    if measure and not terms and _has_column("obs_fact", "segment"):
        order_parts.append("(COALESCE(o.segment,'')='') DESC")
    if _has_column("obs_fact", "doc_type"):
        order_parts.append("CASE COALESCE(o.doc_type,'') WHEN 'deck' THEN 0 WHEN 'results' THEN 1 "
                           "WHEN 'press_release' THEN 2 WHEN 'annual_report' THEN 3 "
                           "WHEN 'transcript' THEN 4 ELSE 5 END")
    order_parts.append("(COALESCE(o.period,'')<>'') DESC")
    order_parts.append("o.known_at DESC")
    if _has_column("obs_fact", "observation_id"):
        order_parts.append("o.observation_id DESC")
    rows = _q(f"SELECT o.* FROM obs_fact o WHERE {' AND '.join(where)}{extra} "
              f"ORDER BY {', '.join(order_parts)} LIMIT ?", (*args, *eargs, *order_args, _cap(limit)))
    out: list[dict[str, Any]] = []
    partial = (not measure_exact) and bool(measure)
    for r in rows:
        keys = set(r.keys())
        g = lambda k: (r[k] if k in keys else None)
        item = {
            "measure": g("measure"), "record_type": g("record_type"), "status": g("status"),
            "source": g("source"), "doc_type": g("doc_type"), "doc_key": g("doc_key"), "page": g("page"),
            "period": g("period"), "period_source": g("period_source"), "period_kind": g("period_kind"),
            "basis": g("basis"),
            "basis_source": g("basis_source"), "unit": g("unit"), "scale": g("scale"), "value": g("value"),
            "value_high": g("value_high"), "printed_label": g("printed_label"),
            "statement": g("statement"), "quote": _trim(g("statement") or g("printed_label"), 300),
            "speaker": g("speaker"), "direction": g("direction"), "question_context": g("question_context"),
            "segment": g("segment"), "geography": g("geography"), "customer": g("customer"),
            "entity_scope": g("entity_scope"), "known_at": g("known_at"),
            # T-242 fix 7: the deck/section a row was read from names a component scope ('Highlights from Sale of
            # Ethanol') that no segment column carries; scope ranking reads both.
            "series_title": g("series_title"), "group_path": g("group_path"),
            "provenance": _prov("obs_fact", f"{g('doc_key')} p{g('page')}", g("known_at"),
                                 doc_type=g("doc_type"), title=_trim((g("series_title") if "series_title" in keys else None) or '', 120),
                                 row_id=g("observation_id")),
        }
        if partial:
            item["match"] = "partial"
        if g("check_status"):   # T-242: an independent model check of an unverified row, labelled, advisory
            item["check"] = {"status": g("check_status"), "by": g("checker"), "evidence": g("check_evidence")}
            if g("check_fields"):
                try:
                    item["check"]["corrected"] = json.loads(str(g("check_fields")))
                except ValueError:
                    pass
        _add_money(item, r["value"], r["unit"], r["scale"])
        out.append(item)
    # T-242 fix 7: the company's own figure before a subsidiary / industry / country / peer / customer row, and a row
    # of the asked period kind before an off-period one (a stable sort keeps the evidence order inside each rank).
    if out and (period or _has_column("obs_fact", "entity_scope")):
        out.sort(key=lambda row: (_scope_rank(row), _period_kind_rank(row, period)))
    return out


def _obs_statement_rows(sym: str, topic: str | None = None, terms: str | None = None,
                        period: str | None = None, rank_terms: str | None = None,
                        latest: bool = False, status: str | None = None,
                        date_from: str | None = None, date_to: str | None = None,
                        as_of: str | None = None, call_docs: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch and rank ``obs_fact`` statement rows with latest, period, rank_terms, topic and status."""
    where = ["o.symbol=?", "o.record_type='statement'"]
    args: list[Any] = [sym]
    if status and status.lower() in ("verified", "unverified"):
        where.append("o.status=?")
        args.append(status.lower())
    else:
        where.append("o.status IN ('verified','unverified')")
    extra, eargs = _asof(as_of, "o.known_at")
    # T-242 fix 4: a named call (date_from == date_to) is served from its own document only.  The transcript's
    # printed call date is held on transcript_statement, not on doc, so it is read per document here; a document
    # matches when that call date OR its filing date is within 3 days of the day named.
    named_day = date_from if date_from and date_to and date_from == date_to else None
    named_at = dt.date.fromisoformat(named_day) if named_day else None
    if latest:
        where.append(f"substr(COALESCE(o.known_at,''),1,10)=(SELECT MAX(substr(COALESCE(o2.known_at,''),1,10)) "
                     f"FROM obs_fact o2 WHERE o2.symbol=? AND o2.record_type='statement'{extra.replace('o.', 'o2.')})")
        args.extend([sym, *eargs])
    doc_join = ("LEFT JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a "
                "WHERE a.symbol=o.symbol AND a.alias_key=o.doc_key), o.doc_key)") if _has_table("doc") else ""
    doc_sel = (", d.title AS doc_title, d.filing_date AS doc_filing_date, d.doc_key AS doc_resolved_key"
               if _has_table("doc") else ", '' AS doc_title, '' AS doc_filing_date, '' AS doc_resolved_key")
    # T-242 fix 4: the transcript's printed call date lives on transcript_statement, not on doc, so it is read once
    # per document here; a document matches the named call when that call date OR its filing date is within 3 days.
    call_days: dict[str, str] = {}
    if named_day and _has_table("doc") and _has_table("transcript_statement"):
        for r in _q("SELECT d.doc_key AS dk, MAX(t.call_date) AS cd FROM transcript_statement t "
                    "JOIN doc d ON d.doc_key=COALESCE((SELECT a.doc_key FROM doc_alias a WHERE a.symbol=t.symbol "
                    "AND a.alias_key=t.doc_key), t.doc_key) WHERE t.symbol=? GROUP BY 1", (sym,)):
            if r["dk"]:
                call_days[r["dk"]] = str(r["cd"] or "")[:10]
    # T-242: a call-date window names the transcript's filing date (the reply's ``call_date``), so filter on the
    # document date and fall back to known_at only when the document holds none.
    doc_day = f"COALESCE(d.filing_date, substr(COALESCE(o.known_at,''),1,10))" if _has_table("doc") \
        else "substr(COALESCE(o.known_at,''),1,10)"
    # T-242 fix 5: a named call is served from the documents its printed call date OR its filing date puts within
    # 3 days, so a call held on 2026-11-03 and filed 2026-11-10 keeps its obs_fact statements (the filing-date
    # window alone dropped them, and the Python near-day check below can only drop rows, never rescue them).
    if named_day and call_docs:
        where.append(f"(COALESCE(d.doc_key, o.doc_key) IN ({','.join('?' * len(call_docs))}) "
                     f"OR (d.doc_key IS NULL AND {doc_day} BETWEEN ? AND ?))")
        args.extend(call_docs)
        args.extend(_day_span(named_day))
        date_from = date_to = None       # the document set IS the named-call filter; no filing-date window beside it
    elif named_day:
        date_from, date_to = _day_span(named_day)
    if date_from:
        where.append(f"{doc_day} >= ?")
        args.append(date_from)
    if date_to:
        where.append(f"{doc_day} <= ?")
        args.append(date_to)
    term_words = [w for w in re.findall(r"\w+", terms or "") if len(w) > 1]
    text_cols = [c for c in ("statement", "printed_label", "question_context", "measure", "segment", "series_title")
                 if _has_column("obs_fact", c)] or ["statement", "measure"]
    if term_words:
        clause, term_args, _used = _word_groups(term_words, [f"o.{c}" for c in text_cols])
        where.append(f"({clause})")
        args.extend(term_args)
    rows = _q(f"SELECT o.*{doc_sel} FROM obs_fact o {doc_join} WHERE {' AND '.join(where)}{extra} "
              f"ORDER BY (o.status='verified') DESC, o.known_at DESC LIMIT 500", (*args, *eargs))
    # T-242: when the question or the arguments name a call date, rank the rows of the call nearest that date
    # first; with no date the newest call stays first.
    want_day = named_at or _text_day(date_from, date_to, topic, terms, rank_terms)
    plan = _topic_plan(topic) if topic else None
    _kind, plabel = norm_period(period)
    plabels: list[str] = []
    if plabel:
        base_labels = ([f"Q{q}FY{plabel[2:]}" for q in (1, 2, 3, 4)] + [plabel]) if plabel.startswith("FY") else [plabel]
        for lb in base_labels:
            plabels.append(lb.lower())
            plabels.append(re.sub(r"^([qh][1-4]|fy)(fy\d{2})$", r"\1 \2", lb.lower()))
    # T-242 fix 3: within ONE named call the ask's own words rank whichever argument a cheap model put them in
    # (rank_terms, topic or terms), and a measure that names the ask scores beside a remark that prints it, so
    # the best-matching remark comes first instead of merely the newest.  Without a named call the old order
    # (newest call first) stands, so a better-matching older call never displaces it.
    ask = rank_terms or ""
    if named_day:
        ask = " ".join(x for x in (rank_terms, topic, terms) if x)
    qwords = list(dict.fromkeys(w.lower() for w in re.findall(r"[\w₹%&\-\.]+", ask) if len(w) > 2))[:12]
    qword_alts = [([w] + [s.lower() for s in _synonyms_for(w)]) for w in qwords]
    measure_words = _measure_words(topic, terms, rank_terms) if named_day else []
    quant = bool(named_day and _ASK_QUANT.search(" ".join(x for x in (topic, terms, rank_terms) if x)))
    scored: list[dict[str, Any]] = []
    for r in rows:
        keys = set(r.keys())
        g = lambda k: (r[k] if k in keys else None)
        stmt = g("statement")
        if not stmt:
            continue
        if plan is not None and not _topic_hit(plan, stmt, g("measure")):
            continue
        call_day = call_days.get(str(g("doc_resolved_key") or g("doc_key") or ""), "")
        if named_at is not None:
            # T-242 fix 4: drop a statement of another call; the call date and the filing date both count, 3 days.
            filed_day = str(g("doc_filing_date") or "")[:10]
            if call_day or filed_day:
                if not (_near_day(call_day, named_at) or _near_day(filed_day, named_at)):
                    continue
            elif not _near_day(str(g("known_at") or "")[:10], named_at):
                continue
        say_blob = " ".join(str(x or "") for x in (stmt, g("question_context"))).lower()
        if named_day:       # T-242 fix 6: the sentence's own words rank, not the whole answer turn's
            say_blob = str(stmt or "").lower()
        measure_blob = " ".join(str(x or "") for x in (g("measure"), g("printed_label"))).lower()
        say_score = sum(1 for alts in qword_alts if any(a in say_blob for a in alts)) if qword_alts else 0
        sent_all = _sentence_hits(stmt, qwords, measure_words, quant)[0] if (named_day and qwords) else False
        measure_score = sum(1 for alts in qword_alts if any(a in measure_blob for a in alts)) if qword_alts else 0
        t_score = say_score + measure_score
        p_rank = 0
        if plabels:
            p_blob = " ".join(str(x or "") for x in (g("period"), stmt, g("doc_title"))).lower()
            p_norm = p_blob.replace("-", "").replace(" ", "")
            p_hit = any(lb in p_blob or lb.replace(" ", "") in p_norm for lb in plabels)
            p_rank = 0 if p_hit else 1
        s_rank = 0 if g("status") == "verified" else 1
        day_rank = 0
        if want_day is not None:
            row_day = str(call_day or g("doc_filing_date") or (g("known_at") or ""))[:10]
            try:
                day_rank = abs((dt.date.fromisoformat(row_day) - want_day).days)
            except ValueError:
                day_rank = 10 ** 4
        title = _trim(g("doc_title") or g("series_title") or "", 120)
        doc_type = _DOC_TYPES.get(str(g("doc_type") or "").lower(), g("doc_type"))
        item: dict[str, Any] = {
            "call_date": (g("doc_filing_date") or g("known_at") or "")[:10],
            "call_period": g("period") or None,
            "speaker": g("speaker"), "role": None, "section": None,
            "topics": g("measure"), "entities": None, "period_discussed": g("period") or None,
            "answer_turn": None, "match": "obs", "status": g("status"), "source": "obs_fact",
            "entity_scope": g("entity_scope"), "page": g("page"), "doc_key": g("doc_key"), "doc_type": doc_type,
            # T-242 fix 9: with the question's own words, a named call's statement is read to its end, because the
            # asked sentence may be its last one (ARCIL's "Other expenses ..." is the final sentence of a long
            # paragraph); the sentence scorer serves only the sentence it picks, so the reply stays short.
            "quote": _trim(stmt, 1600 if (named_day and (rank_terms or terms)) else QUOTE_CHARS),
            "provenance": _prov("obs_fact", f"{g('doc_key')} p{g('page')}", g("known_at"),
                                title=title, doc_type=doc_type, row_id=g("observation_id")),
            "_term_score": t_score,
        }
        if g("question_context"):
            item["question_context"] = _trim(g("question_context"), 300)
        scored.append({"_all": sent_all, "_item": item, "_s_rank": s_rank, "_day": day_rank, "_p": p_rank,
                       "_say": say_score, "_measure": measure_score})
    if scored:
        if named_day and qwords:
            # T-242 fix 7: each ask word is weighted by how rare it is in THIS reply, then the sentence score decides
            weights = _ask_weights([[rec["_item"]] for rec in scored], qwords)
            for rec in scored:
                rec["_score"] = _sentence_hits(str(rec["_item"].get("quote") or ""), qwords, measure_words, quant,
                                               weights)[1]
        scored.sort(key=lambda rec: (0 if (named_day and rec["_all"]) else 1,
                                     -rec["_score"] if (named_day and qwords) else 0,
                                     rec["_s_rank"], _scope_rank(rec["_item"]), rec["_day"], rec["_p"],
                                     -rec["_say"], -rec["_measure"]))
    return [rec["_item"] for rec in scored]


def _obs_fin_rows(sym, measure, period, bas, as_of, cap):
    rows = _obs_rows(sym, measure=measure, period=period, record_type="number", as_of=as_of, limit=max(cap * 3, 20),
                     measure_exact=True)
    rows.sort(key=lambda r: _ask_row_rank(r, measure, period))     # T-242 fix 7: company / asked period / unit first
    verified_keys = {(r["measure"], r["period"], r["basis"] or "not_stated")
                     for r in rows if r.get("status") == "verified"}
    out = []
    for r in rows:
        rb = r.get("basis") or "not_stated"
        if bas and rb not in ("not_stated",) and rb != bas:
            continue
        if r.get("status") != "verified" and (r["measure"], r["period"], rb) in verified_keys:
            continue
        row = {"measure": r["measure"], "period": r["period"], "basis": rb,
               "definition": "observed", "value": r["value"], "unit": r["unit"], "scale": r["scale"] or 1.0,
               "status": r["status"], "check_status": r["status"], "source": "obs_fact",
               "doc_key": r["doc_key"], "page": r["page"], "quote": r.get("quote"),
               "period_source": r["period_source"], "basis_source": r["basis_source"], "known_at": r["known_at"],
               "period_kind": r.get("period_kind"), "entity_scope": r.get("entity_scope"),
               "series_title": r.get("series_title"), "group_path": r.get("group_path"),
               "segment": r.get("segment"), "provenance": r["provenance"]}
        row["_table"], row["_known_at"], row["_rowid"], row["_check"] = "obs_fact", r["known_at"], None, r["status"]
        _add_money(row, r["value"], r["unit"], r["scale"])
        out.append(row)
    return out[:cap]


def _obs_kpi_rows(sym, kpi, period, as_of, cap, basis=None):
    rows = _obs_rows(sym, measure=kpi, period=period, record_type="number", as_of=as_of, limit=max(cap * 3, 20),
                     measure_exact=True)
    if not rows:
        words = [w for w in re.split(r"[\s_.\-]+", str(kpi or "").strip().lower()) if len(w) > 1]
        if len(words) >= 2:
            cand = _obs_rows(sym, terms=" ".join(words), period=period, record_type="number", as_of=as_of,
                             limit=max(cap * 3, 20))
            derived = ("growth", "_pct", "_pp", "change", "_yoy", "_qoq", "delta")
            k_low = str(kpi or "").lower()
            rows = [r for r in cand
                    if not any(d in str(r.get("measure") or "").lower() and d not in k_low for d in derived)]
    rows.sort(key=lambda r: _ask_row_rank(r, kpi, period))          # T-242 fix 7: company / asked period / unit first
    out = []
    for r in rows:
        rb = r.get("basis") or "not_stated"
        if basis and rb not in ("not_stated",) and rb != basis:
            continue
        row = {"metric": r["measure"], "dimension": "total", "value": r["value"], "unit": r["unit"],
               "scale": r["scale"] or 1.0, "period": r["period"], "basis": rb,
               "entity": sym, "segment": r.get("segment") or None,
               "raw_label": r.get("printed_label"), "quote": r.get("quote"),
               "status": r["status"], "check_status": r["status"], "source": "obs_fact",
               "doc_key": r["doc_key"], "page": r["page"],
               "period_source": r["period_source"], "basis_source": r["basis_source"], "known_at": r["known_at"],
               "period_kind": r.get("period_kind"), "entity_scope": r.get("entity_scope"),
               "series_title": r.get("series_title"), "group_path": r.get("group_path"),
               "provenance": r["provenance"]}
        _add_money(row, r["value"], r["unit"], r["scale"])
        out.append(row)
    return out[:cap]


def obs(symbol: str, measure: str | None = None, terms: str | None = None, period: str | None = None,
        record_type: str | None = None, status: str | None = None, as_of: str | None = None,
        limit: int = 20) -> dict[str, Any]:
    sym = resolve_symbol(symbol)
    if not _has_table("obs_fact"):
        return _reply(sym, [], "pilot3_obs", as_of=_day(as_of, "as_of"),
                      nearest=" ".join(x for x in (measure, terms) if x), nearest_as_of=as_of)
    rows = _obs_rows(sym, measure=measure, terms=terms, period=period, record_type=record_type,
                     status=status, as_of=as_of, limit=limit)
    return _reply(sym, rows, "pilot3_obs", as_of=_day(as_of, "as_of"),
                  nearest=" ".join(x for x in (measure, terms) if x), nearest_as_of=as_of,
                  expansions_matched=_expansions_hit(terms, rows) or None)


def events(symbol: str, kind: str | None = None, as_of: str | None = None, limit: int = 50) -> dict[str, Any]:
    sym = resolve_symbol(symbol)
    if not _has_table("filing_event"):
        return _reply(sym, [], "pilot3_events", as_of=_day(as_of, "as_of"))
    day = _day(as_of, "as_of")
    where = ["symbol=?"]
    args: list[Any] = [sym]
    if kind:
        where.append("kind=?")
        args.append(kind)
    extra, eargs = _asof(as_of, "known_at")
    rows = _q(f"SELECT * FROM filing_event WHERE {' AND '.join(where)}{extra} "
              f"ORDER BY COALESCE(filing_date, known_at) DESC LIMIT ?",
              (*args, *eargs, _cap(limit)))
    out = [dict(r) for r in rows]
    return _reply(sym, out, "pilot3_events", as_of=day)
