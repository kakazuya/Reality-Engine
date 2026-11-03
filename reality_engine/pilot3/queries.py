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
        native = ("pct" if u == "pct" else "per_share" if u == "inr_per_share" else "x" if u in ("x", "ratio")
                  else "days" if u == "days" else "inr")
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


# --- kpi_series: confidence-aware reads, growth, share, mix, book-to-bill, coverage (T-049 E) -----------------------
# A growth or share is a formula over stored rows, never an extracted value.  Every function reads the best-confidence
# rows of each (metric, dimension, period): table_row > table_chart > sentence > sentence_default (kpi_series.conf_rank).
import re as _re
from collections import Counter as _Counter

_PERIOD = _re.compile(r"^(?P<k>Q[1-4]|H[12]|[369]M|12M)?FY(?P<y>\d{2})$")


def prior_period(period: str, kind: str = "yoy") -> str | None:
    """Q1FY27 -> Q1FY26 (yoy) / Q4FY26 (qoq); FY26 -> FY25; H1FY27 -> H1FY26; None when there is no such period."""
    m = _PERIOD.match(period or "")
    if not m:
        return None
    k, y = m.group("k"), int(m.group("y"))
    if kind == "yoy":
        return f"{k or ''}FY{y - 1:02d}"
    if kind == "qoq" and k and k.startswith("Q"):
        q = int(k[1])
        return f"Q4FY{y - 1:02d}" if q == 1 else f"Q{q - 1}FY{y:02d}"
    return None


def kpi_value(conn: sqlite3.Connection, symbol: str, metric: str, period: str, dimension: str = "total",
              as_of: str | None = None, basis: str | None = None) -> list[Cand]:
    """The stored value(s) of a KPI: the highest-confidence tier that has the period, then the latest filing; within
    the tier every distinct value is a candidate, the most frequent first (a value several documents repeat)."""
    extra, args = _asof(as_of)
    b = " AND basis=?" if basis else ""
    rows = conn.execute(
        "SELECT value, unit, scale, conf_rank, confidence, known_at, doc_key, page, method FROM kpi_series "
        f"WHERE symbol=? AND metric=? AND dimension=? AND fiscal_period=?{b}{extra} "
        "ORDER BY conf_rank DESC, (method='text_layer') DESC, known_at DESC",
        (symbol, metric, dimension, period, *([basis] if basis else []), *args)).fetchall()
    if not rows:
        return []
    top = rows[0][3]
    tier = [r for r in rows if r[3] == top]
    if any(r[8] == "text_layer" for r in tier):       # a text-layer read beats an OCR read of the same tier
        tier = [r for r in tier if r[8] == "text_layer"]
    freq = _Counter(r[0] for r in tier)
    seen, out = set(), []
    for r in sorted(tier, key=lambda r: (-freq[r[0]], r[5] and -int(r[5][:10].replace("-", "") or 0))):
        if r[0] in seen:
            continue
        seen.add(r[0])
        out.append((r[0], r[1], f"kpi_series {r[4]} {symbol} {metric}/{dimension} {period} {r[6][-20:]} p{r[7]} @{(r[5] or '')[:10]}"))
    return out


def _one(c: list[Cand]) -> float | None:
    return c[0][0] if c else None


def kpi_growth(conn: sqlite3.Connection, symbol: str, metric: str, period: str, dimension: str = "total",
               kind: str = "yoy", as_of: str | None = None) -> list[Cand]:
    """F_KPI_YOY / F_KPI_QOQ: 100 * (value / value of the prior period - 1) from two stored rows."""
    prev = prior_period(period, kind)
    if not prev:
        return []
    cur, old = kpi_value(conn, symbol, metric, period, dimension, as_of), kpi_value(conn, symbol, metric, prev, dimension, as_of)
    if not cur or not old or not old[0][0]:
        return []
    return [(100.0 * (cur[0][0] / old[0][0] - 1.0), "pct", f"F_KPI_{kind.upper()} {metric}/{dimension} {period} vs {prev}")]


def _segments(conn: sqlite3.Connection, symbol: str, metric: str, period: str, as_of: str | None) -> dict[str, float]:
    dims = [r[0] for r in conn.execute(
        "SELECT DISTINCT dimension FROM kpi_series WHERE symbol=? AND metric=? AND fiscal_period=? AND dimension<>'total'",
        (symbol, metric, period))]
    out = {}
    for d in dims:
        v = _one(kpi_value(conn, symbol, metric, period, d, as_of))
        if v is not None:
            out[d] = v
    return out


def kpi_share(conn: sqlite3.Connection, symbol: str, metric: str, period: str, dimension: str,
              as_of: str | None = None) -> list[Cand]:
    """F_SHARE: 100 * segment / total; total = the stored 'total' row, else the sum of the segment rows."""
    seg = _segments(conn, symbol, metric, period, as_of)
    if dimension not in seg:
        return []
    tot = _one(kpi_value(conn, symbol, metric, period, "total", as_of))
    basis = "stored total" if tot else "sum of segments"
    tot = tot or sum(seg.values())
    if not tot:
        return []
    return [(100.0 * seg[dimension] / tot, "pct", f"F_SHARE {metric}/{dimension} {period} over {basis}")]


def kpi_mix(conn: sqlite3.Connection, symbol: str, metric: str, period: str, as_of: str | None = None) -> list[tuple[str, float]]:
    """F_MIX: {segment: 100 * value / sum of the segments}; the shares add to 100."""
    seg = _segments(conn, symbol, metric, period, as_of)
    tot = sum(seg.values())
    return sorted(((d, 100.0 * v / tot) for d, v in seg.items()), key=lambda t: -t[1]) if tot else []


def _revenue_cr(conn: sqlite3.Connection, symbol: str, period: str, basis: str = "consolidated",
                as_of: str | None = None, ttm: bool = False) -> float | None:
    """Revenue from operations in crore for a quarter or fiscal year (ratio_panel, filed results); ttm = last four quarters."""
    extra, args = _asof(as_of)

    def one(p: str) -> float | None:
        r = conn.execute("SELECT value, scale FROM ratio_panel WHERE symbol=? AND fiscal_period=? AND basis=? AND "
                         f"metric='revenue_from_operations'{extra} ORDER BY known_at DESC LIMIT 1", (symbol, p, basis, *args)).fetchone()
        return r[0] * (r[1] or 1.0) / 1e7 if r else None

    if ttm and period.startswith("Q"):
        qs, p = [], period
        for _ in range(4):
            v = one(p)
            if v is None:
                return None
            qs.append(v)
            p = prior_period(p, "qoq")
        return sum(qs)
    return one(period)


def book_to_bill(conn: sqlite3.Connection, symbol: str, period: str, dimension: str = "total",
                 as_of: str | None = None, basis: str = "consolidated") -> list[Cand]:
    """F_B2B: order intake / revenue from operations of the same period (crore on both sides)."""
    oi, rev = _one(kpi_value(conn, symbol, "order_intake", period, dimension, as_of)), _revenue_cr(conn, symbol, period, basis, as_of)
    return [(oi / rev, "x", f"F_B2B order_intake {period} / revenue {period}")] if oi and rev else []


def coverage_years(conn: sqlite3.Connection, symbol: str, period: str, dimension: str = "total",
                   as_of: str | None = None, basis: str = "consolidated") -> list[Cand]:
    """F_COVER: order book / revenue of the year (FY) or of the last four quarters (a quarter-end book), in years."""
    ob = _one(kpi_value(conn, symbol, "order_book", period, dimension, as_of))
    rev = _revenue_cr(conn, symbol, period, basis, as_of, ttm=period.startswith("Q"))
    return [(ob / rev, "x", f"F_COVER order_book {period} / revenue")] if ob and rev else []


def kpi_fy_sum(conn: sqlite3.Connection, symbol: str, metric: str, fy: str, dimension: str = "total",
               as_of: str | None = None) -> list[Cand]:
    """F_FY_SUM over KPI rows: a flow KPI (volume, revenue, order intake) of a fiscal year as the sum of its four stored
    quarters (best confidence each).  Empty unless all four quarters are stored."""
    m = _PERIOD.match(fy or "")
    if not m or m.group("k"):
        return []
    vals, unit = [], None
    for q in (1, 2, 3, 4):
        c = kpi_value(conn, symbol, metric, f"Q{q}FY{m.group('y')}", dimension, as_of)
        if not c:
            return []
        vals.append(c[0][0])
        unit = c[0][1]
    return [(sum(vals), unit, f"F_FY_SUM {metric}/{dimension} {fy} = Q1..Q4")]
