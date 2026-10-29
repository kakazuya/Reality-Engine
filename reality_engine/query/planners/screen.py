"""SCREEN: rank a held universe on one dated metric (or name the missing table).

The universe comes from the pilot (b) ``company_membership_pit`` when that store is
present (PIT index intervals, never today's list); the price/delivery window falls
back to the pilot (b) full NSE bhavcopy when the live tables have no rows for it.
"""
from __future__ import annotations

import re
from typing import Any

from . import envelope, fmt_num, in_period
from .facts import _t1_rows

CHECKED = ["equity_intelligence.master_companies", "equity_intelligence.index_membership",
           "equity_intelligence.daily_price_delivery", "equity_intelligence.quarterly_financials",
           "equity_intelligence.shp_index", "equity_intelligence.price_bands",
           "equity_intelligence.mkt_nse_insider", "market_state.company_ownership_pit",
           "market_state.company_state_daily", "facts_pilot.company_metric_series",
           "market_state_b.company_membership_pit", "market_state_b.mkt_nse_full_daily"]

SCREEN_TABLES = ("company_state_daily", "price_band_daily", "sector_flow_daily",
                 "company_metric_series", "company_membership_pit", "event_day0",
                 "company_theme_pit", "company_operating_metrics")

HOLDING_ASK = re.compile(r"\b(promoter|shareholding|public holding|public shareholding|"
                         r"free float|pledge|non-promoter)\b", re.I)
BAND_ASK = re.compile(r"\b(price band|band|circuit|base price)\b", re.I)
VALUATION_ASK = re.compile(r"\b(p/b|pb|price to book|book value|p/e|pe|price to earnings|"
                           r"market cap|market capitalisation|market capitalization|"
                           r"ev/ebitda|ev/sales|valuation)\b", re.I)
SECTORS = ("Consumer Durables", "Financial Services", "Information Technology",
           "Metals & Mining", "Capital Goods", "Automobile and Auto Components",
           "Oil Gas & Consumable Fuels", "Construction Materials", "Realty", "Chemicals",
           "Healthcare", "Fast Moving Consumer Goods", "Consumer Services", "Power",
           "Telecommunication", "Textiles", "Transport Services", "Industrial Products",
           "General Diversified")


def _sector(question: str) -> str | None:
    low = question.lower()
    for name in SECTORS:
        if name.lower() in low:
            return name
    return None


def _symbol_isins(ctx: Any, symbol: str | None, isin: str | None) -> list[str]:
    """Every ISIN the symbol has traded under (a holding row may carry an old one)."""
    out = [isin] if isin else []
    if symbol:
        key = ("holding_isins", symbol.upper())
        cached = ctx.cache_get(key)
        if cached is None:
            try:
                rows = ctx.rows(
                    "equity_intelligence",
                    "SELECT DISTINCT isin FROM symbol_isin_history "
                    "WHERE upper(symbol) = upper(?)", (symbol,))
                cached = [r["isin"] for r in rows if r.get("isin")]
            except Exception:  # noqa: BLE001 - the identity store is optional
                cached = []
            ctx.cache_put(key, cached)
        out += list(cached)
    return list(dict.fromkeys(value for value in out if value))


def _holding_rows(ctx: Any, isins: list[str], symbol: str | None, as_of: str,
                  want_public: bool, want_pledge: bool) -> list[dict[str, Any]]:
    """Promoter / public / pledge levels from the ownership tables, newest PIT first."""
    quarters: list[dict[str, Any]] = []
    marks = ",".join("?" * len(isins)) if isins else ""
    if isins:
        try:
            quarters = _t1_rows(
                ctx, "market_state",
                "SELECT isin, quarter_end, known_at, promoter_pct, public_pct, pledge_pct "
                f"FROM company_ownership_pit WHERE isin IN ({marks}) AND known_at <= ? "
                "ORDER BY quarter_end DESC LIMIT 8", (*isins, as_of))
        except Exception:  # noqa: BLE001 - the T1 build is optional
            quarters = []
    if not quarters:
        isin_clause = f"isin IN ({marks}) OR " if marks else ""
        try:
            quarters = ctx.rows(
                "equity_intelligence",
                "SELECT isin, quarter_end, broadcast_at AS known_at, promoter_pct, "
                "public_pct, NULL AS pledge_pct FROM shp_index "
                f"WHERE ({isin_clause}upper(symbol) = upper(?)) "
                "AND COALESCE(broadcast_at,'') <> '' AND substr(broadcast_at,1,10) <= ? "
                "ORDER BY quarter_end DESC LIMIT 8",
                (*isins, symbol or "", as_of))
        except Exception:  # noqa: BLE001
            quarters = []
    out: list[dict[str, Any]] = []
    for row in quarters:
        day = str(row.get("quarter_end") or "")[:10]
        known = str(row.get("known_at") or "")[:10] or as_of
        if want_public:
            if row.get("public_pct") is not None:
                out.append({"ref": f"shp_index:{row.get('isin')}", "item": "Public holding %",
                            "period": day, "known_at": known, "symbol": symbol,
                            "isin": row.get("isin"), "value": row["public_pct"]})
            continue
        if row.get("promoter_pct") is not None:
            out.append({"ref": f"shp_index:{row.get('isin')}", "item": "Promoter holding %",
                        "period": day, "known_at": known, "symbol": symbol,
                        "isin": row.get("isin"), "value": row["promoter_pct"]})
        if want_pledge and row.get("pledge_pct") is not None:
            out.append({"ref": f"shp_index:{row.get('isin')}", "item": "Promoter pledge %",
                        "period": day, "known_at": known, "symbol": symbol,
                        "isin": row.get("isin"), "value": row["pledge_pct"]})
    return out


def _pledge_events(ctx: Any, symbol: str | None, as_of: str, slots: dict[str, Any],
                   corpus: bool = False) -> list[dict[str, Any]]:
    """Pledge creation/release filings from the NSE insider (SAST) table."""
    where = ["lower(raw_json) LIKE '%pledge%'", "substr(disseminated_at,1,10) <= ?"]
    params: list[Any] = [as_of]
    if symbol and not corpus:
        where.append("upper(symbol) = upper(?)")
        params.append(symbol)
    low, high = str(slots.get("date_from") or "")[:10], str(slots.get("date_to") or "")[:10]
    if low and high:
        where.append("substr(disseminated_at,1,10) >= ? AND substr(disseminated_at,1,10) <= ?")
        params.extend([low, high])
    try:
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT symbol, transaction_type, securities_qty, after_pct, disseminated_at, "
            "acquirer_name, raw_json FROM mkt_nse_insider "
            f"WHERE {' AND '.join(where)} ORDER BY disseminated_at DESC LIMIT 80", tuple(params))
    except Exception:  # noqa: BLE001 - the SAST table is optional
        return []
    out = []
    for row in rows:
        raw = str(row.get("raw_json") or "").lower()
        label = ("Pledge creation" if "pledge creation" in raw
                 else "Pledge release" if "release" in raw or "revok" in raw
                 else "Pledge")
        qty = row.get("securities_qty")
        out.append({"ref": f"mkt_nse_insider:{row.get('acquirer_name') or ''}",
                    "item": f"Promoter {label} (shares)", "period":
                    str(row.get("disseminated_at") or "")[:10],
                    "known_at": str(row.get("disseminated_at") or "")[:10],
                    "symbol": row.get("symbol"), "value": qty,
                    "detail": f"{label} by {row.get('acquirer_name') or 'promoter'}"})
    return out


def _asked_quarter(question: str) -> str | None:
    """"as of Sep 2026" -> 2026-09-30 (the quarter the holding filing reports)."""
    match = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
                      question, re.I)
    if not match:
        return None
    month = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
             "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}[match.group(1).lower()[:3]]
    quarter_end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[(month - 1) // 3 + 1]
    return f"{match.group(2)}-{quarter_end}"


def _universe_holding(ctx: Any, question: str, slots: dict[str, Any], as_of: str,
                      want_public: bool) -> list[dict[str, Any]]:
    """Rank the asked universe on its shareholding level for the asked quarter."""
    where = ["COALESCE(s.broadcast_at,'') <> ''", "substr(s.broadcast_at,1,10) <= ?"]
    params: list[Any] = [as_of]
    low, high = str(slots.get("date_from") or "")[:10], str(slots.get("date_to") or "")[:10]
    quarter = _asked_quarter(question)
    if low and high:
        where.append("s.quarter_end >= ? AND s.quarter_end <= ?")
        params.extend([low, high])
    elif quarter:
        where.append("s.quarter_end = ?")
        params.append(quarter)
    else:
        where.append("s.quarter_end = (SELECT MAX(quarter_end) FROM shp_index "
                     "WHERE substr(broadcast_at,1,10) <= ? AND quarter_end >= "
                     "(SELECT date(MAX(broadcast_at), '-400 days') FROM shp_index))")
        params.append(as_of)
    filters: list[tuple[str, Any]] = []
    tier = _tier(question)
    if tier:
        filters.append(("m.market_cap_tier = ?", tier))
    sector = _sector(question)
    if sector:
        filters.append(("lower(COALESCE(m.industry, m.sector, '')) LIKE ?",
                        f"%{sector.lower()}%"))
    index = _index(question)
    if index:
        filters.append(("s.isin IN (SELECT isin FROM index_membership "
                        "WHERE lower(index_name) LIKE ?)", f"%{index.lower()}%"))
    column = "public_pct" if want_public else "promoter_pct"

    def run(extra: list[tuple[str, Any]]) -> list[dict[str, Any]]:
        clauses = list(where) + [clause for clause, _ in extra]
        args: list[Any] = list(params) + [value for _, value in extra]
        return ctx.rows(
            "equity_intelligence",
            "SELECT s.symbol, s.isin, s.quarter_end, s.promoter_pct, s.public_pct, "
            "s.broadcast_at FROM shp_index s "
            "LEFT JOIN master_companies m ON upper(m.nse_symbol) = upper(s.symbol) "
            f"WHERE {' AND '.join(clauses)} AND s.{column} IS NOT NULL "
            f"ORDER BY s.{column} DESC LIMIT 15", tuple(args))

    rows: list[dict[str, Any]] = []
    try:
        rows = run(filters)
        if not rows and (sector or index):
            # The bank's sector label is not always our industry label: rank the
            # whole held universe rather than report no filing at all.
            rows = run([f for f in filters if "market_cap_tier" in f[0]])
    except Exception:  # noqa: BLE001 - the shareholding index is optional
        return []
    item = "Public holding %" if want_public else "Promoter holding %"
    return [{"ref": f"shp_index:{r.get('isin')}", "item": item,
             "period": str(r.get("quarter_end") or "")[:10],
             "known_at": str(r.get("broadcast_at") or "")[:10],
             "symbol": r.get("symbol"), "isin": r.get("isin"),
             "value": r.get(column)} for r in rows]


def _holding_screen(slots: dict[str, Any], as_of: str, ctx: Any,
                    question: str) -> dict[str, Any]:
    """The shareholding index for the asked line and quarter (single name or corpus)."""
    symbol = str(slots.get("symbol") or "") or None
    isins = _symbol_isins(ctx, symbol, slots.get("isin"))
    want_public = bool(re.search(r"\bpublic\b|free float|non-promoter", question, re.I))
    want_pledge = bool(re.search(r"\bpledge", question, re.I))
    rows: list[dict[str, Any]] = []
    if want_pledge:
        rows += _pledge_events(ctx, symbol, as_of, slots, corpus=not symbol)
    if symbol or isins:
        rows += _holding_rows(ctx, isins, symbol, as_of, want_public, want_pledge)
    else:
        rows += _universe_holding(ctx, question, slots, as_of, want_public)
    rows = in_period(rows, slots, hop="SCREEN")
    if not rows:
        detail = (f"no shareholding filing for {symbol or slots.get('isin') or 'the universe'} "
                  f"in the asked window known by {as_of}")
        return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    item = ("Public holding %" if want_public and not want_pledge
            else "Promoter pledge" if want_pledge else "Promoter holding %")
    detail = (f"{item}: " + "; ".join(
        f"{r.get('symbol') or r.get('isin')} {fmt_num(r.get('value'))} "
        f"({r.get('period')})" for r in rows[:5]))
    return envelope(
        "SCREEN", ok=True, rows=rows,
        provenance=[{"ref": f"SCREEN:{r.get('ref')}", "known_at": r.get("known_at")}
                    for r in rows[:5]],
        pit=f"quarter_end / disseminated_at <= {as_of}",
        checked=CHECKED, detail=detail)


def _band_screen(slots: dict[str, Any], as_of: str, ctx: Any,
                 question: str) -> dict[str, Any]:
    """The names in a 2/5/10% circuit band on the asked session (price_bands)."""
    anchor = min(str(slots.get("date_from") or as_of)[:10], str(as_of)[:10])
    limit = re.search(r"\b(\d{1,2})\s*%", question)
    max_band = int(limit.group(1)) if limit else None
    try:
        day_row = ctx.one("equity_intelligence",
                          "SELECT MAX(date) AS d FROM price_bands WHERE date <= ?", (anchor,))
    except Exception as exc:  # noqa: BLE001
        return envelope("SCREEN", ok=False, why="tool", checked=CHECKED,
                        detail=f"price band store failed: {type(exc).__name__}: {exc}")
    day = str((day_row or {}).get("d") or "")[:10]
    if not day:
        detail = f"no price band row on or before {anchor}"
        return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    try:
        bands = ctx.rows(
            "equity_intelligence",
            "SELECT symbol, band FROM price_bands WHERE date = ? AND band <> 'No Band'",
            (day,))
    except Exception as exc:  # noqa: BLE001
        return envelope("SCREEN", ok=False, why="tool", checked=CHECKED,
                        detail=f"price band read failed: {type(exc).__name__}: {exc}")
    if max_band is not None:
        bands = [b for b in bands
                 if str(b.get("band") or "").isdigit() and int(b["band"]) <= max_band]
    traded: dict[str, float] = {}
    try:
        for row in ctx.rows(
                "equity_intelligence",
                "SELECT symbol, turnover_lacs FROM mkt_nse_full_daily WHERE date = ?",
                (day,)):
            if row.get("turnover_lacs") is not None:
                traded[str(row["symbol"]).upper()] = float(row["turnover_lacs"])
    except Exception:  # noqa: BLE001 - ordering by turnover is a nicety
        traded = {}
    bands.sort(key=lambda b: traded.get(str(b["symbol"]).upper(), 0.0), reverse=True)
    if not bands:
        detail = f"no name carried a <= {max_band}% band on {day}"
        return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    top = bands[:15]
    out = [{"ref": f"price_bands:{b['symbol']}", "item": f"price band {b['band']}%",
            "period": day, "known_at": as_of, "symbol": b["symbol"],
            "value": b["band"]} for b in top]
    detail = (f"price band on {day}: " + "; ".join(
        f"{b['symbol']} {b['band']}%" for b in top[:6]))
    degraded = [] if day == anchor else [f"the band series ends {day}; the ask is {anchor}"]
    return envelope("SCREEN", ok=True, rows=out,
                    provenance=[{"ref": f"SCREEN:price_bands:{b['symbol']}",
                                 "known_at": as_of} for b in top[:5]],
                    pit=f"price_bands.date <= {as_of}", checked=CHECKED,
                    detail=detail, degraded=degraded)


def _valuation_screen(slots: dict[str, Any], as_of: str, ctx: Any,
                      question: str) -> dict[str, Any] | None:
    """Rank the asked universe on P/B, P/E or market cap from the PIT state row."""
    low = question.lower()
    if re.search(r"p/b|pb|price to book|book value", low):
        kind = "pb"
    elif re.search(r"p/e|pe ratio|price to earnings|\bpe\b", low):
        kind = "pe"
    else:
        kind = "mcap"
    anchor = min(str(slots.get("date_from") or as_of)[:10], str(as_of)[:10])
    sector = _sector(question)
    where, params = ("m.is_active = 1", [])
    if sector:
        where = "lower(COALESCE(m.industry, m.sector, '')) LIKE ?"
        params = [f"%{sector.lower()}%"]
    try:
        names = ctx.rows(
            "equity_intelligence",
            f"SELECT m.isin, m.nse_symbol FROM master_companies m WHERE {where} "
            "AND m.isin IS NOT NULL LIMIT 800", tuple(params))
    except Exception:  # noqa: BLE001
        return None
    isins = list(dict.fromkeys(r["isin"] for r in names if r.get("isin")))
    symbols = {r["isin"]: r.get("nse_symbol") for r in names}
    if not isins:
        return None
    marks = ",".join("?" * len(isins))
    try:
        state = _t1_rows(
            ctx, "market_state",
            "SELECT isin, date, close, mcap_cr FROM company_state_daily "
            "WHERE date = (SELECT MAX(date) FROM company_state_daily WHERE date <= ?) "
            f"AND isin IN ({marks})", (anchor, *isins))
    except Exception:  # noqa: BLE001 - the T1 build is optional
        return None
    if not state:
        return None
    by_isin = {r["isin"]: r for r in state if r.get("isin")}
    values: dict[str, float] = {}
    extra: dict[str, str] = {}
    if kind in ("pb", "pe"):
        metric_key, unit = (("net_worth", "INR_CRORE") if kind == "pb"
                            else ("eps", "INR_PER_SHARE"))
        try:
            facts_rows = _t1_rows(
                ctx, "facts_pilot",
                "SELECT isin, period_end, value FROM company_metric_series "
                "WHERE metric_key = ? AND unit = ? AND basis = 'consolidated' "
                f"AND known_at <= ? AND isin IN ({marks}) ORDER BY period_end DESC",
                (metric_key, unit, as_of, *isins))
        except Exception:  # noqa: BLE001
            facts_rows = []
        per: dict[str, list[float]] = {}
        for row in facts_rows:
            if row.get("value") is None:
                continue
            per.setdefault(str(row.get("isin")), []).append(float(row["value"]))
        for isin, vals in per.items():
            day = by_isin.get(isin)
            if not day:
                continue
            if kind == "pb" and day.get("mcap_cr") and vals[0]:
                values[isin] = float(day["mcap_cr"]) / vals[0]
                extra[isin] = f"net worth {vals[0]:,.0f} cr"
            elif kind == "pe":
                quarters = vals[:4]
                if len(quarters) == 4 and day.get("close") and sum(quarters):
                    values[isin] = float(day["close"]) / sum(quarters)
                    extra[isin] = f"trailing 4q EPS {sum(quarters):.2f}"
    else:
        for isin, day in by_isin.items():
            if day.get("mcap_cr"):
                values[isin] = float(day["mcap_cr"])
    if len(values) < 2:
        return None
    label = {"pb": "P/B", "pe": "P/E (TTM)", "mcap": "Market cap (Rs crore)"}[kind]
    ranked = sorted(values.items(), key=lambda item: item[1], reverse=True)[:15]
    day = next(iter(by_isin.values()))["date"]
    out = [{"ref": f"company_state_daily:{isin}", "item": label, "period": day,
            "known_at": as_of, "symbol": symbols.get(isin), "isin": isin,
            "value": round(value, 2)} for isin, value in ranked]
    detail = (f"{label} on {day}" + (f" ({sector})" if sector else "") + ": " + "; ".join(
        f"{symbols.get(isin) or isin} {value:.2f}" for isin, value in ranked[:5]))
    degraded = []
    if day != anchor:
        degraded.append(f"state row is {day}, the asked session is {anchor}")
    return envelope("SCREEN", ok=True, rows=out,
                    provenance=[{"ref": f"SCREEN:{label}:{isin}", "known_at": as_of}
                                for isin, _ in ranked[:5]],
                    pit=f"company_state_daily.date <= {as_of}; filings known_at <= {as_of}",
                    checked=CHECKED, detail=detail, degraded=degraded)


def _tier(question: str) -> str | None:
    low = question.lower()
    for tier in ("large", "mid", "small", "micro"):
        if f"{tier} cap" in low or f"{tier}-cap" in low:
            return tier.upper()
    return None


def _index(question: str) -> str | None:
    match = re.search(r"(Nifty [A-Za-z0-9 &]+?)(?:\s+(?:members|constituents|names|fell|rose|"
                      r"companies))", question, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b(NIFTY [A-Z0-9 ]+?)\s+(?:constituents|members|companies)", question)
    return match.group(1).strip() if match else None


def _universe(ctx: Any, question: str, slots: dict[str, Any]) -> tuple[str, list[Any]]:
    tier = _tier(question)
    if tier:
        return "m.market_cap_tier = ?", [tier]
    index = _index(question)
    if index:
        return ("m.isin IN (SELECT isin FROM index_membership WHERE lower(index_name) LIKE ?)",
                [f"%{index.lower()}%"])
    if slots.get("entity_level") == "sector" and slots.get("symbol"):
        return "lower(COALESCE(m.sector,m.industry,'')) LIKE ?", [f"%{slots['symbol'].lower()}%"]
    if re.search(r"losers?|top|which companies|fell|fall|decline|drop", question, re.I):
        return "m.is_active = 1", []
    return "m.is_active = 1 AND m.is_nifty500 = 1", []


def _metric_screen(ctx: Any, question: str, as_of: str, table: str) -> dict[str, Any] | None:
    """Rank the held universe on an extraction table (pilot-60 ``metric_state``)."""
    try:
        from reality_engine.query import metrics
        ranked = metrics.screen(ctx, question, as_of, table)
    except Exception:  # noqa: BLE001 - no store: the caller keeps its blocked answer
        return None
    if len(ranked) < 2:
        return None
    symbols = {}
    try:
        marks = ",".join("?" * len(ranked))
        symbols = {r["isin"]: r["nse_symbol"] for r in ctx.rows(
            "equity_intelligence",
            f"SELECT isin, nse_symbol FROM master_companies WHERE isin IN ({marks})",
            tuple(r["isin"] for r in ranked))}
    except Exception:  # noqa: BLE001
        pass
    detail = f"{table} ranked on {ranked[0]['unit'] or 'value'} at {as_of}: " + "; ".join(
        f"{symbols.get(r['isin']) or r['isin']} {r['item']} {r['value']}" for r in ranked[:5])
    return envelope(
        "SCREEN", ok=True, checked=["metric_state." + table],
        rows=[{"ref": r["ref"], "known_at": str(r["known_at"])[:10],
               "symbol": symbols.get(r["isin"]), "value": r["value"], "item": r["item"]}
              for r in ranked],
        provenance=[{"ref": r["ref"], "known_at": str(r["known_at"])[:10]}
                    for r in ranked[:5]],
        pit=f"metric_state.{table}.known_at <= {as_of}", detail=detail,
        degraded=[f"{table} rows are the pilot-60 extraction build, not the full market"])


def _membership_from(ctx: Any, alias: str, index: str, as_of: str) -> tuple[set[str], str] | None:
    """(ISINs, note) from one store's index_list + company_membership_pit, or None.

    ``changes_only`` coverage holds notice-dated changes, not the constituent list:
    using it as a universe would rank only the names that ever moved in or out.
    """
    try:
        matches = ctx.rows(
            alias,
            "SELECT index_code, display_name, coverage FROM index_list "
            "WHERE lower(display_name) LIKE ? ORDER BY "
            "CASE coverage WHEN 'snapshot' THEN 0 WHEN 'derived' THEN 1 ELSE 2 END, "
            "length(index_code)", (f"%{index.lower()}%",))
    except Exception:  # noqa: BLE001 - no such store/table: try the next one
        return None
    for match in matches:
        if str(match.get("coverage") or "") == "changes_only":
            continue
        try:
            rows = ctx.rows(
                alias,
                "SELECT isin FROM company_membership_pit WHERE index_code = ? "
                "AND added_on <= ? AND (removed_on IS NULL OR removed_on > ?)",
                (match["index_code"], as_of, as_of))
        except Exception:  # noqa: BLE001
            return None
        if rows:
            return ({r["isin"] for r in rows},
                    f"{alias} company_membership_pit {match['display_name']} at {as_of}")
    return None


def _pilot_universe(ctx: Any, question: str, as_of: str) -> tuple[set[str] | None, str | None]:
    """ISIN set from a pilot build (whole-market company_state_daily / membership_pit).

    The index universe prefers the pilot (b) ``company_membership_pit`` (dated
    intervals, 2019-2026); the T1 build is the fallback when the run points at it.
    Without either store every branch below behaves exactly as before.
    """
    tier = _tier(question)
    index = _index(question)
    if not tier and not index:
        return None, None
    if tier:
        try:
            ctx.sqlite("market_state")
        except Exception:  # noqa: BLE001 - no pilot build: fall through to the live path
            return None, None
        try:
            day = ctx.one("market_state", "SELECT MAX(date) AS d FROM company_state_daily "
                                          "WHERE date <= ?", (as_of,))
            day = (day or {}).get("d")
            rows = ctx.rows("market_state", "SELECT isin FROM company_state_daily "
                                            "WHERE date = ? AND mcap_bucket = ?", (day, tier))
        except Exception:  # noqa: BLE001
            return None, None
        if rows:
            return ({r["isin"] for r in rows},
                    f"T1 company_state_daily mcap_bucket={tier} on {day}")
        return None, None
    for alias in ("market_state_b", "market_state"):
        found = _membership_from(ctx, alias, index or "", as_of)
        if found:
            return found
    return None, None


#: Names one pilot (b) fallback screen reads at most (a bounded IN list, not a scan).
B_MAX_UNIVERSE = 900
#: "Made a new YTD high" is a level ask; "highest to lowest" is a ranking, not this.
WANT_HIGH = re.compile(r"\bnew (?:ytd |52[- ]week |all[- ]time )?high|"
                       r"\b(?:ytd|52[- ]week|all[- ]time) high|"
                       r"\bmade a (?:new )?high\b", re.I)
WANT_LOW = re.compile(r"\bnew (?:ytd |52[- ]week |all[- ]time )?low|"
                      r"\b(?:ytd|52[- ]week|all[- ]time) low|"
                      r"\bmade a (?:new )?low\b", re.I)


def _screen_rows_from_b(ctx: Any, where: str, params: list[Any], pre_from: str,
                        post_to: str) -> tuple[list[dict[str, Any]], str | None]:
    """(rows, note) from ``market_state_b.mkt_nse_full_daily`` for the same window.

    The live ``daily_price_delivery`` starts 2021-10-27 and stops 2026-09-24; the
    pilot (b) bhavcopy covers 2019-01-01..2026-10-19 for every NSE series EQ name,
    so a screen the live table cannot serve still runs.  Rows come back in the
    live query's column shape, joined to ``master_companies`` by symbol (the two
    stores are separate files, so the join is in Python).
    """
    try:
        universe = ctx.rows(
            "equity_intelligence",
            f"SELECT isin, nse_symbol, company_name FROM master_companies m WHERE {where}",
            params)
    except Exception:  # noqa: BLE001 - no universe: the live answer stands
        return [], None
    by_symbol = {str(row["nse_symbol"]).upper(): row for row in universe
                 if row.get("nse_symbol")}
    if not by_symbol:
        return [], None
    symbols = sorted(by_symbol)
    capped = len(symbols) if len(symbols) > B_MAX_UNIVERSE else None
    symbols = symbols[:B_MAX_UNIVERSE]
    out: list[dict[str, Any]] = []
    for start in range(0, len(symbols), 500):
        batch = symbols[start:start + 500]
        marks = ",".join("?" * len(batch))
        try:
            found = ctx.rows(
                "market_state_b",
                "SELECT symbol, date, close, high, delivery_pct, turnover_lacs "
                f"FROM mkt_nse_full_daily WHERE series = 'EQ' AND date BETWEEN ? AND ? "
                f"AND symbol IN ({marks})", [pre_from, post_to, *batch])
        except Exception:  # noqa: BLE001 - no pilot store: the live answer stands
            return [], None
        for row in found:
            meta = by_symbol.get(str(row["symbol"]).upper())
            if not meta:
                continue
            out.append({"isin": meta["isin"], "nse_symbol": meta["nse_symbol"],
                        "company_name": meta["company_name"], "date": row["date"],
                        "close": row["close"], "high": row["high"],
                        "delivery_pct": row["delivery_pct"],
                        "turnover_lacs": row["turnover_lacs"]})
    note = "prices/delivery from the pilot (b) full NSE bhavcopy"
    if capped:
        note += f" (universe capped at {B_MAX_UNIVERSE} of {capped} names)"
    return out, note


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    question = str(slots.get("question") or "")
    if not slots.get("needs", {}).get("screen"):
        return envelope("SCREEN", ok=True, na=True, checked=CHECKED,
                        detail="single-entity ask; SCREEN not applicable")
    # The held-field ladders run before the price screen: a holding/band ask names
    # a field (shp_index, price_bands, mkt_nse_insider), not a return window.
    if HOLDING_ASK.search(question):
        return _holding_screen(slots, as_of, ctx, question)
    if BAND_ASK.search(question):
        # One company's band is a SERIES field, not a market ranking: the SERIES
        # planner returns its price_bands row with its own date.
        universe = (str(slots.get("entity_level") or "stock") != "stock"
                    or bool(re.search(r"which (companies|names|stocks|large|mid|small)|"
                                      r"rank|top \d|for all", question, re.I)))
        if slots.get("symbol") and not universe:
            return envelope("SCREEN", ok=True, na=True, checked=CHECKED,
                            detail="single-entity band is a SERIES field")
        return _band_screen(slots, as_of, ctx, question)
    if VALUATION_ASK.search(question) and re.search(
            r"which|for all|rank|top \d|across|list", question, re.I):
        ranked = _valuation_screen(slots, as_of, ctx, question)
        if ranked:
            return ranked
    if re.search(r"\bNifty [A-Z]", question) and not re.search(
            r"which (companies|large|mid|small|stocks|names)", question, re.I):
        return envelope("SCREEN", ok=True, na=True, checked=CHECKED,
                        detail="index/sector rotation is a SERIES comparison, not a universe screen")
    status = str(slots.get("status") or "")
    if status.startswith("needs_new_table"):
        table = status.split(":", 1)[-1]
        if table in SCREEN_TABLES:
            ranked = _metric_screen(ctx, question, as_of, table)
            if ranked:
                return ranked
            return envelope("SCREEN", ok=False, why="schema", checked=CHECKED, gap=table,
                            detail=f"screen needs {table}; that table is not held yet",
                            nid_reason=f"BLOCKED_SCHEMA: {table}")
    allowed, pilot_note = _pilot_universe(ctx, question, as_of)
    named_index = _index(question)
    if named_index and allowed is None:
        try:
            snapshot = ctx.one("equity_intelligence",
                               "SELECT as_of FROM index_membership LIMIT 1")
            snapshot_day = str((snapshot or {}).get("as_of") or "")[:10]
            members = ctx.one(
                "equity_intelligence",
                "SELECT COUNT(*) AS n FROM index_membership WHERE lower(index_name) LIKE ?",
                (f"%{named_index.lower()}%",))
            if snapshot_day and snapshot_day > as_of:
                detail = (f"index membership is one snapshot dated {snapshot_day}; "
                          f"a screen as of {as_of} needs company_membership_pit")
                return envelope("SCREEN", ok=False, why="schema", checked=CHECKED,
                                gap="company_membership_pit", detail=detail, nid_reason=detail)
            if members is not None and int(members.get("n") or 0) == 0:
                detail = f"the held membership snapshot has no rows for {named_index}"
                return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                                detail=detail, nid_reason=detail)
        except Exception:
            pass
    date_from = slots.get("date_from") or as_of
    date_to = min(slots.get("date_to") or as_of, as_of)
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    from datetime import date as _date, timedelta
    anchor = date_from
    pre_from = (_date.fromisoformat(anchor) - timedelta(days=10)).isoformat()
    post_to = min(max(date_to, (_date.fromisoformat(anchor) + timedelta(days=10)).isoformat()),
                  as_of)
    where, params = (("m.is_active = 1", []) if allowed is not None
                     else _universe(ctx, question, slots))
    # The universe filter must run before the row LIMIT: a 200-name index set far
    # smaller than the live table would otherwise be cut down to whatever names
    # sort first (the "16 of 200 constituents" truncation).  Kept apart from
    # ``where`` because the pilot (b) fallback filters master_companies only.
    d_clause, d_params = "", []
    if allowed is not None and len(allowed) <= B_MAX_UNIVERSE:
        d_clause = f" AND d.isin IN ({','.join('?' * len(allowed))})"
        d_params = sorted(allowed)
    # A bound on the row count, sized to the universe (a year of 200 names is ~43k
    # rows, more than the old flat cap) so the LIMIT never silently drops names.
    row_limit = max(30000, len(d_params) * 400) if d_params else 30000
    b_note = None
    live_error = None
    try:
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT d.isin, m.nse_symbol, m.company_name, d.date, d.close, d.high, "
            "d.delivery_pct, d.turnover_lacs FROM daily_price_delivery d "
            "JOIN master_companies m ON m.isin = d.isin "
            f"WHERE d.date BETWEEN ? AND ? AND {where}{d_clause} "
            f"ORDER BY d.isin, d.date LIMIT {row_limit}",
            [pre_from, post_to, *params, *d_params])
    except Exception as exc:  # noqa: BLE001 - the pilot (b) bhavcopy may still hold the window
        rows, live_error = [], exc
    if not rows:
        rows, b_note = _screen_rows_from_b(ctx, where, params, pre_from, post_to)
    if not rows and live_error is not None:
        return envelope("SCREEN", ok=False, why="tool", checked=CHECKED,
                        detail=f"screen store failed: {type(live_error).__name__}: {live_error}")
    if allowed is not None:
        rows = [row for row in rows if row["isin"] in allowed]
    degraded = ([pilot_note, f"universe from the pilot build for the whole market at {as_of}"]
                if pilot_note else
                ["membership is the held snapshot, not a point-in-time index history"])
    if b_note:
        degraded.append(b_note)
    bucket: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = bucket.setdefault(row["isin"], {"symbol": row["nse_symbol"],
                                                "company": row["company_name"], "rows": []})
        entry["rows"].append(row)
    if not bucket:
        detail = (f"no price rows for the asked universe between {pre_from} and {post_to}")
        return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    # "Which names made a new YTD / 52-week high (or low), with the value and date?"
    # is a level-per-name ask, not a return ranking: report the extreme and its date.
    want_high = bool(WANT_HIGH.search(question))
    want_low = not want_high and bool(WANT_LOW.search(question))
    if want_high or want_low:
        column, item = ("high", "high") if want_high else ("low", "low")
        picked: list[tuple[dict[str, Any], float, str]] = []
        for entry in bucket.values():
            levels = [p for p in entry["rows"] if p.get(column) is not None]
            if not levels:
                continue
            extreme = (max if want_high else min)(levels, key=lambda p: float(p[column]))
            picked.append((entry, float(extreme[column]), str(extreme["date"])[:10]))
        picked.sort(key=lambda item_: item_[2], reverse=True)
        if not picked:
            detail = f"no {column} rows for the asked universe between {pre_from} and {post_to}"
            return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                            detail=detail, nid_reason=detail)
        top = picked[:15]
        detail = (f"{column}, {len(picked)} names, {pre_from}..{post_to}: " +
                  "; ".join(f"{entry['symbol'] or entry['rows'][0]['isin']} {fmt_num(v)} ({day})"
                            for entry, v, day in top[:5]))
        return envelope(
            "SCREEN", ok=True,
            rows=in_period([{"ref": f"daily_price_delivery:{entry['rows'][0]['isin']}",
                             "known_at": post_to, "period": day, "item": item,
                             "symbol": entry["symbol"], "value": v}
                            for entry, v, day in top], slots, hop="SCREEN"),
            provenance=[{"ref": f"SCREEN:{entry['symbol']}", "known_at": post_to}
                        for entry, _, _ in top[:5]],
            pit=f"daily rows date <= {as_of}; membership snapshot only", checked=CHECKED,
            degraded=degraded, detail=detail)
    if "turnover" in question.lower():
        # A turnover floor: rank only the most-traded 300 names in the window.
        bucket = dict(sorted(
            bucket.items(),
            key=lambda item: max(float(p["turnover_lacs"] or 0) for p in item[1]["rows"]),
            reverse=True)[:300])
    use_delivery = bool(re.search(r"delivery", question, re.I))
    falling = bool(re.search(r"fell|fall|losers?|decline|drop", question, re.I))
    ranked: list[tuple[dict[str, Any], float]] = []
    for entry in bucket.values():
        points = entry["rows"]
        if use_delivery:
            pre = [float(p["delivery_pct"]) for p in points
                   if p["date"] < anchor and p["delivery_pct"] is not None]
            post = [float(p["delivery_pct"]) for p in points
                    if p["date"] >= anchor and p["delivery_pct"] is not None]
            if not pre or not post:
                continue
            ranked.append((entry, sum(post) / len(post) - sum(pre) / len(pre)))
        else:
            if len(points) < 2:
                continue
            first, last = float(points[0]["close"]), float(points[-1]["close"])
            if not first:
                continue
            ranked.append((entry, (last / first - 1) * 100))
    ranked.sort(key=lambda item: item[1], reverse=(not falling) if not use_delivery else False)
    label = "delivery % change" if use_delivery else "window return %"
    if not ranked:
        detail = f"no {label} rows for the asked universe between {pre_from} and {post_to}"
        return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    top = ranked[:15]
    detail = (f"{label}, {len(ranked)} names, {pre_from}..{post_to}: " +
              "; ".join(f"{entry['symbol'] or entry['rows'][0]['isin']} {fmt_num(v)}"
                        for entry, v in top[:5]))
    period = date_from if date_from == date_to else f"{date_from}..{date_to}"
    rows = in_period(
        [{"ref": f"daily_price_delivery:{entry['rows'][0]['isin']}", "known_at": post_to,
          "period": period, "item": label, "symbol": entry["symbol"], "value": v}
         for entry, v in top], slots, hop="SCREEN")
    return envelope(
        "SCREEN", ok=True,
        rows=rows,
        provenance=[{"ref": f"SCREEN:{entry['symbol']}", "known_at": post_to}
                    for entry, _ in top[:5]],
        pit=f"daily rows date <= {as_of}; membership snapshot only", checked=CHECKED,
        degraded=degraded, detail=detail)
