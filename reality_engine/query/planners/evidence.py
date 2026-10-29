"""EVIDENCE: passages from the company's own documents, PIT-filtered in SQL.

Delegates to the ``reality-data`` document tools (``doc_find``, ``doc_page``),
which the task also gains an ``as_of`` argument on.  ``doc_find`` requires every
term, so the planner retries once with fewer terms before it reports empty.

When ``REALITY_CHUNKS_V3`` names a chunks_v3 database (the pilot store), its
FTS5 index is tried first with every filter pushed into SQL (isin, doc_type,
known_at, section/speaker/tag); ``doc_find`` is the fallback.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .. import rerank
from ..router import LIST_ASK
from . import envelope
from .facts import DOC_WINDOW_DAYS, TEXT_TERMS, named_of

CHECKED = ["equity_intelligence.document_chunks", "ar_facts.ar_facts",
           "deck_figures.deck_sources", "bse_announcements.ann",
           "equity_intelligence.corporate_documents"]
CHECKED_V3 = ["chunks_v3.chunk + chunk_fts", "chunks_v3.chunk_tag", "chunks_v3.doc"]

_STOP = {
    "the", "and", "for", "was", "were", "are", "what", "which", "how", "why", "who",
    "did", "does", "from", "that", "this", "with", "has", "have", "had", "its", "their",
    "company", "quarter", "year", "said", "say", "tell",
}
_FTS_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")


def _chunks_db() -> Path | None:
    value = os.environ.get("REALITY_CHUNKS_V3")
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path if path.is_file() else None


def _fts_query(terms: list[str]) -> str:
    """OR of quoted content words, with a de-pluralised form of each."""
    words: list[str] = []
    for term in terms:
        for word in _FTS_WORD.findall(str(term).lower()):
            if word in _STOP:
                continue
            words.append(word)
            if len(word) > 4 and word.endswith("s"):
                words.append(word[:-1])
    unique = list(dict.fromkeys(words))[:16]
    return " OR ".join(f'"{word}"' for word in unique)


def _chunks_v3_search(db: Path, slots: dict[str, Any], as_of: str,
                      doc_type: str | None, limit: int = 5) -> list[dict[str, Any]]:
    """FTS first, then filter push-down on the already-matched row set.

    The FTS match is materialised first (26 ms measured) and the filters then
    run against ``chunk``: the opposite plan (filter ``chunk`` then scan the
    virtual table per row) took ~1 s on the same 37k-chunk store.
    """
    match = _fts_query([str(t) for t in (slots.get("terms") or [])])
    if not match:
        return []
    where = ["c.known_at <= ?"]
    params: list[Any] = [as_of]
    isin = slots.get("isin")
    if isin:
        where.append("c.isin = ?")
        params.append(isin)
    if doc_type:
        where.append("c.doc_type = ?")
        params.append(doc_type)
    section = slots.get("section")
    if section:
        where.append("c.section LIKE ?")
        params.append(f"%{section}%")
    speaker = slots.get("speaker")
    if speaker:
        where.append("c.speaker LIKE ?")
        params.append(f"%{speaker}%")
    tags = slots.get("tags") or slots.get("tag")
    if isinstance(tags, str):
        tags = [tags]
    ctes = [("hits AS MATERIALIZED (SELECT rowid AS chunk_id, "
             "bm25(chunk_fts, 0.2, 1.0) AS score FROM chunk_fts "
             "WHERE chunk_fts MATCH ?)")]
    tag_sql = ""
    if tags:
        # Materialised tag set: a plain join on chunk_tag picked the wrong plan
        # and cost ~1 s; the PK range scan costs ~100 ms.
        if len(tags) == 1:
            ctes.append("tagged AS MATERIALIZED (SELECT chunk_id FROM chunk_tag WHERE tag = ?)")
        else:
            ctes.append("tagged AS MATERIALIZED (SELECT chunk_id FROM chunk_tag "
                        f"WHERE tag IN ({','.join('?' * len(tags))}) GROUP BY chunk_id "
                        "HAVING COUNT(*) = ?)")
            tags = list(tags) + [len(tags)]
        tag_sql = " JOIN tagged ON tagged.chunk_id = hits.chunk_id"
    sql = (f"WITH {', '.join(ctes)} "
           f"SELECT c.doc_id, c.doc_type, c.known_at, c.page_from, c.section, c.speaker, "
           f"c.speaker_role, c.body, c.header FROM hits{tag_sql} "
           f"JOIN chunk c ON c.chunk_id = hits.chunk_id "
           f"WHERE {' AND '.join(where)} ORDER BY hits.score LIMIT ?")
    args = [match] + list(tags or []) + params + [limit]
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(db, timeout_s=10)
    try:
        rows = con.execute(sql, args).fetchall()
    finally:
        con.close()
    return [{"store": "chunks_v3", "doc_id": row[0], "doc_type": row[1],
             "date": row[2], "page": row[3], "section": row[4], "speaker": row[5],
             "speaker_role": row[6], "quote": row[7] or "", "header": row[8] or ""}
            for row in rows]


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
                passages = rerank.rank(passages, terms=terms,
                                       metric_terms=TEXT_TERMS.get(
                                           str(slots.get("metric") or ""), ()),
                                       as_of=as_of)
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
    named = named_of(slots)
    date = named["date"] if named else None
    if date is None and slots.get("period_basis") in ("named date", "named dates"):
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

        terms = [t for t in (slots.get("terms") or []) if len(t) > 3] or slots.get("terms") or []
        symbol_words = {str(symbol).lower(), str(slots.get("symbol") or "").lower()}
        meaningful = [t for t in terms if t.lower() not in symbol_words] or terms
        db = _chunks_db()
        if db is not None and meaningful and _fts_query([str(t) for t in meaningful]):
            try:
                candidates = _chunks_v3_search(db, slots, as_of, doc_type)
            except Exception:  # noqa: BLE001 - a broken pilot DB must not break the answer
                candidates = None  # the legacy doc_find path is the fallback
            # Extraction rows (rating actions, price revisions, contracts, cost inputs,
            # supply links) are passages too: quote + page + known_at, PIT-filtered.
            try:
                from reality_engine.query import metrics
                candidates = (metrics.evidence_rows(ctx, str(slots.get("isin") or ""), as_of,
                                                    str(slots.get("question") or ""))
                              + (candidates or []))
            except Exception:  # noqa: BLE001
                pass
            if candidates is not None:
                # The chunks_v3 store is the authoritative text index for a pilot
                # ISIN.  Ranked FTS is the relevance signal here: half the ask's
                # terms is a clean answer, one term is a degraded answer, and a
                # miss does not fall back to the slow legacy doc_find (6 s per
                # miss on the full stores) because the pilot store already
                # covers the same four doc types.
                need = max(1, (len(meaningful) + 1) // 2)
                clean, partial = [], []
                for passage in candidates:
                    quote = str(passage.get("quote") or "").lower()
                    hits = sum(1 for term in meaningful if term.lower() in quote)
                    if hits >= need:
                        clean.append((hits, passage))
                    elif hits:
                        partial.append((hits, passage))
                clean.sort(key=lambda item: -item[0])
                partial.sort(key=lambda item: -item[0])
                if clean or partial:
                    chosen = [passage for _, passage in (clean or partial)[:3]]
                    detail = " | ".join(
                        f"{p.get('doc_type')} {p.get('date')} p{p.get('page')} "
                        f"{(p.get('section') or '')[:40]}: {(p.get('quote') or '')[:180]}"
                        for p in chosen[:2])
                    return envelope(
                        "EVIDENCE", ok=True,
                        rows=[{"ref": f"chunks_v3:{p.get('doc_id')}#{p.get('page')}",
                               "known_at": p.get("date")} for p in chosen],
                        provenance=[{"ref": f"chunks_v3:{p.get('doc_id')}#{p.get('page')}",
                                     "known_at": p.get("date")} for p in chosen],
                        pit=f"chunk known_at <= {as_of} pushed into the FTS + filter SQL",
                        checked=CHECKED_V3,
                        degraded=([] if clean else ["chunks_v3: top passages match only part of the ask"]),
                        detail=detail)
                return envelope(
                    "EVIDENCE", ok=False, why="no_doc", checked=CHECKED_V3,
                    detail=f"no chunk of {symbol} carries {', '.join(meaningful[:3])} "
                           f"known by {as_of}", nid_reason="no passage in chunks_v3")
        tool = ctx.tool("doc_find")
        attempts = []
        if terms:
            attempts.append(" ".join(terms[:3]))
            attempts.append(" ".join(meaningful[:2]))
            # doc_find is AND over its terms; one strong word often retrieves the
            # page the phrase query misses ("products" alone on a products deck).
            attempts.append(" ".join(meaningful[:1]))
            doc_words = {"presentation", "transcript", "investor", "report", "annual",
                         "results", "announcement", "latest", "dated", "mention"}
            specific = [t for t in meaningful if t.lower() not in doc_words]
            if specific:
                attempts.append(max(specific, key=len))
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
            # A text ask with no numeric metric has no metric family to fall back
            # on: the query itself was the relevance test, so one hit is enough.
            need = 1 if not slots.get("metric") else max(1, (len(meaningful) + 1) // 2)
            metric_words = [word.lower() for word in
                            TEXT_TERMS.get(str(slots.get("metric") or ""), ())]
            scored = []
            for passage in passages:
                quote = str(passage.get("quote") or passage.get("text") or "").lower()
                hits = sum(1 for term in meaningful if term.lower() in quote)
                metric_hit = any(word in quote for word in metric_words)
                if hits >= need or metric_hit:
                    scored.append((hits + (1 if metric_hit else 0), passage))
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
        # Named-document preference: when the question names a document, its
        # passages only.  The nearest held document is not a substitute.
        if named and passages:
            from datetime import date as _date
            anchor = _date.fromisoformat(str(named["date"])[:10])
            inside = []
            for passage in passages:
                try:
                    day = _date.fromisoformat(str(passage.get("date") or "")[:10])
                except ValueError:
                    continue
                if abs((day - anchor).days) <= DOC_WINDOW_DAYS:
                    inside.append(passage)
            if not inside:
                wanted = (f"the {named['doc_type']} of {named['date']} carries no passage for "
                          f"{', '.join(meaningful[:3]) or 'the ask'}; a different document is "
                          f"not the one asked for")
                return envelope("EVIDENCE", ok=False, why="no_doc",
                                checked=res.get("checked") or CHECKED, detail=wanted,
                                nid_reason=wanted)
            passages = inside
        metric_terms = TEXT_TERMS.get(str(slots.get("metric") or ""), ())
        passages = rerank.rank(
            passages, terms=meaningful or terms, metric_terms=metric_terms,
            entity=str(slots.get("symbol") or slots.get("isin") or ""),
            named_date=(named or {}).get("date") or date, as_of=as_of)
        top = passages[:3]
        detail = " | ".join(
            f"{p.get('doc_type')} {p.get('date')} p{p.get('page')}: "
            f"{(p.get('quote') or '')[:180]}" for p in top[:2])
        return envelope(
            "EVIDENCE", ok=True,
            rows=[{"ref": f"{p.get('store')}:{p.get('doc_id')}#{p.get('page')}",
                   "known_at": p.get("date"), "date": p.get("date"),
                   "doc_type": p.get("doc_type"), "page": p.get("page"),
                   "quote": (p.get("quote") or "")[:300], "score": p.get("score")}
                  for p in top],
            provenance=[{"ref": f"{p.get('store')}:{p.get('doc_id')}",
                         "known_at": p.get("date")} for p in top],
            pit=f"chunk published_date / document known_at <= {as_of} in the SQL",
            checked=res.get("checked") or CHECKED,
            degraded=(res.get("warnings") or []) + (
                [f"named-document preference: {named['doc_type']} of {named['date']} "
                 f"(±{DOC_WINDOW_DAYS}d)"] if named else []),
            detail=detail)
    except Exception as exc:  # noqa: BLE001 - a tool failure is data, not a crash
        return envelope("EVIDENCE", ok=False, why="tool", checked=CHECKED,
                        detail=f"document tool failed: {type(exc).__name__}: {exc}")
