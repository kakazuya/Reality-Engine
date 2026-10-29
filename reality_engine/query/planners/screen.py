"""SCREEN: rank a held universe on one dated metric (or name the missing table)."""
from __future__ import annotations

import re
from typing import Any

from . import envelope, fmt_num, in_period

CHECKED = ["equity_intelligence.master_companies", "equity_intelligence.index_membership",
           "equity_intelligence.daily_price_delivery", "equity_intelligence.quarterly_financials",
           "equity_intelligence.shp_index"]

SCREEN_TABLES = ("company_state_daily", "price_band_daily", "sector_flow_daily",
                 "company_metric_series", "company_membership_pit", "event_day0",
                 "company_theme_pit", "company_operating_metrics")


def _promoter_screen(slots: dict[str, Any], as_of: str, ctx: Any, question: str) -> dict[str, Any]:
    """Biggest promoter-holding change over the last year, from shp_index (PIT broadcast).

    A named month/quarter ask ranks that quarter's holding level instead: the
    window the router resolved decides which shareholding filing is in scope.
    """
    from datetime import date, timedelta
    floor = (date.fromisoformat(as_of) - timedelta(days=400)).isoformat()
    tier = _tier(question)
    where = ["COALESCE(s.broadcast_at,'') <> ''", "substr(s.broadcast_at,1,10) <= ?",
             "s.quarter_end >= ?"]
    params: list[Any] = [as_of, floor]
    want_public = bool(re.search(r"\bpublic\b", question, re.I))
    if tier:
        where.append("m.market_cap_tier = ?")
        params.append(tier)
    basis = str(slots.get("period_basis") or "")
    low, high = str(slots.get("date_from") or "")[:10], str(slots.get("date_to") or "")[:10]
    window = None
    if basis in ("month", "quarter end", "month span", "named date", "named dates") \
            and low and high:
        window = ((date.fromisoformat(low) - timedelta(days=3)).isoformat(),
                  (date.fromisoformat(high) + timedelta(days=3)).isoformat())
        where.append("s.quarter_end >= ? AND s.quarter_end <= ?")
        params.extend(window)
    try:
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT s.isin, s.symbol, s.quarter_end, s.promoter_pct, s.public_pct, "
            "s.broadcast_at, m.market_cap_tier FROM shp_index s "
            "JOIN master_companies m ON m.isin = s.isin "
            f"WHERE {' AND '.join(where)} ORDER BY s.isin, s.quarter_end", params)
    except Exception as exc:  # noqa: BLE001
        return envelope("SCREEN", ok=False, why="tool", checked=CHECKED,
                        detail=f"promoter screen failed: {type(exc).__name__}: {exc}")
    bucket: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket.setdefault(row["isin"], []).append(row)
    ranked = []
    level = False
    for points in bucket.values():
        column = "public_pct" if want_public else "promoter_pct"
        if points[-1][column] is None:
            continue
        if len(points) < 2 or window:
            # An in-window filing is a level ("as of Sep 2026"), not a change.
            ranked.append((points[-1], float(points[-1][column])))
            level = True
            continue
        if points[0][column] is None:
            continue
        ranked.append((points[-1], float(points[-1][column]) - float(points[0][column])))
    if not ranked:
        detail = f"no two shareholding filings within 400 days of {as_of}"
        return envelope("SCREEN", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    ranked.sort(key=lambda item: item[1], reverse=level)
    top = ranked[:15]
    item = ("Public holding %" if want_public else "Promoter holding %") if level \
        else "Promoter holding change (pp)"
    detail = (f"{item}, " +
              "; ".join(f"{row['symbol']} {value:+.2f}"
                        f"{'' if level else 'pp'} ({row['quarter_end']})"
                        for row, value in top[:5]))
    return envelope(
        "SCREEN", ok=True,
        rows=[{"ref": f"shp_index:{row['isin']}", "known_at": str(row["broadcast_at"])[:10],
               "period": row["quarter_end"], "item": item,
               "symbol": row["symbol"], "value": value} for row, value in top],
        provenance=[{"ref": f"SCREEN:shp_index:{row['isin']}",
                     "known_at": str(row["broadcast_at"])[:10]} for row, _ in top[:5]],
        pit=f"broadcast_at date <= {as_of}; quarter_end within 400 days",
        checked=CHECKED,
        detail=detail)


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


def _pilot_universe(ctx: Any, question: str, as_of: str) -> tuple[set[str] | None, str | None]:
    """ISIN set from the T1 pilot build (whole-market company_state_daily / membership_pit).

    Only used when the run points at the build (``REALITY_PILOT_T1``); without it every
    branch below behaves exactly as before.
    """
    tier = _tier(question)
    index = _index(question)
    if not tier and not index:
        return None, None
    try:
        ctx.sqlite("market_state")
    except Exception:  # noqa: BLE001 - no pilot build: fall through to the live path
        return None, None
    if tier:
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
    try:
        matches = ctx.rows("market_state", "SELECT index_code, display_name FROM index_list "
                                          "WHERE lower(display_name) LIKE ?",
                           (f"%{index.lower()}%",))
        if not matches:
            return None, None
        codes = [m["index_code"] for m in matches]
        rows = ctx.rows(
            "market_state",
            "SELECT isin FROM company_membership_pit WHERE index_code IN ("
            + ",".join("?" * len(codes)) + ") AND added_on <= ? "
            "AND (removed_on IS NULL OR removed_on > ?)", codes + [as_of, as_of])
    except Exception:  # noqa: BLE001
        return None, None
    if rows:
        return ({r["isin"] for r in rows},
                f"T1 company_membership_pit {matches[0]['display_name']} at {as_of}")
    return None, None


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    question = str(slots.get("question") or "")
    if not slots.get("needs", {}).get("screen"):
        return envelope("SCREEN", ok=True, na=True, checked=CHECKED,
                        detail="single-entity ask; SCREEN not applicable")
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
    if slots.get("metric") == "promoter" and re.search(r"which|biggest|largest|most|rank",
                                                       question, re.I):
        return _promoter_screen(slots, as_of, ctx, question)
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
    try:
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT d.isin, m.nse_symbol, m.company_name, d.date, d.close, d.delivery_pct, "
            "d.turnover_lacs FROM daily_price_delivery d JOIN master_companies m ON m.isin = d.isin "
            f"WHERE d.date BETWEEN ? AND ? AND {where} ORDER BY d.isin, d.date LIMIT 30000",
            [pre_from, post_to, *params])
    except Exception as exc:  # noqa: BLE001
        return envelope("SCREEN", ok=False, why="tool", checked=CHECKED,
                        detail=f"screen store failed: {type(exc).__name__}: {exc}")
    if allowed is not None:
        rows = [row for row in rows if row["isin"] in allowed]
    bucket: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = bucket.setdefault(row["isin"], {"symbol": row["nse_symbol"],
                                                "company": row["company_name"], "rows": []})
        entry["rows"].append(row)
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
    degraded = ([pilot_note, f"universe from the T1 pilot build for the whole market at {as_of}"]
                if pilot_note else
                ["membership is the held snapshot, not a point-in-time index history"])
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
