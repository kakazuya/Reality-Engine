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
    if not VALUATION_ASK.search(question or ""):
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
    if not slots.get("needs", {}).get("price") and metric not in {"return", "cagr", "range"}:
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
            item, line = _flow_line(item, line, flows.get(name), want_volume, want_delivery)
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
        item, line = _flow_line(item, line, flows.get(name), want_volume, want_delivery)
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
    valuation_hit = _valuation_row(ctx, slots, as_of, question)
    if valuation_hit:
        detail_text, val_stats, val_row = valuation_hit
        stats["valuation"] = val_stats
        parts.append(detail_text)
        extra_rows.append(val_row)
    elif VALUATION_ASK.search(question or ""):
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
