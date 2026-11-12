"""T-194: the ``event`` table -- one row per event an announcement names, so a list question ("all FY26 USFDA
inspections") is one call instead of eleven announcement titles.

Built from the announcement / press-release ``doc`` title and its first pages: the kind (regulatory inspection,
buyback, dividend, acquisition, merger), the company unit the inspection named, the inspection dates, the outcome
the text states (OAI, VAI, warning letter, Form 483, no observations, closed), the sentence it came from and (T-197)
the body sentences that state the outcome, observations, classification, impact or amount, with the document's type
and title.  Rules only, never a company list: the same builder serves every company the build holds.

CLI: python -m reality_engine.pilot3.events --out <db> [--symbols A,B]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

import yaml

from . import schema

LEX_DIR = Path(__file__).resolve().parent / "lexicon"
BODY_CHARS = 600             # an event's body excerpt: at most 3 sentences, 600 characters
BODY_SENTENCES = 3


def _cue_patterns(name: str = "event_cues") -> tuple[re.Pattern[str], ...]:
    """The sentences of a filing that answer an event question: its outcome, observations, classification,
    impact, dates and amounts.  The cues live in the existing lexicon files -- ``common`` carries the generic
    ones and each sector family adds its own -- so no company or question is special-cased (T-197 step 7)."""
    sources: list[str] = []
    for path in sorted(LEX_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        sources += [str(cue) for cue in doc.get(name) or []]
    return tuple(re.compile(source, re.I) for source in dict.fromkeys(sources))


_CUES: tuple[re.Pattern[str], ...] | None = None
_AMOUNT_CUES: tuple[re.Pattern[str], ...] | None = None


def _around_cue(sentence: str, cues: tuple[re.Pattern[str], ...], width: int = 320) -> str:
    """A cue sentence that also carries letterhead is cut around the cue, not served from its first character."""
    if len(sentence) <= 240:
        return sentence
    for rx in cues:
        hit = rx.search(sentence)
        if hit:
            start = max(0, hit.start() - 120)
            if start:
                start = max(0, sentence.rfind(" ", 0, start) + 1)   # never start mid-word
            return sentence[start:start + width].strip()
    return sentence[:width].strip()


def body_excerpt(text: str | None) -> str | None:
    """The sentences that state an event's outcome, observations, classification, impact or amount: split on
    sentence ends, keep the word-cue sentences first (an amount or percentage sentence only when no word cue
    matched), at most 3 sentences / 600 characters."""
    global _CUES, _AMOUNT_CUES
    if not text:
        return None
    clean = re.sub(r"\s+", " ", text).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", clean) if s.strip()]
    if _CUES is None:
        _CUES, _AMOUNT_CUES = _cue_patterns(), _cue_patterns("event_amount_cues")
    chosen = [s for s in sentences if any(rx.search(s) for rx in _CUES)][:BODY_SENTENCES]
    if not chosen:
        chosen = [s for s in sentences if any(rx.search(s) for rx in (_AMOUNT_CUES or ()))][:BODY_SENTENCES]
    if not chosen:
        chosen = sentences[:BODY_SENTENCES]
    return (" ".join(_around_cue(s, _CUES + (_AMOUNT_CUES or ())) for s in chosen)[:BODY_CHARS].strip() or None)

# The kinds, in match order.  A regulatory inspection is checked first: its announcement often carries the words
# "dividend"? no -- but a warning letter is an inspection outcome, so it must not become its own event unless the
# text does not describe the inspection itself.
KINDS = (
    # An inspection needs the regulator AND an inspection word in one sentence: a bare "USFDA" is a product
    # approval, and a bare "warning letter" can come from the exchange (a listing-disclosure warning).
    ("inspection", re.compile(
        r"(?:\busfda\b|\bu\.?s\.? ?fda\b|\bus fda\b|\bfda\b)[^.]{0,90}?"
        r"(?:inspection|audit|\bEIR\b|establishment inspection report|form\s?-?483|warning letter|classification"
        r"|observations?)"
        r"|(?:inspection|audit|pre-?approval|\bPAI\b)[^.]{0,90}?(?:\busfda\b|\bfda\b)"
        r"|form\s?-?483"
        r"|warning letter[^.]{0,90}?(?:\busfda\b|\bfda\b)", re.I)),
    ("buyback", re.compile(r"\bbuy\s?-?back\b|\bbuyback\b", re.I)),
    ("merger", re.compile(r"\bmerger\b|amalgamat|scheme of (?:merger|amalgamation)|demerger", re.I)),
    ("acquisition", re.compile(r"\bacqui(?:re|red|res|sition)\b|takeover|\bstake (?:acquisition|purchase)\b", re.I)),
    ("dividend", re.compile(r"\bdividends?\b", re.I)),
)

_MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), 1)}
_MONTHS.update({name[:3]: index for name, index in list(_MONTHS.items())})

_RANGE_DM = re.compile(r"(?:from\s+)?(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|and|[-–])\s*(\d{1,2})(?:st|nd|rd|th)?\s+"
                       r"([A-Za-z]{3,9})\.?,?\s+(\d{4})", re.I)
_RANGE_MD = re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|and|[-–])\s*(\d{1,2})(?:st|nd|rd|th)?,?"
                       r"\s+(\d{4})", re.I)
_ONE_DATE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", re.I)

_UNIT = re.compile(r"\b(unit|plant|facility|site)\s*[-–]?\s*(?:no\.?\s*)?([IVXLC]{1,6}|\d{1,2}[A-Za-z]?)\b", re.I)
_OUTCOMES = (
    ("OAI", re.compile(r"\bofficial action indicated\b|\bOAI\b", re.I)),
    ("VAI", re.compile(r"\bvoluntary action indicated\b|\bVAI\b", re.I)),
    ("warning letter", re.compile(r"\bwarning letter\b", re.I)),
    ("Form 483", re.compile(r"\bform\s?-?483\b|\b483\b", re.I)),
    ("no observations", re.compile(r"\b(?:no|zero|nil)\s+(?:observations|non-compliance|noncompliance|"
                                   r"data integrity issues?)\b", re.I)),
    ("EIR received", re.compile(r"\bestablishment inspection report\b|\bEIR\b", re.I)),
    ("closed", re.compile(r"\b(?:successfully\s+)?closed\b|\bclosure (?:of|received)\b", re.I)),
)


def _date(y: str, month: str, day: str) -> str | None:
    month_no = _MONTHS.get(month.lower().rstrip("."))
    if not month_no:
        return None
    try:
        return f"{int(y):04d}-{month_no:02d}-{int(day):02d}"
    except (TypeError, ValueError):
        return None


def event_dates(text: str) -> tuple[str | None, str | None]:
    """(start, end) of the inspection the text names, as ISO days; (None, None) when it prints no range."""
    for match in _RANGE_DM.finditer(text or ""):
        start = _date(match[4], match[3], match[1])
        end = _date(match[4], match[3], match[2])
        if start and end:
            return start, end
    for match in _RANGE_MD.finditer(text or ""):
        start = _date(match[4], match[1], match[2])
        end = _date(match[4], match[1], match[3])
        if start and end:
            return start, end
    match = _ONE_DATE.search(text or "")
    if match:
        start = _date(match[3], match[2], match[1])
        return (start, start) if start else (None, None)
    return None, None


def _kind(title: str, text: str) -> str | None:
    for kind, rx in KINDS:
        if rx.search(title or ""):
            return kind
    for kind, rx in KINDS:
        if rx.search(text or ""):
            return kind
    return None


def _unit(text: str) -> str | None:
    match = _UNIT.search(text or "")
    return f"{match[1].title()} {match[2].upper() if match[2].isalpha() else match[2]}" if match else None


def _outcome(text: str) -> str | None:
    for label, rx in _OUTCOMES:
        if rx.search(text or ""):
            return label
    return None


def _quote(text: str, match: re.Match | None, width: int = 400) -> str | None:
    """The sentence (or window) around the kind word, so a row carries the words it was built from."""
    if not text:
        return None
    if match is None:
        return text[:width].strip()
    start = max(0, match.start() - width // 3)
    end = min(len(text), start + width)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def build_events(conn: sqlite3.Connection) -> dict:
    """Rewrite ``event`` from the announcement titles and their first pages.  One row per event (document, kind)."""
    schema.migrate(conn)         # T-202: the event table, its T-197 columns and its index, on any older store
    conn.execute("DELETE FROM event")
    docs = conn.execute(
        "SELECT d.doc_key, d.symbol, d.isin, d.title, d.filing_date, COALESCE(d.known_at, d.filing_date) known_at, "
        "d.doc_type FROM doc d WHERE d.doc_type IN ('announcement','press_release') "
        "ORDER BY COALESCE(d.known_at, d.filing_date)").fetchall()
    rows, seen = [], set()
    for doc_key, symbol, isin, title, filing_date, known_at, doc_type in docs:
        pages = conn.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page LIMIT 2",
                             (doc_key,)).fetchall()
        text = "\n".join((page[1] or "") for page in pages)
        kind = _kind(title or "", text)
        if not kind or (doc_key, kind) in seen:
            continue
        seen.add((doc_key, kind))
        body = f"{title or ''}\n{text}"
        match = next((rx.search(title or "") for k, rx in KINDS if k == kind and rx.search(title or "")), None) \
            or next(rx.search(text) for k, rx in KINDS if k == kind)
        start, end = event_dates(body) if kind == "inspection" else (None, None)
        excerpt = body_excerpt(text)
        page = 1
        if excerpt:                          # the page the excerpt's first sentence was printed on
            head = excerpt[:40]
            page = next((int(number) for number, page_text in pages if head and head in (page_text or "")),
                        int(pages[0][0]) if pages else 1)
        rows.append((symbol, isin, kind, start or filing_date, end, filing_date,
                     _unit(body) if kind == "inspection" else None,
                     _outcome(text) if kind == "inspection" else None,
                     re.sub(r"\s+", " ", (title or body)[:300]).strip(), doc_key, page,
                     _quote(body, match), known_at, "doc.known_at", "doc.title+doc_page",
                     "pilot3.events", doc_type, title, excerpt))
    conn.executemany(
        "INSERT INTO event (symbol, isin, kind, event_date, end_date, announced, unit, outcome, subject, doc_key, "
        "page, quote, known_at, known_at_source, source, extractor_rule, doc_type, title, body_excerpt) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    by_kind: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    for row in rows:
        by_kind[row[2]] = by_kind.get(row[2], 0) + 1
        by_symbol[row[0]] = by_symbol.get(row[0], 0) + 1
    return {"rows": len(rows), "by_kind": by_kind, "by_symbol": by_symbol}


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None, help="limit the count report to these symbols (the table is rewritten)")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.out)
    try:
        stats = build_events(conn)
    finally:
        conn.close()
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
