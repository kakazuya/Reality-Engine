"""Rumor corroboration scorer over Tier-2 FTS rows (news-feed Tier-2).

READ-ONLY vs the DB: this module only issues SELECTs (via the caller's
``DatabaseManager``/``Repository`` handle or the default manager). It never
writes, never synthesizes rows -- a miss returns empty lists / zero counts.
Deterministic, no network.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("reality_engine.rumor_scorer")

# Claim-keyword stopwords: generic market chatter tokens that carry no signal.
STOPWORDS = {
    "stock", "market", "share", "price", "target", "breakout",
    "above", "below", "strong", "buying", "selling", "today",
    "tomorrow", "nifty", "sensex", "india", "ltd", "limited",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_TIER2_QUERY = (
    "SELECT chunk_id, symbol, isin, source_type, document_date, document_text"
    " FROM intelligence_fts"
    " WHERE UPPER(source_type) LIKE '%TELEGRAM%'"
    " OR UPPER(source_type) LIKE '%YOUTUBE%'"
    " ORDER BY document_date DESC LIMIT 2000"
)

_TIER0_HIT_QUERY = (
    "SELECT 1 FROM corporate_documents"
    " WHERE symbol = ? AND doc_type = 'ANNOUNCEMENT'"
    " AND ABS(julianday(doc_date) - julianday(?)) * 24.0 <= ? LIMIT 1"
)


def claim_keywords(text: Any) -> set:
    """Lowercase alphanumeric tokens len>=4 minus STOPWORDS; empty -> set()."""
    tokens = _TOKEN_RE.findall(str(text or "").lower())
    return {t for t in tokens if len(t) >= 4 and t not in STOPWORDS}


def _resolve_manager(db: Any) -> Any:
    """Accept a DatabaseManager, a Repository, or None (default manager)."""
    if db is None:
        from reality_engine.db.database import db_manager as _default_mgr

        return _default_mgr
    if hasattr(db, "session"):
        return db
    inner = getattr(db, "db", None)
    if inner is not None and hasattr(inner, "session"):
        return inner
    return db


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _rows(conn: Any, query: str, params: tuple) -> List[Dict[str, Any]]:
    try:
        cur = conn.execute(query, params)
        return [{k: row[k] for k in row.keys()} for row in cur.fetchall()]
    except Exception as exc:  # fail-closed: miss -> empty, never raise
        logger.warning("rumor_scorer query miss: %s", exc)
        return []


def _tier0_hit(conn: Any, symbols: List[str], first_seen: str,
               window_hours: float) -> bool:
    """True if any symbol has an ANNOUNCEMENT within window_hours of first_seen."""
    if not first_seen or not symbols:
        return False
    for sym in symbols:
        try:
            cur = conn.execute(_TIER0_HIT_QUERY, (sym, first_seen, window_hours))
            if cur.fetchone() is not None:
                return True
        except Exception as exc:  # fail-closed per symbol: skip, try next
            logger.warning("rumor_scorer tier0 miss for %s: %s", sym, exc)
            continue
    return False


def corroborate(
    symbol: Optional[str] = None,
    since: Optional[str] = None,
    window_hours: Any = 72,
    min_confirm: Any = 2,
    db: Any = None,
) -> List[Dict[str, Any]]:
    """Cluster Tier-2 FTS rows into corroborated rumor claims.

    Rows sharing >=2 claim keywords AND the same symbol form a claim
    cluster (when ``symbol=''`` is passed explicitly, rows group across
    symbols into any-symbol clusters). ``sources`` is the sorted distinct
    source_types; ``status`` is ``'CONFIRMED'`` when ``tier0_hit`` or
    ``n_sources >= min_confirm``, else ``'UNCONFIRMED'``. Fail-closed.
    """
    try:
        window_hours = max(0.0, float(window_hours))
    except (TypeError, ValueError):
        window_hours = 72.0
    try:
        min_confirm = max(1, int(min_confirm))
    except (TypeError, ValueError):
        min_confirm = 2

    sym_filter = None if symbol is None else _norm_symbol(symbol)
    cross_symbol = symbol is not None and _norm_symbol(symbol) == ""
    since_s = str(since).strip() if since else None

    try:
        mgr = _resolve_manager(db)
        with mgr.session() as conn:
            rows = _rows(conn, _TIER2_QUERY, ())

            if sym_filter:
                rows = [r for r in rows
                        if _norm_symbol(r.get("symbol")) == sym_filter]
            if since_s:
                rows = [r for r in rows
                        if (r.get("document_date") or "") >= since_s]
            if not rows:
                return []

            keys = [claim_keywords(r.get("document_text")) for r in rows]
            syms = [_norm_symbol(r.get("symbol")) for r in rows]

            # Union-find: link pairs sharing >=2 keywords (+ same symbol
            # unless cross-symbol mode). Rows with <2 keywords never link.
            parent = list(range(len(rows)))

            def find(a: int) -> int:
                while parent[a] != a:
                    parent[a] = parent[parent[a]]
                    a = parent[a]
                return a

            for i in range(len(rows)):
                if len(keys[i]) < 2:
                    continue
                for j in range(i + 1, len(rows)):
                    if len(keys[j]) < 2:
                        continue
                    if not cross_symbol and syms[i] != syms[j]:
                        continue
                    if len(keys[i] & keys[j]) >= 2:
                        ri, rj = find(i), find(j)
                        if ri != rj:
                            parent[rj] = ri

            clusters: Dict[int, List[int]] = {}
            for i in range(len(rows)):
                clusters.setdefault(find(i), []).append(i)

            out: List[Dict[str, Any]] = []
            for members in clusters.values():
                # members inherit row order (document_date DESC): [0] is newest.
                newest = rows[members[0]]
                dates = [rows[m].get("document_date") or "" for m in members]
                dated = [d for d in dates if d]
                first_seen = min(dated) if dated else ""
                sources = sorted({str(rows[m].get("source_type") or "")
                                  for m in members if rows[m].get("source_type")})
                member_syms = sorted({syms[m] for m in members if syms[m]})
                hit = _tier0_hit(conn, member_syms, first_seen, window_hours)
                n_sources = len(sources)
                status = ("CONFIRMED" if (hit or n_sources >= min_confirm)
                          else "UNCONFIRMED")
                text = str(newest.get("document_text") or "")
                out.append({
                    "symbol": member_syms[0] if (member_syms and not cross_symbol)
                    else (syms[members[0]] if not cross_symbol else ""),
                    "claim": text[:280],
                    "first_seen": first_seen,
                    "sources": sources,
                    "n_sources": n_sources,
                    "tier0_hit": hit,
                    "status": status,
                })

            out.sort(key=lambda d: (d["first_seen"], d["symbol"], d["claim"]),
                     reverse=True)
            return out
    except Exception as exc:  # fail-closed: any DB failure -> []
        logger.warning("rumor_scorer corroborate miss: %s", exc)
        return []


def score_rumor(
    symbol: str,
    target_date: str,
    db: Any = None,
) -> Dict[str, Any]:
    """Score rumors for ``symbol`` in the default 72h window ending ``target_date``.

    Calls :func:`corroborate` with ``since`` = target_date minus 3 days and
    keeps clusters with ``first_seen`` on/before ``target_date``.
    Fail-closed: bad date or DB miss -> zero counts.
    """
    sym = _norm_symbol(symbol)
    target = str(target_date or "").strip()
    empty: Dict[str, Any] = {
        "symbol": sym,
        "target_date": target,
        "rumors": [],
        "n_confirmed": 0,
        "n_unconfirmed": 0,
    }
    try:
        target_dt = datetime.strptime(target, "%Y-%m-%d").date()
    except ValueError:
        logger.warning("rumor_scorer bad target_date=%r", target_date)
        return empty
    since_s = (target_dt - timedelta(days=3)).isoformat()
    rumors = corroborate(symbol=symbol, since=since_s, db=db)
    kept = [r for r in rumors if (r.get("first_seen") or "")[:10] <= target]
    return {
        "symbol": sym,
        "target_date": target,
        "rumors": kept,
        "n_confirmed": sum(1 for r in kept if r.get("status") == "CONFIRMED"),
        "n_unconfirmed": sum(1 for r in kept if r.get("status") != "CONFIRMED"),
    }
