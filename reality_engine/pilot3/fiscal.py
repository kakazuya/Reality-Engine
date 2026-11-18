"""Fiscal year-end resolution and calendar helpers for pilot3 (T-223).

Most NSE/BSE companies close their fiscal year in March (``fy_end = 3``), while some close in December
(e.g. RSYSTEMS, ``fy_end = 12``) or another month.  The FY label is always the calendar year in which the
fiscal year ends (e.g. Jan-Dec 2025 is ``FY25``; Apr 2025-Mar 2026 is ``FY26``).

Each per-symbol build loop sets ``with fiscal.use(fiscal.fy_end_month(conn, symbol)):`` so deep helpers
that only receive a date string read ``fiscal.current()`` without signature churn.
"""
from __future__ import annotations

import calendar
from collections import Counter
from contextlib import contextmanager
import os
import re
import sqlite3
import threading

_MONTHS: dict[str, int] = {
    name: idx
    for idx, name in enumerate(
        (
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ),
        start=1,
    )
}

_YEAR_ENDED_RX = re.compile(
    r"year\s+ended\s+(?:on\s+)?(?:the\s+)?"
    r"(?:(\d{1,2})(?:st|nd|rd|th)?[\s,]+)?"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:[\s,]+(\d{1,2})(?:st|nd|rd|th)?)?",
    re.IGNORECASE,
)

_CACHE: dict[tuple[str, str], int] = {}
_CACHE_LOCK = threading.Lock()
_LOCAL = threading.local()


def _stack() -> list[int]:
    stack = getattr(_LOCAL, "stack", None)
    if stack is None:
        stack = [3]
        _LOCAL.stack = stack
    return stack


def current() -> int:
    """Active fiscal year-end month (1..12), defaulting to 3 (March)."""
    return _stack()[-1]


@contextmanager
def use(fy_end: int):
    """Set the active fiscal year-end month for the current thread's dynamic scope."""
    month = int(fy_end)
    if not 1 <= month <= 12:
        raise ValueError(f"fy_end must be in 1..12, got {fy_end!r}")
    stack = _stack()
    stack.append(month)
    try:
        yield month
    finally:
        stack.pop()


def clear_cache() -> None:
    """Clear the ``fy_end_month`` cache (intended for tests)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _db_file_key(conn: sqlite3.Connection) -> str:
    try:
        for _seq, name, path in conn.execute("PRAGMA database_list"):
            if name == "main" and path:
                return os.path.normcase(os.path.abspath(path))
    except sqlite3.Error:
        pass
    return ""


def fy_end_month(conn: sqlite3.Connection | None, symbol: str) -> int:
    """Detect a company's fiscal year-end month from pages 1-3 of its annual reports and results.

    Returns the modal month of ``year ended ... <Month>`` hits when it has at least 3 hits and at least
    60% share of all hits; otherwise falls back to 3 (March).  Cached per ``(database file, symbol)``.
    """
    if conn is None or not symbol:
        return 3
    db_key = _db_file_key(conn)
    if db_key:
        with _CACHE_LOCK:
            cached = _CACHE.get((db_key, symbol))
        if cached is not None:
            return cached

    counts: Counter[int] = Counter()
    try:
        rows = conn.execute(
            "SELECT p.text FROM doc_page p "
            "JOIN doc d ON d.doc_key = p.doc_key "
            "WHERE d.symbol = ? AND d.doc_type IN ('annual_report', 'results') AND p.page BETWEEN 1 AND 3",
            (symbol,),
        ).fetchall()
    except sqlite3.Error:
        return 3

    for (text,) in rows:
        if not text:
            continue
        for match in _YEAR_ENDED_RX.finditer(text):
            counts[_MONTHS[match.group(2).lower()]] += 1

    total = sum(counts.values())
    result = 3
    if total > 0:
        best_month, best_hits = counts.most_common(1)[0]
        if best_hits >= 3 and best_hits / total >= 0.6:
            result = best_month

    if db_key:
        with _CACHE_LOCK:
            _CACHE[(db_key, symbol)] = result
    return result


def _resolve_fy_end(fy_end: int | None) -> int:
    month = current() if fy_end is None else int(fy_end)
    if not 1 <= month <= 12:
        raise ValueError(f"fy_end must be in 1..12, got {fy_end!r}")
    return month


def march_equivalent_month(m: int, fy_end: int | None = None) -> int:
    """Map a calendar month ``m`` (1..12) to its equivalent month under a March year-end.

    Example for ``fy_end = 12``: Mar (3) -> 6, Jun (6) -> 9, Sep (9) -> 12, Dec (12) -> 3.
    """
    fe = _resolve_fy_end(fy_end)
    return ((int(m) - fe + 2) % 12) + 1


def _fy_end_calendar_year(period_end: str, fe: int) -> int:
    y, m = int(period_end[:4]), int(period_end[5:7])
    return y + 1 if m > fe else y


def fy_label(period_end: str, fy_end: int | None = None) -> str:
    """Fiscal-year label (e.g. ``'FY26'``) for ``period_end`` (year in which the fiscal year ends)."""
    fe = _resolve_fy_end(fy_end)
    fy = _fy_end_calendar_year(period_end, fe)
    return f"FY{fy % 100:02d}"


def fy_start(period_end: str, fy_end: int | None = None) -> str:
    """First day (``'YYYY-MM-01'``) of the fiscal year containing ``period_end``."""
    fe = _resolve_fy_end(fy_end)
    fy = _fy_end_calendar_year(period_end, fe)
    start_month = (fe % 12) + 1
    start_year = fy if fe == 12 else fy - 1
    return f"{start_year:04d}-{start_month:02d}-01"


def fy_end_date(fy_label_or_year: str | int, fy_end: int | None = None) -> str:
    """Last day (``'YYYY-MM-DD'``) of a fiscal year given as ``'FY26'`` or ``2026``."""
    fe = _resolve_fy_end(fy_end)
    if isinstance(fy_label_or_year, str):
        ye = 2000 + int(fy_label_or_year[-2:])
    else:
        ye = int(fy_label_or_year)
    last_day = calendar.monthrange(ye, fe)[1]
    return f"{ye:04d}-{fe:02d}-{last_day:02d}"


def fy_bounds(fy_label_or_year: str | int, fy_end: int | None = None) -> tuple[str, str]:
    """``(fy_start, fy_end)`` ISO dates for a fiscal year label such as ``'FY26'``."""
    end = fy_end_date(fy_label_or_year, fy_end)
    return fy_start(end, fy_end), end


def fiscal_quarter(period_end: str, fy_end: int | None = None) -> str | None:
    """Quarter label (e.g. ``'Q1FY26'``) counted from the fiscal year start, or ``None`` if invalid."""
    try:
        y, m = int(period_end[:4]), int(period_end[5:7])
    except (TypeError, ValueError, IndexError):
        return None
    if not 1 <= m <= 12:
        return None
    fe = _resolve_fy_end(fy_end)
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(march_equivalent_month(m, fe))
    if q is None:
        return None
    fy = y + 1 if m > fe else y
    return f"Q{q}FY{fy % 100:02d}"


def ytd_label(period_end: str, months: int, fy_end: int | None = None) -> str | None:
    """Year-to-date label (``'H1FY26'``, ``'9MFY26'``, ``'FY26'``) for ``period_end`` and span ``months``."""
    fe = _resolve_fy_end(fy_end)
    fy = fy_label(period_end, fe)
    if months == 12:
        return fy
    if months == 6:
        eq = march_equivalent_month(int(period_end[5:7]), fe)
        return f"H{2 if eq == 3 else 1}{fy}"
    if months == 9:
        return f"9M{fy}"
    if months == 3:
        return fiscal_quarter(period_end, fe)
    return None


def last_fy_end(period_end: str, fy_end: int | None = None) -> str:
    """Last day (``'YYYY-MM-DD'``) of the last completed fiscal year strictly before ``period_end``."""
    fe = _resolve_fy_end(fy_end)
    y, m = int(period_end[:4]), int(period_end[5:7])
    lfy_year = y - 1 if m <= fe else y
    last_day = calendar.monthrange(lfy_year, fe)[1]
    return f"{lfy_year:04d}-{fe:02d}-{last_day:02d}"
