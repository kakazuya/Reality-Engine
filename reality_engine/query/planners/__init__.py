"""Planner registry and the shared hop envelope.

Every planner is ``plan(slots, as_of, ctx) -> envelope``.  The envelope is the
same shape for all eight planners so ``answer.py`` (and the grading harness)
can treat a hop uniformly.  ``ok`` means "this hop answered its part of the
ask", ``na`` means "this hop does not apply to this question" (not a failure),
and an empty hop always carries ``nid_reason``.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence


def envelope(hop: str, *, ok: bool | None = None, na: bool = False,
             rows: Sequence[Any] = (), provenance: Sequence[Any] = (),
             pit: str | None = None, checked: Sequence[str] = (),
             degraded: Sequence[str] = (), detail: str | None = None,
             why: str | None = None, gap: str | None = None,
             nid_reason: str | None = None) -> dict[str, Any]:
    evidence = []
    for item in provenance:
        if isinstance(item, dict) and item.get("known_at"):
            evidence.append(f"{str(item['known_at'])[:10]}:{hop}:{item.get('ref') or ''}")
        elif isinstance(item, str) and len(item) >= 10:
            evidence.append(item)
    if not evidence:
        for item in rows:
            known = item.get("known_at") if isinstance(item, dict) else None
            if known:
                evidence.append(f"{str(known)[:10]}:{hop}:{item.get('ref') or item.get('doc_id') or ''}")
    empty = not rows
    if empty and not nid_reason and not na:
        nid_reason = detail or f"{hop}: no row survived the as_of filter"
    return {
        "hop": hop, "ok": False if na else (bool(ok) if ok is not None else False),
        "na": bool(na),
        "rows": list(rows), "provenance": list(provenance), "pit": pit,
        "checked": list(checked), "degraded": list(degraded),
        "detail": detail, "why": why, "gap": gap, "nid_reason": nid_reason,
        "empty": empty, "evidence": evidence[:8],
    }


def fmt_num(value: Any, unit: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000:
        text = f"{number:,.0f}"
    elif abs(number) >= 10:
        text = f"{number:,.1f}"
    else:
        text = f"{number:,.2f}"
    return f"{text} {unit}".strip()


def isin_of(slots: dict[str, Any], ctx: Any, as_of: str) -> str | None:
    """ISIN from the case, else the PIT identity lookup (never today's symbol)."""
    if slots.get("isin"):
        return str(slots["isin"])
    symbol = slots.get("symbol")
    if not symbol:
        return None
    try:
        row = ctx.one(
            "equity_intelligence",
            "SELECT isin FROM master_companies WHERE upper(nse_symbol)=upper(?) LIMIT 1",
            (symbol,))
        if row:
            return row["isin"]
        row = ctx.one(
            "equity_intelligence",
            "SELECT isin FROM symbol_isin_history WHERE symbol=? AND first_date<=? "
            "AND (last_date IS NULL OR last_date>=?) ORDER BY first_date DESC LIMIT 1",
            (symbol, as_of, as_of))
        return row["isin"] if row else None
    except Exception:
        return None


def terms_clause(terms: Sequence[str], columns: Sequence[str],
                 mode: str = "or") -> tuple[str, list[Any]]:
    """LIKE clause over ``columns`` for the asked terms (SQL, no Python filter)."""
    clean = [str(t).lower() for t in terms if str(t).strip()]
    if not clean:
        return "", []
    parts, params = [], []
    for term in clean:
        inner = " OR ".join(f"lower(COALESCE({col},'')) LIKE ?" for col in columns)
        parts.append(f"({inner})")
        params.extend([f"%{term}%"] * len(columns))
    joiner = " AND " if mode == "and" else " OR "
    return "(" + joiner.join(parts) + ")", params


def identity_symbols(ctx: Any, slots: dict[str, Any], isin: str | None) -> list[str]:
    out = []
    if slots.get("symbol"):
        out.append(str(slots["symbol"]).upper())
    if not out and isin:
        try:
            row = ctx.one("equity_intelligence",
                          "SELECT nse_symbol FROM master_companies WHERE isin=?", (isin,))
            if row and row.get("nse_symbol"):
                out.append(str(row["nse_symbol"]).upper())
        except Exception:
            pass
    return out


def load_planners() -> dict[str, Callable[..., dict[str, Any]]]:
    from . import compare, event, evidence, expectations, facts, resolve, ripple, screen, series
    return {
        "resolve": resolve.plan, "FACTS": facts.plan, "SERIES": series.plan,
        "SCREEN": screen.plan, "EVENT": event.plan, "EVIDENCE": evidence.plan,
        "COMPARE": compare.plan, "RIPPLE": ripple.plan,
        "EXPECTATIONS": expectations.plan,
    }
