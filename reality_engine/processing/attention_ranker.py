"""Tier-3 attention ranking + morning digest (news-feed Tier-2/3 slice).

READ-ONLY vs the DB: this module only issues SELECTs (via the caller's
``DatabaseManager``/``Repository`` handle or the default manager). It never
writes, never synthesizes rows — a miss returns [] / a header-only digest
plus a log line (fail-closed).
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

logger = logging.getLogger("reality_engine.attention_ranker")

_T2_SOURCES = ("TELEGRAM_POST", "YOUTUBE_TRANSCRIPT")
_T1_POLICY_SOURCES = ("PIB_Press_Release", "RBI_Press_Release")
_RUMOR_SCORER_MOD = "reality_engine.processing.rumor_scorer"


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


def _rows(conn: Any, query: str, params: tuple) -> List[Dict[str, Any]]:
    try:
        cur = conn.execute(query, params)
        return [{k: row[k] for k in row.keys()} for row in cur.fetchall()]
    except Exception as exc:  # fail-closed: miss -> empty, never raise
        logger.warning("attention_ranker query miss: %s", exc)
        return []


def _count(conn: Any, query: str, params: tuple) -> int:
    try:
        row = conn.execute(query, params).fetchone()
        if row is None:
            return 0
        try:
            return max(0, int(row[0] if isinstance(row, tuple) else row["c"]))
        except (TypeError, ValueError):
            return 0
    except Exception as exc:  # fail-closed
        logger.warning("attention_ranker count miss: %s", exc)
        return 0


def _tier0_symbols(symbols: List[str], target: str, db: Any) -> List[str]:
    """Scanned symbols with a Tier-0 ANNOUNCEMENT in [target-2d, target]."""
    try:
        from datetime import datetime as _dt, timedelta as _td
        start = (_dt.strptime(str(target).strip(), "%Y-%m-%d").date()
                 - _td(days=2)).isoformat()
    except (TypeError, ValueError):
        return []
    try:
        mgr = _resolve_manager(db)
        with mgr.session() as conn:
            rows = _rows(
                conn,
                "SELECT DISTINCT symbol FROM corporate_documents"
                " WHERE doc_type = 'ANNOUNCEMENT'"
                " AND doc_date >= ? AND doc_date <= ?",
                (start, str(target).strip()),
            )
    except Exception:
        return []
    want = {str(s or "").strip().upper() for s in symbols if s}
    return sorted({str(r.get("symbol") or "").strip().upper()
                   for r in rows} & want)


def _is_confirmed(result: Any) -> bool:
    """True when a rumor_scorer result carries a CONFIRMED verdict."""
    if isinstance(result, str):
        return result.strip().upper() == "CONFIRMED"
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        if result.get("confirmed") is True:
            return True
        for key in ("verdict", "status", "label", "outcome", "decision",
                    "confirmation", "result"):
            val = result.get(key)
            if isinstance(val, str) and val.strip().upper() == "CONFIRMED":
                return True
            if isinstance(val, dict) and _is_confirmed(val):
                return True
        return False
    if isinstance(result, (list, tuple)):
        return any(_is_confirmed(v) for v in result)
    return False


def _load_rumor_fn() -> Any:
    """Return rumor_scorer.corroborate, honoring sys.modules entries.

    A present entry (stub or real) is used as-is and never reimported;
    only a MISSING entry triggers a real import. Absent + unimportable
    means absent (None). Never raises.
    """
    import sys as _sys
    if _RUMOR_SCORER_MOD in _sys.modules:
        mod = _sys.modules[_RUMOR_SCORER_MOD]
        fn = getattr(mod, "corroborate", None) if mod is not None else None
        return fn if callable(fn) else None
    try:
        mod = importlib.import_module(_RUMOR_SCORER_MOD)
    except Exception as exc:
        logger.debug("attention_ranker rumor_scorer import miss: %s", exc)
        return None
    fn = getattr(mod, "corroborate", None)
    return fn if callable(fn) else None


def _rumor_bonus_map(symbols: List[str], target: str, db: Any) -> Dict[str, float]:
    """One corroborate() call for the whole universe; CONFIRMED set -> 0.5 each.

    Fallback: legacy per-symbol path when the batch call misses. Never raises.
    """
    fn = _load_rumor_fn()
    if fn is None:
        return {}
    result: Any = None
    try:
        try:
            result = fn(symbol="", db=db)
        except TypeError:
            result = fn("")
    except Exception as exc:
        logger.debug("attention_ranker batch corroborate miss: %s", exc)
        return {}
    if isinstance(result, dict) and not result.get("symbol"):
        # Batch verdict carries no symbol (stub-style): attribute to scanned
        # symbols with a Tier-0 hit in the window when CONFIRMED, else fall
        # back to the per-symbol path so stub verdicts land correctly.
        if _is_confirmed(result):
            return {s: 0.5 for s in _tier0_symbols(symbols, target, db)}
        out: Dict[str, float] = {}
        for s in symbols:
            sym = str(s or "").strip().upper()
            if sym:
                out[sym] = _rumor_bonus(sym, target, db)
        return out
    bonus: Dict[str, float] = {}
    try:
        for row in result if isinstance(result, list) else []:
            if not isinstance(row, dict):
                continue
            if _is_confirmed(row):
                sym = str(row.get("symbol") or "").strip().upper()
                if sym:
                    bonus[sym] = 0.5
                    continue
                # Cross-symbol cluster (symbol==''): attribute the CONFIRMED
                # bonus to scanned symbols with a Tier-0 hit in the window.
                for s in _tier0_symbols(symbols, target, db):
                    bonus[s] = 0.5
    except Exception:
        return {}
    return bonus


def _rumor_bonus(symbol: str, target: str, db: Any) -> float:
    """0.5 when rumor_scorer.corroborate() reports CONFIRMED; else 0.0.

    Legacy single-symbol path (kept for unit tests + fail-closed fallback).
    Prefer _rumor_bonus_map for universe scans. Never raises.
    """
    fn = _load_rumor_fn()
    if fn is None:
        return 0.0
    result: Any = None
    called = False
    for args in ((symbol, target, db), (symbol, target), (symbol, db), (symbol,)):
        try:
            result = fn(*args)
            called = True
            break
        except TypeError:
            continue
        except Exception as exc:
            logger.debug("attention_ranker corroborate miss for %s: %s", symbol, exc)
            return 0.0
    if not called:
        try:
            result = fn(symbol=symbol, db=db)
        except Exception as exc:
            logger.debug("attention_ranker corroborate miss for %s: %s", symbol, exc)
            return 0.0
    try:
        return 0.5 if _is_confirmed(result) else 0.0
    except Exception:
        return 0.0

def _why_line(components: Dict[str, float]) -> str:
    parts: List[str] = []
    if components.get("price_move", 0.0) > 0:
        parts.append(f"move +{components['price_move']:.2f}")
    if components.get("delivery", 0.0) > 0:
        parts.append(f"delivery +{components['delivery']:.2f}")
    if components.get("news_t0", 0) > 0:
        parts.append(f"news x{int(components['news_t0'])}")
    if components.get("rumor_t2", 0.0) > 0:
        parts.append(f"rumors +{components['rumor_t2']:.1f}")
    if components.get("deals", 0) > 0:
        parts.append(f"deals x{int(components['deals'])}")
    return "; ".join(parts) if parts else "no fresh catalysts"


def rank_attention(
    target_date: str,
    top_n: int = 10,
    db: Any = None,
) -> List[Dict[str, Any]]:
    """Rank symbols by multi-signal attention for ``target_date``.

    Returns ``[{symbol, score, components{price_move, delivery, news_t0,
    rumor_t2, deals}}]`` sorted by score desc (ties by symbol asc),
    truncated to ``top_n``. Never raises on DB misses.
    """
    target = str(target_date or "").strip()
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        top_n = 10
    if top_n <= 0:
        return []
    try:
        target_dt = datetime.strptime(target, "%Y-%m-%d").date()
    except ValueError:
        logger.warning("attention_ranker bad target_date=%r", target_date)
        return []
    start = (target_dt - timedelta(days=2)).isoformat()

    try:
        mgr = _resolve_manager(db)
        with mgr.session() as conn:
            universe = _rows(
                conn,
                "SELECT symbol, change_pct, delivery_spike_ratio"
                " FROM daily_price_delivery WHERE date = ? ORDER BY symbol ASC",
                (target,),
            )
            # One aggregate query per signal table for the WHOLE universe
            # (3 queries total) instead of per-symbol COUNTs (~3 * N).
            # (3 queries total) instead of per-symbol COUNTs (~3 * N).
            ann = {str(r['symbol']): int(r['c'] or 0) for r in _rows(
                conn,
                "SELECT symbol, COUNT(*) AS c FROM corporate_documents"
                " WHERE doc_type = 'ANNOUNCEMENT' AND doc_date >= ? AND doc_date <= ?"
                " GROUP BY symbol",
                (start, target),
            )}
            t2 = {str(r['symbol']): int(r['c'] or 0) for r in _rows(
                conn,
                "SELECT symbol, COUNT(*) AS c FROM intelligence_fts"
                " WHERE source_type IN (?, ?) AND document_date >= ? AND document_date <= ?"
                " GROUP BY symbol",
                (_T2_SOURCES[0], _T2_SOURCES[1], start, target),
            )}
            deal = {str(r['symbol']): int(r['c'] or 0) for r in _rows(
                conn,
                "SELECT symbol, COUNT(*) AS c FROM bulk_block_deals"
                " WHERE deal_date >= ? AND deal_date <= ? GROUP BY symbol",
                (start, target),
            )}
            base: List[Dict[str, Any]] = []
            for r in universe:
                sym = str(r.get('symbol') or '').strip().upper()
                if not sym:
                    continue
                try:
                    chg = float(r.get('change_pct') or 0.0)
                except (TypeError, ValueError):
                    chg = 0.0
                try:
                    dsr = float(r.get('delivery_spike_ratio') or 0.0)
                except (TypeError, ValueError):
                    dsr = 0.0
                price_move = min(abs(chg) / 10.0, 3.0)
                delivery = max(0.0, min(dsr, 5.0)) / 5.0 * 2.0
                news_t0 = min(ann.get(sym, 0), 3)
                rumor_n = min(t2.get(sym, 0), 3)
                deals = min(deal.get(sym, 0), 2)
                base.append({
                    'symbol': sym,
                    'price_move': price_move,
                    'delivery': delivery,
                    'news_t0': news_t0,
                    'rumor_base': rumor_n * 0.5,
                    'deals': deals,
                })
    except Exception as exc:  # fail-closed: any DB failure -> []
        logger.warning("attention_ranker miss for %s: %s", target, exc)
        return []

    bonus_map = _rumor_bonus_map([b["symbol"] for b in base], target, mgr)

    out: List[Dict[str, Any]] = []
    for b in base:
        bonus = bonus_map.get(b["symbol"], 0.0)
        rumor_t2 = b["rumor_base"] + bonus
        components = {
            "price_move": b["price_move"],
            "delivery": b["delivery"],
            "news_t0": b["news_t0"],
            "rumor_t2": rumor_t2,
            "deals": b["deals"],
        }
        score = (b["price_move"] + b["delivery"] + b["news_t0"]
                 + rumor_t2 + b["deals"])
        out.append({"symbol": b["symbol"], "score": score,
                    "components": components})
    out.sort(key=lambda d: (-d["score"], d["symbol"]))
    return out[:top_n]


def morning_digest(target_date: str, db: Any = None) -> str:
    """Render a markdown attention digest for ``target_date``.

    Top-10 attention table plus a Tier-1 policy-watch section (PIB/RBI
    releases in the last 7d). Never raises; empty DB -> header-only digest.
    """
    target = str(target_date or "").strip()
    lines: List[str] = [f"# Morning Attention Digest — {target}", ""]
    try:
        rows = rank_attention(target, top_n=10, db=db)
    except Exception as exc:
        logger.warning("morning_digest rank miss for %s: %s", target, exc)
        rows = []

    lines.append("## Top attention")
    lines.append("")
    if not rows:
        lines.append(f"No price data for {target}.")
    else:
        lines.append("| # | Symbol | Score | Why |")
        lines.append("| --- | --- | --- | --- |")
        for i, r in enumerate(rows, 1):
            lines.append(f"| {i} | {r['symbol']} | {r['score']:.2f}"
                         f" | {_why_line(r['components'])} |")
    lines.append("")

    lines.append("## Policy watch (Tier-1, last 7d)")
    lines.append("")
    policy: List[Dict[str, Any]] = []
    try:
        target_dt = datetime.strptime(target, "%Y-%m-%d").date()
        week_ago = (target_dt - timedelta(days=7)).isoformat()
        mgr = _resolve_manager(db)
        with mgr.session() as conn:
            policy = _rows(
                conn,
                "SELECT title, published_date, source_type FROM raw_documents"
                " WHERE source_type IN (?, ?)"
                " AND published_date >= ? AND published_date <= ?"
                " ORDER BY published_date DESC, title ASC LIMIT 5",
                (_T1_POLICY_SOURCES[0], _T1_POLICY_SOURCES[1],
                 week_ago, target),
            )
    except Exception as exc:
        logger.warning("morning_digest policy miss for %s: %s", target, exc)
        policy = []
    if not policy:
        lines.append("No new policy releases in the last 7d.")
    else:
        for p in policy:
            lines.append(f"- [{p.get('published_date')}] {p.get('title')}"
                         f" ({p.get('source_type')})")
    lines.append("")
    return "\n".join(lines)
