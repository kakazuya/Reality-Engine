"""RIPPLE: trigger -> exposure -> transmission -> market, stopping at the gap.

Stage 1 reads ``policy_events`` (PIT ``published_at``).  Stage 2 maps its
sectors/companies to held ISINs through ``master_companies``.  Stage 4 measures
the market from the daily series.  Stage 3 (cost/segment transmission) is not
held yet, so a chain that needs it says which table is missing instead of
inventing the link.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, terms_clause

CHECKED = ["equity_intelligence.policy_events", "equity_intelligence.master_companies",
           "equity_intelligence.daily_price_delivery"]
MISSING_TABLES = ["company_cost_structure", "company_segment_pnl", "company_price_revision",
                  "macro_claim_target", "company_sector_pit"]


def _policy(ctx: Any, slots: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    terms = [t for t in (slots.get("terms") or []) if len(t) > 3][:4]
    clause, params = terms_clause(terms, ["title", "policy_name", "sectors", "companies",
                                          "products", "quote"])
    where = ["COALESCE(published_at,'') <> ''", "substr(published_at,1,10) <= ?"]
    args: list[Any] = [as_of]
    if clause:
        where.append(clause)
        args.extend(params)
    return ctx.rows(
        "equity_intelligence",
        "SELECT id, title, policy_name, sectors, companies, direction_for_industry, "
        "effective_date, published_at, quote FROM policy_events "
        f"WHERE {' AND '.join(where)} ORDER BY published_at DESC LIMIT 5", args)


def _targets(ctx: Any, policy: dict[str, Any]) -> list[dict[str, Any]]:
    sectors = [s.strip().lower() for s in re.split(r"[,;|]", policy.get("sectors") or "")
               if len(s.strip()) > 2][:4]
    companies = [c.strip() for c in re.split(r"[,;|]", policy.get("companies") or "")
                 if len(c.strip()) > 2][:8]
    if companies:
        clauses = " OR ".join("upper(COALESCE(company_name,'')) LIKE ?" for _ in companies)
        return ctx.rows(
            "equity_intelligence",
            f"SELECT isin, nse_symbol, company_name FROM master_companies WHERE {clauses} "
            "AND is_active=1 LIMIT 20", [f"%{c.upper()}%" for c in companies])
    if sectors:
        clauses = " OR ".join("lower(COALESCE(sector,'') || ' ' || COALESCE(industry,'')) LIKE ?"
                              for _ in sectors)
        return ctx.rows(
            "equity_intelligence",
            f"SELECT isin, nse_symbol, company_name FROM master_companies WHERE {clauses} "
            "AND is_active=1 LIMIT 25", [f"%{s}%" for s in sectors])
    return []


def _market(ctx: Any, isins: list[str], anchor: str, as_of: str) -> dict[str, float]:
    if not isins:
        return {}
    try:
        start = (date.fromisoformat(anchor) - timedelta(days=5)).isoformat()
        end = min((date.fromisoformat(anchor) + timedelta(days=10)).isoformat(), as_of)
        marks = ",".join("?" * len(isins))
        rows = ctx.rows(
            "equity_intelligence",
            "SELECT isin, date, close FROM daily_price_delivery "
            f"WHERE isin IN ({marks}) AND date >= ? AND date <= ? ORDER BY isin, date",
            [*isins, start, end])
    except Exception:
        return {}
    bucket: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        bucket.setdefault(row["isin"], []).append((row["date"], row["close"]))
    out = {}
    for isin, points in bucket.items():
        ret, _, _ = compute.window_return(points)
        if ret is not None:
            out[isin] = ret
    return out


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    if not slots.get("needs", {}).get("ripple"):
        return envelope("RIPPLE", ok=True, na=True, checked=CHECKED,
                        detail="no policy/ripple chain asked; RIPPLE not applicable")
    status = str(slots.get("status") or "")
    gate_table = (status.split(":", 1)[-1] if status.startswith("needs_new_table:") else None)
    try:
        policies = _policy(ctx, slots, as_of)
    except Exception as exc:  # noqa: BLE001
        return envelope("RIPPLE", ok=False, why="tool", checked=CHECKED,
                        detail=f"policy store failed: {type(exc).__name__}: {exc}")
    if not policies:
        detail = f"no policy event matching the ask published on or before {as_of}"
        if gate_table:
            return envelope("RIPPLE", ok=False, why="schema", checked=CHECKED, gap=gate_table,
                            detail=f"{detail}; the chain needs {gate_table}",
                            nid_reason=f"BLOCKED_SCHEMA: {gate_table}")
        return envelope("RIPPLE", ok=False, why="no_doc", checked=CHECKED,
                        detail=detail, nid_reason=detail)
    policy = policies[0]
    targets = _targets(ctx, policy)
    anchor = str(policy.get("effective_date") or policy.get("published_at") or as_of)[:10]
    moves = _market(ctx, [t["isin"] for t in targets], anchor, as_of)
    if not targets:
        missing = gate_table or "company_sector_pit"
        detail = (f"policy {policy.get('title') or policy.get('policy_name')} matched, but its "
                  f"sector/company targets do not map to held ISINs ({missing})")
        return envelope("RIPPLE", ok=False, why="schema", checked=CHECKED, gap=missing,
                        detail=detail, nid_reason=detail)
    detail = (f"trigger: {policy.get('policy_name') or policy.get('title')} "
              f"(known {str(policy.get('published_at'))[:10]}, effective {anchor}); "
              f"{len(targets)} held target(s)")
    ranked = sorted(moves.items(), key=lambda item: item[1], reverse=True)
    if ranked:
        names = {t["isin"]: t["nse_symbol"] for t in targets}
        detail += "; market: " + ", ".join(f"{names.get(i) or i} {fmt_num(v)}%"
                                           for i, v in ranked[:4])
    degraded = ["transmission hop (input share / pass-through) is not held: "
                "company_cost_structure, company_segment_pnl"]
    ok = True
    return envelope(
        "RIPPLE", ok=ok, gap=None,
        rows=[{"ref": f"policy_events:{policy['id']}", "known_at": str(policy["published_at"])[:10],
               "title": policy.get("title")}] +
              [{"ref": f"daily_price_delivery:{isin}", "known_at": as_of, "return_pct": value}
               for isin, value in ranked[:10]],
        provenance=[{"ref": f"policy_events:{policy['id']}",
                     "known_at": str(policy["published_at"])[:10]}],
        pit=f"claim published_at <= {as_of}; market rows date <= {as_of}", checked=CHECKED,
        degraded=degraded, detail=detail,
        nid_reason=None if ok else detail)
