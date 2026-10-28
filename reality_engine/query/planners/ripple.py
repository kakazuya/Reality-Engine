"""RIPPLE: trigger -> exposure -> transmission -> market, stopping at the gap.

Stage 1 reads ``policy_events`` (PIT ``published_at``).  When the claim-target table
is held (``macro_claim_target`` in the live DB, or the pilot DB named by
``REALITY_MACRO_PILOT_DB``), stage 2 takes the claim's own curated targets —
sector / basic industry / ISIN / theme — instead of re-parsing the free-text
``policy_events.sectors``; without it the planner falls back to the text parse so
nothing regresses.  Stage 3 (cost/segment transmission) is not held yet, so a
chain that needs it says which table is missing instead of inventing the link.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from reality_engine.query import compute

from . import envelope, fmt_num, terms_clause

CHECKED = ["equity_intelligence.policy_events", "equity_intelligence.master_companies",
           "equity_intelligence.daily_price_delivery", "macro_claim_target"]
MISSING_TABLES = ["company_cost_structure", "company_segment_pnl", "company_price_revision",
                  "macro_claim_target", "company_sector_pit"]
MAX_TARGETS = 40


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


def _claim_target_rows(ctx: Any, policy_id: Any, as_of: str) -> tuple[list[dict], str | None]:
    """Target rows for one claim, PIT-filtered on the claim document's known_at."""
    for db in ("equity_intelligence", "macro_pilot"):
        try:
            claim = ctx.one(db, "SELECT doc_id, known_at FROM macro_claim WHERE claim_id=?",
                            (policy_id,))
        except Exception:  # noqa: BLE001 - a DDL-built table may not carry the pilot column
            try:
                claim = ctx.one(db, "SELECT doc_id FROM macro_claim WHERE claim_id=?",
                                (policy_id,))
            except Exception:  # noqa: BLE001 - the table is a pilot, not every root has it
                continue
        if not claim:
            continue
        known = str(claim.get("known_at") or "")
        if not known:
            doc = ctx.one(db, "SELECT known_at FROM macro_doc WHERE doc_id=?",
                          (claim.get("doc_id"),))
            known = str((doc or {}).get("known_at") or "")
        if not known or known[:10] > as_of:
            continue
        rows = ctx.rows(
            db,
            "SELECT target_kind, target_id, direction, weight FROM macro_claim_target "
            "WHERE claim_id=? ORDER BY weight DESC, target_kind, target_id LIMIT ?",
            (policy_id, MAX_TARGETS))
        if rows:
            return rows, db
    return [], None


def _company_rows(ctx: Any, sql: str, args: tuple) -> list[dict]:
    try:
        return ctx.rows("equity_intelligence", sql, args)
    except Exception:  # noqa: BLE001 - a fixture root may hold only one industry table
        return []


def _targets_from_claims(ctx: Any, rows: list[dict], as_of: str) -> tuple[list[dict], list[str]]:
    """macro_claim_target -> held ISINs (sector/basic_industry/isin/theme)."""
    found: dict[str, dict] = {}
    notes: list[str] = []

    def add(company: dict, kind: str, ident: str) -> None:
        isin = str(company.get("isin") or "")
        if isin and isin not in found and len(found) < MAX_TARGETS:
            found[isin] = {"isin": isin, "nse_symbol": company.get("nse_symbol"),
                           "company_name": company.get("company_name"),
                           "target_kind": kind, "target_id": ident}

    for target in rows:
        kind, ident = str(target.get("target_kind") or ""), str(target.get("target_id") or "")
        if kind == "isin":
            add({"isin": ident}, kind, ident)
        elif kind == "sector":
            for row in _company_rows(
                    ctx, "SELECT isin, symbol AS nse_symbol FROM company_industry "
                         "WHERE sector=? LIMIT ?", (ident, MAX_TARGETS)):
                add(row, kind, ident)
            for row in _company_rows(
                    ctx, "SELECT isin, nse_symbol, company_name FROM master_companies "
                         "WHERE is_active=1 AND (sector=? OR industry=?) LIMIT ?",
                    (ident, ident, MAX_TARGETS)):
                add(row, kind, ident)
        elif kind == "basic_industry":
            for row in _company_rows(
                    ctx, "SELECT isin, symbol AS nse_symbol FROM company_industry "
                         "WHERE basic_industry=? LIMIT ?", (ident, MAX_TARGETS)):
                add(row, kind, ident)
        elif kind == "theme":
            try:
                theme_rows = ctx.rows(
                    "equity_intelligence",
                    "SELECT isin FROM universe_membership WHERE theme=? "
                    "AND (valid_from IS NULL OR valid_from<=?) "
                    "AND (valid_to IS NULL OR valid_to>=?) LIMIT ?",
                    (ident, as_of, as_of, MAX_TARGETS))
            except Exception:  # noqa: BLE001 - theme membership is not built in the live DB
                theme_rows = []
            for row in theme_rows:
                add(row, kind, ident)
            if not theme_rows:
                notes.append(f"theme '{ident}' membership table not held")
        else:
            notes.append(f"{kind} target '{ident}' has no held ISIN map")
    return list(found.values()), notes


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
    claim_rows, claim_db = _claim_target_rows(ctx, policy["id"], as_of)
    claim_targets, claim_notes = (_targets_from_claims(ctx, claim_rows, as_of)
                                  if claim_rows else ([], []))
    targets = claim_targets or _targets(ctx, policy)
    target_source = (f"macro_claim_target ({claim_db})" if claim_targets
                     else "policy_events.sectors")
    anchor = str(policy.get("effective_date") or policy.get("published_at") or as_of)[:10]
    moves = _market(ctx, [t["isin"] for t in targets], anchor, as_of)
    if not targets:
        missing = gate_table or ("macro_claim_target" if claim_rows else "company_sector_pit")
        detail = (f"policy {policy.get('title') or policy.get('policy_name')} matched, but its "
                  f"sector/company targets do not map to held ISINs ({missing})")
        if claim_notes:
            detail += "; " + "; ".join(claim_notes[:2])
        return envelope("RIPPLE", ok=False, why="schema", checked=CHECKED, gap=missing,
                        detail=detail, nid_reason=detail)
    detail = (f"trigger: {policy.get('policy_name') or policy.get('title')} "
              f"(known {str(policy.get('published_at'))[:10]}, effective {anchor}); "
              f"{len(targets)} held target(s) via {target_source}")
    ranked = sorted(moves.items(), key=lambda item: item[1], reverse=True)
    if ranked:
        names = {t["isin"]: t["nse_symbol"] for t in targets}
        detail += "; market: " + ", ".join(f"{names.get(i) or i} {fmt_num(v)}%"
                                           for i, v in ranked[:4])
    degraded = ["transmission hop (input share / pass-through) is not held: "
                "company_cost_structure, company_segment_pnl"]
    if claim_notes:
        degraded.append("claim target map: " + "; ".join(claim_notes[:3]))
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
