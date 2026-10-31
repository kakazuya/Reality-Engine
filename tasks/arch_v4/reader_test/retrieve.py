"""Cheap FTS retrieval over the pilot chunks, with the filters applied before scoring.

What went wrong with naive search: every chunk header repeats the company name, so an OR
over the question's words matches letterheads and boilerplate.  This module
  * strips the company name and question words out of the query,
  * searches the ``body`` column only (never the header),
  * filters entity, doc_type and ``known_at <= as_of`` in SQL first,
  * runs a strict AND tier and a broader OR tier, then reranks locally on term coverage,
    quoted phrases, numbers and date proximity.
No embeddings and no network are used here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import db

STOP = {
    "what", "whats", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "did", "does", "do", "was", "were", "is", "are", "has", "have", "had", "said", "say",
    "says", "saying", "stated", "state", "according", "about", "into", "from", "with",
    "that", "this", "these", "those", "there", "their", "its", "for", "and", "but", "not",
    "any", "all", "also", "just", "only", "over", "under", "after", "before", "during",
    "latest", "recent", "most", "much", "many", "more", "some", "the", "a", "an", "of",
    "to", "in", "on", "at", "by", "as", "or", "be", "been", "being", "it", "he", "she",
    "they", "we", "you", "i", "company", "management", "report", "reported", "disclosure",
    "disclosed", "filing", "filed", "exactly", "please", "tell", "give", "given", "take",
    "taken", "make", "made", "per", "cent", "percent", "million", "billion", "crore",
    "lakh", "tonne", "tonnes", "ton", "tons", "mw", "gw", "inr", "rs", "rupees", "fy",
    "q1", "q2", "q3", "q4", "h1", "h2", "year", "years", "quarter", "quarters", "month",
    "months", "today", "current", "last", "next", "first", "second", "third", "new",
    "kya", "ka", "ki", "ke", "ko", "mein", "ne", "aur", "kis", "kab", "kaunsa", "kaunsi",
    "kitna", "kitne", "kyun", "kiske", "aage", "peeche", "bola", "tha", "hoga", "kar",
    "raha", "rahe", "hai", "hain", "se", "par", "ek", "wala", "wale", "bhi", "nahi",
    "kuch", "liye", "gaya", "gayi", "hua", "hui", "hue", "banaya", "bataya", "chahiye",
    "khiske", "usko", "uthana", "padega", "kiya", "baare", "likha", "saal", "tak",
    "hinglish", "nse", "bse", "s",
}

# Month names must match as whole words: a bare ``mar`` must not eat "margins".
_MONTH_IN_TEXT = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?", re.I)

# Collocations that a bag-of-words query breaks.  Added as phrases only when present.
COLLOCATIONS = [
    "on track", "capital repairs", "capital repair", "order book", "joint venture",
    "renewable energy", "operating margin", "revenue growth", "working capital",
    "management change", "statutory auditor", "auditor resignation", "auditor declaration",
    "force majeure", "plant shutdown", "capacity additions", "cement demand",
    "internal accruals", "debt or internal accruals", "credit rating", "key audit matters",
]
_UNIT_MT = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:MT|mt)\b")
_UNIT_MW = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:MW|mw)\b")
_UNIT_GW = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:GW|gw)\b")

# Generic, hand-written synonym groups.  They are applied to every question, not fitted to
# the 40: the aim is to test whether ordinary domain vocabulary closes the gap between the
# ask's wording and the transcript's wording.
SYNONYMS = {
    "renewable": ["solar", "wind", "hydro"],
    "capacity": ["mtpa", "capacity"],
    "repair": ["repairs", "maintenance", "shutdown"],
    "repairs": ["repair", "maintenance", "shutdown"],
    "order": ["orders", "orderbook"],
    "orderbook": ["order", "orders"],
    "margin": ["ebitda", "margin"],
    "capex": ["capital", "expenditure"],
    "auditor": ["statutory", "auditor"],
    "facility": ["facilities", "plant", "plants", "units"],
    "facilities": ["facility", "plant", "plants", "units"],
    "guidance": ["guided", "guidance", "outlook"],
    "pledge": ["pledged", "pledge"],
    "jv": ["joint", "venture"],
    "ceo": ["managing", "director"],
    "wagon": ["wagons", "wheelset", "wheelsets"],
    "approval": ["approvals", "ccs"],
    "declaration": ["declared", "declaration", "opinion"],
    "resignation": ["resigned", "resignation"],
    "commissioned": ["commissioning", "commissioned"],
    "commissioning": ["commissioned", "commissioning"],
    "freight": ["logistics"],
    "subsidiary": ["subsidiaries"],
    "guarantee": ["guarantees"],
    "borrowing": ["borrowings", "debt"],
    "debt": ["borrowings", "debt"],
    "funded": ["funding", "financed"],
    "acquisition": ["acquired", "acquisition"],
}

_QUOTED = re.compile(r"[\"'\u2018\u2019\u201c\u201d]([^\"'\u2018\u2019\u201c\u201d]{3,80})[\"'\u2018\u2019\u201c\u201d]")
_DATE_DMY = re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})\b", re.I)
_DATE_ISO = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+\.\d+|\d+)(?![\w.])")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


@dataclass
class TermSet:
    words: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())


def _entity_words(q: dict) -> set[str]:
    drop = set()
    for value in (q.get("symbol"), q.get("name")):
        for t in _tokens(str(value or "")):
            if len(t) >= 3 and t not in {"limited", "ltd", "industries", "industry", "company"}:
                drop.add(t)
    # symbols are often one word; names add words such as "apollo", "hindalco"
    return drop


def _date_seeds(text: str) -> list[str]:
    out: list[str] = []
    for d, mon, y in _DATE_DMY.findall(text):
        try:
            out.append(date(int(y), _MONTHS[mon.lower()[:3]], int(d)).isoformat())
        except ValueError:
            pass
    for iso in _DATE_ISO.findall(text):
        out.append(iso)
    return sorted(set(out))


def terms_for_question(q: dict) -> TermSet:
    text = q["question"]
    # Units in the ask are usually printed in full in the document ("8 MT" -> "8 Mn Ton").
    norm = _UNIT_MT.sub(r"\1 million tonne capacity", text)
    norm = _UNIT_MW.sub(r"\1 megawatt", norm)
    norm = _UNIT_GW.sub(r"\1 gigawatt", norm)
    norm = _MONTH_IN_TEXT.sub(" ", norm)  # dates are handled separately, not as words
    drop = _entity_words(q) | STOP
    raw = _tokens(norm)

    words: list[str] = []
    for t in raw:
        if t in drop or len(t) < 3:
            continue
        if re.fullmatch(r"(?:q[1-4]fy\d{2,4}|fy\d{2,4}|q[1-4])", t):
            continue
        words.append(t)
    # quoted phrases are the ask's own distinctive words; keep their words too
    phrases: list[str] = []
    for p in _QUOTED.findall(text):
        toks = [t for t in _tokens(p) if t not in STOP and t not in drop]
        if len(toks) >= 2:
            phrases.append(" ".join(toks))
            words.extend(toks)
    # adjacent content-word bigrams ("capital repairs", "operating margin", ...)
    for a, b in zip(words, words[1:]):
        if a != b and not a.isdigit() and not b.isdigit():
            phrases.append(f"{a} {b}")
    low = text.lower()
    for coll in COLLOCATIONS:
        if coll in low:
            phrases.append(coll)
    if "margin" in words or "margins" in words:
        phrases.append("operating margin")

    # simple plural/stem variants: FTS5 unicode61 does not stem
    expanded: list[str] = []
    for w in words:
        expanded.append(w)
        if w.endswith("ies") and len(w) > 5:
            expanded.append(w[:-3] + "y")
        elif w.endswith("es") and len(w) > 4:
            expanded.append(w[:-2])
        elif w.endswith("s") and len(w) > 4:
            expanded.append(w[:-1])
        elif len(w) > 4:
            expanded.append(w + "s")
        for syn in SYNONYMS.get(w, []):
            expanded.append(syn)
            if " " in syn:
                phrases.append(syn)

    # numbers: keep discriminating values; drop calendar years
    numbers: list[str] = []
    for tok in _NUM.findall(text):
        clean = tok.replace(",", "")
        if clean.endswith(".0"):
            clean = clean[:-2]
        try:
            val = float(clean)
        except ValueError:
            continue
        if 1900 <= val <= 2100 and "." not in clean:
            continue
        if val < 3 and "." not in clean:
            continue
        numbers.append(clean)

    # dedupe while preserving order, cap the OR query
    seen = set()
    uniq = []
    for w in expanded:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    phrases = list(dict.fromkeys(p for p in phrases if p))
    return TermSet(words=uniq[:26], phrases=phrases[:8], numbers=sorted(set(numbers)),
                   dates=_date_seeds(text))


def _quote_term(t: str) -> str:
    safe = re.sub(r"[^a-z0-9. ]", "", t.lower()).strip()
    return f'"{safe}"' if safe else ""


def fts_or(terms: TermSet) -> str:
    parts = [_quote_term(t) for t in terms.words[:18]]
    parts += [_quote_term(p) for p in terms.phrases[:4]]
    parts += [_quote_term(n) for n in terms.numbers[:6]]
    return " OR ".join(p for p in parts if p)


def fts_and(terms: TermSet) -> str:
    # the strict tier uses the most selective words the ask names
    parts = [_quote_term(t) for t in terms.words[:6]]
    parts += [_quote_term(n) for n in terms.numbers[:2]]
    return " AND ".join(p for p in parts if p)


def _contains_word(hay: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", hay) is not None


def _date_score(known_at: str, dates: list[str]) -> float:
    if not dates or not known_at:
        return 0.0
    try:
        kd = date.fromisoformat(known_at[:10])
    except ValueError:
        return 0.0
    best = 9999
    for d in dates:
        try:
            best = min(best, abs((kd - date.fromisoformat(d)).days))
        except ValueError:
            continue
    if best <= 3:
        return 2.0
    if best <= 10:
        return 1.2
    if best <= 30:
        return 0.4
    return 0.0


LETTERHEAD = re.compile(
    r"(registered office|corporate identity number|\bcin\b|corporate office|"
    r"telephone|website:|investor relations|stock exchange|symbol:|scrip code|"
    r"co\.?secy|our ref|by portal|corporate relationship department|"
    r"phiroze jeejeebhoy|exchange plaza|dalal street|bandra.kurla|listing department)",
    re.I,
)


def _recency_score(known_at: str, as_of: str) -> float:
    try:
        kd = date.fromisoformat((known_at or "")[:10])
        ad = date.fromisoformat((as_of or "")[:10])
    except ValueError:
        return 0.0
    age = (ad - kd).days
    if age < 0:
        return 0.0
    if age <= 150:
        return 1.8
    if age <= 400:
        return 0.9
    if age <= 800:
        return 0.3
    return -0.8


def rerank(rows: list[dict], terms: TermSet, doc_types: list[str], top_k: int = 8,
           as_of: str = "") -> list[dict]:
    """Local rerank.  ``rows`` already carry the per-tier reciprocal rank and the raw row."""
    hinted = set(doc_types)
    for r in rows:
        body = (r["body"] or "")
        body_l = re.sub(r"\s+", " ", body.lower())
        coverage = sum(1 for w in terms.words[:18] if _contains_word(body_l, w))
        phrase_hits = sum(1 for p in terms.phrases if p in body_l)
        num_hits = sum(1 for n in terms.numbers if _contains_word(body_l, n))
        score = 1.6 * coverage + 2.2 * phrase_hits + 1.2 * num_hits
        score += 0.9 * float(r.get("rr") or 0.0)
        score += _date_score(r.get("known_at", ""), terms.dates)
        score += _recency_score(r.get("known_at", ""), as_of)
        if r.get("tier") == "and":
            score += 1.1
        if r.get("doc_type") in hinted:
            score += 0.9 * (len(hinted) - doc_types.index(r["doc_type"])) / max(1, len(hinted))
        boilter = len(LETTERHEAD.findall(body[:700]))
        if boilter:
            score -= min(7.0, 2.4 * boilter)
        if r.get("unit_kind") == "paragraph" and (r.get("speaker_role") in (None, "unknown")):
            score -= 3.0
        role = r.get("speaker_role")
        if role == "management":
            score += 0.9
        elif role == "analyst":
            score -= 0.6
        if r.get("unit_kind") == "opening_remark":
            score += 0.5
        if len(body) < 220:
            score -= 0.6
        r["rerank"] = round(score, 3)
        r["term_coverage"] = coverage
        r["phrase_hits"] = phrase_hits
        r["num_hits"] = num_hits

    ordered = sorted(rows, key=lambda r: (-r["rerank"], r.get("bm25") or 0.0))
    picked: list[dict] = []
    seen: set[int] = set()
    per_type: dict[str, int] = {}
    cap = max(3, top_k // 2)
    for r in ordered:
        t = r["doc_type"]
        if per_type.get(t, 0) >= cap:
            continue
        picked.append(r)
        seen.add(r["chunk_id"])
        per_type[t] = per_type.get(t, 0) + 1
        if len(picked) >= top_k:
            return picked
    for r in ordered:
        if len(picked) >= top_k:
            break
        if r["chunk_id"] not in seen:
            picked.append(r)
            seen.add(r["chunk_id"])
    return picked


def retrieve_for_question(con, q: dict, top_k: int = 8) -> dict:
    terms = terms_for_question(q)
    doc_types = list(q.get("doc_types") or ["concall", "deck", "annual_report", "results_notes", "announcement"])
    all_types = ["concall", "deck", "annual_report", "results_notes", "announcement"]
    or_q, and_q = fts_or(terms), fts_and(terms)
    merged: dict[int, dict] = {}
    per_type: dict[str, dict] = {}

    def run(types: list[str]) -> None:
        for dt in types:
            hits = []
            for tier, fq in (("and", and_q), ("or", or_q)):
                if not fq:
                    continue
                try:
                    got = db.search(con, isin=q["isin"], doc_types=[dt], as_of=q["as_of"],
                                    fts_query=fq, limit=60)
                except ValueError:
                    got = []
                for pos, row in enumerate(got):
                    d = dict(row)
                    d["tier"] = tier
                    d["rr"] = 1.0 / (1.0 + pos)
                    d["want_type"] = dt
                    old = merged.get(d["chunk_id"])
                    if old is None or d["rr"] > old["rr"] or (tier == "and" and old["tier"] != "and"):
                        merged[d["chunk_id"]] = d
                hits.append(len(got))
            per_type[dt] = {"and": hits[0] if len(hits) > 0 else 0,
                            "or": hits[1] if len(hits) > 1 else 0}

    run(all_types)
    picked = rerank(list(merged.values()), terms, doc_types, top_k=top_k, as_of=q["as_of"])
    widened = bool(set(all_types) - set(doc_types))
    return {
        "query_terms": {"words": terms.words[:18], "phrases": terms.phrases,
                        "numbers": terms.numbers, "dates": terms.dates},
        "fts": {"or": or_q, "and": and_q},
        "per_type_hits": per_type,
        "hinted_types": doc_types,
        "widened_beyond_hint": widened,
        "n_candidates": len(merged),
        "chunks": [{k: r.get(k) for k in (
            "chunk_id", "doc_id", "doc_type", "header", "body", "section", "speaker",
            "speaker_role", "unit_kind", "known_at", "event_date", "fiscal_period",
            "page_from", "page_to", "char_len", "quality_grade", "bm25", "tier",
            "rerank", "term_coverage", "phrase_hits", "num_hits")} for r in picked],
    }
