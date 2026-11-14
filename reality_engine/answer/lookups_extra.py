"""Read-only lookups the answer pass adds beside the pilot3 server (T-205 round 6).

* ``price_rows`` -- price sessions for named dates, a start/end pair, or an EVENT (``event_doc`` from the menu, or
  ``event_time``): the session before day 0, day 0 and the next session, each with the previous session's close and
  the adjusted close.  Day 0 is decided by the SAME rule the ``tech`` reaction lookup uses
  (``lookups_tech.day0_for``: a filing out at or before the 15:30 IST close is that session, later is the next), so the
  answer pass never picks the session itself.  A range over 80 sessions returns its two endpoints plus the return row.
* ``holding_share_rows`` -- the filed share count at each quarter end a holding lookup asked for.

They read the store the caller already pinned (``lookups_pilot3``'s read-only connection) and never write.
"""
from __future__ import annotations

import re

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _day(value) -> str | None:
    text = str(value or "").strip()[:10]
    return text if _ISO.match(text) else None


def _prior_session(p3, symbol: str, date: str) -> tuple[str | None, float | None]:
    rows = p3._q("SELECT date, close FROM price_delivery WHERE symbol=? AND exchange='NSE' AND date<? "
                 "AND close IS NOT NULL ORDER BY date DESC LIMIT 1", (symbol, date))
    if not rows:
        return None, None
    return str(rows[0]["date"]), rows[0]["close"]


def _row_of(r: dict, prior_date=None, prior_close=None) -> dict:
    """One session row, with the previous session's close (the column, else the session before it)."""
    prev_close = r.get("prev_close")
    prev = prior_date
    if prev_close is None and prior_close is not None:
        prev_close = prior_close
    if prev_close is None:
        prev = None
    adj = r.get("adj_close") if r.get("adj_close") is not None else r.get("close")
    change = round((r["close"] / prev_close - 1.0) * 100.0, 2) if prev_close else None
    head = (f"{r['date']}: close {r['close']}, previous close {prev_close}"
            + (f" ({change:+.2f}%)" if change is not None else "")
            + f", adjusted close {adj}, volume {r.get('volume')}, delivery {r.get('delivery_pct')}%")
    return {"date": r["date"], "open": r.get("open"), "high": r.get("high"), "low": r.get("low"),
            "close": r.get("close"), "prev_close": prev_close, "prev_session": prev,
            "change_pct": change, "adj_close": adj, "volume": r.get("volume"),
            "delivery_pct": r.get("delivery_pct"), "known_at": r.get("known_at"), "text": head}


def _sessions_to(p3, symbol: str, day: str) -> list[dict]:
    rows = [dict(r) for r in p3._q(
        "SELECT date, open, high, low, close, prev_close, volume, delivery_pct, adj_close, known_at "
        "FROM price_delivery WHERE symbol=? AND exchange='NSE' AND close IS NOT NULL AND date<=? ORDER BY date",
        (symbol, day))]
    return rows


def _event_rows(p3, sym: str, day: str, as_of: str, event_doc, event_time) -> dict:
    import lookups_tech

    known_at, doc_type = None, None
    if event_doc:
        rows = p3._q("SELECT doc_key, doc_type, known_at, filing_date FROM doc WHERE symbol=? AND doc_key=?",
                     (sym, str(event_doc)))
        if not rows:
            return {"found": False, "symbol": sym, "tool": "answer_price_rows",
                    "reason": f"no document {event_doc!r} for {sym} on or before {day}"}
        known_at = str(rows[0]["known_at"] or rows[0]["filing_date"] or "")
        doc_type = rows[0]["doc_type"]
    else:
        known_at = str(event_time or "")
    if len(known_at) < 10:
        return {"found": False, "symbol": sym, "tool": "answer_price_rows",
                "reason": "event_doc or event_time (YYYY-MM-DD or an ISO timestamp) is required"}
    sessions = _sessions_to(p3, sym, day)
    if not sessions:
        return {"found": False, "symbol": sym, "tool": "answer_price_rows", "reason": "no NSE session on or before as_of"}
    dates = [r["date"] for r in sessions]
    i0, rule = lookups_tech.day0_for(dates, known_at)
    if i0 is None:
        return {"found": False, "symbol": sym, "tool": "answer_price_rows", "day0_rule": rule,
                "filing_known_at": known_at,
                "note": rule + "; no later session in the data"}
    out = []
    for idx in range(max(0, i0 - 1), min(len(sessions), i0 + 2)):
        prior = sessions[idx - 1] if idx > 0 else None
        out.append(_row_of(sessions[idx], prior["date"] if prior else None, prior["close"] if prior else None))
    return {"found": True, "symbol": sym, "tool": "answer_price_rows", "n": len(out), "rows": out,
            "day0": sessions[i0]["date"], "day0_rule": rule,
            "filing_known_at": known_at, "doc_type": doc_type, "event_doc": event_doc, "event_time": event_time,
            "as_of": day}


def price_rows(p3, symbol: str, as_of: str, dates=None, start=None, end=None,
               event_doc=None, event_time=None) -> dict:
    """Sessions for ``dates``/``start..end`` or the sessions around an EVENT (``event_doc`` / ``event_time``)."""
    sym = p3.resolve_symbol(symbol)
    day = _day(as_of) or "9999-12-31"
    if event_doc or event_time:
        return _event_rows(p3, sym, day, as_of, event_doc, event_time)
    wanted: list[str] = []
    if isinstance(dates, (list, tuple)):
        wanted = [d for d in (_day(x) for x in dates) if d]
    start_day, end_day = _day(start), _day(end)
    if not wanted and not start_day and not end_day:
        return {"found": False, "symbol": sym, "tool": "answer_price_rows",
                "reason": "give dates=[YYYY-MM-DD, ...], start=/end=, or event_doc=/event_time="}
    where = ["symbol=?", "exchange='NSE'", "close IS NOT NULL"]
    args: list = [sym]
    if wanted:
        where.append(f"date IN ({','.join('?' * len(wanted))})")
        args.extend(wanted)
    if start_day:
        where.append("date>=?")
        args.append(start_day)
    if end_day:
        where.append("date<=?")
        args.append(end_day)
    extra, eargs = p3._asof(as_of, "known_at")
    rows = [dict(r) for r in p3._q(
        "SELECT date, open, high, low, close, prev_close, volume, delivery_pct, adj_close, known_at "
        f"FROM price_delivery WHERE {' AND '.join(where)}{extra} ORDER BY date", tuple(args) + tuple(eargs))]
    out = []
    for i, r in enumerate(rows):
        if r["date"] > day:
            continue
        prior = rows[i - 1] if i > 0 else None
        row = _row_of(r, prior["date"] if prior else None, prior["close"] if prior else None)
        if row["prev_close"] is None:
            row["prev_session"], row["prev_close"] = _prior_session(p3, sym, str(r["date"]))
        out.append(row)
    first = out[0] if out else None
    last = out[-1] if out else None
    ret = ret_x = None
    if first and last and first is not last and first.get("adj_close"):
        ret = round((last["adj_close"] / first["adj_close"] - 1.0) * 100.0, 2)
        ret_x = round(last["adj_close"] / first["adj_close"], 4)
    sessions = len(out)
    endpoint_only = False
    if not wanted and sessions > 80:
        # a multi-year range is asked for its return, not its 1,500 rows
        out = [out[0], out[-1]]
        endpoint_only = True
    if ret is not None and first is not None and last is not None:
        out.append({"date": last["date"], "period": f"{first['date']}..{last['date']}",
                    "value": ret, "unit": "return_pct", "return_x": ret_x,
                    "text": f"adjusted price return {first['date']}..{last['date']}: {ret:+.2f}%"
                            f" ({ret_x:.2f}x) from adjusted close {first['adj_close']} to {last['adj_close']}"
                            f" ({sessions} sessions, splits and bonuses applied)",
                    "known_at": last.get("known_at")})
    note = None
    if wanted and len(out) < len(wanted):
        note = f"{len(wanted) - len(out)} of the dates asked have no session on or before {day}"
    if endpoint_only:
        note = (f"{sessions} sessions in the range; only the first and last are returned, the return above uses "
                "the full span")
    return {"found": bool(out), "symbol": sym, "tool": "answer_price_rows", "n": len(out), "rows": out,
            "sessions_in_range": sessions, "endpoints_only": endpoint_only,
            "sessions_returned": ret is not None,
            "requested_dates": wanted or None, "start": out[0]["date"] if out else start_day,
            "end": out[-1]["date"] if out else end_day,
            "return_pct": ret, "return_x": ret_x,
            "return_basis": "first-to-last adjusted close (splits and bonuses applied)" if ret is not None else None,
            "note": note, "as_of": day,
            "hint": None if out else "no NSE session for those dates in this store"}


def holding_share_rows(p3, symbol: str, args: dict, reply: dict) -> list[dict]:
    """One share-count row per quarter end a holding lookup asked for (the latest filing on or before it)."""
    quarters: list[str] = []
    asked = _day(args.get("quarter_end"))
    if asked:
        quarters.append(asked)
    for row in reply.get("rows") or []:
        q = _day(row.get("quarter_end"))
        if q and q not in quarters:
            quarters.append(q)
    out = []
    for quarter in quarters:
        rows = p3._q("SELECT rowid, * FROM share_capital WHERE symbol=? AND event IS NULL AND as_of_date<=? "
                     "AND shares_outstanding IS NOT NULL ORDER BY as_of_date DESC, known_at DESC LIMIT 1",
                     (symbol, quarter))
        if not rows:
            continue
        r = dict(rows[0])
        shares = r.get("shares_outstanding")
        out.append({"date": quarter, "period": quarter, "value": shares, "unit": "shares",
                    "quarter_end": quarter,
                    "text": f"share count at {quarter}: {shares:,} shares outstanding "
                            f"(paid-up capital {r.get('paid_up_capital')}, face value {r.get('face_value')}, "
                            f"count basis {r.get('count_basis') or r.get('source_table')})",
                    "known_at": r.get("known_at"),
                    "provenance": {"table": "share_capital", "source": f"row {r.get('rowid')}",
                                   "known_at": r.get("known_at")}})
    return out
