"""The fixed SQL of the pilot3 core tables, one function per question shape (T-049 part A).

Every function takes the pilot3 connection and plain arguments and returns a list of candidates
``(value, native_unit, source_label)``: ``native_unit`` is one of ``inr`` (rupees), ``per_share``, ``pct``,
``count``, ``x``.  The oracle (``oracle.py``) maps each number of a stored answer onto one of these shapes;
nothing here calls a model.  ``as_of`` filters on ``known_at`` so a query cannot see a filing that was not out yet.
"""
from __future__ import annotations

import sqlite3

Cand = tuple[float, str, str]
PX_FIELDS = {"open", "high", "low", "close", "volume", "deliverable_qty", "delivery_pct", "adj_close", "prev_close"}
PX_UNIT = {"volume": "count", "deliverable_qty": "count", "delivery_pct": "pct"}


def _asof(as_of: str | None) -> tuple[str, tuple]:
    return (" AND substr(known_at,1,10) <= ?", (as_of,)) if as_of else ("", ())


# --- price_delivery ---------------------------------------------------------------------------------
def px_on(conn: sqlite3.Connection, symbol: str, day: str, field: str, exchange: str = "NSE") -> list[Cand]:
    """S-PX-DAY: one field on a date (the last trading day on or before it)."""
    assert field in PX_FIELDS
    row = conn.execute(
        f"SELECT {field}, date FROM price_delivery WHERE symbol=? AND exchange=? AND date<=? "
        f"AND {field} IS NOT NULL ORDER BY date DESC LIMIT 1", (symbol, exchange, day)).fetchone()
    return [(row[0], PX_UNIT.get(field, "inr" if field in ("open", "high", "low", "close", "adj_close", "prev_close") else "count"),
             f"price_delivery {exchange} {row[1]}")] if row else []


def px_extreme(conn: sqlite3.Connection, symbol: str, field: str, agg: str, start: str, end: str) -> list[Cand]:
    """S-PX-RANGE: MAX(high) / MIN(low) over a date range (calendar year to date, 52 weeks)."""
    assert agg in ("MAX", "MIN") and field in PX_FIELDS
    row = conn.execute(f"SELECT {agg}({field}) FROM price_delivery WHERE symbol=? AND exchange='NSE' "
                       f"AND date>? AND date<=?", (symbol, start, end)).fetchone()
    return [(row[0], "inr", f"price_delivery {agg}({field}) {start}..{end}")] if row and row[0] is not None else []


# --- fin_quarter_xbrl / ratio_panel ----------------------------------------------------------------
def fin_quarter(conn: sqlite3.Connection, symbol: str, period: str, item: str, basis: str,
                as_of: str | None = None) -> list[Cand]:
    """S-FQ: a reported quarterly line item, latest filing first."""
    extra, args = _asof(as_of)
    rows = conn.execute(
        "SELECT value, unit, known_at FROM fin_quarter_xbrl WHERE symbol=? AND fiscal_period=? AND basis=? "
        f"AND line_item=?{extra} ORDER BY known_at DESC", (symbol, period, basis, item, *args)).fetchall()
    return [(v, "per_share" if u == "inr_per_share" else "inr", f"fin_quarter_xbrl {basis} {period} {item} @{k[:10]}")
            for v, u, k in rows]


def ratio(conn: sqlite3.Connection, symbol: str, period: str, metric: str, basis: str,
          as_of: str | None = None) -> list[Cand]:
    """S-RATIO: a ratio_panel metric for a quarter (QnFYyy) or fiscal year (FYyy)."""
    extra, args = _asof(as_of)
    rows = conn.execute(
        "SELECT value, unit, known_at FROM ratio_panel WHERE symbol=? AND fiscal_period=? AND basis=? "
        f"AND metric=?{extra} ORDER BY known_at DESC", (symbol, period, basis, metric, *args)).fetchall()
    native = {"pct": "pct", "x": "x", "inr_per_share": "per_share", "inr": "inr"}
    return [(v, native.get(u, "inr"), f"ratio_panel {basis} {period} {metric} @{k[:10]}") for v, u, k in rows]


# --- fin_annual_line --------------------------------------------------------------------------------
def fin_annual(conn: sqlite3.Connection, symbol: str, fy: str, item: str, basis: str,
               as_of: str | None = None) -> list[Cand]:
    """S-FA: reported annual lines out of ar_facts; every distinct value is a candidate (restated rows keep both)."""
    extra, args = _asof(as_of)
    rows = conn.execute(
        "SELECT value, unit, scale, page, known_at FROM fin_annual_line WHERE symbol=? AND fiscal_year=? AND basis=? "
        f"AND line_item=?{extra} ORDER BY known_at DESC, page", (symbol, fy, basis, item, *args)).fetchall()
    out = []
    for v, u, s, page, k in rows:
        native = "pct" if u == "pct" else "per_share" if u == "inr_per_share" else "inr"
        value = v * s if native == "inr" else v
        out.append((value, native, f"fin_annual_line {basis} {fy} {item} p{page} @{k[:10]}"))
    return out


# --- shp_category -----------------------------------------------------------------------------------
def shp(conn: sqlite3.Connection, symbol: str, quarter_end: str, category: str, as_of: str | None = None,
        what: str = "pct") -> list[Cand]:
    """S-SHP: holding of a category at a quarter end (xbrl first, then the shp_index promoter/public row)."""
    extra, args = _asof(as_of)
    col = "pct" if what == "pct" else "shares"
    rows = conn.execute(
        f"SELECT {col}, source_kind, known_at FROM shp_category WHERE symbol=? AND quarter_end=? AND category=? "
        f"AND {col} IS NOT NULL{extra} ORDER BY (source_kind='xbrl') DESC, known_at DESC",
        (symbol, quarter_end, category, *args)).fetchall()
    return [(v, "pct" if what == "pct" else "count", f"shp_category {kind} {quarter_end} {category} @{k[:10]}")
            for v, kind, k in rows]


def shp_latest_quarter(conn: sqlite3.Connection, symbol: str, on_or_before: str) -> str | None:
    row = conn.execute("SELECT MAX(quarter_end) FROM shp_category WHERE symbol=? AND quarter_end<=?",
                       (symbol, on_or_before)).fetchone()
    return row[0] if row else None


# --- share_capital ----------------------------------------------------------------------------------
def shares(conn: sqlite3.Connection, symbol: str, day: str, field: str = "shares_outstanding",
           basis: str = "consolidated") -> list[Cand]:
    """S-SHARES: share count / paid-up / face value as filed by `day` (latest period_end at or before it)."""
    assert field in ("shares_outstanding", "paid_up_capital", "face_value")
    rows = conn.execute(
        f"SELECT {field}, as_of_date, known_at FROM share_capital WHERE symbol=? AND event IS NULL AND basis=? "
        f"AND {field} IS NOT NULL AND as_of_date<=? ORDER BY as_of_date DESC, known_at DESC LIMIT 3",
        (symbol, basis, day)).fetchall()
    native = {"shares_outstanding": "count", "paid_up_capital": "inr", "face_value": "per_share"}[field]
    return [(v, native, f"share_capital {basis} {d} @{k[:10]}") for v, d, k in rows]


# --- valuation_daily --------------------------------------------------------------------------------
def valuation(conn: sqlite3.Connection, symbol: str, day: str, field: str) -> list[Cand]:
    """S-VAL: a valuation_daily field on a trading day (the last one on or before `day`)."""
    assert field in ("close", "shares_outstanding", "market_cap", "trailing_eps", "trailing_pat", "pe", "pb",
                     "ev_ebitda", "trailing_ebitda", "net_worth", "net_debt", "dividend_yield_pct")
    row = conn.execute(f"SELECT {field}, date FROM valuation_daily WHERE symbol=? AND date<=? AND {field} IS NOT NULL "
                       f"ORDER BY date DESC LIMIT 1", (symbol, day)).fetchone()
    native = {"close": "inr", "shares_outstanding": "count", "market_cap": "inr", "trailing_eps": "per_share",
              "trailing_pat": "inr", "pe": "x", "pb": "x", "ev_ebitda": "x", "trailing_ebitda": "inr",
              "net_worth": "inr", "net_debt": "inr", "dividend_yield_pct": "pct"}[field]
    return [(row[0], native, f"valuation_daily {row[1]} {field}")] if row else []
