"""EVIDENCE: passages from the company's own documents, PIT-filtered in SQL.

Delegates to the ``reality-data`` document tools (``doc_find``, ``doc_page``),
which the task also gains an ``as_of`` argument on.  ``doc_find`` requires every
term, so the planner retries once with fewer terms before it reports empty.
"""
from __future__ import annotations

from typing import Any

from ..router import LIST_ASK
from . import envelope

CHECKED = ["equity_intelligence.document_chunks", "ar_facts.ar_facts",
           "deck_figures.deck_sources", "bse_announcements.ann",
           "equity_intelligence.corporate_documents"]


def _missing(res: dict[str, Any]) -> str:
    for key in ("reason", "detail", "why", "message", "hint"):
        if res.get(key):
            return str(res[key])
    nearest = res.get("nearest")
    if isinstance(nearest, list) and nearest:
        first = nearest[0]
        if isinstance(first, dict):
            return (f"nearest held: {first.get('doc_type')} {first.get('date')} "
                    f"{(first.get('title') or '')[:80]}")
    return "no passage carries the ask"


def plan(slots: dict[str, Any], as_of: str, ctx: Any) -> dict[str, Any]:
    needs = slots.get("needs", {})
    if not needs.get("text") and not needs.get("page"):
        return envelope("EVIDENCE", ok=True, na=True, checked=CHECKED,
                        detail="no passage asked; EVIDENCE not applicable")
    symbol = slots.get("symbol") or slots.get("isin")
    question = str(slots.get("question") or "")
    list_ask = bool(LIST_ASK.search(question))
    if list_ask:
        symbol = None  # a proxy company's documents cannot answer a corpus list
    status = str(slots.get("status") or "")
    gate = (status.split(":", 1)[-1] if status.startswith("needs_new_table:") else None)
    if not symbol:
        terms = [t for t in (slots.get("terms") or []) if len(t) > 3]
        if terms:
            try:
                tool = ctx.tool("search_docs")
                raw = tool(" ".join(terms[:2]), date_to=slots.get("date_to") or as_of,
                           as_of=as_of, top_k=3)
            except Exception as exc:  # noqa: BLE001
                return envelope("EVIDENCE", ok=False, why="tool", checked=CHECKED,
                                detail=f"corpus search failed: {type(exc).__name__}: {exc}")
            results = raw.get("results") if isinstance(raw, dict) else raw
            passages = [p for p in (results or [])
                        if (p.get("date") or "")[:10] and (p.get("date") or "")[:10] <= as_of]
            if passages:
                top = passages[:3]
                if list_ask:
                    detail = (f"found {len(top)} example passage(s); a complete company list "
                              "needs a corpus-wide aggregation (chunks_v3 / announcement index)")
                    return envelope("EVIDENCE", ok=False, why="schema", checked=CHECKED,
                                    gap="chunks_v3", detail=detail, nid_reason=detail)
                detail = " | ".join(
                    f"{p.get('doc_type')} {p.get('date')}: {(p.get('text') or '')[:180]}"
                    for p in top[:2])
                return envelope(
                    "EVIDENCE", ok=True,
                    rows=[{"ref": f"{p.get('doc_type')}:{p.get('doc_id')}",
                           "known_at": p.get("date")} for p in top],
                    provenance=[{"ref": f"search_docs:{p.get('doc_id')}",
                                 "known_at": p.get("date")} for p in top],
                    pit=f"corpus rows dated <= {as_of} in the SQL", checked=CHECKED,
                    detail=detail)
        detail = (f"corpus search found no passage for {', '.join(terms[:3]) or 'the ask'} "
                  f"known by {as_of}")
        if list_ask:
            return envelope("EVIDENCE", ok=False, why="schema", checked=CHECKED, gap="chunks_v3",
                            detail=f"{detail}; a complete company list needs chunks_v3",
                            nid_reason="BLOCKED_SCHEMA: chunks_v3")
        if gate:
            return envelope("EVIDENCE", ok=False, why="schema", checked=CHECKED, gap=gate,
                            detail=f"{detail}; precise retrieval needs {gate}",
                            nid_reason=f"BLOCKED_SCHEMA: {gate}")
        return envelope("EVIDENCE", ok=False, why="no_doc", checked=CHECKED, detail=detail,
                        nid_reason=detail)
    doc_type = slots.get("doc_type")
    date = None
    if slots.get("period_basis") in ("named date", "named dates"):
        date = slots.get("date_from")
    try:
        if needs.get("page"):
            tool = ctx.tool("doc_page")
            res = tool(symbol, date or as_of, int(needs["page"]), doc_type=doc_type,
                       as_of=as_of)
            if res.get("found") and res.get("text"):
                doc = res.get("document") or {}
                detail = (f"{doc.get('doc_type')} {doc.get('date')} page {res.get('page')}"
                          f"/{res.get('page_count')}: {(res.get('text') or '')[:300]}")
                return envelope(
                    "EVIDENCE", ok=True,
                    rows=[{"ref": f"page:{doc.get('doc_id')}#{res.get('page')}",
                           "known_at": doc.get("date") or as_of}],
                    provenance=[{"ref": f"doc_page:{doc.get('doc_id')}",
                                 "known_at": doc.get("date") or as_of}],
                    pit=f"document known_at <= {as_of}", checked=res.get("checked") or CHECKED,
                    degraded=res.get("warnings") or [], detail=detail)
            detail = _missing(res)
            return envelope("EVIDENCE", ok=False, why="no_doc", checked=res.get("checked") or CHECKED,
                            detail=detail, nid_reason=detail)

        tool = ctx.tool("doc_find")
        terms = [t for t in (slots.get("terms") or []) if len(t) > 3] or slots.get("terms") or []
        symbol_words = {str(symbol).lower(), str(slots.get("symbol") or "").lower()}
        meaningful = [t for t in terms if t.lower() not in symbol_words] or terms
        attempts = []
        if terms:
            attempts.append(" ".join(terms[:3]))
            attempts.append(" ".join(meaningful[:2]))
        res: dict[str, Any] = {}
        found_any = False
        for query in dict.fromkeys(attempts):
            res = tool(symbol, query, doc_type=doc_type, date=date, as_of=as_of)
            if res.get("found") and res.get("passages"):
                found_any = True
                break
        passages = [p for p in (res.get("passages") or [])
                    if (p.get("date") or "")[:10] and (p.get("date") or "")[:10] <= as_of]
        # A passage only answers the hop when its own quote carries the ask's
        # meaningful terms (not just the company name).  At least half must hit.
        if meaningful and passages:
            need = max(1, (len(meaningful) + 1) // 2)
            scored = []
            for passage in passages:
                quote = str(passage.get("quote") or "").lower()
                hits = sum(1 for term in meaningful if term.lower() in quote)
                if hits >= need:
                    scored.append((hits, passage))
            scored.sort(key=lambda item: -item[0])
            passages = [passage for _, passage in scored]
            if not passages:
                res = dict(res)
                res["reason"] = (f"documents are held but no passage carries "
                                 f"{', '.join(meaningful[:3])}")
                # Do not retry after a relevance rejection: the retry is for a
                # query that returned nothing at all (AND semantics).
                found_any = True
        if not passages and not found_any:
            detail = _missing(res)
            checked = res.get("checked") or CHECKED
            if gate:
                return envelope("EVIDENCE", ok=False, why="schema", checked=checked, gap=gate,
                                detail=f"{detail}; precise retrieval needs {gate}",
                                nid_reason=f"BLOCKED_SCHEMA: {gate}")
            return envelope("EVIDENCE", ok=False, why="no_doc", checked=checked,
                            detail=detail, nid_reason=detail)
        top = passages[:3]
        detail = " | ".join(
            f"{p.get('doc_type')} {p.get('date')} p{p.get('page')}: "
            f"{(p.get('quote') or '')[:180]}" for p in top[:2])
        return envelope(
            "EVIDENCE", ok=True,
            rows=[{"ref": f"{p.get('store')}:{p.get('doc_id')}#{p.get('page')}",
                   "known_at": p.get("date")} for p in top],
            provenance=[{"ref": f"{p.get('store')}:{p.get('doc_id')}",
                         "known_at": p.get("date")} for p in top],
            pit=f"chunk published_date / document known_at <= {as_of} in the SQL",
            checked=res.get("checked") or CHECKED,
            degraded=res.get("warnings") or [],
            detail=detail)
    except Exception as exc:  # noqa: BLE001 - a tool failure is data, not a crash
        return envelope("EVIDENCE", ok=False, why="tool", checked=CHECKED,
                        detail=f"document tool failed: {type(exc).__name__}: {exc}")
