"""Assemble the hops into one structured answer, or the NOT-IN-DATA wording.

v1 (2026-10-28): the case is split into sub-questions by ``decompose``; each
sub-question runs its own planner chain through the router, and the answer only
counts as complete when every sub-question has evidence-backed content.  Rows
whose metric is not the asked metric family are dropped before assembly
(``METRIC_SYNONYMS``); the strict grader reuses the same table.

The wording contract is QUERY_LAYER.md §4: a NID answer must say what was
checked (with post-PIT row counts), what the nearest held document is, why the
fact is missing, and which table/fetch would close it.  A partial answer never
becomes a NID: the answered part is kept and the missing hop is named.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .ctx import Ctx
from .decompose import decompose, sub_case
from .planners import load_planners
from .router import period_bounds, route

# canonical metric -> (include phrases, exclude phrases).  Phrases are matched
# as substrings of the normalised row text; the excludes stop the trap the v0
# bench hit ("Net Promoter Score" is not promoter holding, a "sales volume drop"
# is not revenue).
METRIC_SYNONYMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "revenue": (("revenue", "turnover", "sales", "income from operations", "topline"),
                ("sales volume", "volume drop", "growth in volume")),
    "pat": (("pat", "profit after tax", "net profit", "net income", "profit", "bottom line"),
            ("margin", "operating profit", "profit before tax")),
    "ebitda": (("ebitda", "operating profit"), ("margin",)),
    "margin": (("margin", "opm"), ()),
    "eps": (("eps", "earnings per share"), ()),
    "net_npa": (("npa", "non performing", "non-performing"), ("net worth",)),
    "promoter": (("promoter", "shareholding", "stake", "holding pattern", "pledge",
                  "promoter holding", "public holding", "holding %"),
                 ("net promoter", "nps", "promoter score", "total shareholding pattern",
                  "shares outstanding", "paid-up", "paid up", "share capital")),
    "facilities": (("facilit", "plant", "factory", "factories", "manufacturing unit"),
                   ("capacity", "capex", "installation")),
    "capacity": (("capacity", "capacities", "utilisation", "utilization", "mtpa", "tpa"),
                 ("capacity utilisation of the plant",)),
    "order_book": (("order book", "orderbook", "order intake", "orders"), ()),
    "dso": (("receivable", "debtor", "collection", "dso"), ()),
    "cfo": (("cash flow", "cfo", "operating cash"), ()),
    "segment": (("segment", "business mix", "vertical", "division"), ()),
    "return": (("return", "close", "rose", "fell", "gained", "dropped", "moved",
                "performance", "cagr", "excess"), ("dividend", "total return")),
    "cagr": (("cagr", "annualised", "annualized"), ()),
    "range": (("high", "low", "range", "support", "resistance", "52-week", "52 week", "ytd"), ()),
    "gap": (("gap",), ()),
    "rsi": (("rsi", "oversold", "overbought"), ()),
    "delivery": (("delivery", "delivered"), ()),
    "valuation": (("valuation", "pe", "p/e", "ev/ebitda", "ev/sales", "multiple", "premium",
                   "discount", "market cap"), ()),
    "guidance": (("guidance", "guided", "outlook", "expects", "target"), ()),
    "audit": (("audit", "auditor", "opinion", "qualified", "qualification"), ()),
}


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9%./ ]+", " ", str(text or "").lower())


def metric_matches(metric: str | None, text: Any) -> bool:
    """Does ``text`` belong to the asked metric family?  Unknown metric -> True.

    Look-alike phrases are stripped first, not used as a veto: a slide that says
    "Manufacturing Facilities ... Washing Capacity" is a facilities passage, a
    transcript that says "margins ... ebitda margins" is an EBITDA passage, and
    "Net Promoter Score (NPS)" stops being a promoter-holding row once "net
    promoter" and "nps" are removed.
    """
    if not metric or metric not in METRIC_SYNONYMS:
        return True
    include, exclude = METRIC_SYNONYMS[metric]
    low = _norm(text)
    for word in exclude:
        low = low.replace(word, " ")
    return any(word in low for word in include)


def evidence_matches(metric: str | None, text: Any) -> bool:
    """Same family test for EVIDENCE quotes (long text, same stripping rule)."""
    return metric_matches(metric, text)


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


def _run_chain(plan: dict[str, Any], ctx: Ctx) -> list[dict[str, Any]]:
    planners = load_planners()
    hops: list[dict[str, Any]] = []
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
    return hops


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
    subs = decompose(case)
    parent_from, parent_to, _ = period_bounds(case)
    picks: dict[int, dict[str, Any]] = {}
    runs: list[dict[str, Any]] = []
    first_plan: dict[str, Any] | None = None
    try:
        for sub in subs:
            picked = picks.get(sub["entity_from"]) if sub.get("entity_from") is not None else None
            variant = sub_case(case, sub, picked)
            plan = route(variant)
            if first_plan is None:
                first_plan = plan
            slots = plan["slots"]
            if (parent_from and parent_to and not sub.get("named_document")
                    and slots.get("needs", {}).get("price")
                    and slots.get("period_basis") in ("as_of", "none")):
                # Later sub-questions inherit the parent's window ("last year"
                # lives on the parent question, not on "did the stock absorb it?").
                slots["date_from"], slots["date_to"] = parent_from, parent_to
                slots["period_basis"] = "inherited window"
            hops = [filter_hop(hop, sub) for hop in _run_chain(plan, ctx)]
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
            runs.append({"index": sub["index"], "text": sub["text"],
                         "chain": plan["chain"], "hops": hops,
                         "answered": bool(answered or identity_only), "detail": detail,
                         "metric": sub.get("metric"), "steps": sub.get("steps") or [],
                         "entities": list(variant.get("entities") or [])})
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
                    parts.append(f"{label}MISSING: " + "; ".join(
                        f"{hop['hop']}: {hop.get('detail')}"
                        for hop in run["hops"] if not hop["ok"] and not hop["na"]))
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
