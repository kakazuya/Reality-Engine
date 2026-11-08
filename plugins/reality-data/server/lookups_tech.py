"""pilot3 technicals computed in code (T-128): the price reaction to a filing, gaps, Wilder RSI, SMA 50/200,
volume spikes and the 52-week range position.

Models got these wrong in the 8 Nov re-ask (9 of 136 answers): a filing that reached the exchange at 16:02 was
read as a same-day reaction, a gap was scored close vs *open* instead of close vs the previous close, the RSI
method was guessed, the last moving-average cross was missed and a volume spike was measured against its own
day.  Every number here is computed once, from ``price_delivery``, so an answer copies it and never hand-sums.

Read-only over one pilot3 build, opened through ``lookups_pilot3`` (``REALITY_PILOT3_DB`` names another build,
the same connection and ``as_of`` rule as the other ``pilot3_*`` tools).  Three rules the brief fixes:

* Sessions come from ``price_delivery`` for ``exchange='NSE'``, never from the calendar.
* Raw ``close`` / ``prev_close`` give daily % and gaps; ``adj_close`` gives the RSI, the SMAs and the divergence
  points (a split must never read as a 50% fall).
* A prior-N mean excludes the day itself.
"""
from __future__ import annotations

import bisect
import datetime as dt
from typing import Any

import lookups_pilot3 as p3
from core import DataError

EXCHANGE = "NSE"
CLOSE_TIME = "15:30:00"
KINDS = ("reaction", "gaps", "rsi", "ma", "volume_spikes", "range")

METHODS = {
    "reaction": "day 0 = the filing date when known_at is at or before the 15:30 IST close and that date is a "
                "trading session, else the next session; ret_pct = close vs the previous session close; cum_pct = "
                "close vs the close before day 0; volume_multiple = the day's volume over the mean of the 20 "
                "sessions before day 0; cum_5s_pct = cum_pct on the 5th session counted from day 0.",
    "gaps": "gap_pct = open/prev_close-1; close_ret_pct = close/prev_close-1; held = (close-prev_close)/"
            "(open-prev_close), negative when the gap reverses; a gap up is filled by the first later session "
            "whose low touches prev_close, a gap down by the first whose high does; delivery_pct is compared with "
            "its trailing 250-session mean.",
    "rsi": "Wilder 14 on adjusted close",
    "ma": "SMA 50 and 200 on adjusted close; a cross is the close moving from one side of its SMA to the other, "
          "reported only where the SMA has its full history; insufficient_history says so.",
    "volume_spikes": "volume over the mean volume of the PRIOR 20 sessions (the day itself excluded), close vs "
                     "the previous session close.",
    "range": "52-week high and low of close (raw), position = (close-low)/(high-low).",
}


# --- small helpers ----------------------------------------------------------------------------------
def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out


def _r(value: float | None, nd: int = 2) -> float | None:
    return None if value is None else round(float(value), nd)


def _pct(now: float | None, before: float | None, nd: int = 2) -> float | None:
    if now is None or not before:
        return None
    return _r((now / before - 1.0) * 100.0, nd)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _adj(row: dict) -> float | None:
    return row["adj_close"] if row["adj_close"] is not None else row["close"]


def _prov(row: dict) -> dict[str, Any]:
    day = row["date"]
    return {"table": "price_delivery", "source": f"{EXCHANGE} {day}", "known_at": row.get("known_at") or day}


def _sessions(sym: str, as_of: str) -> list[dict]:
    rows = p3._q(
        "SELECT date, open, high, low, close, prev_close, volume, delivery_pct, adj_close, known_at "
        "FROM price_delivery WHERE symbol=? AND exchange=? AND date<=? ORDER BY date",
        (sym, EXCHANGE, as_of),
    )
    return [dict(r) for r in rows]


def _index_moves(sym: str, as_of: str) -> tuple[str | None, dict[str, float]]:
    """Same-day index % per session for the symbol's main index (the one the build holds most rows for)."""
    names = p3._q(
        "SELECT index_name, COUNT(*) c FROM index_price WHERE symbol=? AND index_name IS NOT NULL AND date<=? "
        "GROUP BY index_name ORDER BY c DESC LIMIT 1", (sym, as_of))
    if not names:
        return None, {}
    index_name = names[0]["index_name"]
    rows = p3._q("SELECT date, index_close FROM index_price WHERE symbol=? AND index_name=? AND date<=? ORDER BY date",
                 (sym, index_name, as_of))
    moves: dict[str, float] = {}
    prev: float | None = None
    for row in rows:
        close = row["index_close"]
        move = _pct(close, prev)
        if move is not None:
            moves[row["date"]] = move
        prev = close
    return index_name, moves


def _reply(sym: str, kind: str, as_of: str, found: bool = True, rows: list | None = None,
           **extra: Any) -> dict[str, Any]:
    rows = rows or []
    out: dict[str, Any] = {"found": found, "symbol": sym, "tool": "pilot3_tech", "kind": kind, "as_of": as_of,
                           "method": METHODS[kind], "n": len(rows), "rows": rows, **extra,
                           "provenance": p3._db_prov()}
    if not found:
        out["hint"] = (f"NOT IN DATA of pilot3 for {sym} / {kind} / as_of {as_of}: the build holds no NSE session "
                       "for that day, too little history for the measure, or no filing of the requested doc_type; "
                       "widen the range or check pilot3_docs, then say NOT IN DATA.")
    return out


def _threshold(value: Any, default: float) -> float:
    """A ratio (0.03 = 3%); a number >= 1 is read as percent so a model passing 3 means 3%."""
    out = _float(value, default)
    if out >= 1:
        out /= 100.0
    if out <= 0:
        raise DataError("bad_threshold", f"threshold must be a positive ratio such as 0.03 (3%), got {value!r}")
    return out


# --- reaction ----------------------------------------------------------------------------------------
def _reaction(sym: str, px: list[dict], as_of: str, start: str | None, end: str | None, sessions: int,
              doc_type: str, limit: int) -> dict[str, Any]:
    dtype = p3._DOC_TYPES.get(doc_type.strip().lower(), doc_type.strip().lower())
    where = ["symbol=?", "doc_type=?", "known_at IS NOT NULL", "substr(known_at,1,10)<=?"]
    args: list[Any] = [sym, dtype, as_of]
    if start:
        where.append("substr(known_at,1,10)>=?")
        args.append(start)
    if end:
        where.append("substr(known_at,1,10)<=?")
        args.append(end)
    docs = [dict(r) for r in p3._q(
        "SELECT doc_key, doc_type, title, filing_date, known_at FROM doc WHERE " + " AND ".join(where) +
        " ORDER BY known_at DESC, doc_key LIMIT ?", (*args, limit))]
    dates = [r["date"] for r in px]
    index_name, index_pct = _index_moves(sym, as_of)
    filings: list[dict[str, Any]] = []
    for doc in docs:
        known = doc["known_at"]
        filing_day = known[:10]
        filed_at = known[11:19] if len(known) >= 19 else "00:00:00"
        same = filed_at <= CLOSE_TIME
        pos = bisect.bisect_left(dates, filing_day)
        on_session = pos < len(px) and dates[pos] == filing_day
        if on_session and same:
            i0: int | None = pos
            rule = f"same session: filed {filed_at} IST, at or before the 15:30 close"
        else:
            j = bisect.bisect_right(dates, filing_day)
            i0 = j if j < len(px) else None
            rule = (f"next session: filed {filed_at} IST, after the 15:30 close" if on_session
                    else f"next session: {filing_day} is not a trading session")
        entry: dict[str, Any] = {"known_at": known, "doc_key": doc["doc_key"], "title": doc["title"],
                                 "filing_date": filing_day, "day0": None, "day0_rule": rule, "rows": [],
                                 "cum_1d_pct": None, "cum_5s_pct": None}
        if i0 is None:
            entry["day0_rule"] = rule + "; no later session in the data"
            filings.append(entry)
            continue
        base = px[i0]["prev_close"] if px[i0]["prev_close"] is not None else (px[i0 - 1]["close"] if i0 else None)
        prior = [r["volume"] for r in px[max(0, i0 - 20):i0] if r["volume"] is not None]
        prior_mean = _mean(prior)
        rows: list[dict[str, Any]] = []
        for offset in range(sessions + 1):
            i = i0 + offset
            if i >= len(px):
                break
            row = px[i]
            volume = row["volume"]
            rows.append({
                "day": offset,
                "date": row["date"],
                "ret_pct": _pct(row["close"], row["prev_close"]),
                "cum_pct": _pct(row["close"], base),
                "close": row["close"],
                "volume": volume,
                "volume_multiple": _r(volume / prior_mean) if volume is not None and prior_mean else None,
                "volume_baseline_sessions": len(prior),
                "volume_mean_20": _r(prior_mean),
                "delivery_pct": _r(row["delivery_pct"]),
                "index_pct": index_pct.get(row["date"]),
                "provenance": _prov(row),
            })
        entry.update({"day0": px[i0]["date"], "rows": rows,
                      "cum_1d_pct": rows[0]["cum_pct"] if rows else None,
                      "cum_5s_pct": rows[4]["cum_pct"] if len(rows) >= 5 else None,
                      "cum_window_pct": rows[-1]["cum_pct"] if rows else None,
                      "window_sessions": len(rows)})
        filings.append(entry)
    return _reply(sym, "reaction", as_of, bool(filings), filings, index_name=index_name,
                  doc_type=dtype, start=start, end=end, sessions=sessions)


# --- gaps --------------------------------------------------------------------------------------------
def _gaps(sym: str, px: list[dict], as_of: str, start: str | None, end: str | None,
          threshold: Any) -> dict[str, Any]:
    gap_threshold = _threshold(threshold, 0.03)
    window_end = end or as_of
    if start is None:
        window_start = (dt.date.fromisoformat(window_end) - dt.timedelta(days=365)).isoformat()
    else:
        window_start = start
    rows: list[dict[str, Any]] = []
    for i, row in enumerate(px):
        if not (window_start <= row["date"] <= window_end):
            continue
        gap = _pct(row["open"], row["prev_close"], nd=4)
        if gap is None or abs(gap) < gap_threshold * 100.0:
            continue
        up = gap > 0
        delivery = [r["delivery_pct"] for r in px[max(0, i - 250):i] if r["delivery_pct"] is not None]
        delivery_mean = _mean(delivery)
        open_, close, prev = row["open"], row["close"], row["prev_close"]
        held = (close - prev) / (open_ - prev) if open_ != prev and close is not None else None
        fill_date = fill_price = None
        for later in px[i + 1:]:
            if up and later["low"] is not None and later["low"] <= prev:
                fill_date, fill_price = later["date"], later["low"]
                break
            if not up and later["high"] is not None and later["high"] >= prev:
                fill_date, fill_price = later["date"], later["high"]
                break
        rows.append({
            "date": row["date"],
            "direction": "up" if up else "down",
            "open": open_,
            "prev_close": prev,
            "gap_pct": _r(gap),
            "close": close,
            "close_ret_pct": _pct(close, prev),
            "held": _r(held, 4),
            "held_pct": _r(held * 100.0) if held is not None else None,
            "fill_date": fill_date,
            "fill_price": _r(fill_price),
            "delivery_pct": _r(row["delivery_pct"]),
            "delivery_mean_250": _r(delivery_mean),
            "delivery_ratio": _r(row["delivery_pct"] / delivery_mean) if row["delivery_pct"] is not None
            and delivery_mean else None,
            "provenance": _prov(row),
        })
    return _reply(sym, "gaps", as_of, True, rows, threshold=round(gap_threshold, 4),
                  start=window_start, end=window_end,
                  note=None if rows else f"no session gapped by {gap_threshold * 100:g}% or more in "
                                         f"{window_start}..{window_end}")


# --- RSI (Wilder 14 on adjusted close) ---------------------------------------------------------------
def _wilder(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _rsi(sym: str, px: list[dict], as_of: str, window: Any) -> dict[str, Any]:
    closes = [_adj(row) for row in px]
    prices = [c for c in closes if c is not None]
    values = _wilder(prices, 14)
    if len(prices) != len(closes) or not values or values[-1] is None:
        return _reply(sym, "rsi", as_of, False, [],
                      insufficient_history=True, sessions_available=len(px), needed=15, window=None)
    n = _int(window, 30, 2, 250)
    defined: list[tuple[int, float]] = []
    for i in range(len(px)):
        value = values[i]
        if value is not None:
            defined.append((i, value))
    points = defined[-n:]
    rsi_at = dict(points)
    series = [{"date": px[i]["date"], "adj_close": _r(prices[i]), "rsi": _r(value), "provenance": _prov(px[i])}
              for i, value in points]
    divergence: dict[str, Any] = {"window": len(points), "bullish_divergence": False, "bearish_divergence": False,
                                  "lows": [], "highs": []}
    if len(points) >= 2:
        indexes = [i for i, _ in points]
        lows = sorted(indexes, key=lambda i: (prices[i], i))[:2]
        lows.sort()
        highs = sorted(indexes, key=lambda i: (-prices[i], i))[:2]
        highs.sort()
        divergence["lows"] = [{"date": px[i]["date"], "adj_close": _r(prices[i]), "rsi": _r(rsi_at[i]),
                               "provenance": _prov(px[i])} for i in lows]
        divergence["highs"] = [{"date": px[i]["date"], "adj_close": _r(prices[i]), "rsi": _r(rsi_at[i]),
                                "provenance": _prov(px[i])} for i in highs]
        divergence["bullish_divergence"] = (prices[lows[1]] < prices[lows[0]]
                                            and rsi_at[lows[1]] > rsi_at[lows[0]])
        divergence["bearish_divergence"] = (prices[highs[1]] > prices[highs[0]]
                                            and rsi_at[highs[1]] < rsi_at[highs[0]])
    last = len(px) - 1
    return _reply(sym, "rsi", as_of, True, [], rsi=_r(values[last]), rsi_date=px[last]["date"],
                  adj_close=_r(prices[last]), window=len(points), series=series, divergence=divergence)


# --- SMA 50 / 200 ------------------------------------------------------------------------------------
def _sma_block(px: list[dict], closes: list[float | None], period: int) -> dict[str, Any]:
    prices = [c for c in closes if c is not None]
    if len(prices) != len(closes) or len(prices) < period:
        return {"period": period, "insufficient_history": True, "sessions_available": len(closes),
                "needed": period}
    values: list[float | None] = [None] * (period - 1)
    running = sum(prices[:period])
    values.append(running / period)
    for i in range(period, len(prices)):
        running += prices[i] - prices[i - period]
        values.append(running / period)
    last = len(px) - 1
    last_cross = last_cross_direction = None
    last_sign = 0
    for i in range(period - 1, len(px)):
        sma = values[i]
        if sma is None:
            continue
        diff = prices[i] - sma
        if diff == 0:
            continue
        sign = 1 if diff > 0 else -1
        if last_sign and sign != last_sign:
            last_cross = px[i]["date"]
            last_cross_direction = "up" if sign > 0 else "down"
        last_sign = sign
    return {"period": period, "insufficient_history": False, "value": _r(values[last]), "adj_close": _r(prices[last]),
            "pct_vs_sma": _pct(prices[last], values[last]), "last_cross": last_cross,
            "last_cross_direction": last_cross_direction, "sessions": len(prices),
            "provenance": _prov(px[last])}


def _ma(sym: str, px: list[dict], as_of: str) -> dict[str, Any]:
    closes = [_adj(row) for row in px]
    rows = [_sma_block(px, closes, period) for period in (50, 200)]
    return _reply(sym, "ma", as_of, True, rows, close=_r(px[-1]["close"]), close_date=px[-1]["date"],
                  adj_close=_r(closes[-1]))


# --- volume spikes -----------------------------------------------------------------------------------
def _volume_spikes(sym: str, px: list[dict], as_of: str, threshold: Any) -> dict[str, Any]:
    multiple_threshold = _float(threshold, 3.0)
    if multiple_threshold <= 0:
        raise DataError("bad_threshold", f"threshold must be a positive volume multiple, got {threshold!r}")
    window_end = as_of
    window_start = (dt.date.fromisoformat(window_end) - dt.timedelta(days=365)).isoformat()
    rows: list[dict[str, Any]] = []
    for i, row in enumerate(px):
        if row["date"] < window_start or i < 20:
            continue
        prior = [r["volume"] for r in px[i - 20:i] if r["volume"] is not None]
        if len(prior) < 20:
            continue
        mean = _mean(prior)
        if not mean or row["volume"] is None:
            continue
        multiple = row["volume"] / mean
        if multiple < multiple_threshold:
            continue
        rows.append({"date": row["date"], "volume": row["volume"], "multiple": _r(multiple),
                     "close": row["close"], "ret_pct": _pct(row["close"], row["prev_close"]),
                     "delivery_pct": _r(row["delivery_pct"]),
                     "volume_mean_20": _r(mean), "provenance": _prov(row)})
    return _reply(sym, "volume_spikes", as_of, True, rows, threshold=multiple_threshold,
                  start=window_start, end=window_end, baseline="mean volume of the prior 20 sessions",
                  note=None if rows else f"no session traded {multiple_threshold:g}x its prior-20 mean or more in "
                                         f"{window_start}..{window_end}")


# --- 52-week range -----------------------------------------------------------------------------------
def _range(sym: str, px: list[dict], as_of: str) -> dict[str, Any]:
    window_start = (dt.date.fromisoformat(as_of) - dt.timedelta(days=365)).isoformat()
    window = [row for row in px if row["date"] >= window_start and row["close"] is not None]
    if not window:
        return _reply(sym, "range", as_of, False, [], window_start=window_start)
    last = window[-1]
    high = max(window, key=lambda r: (r["close"], r["date"]))
    low = min(window, key=lambda r: (r["close"], r["date"]))
    span = high["close"] - low["close"]
    position = (last["close"] - low["close"]) / span if span else None
    row = {
        "last_close": _r(last["close"]),
        "last_date": last["date"],
        "high": _r(high["close"]),
        "high_date": high["date"],
        "low": _r(low["close"]),
        "low_date": low["date"],
        "position": _r(position, 4),
        "pct_above_low": _pct(last["close"], low["close"]),
        "pct_below_high": _pct(last["close"], high["close"]),
        "window_start": window_start,
        "window_end": last["date"],
        "sessions": len(window),
        "provenance": _prov(last),
    }
    return _reply(sym, "range", as_of, True, [row], window_start=window_start)


# --- entry point -------------------------------------------------------------------------------------
def tech(symbol: str, kind: str, as_of: str | None = None, start: str | None = None, end: str | None = None,
         sessions: int = 5, threshold: float | None = None, window: int | None = None,
         doc_type: str = "results", limit: int = 10) -> dict[str, Any]:
    """Price reaction to a filing, gaps, Wilder RSI, SMA 50/200 crosses, volume spikes, 52-week range.

    kind: reaction | gaps | rsi | ma | volume_spikes | range.  as_of drops every session after that day.
    """
    sym = p3.resolve_symbol(symbol)
    name = (kind or "").strip().lower().replace("-", "_")
    if name not in KINDS:
        raise DataError("bad_kind", f"kind must be one of {', '.join(KINDS)}; got {kind!r}")
    asof = p3._day(as_of, "as_of") or dt.date.today().isoformat()
    start_day = p3._day(start, "start")
    end_day = p3._day(end, "end")
    if start_day and end_day and start_day > end_day:
        raise DataError("bad_range", f"start {start_day} is after end {end_day}")
    px = _sessions(sym, asof)
    if not px:
        return _reply(sym, name, asof, False, [], reason="no NSE session on or before as_of")
    if name == "reaction":
        return _reaction(sym, px, asof, start_day, end_day, _int(sessions, 5, 1, 30), doc_type,
                         p3._cap(limit, 10))
    if name == "gaps":
        return _gaps(sym, px, asof, start_day, end_day, threshold)
    if name == "rsi":
        return _rsi(sym, px, asof, window)
    if name == "ma":
        return _ma(sym, px, asof)
    if name == "volume_spikes":
        return _volume_spikes(sym, px, asof, threshold)
    return _range(sym, px, asof)
