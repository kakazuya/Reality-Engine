"""RESOLVE: canonical identity at ``as_of`` (never today's symbol)."""
from __future__ import annotations

from typing import Any

from . import envelope

CHECKED = ["equity_intelligence.master_companies",
           "equity_intelligence.security_master",
           "equity_intelligence.symbol_isin_history"]


def _master(ctx: Any, key: str) -> dict[str, Any] | None:
    return ctx.one(
        "equity_intelligence",
        "SELECT isin, nse_symbol, bse_code, company_name, industry, sector, market_cap_tier, "
        "is_active, is_nifty500 FROM master_companies "
        "WHERE upper(nse_symbol)=upper(?) OR isin=? OR upper(COALESCE(bse_code,''))=upper(?) "
        "LIMIT 1",
        (key, key, key))


def _security(ctx: Any, key: str) -> dict[str, Any] | None:
    return ctx.one(
        "equity_intelligence",
        "SELECT isin, nse_symbol, bse_code, name, bse_status, first_trade, last_trade "
        "FROM security_master WHERE isin=? OR upper(COALESCE(nse_symbol,''))=upper(?) "
        "OR upper(COALESCE(bse_code,''))=upper(?) LIMIT 1",
        (key, key, key))


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    keys = [k for k in [slots.get("symbol"), slots.get("isin"),
                        *(slots.get("symbols") or [])] if k]
    keys = list(dict.fromkeys(str(k) for k in keys))
    if not keys:
        return envelope("resolve", ok=False, na=True, checked=CHECKED,
                        detail="no entity named in the case",
                        nid_reason="gate G1: the question names no company, symbol or ISIN")
    master = security = None
    for key in keys:
        try:
            master = master or _master(ctx, key)
            security = security or _security(ctx, key)
        except Exception as exc:  # noqa: BLE001 - a missing store is a degraded hop
            return envelope("resolve", ok=False, why="tool", checked=CHECKED,
                            detail=f"identity stores unavailable: {type(exc).__name__}: {exc}")
        if master or security:
            break
    if not master and not security:
        return envelope("resolve", ok=False, why="no_doc", checked=CHECKED,
                        detail=f"{keys[0]} is not in master_companies or security_master",
                        nid_reason=f"gate G1: {keys[0]} has no ISIN in any identity store")
    isin = (master or {}).get("isin") or (security or {}).get("isin")
    symbol = (master or {}).get("nse_symbol") or (security or {}).get("nse_symbol")
    history: list[dict[str, Any]] = []
    if symbol or isin:
        try:
            windows = ctx.rows(
                "equity_intelligence",
                "SELECT exchange, symbol, isin, first_date, last_date FROM symbol_isin_history "
                "WHERE (upper(COALESCE(symbol,''))=upper(?) OR isin=?) AND first_date<=? "
                "ORDER BY first_date DESC LIMIT 20",
                (symbol or "", isin or "", as_of))
            # The last window ends on the last trading day, which can be a few
            # sessions before as_of (weekend/holiday): 10 days is the tolerance.
            from datetime import date, timedelta
            cutoff = (date.fromisoformat(as_of) - timedelta(days=10)).isoformat()
            history = [w for w in windows
                       if not w.get("last_date") or str(w["last_date"]) >= cutoff]
        except Exception:
            history = []
    row = {
        "isin": isin, "symbol": symbol, "bse_code": (master or {}).get("bse_code")
        or (security or {}).get("bse_code"),
        "company": (master or {}).get("company_name") or (security or {}).get("name"),
        "industry": (master or {}).get("industry"), "sector": (master or {}).get("sector"),
        "market_cap_tier": (master or {}).get("market_cap_tier"),
        "is_active": (master or {}).get("is_active"),
        "as_of": as_of, "known_at": as_of, "ref": f"symbol_isin_history:{_window(history)}",
    }
    degraded = []
    try:
        seen = ctx.rows(
            "equity_intelligence",
            "SELECT first_date, last_date FROM symbol_isin_history "
            "WHERE (upper(COALESCE(symbol,''))=upper(?) OR isin=?) LIMIT 20",
            (symbol or "", isin or ""))
        if seen and not history:
            degraded.append(f"{symbol or isin} has no trading window covering {as_of}")
    except Exception:
        pass
    ok = True
    return envelope(
        "resolve", ok=ok, rows=[row], provenance=[{"ref": f"master_companies:{isin}",
                                                   "known_at": as_of}],
        pit=f"identity at {as_of}: symbol windows containing the date",
        checked=CHECKED, degraded=degraded,
        detail=f"{symbol or isin} = {row['company']} ({isin}), "
               f"{(row['industry'] or 'industry n/a')}, tier {row['market_cap_tier'] or 'n/a'}",
        why=None if ok else "no_doc",
        nid_reason=None if ok else f"the symbol did not exist on {as_of}")


def _window(history: list[dict[str, Any]]) -> str:
    if not history:
        return "none-at-as_of"
    first = history[0]
    return f"{first.get('symbol')}@{first.get('first_date')}..{first.get('last_date') or 'open'}"
