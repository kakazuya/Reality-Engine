"""Point-in-time theme universes.

``universe(theme, as_of=None, min_weight=0)`` reads
``equity_intelligence.db:universe_membership`` (written by
``reality_engine/scripts/build_universe_membership.py``) and returns the companies
that were in the theme on ``as_of`` with their weight and evidence.  Nothing is
hard-coded here: the builder derives membership from the data and keeps the
``valid_from`` / ``valid_to`` intervals.
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


def universe(theme: str, as_of: str | None = None, min_weight: float = 0.0) -> dict[str, Any]:
    """Companies in a theme on a date, sorted by weight, each with evidence."""
    query = (theme or "").strip()
    if not query:
        raise core.DataError("bad_query", "universe() needs a theme name")
    as_of_d = core._parse_date(as_of, "as_of") or dt.date.today()
    try:
        min_weight = float(min_weight)
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
            "count": 0,
            "error": {"code": "unknown_theme",
                      "message": f"unknown theme {query!r}; known: {', '.join(known)}" if known else
                                 "no themes defined (universes.yaml missing)"},
            "provenance": core.provenance("equity_intelligence",
                                          ["universe_membership", "universe_membership_runs"]),
        }

    if not _table_exists(con, "universe_membership"):
        return {
            "theme": key, "found": False, "as_of": as_of_d.isoformat(),
            "members": [], "count": 0, "closest_themes": [key], "stale_days": None,
            "note": _BUILD_HINT,
            "provenance": core.provenance("equity_intelligence", []),
        }

    try:
        rows = con.execute(
            "SELECT theme, isin, symbol, weight, method, valid_from, valid_to, evidence_id, "
            "evidence_quote, pivot FROM universe_membership "
            "WHERE theme = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to = '' OR valid_to >= ?) "
            "AND COALESCE(weight, 0) >= ? ORDER BY COALESCE(weight, 0) DESC, symbol, isin",
            (key, as_of_d.isoformat(), as_of_d.isoformat(), min_weight),
        ).fetchall()
    except sqlite3.DatabaseError:
        rows = []

    missing = [str(r[1]) for r in rows if not r[2]]
    symbols = _symbols(con, list(dict.fromkeys(missing)))
    members = []
    for row in rows:
        isin = str(row[1])
        members.append({
            "symbol": row[2] or symbols.get(isin, ""),
            "isin": isin,
            "weight": round(float(row[3] or 0.0), 6),
            "method": row[4] or "",
            "since": row[5] or "",
            "until": row[6] or None,
            "evidence_id": row[7] or "",
            "evidence_quote": row[8] or "",
            "pivot": bool(row[9]),
        })

    last = _last_build(con)
    label = (themes().get(key) or {}).get("label", key)
    return {
        "theme": key,
        "label": label,
        "found": True,
        "as_of": as_of_d.isoformat(),
        "count": len(members),
        "members": members,
        "last_built": last.isoformat() if last else None,
        "stale_days": (dt.date.today() - last).days if last else None,
        "note": _BUILD_HINT if last is None else None,
        "provenance": core.provenance("equity_intelligence",
                                      ["universe_membership", "universe_membership_runs"]),
    }
