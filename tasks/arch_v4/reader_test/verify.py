"""Verbatim-quote and number checks.

The rule fixed before running: an answer is accepted only if its quote is a verbatim
substring of one of the retrieved chunks.  Two match strengths are recorded:
  * ``exact``: the normalised quote is a substring (case/whitespace/unicode folded);
  * ``words``: the same words in the same order after punctuation is dropped.
Anything else is a fabricated quote and the answer is rejected.  Numbers in the answer
must already be present in the quote: the model may connect words, never set a number.
"""
from __future__ import annotations

import re
import unicodedata

_NOT_STATED = {"not stated", "not_stated", "notstated", "not in data", "not found",
               "not available", "no statement", "the documents do not state this"}

# Period labels are connectors, not facts: "Q3 of the current fiscal" need not carry "27".
_PERIOD = re.compile(
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|"
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|"
    r"\bFY\s*'?\d{2}\s*[-\u2013/]\s*'?\d{2}\b|"
    r"\b(?:19|20)\d{2}\s*[-\u2013]\s*(?:19|20)?\d{2}\b|"
    r"'?\b\d{2}\s*[-\u2013]\s*'?\d{2}\b|"
    r"\b(?:Q[1-4]\s*FY\s*'?\d{2,4}|FY\s*'?\d{2,4}|(?:19|20)\d{2}|Q[1-4])\b|"
    r"'\d{2}\b",
    re.I,
)
# Page/note citations are provenance, not numbers the model is asserting about the company.
_CITATION = re.compile(
    r"\b(?:pages?|p\.?|notes?|sections?|clauses?|regulations?|annexures?)\s*"
    r"\d+(?:\s*(?:,|and|&|to)\s*\d+)*",
    re.I,
)
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w.])")


def normalise(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = (s.replace("\u00ad", "").replace("\u200b", "").replace("\ufeff", "")
          .replace("\u2018", "'").replace("\u2019", "'")
          .replace("\u201c", '"').replace("\u201d", '"')
          .replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-"))
    return re.sub(r"\s+", " ", s).strip()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", normalise(text).lower())


def _word_subsequence(needle: list[str], hay: list[str]) -> bool:
    if len(needle) < 4 or len(needle) > len(hay):
        return False
    n = len(needle)
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def find_quote(quote: str, chunks: list[dict]) -> dict:
    """Return the first chunk whose text contains the quote, and how strong the match is."""
    qn = normalise(quote).lower()
    qw = words(quote)
    if len(qn) < 8 or len(qw) < 4:
        return {"ok": False, "kind": "too_short", "chunk_id": None, "where": None}
    for ch in chunks:
        for where in ("body", "header"):
            hay = normalise(ch.get(where) or "")
            if qn and qn in hay.lower():
                return {"ok": True, "kind": "exact", "chunk_id": ch["chunk_id"], "where": where}
    for ch in chunks:
        for where in ("body", "header"):
            if _word_subsequence(qw, words(ch.get(where) or "")):
                return {"ok": True, "kind": "words", "chunk_id": ch["chunk_id"], "where": where}
    return {"ok": False, "kind": "not_found", "chunk_id": None, "where": None}


def quote_span(quote: str, chunk: dict, width: int = 220) -> str:
    text = normalise(chunk.get("body") or "")
    qn = normalise(quote)
    idx = text.lower().find(qn.lower())
    if idx < 0:
        return text[:width]
    lo = max(0, idx - width // 3)
    return text[lo:lo + width]


def _numbers(text: str) -> list[str]:
    clean = _PERIOD.sub(" ", normalise(text))
    clean = _CITATION.sub(" ", clean)
    out = []
    for tok in _NUM.findall(clean):
        v = tok.replace(",", "")
        if v.endswith(".0"):
            v = v[:-2]
        try:
            f = float(v)
        except ValueError:
            continue
        # one-digit quantities are too ambiguous (a quarter, a bullet) to police
        if f < 10 and "." not in v:
            continue
        out.append(v)
    return out


def number_check(answer: str, quote: str, question: str = "") -> dict:
    """Every *new* number must be in the quote.

    A number the question itself supplies (e.g. "4.5 GW", "15% growth") is a premise, not
    a model-set value, so restating it is allowed.  Anything else must come from the quote.
    """
    allowed = set(_numbers(quote)) | set(_numbers(question))
    missing = [n for n in _numbers(answer) if n not in allowed]
    return {"ok": not missing, "answer_numbers": _numbers(answer), "missing_numbers": missing}


def is_not_stated(answer: str) -> bool:
    a = normalise(answer).lower().strip(" .!")
    return a in _NOT_STATED or a.startswith("not stated") or a.startswith("not in data")


def verify_answer(answer: str, quote: str, chunks: list[dict], question: str = "") -> dict:
    if is_not_stated(answer) and not (quote or "").strip():
        return {"status": "not_stated", "quote_ok": False, "number_ok": True,
                "match": {"ok": False, "kind": "not_stated", "chunk_id": None, "where": None},
                "missing_numbers": []}
    if is_not_stated(answer) and (quote or "").strip():
        # A "not stated" answer that carries a quote is self-contradictory; it cannot be
        # accepted as either an answer or a clean not-stated.
        return {"status": "rejected_contradiction", "quote_ok": find_quote(quote, chunks)["ok"],
                "number_ok": True, "match": find_quote(quote, chunks),
                "missing_numbers": []}
    if not (quote or "").strip():
        return {"status": "rejected_no_quote", "quote_ok": False, "number_ok": False,
                "match": {"ok": False, "kind": "empty", "chunk_id": None, "where": None},
                "missing_numbers": _numbers(answer)}
    match = find_quote(quote, chunks)
    num = number_check(answer, quote, question)
    if not match["ok"]:
        status = "rejected_quote"
    elif not num["ok"]:
        status = "rejected_number"
    else:
        status = "verified"
    return {"status": status, "quote_ok": match["ok"],
            "quote_match_kind": match["kind"], "quote_chunk_id": match["chunk_id"],
            "quote_where": match["where"], "number_ok": num["ok"],
            "missing_numbers": num["missing_numbers"], "match": match}
