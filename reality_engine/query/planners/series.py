"""SERIES: dated price/index/commodity rows plus the arithmetic the ask names.

Reads the DuckDB primary series (``px_daily``, adjusted closes) when the dated
snapshot is present, falls back to ``daily_price_delivery`` (raw, indexed).
PIT is always ``date <= as_of`` in the SQL.
"""
from __future__ import annotations

import re
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, isin_of

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

    names = indexes_in(question)
    commodity = commodity_in(question)
    try:
        if names:
            for name in names:
                rows = _index_rows(ctx, name, start, end)
                series[name] = _points(rows)
        elif commodity:
            rows = _commodity_rows(ctx, commodity, start, end)
            series[commodity] = _points(rows)
        else:
            symbols = [s for s in (slots.get("symbols") or [])
                       if not str(s).startswith("IN")][:4]
            if not symbols and slots.get("symbol"):
                symbols = [str(slots["symbol"])]
            if not symbols:
                return envelope("SERIES", ok=False, na=True, checked=CHECKED,
                                detail="no entity for a price series",
                                nid_reason="gate G1: no symbol/ISIN to price")
            for symbol in symbols:
                isin = slots.get("isin") if len(symbols) == 1 else isin_of(
                    {"symbol": symbol}, ctx, as_of)
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
                    series[symbol] = points
                    raw[symbol] = _points(rows, "close")
            if re.search(r"\bnifty\b|benchmark|relative strength", question, re.I):
                bench = _points(_index_rows(ctx, "Nifty 50", start, end))
                if bench:
                    series["Nifty 50"] = bench
    except Exception as exc:  # noqa: BLE001
        return envelope("SERIES", ok=False, why="tool", checked=CHECKED,
                        detail=f"series store failed: {type(exc).__name__}: {exc}")

    series = {k: v for k, v in series.items() if v}
    if not series:
        detail = (f"no price rows for {slots.get('symbol') or slots.get('isin')} "
                  f"between {start} and {end}")
        return envelope("SERIES", ok=False, why="no_doc", checked=CHECKED, degraded=degraded,
                        detail=detail, nid_reason=detail)

    parts: list[str] = []
    stats: dict[str, Any] = {}
    day_pct: dict[str, float] = {}
    for name, points in series.items():
        st = compute.series_stats(points)
        stats[name] = st
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
            parts.append(line)
            continue
        cagr_pct, years = compute.cagr_between(st["first"], st["last"], st["start"], st["end"])
        line = (f"{name}: {st['start']} close {fmt_num(st['first'])} -> {st['end']} close "
                f"{fmt_num(st['last'])}, return {st['return_pct']:.1f}% "
                f"({st['rows']} sessions)")
        if metric == "cagr" or "cagr" in question.lower():
            if cagr_pct is not None:
                line += f", CAGR {cagr_pct:.1f}% over {years:.1f}y"
        if metric == "range" or re.search(r"\brange|support|resistance|52[- ]week|ytd|high|low\b",
                                          question, re.I):
            high_label = ("adjusted high" if name in raw and "adjusted" in question.lower()
                          else "high")
            line += (f", {high_label} {fmt_num(st['high'])} ({st['high_date']}), "
                     f"low {fmt_num(st['low'])} ({st['low_date']})")
            if name in raw and "adjusted" in question.lower():
                raw_st = compute.series_stats(raw[name])
                line += (f"; raw close high {fmt_num(raw_st['high'])} "
                         f"({raw_st['high_date']})")
            if len(points) > 3:
                edge = max(abs(st["high"] or 0), abs(st["low"] or 0), 1e-9)
                tests = sum(1 for _, v in points if abs(v - (st["high"] or v)) <= edge * 0.01
                            or abs(v - (st["low"] or v)) <= edge * 0.01)
                line += f", {tests} daily closes within 1% of an edge"
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

    if slots.get("needs", {}).get("intraday"):
        degraded.append("intraday bars are not held; only daily high/low/close")
        detail = "; ".join(parts)
        return envelope("SERIES", ok=False, why="schema", checked=CHECKED, degraded=degraded,
                        detail=f"{detail} | daily window only, intraday amplitude not in data",
                        rows=[{"ref": name, "known_at": as_of, "stats": st}
                              for name, st in stats.items()],
                        pit=f"date <= {as_of}",
                        nid_reason="intraday bars / how-many-tests count are not in held data")

    detail = "; ".join(parts)
    return envelope(
        "SERIES", ok=True, rows=[{"ref": name, "known_at": as_of, "stats": st}
                                 for name, st in stats.items()],
        provenance=[{"ref": f"SERIES:{name}", "known_at": as_of} for name in stats],
        pit=f"date <= {as_of} (session close)", checked=CHECKED, degraded=degraded,
        detail=detail)
