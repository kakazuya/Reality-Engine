"""Point-in-time theme universes.

``universe(theme, as_of=None, min_weight=0.01)`` reads
``equity_intelligence.db:universe_membership`` (written by
``reality_engine/scripts/build_universe_membership.py``) and returns the companies
that were in the theme on ``as_of`` with their weight and evidence.  Nothing is
hard-coded here: the builder derives membership from the data and keeps the
``valid_from`` / ``valid_to`` intervals.

A member is either *weighted* (a measured revenue share) or explicitly *unweighted*
(``weight_source`` = ``industry`` / ``curated``); there is no zero weight, so
``members`` holds the weighted rows sorted by weight and ``unweighted`` the rest.
Rows keyed in ``substrate_quarantine`` are excluded (AGENTS.md rule 13).
"""
from __future__ import annotations

import datetime as dt
import difflib
import sqlite3
from pathlib import Path
from typing import Any

import yaml

import core

THEMES_PATH = Path(__file__).with_name("universes.yaml")
#: A revenue-mix share below this is noise, not a theme weight.
DEFAULT_MIN_WEIGHT = 0.01
_BUILD_HINT = ("no build yet; run: python -m reality_engine.scripts.build_universe_membership "
               "(or point --db at a built copy)")


def themes() -> dict[str, Any]:
    """Theme definitions from universes.yaml ({} when the file is missing)."""
    try:
        raw = yaml.safe_load(THEMES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return raw.get("themes") or {}


def _known_themes(con: sqlite3.Connection) -> list[str]:
    known = set(themes())
    try:
        known |= {str(r[0]) for r in con.execute("SELECT DISTINCT theme FROM universe_membership")}
    except sqlite3.DatabaseError:
        pass
    return sorted(known)


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    try:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone() is not None
    except sqlite3.DatabaseError:
        return False


def _quarantined(con: sqlite3.Connection) -> set[str]:
    """row_key set from ``substrate_quarantine`` (empty when the table is absent)."""
    if not _table_exists(con, "substrate_quarantine"):
        return set()
    try:
        return {str(r[0]) for r in con.execute("SELECT DISTINCT row_key FROM substrate_quarantine")
                if r[0] is not None}
    except sqlite3.DatabaseError:
        return set()


def _symbols(con: sqlite3.Connection, isins: list[str]) -> dict[str, str]:
    """ISIN -> symbol, current master first, industry snapshot as fallback."""
    if not isins:
        return {}
    out: dict[str, str] = {}
    for table, sym_col in (("master_companies", "nse_symbol"), ("company_industry", "symbol")):
        if not _table_exists(con, table):
            continue
        try:
            cols = {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")}
            if "isin" not in cols or sym_col not in cols:
                continue
            marks = ",".join("?" for _ in isins)
            for isin, symbol in con.execute(
                f"SELECT isin, {sym_col} FROM {table} WHERE isin IN ({marks})", isins
            ):
                if isin not in out and symbol:
                    out[str(isin)] = str(symbol)
        except sqlite3.DatabaseError:
            continue
    return out


def _last_build(con: sqlite3.Connection) -> dt.date | None:
    stamps: list[str] = []
    if _table_exists(con, "universe_membership_runs"):
        try:
            stamps += [str(r[0]) for r in con.execute("SELECT built_at FROM universe_membership_runs")]
        except sqlite3.DatabaseError:
            pass
    if _table_exists(con, "universe_membership"):
        try:
            stamps += [str(r[0]) for r in con.execute("SELECT DISTINCT built_at FROM universe_membership")]
        except sqlite3.DatabaseError:
            pass
    dates = []
    for stamp in stamps:
        try:
            dates.append(dt.date.fromisoformat(stamp[:10]))
        except ValueError:
            continue
    return max(dates) if dates else None


def _not_built(key: str, as_of: dt.date) -> dict[str, Any]:
    """A theme the builder knows but has written no rows for is not an empty answer."""
    return {
        "theme": key, "found": False, "as_of": as_of.isoformat(),
        "members": [], "unweighted": [], "count": 0, "closest_themes": [key],
        "stale_days": None,
        "error": {"code": "not_built",
                  "message": f"theme {key!r} is defined but has no membership rows; {_BUILD_HINT}"},
        "note": _BUILD_HINT,
        "provenance": core.provenance("equity_intelligence", []),
    }


def universe(theme: str, as_of: str | None = None,
             min_weight: float | None = DEFAULT_MIN_WEIGHT) -> dict[str, Any]:
    """Companies in a theme on a date.

    ``members`` are the weighted ones (``weight >= min_weight``) sorted by weight;
    ``unweighted`` are the industry / curated members, which have no revenue share and
    therefore no weight to filter on.
    """
    query = (theme or "").strip()
    if not query:
        raise core.DataError("bad_query", "universe() needs a theme name")
    as_of_d = core._parse_date(as_of, "as_of") or dt.date.today()
    try:
        min_weight = DEFAULT_MIN_WEIGHT if min_weight is None else float(min_weight)
    except (TypeError, ValueError):
        raise core.DataError("bad_weight", "min_weight must be a number")

    con = core.connect_sqlite("equity_intelligence")
    known = _known_themes(con)
    key = query.lower().replace("-", " ").replace(" ", "_")
    if key not in known:
        close = difflib.get_close_matches(key, known, n=5, cutoff=0.2)
        return {
            "theme": query,
            "found": False,
            "as_of": as_of_d.isoformat(),
            "closest_themes": close or known,
            "members": [],
            "unweighted": [],
            "count": 0,
            "error": {"code": "unknown_theme",
                      "message": f"unknown theme {query!r}; known: {', '.join(known)}" if known else
                                 "no themes defined (universes.yaml missing)"},
            "provenance": core.provenance("equity_intelligence",
                                          ["universe_membership", "universe_membership_runs"]),
        }

    if not _table_exists(con, "universe_membership"):
        return _not_built(key, as_of_d)

    try:
        rows = con.execute(
            "SELECT theme, isin, symbol, weight, weight_source, method, valid_from, valid_to, "
            "evidence_id, evidence_quote, pivot FROM universe_membership "
            "WHERE theme = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to = '' OR valid_to > ?) "
            "ORDER BY COALESCE(weight, -1) DESC, symbol, isin",
            (key, as_of_d.isoformat(), as_of_d.isoformat()),
        ).fetchall()
        # Known theme with no rows at all: the build never covered it.  A theme with rows
        # but none valid on this date is a real empty answer.
        built = con.execute(
            "SELECT 1 FROM universe_membership WHERE theme = ? LIMIT 1", (key,)
        ).fetchone() is not None
    except sqlite3.DatabaseError:
        rows, built = [], False
    if not built:
        return _not_built(key, as_of_d)

    blocked = _quarantined(con)
    rows = [row for row in rows if str(row[1]) not in blocked]
    missing = [str(r[1]) for r in rows if not r[2]]
    symbols = _symbols(con, list(dict.fromkeys(missing)))
    members, unweighted = [], []
    for row in rows:
        isin = str(row[1])
        weight = None if row[3] is None else round(float(row[3]), 6)
        member = {
            "symbol": row[2] or symbols.get(isin, ""),
            "isin": isin,
            "weight": weight,
            "weight_source": row[4] or row[5] or "",
            "method": row[5] or "",
            "since": row[6] or "",
            "until": row[7] or None,
            "evidence_id": row[8] or "",
            "evidence_quote": row[9] or "",
            "pivot": bool(row[10]),
        }
        if weight is None:
            unweighted.append(member)
        elif weight >= min_weight:
            members.append(member)

    last = _last_build(con)
    label = (themes().get(key) or {}).get("label", key)
    return {
        "theme": key,
        "label": label,
        "found": True,
        "as_of": as_of_d.isoformat(),
        "count": len(members) + len(unweighted),
        "weighted_count": len(members),
        "unweighted_count": len(unweighted),
        "min_weight": min_weight,
        "members": members,
        "unweighted": unweighted,
        "last_built": last.isoformat() if last else None,
        "stale_days": (dt.date.today() - last).days if last else None,
        "note": _BUILD_HINT if last is None else None,
        "provenance": core.provenance("equity_intelligence",
                                      ["universe_membership", "universe_membership_runs"]),
    }
