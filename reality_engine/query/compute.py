"""Pure arithmetic for the query layer: no I/O, no globals.

Every function returns ``None`` instead of guessing when its inputs are not
usable (missing value, zero denominator, no elapsed time).  Callers turn that
into a partial answer, never into a number.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Sequence


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _day(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "")[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def growth(begin: Any, end: Any) -> float | None:
    """Simple growth in percent (0.10 -> 10.0)."""
    a, b = _f(begin), _f(end)
    if a is None or b is None or a == 0:
        return None
    return (b / a - 1.0) * 100.0


def cagr(begin: Any, end: Any, years: Any) -> float | None:
    """Compound annual growth in percent; ``years`` must be > 0."""
    a, b, n = _f(begin), _f(end), _f(years)
    if a is None or b is None or n is None or a <= 0 or b < 0 or n <= 0:
        return None
    return ((b / a) ** (1.0 / n) - 1.0) * 100.0


def cagr_between(begin: Any, end: Any, begin_date: Any, end_date: Any) -> tuple[float | None, float | None]:
    """(cagr_pct, years) from two values and their dates."""
    d1, d2 = _day(begin_date), _day(end_date)
    if d1 is None or d2 is None or d2 <= d1:
        return None, None
    years = (d2 - d1).days / 365.25
    return cagr(begin, end, years), years


def margin(numerator: Any, denominator: Any) -> float | None:
    """Percentage share of ``numerator`` in ``denominator``."""
    a, b = _f(numerator), _f(denominator)
    if a is None or b is None or b == 0:
        return None
    return a / b * 100.0


def ratio(numerator: Any, denominator: Any) -> float | None:
    a, b = _f(numerator), _f(denominator)
    if a is None or b is None or b == 0:
        return None
    return a / b


def delta(begin: Any, end: Any) -> float | None:
    a, b = _f(begin), _f(end)
    return None if a is None or b is None else b - a


def window_return(points: Sequence[tuple[Any, Any]]) -> tuple[float | None, float | None, float | None]:
    """(return_pct, first_close, last_close) over dated closes, ordered or not."""
    clean = [(_day(d), _f(v)) for d, v in points]
    clean = [(d, v) for d, v in clean if d is not None and v is not None]
    if len(clean) < 2:
        return None, None, None
    clean.sort(key=lambda item: item[0])
    first, last = clean[0][1], clean[-1][1]
    return growth(first, last), first, last


def max_drawdown(points: Sequence[tuple[Any, Any]]) -> float | None:
    """Worst peak-to-trough fall in percent (positive number)."""
    clean = [(_day(d), _f(v)) for d, v in points]
    clean = [(d, v) for d, v in clean if d is not None and v is not None]
    if len(clean) < 2:
        return None
    clean.sort(key=lambda item: item[0])
    peak, worst = clean[0][1], 0.0
    for _, value in clean:
        peak = max(peak, value)
        if peak:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def extreme(points: Sequence[tuple[Any, Any]], kind: str = "max") -> tuple[float, Any] | None:
    """(value, date) of the max/min close in the window."""
    clean = [(_day(d), _f(v)) for d, v in points]
    clean = [(d, v) for d, v in clean if d is not None and v is not None]
    if not clean:
        return None
    pick = max(clean, key=lambda item: item[1]) if kind == "max" else min(clean, key=lambda item: item[1])
    return pick[1], pick[0].isoformat()


def rank(values: dict[str, Any], descending: bool = True) -> list[tuple[str, float, int]]:
    """[(label, value, rank)] sorted; ties share the lower rank."""
    clean = [(label, _f(value)) for label, value in values.items()]
    clean = [(label, value) for label, value in clean if value is not None]
    clean.sort(key=lambda item: item[1], reverse=descending)
    out: list[tuple[str, float, int]] = []
    for i, (label, value) in enumerate(clean, 1):
        if i > 1 and value == out[-1][1]:
            out.append((label, value, out[-1][2]))
        else:
            out.append((label, value, i))
    return out


def percentile(values: Iterable[Any], x: Any) -> float | None:
    """Share of values <= x, in percent (100 = the highest)."""
    clean = [_f(v) for v in values]
    clean = [v for v in clean if v is not None]
    xv = _f(x)
    if not clean or xv is None:
        return None
    return sum(1 for v in clean if v <= xv) / len(clean) * 100.0


def zscore(values: Iterable[Any], x: Any) -> float | None:
    clean = [_f(v) for v in values]
    clean = [v for v in clean if v is not None]
    xv = _f(x)
    if not clean or xv is None or len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    var = sum((v - mean) ** 2 for v in clean) / (len(clean) - 1)
    return None if var <= 0 else (xv - mean) / (var ** 0.5)


def relative_return(subject: Sequence[tuple[Any, Any]],
                    benchmark: Sequence[tuple[Any, Any]]) -> float | None:
    """Excess return in percent of the subject over the benchmark."""
    own, _, _ = window_return(subject)
    bench, _, _ = window_return(benchmark)
    return None if own is None or bench is None else own - bench


def rsi(closes: Sequence[Any], period: int = 14) -> float | None:
    """Wilder RSI over the tail of a close series."""
    clean = [v for v in (_f(c) for c in closes) if v is not None]
    if len(clean) <= period:
        return None
    gains, losses = [], []
    for prev, cur in zip(clean[:-1], clean[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def series_stats(points: Sequence[tuple[Any, Any]]) -> dict[str, Any]:
    """One dict of the numbers every SERIES answer quotes."""
    clean = [(_day(d), _f(v)) for d, v in points]
    clean = [(d, v) for d, v in clean if d is not None and v is not None]
    if not clean:
        return {"rows": 0}
    clean.sort(key=lambda item: item[0])
    first, last = clean[0][1], clean[-1][1]
    ret, _, _ = window_return([(d.isoformat(), v) for d, v in clean])
    hi, hi_date = extreme([(d.isoformat(), v) for d, v in clean], "max") or (None, None)
    lo, lo_date = extreme([(d.isoformat(), v) for d, v in clean], "min") or (None, None)
    return {
        "rows": len(clean),
        "start": clean[0][0].isoformat(),
        "end": clean[-1][0].isoformat(),
        "first": first,
        "last": last,
        "return_pct": ret,
        "high": hi,
        "high_date": hi_date,
        "low": lo,
        "low_date": lo_date,
        "max_drawdown_pct": max_drawdown([(d.isoformat(), v) for d, v in clean]),
    }


def flow_stats(rows: Sequence[Any]) -> dict[str, Any]:
    """Volume / delivery numbers over the window rows (``volume``, ``delivery_pct``)."""
    vols, deliv = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        vol, pct = _f(row.get("volume")), _f(row.get("delivery_pct"))
        if vol is not None:
            vols.append(vol)
        if pct is not None:
            deliv.append(pct)
    return {"volume_last": vols[-1] if vols else None,
            "volume_avg": (sum(vols) / len(vols)) if vols else None,
            "delivery_last": deliv[-1] if deliv else None,
            "delivery_avg": (sum(deliv) / len(deliv)) if deliv else None,
            "rows": len(vols)}


def days_within(points: Sequence[tuple[Any, Any]], pct: float) -> dict[str, Any] | None:
    """"How many sessions sat within ``pct``%% of the window high?"""
    clean = [(_day(d), _f(v)) for d, v in points]
    clean = [(d, v) for d, v in clean if d is not None and v is not None]
    if len(clean) < 2:
        return None
    clean.sort(key=lambda item: item[0])
    peak = max(v for _, v in clean)
    if peak <= 0:
        return None
    near = [(d, v) for d, v in clean if v >= peak * (1.0 - pct / 100.0)]
    return {"sessions": len(clean), "near": len(near),
            "share_pct": len(near) / len(clean) * 100.0,
            "first": near[0][0].isoformat() if near else None,
            "last": near[-1][0].isoformat() if near else None}


def drawdown_recoveries(points: Sequence[tuple[Any, Any]], threshold: float = 15.0,
                        runs: int = 3) -> list[dict[str, Any]] | None:
    """The last ``runs`` falls of >= ``threshold``%%: fall depth and sessions to regain."""
    clean = [(_day(d), _f(v)) for d, v in points]
    clean = [(d, v) for d, v in clean if d is not None and v is not None]
    if len(clean) < 20:
        return None
    clean.sort(key=lambda item: item[0])
    out: list[dict[str, Any]] = []
    peak_day, peak = clean[0][0], clean[0][1]
    trough_day, trough = peak_day, peak
    for day, value in clean:
        if value >= peak:
            if peak > 0 and trough < peak * (1.0 - threshold / 100.0):
                out.append({"peak": peak_day.isoformat(), "trough": trough_day.isoformat(),
                            "fall_pct": (trough / peak - 1.0) * 100.0,
                            "recovered": day.isoformat(),
                            "sessions": (day - trough_day).days})
            peak_day, peak = day, value
            trough_day, trough = day, value
        elif value < trough:
            trough_day, trough = day, value
    if peak > 0 and trough < peak * (1.0 - threshold / 100.0):
        out.append({"peak": peak_day.isoformat(), "trough": trough_day.isoformat(),
                    "fall_pct": (trough / peak - 1.0) * 100.0,
                    "recovered": None, "sessions": None})
    return out[-runs:] or None


def rsi_divergence(dated: Sequence[tuple[Any, Any, Any]], lookback: int = 120) -> dict[str, Any] | None:
    """Price lower low with RSI higher low (``dated`` = [(date, close, rsi)])."""
    clean = [(d, _f(c), _f(r)) for d, c, r in dated]
    clean = [row for row in clean if row[1] is not None and row[2] is not None]
    if len(clean) < 30:
        return None
    clean = clean[-lookback:]
    lows = [i for i in range(1, len(clean) - 1)
            if clean[i][1] <= clean[i - 1][1] and clean[i][1] <= clean[i + 1][1]]
    if len(lows) < 2:
        return None
    first, last = lows[-2], lows[-1]
    price_lower = clean[last][1] < clean[first][1]
    rsi_higher = clean[last][2] > clean[first][2]
    return {"first_low": str(clean[first][0])[:10], "last_low": str(clean[last][0])[:10],
            "price_lower_low": price_lower, "rsi_higher_low": rsi_higher,
            "divergence": bool(price_lower and rsi_higher),
            "rsi_first": clean[first][2], "rsi_last": clean[last][2]}
