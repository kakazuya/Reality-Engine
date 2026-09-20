"""News explainer: read-only move attribution over Tier-0 tables (news-feed v1).

READ-ONLY vs the DB: this module only issues SELECTs (via the caller's
``DatabaseManager``/``Repository`` handle or the default manager). It never
writes, never synthesizes rows — a miss returns empty lists + LOW verdict.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("reality_engine.news_explainer")

# Module-level severity map: HIGH wins over MEDIUM wins over LOW (default).
KEYWORD_SEVERITY: Dict[str, List[str]] = {
    "HIGH": [
        "resignation", "fraud", "sebi", "raid", "default", "downgrade",
        "cessation", "strike", "accident", "fire", "penalty", "ban",
        "suspension", "investigation", "scam",
    ],
    "MEDIUM": [
        "clarification", "update", "appointment", "dividend", "bonus",
        "split", "buyback", "merger", "order", "contract", "guidance",
        "rating",
    ],
}

_SEV_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _severity_for_title(title: Any) -> str:
    """Classify one announcement title; unknown/empty -> LOW."""
    text = str(title or "").lower()
    for kw in KEYWORD_SEVERITY["HIGH"]:
        if kw in text:
            return "HIGH"
    for kw in KEYWORD_SEVERITY["MEDIUM"]:
        if kw in text:
            return "MEDIUM"
    return "LOW"


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
        logger.warning("news_explainer query miss: %s", exc)
        return []


def explain_move(
    symbol: str,
    target_date: str,
    window_days: int = 2,
    db: Any = None,
) -> Dict[str, Any]:
    """Attribute a symbol's move on ``target_date`` to Tier-0 news flow.

    Returns dict ``{symbol, target_date, price, announcements, corp_actions,
    deals, verdict}`` where ``price`` is a ``{date, close, prev_close,
    change_pct, delivery_spike_ratio}`` dict or None, and ``verdict`` is
    ``{severity, drivers}``. Never raises on DB misses.
    """
    sym = str(symbol or "").strip().upper()
    target = str(target_date or "").strip()
    try:
        window_days = max(0, int(window_days))
    except (TypeError, ValueError):
        window_days = 2

    empty: Dict[str, Any] = {
        "symbol": sym,
        "target_date": target,
        "price": None,
        "announcements": [],
        "corp_actions": [],
        "deals": [],
        "verdict": {"severity": "LOW", "drivers": []},
    }
    try:
        target_dt = datetime.strptime(target, "%Y-%m-%d").date()
    except ValueError:
        logger.warning("news_explainer bad target_date=%r", target_date)
        return empty
    start = (target_dt - timedelta(days=window_days)).isoformat()

    try:
        mgr = _resolve_manager(db)
        with mgr.session() as conn:
            price_rows = _rows(
                conn,
                "SELECT date, close, prev_close, change_pct, delivery_spike_ratio"
                " FROM daily_price_delivery WHERE symbol = ? AND date = ? LIMIT 1",
                (sym, target),
            )
            ann_rows = _rows(
                conn,
                "SELECT doc_date, title, source_url FROM corporate_documents"
                " WHERE symbol = ? AND doc_type = 'ANNOUNCEMENT'"
                " AND doc_date >= ? AND doc_date <= ? ORDER BY doc_date ASC",
                (sym, start, target),
            )
            action_rows = _rows(
                conn,
                "SELECT action_type, subject, ex_date FROM corporate_actions"
                " WHERE symbol = ? AND ((ex_date >= ? AND ex_date <= ?)"
                " OR (broadcast_date >= ? AND broadcast_date <= ?))"
                " ORDER BY ex_date ASC",
                (sym, start, target, start, target),
            )
            deal_rows = _rows(
                conn,
                "SELECT deal_date, client_name, deal_type, buy_sell, quantity,"
                " trade_price FROM bulk_block_deals"
                " WHERE symbol = ? AND deal_date >= ? AND deal_date <= ?"
                " ORDER BY deal_date ASC",
                (sym, start, target),
            )
    except Exception as exc:  # fail-closed: any DB failure -> empty LOW
        logger.warning("news_explainer miss for %s @ %s: %s", sym, target, exc)
        return empty

    price: Optional[Dict[str, Any]] = None
    if price_rows:
        r = price_rows[0]
        price = {
            "date": r.get("date"),
            "close": r.get("close"),
            "prev_close": r.get("prev_close"),
            "change_pct": r.get("change_pct"),
            "delivery_spike_ratio": r.get("delivery_spike_ratio"),
        }

    announcements = [
        {"doc_date": r.get("doc_date"), "title": r.get("title"),
         "source_url": r.get("source_url")}
        for r in ann_rows
    ]
    corp_actions = [
        {"action_type": r.get("action_type"), "subject": r.get("subject"),
         "ex_date": r.get("ex_date")}
        for r in action_rows
    ]
    deals = [
        {"deal_date": r.get("deal_date"), "client_name": r.get("client_name"),
         "deal_type": r.get("deal_type"), "buy_sell": r.get("buy_sell"),
         "quantity": r.get("quantity"), "trade_price": r.get("trade_price")}
        for r in deal_rows
    ]

    severity = "LOW"
    for a in announcements:
        sev = _severity_for_title(a.get("title"))
        if _SEV_RANK[sev] > _SEV_RANK[severity]:
            severity = sev
            if severity == "HIGH":
                break
    if price is None and not announcements:
        severity = "LOW"

    drivers: List[str] = []
    if price is not None:
        try:
            chg = float(price.get("change_pct") or 0.0)
            chg_s = f"{chg:+.2f}%"
        except (TypeError, ValueError):
            chg_s = str(price.get("change_pct"))
        drivers.append(
            f"Price on {price.get('date')}: close {price.get('close')} ({chg_s})"
        )
    for a in announcements:
        drivers.append(f"Announcement {a.get('doc_date')}: {a.get('title')}")
    for c in corp_actions:
        drivers.append(
            f"Corporate action {c.get('action_type')} (ex {c.get('ex_date')}):"
            f" {c.get('subject')}"
        )
    for d in deal_rows:
        drivers.append(
            f"{d.get('deal_type')} {d.get('buy_sell')} by {d.get('client_name')}:"
            f" {d.get('quantity')} @ {d.get('trade_price')} ({d.get('deal_date')})"
        )

    return {
        "symbol": sym,
        "target_date": target,
        "price": price,
        "announcements": announcements,
        "corp_actions": corp_actions,
        "deals": deals,
        "verdict": {"severity": severity, "drivers": drivers},
    }
