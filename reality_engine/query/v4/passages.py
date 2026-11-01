"""Local keyword retrieval over a chunk store for a narrative ask (T-038).

No embeddings, no model and no paid call: BM25 (k1=1.2, b=0.75) over the chunk bodies of
one company only, with the question's own words as the topic when the decomposer gives
none.  A passage is returned only when it matches enough of the topic terms, and every
quote is an exact substring of its chunk body -- a passage is never turned into a number
and never counted as an answered value.
"""
from __future__ import annotations

import math
import re
import sqlite3
from typing import Any, Sequence

K1, B = 1.2, 0.75
#: words that carry no topic of their own in an analyst question
STOPWORDS = frozenset("""
about above after again against almost also among another anything asked available back
been before being below best between both business came could current currently didn't
does doesn't doing done down during each every explain first following from further give
given going good great had has have having here how however into just keep keep latest
less like long made make many may more most much must near need never next none nothing
offer often only other otherwise our out over overall past please possible quarter rather
really report reported said same say says second see seem sense should show side since
some something still such take tell than that their them then there therefore these they
thing think third this those though through time today told took toward under until upon
used very want was way week well were what when where whether which while who whole why
will with within without would year years you your
the and for are was did how its has per not but can all who why any new one two own off
company management concall transcript earnings call investor presentation document
january february march april may june july august september october november december
""".split())


def terms(question: str | None, topic: Any = None) -> list[str]:
    """Topic terms: the decomposer's topic when it gave one, else the question's own words."""
    text = str(topic or "").strip() or str(question or "")
    # Three letters, because EPC, HAM, NIM and CFO are often the whole topic of a question.
    words = re.findall(r"[a-z][a-z0-9]{2,}", text.lower())
    out: list[str] = []
    for word in words:
        if word in STOPWORDS or word.isdigit() or word in out:
            continue
        out.append(word)
    return out


def _hits(body: str, terms: Sequence[str]) -> dict[str, int]:
    low = body.lower()
    return {term: len(re.findall(r"\b" + re.escape(term), low)) for term in terms}


def quote_of(body: str, terms: Sequence[str]) -> str:
    """The passage's own text from the sentence that carries the most topic terms.

    It is always a contiguous substring of ``body`` (a reader can find it verbatim), which
    rules out stitching wrapped lines back together.  A page heading ("PRICE WATERHOUSE
    LLP") loses to a sentence of six words or more when one matches.
    """
    starts = [0] + [match.end() for match in re.finditer(r"(?<=[.!?;])\s+|\n+", body)]
    best = (0, False, 0)                     # topic hits, a sentence of 6+ words, start
    for start in starts:
        head = re.split(r"(?<=[.!?;])\s+|\n", body[start:start + 600], maxsplit=1)[0]
        hits = sum(1 for term in terms if re.search(r"\b" + re.escape(term), head.lower()))
        if (hits, len(head.split()) >= 6) > (best[0], best[1]):
            best = (hits, len(head.split()) >= 6, start)
    if best[0]:
        quote = body[best[2]:best[2] + 480].strip()
        if len(quote) == 480 and " " in quote:
            quote = quote[:quote.rfind(" ")].rstrip(" ,;:-")
        return quote
    low = body.lower()
    for term in sorted(terms, key=len, reverse=True):
        index = low.find(term)
        if index >= 0:
            start = body.rfind(" ", 0, max(0, index - 120))
            return body[max(0, start + 1):index + 360].strip()
    return body.strip()[:360]


def retrieve(conn: Any, isin: str, terms_: Sequence[str], as_of: str,
             limit: int = 5) -> list[dict[str, Any]] | None:
    """Top passages of ``isin`` known by ``as_of`` that match enough of ``terms_``.

    ``None`` when this store has no ``chunk`` table; ``[]`` when nothing matched, which
    the caller must refuse rather than fill with unrelated text.
    """
    if not isin or not terms_:
        return []
    sql = ("SELECT chunk_id, doc_id, doc_type, page_from, page_to, body, known_at "
           "FROM chunk WHERE isin = ? AND substr(known_at, 1, 10) <= ?")
    try:
        cursor = conn.execute(sql, (isin, as_of))
        names = [item[0] for item in (cursor.description or [])]
        rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    except sqlite3.Error:
        return None
    if not rows:
        return []
    counts = [_hits(str(row.get("body") or ""), terms_) for row in rows]
    n = len(rows)
    df = {term: sum(1 for hit in counts if hit[term]) for term in terms_}
    # A word in a tenth of the company's chunks (its name, the year, "EBITDA" in a bank
    # deck) names no topic: requiring it would fill the slot with the nearest page header.
    topical = [term for term in terms_ if df[term] <= max(3, int(0.1 * n))]
    if not topical:
        return []
    avg = sum(len(str(row.get("body") or "").split()) for row in rows) / max(n, 1)
    need = 1 if len(topical) < 2 else max(2, math.ceil(0.6 * len(topical)))
    # ...and one matched term must be specific to this company's filings.  A passage that
    # matches only words every page carries ("price", "value", "date") is unrelated text.
    rare_cut = max(2, int(0.02 * n))
    scored = []
    for row, hit in zip(rows, counts):
        matched = [term for term in topical if hit[term]]
        if len(matched) < need or not any(df[term] <= rare_cut for term in matched):
            continue
        length = len(str(row.get("body") or "").split())
        score = 0.0
        for term in topical:
            if not hit[term]:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = hit[term] / max(length, 1)
            score += idf * freq * (K1 + 1) / (freq + K1 * (1 - B + B * length / max(avg, 1)))
        scored.append((score, row))
    scored.sort(key=lambda item: -item[0])
    out = []
    for score, row in scored[:limit]:
        body = str(row.get("body") or "")
        matched = [term for term in topical if _hits(body, [term])[term]]
        out.append({"chunk_id": row.get("chunk_id"), "doc_id": row.get("doc_id"),
                    "doc_type": row.get("doc_type"),
                    "page_no": row.get("page_from"), "page_to": row.get("page_to"),
                    "known_at": str(row.get("known_at") or "")[:10],
                    "quote": quote_of(body, topical), "score": round(score, 6),
                    "matched_terms": matched})
    return out
