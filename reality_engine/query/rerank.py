"""Cheap local reranker for EVIDENCE passages (no embeddings, no network).

Score = BM25(query terms) + entity overlap + metric overlap + date preference.
BM25 is computed over the candidate passages themselves (a handful of rows), so
it needs no corpus-wide index and stays deterministic.  The date feature prefers
passages from the named document (within ±3 days) and, when no document is
named, the latest passage as of the as_of.
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Iterable

K1, B = 1.5, 0.75
DATE_WINDOW_DAYS = 3


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9]{2,}", str(text or "").lower())


def bm25(query: Iterable[str], docs: list[list[str]]) -> list[float]:
    """BM25 over the candidate documents (IDF from this candidate set)."""
    terms = [t for t in dict.fromkeys(str(q).lower() for q in query) if t]
    if not terms or not docs:
        return [0.0] * len(docs)
    n = len(docs)
    avg = sum(len(doc) for doc in docs) / n if n else 0.0
    df = {term: sum(1 for doc in docs if term in doc) for term in terms}
    idf = {term: math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5)) for term in terms}
    out = []
    for doc in docs:
        score = 0.0
        length = len(doc) or 1
        for term in terms:
            freq = doc.count(term)
            if not freq:
                continue
            score += idf[term] * freq * (K1 + 1) / (
                freq + K1 * (1 - B + B * length / (avg or 1)))
        out.append(score)
    return out


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _name_hits(passage: dict[str, Any], entity: str) -> int:
    if not entity:
        return 0
    low = f"{passage.get('quote') or ''} {passage.get('text') or ''}".lower()
    keys = {str(entity).lower(), str(passage.get("symbol") or "").lower()}
    return sum(1 for key in keys if key and key in low)


def rank(passages: list[dict[str, Any]], terms: Iterable[str] = (),
         metric_terms: Iterable[str] = (), entity: str | None = None,
         named_date: str | None = None, as_of: str | None = None) -> list[dict[str, Any]]:
    """Order passages best-first; each row keeps its ``score`` and features."""
    passages = [dict(p) for p in passages if isinstance(p, dict)]
    if not passages:
        return []
    docs = [_tokens(f"{p.get('quote') or ''} {p.get('text') or ''} {p.get('title') or ''}")
            for p in passages]
    lexical = bm25([*terms, *metric_terms], docs)
    named = _day(named_date)
    days = [_day(p.get("date")) for p in passages]
    newest = max((d for d in days if d), default=None)
    metric_set = [str(t).lower() for t in metric_terms if str(t).strip()]
    scored = []
    for i, passage in enumerate(passages):
        low = str(passage.get("quote") or passage.get("text") or "").lower()
        metric_hits = sum(1 for term in metric_set if term in low)
        day = days[i]
        date_feature = 0.0
        if named and day:
            span = abs((day - named).days)
            date_feature = 1.0 if span <= DATE_WINDOW_DAYS else -0.5
        elif newest and day and not named:
            date_feature = 0.3 if day == newest else 0.0
        score = (float(lexical[i]) + 0.5 * _name_hits(passage, entity or "")
                 + 0.4 * metric_hits + 0.6 * date_feature)
        row = dict(passage)
        row["score"] = round(score, 4)
        row["features"] = {"bm25": round(float(lexical[i]), 4), "metric_hits": metric_hits,
                           "date": date_feature}
        scored.append(row)
    scored.sort(key=lambda row: (-row["score"], str(row.get("date") or ""), str(row.get("page") or "")))
    return scored
