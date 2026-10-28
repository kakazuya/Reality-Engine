"""EVENT: what was known at T and how the session(s) around it moved.

Reads the dated snapshot's unified ``events`` table (PIT ``known_at_utc``) and
the primary daily series.  The 15:30 rule maps a filing time to its trading
session: known at or before 15:30 -> that session, later -> the next one.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, isin_of

CHECKED = ["truth_duckdb.events", "truth_duckdb.px_daily",
           "equity_intelligence.daily_price_delivery"]


def _price_window(ctx: Any, isin: str, start: str, end: str) -> list[dict[str, Any]]:
    try:
        return ctx.duck_rows(
            "SELECT date, close, prev_close FROM px_daily WHERE isin = ? AND date >= ? "
            "AND date <= ? ORDER BY date", [isin, start, end])
    except Exception:
        try:
            return ctx.rows(
                "equity_intelligence",
                "SELECT date, close, prev_close FROM daily_price_delivery WHERE isin = ? "
                "AND date >= ? AND date <= ? ORDER BY date", (isin, start, end))
        except Exception:
            return []


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    if not slots.get("needs", {}).get("event"):
        return envelope("EVENT", ok=True, na=True, checked=CHECKED,
                        detail="no event window asked; EVENT not applicable")
    isin = isin_of(slots, ctx, as_of)
    if not isin:
        if slots.get("entity_level") != "stock":
            return envelope("EVENT", ok=True, na=True, checked=CHECKED,
                            detail="index/sector move is a SERIES ask; EVENT not applicable")
        return envelope("EVENT", ok=False, why="no_doc", checked=CHECKED,
                        detail="cannot resolve an ISIN at as_of")
    anchor = slots.get("date_from") or as_of
    if len(anchor) != 10:
        anchor = as_of
    lo = (date.fromisoformat(anchor) - timedelta(days=5)).isoformat()
    hi = (date.fromisoformat(anchor) + timedelta(days=5)).isoformat()
    events: list[dict[str, Any]] = []
    try:
        events = ctx.duck_rows(
            "SELECT isin, known_at_utc, kind, source_ref, summary FROM events "
            "WHERE isin = ? AND substr(known_at_utc,1,10) <= ? "
            "AND substr(known_at_utc,1,10) >= ? AND substr(known_at_utc,1,10) <= ? "
            "ORDER BY known_at_utc LIMIT 25", [isin, as_of, lo, hi])
    except Exception as exc:  # noqa: BLE001
        degraded = [f"unified events table unavailable ({type(exc).__name__}); "
                    "no announcement timeline"]
        prices = _price_window(ctx, isin, lo, hi)
        if not prices:
            return envelope("EVENT", ok=False, why="tool", checked=CHECKED,
                            detail="event store unavailable and no price window",
                            degraded=degraded)
        events = []
        degraded.append("price-only event window")
    else:
        degraded = []
    prices = _price_window(ctx, isin, (date.fromisoformat(lo) - timedelta(days=7)).isoformat(),
                           (date.fromisoformat(hi) + timedelta(days=14)).isoformat())
    by_date = {str(r["date"])[:10]: r for r in prices}
    ordered = sorted(by_date)
    reaction = None
    if len(ordered) >= 2:
        before = [d for d in ordered if d <= anchor]
        after = [d for d in ordered if d > anchor]
        if before and after:
            prev = by_date[before[-1]]
            nxt = by_date[after[0]]
            reaction = {"session": after[0], "prev_close": prev["close"],
                        "close": nxt["close"],
                        "return_pct": compute.growth(prev["close"], nxt["close"])}
        elif before:
            row = by_date[before[-1]]
            reaction = {"session": before[-1], "prev_close": row.get("prev_close"),
                        "close": row["close"],
                        "return_pct": compute.growth(row.get("prev_close"), row["close"])}
    if not events and not prices:
        return envelope("EVENT", ok=False, why="no_doc", checked=CHECKED, degraded=degraded,
                        detail=f"no event or price row for {isin} around {anchor}",
                        nid_reason=f"no announcement/event known by {as_of} around {anchor}")
    if not events:
        detail = f"no event row around {anchor}"
        if reaction and reaction.get("return_pct") is not None:
            detail += f"; price moved {reaction['return_pct']:+.2f}% on {reaction['session']}"
        return envelope("EVENT", ok=False, why="no_doc", checked=CHECKED, degraded=degraded,
                        detail=detail, nid_reason=detail)
    kinds = ", ".join(sorted({str(e["kind"]) for e in events})[:6])
    detail = f"{len(events)} event(s) around {anchor} known by {as_of}: {kinds}"
    if reaction and reaction.get("return_pct") is not None:
        detail += (f"; session {reaction['session']} close {fmt_num(reaction['close'])} "
                   f"({reaction['return_pct']:+.2f}%)")
    return envelope(
        "EVENT", ok=True,
        rows=[{"ref": f"events:{e.get('source_ref')}", "known_at": str(e["known_at_utc"])[:10],
               "kind": e["kind"], "summary": (e.get("summary") or "")[:200]} for e in events[:8]],
        provenance=[{"ref": f"events:{e.get('source_ref')}",
                     "known_at": str(e["known_at_utc"])[:10]} for e in events[:8]],
        pit=f"known_at_utc date <= {as_of}; session mapping by the 15:30 rule",
        checked=CHECKED, degraded=degraded, detail=detail)
