"""EVENT: what was known at T and how the session(s) around it moved.

The day-0 store is the T1 build's ``event_day0`` (``session_0`` was built with the
15:30 IST rule); the event's own announcement is resolved from ``ann`` (symbol +
DissemDT, PIT ``known_at`` <= as_of) and the dated snapshot's unified ``events``
table is the last resort.  The window is the four sessions from day 0 -- or the
four before it when the ask says "before"/"leak" -- and every row is dated at the
session it is about, so the period gate can judge it instead of guessing.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, identity_symbols, in_period, isin_of

CHECKED = ["market_state.event_day0", "bse_announcements.ann",
           "truth_duckdb.events", "truth_duckdb.px_daily",
           "equity_intelligence.daily_price_delivery"]
#: How many sessions the news gets to diffuse (the study's window, not a guess).
DIFFUSION_SESSIONS = 4
#: Calendar padding either side of the ask's anchor when hunting for the event.
SEARCH_DAYS = 10
MAX_EVENTS = 3
PRE_WINDOW = re.compile(r"\b(before|prior|leak|lead[- ]?up|ahead of)\b", re.I)


def day0(known_at: str) -> str | None:
    """The 15:30 IST rule: filed at or before 15:30 is that session, later is T+1."""
    text = str(known_at or "")
    try:
        stamp = date.fromisoformat(text[:10])
    except ValueError:
        return None
    if len(text) > 10 and text[11:16] > "15:30":
        stamp += timedelta(days=1)
    return stamp.isoformat()


def _ist(known_at_utc: Any) -> str:
    """The snapshot stamps UTC; the day-0 rule is an IST rule, so shift first."""
    raw = str(known_at_utc or "")
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "").replace("+00:00", ""))
    except ValueError:
        return raw
    return (stamp + timedelta(hours=5, minutes=30)).isoformat(timespec="seconds")


def _day0_rows(ctx: Any, isin: str, lo: str, hi: str,
               as_of: str) -> tuple[list[dict[str, Any]], bool]:
    try:
        return ctx.rows(
            "market_state",
            "SELECT event_id, event_kind, known_at, session_0 FROM event_day0 "
            "WHERE isin = ? AND session_0 >= ? AND session_0 <= ? AND known_at <= ? "
            "ORDER BY session_0 DESC, known_at DESC LIMIT 60",
            (isin, lo, hi, f"{as_of}T23:59:59")), True
    except Exception:  # noqa: BLE001 - the T1 store is optional; ann is the next source
        return [], False


def _ann_rows(ctx: Any, symbols: list[str], lo: str, hi: str,
              as_of: str) -> tuple[list[dict[str, Any]], bool]:
    if not symbols:
        return [], False
    marks = ",".join("?" * len(symbols))
    try:
        return ctx.rows(
            "bse_announcements",
            "SELECT NEWSID, symbol, DissemDT, CATEGORYNAME, SUBCATNAME, HEADLINE FROM ann "
            f"WHERE symbol IN ({marks}) AND DissemDT >= ? AND DissemDT <= ? "
            "AND DissemDT <= ? ORDER BY DissemDT DESC LIMIT 20",
            [*symbols, f"{lo}T00:00:00", f"{hi}T23:59:59", f"{as_of}T23:59:59"]), True
    except Exception:  # noqa: BLE001 - announcements decorate the timeline, not replace it
        return [], False


def _snapshot_rows(ctx: Any, isin: str, lo: str, hi: str,
                   as_of: str) -> list[dict[str, Any]]:
    """The dated snapshot's unified events; ``CAST`` because the column is a TIMESTAMP."""
    try:
        return ctx.duck_rows(
            "SELECT isin, known_at_utc, kind, source_ref, summary FROM events "
            "WHERE isin = ? AND CAST(known_at_utc AS DATE) >= CAST(? AS DATE) "
            "AND CAST(known_at_utc AS DATE) <= CAST(? AS DATE) "
            "AND CAST(known_at_utc AS DATE) <= CAST(? AS DATE) "
            "ORDER BY known_at_utc LIMIT 25", [isin, lo, hi, as_of])
    except Exception:  # noqa: BLE001 - duckdb/snapshot are optional in a fixture root
        return []


def _merge(events: list[dict[str, Any]], event: dict[str, Any]) -> None:
    """One event per filing: an announcement fills the event's headline, not a new row.

    ``ann`` is keyed on the BSE dissemination stamp and ``event_day0`` on the
    snapshot's event stamp, so the same filing reaches here with two sessions (the
    store resolves T+1 to the next trading day, the rule to the next date): the
    store's session is kept and the announcement adds the headline.
    """
    key = str(event["ref"]).split(":", 1)[-1]
    for old in events:
        same_ref = str(old["ref"]).split(":", 1)[-1] == key
        # A headline only belongs to an announcement row: a band code ("H"/"L") is
        # not a news event and must not borrow the day's filing text.
        same_day = (old.get("kind") == "announcement" and not old.get("quote")
                    and bool(old["known_at"][:10])
                    and old["known_at"][:10] == event["known_at"][:10])
        if not (same_ref or same_day):
            continue
        if event.get("quote"):
            old["quote"] = event["quote"]
        if same_ref:
            old["ref"] = event["ref"]  # the announcement names the filing (NEWSID)
        if old.get("kind") == "announcement":
            old["kind"] = old["item"] = event["kind"]
        return
    events.append(event)


def _timeline(ctx: Any, isin: str, symbols: list[str], lo: str, hi: str,
              as_of: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Events in [lo, hi] known by as_of, from every held source."""
    events: list[dict[str, Any]] = []
    depth0, t1_ok = _day0_rows(ctx, isin, lo, hi, as_of)
    for row in depth0:
        session = str(row.get("session_0") or "")[:10]
        kind = str(row.get("event_kind") or "event")
        if session:
            _merge(events, {"ref": f"event_day0:{row.get('event_id')}", "period": session,
                            "known_at": str(row.get("known_at") or "")[:10], "kind": kind,
                            "item": kind, "quote": ""})
    announcements, ann_ok = _ann_rows(ctx, symbols, lo, hi, as_of)
    for row in announcements:
        stamp = str(row.get("DissemDT") or "")
        session = day0(stamp)
        if not session:
            continue
        kind = str(row.get("SUBCATNAME") or row.get("CATEGORYNAME") or "announcement")
        _merge(events, {"ref": f"ann:{row.get('NEWSID')}", "period": session,
                        "known_at": stamp[:10], "kind": kind, "item": kind,
                        "quote": str(row.get("HEADLINE") or "")})
    snapshot = _snapshot_rows(ctx, isin, lo, hi, as_of)
    for row in snapshot:
        known = _ist(row.get("known_at_utc"))
        if not known or known[:10] > as_of:
            continue  # UTC date <= as_of is not enough: the IST day is what was known
        session = day0(known)
        if not session:
            continue
        kind = str(row.get("kind") or "event")
        summary = str(row.get("summary") or "")
        _merge(events, {"ref": f"events:{row.get('source_ref')}", "period": session,
                        "known_at": known[:10], "kind": kind, "item": kind,
                        "quote": summary if len(summary) > 8 else ""})
    degraded = []
    if not events:
        degraded.append("no event_day0/ann row for the entity in the window"
                        + ("" if t1_ok or ann_ok else "; day-0 store not configured")
                        + ("; dated snapshot events only" if snapshot else ""))
    return events, degraded


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


def _diffusion(prices: list[dict[str, Any]], start: str,
               question: str) -> list[dict[str, Any]]:
    """The four sessions from day 0 (or the four before it) with their returns."""
    by_date = {str(row["date"])[:10]: row for row in prices}
    ordered = sorted(by_date)
    at = next((index for index, day in enumerate(ordered) if day >= start), None)
    if at is None:
        return []
    if PRE_WINDOW.search(question):
        sessions = ordered[max(0, at - DIFFUSION_SESSIONS):at]
    else:
        sessions = ordered[at:at + DIFFUSION_SESSIONS]
    out = []
    for day in sessions:
        index = ordered.index(day)
        row = by_date[day]
        prev = row.get("prev_close")
        if (prev in (None, "") or not float(prev or 0)) and index:
            prev = by_date[ordered[index - 1]].get("close")
        ret = compute.growth(prev, row.get("close"))
        out.append({"session": day, "close": row.get("close"), "return_pct": ret})
    return out


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
    question = str(slots.get("question") or "")
    anchor = str(slots.get("date_from") or as_of)[:10]
    try:
        stamp = date.fromisoformat(anchor)
    except ValueError:
        anchor = as_of
        stamp = date.fromisoformat(as_of)
    lo = (stamp - timedelta(days=SEARCH_DAYS)).isoformat()
    hi = (stamp + timedelta(days=SEARCH_DAYS)).isoformat()
    events, degraded = _timeline(
        ctx, isin, identity_symbols(ctx, slots, isin), lo, hi, as_of)
    # PIT: a session after the decision day is not knowable, so the window stops there.
    prices = _price_window(
        ctx, isin, (stamp - timedelta(days=SEARCH_DAYS + 7)).isoformat(),
        min((stamp + timedelta(days=SEARCH_DAYS + 14)).isoformat(), as_of))
    if not events:
        detail = f"no event row around {anchor}"
        later = [row for row in prices if str(row["date"])[:10] >= anchor]
        if later:
            detail += (f"; close {fmt_num(later[0].get('close'))} on "
                       f"{str(later[0]['date'])[:10]}")
        return envelope("EVENT", ok=False, why="no_doc", checked=CHECKED, degraded=degraded,
                        detail=detail, nid_reason=detail)
    # Nearest event to the ask's anchor is day 0 (ties go to the later session).
    events.sort(key=lambda event: (abs((date.fromisoformat(event["period"]) - stamp).days),
                                   event["period"], event["kind"]))
    day0_session = events[0]["period"]
    diffusion = _diffusion(prices, day0_session, question)
    rows: list[dict[str, Any]] = []
    for event in events[:MAX_EVENTS]:
        row = {"ref": event["ref"], "isin": isin, "period": event["period"],
               "known_at": event["known_at"], "item": event["item"]}
        if event.get("quote"):
            row["quote"] = str(event["quote"])[:200]
        rows.append(row)
    for point in diffusion:
        rows.append({"ref": f"daily_price_delivery:{isin}", "isin": isin,
                     "period": point["session"], "known_at": point["session"],
                     "item": "session return", "close": point["close"],
                     "return_pct": point["return_pct"]})
    kept = in_period(rows, slots, hop="EVENT")
    dropped = len(rows) - len(kept)
    if dropped:
        degraded.append(f"{dropped} session row(s) outside the asked period were dropped")
    if not kept:
        detail = (f"{len(events)} event(s) exist around {anchor} but none is inside the "
                  f"asked period ({slots.get('date_from')}..{slots.get('date_to')})")
        return envelope("EVENT", ok=False, why="no_doc", checked=CHECKED, degraded=degraded,
                        detail=detail, nid_reason=detail)
    kinds = ", ".join(dict.fromkeys(event["kind"] for event in events))
    detail = (f"{len(events)} event(s) around {anchor} known by {as_of}: {kinds}; "
              f"day 0 {day0_session}")
    moves = [point for point in diffusion if point["return_pct"] is not None]
    if moves:
        label = "4 sessions before" if PRE_WINDOW.search(question) else "4-session diffusion"
        detail += (f"; {label}: " + ", ".join(
            f"{point['session']} {point['return_pct']:+.2f}%" for point in moves))
    return envelope(
        "EVENT", ok=True, rows=kept,
        provenance=[{"ref": event["ref"], "known_at": event["known_at"]}
                    for event in events[:MAX_EVENTS]],
        pit=f"known_at <= {as_of} (15:30 IST day-0 rule); sessions in the price window",
        checked=CHECKED, degraded=degraded, detail=detail)
