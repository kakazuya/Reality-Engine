"""C1: structure-aware chunking.

The old chunker cut every document into fixed 512-token windows with a
64-token overlap, so tables, Q&A pairs and numbered clauses were routinely
sliced.  This module cuts on the document's own units instead:

* concall transcripts  -> one speaker turn; an analyst question plus the whole
  management answer as one Q&A chunk; opening remarks per speaker;
* investor decks       -> one slide (page) per chunk;
* annual reports, results -> one note / schedule / table per chunk, headings
  from heading blocks (PyMuPDF font size and bold spans in the PDF path);
* PIB / RBI / circulars -> one clause or numbered paragraph per chunk.

Every chunk body is a *verbatim slice* of the document text, so its character
span stays exact and two chunkings of the same text can be compared on
spans.  The header is metadata only and stored separately.

Size rules: a unit over ``MAX_CHARS`` is split at the next structural boundary
(paragraph, line, sentence -- never mid-sentence unless a single sentence is
itself too long); a unit under ``MIN_CHARS`` is merged with its neighbour in
the same section.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

MAX_CHARS = 6000
MIN_CHARS = 300
# One Q&A pair must fit a single retrieval slot: a management answer can run for
# many minutes, and a 12k-char "chunk" is invisible to a 512-token embedder and
# to any caller that budgets characters.  Turn boundaries are the cuts; only an
# answer that is itself longer is split at sentence boundaries, with the
# question repeated in the header of every continuation.
QA_MAX_CHARS = 2200

DOC_LABELS = {
    "concall": "Concall transcript",
    "deck": "Investor deck",
    "annual_report": "Annual report",
    "results": "Results filing",
    "circular": "PIB/RBI circular",
}

DOC_TYPES = ("concall", "deck", "annual_report", "results", "circular")


# ---------------------------------------------------------------------------
# Text normalisation (the space in which spans are compared)
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Collapse every whitespace run to one space.

    Old and new chunks both map into this space when their spans are compared,
    because the old chunker stored whitespace-collapsed bodies.
    """
    return _WS.sub(" ", text or "").strip()


def join_pages(pages: Sequence[str]) -> str:
    """The single text a multi-page document is chunked over."""
    return "\n".join(pages or [])


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """A structural block of the document text (offsets into that text)."""

    start: int
    end: int
    kind: str  # heading | table | text
    level: int = 0
    page: int = 0


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    symbol: str
    isin: str
    doc_type: str
    section: str
    speaker: str
    unit_kind: str
    header: str
    body: str
    char_len: int
    published_date: str
    page_from: int
    page_to: int
    span_start: int
    span_end: int

    def as_row(self) -> tuple:
        return (
            self.doc_id, self.symbol, self.isin, self.doc_type, self.section,
            self.speaker, self.unit_kind, self.header, self.body, self.char_len,
            self.published_date, self.page_from, self.page_to,
            self.span_start, self.span_end,
        )


@dataclass
class _Unit:
    start: int
    end: int
    kind: str
    section: str = ""
    speaker: str = ""
    level: int = 0
    group: str = ""


def make_header(symbol: str, doc_type: str, fiscal_period: str, section: str,
                speaker: str, filed: str, title: str = "") -> str:
    """``<SYMBOL> · <doc type or title> · <fiscal period> · <section/speaker> · filed <date>``."""
    where = section or speaker or "-"
    label = (title or "").strip()[:90] or DOC_LABELS.get(doc_type, doc_type or "document")
    return " · ".join([
        (symbol or "DOCUMENT").upper(),
        label,
        fiscal_period or "-",
        where,
        f"filed {filed}" if filed else "filed date unknown",
    ])


# ---------------------------------------------------------------------------
# Size handling
# ---------------------------------------------------------------------------

_PARA_BOUNDARY = re.compile(r"\n[ \t]*\n")
_LINE_BOUNDARY = re.compile(r"\n")
_SENT_BOUNDARY = re.compile(r"(?<=[.!?])[\"'\u2019)\]]?[ \t]+")


def _inside(pos: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(s < pos < e for s, e in spans)


def _best_cut(text: str, pos: int, limit: int, protected: Sequence[tuple[int, int]]) -> int:
    lo = pos + max(1, int((limit - pos) * 0.55))
    table_ends: list[int] = []
    for pattern in (_PARA_BOUNDARY, _LINE_BOUNDARY, _SENT_BOUNDARY):
        ends = [m.end() for m in pattern.finditer(text, lo, limit) if m.end() > pos]
        if not ends:
            continue
        clean = [e for e in ends if not _inside(e, protected)]
        if clean:
            return max(clean)
        table_ends = ends if pattern is _LINE_BOUNDARY else table_ends
    if table_ends:
        # The table alone is longer than the limit: cut at a row boundary.
        return max(table_ends)
    match = _SENT_BOUNDARY.search(text, limit, min(len(text), limit + int((limit - pos) * 0.3)))
    if match and not _inside(match.end(), protected):
        return match.end()
    # ponytail: a single sentence (usually a rendered table row) over MAX_CHARS
    # has no boundary; hard cut and accept it. Raise MAX_CHARS for such docs.
    return limit


def _is_clean_end(text: str, cut: int, end: int) -> bool:
    """True when ``cut`` ends a sentence or a paragraph (not a wrapped line)."""
    if cut >= end:
        return True
    if text[cut - 1] in ".!?\"'\u2019)]":
        return True
    return text[cut - 1] == "\n" and cut >= 2 and text[cut - 2] == "\n"


def _split_long(text: str, unit: _Unit, protected: Sequence[tuple[int, int]]) -> list[_Unit]:
    """Split an oversize unit into near-equal pieces.

    Greedy ``pos + MAX_CHARS`` cuts leave a tiny tail on the last piece (an AR
    note of 6,100 chars produced a 5,900-char chunk plus a 100-char fragment
    that no neighbour could absorb).  Dividing the length first keeps every
    piece near ``length / n``, so the tail is no smaller than the others.

    When the only boundary inside the window is the hard limit (PyMuPDF text
    has few line breaks inside a note), the cut extends forward to the next
    sentence end within +15% of ``MAX_CHARS`` instead of cutting a sentence.
    """
    length = unit.end - unit.start
    if length <= MAX_CHARS:
        return [unit]
    count = max(2, math.ceil(length / MAX_CHARS))
    target = length / count
    ceiling = int(MAX_CHARS * 1.15)
    pieces: list[_Unit] = []
    pos = unit.start
    for index in range(1, count):
        want = unit.start + int(round(target * index))
        # Stay under the hard ceiling: the boundary window may claim more than
        # MAX_CHARS otherwise (a 10.5k-char note split into two 5.3k targets
        # still produced a 6.8k piece when the window was target + 30%).
        limit = min(unit.end, want + int(target * 0.2), pos + MAX_CHARS)
        cut = _best_cut(text, pos, max(pos + 1, limit), protected)
        if cut <= pos or cut >= unit.end:
            cut = min(unit.end - 1, max(pos + 1, want))
        if not _is_clean_end(text, cut, unit.end) and cut <= pos + MAX_CHARS:
            # The window found no sentence/line end: take the next sentence end
            # up to MAX_CHARS + 15% rather than cutting mid-sentence.
            match = _SENT_BOUNDARY.search(text, cut, min(unit.end, pos + ceiling))
            if match and not _inside(match.end(), protected):
                cut = match.end()
        cut = min(cut, pos + ceiling, unit.end)
        pieces.append(replace(unit, start=pos, end=cut,
                              kind=unit.kind if not pieces else f"{unit.kind}_cont"))
        pos = cut
        if pos >= unit.end:
            break
    if pos < unit.end:
        pieces.append(replace(unit, start=pos, end=unit.end,
                              kind=unit.kind if not pieces else f"{unit.kind}_cont"))
    return pieces


def _split_oversize(text: str, units: Iterable[_Unit],
                    protected: Sequence[tuple[int, int]] = ()) -> list[_Unit]:
    out: list[_Unit] = []
    for unit in units:
        out.extend(_split_long(text, unit, protected))
    return out


def _same_group(unit: _Unit, other: _Unit) -> bool:
    return (unit.group or unit.section or "") == (other.group or other.section or "")


def _merge_small(units: list[_Unit], min_chars: int = MIN_CHARS) -> list[_Unit]:
    """Merge a unit under ``min_chars`` with a neighbour.

    Forward first (a stub heading belongs to what follows), then backwards,
    then whatever is still small is folded into *any* neighbour that fits.
    The last pass is what kills page numbers, CIN lines and signature stubs:
    no chunk under ``min_chars`` survives unless the whole document is that
    small or its neighbours are already at ``MAX_CHARS``.
    """
    forward: list[_Unit] = []
    i = 0
    while i < len(units):
        unit = units[i]
        if unit.kind == "front_matter" and i + 1 < len(units) \
                and units[i + 1].end - unit.start <= MAX_CHARS:
            forward.append(replace(units[i + 1], start=unit.start))
            i += 2
            continue
        if (unit.end - unit.start) < min_chars and i + 1 < len(units):
            nxt = units[i + 1]
            if _same_group(unit, nxt) and nxt.end - unit.start <= MAX_CHARS:
                forward.append(replace(nxt, start=unit.start))
                i += 2
                continue
        forward.append(unit)
        i += 1

    out: list[_Unit] = []
    for unit in forward:
        if out and (unit.end - unit.start) < min_chars \
                and _same_group(unit, out[-1]) and unit.end - out[-1].start <= MAX_CHARS:
            out[-1] = replace(out[-1], end=unit.end)
            continue
        out.append(unit)

    # Furniture (page numbers, CIN lines, signature stubs, one-line notes) has
    # no retrieval value alone; semantic units (a Q&A pair, a clause, a speaker
    # turn) are kept even when short.
    def _furniture(unit: _Unit) -> bool:
        return unit.kind.startswith(
            ("note", "table", "paragraph", "front_matter", "preamble", "slide"))

    floor: list[_Unit] = []
    for unit in out:
        if floor and (unit.end - unit.start) < min_chars and _furniture(unit) \
                and unit.end - floor[-1].start <= MAX_CHARS:
            floor[-1] = replace(floor[-1], end=unit.end)
            continue
        floor.append(unit)

    if len(floor) > 1 and (floor[0].end - floor[0].start) < min_chars \
            and _furniture(floor[0]) and floor[1].end - floor[0].start <= MAX_CHARS:
        floor[1] = replace(floor[1], start=floor[0].start)
        floor.pop(0)
    return floor


def _trim(text: str, unit: _Unit) -> _Unit:
    start, end = unit.start, unit.end
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return replace(unit, start=start, end=end)


def _finalise(text: str, units: Iterable[_Unit], meta: dict,
              protected: Sequence[tuple[int, int]] = (),
              page_at=None, min_chars: int = MIN_CHARS) -> list[Chunk]:
    units = [_trim(text, u) for u in units]
    units = [u for u in units if u.end > u.start]
    units = _merge_small(_split_oversize(text, units, protected), min_chars)
    chunks: list[Chunk] = []
    for unit in units:
        body = text[unit.start:unit.end]
        section = unit.section
        chunk = Chunk(
            doc_id=str(meta.get("doc_id", "")),
            symbol=(meta.get("symbol") or "").upper(),
            isin=meta.get("isin") or "",
            doc_type=meta.get("doc_type") or "",
            section=section,
            speaker=unit.speaker,
            unit_kind=unit.kind,
            header=make_header(meta.get("symbol", ""), meta.get("doc_type", ""),
                               meta.get("fiscal_period", ""), section,
                               unit.speaker, meta.get("published_date", ""),
                               meta.get("title", "")),
            body=body,
            char_len=len(body),
            published_date=meta.get("published_date") or "",
            page_from=page_at(unit.start) if page_at else 0,
            page_to=page_at(max(unit.start, unit.end - 1)) if page_at else 0,
            span_start=unit.start,
            span_end=unit.end,
        )
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Concall transcripts
# ---------------------------------------------------------------------------

_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\u20b9\"'])")


def sentence_units(text: str, target: int = 1200, kind: str = "paragraph",
                   section: str = "") -> list[_Unit]:
    """Group prose into roughly ``target``-char units on sentence boundaries.

    Used where a document has no structure left to follow: a release whose
    paragraphs were collapsed, or a deck whose page text was never stored.
    """
    units: list[_Unit] = []
    start = 0
    for match in _SENT_END.finditer(text):
        if match.end() - start >= target:
            units.append(_Unit(start, match.end(), kind, section))
            start = match.end()
    if start < len(text):
        units.append(_Unit(start, len(text), kind, section))
    return units


def sentence_groups(text: str, target: int = 1000) -> list[str]:
    """Page-sized string groups for documents chunked page-by-page."""
    return [text[u.start:u.end] for u in sentence_units(text, target)]


_SPEAKER_STOP = {
    "note", "subject", "date", "scrip", "symbol", "code", "website", "email",
    "tel", "fax", "cin", "enclosed", "thanking", "regards", "dear", "sir",
    "madam", "attention", "ref", "reference", "sub", "re", "cc", "to", "from",
    "by", "title", "source", "page", "q", "a", "q&a", "question", "answer",
    "prepared", "called", "shown", "per", "as", "if", "on", "in", "at",
}
_SPEAKER_ROLE = re.compile(
    r"^(moderator|operator|analyst( \d+)?|participant( \d+)?|questioner|"
    r"management|investor relations|chief financial officer|managing director)$")
_NAME_TOKEN = r"(?:(?:mr|mrs|ms|dr|prof|shri|smt)\.|[A-Za-z][A-Za-z'\-]*)"
_SPEAKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + _NAME_TOKEN + r"(?:[ \t]+" + _NAME_TOKEN + r"){0,3}"
    r"(?:[ \t]+\d{1,2})?)"          # "Analyst 1:", "Participant 2:" (role + number)
    r"[ \t]*:[ \t]+", re.I)


def speaker_turns(text: str) -> list[tuple[str, int, int]]:
    """``(speaker, start, end)`` for each detected speaker turn.

    A name is kept when it repeats, when it is a known call role, or when the
    text after its colon holds a question mark before the next candidate
    marker -- the last rule is what captures an analyst who speaks once.
    ``subject :`` / ``note :`` stay out through the stop list.
    """
    hits: dict[str, list[tuple[int, int]]] = {}
    ordered: list[tuple[int, int, str]] = []
    for m in _SPEAKER_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip().strip(".").lower()
        if len(name) < 3:
            continue
        tokens = name.split()
        if any(tok.strip(".") in _SPEAKER_STOP for tok in tokens):
            continue
        if len(tokens) < 2 and not _SPEAKER_ROLE.match(name):
            continue
        hits.setdefault(name, []).append((m.start(1), m.end(1)))
        ordered.append((m.start(1), m.end(), name))

    asked = set()
    for i, (_, end, name) in enumerate(ordered):
        next_start = ordered[i + 1][0] if i + 1 < len(ordered) else len(text)
        if "?" in text[end:min(next_start, end + 1200)]:
            asked.add(name)

    keep = {k: v for k, v in hits.items()
            if len(v) >= 2 or _SPEAKER_ROLE.match(k) or k in asked}
    marks = sorted((start, name) for name, spans in keep.items() for start, _ in spans)
    turns: list[tuple[str, int, int]] = []
    for i, (start, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        turns.append((name, start, end))
    return turns


def _managers(turns: Sequence[tuple[str, int, int]]) -> set[str]:
    """Who is management: the speakers carrying most of the words.

    Turn counts are a bad signal -- a busy analyst takes six turns too -- while
    word share separates the two sides of the call reliably.
    """
    weight: dict[str, int] = {}
    for name, start, end in turns:
        weight[name] = weight.get(name, 0) + (end - start)
    total = sum(weight.values()) or 1
    managers: set[str] = set()
    covered = 0
    for name, n in sorted(weight.items(), key=lambda kv: (-kv[1], kv[0])):
        managers.add(name)
        covered += n
        if covered >= 0.5 * total:
            break
    return managers


def _is_question(name: str, body: str, managers: set[str]) -> bool:
    """A turn is a question when it ends on a question mark and is not
    management's.  ``contains ? somewhere`` is far too loose: managers close
    answers with "...right?" and each such hit split a Q&A pair."""
    if name in managers or len(body) > 2500:
        return False
    return body.rstrip().rstrip("\"')]").endswith("?")


def _question_tail_start(body: str, qpos: int) -> int | None:
    """Offset of the trailing question inside ``body`` (None when answered)."""
    if len(body) - qpos > 120:
        return None
    window_start = max(0, qpos - 800)
    ends = [m.end() for m in _SENT_BOUNDARY.finditer(body, window_start, qpos)]
    if not ends:
        return None
    start = ends[-1]
    for end in reversed(ends[:-1]):
        if body[max(0, end - 2):end].strip().endswith("?"):
            start = end
        else:
            break
    return start if qpos - start <= 800 else None


def _hoist_questions(text: str, units: list[_Unit]) -> list[_Unit]:
    """Move a trailing analyst question into the next unit.

    An analyst whose name is never repeated is not detected as a speaker, so
    their question lands at the end of the previous answer's unit.  When a unit
    ends on a question mark with no answer after it, the boundary is in the
    wrong place: shift it so question and answer stay in one chunk.
    """
    for i in range(len(units) - 1):
        current, following = units[i], units[i + 1]
        body = text[current.start:current.end]
        qpos = body.rfind("?")
        if qpos < 0:
            continue
        start = _question_tail_start(body, qpos)
        if start is None:
            continue
        new_start = current.start + start
        if new_start - current.start < 40 or new_start >= following.start:
            continue
        current.end = new_start
        following.start = new_start
        if following.kind == "turn":
            following.kind = "qa_pair"
            following.section = "Q&A"
    return units


def _split_span(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
    """Cut ``[start, end)`` into pieces of at most ~``limit`` chars."""
    pieces: list[tuple[int, int]] = []
    pos = start
    while end - pos > limit:
        cut = _best_cut(text, pos, pos + limit, ())
        cut = min(max(cut, pos + 1), end)
        pieces.append((pos, cut))
        pos = cut
    pieces.append((pos, end))
    return pieces


def _cap_qa(text: str, units: list[_Unit], max_chars: int) -> list[_Unit]:
    """Split an oversize Q&A unit at speaker turns, then at sentences.

    Every continuation repeats the question in its section header, so a piece
    that starts mid-answer is still retrievable from the question's wording.
    Unique groups keep ``_merge_small`` from stitching the pieces back together.
    """
    out: list[_Unit] = []
    for unit in units:
        if unit.kind != "qa_pair" or unit.end - unit.start <= max_chars:
            out.append(unit)
            continue
        turns = speaker_turns(text[unit.start:unit.end])
        segments = [(unit.start + start, unit.start + end) for _, start, end in turns]
        if not segments:
            segments = [(unit.start, unit.end)]
        question = text[segments[0][0]:segments[0][1]].strip()
        if len(segments) == 1:
            question = question[:160]
        question = re.sub(r"^[^:]{1,80}:\s*", "", question)

        pieces: list[tuple[int, int]] = []
        current: tuple[int, int] | None = None
        for start, end in segments:
            if end - start > max_chars:
                if current:
                    pieces.append(current)
                    current = None
                pieces.extend(_split_span(text, start, end, max_chars))
                continue
            if current is None:
                current = (start, end)
            elif end - current[0] <= max_chars:
                current = (current[0], end)
            else:
                pieces.append(current)
                current = (start, end)
        if current:
            pieces.append(current)

        for index, (start, end) in enumerate(pieces):
            speaker = next((name for name, s, e in turns
                            if s <= start - unit.start < e), unit.speaker)
            if index == 0:
                out.append(replace(unit, start=start, end=end, speaker=speaker,
                                   group=f"{unit.group or 'Q&A'}#0"))
            else:
                out.append(replace(unit, start=start, end=end, speaker=speaker,
                                   section=f"Q&A (cont.) · Q: {normalise(question)[:140]}",
                                   group=f"{unit.group or 'Q&A'}#{index}"))
    return out


def chunk_concall(text: str, meta: dict | None = None,
                  qa_max_chars: int | None = QA_MAX_CHARS) -> list[Chunk]:
    meta = dict(meta or {})
    meta.setdefault("doc_type", "concall")
    turns = speaker_turns(text)
    if not turns:
        return _finalise(text, [_Unit(0, len(text), "paragraph", "Transcript")], meta)

    managers = _managers(turns)
    units: list[_Unit] = []
    if turns[0][1] > 0:
        units.append(_Unit(0, turns[0][1], "front_matter", "Header"))

    first_q = next((i for i, (name, s, e) in enumerate(turns)
                    if _is_question(name, text[s:e], managers)), len(turns))

    # Opening remarks: consecutive turns of one speaker before the first question.
    run: _Unit | None = None
    for name, start, end in turns[:first_q]:
        if run is not None and run.speaker == name and end - run.start <= MAX_CHARS:
            run.end = end
        else:
            if run is not None:
                units.append(run)
            run = _Unit(start, end, "opening_remark", "Opening remarks", name)
    if run is not None:
        units.append(run)

    i = first_q
    while i < len(turns):
        name, start, end = turns[i]
        if _is_question(name, text[start:end], managers):
            j = i + 1
            while j < len(turns) and not _is_question(turns[j][0], text[turns[j][1]:turns[j][2]], managers):
                j += 1
            answer = turns[j - 1] if j > i + 1 else turns[i]
            units.append(_Unit(start, answer[2], "qa_pair", "Q&A", name))
            i = j
        else:
            units.append(_Unit(start, end, "turn", "Discussion", name))
            i += 1
    units = _hoist_questions(text, units)
    if qa_max_chars:
        units = _cap_qa(text, units, qa_max_chars)
    return _finalise(text, units, meta)


# ---------------------------------------------------------------------------
# Investor decks
# ---------------------------------------------------------------------------


def _page_spans(pages: Sequence[str]) -> list[tuple[int, int, int]]:
    spans: list[tuple[int, int, int]] = []
    pos = 0
    for i, page in enumerate(pages):
        spans.append((pos, pos + len(page), i + 1))
        pos += len(page) + 1  # "\n" separator
    return spans


def _page_lookup(spans: Sequence[tuple[int, int, int]]):
    def page_at(pos: int) -> int:
        for start, end, page in spans:
            if start <= pos <= end:
                return page
        return spans[-1][2] if spans else 0
    return page_at


def _slide_title(page: str) -> str:
    for line in (page or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) >= 3 and sum(ch.isalpha() for ch in line) >= 3:
            return line[:80]
    return ""


DECK_MIN_CHARS = 250
_DECK_DIVIDER_MAX = 180
_DECK_NOT_A_SECTION = {
    "thank you", "thank you.", "questions", "q&a", "question & answer",
    "disclaimer", "safe harbour", "safe harbor", "agenda",
}


def _is_section_divider(page: str) -> bool:
    """A divider slide: a short label with no table of numbers under it."""
    body = normalise(page)
    if not body or len(body) > _DECK_DIVIDER_MAX:
        return False
    if body.lower().strip(" .:-") in _DECK_NOT_A_SECTION:
        return False
    if len(_NUMERIC.findall(body)) > 1:
        return False
    return sum(ch.isalpha() for ch in body) >= 8


def chunk_deck(page_texts: Sequence[str], meta: dict | None = None) -> list[Chunk]:
    """One slide per chunk, titled by its nearest section-divider slide.

    A slide under ``DECK_MIN_CHARS`` of body merges into the next slide in the
    same section: a one-line "Financials" divider or a "Thank you" slide is not
    a retrieval unit on its own.  The deck title from metadata heads every
    slide chunk, so a slide with no company name in its own text is still
    findable.
    """
    meta = dict(meta or {})
    meta.setdefault("doc_type", "deck")
    pages = list(page_texts or [])
    if not pages:
        return []
    text = join_pages(pages)
    spans = _page_spans(pages)
    dividers = [_is_section_divider(page) for page in pages]
    sectioned = any(dividers)
    units: list[_Unit] = []
    section = ""
    for (start, end, page), page_text, is_divider in zip(spans, pages, dividers):
        if not page_text.strip():
            continue
        slide = _slide_title(page_text) or f"Slide {page}"
        if is_divider:
            section = slide
        if sectioned:
            label, group = section or slide, section or slide
        else:
            # No divider to group by: every slide is its own section, but a
            # short one may still merge forward into its neighbour.
            label, group = slide, ""
        units.append(_Unit(start, end, "slide", label, group=group))
    return _finalise(text, units, meta, page_at=_page_lookup(spans),
                     min_chars=DECK_MIN_CHARS)


# ---------------------------------------------------------------------------
# Annual reports / results notes
# ---------------------------------------------------------------------------

_NOTE_HEADING = re.compile(
    r"^(?:note\s+\d{1,3}[a-z]?\b[^.]{0,80}|schedule\s+[ivxlc\d]+\b[^.]{0,80}|"
    r"notes?\s+to\s+(?:the\s+)?(?:consolidated\s+|standalone\s+)?financial\s+statements"
    r"[^.]{0,40})$", re.I)
_NUMBERED_HEADING = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}\s+[A-Z][^.]{3,80}$")
#: A bare date line ("31 March 2025") is a table column header, not a heading;
#: treating it as one split borrowings notes mid-table in the hand check.
_DATE_HEADING = re.compile(
    r"^\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}$", re.I)
_NUMERIC = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")


def _row_density(line: str) -> int:
    return len(_NUMERIC.findall(line))


def _is_table_row(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 400:
        return False
    if s.count("|") >= 2 or s.count("\t") >= 2:
        return True
    return _row_density(s) >= 3


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if _DATE_HEADING.match(s):
        return False
    if _NOTE_HEADING.match(s) or _NUMBERED_HEADING.match(s):
        return True
    if s.endswith((".", ",", ";", ":")):
        return False
    letters = sum(ch.isalpha() for ch in s)
    if letters < 5 or len(s.split()) < 2:
        return False
    return sum(ch.isupper() for ch in s) / letters >= 0.75


def blocks_from_text(text: str) -> tuple[list[Block], list[tuple[int, int]]]:
    """Heading / table / text blocks from plain text (the no-PDF fallback).

    Returns ``(blocks, table_spans)``; table spans are protected from cuts.
    """
    lines = []
    pos = 0
    for raw in (text or "").split("\n"):
        lines.append((pos, pos + len(raw), raw))
        pos += len(raw) + 1

    blocks: list[Block] = []
    tables: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        start, end, raw = lines[i]
        if _is_heading(raw):
            blocks.append(Block(start, end, "heading", 1))
            i += 1
            continue
        if _is_table_row(raw):
            j = i
            while j < len(lines) and _is_table_row(lines[j][2]):
                j += 1
            if j - i >= 2:
                t_start, t_end = lines[i][0], lines[j - 1][1]
                blocks.append(Block(t_start, t_end, "table"))
                tables.append((t_start, t_end))
                i = j
                continue
        blocks.append(Block(start, end, "text"))
        i += 1
    return blocks, tables


def chunk_annual_report(page_texts: Sequence[str], meta: dict | None = None,
                        blocks: Sequence[Block] | None = None) -> list[Chunk]:
    """One chunk per note / schedule; tables inside a note stay whole."""
    meta = dict(meta or {})
    meta.setdefault("doc_type", "annual_report")
    pages = list(page_texts or [])
    if not pages:
        return []
    text = join_pages(pages)
    spans = _page_spans(pages)
    page_at = _page_lookup(spans)
    if blocks is None:
        blocks, tables = blocks_from_text(text)
    else:
        blocks = list(blocks)
        tables = [(b.start, b.end) for b in blocks if b.kind == "table"]

    units: list[_Unit] = []
    start: int | None = None
    kind = "note"
    parts: list[str] = []
    has_body = False
    for block in blocks:
        if block.kind == "heading":
            label = re.sub(r"\s+", " ", text[block.start:block.end]).strip()[:80]
            if start is not None and not has_body:
                # A heading with no body yet is a section path, not a chunk.
                parts.append(label)
                continue
            if start is not None:
                units.append(_Unit(start, block.start, kind, " > ".join(parts),
                                   group=parts[0]))
            parts = [label]
            start, kind, has_body = block.start, "note", False
            continue
        if start is None:
            start = block.start
            kind = "table" if block.kind == "table" else "paragraph"
            parts = parts or ["Body"]
        has_body = True
    if start is not None:
        units.append(_Unit(start, len(text), kind, " > ".join(parts), group=parts[0]))
    return _finalise(text, units, meta, protected=tables, page_at=page_at)


# ---------------------------------------------------------------------------
# PIB / RBI / circulars
# ---------------------------------------------------------------------------

_CLAUSE_RE = re.compile(r"(?:(?<=\s)|^)(\d{1,2}(?:\.\d{1,3}){0,3})[.)]?\s+(?=[A-Z(\u20b9\"'])", re.M)


def _clause_marks(text: str) -> list[tuple[int, str, int]]:
    """Clause markers, keeping only a plausible increasing top-level run.

    The run guard (top level +1..+3) is what keeps prose numbers such as
    ``26 The`` or an amount out of the marker list.
    """
    marks: list[tuple[int, str, int]] = []
    last_top = 0
    for m in _CLAUSE_RE.finditer(text):
        top = int(m.group(1).split(".")[0])
        if not marks and top > 12:
            continue
        if marks and not (1 <= top - last_top <= 3):
            continue
        marks.append((m.start(1), m.group(1), m.end()))
        last_top = top
    return marks


def chunk_circular(text: str, meta: dict | None = None) -> list[Chunk]:
    meta = dict(meta or {})
    meta.setdefault("doc_type", "circular")
    marks = _clause_marks(text)
    units: list[_Unit] = []
    if len(marks) < 3:
        # Unnumbered release: sentence groups are the only structure left.
        return _finalise(text, sentence_units(text, 1200, "paragraph", "Release"), meta)

    if marks[0][0] > 0:
        units.append(_Unit(0, marks[0][0], "preamble", "Preamble"))
    for i, (start, number, body_at) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        clause = re.sub(r"\s+", " ", text[body_at:end])[:70].strip()
        units.append(_Unit(start, end, "clause", f"Clause {number} · {clause}".strip()))
    return _finalise(text, units, meta)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def chunk_document(meta: dict, pages: Sequence[str] | None = None,
                   blocks: Sequence[Block] | None = None) -> list[Chunk]:
    """Chunk one document by its type.

    ``pages`` are the document's page texts in order (a single-element list for
    text-only sources); ``blocks`` are pre-computed structural blocks over
    ``join_pages(pages)``.
    """
    meta = dict(meta or {})
    doc_type = meta.get("doc_type") or "annual_report"
    pages = list(pages or [])
    text = join_pages(pages)
    if doc_type == "concall":
        return chunk_concall(text, meta, qa_max_chars=meta.get("qa_max_chars", QA_MAX_CHARS))
    if doc_type == "deck":
        return chunk_deck(pages, meta)
    if doc_type == "circular":
        return chunk_circular(text, meta)
    return chunk_annual_report(pages, meta, blocks)





