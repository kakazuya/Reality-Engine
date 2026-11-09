"""pilot3_ratings: credit-rating rationale text and instrument actions from the outside-doc ratings store (T-139).

``reality_engine.ingestion.rating_rationale_load`` writes the store: one ``outside_doc`` row per fetched
rationale (the whole text verbatim), plus ``rating_doc`` (symbol, agency, dates), ``rating_action`` (every
instrument row the text prints) and ``rating_section`` (rationale, drivers, strengths, weaknesses,
sensitivities, liquidity, outlook — verbatim).

``REALITY_RATINGS_DB`` names the store; the default is ``D:/RealityEngine/outside_doc/ratings.db``.  Read-only
(``core.connect_ro``).  ``as_of`` is point in time on ``known_at`` (the day the rationale became public: its
printed press-release date, never earlier than the index date), so a later rating action never shows up in an
earlier answer.  Every row carries provenance: agency, url, rating date and known_at.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import core
from core import DataError

_DEFAULT = Path("D:/RealityEngine/outside_doc/ratings.db")
MAX_LIMIT = 20
SECTION_CHARS = 3000
SECTIONS = ("rationale", "drivers", "strengths", "weaknesses", "sensitivities", "liquidity", "outlook")
_SECTION_ALIASES = {
    "rationale": "rationale", "key rating drivers": "rationale", "rating rationale": "rationale",
    "drivers": "drivers", "key rating drivers and their description": "drivers",
    "strength": "strengths", "strengths": "strengths", "key strengths": "strengths", "credit strengths": "strengths",
    "weakness": "weaknesses", "weaknesses": "weaknesses", "key weaknesses": "weaknesses",
    "credit challenges": "weaknesses", "challenges": "weaknesses",
    "sensitivity": "sensitivities", "sensitivities": "sensitivities", "rating sensitivities": "sensitivities",
    "rating sensitivity factors": "sensitivities", "triggers": "sensitivities", "rating triggers": "sensitivities",
    "liquidity": "liquidity", "liquidity position": "liquidity", "outlook": "outlook",
}
_SHORT_TERM = re.compile(r"A[1-4]\+?$")


def db_path() -> Path:
    env = os.environ.get("REALITY_RATINGS_DB")
    return Path(env) if env else _DEFAULT


def _connect() -> sqlite3.Connection:
    path = db_path()
    if not path.is_file():
        raise DataError("ratings_db_missing", f"the ratings store is not at {path}; build it with "
                        "python -m reality_engine.ingestion.rating_rationale_load --src <folder> --out <db> "
                        "(or point REALITY_RATINGS_DB at a build)")
    con = core.connect_ro(path, timeout_s=core.READ_TIMEOUT_S)
    con.row_factory = sqlite3.Row
    return con


def _db_prov() -> dict[str, Any]:
    path = db_path()
    built = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime)) if path.exists() else None
    return {"db": "ratings", "path": str(path), "read_only": True, "built": built}


def _day(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise DataError("bad_date", f"as_of must be YYYY-MM-DD, got {value!r}")


def _section(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    text = re.sub(r"\s+", " ", str(value).strip().lower())
    if text in _SECTION_ALIASES:
        return _SECTION_ALIASES[text]
    for name in SECTIONS:
        if name in text:
            return name
    raise DataError("bad_section", f"section must be one of {', '.join(SECTIONS)} (got {value!r})")


def _resolve(con: sqlite3.Connection, symbol: str) -> str:
    """A symbol, BSE code, ISIN or name of a company the store holds; anything else is a DataError."""
    text = (symbol or "").strip()
    if not text:
        raise DataError("bad_symbol", "symbol is required")
    known = {str(row[0]).upper() for row in con.execute("SELECT DISTINCT symbol FROM rating_doc")}
    if text.upper() in known:
        return text.upper()
    for candidate in _candidates(text):
        if candidate in known:
            return candidate
    raise DataError(
        "not_in_ratings",
        f"{symbol!r} has no rating rationale in {db_path()}: the store holds {len(known)} compan(ies) "
        f"({', '.join(sorted(known))})",
    )


def _candidates(text: str) -> list[str]:
    out: list[str] = []
    try:  # the shared resolver (main data root) knows BSE codes, ISINs and names
        ident = core.resolve_one(text)
        for key in ("nse_symbol", "bse_symbol"):
            if ident.get(key):
                out.append(str(ident[key]).upper())
    except Exception:
        pass
    try:  # the pilot store's resolver knows names like HAVELLS INDIA
        import lookups_pilot3 as p3
        out.append(p3.resolve_symbol(text))
    except Exception:
        pass
    return out


def _long_term(rating: str) -> bool:
    """A long-term letter grade (AAA/AA/A/BBB ...) rather than a short-term A1+/A2+."""
    return not _SHORT_TERM.search((rating or "").strip())


def _prov(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    agency = row["agency"] or ""
    return {"table": "rating_action", "source": f"{agency} rationale {row['rating_date'] or ''}".strip(),
            "agency": agency, "url": row["url"] if "url" in row.keys() else None,
            "rating_date": row["rating_date"], "known_at": row["known_at"]}


def ratings(symbol: str, as_of: str | None = None, agency: str | None = None, section: str | None = None,
            limit: int = 20) -> dict[str, Any]:
    """Every rating action a company's fetched rationales print, known by ``as_of``, with the key sections."""
    day = _day(as_of)
    wanted = _section(section)
    try:
        cap = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        cap = MAX_LIMIT
    con = _connect()
    try:
        try:
            sym = _resolve(con, symbol)
        except DataError as exc:
            if getattr(exc, "code", "") != "not_in_ratings":
                raise
            held = sorted({str(row[0]).upper() for row in con.execute("SELECT DISTINCT symbol FROM rating_doc")})
            return {"found": False, "symbol": str(symbol or "").upper(), "as_of": day, "n": 0, "actions": [],
                    "documents": [], "available_symbols": held, "hint": str(exc), "provenance": _db_prov()}
        sql = ("SELECT d.doc_id, d.symbol, d.agency, d.rating_date, d.known_at, d.title, d.url "
               "FROM rating_doc d WHERE d.symbol = ?")
        params: list[Any] = [sym]
        if day:
            sql += " AND d.known_at IS NOT NULL AND substr(d.known_at, 1, 10) <= ?"
            params.append(day)
        if agency:
            sql += " AND upper(d.agency) = ?"
            params.append(str(agency).strip().upper())
        sql += " ORDER BY d.rating_date DESC, d.doc_id DESC LIMIT ?"
        params.append(cap)
        docs = [dict(row) for row in con.execute(sql, tuple(params))]
        if not docs:
            reply = {"found": False, "symbol": sym, "as_of": day, "agency": agency, "n": 0, "actions": [],
                     "documents": [], "provenance": _db_prov()}
            held = [dict(row) for row in con.execute(
                "SELECT agency, MAX(rating_date) AS latest, COUNT(*) AS docs, MIN(known_at) AS first_known "
                "FROM rating_doc WHERE symbol = ? GROUP BY agency ORDER BY agency", (sym,))]
            reply["held"] = held
            reply["hint"] = (f"no {sym} rationale known by {day}" if day else f"no {sym} rationale") + \
                (f" for agency {agency}" if agency else "") + "; 'held' lists the agency/date coverage"
            return reply
        ids = [doc["doc_id"] for doc in docs]
        marks = ",".join("?" * len(ids))
        actions = [dict(row) for row in con.execute(
            f"SELECT a.doc_id, a.agency, a.instrument, a.rating, a.outlook, a.action, a.amount_crore, "
            f"a.rating_date, d.known_at, d.url FROM rating_action a JOIN rating_doc d ON d.doc_id = a.doc_id "
            f"WHERE a.doc_id IN ({marks}) ORDER BY d.rating_date DESC, a.doc_id DESC, a.rowid", ids)]
        sections: dict[int, dict[str, str]] = {}
        for row in con.execute(
                f"SELECT doc_id, section, text FROM rating_section WHERE doc_id IN ({marks}) ORDER BY doc_id, section",
                ids):
            if wanted and row["section"] != wanted:
                continue
            sections.setdefault(row["doc_id"], {})[row["section"]] = row["text"]
        latest: dict[str, dict[str, Any]] = {}
        for action in actions:
            entry = latest.get(action["agency"])
            action_day = action["rating_date"] or ""
            if entry is None or (action_day, action["doc_id"]) > (entry["rating_date"] or "", entry["doc_id"]):
                latest[action["agency"]] = {**action}
        for name, action in list(latest.items()):
            newest = (action["rating_date"] or "", action["doc_id"])
            same = [a for a in actions
                    if a["agency"] == name and (a["rating_date"] or "", a["doc_id"]) == newest]
            graded = [a for a in same if _long_term(a["rating"])]
            if graded:
                latest[name] = {**graded[0]}
        for action in actions:
            action["provenance"] = _prov(action)
        for doc in docs:
            body = sections.get(doc["doc_id"], {})
            doc["sections"] = {key: (text if len(text) <= SECTION_CHARS
                                     else text[:SECTION_CHARS].rstrip() + " …")
                               for key, text in body.items()}
            doc["section_names"] = sorted(body)
            doc["provenance"] = {"table": "rating_doc", "agency": doc["agency"],
                                 "source": doc["url"], "rating_date": doc["rating_date"],
                                 "known_at": doc["known_at"]}
        reply = {
            "found": True, "symbol": sym, "as_of": day, "agency": agency, "section": wanted,
            "n": len(docs), "actions": actions, "documents": docs, "latest_by_agency": latest,
            "provenance": _db_prov(),
        }
        if wanted and not any(doc["sections"] for doc in docs):
            reply["hint"] = (f"none of these rationales prints a {wanted!r} section; section_names on each "
                             "document lists what it does print")
        return reply
    except core.QueryTimeout as exc:
        raise DataError("query_timeout", str(exc))
    except sqlite3.DatabaseError as exc:
        raise DataError("sql_error", f"{type(exc).__name__}: {exc}")
    finally:
        con.close()
