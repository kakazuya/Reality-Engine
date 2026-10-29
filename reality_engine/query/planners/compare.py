"""COMPARE: the same metric or window return over a peer set, ranked.

Peers come from the case's named symbols, else ``master_companies.industry`` of
the seed company.  Every peer's fact carries its own ``known_at <= as_of`` and a
later filing never leaks into an earlier comparison.
"""
from __future__ import annotations

import re
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, in_period, isin_of

CHECKED = ["results_xbrl.filings", "results_xbrl.facts",
           "equity_intelligence.daily_price_delivery", "equity_intelligence.master_companies"]
FIN_METRICS = {"revenue", "pat", "margin", "ebitda", "eps", "valuation", "dso", "cfo",
               "order_book", "capacity", "net_npa", "promoter"}


def _seed_isin(ctx: Any, slots: dict[str, Any], as_of: str) -> str | None:
    return isin_of(slots, ctx, as_of)


def _peer_isins(ctx: Any, slots: dict[str, Any], seed: str | None) -> list[str]:
    out: list[str] = []
    for key in slots.get("symbols") or []:
        try:
            row = ctx.one("equity_intelligence",
                          "SELECT isin FROM master_companies WHERE upper(nse_symbol)=upper(?) "
                          "OR isin=? LIMIT 1", (key, key))
            if row and row["isin"] not in out:
                out.append(row["isin"])
        except Exception:
            continue
    if len(out) < 2 and seed:
        try:
            row = ctx.one("equity_intelligence", "SELECT industry FROM master_companies WHERE isin=?",
                          (seed,))
            if row and row.get("industry"):
                peers = ctx.rows(
                    "equity_intelligence",
                    "SELECT isin FROM master_companies WHERE industry=? AND isin<>? "
                    "ORDER BY is_nifty500 DESC, isin LIMIT 10", (row["industry"], seed))
                out += [r["isin"] for r in peers if r["isin"] not in out]
        except Exception:
            pass
    return out[:10]


def _price_returns(ctx: Any, isins: list[str], start: str, end: str) -> dict[str, float]:
    if not isins:
        return {}
    marks = ",".join("?" * len(isins))
    rows: list[dict[str, Any]] = []
    try:
        rows = ctx.duck_rows(
            "SELECT isin, date, adj_close AS close FROM px_daily "
            f"WHERE isin IN ({marks}) AND date >= ? AND date <= ? ORDER BY isin, date",
            [*isins, start, end])
    except Exception:
        rows = []
    if not rows:
        try:
            rows = ctx.rows(
                "equity_intelligence",
                "SELECT isin, date, close FROM daily_price_delivery "
                f"WHERE isin IN ({marks}) AND date >= ? AND date <= ? ORDER BY isin, date",
                [*isins, start, end])
        except Exception:
            return {}
    bucket: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        bucket.setdefault(row["isin"], []).append((str(row["date"])[:10], row["close"]))
    out = {}
    for isin, points in bucket.items():
        ret, _, _ = compute.window_return(points)
        if ret is not None:
            out[isin] = ret
    return out


def _fin_growth(ctx: Any, isins: list[str], as_of: str,
                period: tuple[str | None, str | None] = (None, None)
                ) -> dict[str, tuple[float, str]]:
    if not isins:
        return {}
    marks = ",".join("?" * len(isins))
    where = [f"fi.isin IN ({marks})", "x.concept = 'RevenueFromOperations'",
             "x.value IS NOT NULL",
             "COALESCE(f.dissem_ts,f.broadcast_ts,f.filing_ts) <> ''",
             "substr(COALESCE(f.dissem_ts,f.broadcast_ts,f.filing_ts),1,10) <= ?"]
    params: list[Any] = [*isins, as_of]
    if period[0] and period[1]:
        from datetime import date, timedelta
        low = period[0]
        if period[0] == period[1]:
            # A single requested quarter: grow it against the same quarter a year
            # ago, so the row still sits in the asked quarter.
            low = (date.fromisoformat(period[0]) - timedelta(days=370)).isoformat()
        where.append("f.period_end >= ? AND f.period_end <= ?")
        params.extend([low, period[1]])
    try:
        rows = ctx.rows(
            "results_xbrl",
            "SELECT fi.isin, f.period_end, x.concept, x.value FROM filings f "
            "JOIN filings_isin fi ON fi.file = f.file JOIN facts x ON x.file = f.file "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY fi.isin, f.period_end", params)
    except Exception:
        return {}
    bucket: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        bucket.setdefault(row["isin"], []).append((str(row["period_end"])[:10], row["value"]))
    out: dict[str, tuple[float, str]] = {}
    for isin, points in bucket.items():
        points = sorted({d: v for d, v in points}.items())
        if len(points) < 2:
            continue
        latest, prior = points[-1], points[-2]
        growth = compute.growth(prior[1], latest[1])
        if growth is not None:
            out[isin] = (growth, latest[0])
    return out


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    if not slots.get("needs", {}).get("compare"):
        return envelope("COMPARE", ok=True, na=True, checked=CHECKED,
                        detail="no peer comparison asked; COMPARE not applicable")
    seed = _seed_isin(ctx, slots, as_of)
    isins = _peer_isins(ctx, slots, seed)
    if len(isins) < 2:
        detail = ("fewer than two peers resolve at as_of; "
                  "a peer table (company_sector_pit) is the missing piece")
        return envelope("COMPARE", ok=False, why="schema", checked=CHECKED, gap="company_sector_pit",
                        detail=detail, nid_reason=detail)
    metric = slots.get("metric")
    question = str(slots.get("question") or "")
    price_ask = bool(re.search(r"relative strength|outperform|underperform|better|worse|"
                               r"return|perform|price", question, re.I))
    start = slots.get("date_from") or as_of
    end = min(slots.get("date_to") or as_of, as_of)
    period = (slots.get("date_from"), slots.get("date_to"))
    if metric in FIN_METRICS and not price_ask:
        values = _fin_growth(ctx, isins, as_of, period)
        label = "revenue growth (filed for the asked period, PIT)"
        periods = {k: v[1] for k, v in values.items()}
    else:
        values = _price_returns(ctx, isins, start, end)
        label = f"window return % {start}..{end}"
        periods = {}
    if len(values) < 2:
        detail = f"no comparable {metric or 'metric'} for two peers filed by {as_of}"
        return envelope("COMPARE", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    ranked = compute.rank({k: (v[0] if isinstance(v, tuple) else v) for k, v in values.items()})
    names = {}
    try:
        marks = ",".join("?" * len(values))
        for row in ctx.rows("equity_intelligence",
                            f"SELECT isin, nse_symbol FROM master_companies WHERE isin IN ({marks})",
                            list(values)):
            names[row["isin"]] = row["nse_symbol"]
    except Exception:
        pass
    detail = f"{label}: " + "; ".join(
        f"{names.get(isin) or isin} {fmt_num(value, '')}" for isin, value, _ in ranked)
    known = max((v[1] for v in values.values() if isinstance(v, tuple)), default=end)
    window = start if start == end else f"{start}..{end}"
    rows = in_period(
        [{"ref": f"peer:{isin}", "known_at": known, "value": value, "rank": rank,
          "period": periods.get(isin) or window} for isin, value, rank in ranked],
        slots, hop="COMPARE")
    return envelope(
        "COMPARE", ok=True,
        rows=rows,
        provenance=[{"ref": f"COMPARE:{isin}", "known_at": known} for isin, _, _ in ranked],
        pit=f"each peer's own filing timestamp <= {as_of}", checked=CHECKED,
        detail=detail)
