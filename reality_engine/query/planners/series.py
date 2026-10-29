"""SERIES: dated price/index/commodity rows plus the arithmetic the ask names.

Reads the DuckDB primary series (``px_daily``, adjusted closes) when the dated
snapshot is present, falls back to ``daily_price_delivery`` (raw, indexed).
PIT is always ``date <= as_of`` in the SQL.
"""
from __future__ import annotations

import re
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, in_period, isin_of
from .facts import _t1_rows

CHECKED = ["truth_duckdb.px_daily", "equity_intelligence.daily_price_delivery",
           "equity_intelligence.mkt_nse_index_daily",
           "equity_intelligence.mkt_commodity_daily"]

INDEXES = ["Nifty 50", "Nifty Bank", "Nifty IT", "Nifty Energy", "Nifty Metal", "Nifty Auto",
           "Nifty FMCG", "Nifty Pharma", "Nifty Realty", "Nifty PSU Bank",
           "Nifty Private Bank", "Nifty Financial Services", "Nifty Midcap 100",
           "Nifty Smallcap 100", "Nifty 500", "Nifty 200", "Nifty Next 50",
           "Nifty India Defence", "Nifty Infrastructure", "Nifty Consumer Durables",
           "Nifty Oil & Gas", "India VIX"]
COMMODITIES = [("crude palm", "crude_palm"), ("brent", "crude_brent"), ("crude", "crude_brent"),
               ("copper", "copper"), ("usdinr", "usdinr"), ("rupee", "usdinr"),
               ("gold", "gold"), ("silver", "silver"), ("zinc", "zinc"),
               ("alumin", "aluminium"), ("coal", "coal_newcastle"),
               ("natural gas", "natural_gas"), ("steel", "steel_hrc_us"),
               ("iron ore", "iron_ore_62"), ("platinum", "platinum")]


def indexes_in(question: str) -> list[str]:
    low = question.lower()
    return [name for name in INDEXES if name.lower() in low][:3]


def commodity_in(question: str) -> str | None:
    low = question.lower()
    for key, code in COMMODITIES:
        if key in low:
            return code
    return None


def _stock_duck(ctx: Any, isin: str | None, symbol: str | None, start: str,
                end: str) -> list[dict[str, Any]]:
    where, params = ("isin = ?", [isin]) if isin else ("upper(symbol) = upper(?)", [symbol])
    return ctx.duck_rows(
        "SELECT date, close, adj_close, high, adj_high, low, adj_low, volume, delivery_pct "
        f"FROM px_daily WHERE {where} AND date >= ? AND date <= ? ORDER BY date",
        [*params, start, end])


def _stock_sqlite(ctx: Any, isin: str | None, symbol: str | None, start: str,
                  end: str) -> list[dict[str, Any]]:
    where, params = ("isin = ?", [isin]) if isin else ("upper(symbol) = upper(?)", [symbol])
    return ctx.rows(
        "equity_intelligence",
        "SELECT date, close, close AS adj_close, high, high AS adj_high, low, low AS adj_low, "
        "total_volume AS volume, delivery_pct FROM daily_price_delivery "
        f"WHERE {where} AND date >= ? AND date <= ? ORDER BY date", [*params, start, end])


def _index_rows(ctx: Any, name: str, start: str, end: str) -> list[dict[str, Any]]:
    return ctx.rows(
        "equity_intelligence",
        "SELECT date, close, close AS adj_close, high, high AS adj_high, low, low AS adj_low, "
        "pct_change FROM mkt_nse_index_daily WHERE lower(index_name) = lower(?) "
        "AND date >= ? AND date <= ? ORDER BY date", (name, start, end))


def _index_day_ranking(ctx: Any, day: str) -> list[dict[str, Any]]:
    """Every Nifty index's move on one session, worst first (PIT date = as_of)."""
    return ctx.rows(
        "equity_intelligence",
        "SELECT index_name, pct_change, close FROM mkt_nse_index_daily "
        "WHERE date = ? AND pct_change IS NOT NULL ORDER BY pct_change ASC LIMIT 8",
        (day,))


def _commodity_rows(ctx: Any, code: str, start: str, end: str) -> list[dict[str, Any]]:
    return ctx.rows(
        "equity_intelligence",
        "SELECT date, COALESCE(adj_close, close) AS adj_close, close, high AS adj_high, "
        "low AS adj_low FROM mkt_commodity_daily WHERE (lower(commodity) = lower(?) OR "
        "lower(ticker) = lower(?)) AND date >= ? AND date <= ? ORDER BY date",
        (code, code, start, end))


def _points(rows: list[dict[str, Any]], key: str = "adj_close") -> list[tuple[str, float]]:
    return [(str(r.get("date") or "")[:10], r.get(key))
            for r in rows if r.get(key) is not None]


def _row_period(stats: dict[str, Any]) -> str | None:
    """The window a series row is about, shown to the gate (never the as_of day)."""
    start, end = stats.get("start"), stats.get("end")
    if start and end:
        return start if start == end else f"{start}..{end}"
    return stats.get("data_end")


def _series_rows(stats: dict[str, Any],
                 ident: dict[str, tuple[str | None, str | None]],
                 as_of: str, fallback_period: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for name in stats:
        value = stats[name]
        period = _row_period(value) if isinstance(value, dict) else fallback_period
        row = {"ref": name, "known_at": as_of, "period": period, "stats": value}
        isin, symbol = ident.get(name, (None, None))
        if isin:
            row["isin"] = isin
        if symbol:
            row["symbol"] = symbol
        rows.append(row)
    return rows


def _flow_line(item: list[str], line: str, rows: list[dict[str, Any]] | None,
               want_volume: bool, want_delivery: bool) -> tuple[list[str], str]:
    """Add the volume/delivery the ask names, and label the row with them.

    A row must say what it reports: the gate judges the row it is shown, so a
    close row that also quotes volume has to name volume.
    """
    if not rows or not (want_volume or want_delivery):
        return item, line
    flow = compute.flow_stats(rows)
    if want_volume and flow.get("volume_last") is not None:
        line += (f", volume {fmt_num(flow['volume_last'])} {fmt_num(flow['volume_avg'])} "
                 f"average over {flow['rows']} sessions")
        item.append("volume")
    if want_delivery and flow.get("delivery_last") is not None:
        line += (f", delivery {flow['delivery_last']:.1f}% "
                 f"({flow['delivery_avg']:.1f}% average)")
        item.append("delivery")
    return item, line


def _valuation(ctx: Any, isin: str | None, as_of: str) -> dict[str, Any] | None:
    """P/E, P/B and market cap over held data: close, TTM EPS and filed net worth.

    ``company_state_daily`` carries the close, the market cap and the share count
    on a PIT date; ``company_metric_series`` carries the filed EPS (per share) and
    net worth (crore) with their own ``known_at``.  P/E uses the trailing four
    quarters; P/B is market cap over the latest filed net worth.  Either ratio is
    returned only when both of its inputs are held.
    """
    if not isin:
        return None
    try:
        state = _t1_rows(
            ctx, "market_state",
            "SELECT date, close, mcap_cr, shares_out FROM company_state_daily "
            "WHERE isin = ? AND date <= ? ORDER BY date DESC LIMIT 1", (isin, as_of))
        eps = _t1_rows(
            ctx, "facts_pilot",
            "SELECT period_end, value FROM company_metric_series "
            "WHERE isin = ? AND metric_key = 'eps' AND unit = 'INR_PER_SHARE' "
            "AND basis = 'consolidated' AND known_at <= ? "
            "ORDER BY period_end DESC, known_at DESC LIMIT 12", (isin, as_of))
        worth = _t1_rows(
            ctx, "facts_pilot",
            "SELECT period_end, value FROM company_metric_series "
            "WHERE isin = ? AND metric_key = 'net_worth' AND unit = 'INR_CRORE' "
            "AND basis = 'consolidated' AND known_at <= ? "
            "ORDER BY period_end DESC, known_at DESC LIMIT 4", (isin, as_of))
    except Exception:  # noqa: BLE001 - the T1 build is optional in a plain data root
        return None
    if not state:
        return None
    day = state[0]
    close, mcap = day.get("close"), day.get("mcap_cr")
    stats: dict[str, Any] = {"price_date": day.get("date"), "close": close,
                             "mcap_cr": mcap, "shares_out": day.get("shares_out")}
    parts = []
    if mcap:
        parts.append(f"market cap {fmt_num(mcap)} crore on {day.get('date')}")
    by_period: dict[str, Any] = {}
    for row in eps:
        by_period.setdefault(str(row.get("period_end")), row.get("value"))
    quarters = [value for _, value in sorted(by_period.items(), reverse=True)[:4]]
    if len(quarters) == 4 and close:
        ttm = sum(float(v) for v in quarters if v is not None)
        if ttm:
            stats.update({"eps_ttm": ttm, "pe": float(close) / ttm,
                          "eps_periods": sorted(by_period)[-1]})
            parts.append(f"P/E {float(close) / ttm:.1f} (close {fmt_num(close)} / trailing "
                         f"4-quarter EPS {ttm:.2f})")
    if worth and mcap and worth[0].get("value"):
        net_worth = float(worth[0]["value"])
        if net_worth > 0:
            stats.update({"net_worth_cr": net_worth,
                          "book_value_per_share": (net_worth * 1e7 / day["shares_out"]
                                                   if day.get("shares_out") else None),
                          "pb": float(mcap) / net_worth,
                          "net_worth_period": worth[0].get("period_end")})
            label = (f"P/B {float(mcap) / net_worth:.2f} (market cap {fmt_num(mcap)} crore / "
                     f"net worth {fmt_num(net_worth)} crore at {worth[0].get('period_end')})")
            if stats["book_value_per_share"]:
                label += f", book value per share {stats['book_value_per_share']:.1f}"
            parts.append(label)
    if not parts:
        return None
    return {"detail": "; ".join(parts), "stats": stats}


VALUATION_ASK = re.compile(
    r"\bp/b\b|\bpb\b|price to book|book value|\bp/e\b|\bpe\b|pe ratio|price to earnings|"
    r"market cap|valuation|ev/ebitda|ev/sales", re.I)


def _valuation_row(ctx: Any, slots: dict[str, Any], as_of: str,
                   question: str) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    """(detail, stats, row) when the ask names a valuation ratio it can compute."""
    # "book-value date" / "P/B-vs-P/E" spell the ratio with a hyphen; normalise it
    # so a follow-up "state the book-value date" still reads the valuation block.
    if not VALUATION_ASK.search((question or "").replace("-", " ")):
        return None
    valuation = _valuation(ctx, slots.get("isin") or isin_of(slots, ctx, as_of), as_of)
    if not valuation:
        return None
    row = {"ref": str(slots.get("symbol") or slots.get("isin") or ""),
           "item": _valuation_label(valuation["stats"]),
           "known_at": as_of, "stats": valuation["stats"]}
    return valuation["detail"], valuation["stats"], row


def _valuation_label(stats: dict[str, Any]) -> str:
    """Only the ratios the row actually reports (a row may not claim an uncomputed one)."""
    labels = [name for key, name in (("pe", "P/E"), ("pb", "P/B")) if key in stats]
    if stats.get("book_value_per_share"):
        labels.append("book value per share")
    if stats.get("mcap_cr"):
        labels.append("market cap")
    return ", ".join(labels) or "valuation"


def _history(ctx: Any, symbol: str, as_of: str) -> list[tuple[str, float]]:
    """The company's whole held daily close history (studies, not the routed window)."""
    if not symbol:
        return []
    try:
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT date, close FROM daily_price_delivery WHERE symbol = ? AND date <= ? "
            "AND close IS NOT NULL ORDER BY date LIMIT 6000", (symbol.upper(), as_of))
    except Exception:  # noqa: BLE001 - a missing store is a degraded study
        return []
    return [(str(r["date"])[:10], r["close"]) for r in rows if r.get("close") is not None]


def _pct_asked(question: str, default: float) -> float:
    """The percentage an ask names for a move/drawdown ("15% below its high")."""
    hits = [float(x) for x in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", question or "")]
    return hits[-1] if hits else default


def _rsi_study(ctx: Any, symbol: str, as_of: str) -> dict[str, Any] | None:
    """Oversold days (RSI<30) and the 20-session forward return after each."""
    if not symbol:
        return None
    try:
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT date, rsi_14, close FROM daily_price_delivery "
            "WHERE symbol = ? AND date <= ? AND rsi_14 IS NOT NULL "
            "ORDER BY date LIMIT 4000", (symbol.upper(), as_of))
    except Exception:
        return None
    if len(rows) < 60:
        return None
    closes = [float(r["close"]) for r in rows]
    oversold = [i for i, r in enumerate(rows) if r["rsi_14"] and float(r["rsi_14"]) < 30]
    fwd = [compute.growth(closes[i], closes[i + 20])
           for i in oversold if i + 20 < len(closes)]
    fwd = [x for x in fwd if x is not None]
    last_rsi = float(rows[-1]["rsi_14"]) if rows[-1]["rsi_14"] is not None else None
    return {
        "last_rsi": last_rsi,
        "last_rsi_percentile": compute.percentile(
            [float(r["rsi_14"]) for r in rows if r["rsi_14"] is not None], last_rsi),
        "oversold_days": len(oversold),
        "forward_20d_avg_pct": (sum(fwd) / len(fwd)) if fwd else None,
        "forward_20d_positive_pct": (sum(1 for x in fwd if x > 0) / len(fwd) * 100) if fwd else None,
        "samples": len(fwd),
        "data_end": str(rows[-1]["date"])[:10],
    }


def _flow_fallback(ctx: Any, isin: str | None, symbol: str | None, start: str,
                   end: str) -> list[dict[str, Any]]:
    """Delivery/volume rows from the live store when the price snapshot has them NULL.

    The DuckDB snapshot carries close/high/low for every ISIN but its delivery
    columns are NULL for thin names; ``daily_price_delivery`` (NSE + BSE, indexed
    on symbol/ISIN/date) holds the delivered quantity and percent.
    """
    key = isin if isin else symbol
    if not key:
        return []
    where = "isin = ?" if isin else "upper(symbol) = upper(?)"
    try:
        return ctx.rows(
            "equity_intelligence",
            "SELECT date, total_volume AS volume, delivery_pct FROM daily_price_delivery "
            f"WHERE {where} AND date >= ? AND date <= ? ORDER BY date",
            (key, start, end))
    except Exception:  # noqa: BLE001 - a missing delivery table is a degraded label
        return []


_MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_SPAN_RE = re.compile(
    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*[-–—]\s*"
    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})", re.I)


def _study_window(question: str, as_of: str) -> tuple[str, str, str] | None:
    """The window the ask's own high/low names, when it is not the routed one."""
    from datetime import date, timedelta
    text = question or ""
    match = _SPAN_RE.search(text)
    if match:
        year = int(match.group(5))
        low = f"{year}-{_MONTH_NUM[match.group(2).lower()[:3]]:02d}-{int(match.group(1)):02d}"
        high = f"{year}-{_MONTH_NUM[match.group(4).lower()[:3]]:02d}-{int(match.group(3)):02d}"
        return (min(low, high), max(low, high), "asked span")
    from ..router import parse_dates
    days = parse_dates(text)
    low_text = text.lower()
    # "As of 30 June 2026, what was the YTD high in 2026" names the window END, not
    # the window: the YTD/52-week form wins over the single parsed date.
    end = days[0] if days else as_of
    if re.search(r"52[- ]week", low_text):
        return ((date.fromisoformat(end) - timedelta(days=365)).isoformat(), end,
                "52 weeks")
    if re.search(r"\bytd\b|year[- ]to[- ]date", low_text):
        return f"{end[:4]}-01-01", end, "YTD"
    if re.search(r"all[- ]time|record high|record low", low_text):
        return "1900-01-01", end, "held history"
    if len(days) >= 2:
        return min(days), max(days), "asked span"
    if days:
        return days[0], days[0], "asked date"
    return None


def _range_study(ctx: Any, slots: dict[str, Any], as_of: str,
                 question: str) -> tuple[str, dict[str, Any]] | None:
    """The high/low the ask itself names, over the company's own held closes.

    "MMP's YTD high in 1 January-30 September 2026" is a window the router's
    single named date does not carry; the study reads the ask's own window so the
    row can name the high and its date (a close row cannot).
    """
    window = _study_window(question, as_of)
    if not window:
        return None
    history = _history(ctx, str(slots.get("symbol") or ""), as_of)
    if not history:
        return None
    low, high, label = window
    points = [(day, value) for day, value in history if low <= day <= high]
    stats = compute.series_stats(points)
    if not stats.get("rows"):
        return None
    detail = (f"{label} high {fmt_num(stats['high'])} ({stats['high_date']}), "
              f"low {fmt_num(stats['low'])} ({stats['low_date']}) over "
              f"{stats['rows']} sessions ({stats['start']}..{stats['end']})")
    row = {"ref": str(slots.get("symbol") or slots.get("isin") or ""),
           "item": "high, low", "period": stats["end"], "known_at": as_of,
           "isin": slots.get("isin"), "symbol": slots.get("symbol"),
           "stats": dict(stats, study=label, window_low=low, window_high=high)}
    return detail, row


BAND_ASK = re.compile(r"\b(price band|band|circuit|base price)\b", re.I)
LISTING_ASK = re.compile(r"\b(listing|listed|ipo|initial public offer|prospectus|grey market)\b",
                         re.I)


def _listing_study(ctx: Any, slots: dict[str, Any], as_of: str,
                   question: str) -> tuple[str, dict[str, Any]] | None:
    """The listing date / first trade the ask names, from the security master."""
    if not LISTING_ASK.search(question or ""):
        return None
    isin, symbol = slots.get("isin"), str(slots.get("symbol") or "")
    if not isin and not symbol:
        return None
    where, params = ("isin = ?", (isin,)) if isin else ("upper(nse_symbol) = upper(?)",
                                                       (symbol,))
    try:
        row = ctx.one(
            "equity_intelligence",
            f"SELECT isin, nse_symbol, nse_listing_date, first_trade FROM security_master "
            f"WHERE {where} LIMIT 1", params)
    except Exception:  # noqa: BLE001 - the identity store is optional
        return None
    if not row:
        return None
    listing = str(row.get("nse_listing_date") or "")[:10]
    first = str(row.get("first_trade") or "")[:10]
    if not listing and not first:
        return None
    detail = (f"listing date {listing or 'n/a'}"
              + (f", first trade {first}" if first else ""))
    day = str(slots.get("date_to") or as_of)[:10]
    out = {"ref": f"security_master:{row.get('isin')}", "item": "listing date, first trade",
           "period": day, "known_at": as_of, "isin": row.get("isin"),
           "symbol": row.get("nse_symbol") or slots.get("symbol"),
           "value": listing or first}
    return detail, out


def _band_study(ctx: Any, slots: dict[str, Any], as_of: str,
                start: str, end: str) -> tuple[str, list[dict[str, Any]], list[str]] | None:
    """The price band the exchange applied, and how often a close sat on it.

    ``price_bands`` is the live NSE series (band 2/5/10/20/40 or "No Band"); the
    same sessions' high/close decide an "upper band" close (close == high with a
    real limit).  The series is sparse and ends before the snapshot date, so the
    latest held band rows are returned with their own dates rather than passed off
    as the asked date.
    """
    from datetime import date, timedelta
    isin, symbol = slots.get("isin"), str(slots.get("symbol") or "")
    if not symbol:
        return None  # price_bands is symbol-keyed
    anchor = min(str(end or as_of)[:10], str(as_of)[:10])
    degraded: list[str] = []
    try:
        floor = (date.fromisoformat(anchor) - timedelta(days=60)).isoformat()
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT date, band, remarks FROM price_bands WHERE upper(symbol) = upper(?) "
            "AND date >= ? AND date <= ? ORDER BY date", (symbol, floor, anchor))
    except Exception:  # noqa: BLE001 - a missing band series is a degraded study
        return None
    if not rows:
        try:
            rows = ctx.rows(
                "equity_intelligence",
                "SELECT date, band, remarks FROM price_bands WHERE upper(symbol) = upper(?) "
                "AND date <= ? ORDER BY date DESC LIMIT 20", (symbol, anchor))
            rows = list(reversed(rows))
            if rows:
                degraded.append(f"no band row within 60 days of {anchor}; latest held is "
                                f"{rows[-1]['date']}")
        except Exception:  # noqa: BLE001
            return None
    if not rows:
        return None
    latest = rows[-1]
    band = str(latest.get("band") or "").strip()
    if not band:
        return None
    label = f"price band {band}%" if band.isdigit() else f"price band {band}"
    # Upper-band closes among the returned sessions: a close at the day's high
    # while a real circuit is in force is a sealed upper limit.
    upper = None
    if re.search(r"upper|circuit|hit|stuck|closed", str(slots.get("question") or ""), re.I):
        day_where = "isin = ?" if isin else "upper(symbol) = upper(?)"
        try:
            days = ctx.rows(
                "equity_intelligence",
                "SELECT date, close, high FROM daily_price_delivery WHERE "
                + day_where + " AND date >= ? AND date <= ?",
                ((isin if isin else symbol), rows[0]["date"], rows[-1]["date"]))
        except Exception:  # noqa: BLE001
            days = []
        limits = {str(r["date"]): str(r.get("band") or "") for r in rows}
        upper = sum(1 for day in days
                    if day.get("high") is not None and day.get("close") is not None
                    and float(day["close"]) >= float(day["high"])
                    and limits.get(str(day["date"]), "No Band") not in ("", "No Band"))
    detail = f"{label} on {latest['date']}"
    if len(rows) > 1:
        changed = rows[0]["band"] != latest["band"]
        detail += (f" ({rows[0]['date']} band {rows[0]['band']}"
                   f"{' -> ' if changed else ', unchanged'}"
                   f"{latest['band'] if changed else ''}; {len(rows)} band sessions held)")
    if upper is not None:
        detail += f", upper-band closes {upper} of {len(rows)} band sessions"
    out = [{"ref": f"price_bands:{symbol}", "item": label,
            "period": latest["date"], "known_at": as_of,
            "isin": slots.get("isin"), "symbol": slots.get("symbol"),
            "value": band}]
    if upper is not None:
        out.append({"ref": f"price_bands:{symbol}", "item": "upper-band closes",
                    "period": latest["date"], "known_at": as_of,
                    "isin": slots.get("isin"), "symbol": slots.get("symbol"),
                    "value": upper})
    return detail, out, degraded


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    question = str(slots.get("question") or "")
    metric = slots.get("metric")
    status = str(slots.get("status") or "")
    feed = status.split(":", 1)[-1] if status.startswith("needs_new_fetch:") else None
    if re.search(r"max pain|maxpain|\bpcr\b|open interest|oi buildup", question, re.I) and feed:
        detail = f"the question needs {feed}, which is not held"
        return envelope("SERIES", ok=False, why="tool", checked=CHECKED, gap=feed,
                        detail=detail, nid_reason=f"BLOCKED_TOOL: {feed}")
    if re.search(r"tracking error|inav|iNAV", question, re.I):
        detail = "tracking error needs a daily iNAV series; only one premium snap per date is held"
        return envelope("SERIES", ok=False, why="schema", checked=CHECKED, gap="etf_inav_daily",
                        detail=detail, nid_reason=detail)
    if re.search(r"listing[- ]day|listing pop|listing-day return", question, re.I):
        detail = ("the listing-day return needs the issue price; the price series starts at the "
                  "first close, so the pop cannot be computed from held data")
        return envelope("SERIES", ok=False, why="schema", checked=CHECKED, gap="ipo_issue_price",
                        detail=detail, nid_reason=detail)
    if not slots.get("needs", {}).get("price") and metric not in {"return", "cagr", "range",
                                                                 "band", "volume", "delivery"}:
        return envelope("SERIES", ok=True, na=True, checked=CHECKED,
                        detail="no dated series asked; SERIES not applicable")
    start = slots.get("date_from") or as_of
    end = min(slots.get("date_to") or as_of, as_of)
    if start > end:
        start, end = end, start
    degraded: list[str] = []
    series: dict[str, list[tuple[str, float]]] = {}
    raw: dict[str, list[tuple[str, float]]] = {}
    ident: dict[str, tuple[str | None, str | None]] = {}
    flows: dict[str, list[dict[str, Any]]] = {}

    names = indexes_in(question)
    commodity = commodity_in(question)
    # The asked entity owns the series: a commodity or index word in the question
    # ("gold", "copper", "Nifty 50") is context, not the subject.  Reading the
    # commodity instead of the stock is the GOLD leak the entity gate caught.
    keys = [str(s) for s in (slots.get("symbols") or [])
            if not str(s).startswith("IN")][:4]
    if not keys and slots.get("isin"):
        keys = [str(slots["isin"])]
    if not keys and slots.get("symbol"):
        keys = [str(slots["symbol"])]
    try:
        if keys:
            for key in keys:
                isin = key if key.startswith("IN") else (
                    slots.get("isin") if len(keys) == 1 else isin_of({"symbol": key}, ctx, as_of))
                symbol = None if key.startswith("IN") else key.upper()
                rows: list[dict[str, Any]] = []
                try:
                    rows = _stock_duck(ctx, isin, symbol, start, end)
                except Exception as exc:  # noqa: BLE001 - missing snapshot is degraded
                    degraded.append(f"duckdb snapshot unavailable ({type(exc).__name__}); raw closes")
                if not rows:
                    try:
                        rows = _stock_sqlite(ctx, isin, symbol, start, end)
                    except Exception:
                        rows = []
                points = _points(rows)
                if points:
                    series[key] = points
                    raw[key] = _points(rows, "close")
                    ident[key] = (isin, symbol)
                    flows[key] = [dict(row) for row in rows]
            if re.search(r"\bnifty\b|benchmark|relative strength", question, re.I):
                bench = _points(_index_rows(ctx, "Nifty 50", start, end))
                if bench:
                    series["Nifty 50"] = bench
        elif names:
            for name in names:
                rows = _index_rows(ctx, name, start, end)
                series[name] = _points(rows)
        elif commodity:
            rows = _commodity_rows(ctx, commodity, start, end)
            series[commodity] = _points(rows)
        else:
            return envelope("SERIES", ok=False, na=True, checked=CHECKED,
                            detail="no entity for a price series",
                            nid_reason="gate G1: no symbol/ISIN to price")
    except Exception as exc:  # noqa: BLE001
        return envelope("SERIES", ok=False, why="tool", checked=CHECKED,
                        detail=f"series store failed: {type(exc).__name__}: {exc}")

    series = {k: v for k, v in series.items() if v}
    if not series:
        # A P/B or market-cap ask still answers when the routed price window is
        # empty but the T1 state carries a PIT close and a filed book value.
        valuation_hit = _valuation_row(ctx, slots, as_of, question)
        if valuation_hit:
            detail_text, val_stats, val_row = valuation_hit
            return envelope("SERIES", ok=True, rows=[val_row],
                            provenance=[{"ref": f"SERIES:{val_row['ref']}", "known_at": as_of}],
                            pit=f"price date and filing known_at <= {as_of}", checked=CHECKED,
                            degraded=degraded + ["no routed price window; the T1 state row "
                                                 "supplies the close"],
                            detail=detail_text)
        detail = (f"no price rows for {slots.get('symbol') or slots.get('isin')} "
                  f"between {start} and {end}")
        return envelope("SERIES", ok=False, why="no_doc", checked=CHECKED, degraded=degraded,
                        detail=detail, nid_reason=detail)

    parts: list[str] = []
    stats: dict[str, Any] = {}
    items: dict[str, str] = {}
    day_pct: dict[str, float] = {}
    want_volume = bool(re.search(r"\bvolume|volumes|traded quantity|accumulat", question, re.I))
    want_delivery = bool(re.search(r"\bdelivery|delivered", question, re.I))
    for name, points in series.items():
        st = compute.series_stats(points)
        stats[name] = st
        item = ["close"]
        flow_rows = flows.get(name) or []
        flow = compute.flow_stats(flow_rows)
        if (want_volume and flow.get("volume_last") is None) or \
                (want_delivery and flow.get("delivery_last") is None):
            fallback = _flow_fallback(ctx, ident.get(name, (None, None))[0],
                                      ident.get(name, (None, None))[1], start, end)
            if fallback:
                degraded.append(f"{name}: volume/delivery read from daily_price_delivery "
                                f"(the price snapshot has them NULL)")
                flow_rows = flow_rows + fallback
        if len(points) == 1:
            line = f"{name}: close {fmt_num(st['first'])} on {st['start']}"
            if names:
                try:
                    row = ctx.one(
                        "equity_intelligence",
                        "SELECT pct_change FROM mkt_nse_index_daily "
                        "WHERE lower(index_name)=lower(?) AND date=? LIMIT 1",
                        (name, st["start"]))
                    if row and row.get("pct_change") is not None:
                        day_pct[name] = float(row["pct_change"])
                        line += f" ({day_pct[name]:+.2f}% on the day)"
                except Exception:
                    pass
            item, line = _flow_line(item, line, flow_rows, want_volume, want_delivery)
            items[name] = ", ".join(item)
            parts.append(line)
            continue
        cagr_pct, years = compute.cagr_between(st["first"], st["last"], st["start"], st["end"])
        item.append("return")
        line = (f"{name}: {st['start']} close {fmt_num(st['first'])} -> {st['end']} close "
                f"{fmt_num(st['last'])}, return {st['return_pct']:.1f}% "
                f"({st['rows']} sessions)")
        if metric == "cagr" or "cagr" in question.lower():
            if cagr_pct is not None:
                line += f", CAGR {cagr_pct:.1f}% over {years:.1f}y"
                item.append("CAGR")
        if metric == "range" or re.search(r"\brange|support|resistance|52[- ]week|ytd|high|low\b",
                                          question, re.I):
            high_label = ("adjusted high" if name in raw and "adjusted" in question.lower()
                          else "high")
            line += (f", {high_label} {fmt_num(st['high'])} ({st['high_date']}), "
                     f"low {fmt_num(st['low'])} ({st['low_date']})")
            item += ["high", "low"]
            if name in raw and "adjusted" in question.lower():
                raw_st = compute.series_stats(raw[name])
                line += (f"; raw close high {fmt_num(raw_st['high'])} "
                         f"({raw_st['high_date']})")
            if len(points) > 3:
                edge = max(abs(st["high"] or 0), abs(st["low"] or 0), 1e-9)
                tests = sum(1 for _, v in points if abs(v - (st["high"] or v)) <= edge * 0.01
                            or abs(v - (st["low"] or v)) <= edge * 0.01)
                line += f", {tests} daily closes within 1% of an edge"
        item, line = _flow_line(item, line, flow_rows, want_volume, want_delivery)
        items[name] = ", ".join(item)
        parts.append(line)

    if len(series) >= 2:
        ordered = sorted(series, key=lambda key: stats[key].get("return_pct") or -1e9,
                         reverse=True)
        for i, name in enumerate(ordered):
            for other in ordered[i + 1:]:
                rel = compute.relative_return(series[name], series[other])
                if rel is not None:
                    parts.append(f"excess return {name} minus {other}: {rel:+.1f}%")
    if names and day_pct and re.search(r"which (?:sector|index)|sabse|most|worst|best",
                                        question, re.I):
        try:
            ranking = _index_day_ranking(ctx, start)
        except Exception:
            ranking = []
        if ranking:
            parts.append("all Nifty indices that day (worst first): " + ", ".join(
                f"{r['index_name']} {float(r['pct_change']):+.2f}%" for r in ranking))
            stats["_index_ranking"] = ranking

    rsi_study = None
    if metric == "rsi" or re.search(r"\brsi|oversold|overbought\b", question, re.I):
        rsi_study = _rsi_study(ctx, str(slots.get("symbol") or ""), as_of)
        if rsi_study:
            stats["rsi_study"] = rsi_study
            tail = (f"RSI(14) at {rsi_study['data_end']}: "
                    f"{rsi_study['last_rsi']:.1f} "
                    f"(percentile {rsi_study['last_rsi_percentile']:.0f}); "
                    f"{rsi_study['oversold_days']} oversold days")
            if rsi_study["samples"]:
                tail += (f"; 20-session forward return after an oversold day averaged "
                         f"{rsi_study['forward_20d_avg_pct']:.1f}% and was positive "
                         f"{rsi_study['forward_20d_positive_pct']:.0f}% of "
                         f"{rsi_study['samples']} times")
            parts.append(tail)
            degraded.append("daily closes only; RSI is the stored daily rsi_14")
        else:
            degraded.append("no RSI series for this symbol")

    extra_rows: list[dict[str, Any]] = []
    # A high/low ask is answered by the high and low, not by the close: the study
    # reads the window the ask itself names (YTD, 52 weeks, a named span) when the
    # routed window is a single date.
    range_study = None
    if re.search(r"\b(high|low|range|52[- ]week|ytd|all[- ]time|record high|record low)\b",
                 question, re.I):
        range_study = _range_study(ctx, slots, as_of, question)
        if range_study:
            detail_text, row = range_study
            stats["range_study"] = row["stats"]
            parts.append(detail_text)
            extra_rows.append(row)
    if metric == "band" or BAND_ASK.search(question or ""):
        band_study = _band_study(ctx, slots, as_of, start, end)
        if band_study:
            detail_text, band_rows, band_notes = band_study
            parts.append(detail_text)
            degraded.extend(band_notes)
            extra_rows.extend(band_rows)
        else:
            degraded.append(f"price bands are not held for {slots.get('symbol') or ''} "
                            f"in this window")
    listing_hit = _listing_study(ctx, slots, as_of, question)
    if listing_hit:
        detail_text, listing_row = listing_hit
        parts.append(detail_text)
        extra_rows.append(listing_row)
    valuation_hit = _valuation_row(ctx, slots, as_of, question)
    if valuation_hit:
        detail_text, val_stats, val_row = valuation_hit
        stats["valuation"] = val_stats
        parts.append(detail_text)
        extra_rows.append(val_row)
    elif VALUATION_ASK.search((question or "").replace("-", " ")):
        degraded.append("no held EPS/net-worth pair for a P/E or P/B on this date")

    # The technical studies the bank asks for by name: a session count near the
    # high, drawdown recovery time, RSI divergence.  Each is arithmetic over the
    # same held closes, never a different window.
    study_series = series.get(str(slots.get("symbol") or "")) or next(iter(series.values()), [])
    if study_series and re.search(r"within\s+\d+(?:\.\d+)?\s*%|how many (?:prior )?sessions",
                                  question, re.I):
        pct = _pct_asked(question, 2.0)
        near = compute.days_within(study_series, pct)
        if near:
            stats["days_within"] = dict(near, pct=pct)
            parts.append(f"sessions within {pct:g}% of the window high: {near['near']} of "
                         f"{near['sessions']} ({near['share_pct']:.0f}%), "
                         f"{near['first']} .. {near['last']}")
            degraded.append("the window high is the routed window's own high, not a "
                            "reconstructed 52-week high")
    if re.search(r"drawdown|recover", question, re.I):
        # "the last three drawdowns of that size" is not a 52-week question: the
        # study reads the company's own history (the same rule _rsi_study uses).
        history = _history(ctx, str(slots.get("symbol") or ""), as_of) or study_series
        falls = compute.drawdown_recoveries(history, _pct_asked(question, 15.0))
        if falls:
            stats["drawdowns"] = falls
            said = "; ".join(
                f"{f['peak']} -> {f['trough']} fell {f['fall_pct']:.1f}%"
                + (f" and recovered after {f['sessions']} sessions ({f['recovered']})"
                   if f["recovered"] else " and has not recovered in the window")
                for f in falls)
            parts.append(f"drawdown recovery ({len(falls)} falls of at least "
                         f"{_pct_asked(question, 15.0):g}%): {said}")
        elif history:
            parts.append(f"no fall of at least {_pct_asked(question, 15.0):g}% in the held "
                         f"close history ({len(history)} sessions)")
            degraded.append("no qualifying drawdown in the held history")
    if re.search(r"divergen", question, re.I):
        try:
            rsi_rows = ctx.rows(
                "equity_intelligence",
                "SELECT date, close, rsi_14 FROM daily_price_delivery "
                "WHERE symbol = ? AND date <= ? AND rsi_14 IS NOT NULL "
                "ORDER BY date LIMIT 4000", (str(slots.get("symbol") or "").upper(), as_of))
        except Exception:  # noqa: BLE001 - a missing RSI column is a degraded answer
            rsi_rows = []
        divergence = compute.rsi_divergence(
            [(r["date"], r["close"], r["rsi_14"]) for r in rsi_rows])
        if divergence:
            stats["rsi_divergence"] = divergence
            parts.append(
                f"RSI divergence: price low {divergence['first_low']} -> "
                f"{divergence['last_low']} {'lower' if divergence['price_lower_low'] else 'higher'}"
                f", RSI {'higher' if divergence['rsi_higher_low'] else 'lower'} "
                f"({divergence['rsi_first']:.1f} -> {divergence['rsi_last']:.1f}): "
                f"{'yes' if divergence['divergence'] else 'no'} divergence")
        else:
            degraded.append("fewer than two RSI price lows in the window; no divergence measurable")

    if slots.get("needs", {}).get("intraday"):
        degraded.append("intraday bars are not held; only daily high/low/close")
        detail = "; ".join(parts)
        return envelope("SERIES", ok=False, why="schema", checked=CHECKED, degraded=degraded,
                        detail=f"{detail} | daily window only, intraday amplitude not in data",
                        rows=_series_rows(stats, ident, as_of, start),
                        pit=f"date <= {as_of}",
                        nid_reason="intraday bars / how-many-tests count are not in held data")

    detail = "; ".join(parts)
    rows = in_period(_series_rows(stats, ident, as_of, start), slots, hop="SERIES")
    for row in rows:   # name what each series row reports (close / volume / delivery / study)
        row["item"] = items.get(row["ref"], "close")
    rows += extra_rows
    return envelope(
        "SERIES", ok=True, rows=rows,
        provenance=[{"ref": f"SERIES:{name}", "known_at": as_of} for name in stats],
        pit=f"date <= {as_of} (session close)", checked=CHECKED, degraded=degraded,
        detail=detail)
