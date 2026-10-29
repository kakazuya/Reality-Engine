"""Assemble the hops into one structured answer, or the NOT-IN-DATA wording.

v1 (2026-10-28): the case is split into sub-questions by ``decompose``; each
sub-question runs its own planner chain through the router, and the answer only
counts as complete when every sub-question has evidence-backed content.  Rows
whose metric is not the asked metric family are dropped before assembly
(``METRIC_SYNONYMS``); the strict grader reuses the same table.

v2 (2026-10-29, speed): one question's hops are independent of each other (they
read the routed slots, not the previous hop's rows) and independent sub-questions
are independent too, so the whole question's hops go to one fixed thread pool and
their results are collected back in chain order -- the answer text and hop order
stay byte-for-byte deterministic.  A per-question cache keyed on
``(planner, entity, period, ask)`` shares the repeated identity/price/filing work
between sub-questions.

The wording contract is QUERY_LAYER.md §4: a NID answer must say what was
checked (with post-PIT row counts), what the nearest held document is, why the
fact is missing, and which table/fetch would close it.  A partial answer never
becomes a NID: the answered part is kept and the missing hop is named.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .ctx import Ctx
from .decompose import decompose, sub_case
from .gate import (METRIC_SYNONYMS, asked_concepts, evidence_matches, gate_hop,
                   gate_run, key_terms, metric_matches)
from .planners import load_planners
from .router import period_bounds, route

#: One fixed pool for the whole process: a hop is DB-bound (SQLite releases the
#: GIL around execute/fetch), and persistent threads keep each thread's warm
#: read-only connections alive instead of reconnecting per call.
HOP_WORKERS = 4
_POOL = ThreadPoolExecutor(max_workers=HOP_WORKERS, thread_name_prefix="qhop")

__all__ = ["answer", "filter_hop", "hop_results", "metric_matches", "evidence_matches",
           "row_matches", "METRIC_SYNONYMS", "pit_audit", "assemble"]


def row_matches(metric: str | None, row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return True
    if metric == "promoter":
        unit = str(row.get("unit") or "").lower()
        item = str(row.get("item") or "").lower()
        if unit in ("number", "shares") and "%" not in item:
            return False  # a share count, not a holding percentage
    text = " ".join(str(row.get(key) or "") for key in
                    ("item", "metric", "quote", "text", "context", "period"))
    return metric_matches(metric, text)


def _filter_evidence_rows(metric: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A page-level row has no quote to judge; keep it (the page itself matched).
    return [row for row in rows
            if not row.get("quote") or evidence_matches(metric, row.get("quote"))]


def filter_hop(hop: dict[str, Any], sub: dict[str, Any]) -> dict[str, Any]:
    """Drop rows whose metric is not the sub-question's metric family."""
    metric = sub.get("metric")
    if not metric or hop.get("na") or not hop.get("rows") or \
            hop["hop"] not in ("FACTS", "EVIDENCE"):
        return hop
    rows = hop["rows"]
    kept = ([row for row in rows if row_matches(metric, row)]
            if hop["hop"] == "FACTS" else _filter_evidence_rows(metric, rows))
    if not kept:
        return dict(hop, ok=False, empty=True, rows=[], provenance=[], evidence=[],
                    why="no_doc",
                    detail=(f"{len(rows)} {hop['hop'].lower()} row(s) retrieved but none matches "
                            f"the asked metric ({metric})"),
                    nid_reason=f"none of the retrieved rows carries the asked metric ({metric})")
    if len(kept) == len(rows):
        return hop
    if hop["hop"] == "FACTS":
        detail = "; ".join(
            f"{row.get('item')} {row.get('period') or ''} = {row.get('value')} "
            f"{row.get('unit') or ''} ({row.get('store')}, known {str(row.get('known_at'))[:10]})"
            for row in kept[:3])
    else:
        detail = " | ".join(
            f"{row.get('doc_type')} {row.get('date')} p{row.get('page')}: "
            f"{(row.get('quote') or '')[:180]}" for row in kept[:2])
    return dict(hop, rows=kept, detail=detail,
                evidence=[f"{str(row.get('known_at'))[:10]}:{hop['hop']}:{row.get('ref') or ''}"
                          for row in kept[:8]])


def _gates(case: dict, plan: dict[str, Any], hops: list[dict[str, Any]]) -> tuple[str, str]:
    resolve = next((h for h in hops if h["hop"] == "resolve"), None)
    if resolve and not resolve["ok"] and not resolve["na"]:
        return "G1", resolve.get("nid_reason") or "the entity did not exist at as_of"
    status = str(plan.get("status") or "")
    if status.startswith("NOT_IN_DATA"):
        return "G3", "no source publishes this fact (paid-only, unpublished or out of scope)"
    question = str(case.get("question") or "").lower()
    if any(word in question for word in ("will ", "forecast", "expect to", "should i")):
        return "G4", "the ask is a forecast or an opinion with no held store"
    return "G2", "every hop returned 0 rows after its PIT filter"


def _nid_text(case: dict, plan: dict[str, Any], hops: list[dict[str, Any]]) -> str:
    gate, why = _gates(case, plan, hops)
    checked = ", ".join(f"{h['hop']} ({len(h.get('rows') or [])} rows, {len(h.get('checked') or [])} "
                        f"store(s))" for h in hops if not h["na"])
    nearest = ""
    for hop in hops:
        if hop["hop"] == "resolve" or hop["na"] or hop["ok"]:
            continue
        if hop.get("detail"):
            nearest = hop["detail"]
            break
    if not nearest:
        for hop in hops:
            if hop["hop"] != "resolve" and hop.get("detail"):
                nearest = hop["detail"]
                break
    status = str(plan.get("status") or "")
    if ":" in status and status.split(":", 1)[0].startswith("needs_new"):
        to_close = status.split(":", 1)[1]
    elif status == "answerable_now":
        to_close = "a re-run with the missing store field"
    else:
        to_close = status or "unknown"
    lines = [f"NOT IN DATA: {case.get('question')}",
             f"Checked: {checked or 'no hop ran'}, as_of {plan['as_of']}."]
    if nearest:
        lines.append(f"Nearest held: {nearest}.")
    lines.append(f"Why: [{gate}] {why}.")
    lines.append(f"To close: {to_close}.")
    return "\n".join(lines)


def pit_audit(hops: list[dict[str, Any]], as_of: str) -> list[str]:
    """Any evidence/provenance row first known after as_of is a PIT violation."""
    out: list[str] = []
    for hop in hops:
        for item in hop.get("provenance") or hop.get("evidence") or []:
            known = item.get("known_at") if isinstance(item, dict) else str(item)
            day = str(known or "")[:10]
            if len(day) == 10 and day[:4].isdigit() and day > as_of:
                out.append(f"{hop['hop']}: {day} > as_of {as_of}")
    return out


def assemble(case: dict, plan: dict[str, Any], hops: list[dict[str, Any]]) -> tuple[str, bool]:
    """Single-chain assembly (kept for callers of the v0 entry point)."""
    ok_parts = [h["detail"] for h in hops
                if h["ok"] and not h["na"] and h.get("detail")]
    bad = [h for h in hops if not h["ok"] and not h["na"]]
    if ok_parts:
        text = "; ".join(ok_parts)
        if bad:
            text += " | MISSING: " + "; ".join(f"{h['hop']}: {h.get('detail')}" for h in bad)
        return text[:4000], False
    return _nid_text(case, plan, hops)[:4000], True


def _cache_key(plan: dict[str, Any], name: str) -> tuple:
    """One hop's identity: planner + entity + period + the ask the planner reads.

    RESOLVE depends on the identity and as_of only, so the sub-questions of one
    question share it (the ask's words and metric are not inputs).  Every other
    planner also reads the ask, so its key keeps the metric/doc/page/terms.
    """
    slots = plan["slots"]
    if name == "resolve":
        return (name, slots.get("isin"), slots.get("symbol"),
                tuple(slots.get("symbols") or ()), plan["as_of"])
    return (name, slots.get("isin") or slots.get("symbol") or "",
            plan["as_of"], slots.get("date_from"), slots.get("date_to"),
            slots.get("metric"), slots.get("doc_type"), slots.get("page"),
            tuple(slots.get("terms") or ()))


def _run_hop(plan: dict[str, Any], name: str, ctx: Ctx) -> dict[str, Any]:
    key = _cache_key(plan, name)
    cached = ctx.cache_get(key)
    if cached is not None:
        cached["seconds"] = 0.0
        cached["cached"] = True
        return cached
    planners = load_planners()
    started = time.perf_counter()
    try:
        hop = planners[name](plan["slots"], plan["as_of"], ctx)
    except Exception as exc:  # noqa: BLE001 - a planner bug is a graded hop
        hop = {"hop": name, "ok": False, "na": False, "rows": [], "provenance": [],
               "evidence": [], "checked": [], "degraded": [], "pit": None,
               "detail": f"planner error: {type(exc).__name__}: {exc}",
               "why": "tool", "gap": None, "empty": True, "nid_reason": None}
    hop["seconds"] = round(time.perf_counter() - started, 4)
    ctx.cache_put(key, hop)
    return hop


def _run_batch(chains: list[tuple[int, dict[str, Any]]], ctx: Ctx) -> dict[int, list[dict[str, Any]]]:
    """Run every hop of every chain concurrently, returning hops in chain order.

    The jobs are submitted in ``(sub index, chain position)`` order and read
    back in the same order, so assembly never depends on completion order.
    """
    jobs: list[tuple[int, dict[str, Any], str]] = []
    for index, plan in chains:
        for name in plan["chain"]:
            jobs.append((index, plan, name))
    if len(jobs) <= 1:
        done = {(index, name): _run_hop(plan, name, ctx) for index, plan, name in jobs}
    else:
        futures = [(_POOL.submit(_run_hop, plan, name, ctx), (index, name))
                   for index, plan, name in jobs]
        done = {key: future.result() for future, key in futures}
    out: dict[int, list[dict[str, Any]]] = {}
    for index, plan in chains:
        out[index] = [done[(index, name)] for name in plan["chain"]]
    return out


def _prepare_sub(case: dict, sub: dict[str, Any], picked: dict[str, Any] | None,
                 parent_from: str | None, parent_to: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    variant = sub_case(case, sub, picked)
    plan = route(variant)
    slots = plan["slots"]
    if (parent_from and parent_to and not sub.get("named_document")
            and slots.get("needs", {}).get("price")
            and slots.get("period_basis") in ("as_of", "none")):
        # Later sub-questions inherit the parent's window ("last year" lives on
        # the parent question, not on "did the stock absorb it?").
        slots["date_from"], slots["date_to"] = parent_from, parent_to
        slots["period_basis"] = "inherited window"
    return plan, variant


def _run_record(index: int, sub: dict[str, Any], plan: dict[str, Any],
                variant: dict[str, Any], hops: list[dict[str, Any]]) -> dict[str, Any]:
    slots = plan["slots"]
    concepts = asked_concepts(f"{sub.get('text') or ''} {slots.get('question') or ''}")
    terms = [] if concepts else key_terms(str(sub.get("text") or ""))
    named = sub.get("named_document")
    hops = [gate_hop(hop, slots, concepts, terms, named) for hop in hops]
    gate = gate_run(hops, sub, concepts, terms)
    body = [hop for hop in hops if hop["hop"] != "resolve"]
    answered = [hop for hop in body if hop["ok"] and not hop["na"]]
    identity_only = bool(body) and all(hop["na"] for hop in body) and any(
        hop["ok"] for hop in hops if hop["hop"] == "resolve")
    bad = [hop for hop in body if not hop["ok"] and not hop["na"]]
    detail = "; ".join(hop["detail"] for hop in (answered or
                                                 [h for h in hops if h["hop"] == "resolve"])
                       if hop.get("detail"))
    if (answered or identity_only) and bad:
        detail += " | MISSING: " + "; ".join(
            f"{hop['hop']}: {hop.get('detail')}" for hop in bad)
    if gate:
        detail += (" | MISSING: " if detail else " | ") + gate
    return {"index": index, "text": sub["text"],
            "chain": plan["chain"], "hops": hops,
            "answered": bool(answered or identity_only) and not gate, "detail": detail,
            "gate": gate, "ask_concepts": concepts,
            "slots": {k: slots.get(k) for k in (
                "isin", "symbol", "symbols", "period", "period_basis",
                "date_from", "date_to")},
            "metric": sub.get("metric"), "steps": sub.get("steps") or [],
            "entities": list(variant.get("entities") or [])}


def _pick(hops: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The leading row of a ranking hop: the entity the next sub-question is about."""
    for hop in hops:
        if hop["hop"] in ("SCREEN", "COMPARE") and hop["ok"] and hop["rows"]:
            for row in hop["rows"]:
                if isinstance(row, dict) and row.get("symbol"):
                    return {"symbol": row["symbol"], "value": row.get("value")}
    return None


def answer(case: dict, ctx: Ctx | None = None, close: bool = True) -> dict[str, Any]:
    """Run each sub-question's routed chain for one master-bank case."""
    own = ctx is None
    ctx = ctx or Ctx()
    ctx.cache_clear()
    subs = decompose(case)
    parent_from, parent_to, _ = period_bounds(case)
    first_plan: dict[str, Any] | None = None
    try:
        runs: list[dict[str, Any]] = []
        if all(sub.get("entity_from") is None for sub in subs):
            # No sub-question needs a previous sub-question's ranking row: run
            # every sub-question's whole chain in one batch.
            prepared = []
            for sub in subs:
                plan, variant = _prepare_sub(case, sub, None, parent_from, parent_to)
                first_plan = first_plan or plan
                prepared.append((sub, plan, variant))
            hops_by = _run_batch([(sub["index"], plan) for sub, plan, _ in prepared], ctx)
            for sub, plan, variant in prepared:
                hops = [filter_hop(hop, sub) for hop in hops_by[sub["index"]]]
                runs.append(_run_record(sub["index"], sub, plan, variant, hops))
        else:
            picks: dict[int, dict[str, Any]] = {}
            for sub in subs:
                picked = picks.get(sub["entity_from"]) if sub.get("entity_from") is not None else None
                plan, variant = _prepare_sub(case, sub, picked, parent_from, parent_to)
                if first_plan is None:
                    first_plan = plan
                hops = [filter_hop(hop, sub) for hop in
                        _run_batch([(sub["index"], plan)], ctx)[sub["index"]]]
                runs.append(_run_record(sub["index"], sub, plan, variant, hops))
                pick = _pick(hops) if (sub.get("universe") or sub.get("entity_from") is not None) else None
                if pick:
                    picks[sub["index"]] = pick
        first_plan = first_plan or route(case)
        flat = [hop for run in runs for hop in run["hops"]]
        complete = bool(runs) and all(run["answered"] for run in runs)
        if any(run["answered"] for run in runs):
            parts = []
            multi = len(runs) > 1
            for run in runs:
                label = f"Q{run['index'] + 1}: " if multi else ""
                if run["answered"]:
                    parts.append(label + run["detail"])
                else:
                    missing = "; ".join(
                        f"{hop['hop']}: {hop.get('detail')}"
                        for hop in run["hops"] if not hop["ok"] and not hop["na"])
                    parts.append(f"{label}MISSING: " + (missing or str(run.get("gate") or
                                                                     "no evidence")))
            text, nid = " | ".join(parts)[:4000], False
        else:
            text, nid = _nid_text(case, first_plan, flat)[:4000], True
        return {"mid": case.get("mid"), "plan": first_plan, "hops": flat, "subs": runs,
                "answer": text, "nid": nid, "complete": complete,
                "pit_violations": pit_audit(flat, first_plan["as_of"]),
                "seconds": round(sum(hop["seconds"] for hop in flat), 3)}
    finally:
        if own and close:
            ctx.close()


def hop_results(hops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The bench's hop-result shape, so grading rules stay identical."""
    out = []
    for hop in hops:
        out.append({"hop": hop["hop"], "ok": hop["ok"], "na": hop["na"],
                    "detail": hop.get("detail"), "evidence": hop.get("evidence") or [],
                    "why": hop.get("why"), "gap": hop.get("gap"),
                    "seconds": hop.get("seconds", 0.0)})
    return out
