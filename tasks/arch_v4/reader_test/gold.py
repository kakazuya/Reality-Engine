"""Locate the bank's own gold quote inside the pilot corpus (no model involved).

This separates the two failure modes: was the right passage retrievable at all, and, if it
was put in front of the model, did the model read it?  The locator is deliberately simple:
FTS over the gold quote's content words inside the entity's chunks, then token-overlap
against the quote.  A bank row whose gold is not in the pilot corpus is a data gap, never a
reader failure.
"""
from __future__ import annotations

import re

from . import db

CONTENT = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")
STOP = {"the", "and", "a", "an", "of", "to", "in", "on", "for", "with", "by", "from",
        "that", "this", "is", "are", "was", "were", "has", "have", "had", "will", "we",
        "our", "it", "its", "as", "at", "be", "but", "or", "not", "so", "which", "which,",
        "there", "their", "they", "i", "you", "he", "she", "would", "could", "should",
        "about", "into", "than", "then", "also", "very", "more", "most", "such", "can",
        "may", "might", "must", "do", "does", "did", "been", "being", "up", "out", "if"}


def quote_of(ground_truth: str) -> str:
    s = (ground_truth or "").strip()
    if not s:
        return ""
    # the bank often writes "<label>: '<quote>' filed <timestamp>"
    m = re.search(r"[\u201c\"]([^\u201d\"]{12,})[\u201d\"]", s)
    if m:
        return m.group(1).strip()
    if ":" in s:
        tail = s.split(":", 1)[1].strip()
        m = re.search(r"[\u201c']([^\u201d']{12,})[\u201d']", tail)
        if m:
            return m.group(1).strip()
        return tail[:300]
    return s[:300]


def content_words(text: str) -> list[str]:
    return [t for t in CONTENT.findall((text or "").lower()) if t not in STOP and len(t) >= 2]


def _fts(gold: str, n: int = 10) -> str:
    words = [w for w in content_words(gold)]
    # rare-ish words first: longer words, then numbers
    words = sorted(dict.fromkeys(words), key=lambda w: (-len(w), w))[:n]
    return " OR ".join(f'"{w}"' for w in words)


def locate(con, isin: str, ground_truth: str, as_of: str) -> dict:
    gold = quote_of(ground_truth)
    target = content_words(gold)
    if len(target) < 3:
        return {"found": False, "reason": "gold has fewer than 3 content words", "quote": gold}
    fq = _fts(gold)
    if not fq:
        return {"found": False, "reason": "no gold terms", "quote": gold}
    rows = db.search(con, isin=isin, doc_types=["concall", "deck", "annual_report",
                                                "results_notes", "announcement"],
                     as_of=as_of, fts_query=fq, limit=80)
    best = None
    tset = set(target)
    for r in rows:
        got = set(content_words((r["body"] or "") + " " + (r["header"] or "")))
        if not tset:
            continue
        overlap = len(tset & got) / len(tset)
        if best is None or overlap > best["overlap"]:
            best = {"found": overlap >= 0.55, "overlap": round(overlap, 3),
                    "chunk_id": r["chunk_id"], "doc_type": r["doc_type"],
                    "known_at": r["known_at"], "quote": gold,
                    "matched_words": len(tset & got), "gold_words": len(tset)}
    if best is None:
        return {"found": False, "reason": "no FTS hit for the gold words", "quote": gold}
    if not best["found"]:
        best["reason"] = "best token overlap below 0.55"
    return best
