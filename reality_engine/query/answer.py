"""Assemble the hops into one structured answer, or the NOT-IN-DATA wording.

The wording contract is QUERY_LAYER.md §4: a NID answer must say what was
checked (with post-PIT row counts), what the nearest held document is, why the
fact is missing, and which table/fetch would close it.  A partial answer never
becomes a NID: the answered part is kept and the missing hop is named.
"""
from __future__ import annotations

import time
from typing import Any

from .ctx import Ctx
from .planners import load_planners
from .router import route


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
    ok_parts = [h["detail"] for h in hops
                if h["ok"] and not h["na"] and h.get("detail")]
    bad = [h for h in hops if not h["ok"] and not h["na"]]
    if ok_parts:
        text = "; ".join(ok_parts)
        if bad:
            text += " | MISSING: " + "; ".join(f"{h['hop']}: {h.get('detail')}" for h in bad)
        return text[:4000], False
    return _nid_text(case, plan, hops)[:4000], True


def answer(case: dict, ctx: Ctx | None = None, close: bool = True) -> dict[str, Any]:
    """Run the routed chain for one master-bank case."""
    own = ctx is None
    ctx = ctx or Ctx()
    plan = route(case)
    planners = load_planners()
    hops: list[dict[str, Any]] = []
    try:
        for name in plan["chain"]:
            started = time.perf_counter()
            try:
                hop = planners[name](plan["slots"], plan["as_of"], ctx)
            except Exception as exc:  # noqa: BLE001 - a planner bug is a graded hop
                hop = {"hop": name, "ok": False, "na": False, "rows": [], "provenance": [],
                       "evidence": [], "checked": [], "degraded": [], "pit": None,
                       "detail": f"planner error: {type(exc).__name__}: {exc}",
                       "why": "tool", "gap": None, "empty": True, "nid_reason": None}
            hop["seconds"] = round(time.perf_counter() - started, 4)
            hops.append(hop)
        text, nid = assemble(case, plan, hops)
        violations = pit_audit(hops, plan["as_of"])
        return {"mid": case.get("mid"), "plan": plan, "hops": hops, "answer": text,
                "nid": nid, "pit_violations": violations,
                "seconds": round(sum(h["seconds"] for h in hops), 3)}
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
