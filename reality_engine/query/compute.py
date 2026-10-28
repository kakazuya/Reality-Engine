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
