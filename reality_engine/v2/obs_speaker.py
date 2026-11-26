"""T-241: speaker attribution post-pass for hy4 transcript observations.

Reads a finished ``observations.py`` SQLite database and the per-company
``doc_page`` stores, writes a copy via SQLite's backup API, adds
``observation.speaker_role``, and populates ``speaker`` (when empty) and
``speaker_role`` on transcript observations (``doc_key`` containing
``concall_transcript`` or ``transcript``).

Attribution rule
----------------
For each transcript observation with an empty ``speaker``:
1. Locate the observation on ``doc_page.text`` for ``(doc_key, page)`` using
   ``value_text`` (prefixed with ``printed_label`` when both exist to avoid
   short-number collisions such as ``2`` matching ``Page 2 of 20``), else
   ``printed_label``, else the first 40 characters of ``statement``.
2. Take the nearest speaker turn label before that character offset on the
   same page (``Name:`` at line start or after a sentence end; names are 1-5
   capitalised words including initials/dots, plus ``Moderator``/``Management``/
   ``Operator``, and ``Name - Designation:`` lines; running headers such as
   ``Company Name ... Page 3 of 24`` and conversational starters such as
   ``Sir,`` or ``Thank you.`` are ignored).
3. If no turn precedes the match on that page, carry forward the last spoken
   turn from the preceding page.
4. If the text is not found on the page (or no turn exists on this or prior
   pages), leave ``speaker`` empty (never guess).

Speaker role rule (``speaker_role``)
------------------------------------
Every transcript observation with a non-empty ``speaker`` is classified into:
- ``'moderator'``: speaker is ``Moderator`` / ``Operator`` / ``Coordinator`` /
  ``Host``, or matches the moderator listed in pages 1-3 (when not in the
  management list).
- ``'management'``: speaker is ``Management`` / ``Management Team``, has a
  management designation hint on the turn label, appears in the management
  participant list of pages 1-3, or is answering a question (preceding turn
  ended with ``?`` or contained a question prompt and the speaker is not in
  the analyst list).
- ``'analyst'``: speaker was introduced by the moderator (e.g.
  ``"next question is from <name> from <firm>"``), has an explicit
  ``Participant``/``Analyst`` hint or external-participant listing, or the
  turn itself is a question.
- ``'unknown'``: otherwise (empty when ``speaker`` itself is empty).

T-242 statement pass (used by the observations read path and ``--reparse``, not by ``run``)
-------------------------------------------------------------------------------------------
``attach_statement_speakers`` carries a statement's speaker across a page break, resolves a
company-name / first-name / initials label to one full management name, marks the row
unverified (``speaker_unresolved:``) or a referentless short reply (``no_referent:``), and fills
an empty ``question_context`` with the analyst's printed question (``preceding_question``).

T-242 surprise-audit rules (25 Nov 2026)
----------------------------------------
1. A document typed ``transcript`` is a call only when it prints at least 3 call turns
   (``Name:`` / ``Name - Designation:`` / a repeated or role speaker label) across its pages
   (``is_call_document``); every statement of a document without them is unverified
   (``not_a_call:``) and ``observations.transcript_pages`` skips the document.  A label that is a
   slide or table heading (all financial words, e.g. ``Profit After Tax``) or carries digits is
   never a speaker (``speaker_not_a_person:``).
2. A statement whose speaker is the moderator/operator is never a management statement
   (``speaker_moderator:``); it is unverified, not dropped.
3. A passage of at most 8 words with no figure and no named entity is dropped when it is only
   generic praise, a pointer to another speaker/question, or a sentence that refers back with no
   referent in ``question_context`` (``short_remark_reason``).
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from reality_engine.db.readonly import connect_ro

_TRANSCRIPT_KEY = ("concall_transcript", "transcript")

_HONORIFIC_RE = re.compile(r"^(?:Mr|Mrs|Ms|Dr|Shri|Smt|Prof|CA)\.?\s+", re.I)
_PARTICLES = {"de", "da", "del", "van", "von", "al", "bin", "singh"}

_ROLE_WORDS = {"moderator", "management", "operator", "participant", "coordinator", "host"}
_MODERATOR_NAMES = {"moderator", "operator", "coordinator", "host"}

# Non-speaker labels that frequently appear before a colon on transcript cover
# pages, headers, or conversational prose.
_NON_SPEAKER_WORDS = {
    "a", "an", "and", "or", "the", "in", "on", "at", "for", "from", "with", "to", "of", "by",
    "as", "is", "was", "were", "are", "be", "been", "this", "that", "these", "those", "our",
    "we", "you", "your", "my", "his", "her", "it", "its", "some", "all", "any", "no", "not",
    "yes", "sir", "madam", "thank", "thanks", "please", "okay", "ok", "well", "now", "here",
    "there", "also", "just", "only", "very", "more", "most", "however", "moreover", "therefore",
    "additionally", "meanwhile", "further", "forward", "overall", "example", "follows", "kindly",
    "note", "notes", "disclaimer", "caution", "reminder", "sensitivity", "classification",
    "sub", "subject", "dear", "kind", "attention", "ref", "encl", "date", "time", "duration",
    "venue", "mode", "link", "status", "code", "scrip", "isin", "cin", "din", "pan", "gst",
    "gstin", "tan", "symbol", "series", "tel", "fax", "phone", "mobile", "contact", "email",
    "e-mail", "website", "address", "reg", "regd", "office", "department", "listing",
    "compliance", "exchange", "board", "registered", "corporate", "external", "participants",
    "participents", "attendees", "panelists", "coordinators", "analysts", "executives", "team",
    "company", "limited", "ltd", "pvt", "inc", "corp", "corporation", "llp", "securities",
    "advisors", "broking", "capital", "financial", "services", "industries", "equipments",
    "solutions", "technologies", "pharmaceuticals", "infraprojects", "enterprises",
    "holdings", "systems", "india", "bank", "utility", "utilities", "meeting", "audio",
    "video", "recording", "solar", "power", "energy", "infra", "infrastructure", "project",
    "projects", "product", "products", "customer", "customers", "capacity", "export",
    "exports", "import", "imports", "domestic", "international", "retail", "wholesale",
    "digital", "manufacturing", "plant", "plants", "facility", "facilities", "expansion",
    "strategy", "strategic", "execution", "operations", "operational", "financials",
    "valuation", "acquisition", "merger", "dividend", "equity", "shares", "shareholding",
    "promoter", "promoters", "warning", "agenda", "objective", "conclusion", "background",
    "introduction", "remarks", "closing", "opening", "line", "agriculture", "horticulture",
    "commercial", "residential", "industrial", "institutional", "consumer", "enterprise",
    "healthcare", "pharma", "automotive", "telecom", "banking", "insurance", "treasury",
    "page", "slide", "table", "chart", "figure", "annex", "annexure", "appendix",
    "key", "highlights", "summary", "overview", "update", "updates", "outlook", "guidance",
    "question", "questions", "answer", "answers", "session", "conference", "call",
    "earnings", "investor", "investors", "relations", "presentation", "transcript",
    "quarter", "fiscal", "annual", "total", "net", "gross", "revenue", "margin", "margins",
    "ebitda", "pat", "order", "book", "capex", "debt", "cash", "growth", "segment", "business",
    "performance", "demand", "numbers", "finportal", "dn", "e&oe", "cc",
    # T-242: section headings and discourse markers read as "Name:" labels on a prepared-remarks page
    "asset", "quality", "deposits", "mobility", "geographical", "diversification", "initiative", "agency",
    "supply", "government", "internally", "first", "second", "third", "firstly", "finally",
    "good", "morning", "afternoon", "evening", "ladies", "gentlemen", "so",
    "place", "location",
}

_PAGE_HEADER_LINE = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.I)

# Horizontal whitespace only inside a speaker label, never across newlines.
_WORD = r"(?:[A-Z][A-Za-z.'’\-]*|[A-Z]\.(?:[A-Z]\.)*)"
_HONORIFIC_OPT = r"(?:(?:Mr|Mrs|Ms|Dr|Shri|Smt|Prof|CA)\.?\s+)?"
_NAME_CORE = rf"{_HONORIFIC_OPT}{_WORD}(?:[ \t]+(?:{_WORD}|de|da|del|van|von|al|bin|singh)){{0,4}}"

# Colon turn at line start (with optional bullet) or after sentence end.
_COLON_TURN_RE = re.compile(
    rf"(?:^[ \t]*(?:[•−\-*][ \t]*)?|(?<=[.!?])[ \t]+)({_NAME_CORE})[ \t]*:",
    re.M,
)

# Designation turn at line start: "Mr. Hardeep Singh Ahluwalia - MD & CEO, Canara Bank:"
_DESIG_TURN_RE = re.compile(
    rf"^[ \t]*(?:[•−\-*][ \t]*)?({_NAME_CORE})[ \t]*[-–,][ \t]*([^\n:]{{2,65}})[ \t]*:",
    re.M,
)

# Standalone line without colon (used when a transcript omits colons or names a known participant).
_STANDALONE_LINE_RE = re.compile(
    rf"^[ \t]*({_NAME_CORE})[ \t]*$",
    re.M,
)

_PARTICIPANT_HEADER_AFTER = re.compile(
    r"^\s*(?:[•−\-*]\s*)?(?:MR|MRS|MS|DR|SHRI|SMT|PROF)\.?\s+[A-Z]",
)

_COVER_LETTER_RE = re.compile(
    r"\b(?:dear\s+(?:sirs?|madam|sir\s*/\s*madam)|s(?:crip|ecurity)\s+code|listing\s+(?:dept|department)|"
    r"compliance\s+(?:officer|department)|regulation\s+30|trading\s+symbol|bse\s+code|"
    r"sub(?:ject)?\.?\s*[:\-])",
    re.I,
)

_MGMT_SECTION_HEAD = re.compile(
    r"\b(?:management(?:\s+team|\s+participants|\s+attendees)?|"
    r"corporate\s+participants|company\s+participants|executives|panelists)\b",
    re.I,
)
_EXTERNAL_SECTION_HEAD = re.compile(
    r"\b(?:external\s+participants|active\s+q\s*&\s*a\s+particip[ae]nts|"
    r"analysts?|moderator|host|call\s+coordinator)\b",
    re.I,
)
_MGMT_ROLE_RE = re.compile(
    r"\b(?:managing\s+director|chief\s+executive|chief\s+financial|chief\s+operating|"
    r"chief\s+technology|executive\s+director|whole[- ]?time\s+director|joint\s+managing|"
    r"cmd|ceo|cfo|coo|cto|director|president|vice\s+president|chairman|chairperson|"
    r"company\s+secretary|investor\s+relations|head\s+of|general\s+manager|gm\b)\b",
    re.I,
)
_ANALYST_HINT_RE = re.compile(r"\b(?:participant|analyst)\b", re.I)

_ANALYST_INTRO_RE = re.compile(
    r"\b(?:first|next|last)?\s*question\s+(?:is\s+)?(?:comes\s+)?from\s+"
    r"(?:the\s+line\s+of\s+)?([A-Z][A-Za-z.'’\-]+(?:[ \t]+(?:[A-Z][A-Za-z.'’\-]+|de|da|van|von|singh)){0,3}?)"
    r"(?=[ \t]+(?:from|of|with|an|at)\b|[.,;:)\n]|$)"
    r"|\bfrom\s+the\s+line\s+of\s+"
    r"([A-Z][A-Za-z.'’\-]+(?:[ \t]+(?:[A-Z][A-Za-z.'’\-]+|de|da|van|von|singh)){0,3}?)"
    r"(?=[ \t]+(?:from|of|with|an|at)\b|[.,;:)\n]|$)",
    re.I,
)

_QUESTION_CUE_RE = re.compile(
    r"\?|\b(?:my\s+(?:first|second|next|last)?\s*question|can\s+you|could\s+you|"
    r"would\s+you|how\s+much|how\s+many|please\s+explain|wanted\s+to\s+understand|"
    r"join\s+back\s+in\s+the\s+queue|thank\s+you\s+for\s+(?:taking|the\s+opportunity))\b",
    re.I,
)


@dataclass(frozen=True)
class SpeakerTurn:
    """One speaker turn detected on a transcript page."""

    start: int
    end: int
    name: str
    role_hint: str = ""


@dataclass
class DocContext:
    """Document-level speaker metadata parsed from all pages of one transcript."""

    mgmt_names: list[str]
    analyst_names: list[str]
    moderator_names: list[str]
    allow_standalone: bool


def _strip_honorific(name: str) -> str:
    s = " ".join((name or "").split()).strip()
    while True:
        s2 = _HONORIFIC_RE.sub("", s, count=1).strip()
        if s2 == s:
            break
        s = s2
    return s


def _norm_name(name: str) -> str:
    s = _strip_honorific(name).lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    return " ".join(s.split())


def _name_matches_list(speaker: str, candidates: list[str], *, allow_single_token: bool = True) -> bool:
    norm = _norm_name(speaker)
    if not norm:
        return False
    tokens = norm.split()
    for cand in candidates:
        if not cand:
            continue
        if norm == cand:
            return True
        cand_tokens = cand.split()
        if len(tokens) >= 2 and len(cand_tokens) >= 2:
            if all(t in cand_tokens for t in tokens):
                return True
            if (
                SequenceMatcher(None, tokens[0], cand_tokens[0]).ratio() >= 0.85
                and SequenceMatcher(None, tokens[-1], cand_tokens[-1]).ratio() >= 0.85
            ):
                return True
        if allow_single_token and len(tokens) == 1 and len(tokens[0]) >= 4 and tokens[0] in cand_tokens:
            return True
    return False


# T-242 (25 Nov, surprise audit W): a slide or table heading read as "Name:" is not a speaker.  A label is a heading
# when at least one word is a financial term and every other word is a financial term or a heading stop word.
_FINANCIAL_TERMS = frozenset({
    "profit", "profits", "loss", "losses", "pbt", "pat", "ebit", "ebitda", "tax", "income", "expense",
    "expenses", "revenue", "revenues", "margin", "margins", "capex", "debt", "cash", "dividend", "eps",
    "turnover", "sales", "growth", "order", "orders", "book", "borrowings", "receivables", "payables",
    "inventory", "npa", "gnpa", "nnpa", "aum", "nim", "roa", "roe", "roce", "net", "gross", "total",
    "operations", "operating", "expenditure", "flow", "flows", "earnings", "interest", "taxes", "cost", "costs",
    "ratio", "ratios", "yield", "yields", "equity", "assets", "deposits", "advances",
})
_HEADING_STOP = frozenset({
    "after", "before", "from", "and", "or", "of", "the", "in", "on", "for", "to", "per", "at", "by",
    "vs", "statement", "statements", "sheet", "account", "accounts", "highlights", "summary",
    "overview", "performance", "update", "updates", "outlook", "guidance",
})
# Letter / metadata labels ("Date:", "Place:", "Location:") read as speakers on notice and deck pages.
_LABEL_FIELD_WORDS = frozenset({
    "date", "time", "place", "location", "venue", "mode", "link", "webcast", "event", "purpose",
    "details", "detail", "particulars", "agenda", "subject", "sub", "ref", "reference", "regarding",
    "participant", "participants", "dial-in", "dialin", "passcode", "access", "packet", "transcription",
})


def _is_heading_label(name: str) -> bool:
    """True when ``name`` is a slide/table heading ("Profit After Tax", "Cost-to-income ratio", "EPS") not a person."""
    toks = [t.strip(".:;,'’\"“”()").lower() for t in re.split(r"[\s\-–—/]+", name or "")]
    toks = [t for t in toks if t]
    return bool(toks) and any(t in _FINANCIAL_TERMS for t in toks) \
        and all(t in _FINANCIAL_TERMS or t in _HEADING_STOP for t in toks)


def is_person_speaker(speaker: str) -> bool:
    """T-242: a speaker label that can be a person: a person's short name, not a slide/table heading.

    A label may carry the designation after the name ("Mr. Alexander Gerding, Managing Director",
    "Mr. Sanjay Wadhwa - Chief Financial Officer, 360 ONE WAM Limited:"): the name before the first separator is what
    must be a person, and only that name is checked for digits (the company in the designation may hold one).  A
    slide or table heading is rejected whole.
    """
    s = " ".join((speaker or "").split()).strip().rstrip(":").strip()
    if not s or len(s) > 90 or _is_heading_label(s):
        return False
    head = _LABEL_SPLIT_RE.split(s, maxsplit=1)[0].strip()
    if not head or _is_heading_label(head) or any(ch.isdigit() for ch in head):
        return False
    toks = head.split()
    if not 1 <= len(toks) <= 5:
        return False
    return _norm_name(head) not in _LABEL_FIELD_WORDS


def call_label_lines(pages: Iterable[tuple[int, str]]) -> int:
    """T-242: how many call turns a document prints.

    A colon/designation turn (``Name:``, ``Name - Designation:``, ``Analyst:``) counts as extracted.  A name printed
    on its own line, with or without a dash/designation/parenthesised role and without a colon (``Vaidehi Sharma -
    Moderator``, ``SHIVANG BAGLA (HOST- EMKAY)``), counts only when it is a role word or the same name recurs: unique
    slide headings never add up to a call.  An auto-transcript timestamp before or after the name (``0:05 Ved
    Krishna:``, ``[1:33] Pranay Pasricha:``, ``Sachin Srivastava 0:10``) is metadata, not part of the speaker, and
    makes the line a label whichever side it sits on (PAKKA).

    Only the label part is checked for digits: "Ramesh Iyer: revenue grew 12%" is a turn, "Date: 27.09.2026" is not.
    """
    page_list = [(int(pg), str(txt or "")) for pg, txt in pages]
    strict = 0
    for pg, txt in page_list:
        for turn in extract_turns(txt, pg, allow_standalone=False):
            norm = _norm_name(turn.name)
            if norm in _CALL_ROLE_WORDS or 2 <= len(norm.split()) <= 5:
                strict += 1
    if strict >= 3:
        return strict
    strong = 0
    standalone: list[tuple[str, bool]] = []
    for _pg, txt in page_list:
        for line in txt.splitlines():
            got = _call_label_line(line)
            if got is None:
                continue
            norm, has_colon, timestamped = got
            role = norm in _CALL_ROLE_WORDS or bool(_CALL_ROLE_IN_LINE_RE.search(line))
            if has_colon or timestamped:
                if timestamped or role or len(norm.split()) >= 2:
                    strong += 1
            elif role or len(norm.split()) >= 2:
                standalone.append((norm, role))
    names = Counter(n for n, _role in standalone)
    return strict + strong + sum(1 for n, role in standalone if role or names[n] >= 2)


# T-242 (25 Nov, surprise audit J): a transcript label may carry an auto-transcript timestamp before or after the name.
_TS_PREFIX_RE = re.compile(r"^\[?\d{1,2}:\d{2}(?::\d{2})?\]?[ \t]+")
_TS_SUFFIX_RE = re.compile(r"[ \t]+\[?\d{1,2}:\d{2}(?::\d{2})?\]?[ \t]*$")
_LABEL_SPLIT_RE = re.compile(r"\s*[:–—]\s*|\s+-\s+|[(\[,]")
# Role labels are call turns too: "CS:", "CMD:", "Analyst:", "MD - Finance:".
_CALL_ROLE_WORDS = frozenset(_ROLE_WORDS | {"analyst", "analysts", "cs", "cmd", "md", "cfo", "ceo", "coo",
                                            "cto", "ed", "ir", "investor relations", "company secretary"})
_CALL_ROLE_IN_LINE_RE = re.compile(
    r"\b(?:moderator|operator|host|coordinator|participant|management|analyst|cs|cmd|md|cfo|ceo|coo|cto|ed|ir)\b",
    re.I)


def _call_label_line(line: str) -> tuple[str, bool, bool] | None:
    """(normalised label, printed with a colon, timestamped) for one call-turn line, else None."""
    s = re.sub(r"^[^0-9A-Za-z]+", "", line).strip()
    if not s:
        return None
    timestamped = False
    m = _TS_PREFIX_RE.match(s)
    if m:
        s, timestamped = s[m.end():].strip(), True
    m = _TS_SUFFIX_RE.search(s)
    if m:
        s, timestamped = s[:m.start()].strip(), True
    if not s:
        return None
    has_colon = ":" in s
    head = s.split(":", 1)[0] if has_colon else s
    if any(ch.isdigit() for ch in head):       # the label, never the speech after its colon, must be digit-free
        return None
    name = _LABEL_SPLIT_RE.split(head, maxsplit=1)[0].strip()
    if not name:
        return None
    cleaned = _is_valid_speaker_name(name, allow_all_caps_name=True)
    if cleaned:
        return _norm_name(cleaned), has_colon, timestamped
    role = _norm_name(name)
    return (role, has_colon, timestamped) if role in _CALL_ROLE_WORDS else None


def is_call_document(pages: Iterable[tuple[int, str]]) -> bool:
    """T-242: a transcript is a call only when it prints at least 3 call turns across its pages."""
    return call_label_lines(pages) >= 3


def _is_valid_speaker_name(
    raw_name: str,
    *,
    allow_all_caps_role: bool = True,
    allow_all_caps_name: bool = False,
) -> str | None:
    """Return cleaned speaker name if ``raw_name`` is a valid speaker label, else None."""
    cleaned = _strip_honorific(raw_name)
    if not cleaned or len(cleaned) > 60 or any(ch.isdigit() for ch in cleaned):
        return None
    if re.search(r"\bPage\s+\d+", cleaned, re.I) or "," in cleaned:
        return None
    if _is_heading_label(cleaned):
        return None
    tokens = cleaned.split()
    if not tokens or len(tokens) > 5:
        return None

    low_full = cleaned.lower()
    if low_full in _ROLE_WORDS:
        if cleaned.isupper() and not allow_all_caps_role:
            return None
        return cleaned.title() if cleaned.isupper() else cleaned

    if len(tokens) == 1:
        tok = tokens[0]
        bare = tok.strip(".").lower()
        if len(bare) < 3 or bare in _NON_SPEAKER_WORDS:
            return None
        if tok.isupper() and not allow_all_caps_name and len(tok) <= 6:
            return None
        if not tok[0].isupper():
            return None
        return cleaned.title() if (allow_all_caps_name and cleaned.isupper()) else cleaned

    if all(t.isupper() for t in tokens) and not allow_all_caps_name:
        return None

    for i, tok in enumerate(tokens):
        bare = tok.strip(".").lower()
        if bare in _NON_SPEAKER_WORDS:
            return None
        if i > 0 and bare in _PARTICLES:
            continue
        if not tok[0].isupper():
            return None
    return cleaned.title() if (allow_all_caps_name and cleaned.isupper()) else cleaned


def _is_participant_header(raw_name: str, after_text: str, page_num: int) -> bool:
    """True when ``MANAGEMENT:`` / ``MODERATOR:`` on pages 1-3 introduces a roster, not speech."""
    if page_num > 3:
        return False
    if raw_name.strip().upper() not in {"MANAGEMENT", "MODERATOR"}:
        return False
    return bool(_PARTICIPANT_HEADER_AFTER.match(after_text[:120]))


def extract_turns(
    page_text: str,
    page_num: int = 1,
    *,
    known_names: set[str] | None = None,
    allow_standalone: bool = False,
) -> list[SpeakerTurn]:
    """Return sorted speaker turns found on ``page_text``."""
    turns: list[SpeakerTurn] = []
    seen_spans: list[tuple[int, int]] = []

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= a or s >= b) for a, b in seen_spans)

    # 1. Designation turns at line start ("Mr. X - MD & CEO, Bank:")
    for m in _DESIG_TURN_RE.finditer(page_text):
        raw_name = m.group(1).strip()
        hint = m.group(2).strip()
        if (
            any(ch.isdigit() for ch in raw_name)
            or any(ch.isdigit() for ch in hint)   # T-242: "Sunday, September 27, 2026 at 11:30" is a date line
            or re.search(r"^\d|\b(?:Page\s+\d+|tel\.?|fax|phone|email|www)\b", hint, re.I)
        ):
            continue
        name = _is_valid_speaker_name(raw_name)
        if not name:
            continue
        turns.append(SpeakerTurn(m.start(), m.end(), name, hint))
        seen_spans.append((m.start(), m.end()))

    # 2. Standard colon turns ("Name:" or "Moderator:")
    for m in _COLON_TURN_RE.finditer(page_text):
        if _overlaps(m.start(), m.end()):
            continue
        raw_name = m.group(1).strip()
        if _is_participant_header(raw_name, page_text[m.end():m.end() + 120], page_num):
            continue
        name = _is_valid_speaker_name(raw_name)
        if not name:
            continue
        turns.append(SpeakerTurn(m.start(), m.end(), name))
        seen_spans.append((m.start(), m.end()))

    # 3. Standalone lines without colon (when transcript omits colons or matches a known participant)
    if page_num >= 2:
        norm_known = known_names or set()
        for m in _STANDALONE_LINE_RE.finditer(page_text):
            if _overlaps(m.start(), m.end()):
                continue
            raw_name = m.group(1).strip()
            name = _is_valid_speaker_name(raw_name, allow_all_caps_role=False)
            if not name:
                continue
            norm = _norm_name(name)
            is_known = norm in _ROLE_WORDS or norm in norm_known
            if not is_known:
                if not allow_standalone:
                    continue
                # Strict guard for unknown standalone lines: at least 2 words,
                # followed by spoken prose on the next non-empty line.
                if len(name.split()) < 2:
                    continue
            rest = page_text[m.end():m.end() + 200].lstrip("\r\n ")
            if not rest or len(rest.splitlines()[0].strip()) < 8:
                continue
            turns.append(SpeakerTurn(m.start(), m.end(), name))
            seen_spans.append((m.start(), m.end()))

    turns.sort(key=lambda t: t.start)
    return turns


def _extract_name_from_roster_line(line: str) -> str | None:
    s = re.sub(r"^(?:[•−\-*\d.)]+|o(?=\s))+\s*", "", line.strip()).strip()
    if not s:
        return None
    # Split on role dash or colon or comma
    head = re.split(r"\s*[-–:]\s*|,\s*", s, maxsplit=1)[0].strip()
    return _is_valid_speaker_name(head, allow_all_caps_role=False, allow_all_caps_name=True)


def _looks_like_roster_after(after: str) -> bool:
    if not after:
        return True
    return bool(
        re.match(r"^(?:[•−\-*]\s*)?(?:MR|MRS|MS|DR|SHRI|SMT|PROF)\.?\s+[A-Z]", after, re.I)
        or " - " in after
        or " – " in after
    )


def _next_nonempty(lines: list[str], idx: int) -> str:
    for j in range(idx + 1, len(lines)):
        if lines[j]:
            return lines[j]
    return ""


def build_doc_context(pages: list[tuple[int, str]]) -> DocContext:
    """Extract management/analyst/moderator rosters and turn style from a transcript's pages."""
    mgmt_names: list[str] = []
    analyst_names: list[str] = []
    moderator_names: list[str] = []

    transcript_started = False
    for pg, txt in sorted(pages, key=lambda x: x[0]):
        if pg == 1 and _COVER_LETTER_RE.search(txt or ""):
            continue            # T-242: a filing cover letter's "Reference:" line reads as a speaker and stops the roster
        if pg <= 3 and not transcript_started:
            lines = [ln.strip() for ln in (txt or "").splitlines()]
            section = ""
            for i, ln in enumerate(lines):
                if not ln:
                    continue
                if re.match(r"^(?:MODERATOR|HOST|CALL\s+COORDINATOR)\s*:", ln, re.I):
                    after = ln.split(":", 1)[1].strip()
                    nxt = _next_nonempty(lines, i) if not after else after
                    if not _looks_like_roster_after(nxt):
                        transcript_started = True
                        break
                    section = "moderator"
                    if after:
                        nm = _extract_name_from_roster_line(after)
                        if nm:
                            moderator_names.append(_norm_name(nm))
                    continue
                if _MGMT_SECTION_HEAD.search(ln) and len(ln) < 90:
                    if ":" in ln:
                        after = ln.split(":", 1)[1].strip()
                        nxt = _next_nonempty(lines, i) if not after else after
                        if not _looks_like_roster_after(nxt):
                            transcript_started = True
                            break
                        section = "management"
                        if after:
                            nm = _extract_name_from_roster_line(after)
                            if nm and _norm_name(nm) not in _ROLE_WORDS:
                                mgmt_names.append(_norm_name(nm))
                    else:
                        section = "management"
                    continue
                if _EXTERNAL_SECTION_HEAD.search(ln) and len(ln) < 90:
                    section = "external"
                    continue
                # Stop roster extraction once a spoken turn ("Name: prose...") begins
                if ":" in ln:
                    before_c, after_c = ln.split(":", 1)
                    after_s = after_c.strip()
                    nxt = _next_nonempty(lines, i) if not after_s else after_s
                    if nxt and not _looks_like_roster_after(nxt) and len(nxt) >= 15:
                        if _is_valid_speaker_name(before_c.strip()):
                            transcript_started = True
                            break

                if section == "management":
                    nm = _extract_name_from_roster_line(ln)
                    if nm and _norm_name(nm) not in _ROLE_WORDS:
                        mgmt_names.append(_norm_name(nm))
                elif section == "moderator":
                    nm = _extract_name_from_roster_line(ln)
                    if nm and _norm_name(nm) not in _ROLE_WORDS:
                        moderator_names.append(_norm_name(nm))
                elif section == "external":
                    nm = _extract_name_from_roster_line(ln)
                    if nm and _norm_name(nm) not in _ROLE_WORDS:
                        analyst_names.append(_norm_name(nm))
                elif _MGMT_ROLE_RE.search(ln) and len(ln) < 120:
                    nm = _extract_name_from_roster_line(ln)
                    if nm and _norm_name(nm) not in _ROLE_WORDS:
                        mgmt_names.append(_norm_name(nm))
                    elif i > 0:
                        prev_nm = _extract_name_from_roster_line(lines[i - 1])
                        if prev_nm and _norm_name(prev_nm) not in _ROLE_WORDS:
                            mgmt_names.append(_norm_name(prev_nm))

        for m in _ANALYST_INTRO_RE.finditer(txt or ""):
            raw = (m.group(1) or m.group(2) or "").strip()
            nm = _is_valid_speaker_name(raw, allow_all_caps_role=False)
            if nm:
                analyst_names.append(_norm_name(nm))

    colon_turns = sum(
        len(_COLON_TURN_RE.findall(txt or "")) + len(_DESIG_TURN_RE.findall(txt or ""))
        for pg, txt in pages if pg >= 3
    )
    allow_standalone = colon_turns < 3 and len(pages) >= 3
    return DocContext(
        mgmt_names=list(dict.fromkeys(mgmt_names)),
        analyst_names=list(dict.fromkeys(analyst_names)),
        moderator_names=list(dict.fromkeys(moderator_names)),
        allow_standalone=allow_standalone,
    )


def _flex_regex(text: str, *, digit_bounds: bool = False) -> re.Pattern[str] | None:
    s = (text or "").strip()
    if not s:
        return None
    parts = [re.escape(p) for p in s.split()]
    pat = r"\s+".join(parts)
    # Normalize curly vs straight quotes if present.  One substitution per quote char: chaining two .replace() calls
    # nested a class inside the first one ("['['’]]") and a statement holding "FY '26" then never matched (T-242).
    pat = re.sub(r"['\u2019]", "['\u2019]", pat)
    pat = re.sub(r'["\u201c\u201d]', '["\u201c\u201d]', pat)
    if digit_bounds:
        if s[0].isdigit():
            pat = r"(?<!\d)" + pat
        if s[-1].isdigit():
            pat = pat + r"(?!\d)"
    return re.compile(pat)


def _is_in_page_header(page_text: str, start: int) -> bool:
    line_start = page_text.rfind("\n", 0, start) + 1
    line_end = page_text.find("\n", start)
    if line_end == -1:
        line_end = len(page_text)
    line = page_text[line_start:line_end]
    return bool(_PAGE_HEADER_LINE.match(line))


def find_observation_pos(
    page_text: str,
    value_text: str,
    printed_label: str,
    statement: str,
) -> int | None:
    """Locate the observation snippet in ``page_text`` and return its start offset, or None."""
    if not page_text:
        return None
    vt = (value_text or "").strip()
    pl = (printed_label or "").strip()
    st = (statement or "").strip()

    # 1. Statement prefix when substantial (guidance / statement rows)
    if len(st) >= 12:
        pat = _flex_regex(st[:40])
        if pat:
            m = pat.search(page_text)
            if m:
                return m.start()

    # 2. printed_label + value_text together avoids short-number false matches
    if len(pl) >= 3 and vt:
        pl_pat = _flex_regex(pl)
        vt_pat = _flex_regex(vt, digit_bounds=True)
        if pl_pat and vt_pat:
            combo = re.compile(pl_pat.pattern + r"[^\n.!?]{0,25}?" + vt_pat.pattern)
            for m in combo.finditer(page_text):
                if not _is_in_page_header(page_text, m.start()):
                    return m.start()

    # 3. value_text alone (skip running "Page X of Y" headers)
    if vt:
        vt_pat = _flex_regex(vt, digit_bounds=True)
        if vt_pat:
            for m in vt_pat.finditer(page_text):
                if not _is_in_page_header(page_text, m.start()):
                    return m.start()
        # Fallback if currency prefix spacing differs (e.g. "INR 1,800" vs "INR1,800")
        vt_tight = re.sub(r"^(INR|Rs\.?|₹|\$)\s+", r"\1\\s*", re.escape(vt))
        if vt_tight != re.escape(vt):
            pat = re.compile(vt_tight.replace(r"\ ", r"\s+"))
            for m in pat.finditer(page_text):
                if not _is_in_page_header(page_text, m.start()):
                    return m.start()

    # 4. printed_label alone
    if len(pl) >= 3:
        pl_pat = _flex_regex(pl)
        if pl_pat:
            for m in pl_pat.finditer(page_text):
                if not _is_in_page_header(page_text, m.start()):
                    return m.start()

    # 5. Short statement fallback
    if st:
        pat = _flex_regex(st[:40])
        if pat:
            m = pat.search(page_text)
            if m:
                return m.start()

    return None


def classify_speaker_role(
    speaker: str,
    doc_ctx: DocContext,
    *,
    role_hint: str = "",
    turn_text: str = "",
    prev_turn_text: str = "",
    prev_speaker: str = "",
    inferred_roles: dict[str, str] | None = None,
) -> str:
    """Classify ``speaker`` into management, analyst, moderator, or unknown."""
    norm = _norm_name(speaker)
    if not norm:
        return ""

    if norm in _MODERATOR_NAMES or "moderator" in norm or "operator" in norm:
        return "moderator"

    if norm in {"management", "management team"}:
        return "management"
    if role_hint:
        if _ANALYST_HINT_RE.search(role_hint):
            return "analyst"
        if _MGMT_ROLE_RE.search(role_hint):
            return "management"

    if _name_matches_list(speaker, doc_ctx.mgmt_names):
        return "management"
    if _name_matches_list(speaker, doc_ctx.analyst_names):
        return "analyst"
    if _name_matches_list(speaker, doc_ctx.moderator_names, allow_single_token=False):
        return "moderator"

    prev_norm = _norm_name(prev_speaker)
    prev_is_mod = bool(prev_norm and (prev_norm in _MODERATOR_NAMES or "moderator" in prev_norm or "operator" in prev_norm))
    if prev_turn_text and not prev_is_mod and _QUESTION_CUE_RE.search(prev_turn_text.strip()[-300:]):
        return "management"
    if turn_text and _QUESTION_CUE_RE.search(turn_text):
        return "analyst"

    if inferred_roles and norm in inferred_roles:
        return inferred_roles[norm]
    return "unknown"


def attribute_document(
    pages: list[tuple[int, str]],
    rows: list[tuple[int, int, str, str, str, str]],
) -> dict[int, tuple[str, str]]:
    """Attribute speakers and roles for one transcript document.

    ``pages`` is ``[(page, text), ...]`` ordered by page ascending.
    ``rows`` is ``[(observation_id, page, value_text, printed_label, statement, existing_speaker), ...]``.
    Returns ``{observation_id: (speaker, speaker_role)}``.
    """
    doc_ctx = build_doc_context(pages)
    known_names = set(doc_ctx.mgmt_names) | set(doc_ctx.analyst_names) | set(doc_ctx.moderator_names)

    page_turns: dict[int, list[SpeakerTurn]] = {}
    page_texts: dict[int, str] = {}
    all_turns: list[tuple[int, SpeakerTurn, str, str, str]] = []  # (page, turn, turn_text, prev_turn_text, prev_speaker)
    prev_turn: SpeakerTurn | None = None
    prev_turn_text = ""

    for pg, txt in sorted(pages, key=lambda x: x[0]):
        txt = txt or ""
        page_texts[pg] = txt
        if pg == 1 and _COVER_LETTER_RE.search(txt):
            turns = []
        else:
            turns = extract_turns(txt, pg, known_names=known_names, allow_standalone=doc_ctx.allow_standalone)
        page_turns[pg] = turns
        for idx, t in enumerate(turns):
            end_pos = turns[idx + 1].start if idx + 1 < len(turns) else len(txt)
            tbody = txt[t.end:end_pos]
            all_turns.append((pg, t, tbody, prev_turn_text, prev_turn.name if prev_turn else ""))
            prev_turn = t
            prev_turn_text = tbody

    # Build doc-level inferred roles for turns that clearly ask or answer questions,
    # so follow-up turns by the same speaker inherit their role.
    inferred_roles: dict[str, str] = {}
    for _, t, tbody, pbody, pspeaker in all_turns:
        norm = _norm_name(t.name)
        if not norm or norm in inferred_roles:
            continue
        r = classify_speaker_role(
            t.name, doc_ctx, role_hint=t.role_hint, turn_text=tbody, prev_turn_text=pbody, prev_speaker=pspeaker
        )
        if r in {"management", "analyst", "moderator"}:
            inferred_roles[norm] = r

    # Precompute carry-in speaker turn for each page (last turn of preceding pages)
    carry_in: dict[int, tuple[SpeakerTurn | None, str, str, str]] = {}
    running_turn: SpeakerTurn | None = None
    running_body = ""
    running_prev_body = ""
    running_prev_speaker = ""
    for pg in sorted(page_texts):
        carry_in[pg] = (running_turn, running_body, running_prev_body, running_prev_speaker)
        turns = page_turns[pg]
        if turns:
            txt = page_texts[pg]
            for idx, t in enumerate(turns):
                end_pos = turns[idx + 1].start if idx + 1 < len(turns) else len(txt)
                running_prev_speaker = running_turn.name if running_turn else ""
                running_prev_body = running_body
                running_body = txt[t.end:end_pos]
                running_turn = t

    results: dict[int, tuple[str, str]] = {}
    for oid, pg, vt, pl, st, existing_speaker in rows:
        existing_speaker = (existing_speaker or "").strip()
        txt = page_texts.get(pg, "")
        turns = page_turns.get(pg, [])

        if existing_speaker:
            pos = find_observation_pos(txt, vt, pl, st) if txt else None
            matched_turn: SpeakerTurn | None = None
            tbody = ""
            pbody = ""
            pspeaker = ""
            if pos is not None:
                idx = -1
                for i, t in enumerate(turns):
                    if t.start <= pos:
                        idx = i
                    else:
                        break
                if idx >= 0:
                    matched_turn = turns[idx]
                    end_pos = turns[idx + 1].start if idx + 1 < len(turns) else len(txt)
                    tbody = txt[matched_turn.end:end_pos]
                    if idx > 0:
                        pbody = txt[turns[idx - 1].end:turns[idx].start]
                        pspeaker = turns[idx - 1].name
                    else:
                        _, _, pbody, pspeaker = carry_in.get(pg, (None, "", "", ""))
                else:
                    matched_turn, tbody, pbody, pspeaker = carry_in.get(pg, (None, "", "", ""))
            role = classify_speaker_role(
                existing_speaker,
                doc_ctx,
                role_hint=matched_turn.role_hint if matched_turn else "",
                turn_text=tbody or st,
                prev_turn_text=pbody,
                prev_speaker=pspeaker,
                inferred_roles=inferred_roles,
            )
            results[oid] = (existing_speaker, role)
            continue

        if not txt:
            continue
        pos = find_observation_pos(txt, vt, pl, st)
        if pos is None:
            continue

        idx = -1
        for i, t in enumerate(turns):
            if t.start <= pos:
                idx = i
            else:
                break
        if idx >= 0:
            turn = turns[idx]
            end_pos = turns[idx + 1].start if idx + 1 < len(turns) else len(txt)
            tbody = txt[turn.end:end_pos]
            if idx > 0:
                pbody = txt[turns[idx - 1].end:turns[idx].start]
                pspeaker = turns[idx - 1].name
            else:
                _, _, pbody, pspeaker = carry_in.get(pg, (None, "", "", ""))
        else:
            turn, tbody, pbody, pspeaker = carry_in.get(pg, (None, "", "", ""))

        if turn is None:
            continue
        role = classify_speaker_role(
            turn.name,
            doc_ctx,
            role_hint=turn.role_hint,
            turn_text=tbody,
            prev_turn_text=pbody,
            prev_speaker=pspeaker,
            inferred_roles=inferred_roles,
        )
        results[oid] = (turn.name, role)

    return results


_COMPANY_SUFFIX = frozenset({"limited", "ltd", "corporation", "corp", "company", "co", "private", "pvt", "inc",
                             "llp", "and"})


def _company_key(name: str) -> str:
    """A name without its legal-form words, so "Ashoka Buildcon Limited" and "ASHOKA" share one key."""
    return " ".join(t for t in _norm_name(name).split() if t not in _COMPANY_SUFFIX)


def _initials(norm: str) -> str:
    return "".join(t[0] for t in norm.split())


def _display_name(norm: str) -> str:
    return " ".join(t.upper() if len(t) <= 2 else t.capitalize() for t in norm.split())


def management_pool(pages: list[tuple[int, str]]) -> list[str]:
    """Normalised full management names for one transcript: the roster plus turns carrying a management title."""
    ctx = build_doc_context(pages)
    known = set(ctx.mgmt_names) | set(ctx.analyst_names) | set(ctx.moderator_names)
    names = list(ctx.mgmt_names)
    for pg, txt in sorted(pages, key=lambda x: x[0]):
        for turn in extract_turns(txt or "", pg, known_names=known, allow_standalone=ctx.allow_standalone):
            norm = _norm_name(turn.name)
            if norm and norm not in names and turn.role_hint and _MGMT_ROLE_RE.search(turn.role_hint):
                names.append(norm)
    return names


_GENERIC_DESIGNATION_WORDS = frozenset({
    "cmd", "cfo", "ceo", "coo", "cto", "cio", "chro", "cmo", "cro", "cbo", "cso", "cs",
    "md", "ed", "jmd", "wtd", "vp", "svp", "evp", "avp", "gm", "dgm", "agm",
    "head", "chief", "managing", "executive", "whole", "time", "wholetime", "joint",
    "non", "independent", "director", "chairman", "chairperson", "president", "vice",
    "secretary", "compliance", "officer", "manager", "investor", "relations", "ir",
    "founder", "promoter", "group", "deputy", "assistant", "associate", "senior",
    "general", "team", "lead", "representative", "spokesperson",
    "finance", "financial", "operations", "operational", "risk", "strategy", "strategic",
    "commercial", "corporate", "marketing", "sales", "technical", "technology",
    "business", "development", "hr", "human", "resources", "legal", "treasury",
    "accounts", "audit", "tax", "it", "supply", "chain", "manufacturing", "production",
    "projects", "company", "management", "moderator", "operator", "coordinator", "host",
    "participant", "analyst", "unknown", "speaker",
    "of", "and", "for", "the", "in", "on", "to",
})


def _is_generic_speaker(speaker: str) -> bool:
    """True when ``speaker`` is empty, a generic role/company label, or a bare designation (CFO, ED (Finance))."""
    s = " ".join((speaker or "").split()).strip()
    if not s:
        return True
    toks = [t for t in re.split(r"[\s&/,().:\-]+", s.lower()) if t]
    if not toks:
        return True
    if all(t in _GENERIC_DESIGNATION_WORDS for t in toks):
        return True
    return bool(re.match(r"^(?:management\s+of\b|.*\bmanagement$)", s, re.I))


def resolve_speaker_name(speaker: str, pool: list[str],
                         company_keys: Iterable[str] = ()) -> tuple[str, str]:
    """T-242: resolve a company/first-name/initials label to one full management name; else keep it and say why.

    Returns ``(name, reason)``; ``reason`` is '' when the label (or its replacement) is a usable speaker.
    A full person name the roster does not list is kept as printed. Generic labels ('Management', 'Company',
    'Moderator') and bare designations ('CFO', 'ED (Finance)') are marked ``speaker_generic``.
    """
    raw = " ".join((speaker or "").split()).strip()
    norm = _norm_name(raw)
    if not norm:
        return raw, ""
    if _is_generic_speaker(raw):
        return raw, f"speaker_generic: {raw!r} is a generic speaker or bare designation"
    keys = set(company_keys)
    if _company_key(raw) in keys:
        return raw, f"speaker_unresolved: {raw!r} is the company, not a person"
    if len(norm.split()) > 1 and _name_matches_list(raw, pool):
        return raw, ""                 # already a full management name as printed
    tokens = norm.split()
    if len(tokens) == 1:
        tok = tokens[0]
        first = [cand for cand in pool if tok in cand.split()]
        initials = [cand for cand in pool if _initials(cand) == tok] if tok.isalpha() and len(tok) <= 3 else []
        cands = initials if len(initials) == 1 else first
    elif all(len(t) == 1 for t in tokens):
        wanted = "".join(tokens)
        cands = [cand for cand in pool if _initials(cand) == wanted]
    else:
        return raw, ""                 # a printed multi-word person name the roster does not list: keep it
    cands = list(dict.fromkeys(c for c in cands if c))
    if len(cands) == 1:
        return _display_name(cands[0]), ""
    why = f"matches {len(cands)} management names" if cands else "is not a full management name"
    return raw, f"speaker_unresolved: {raw!r} {why}"


_NO_REFERENT_START_RE = re.compile(r"^(?:yes|no|right|correct|sure)\b[\s,.!:;\u2013-]", re.I)


def no_referent_reason(statement: str) -> str:
    """T-242: a reply shorter than 8 words that opens with yes/no/right/correct/sure needs its question."""
    text = " ".join((statement or "").split())
    if not text or len(text.split()) >= 8 or not _NO_REFERENT_START_RE.match(text):
        return ""
    return "no_referent: a short reply whose question is not stored with it"


def load_pages(store_db: str | Path, doc_key: str) -> list[tuple[int, str]]:
    con = connect_ro(store_db, timeout_s=60)
    try:
        cur = con.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,))
        rows: list[Any] = [] if cur is None else list(cur.fetchall() or [])
    finally:
        con.close()
    return [(int(p), str(t or "")) for p, t in rows]


_FILING_LINE_RE = re.compile(r"\bfor\s+your\s+(?:kind\s+)?information\s+and\s+(?:records?|necessary)|"
                             r"\b(?:please|kindly)\s+take\s+(?:the\s+same\s+|the\s+above\s+|above\s+)?on\s+(?:your\s+)?record\b|"
                             r"\bregulation\s+30\b|\bplease\s+find\s+(?:enclosed|attached)\b|\benclosed\s+herewith\b", re.I)


_GREETING_SENTENCE_RE = re.compile(
    r"^(?:(?:now|so|and|with\s+that)\s+)?"
    r"(?:thank\s+you|thanks|good\s+(?:morning|afternoon|evening|night)|hello|hi|welcome|over\s+to\s+you"
    r"|i\s+(?:would\s+)?(?:now\s+)?(?:like\s+to\s+)?(?:hand|pass)\s+(?:it\s+)?over"
    r"|(?:now\s+)?(?:i\s+would|i'd|let\s+me)\s+(?:like\s+to\s+)?(?:take|walk)\s+you\s+through"
    r"|(?:i\s+)?(?:hope|trust)\s+(?:you|everyone)\s+(?:are|is)\s+(?:doing\s+)?well"
    # call logistics (394_v3 ckpt_0002 J): "I'll come back into the queue", "I'll join back the queue"
    r"|(?:i\s*(?:'ll|’ll|\s+will)\s+|let\s+me\s+|please\s+|i\s+)?(?:come\s+back|get\s+back|fall\s+back|join\s+back"
    r"|rejoin|go\s+back|step\s+back)\s+(?:in(?:to)?\s+|to\s+|in\s+)?(?:the\s+)?(?:queue|line)"
    r"|(?:that's|that\s+is|those\s+are)\s+(?:all|it)\s+(?:from\s+my\s+side|for\s+me|from\s+me)"
    r"|(?:all\s+the\s+)?best(?:\s+of\s+luck|\s+wishes)?(?:\s+for\s+the\s+(?:coming|next|future)\s*(?:quarters?|years?)?)?)\b",
    re.I)
_GREETING_TAIL_WORDS = 8     # what follows the greeting phrase: a name, "for your question", "for joining us"

_PERIOD_LABEL_RE = re.compile(
    r"\b(?:(?:[QH][1-4]|[1-4]Q|9M)\s*(?:FY\s*)?['’]?\s*\d{2,4}(?:\s*-\s*\d{2,4})?"
    r"|FY\s*['’]?\s*\d{2,4}(?:\s*-\s*\d{2,4})?"
    r"|[QH][1-4]|[1-4]Q|9M)\b"
    r"|\bversion\s+\d+(?:\.\d+)?\b",
    re.I,
)
_ABBREV_DOT_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Shri|Sh|Prof|Sr|Smt|Er|Capt|vs|etc)\.|(?<!\d)\bRs\.(?=\s*\d)", re.I)


_LIGATURE_MAP = str.maketrans({
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
    "\u019f": "ti",  # PDF CMap artefact in Indian filings ("quesƟon", "conƟnue")
    "\u0275": "ti",
    "\u01af": "ff",  # PDF CMap artefact ("oƯset", "diƯerence")
})


def _normalise_ligatures(text: str) -> str:
    """Fold PDF OCR ligatures before pattern matching; never mutates stored text."""
    return str(text or "").translate(_LIGATURE_MAP)


def _has_figure(text: str) -> bool:
    """A digit in the sentence, except a fiscal-period label ("Q2FY27 / H1FY27" is not a figure)."""
    return bool(re.search(r"\d", _PERIOD_LABEL_RE.sub(" ", text)))


_THANKS_WELCOME_RE = re.compile(
    r"^(?:(?:so|now|and|hi|hello|good\s+\w+|ladies\s+and\s+gentlemen)[,\s]+)*"
    r"(?:thank\s+you|thanks)\b[^.!?;]*\bwelcome\b[^.!?;]*"
    r"\b(?:all\s+(?:the\s+)?participants|participants|everyone|all\s+of\s+you|"
    r"(?:the\s+)?(?:earnings|conference|investor|analyst|results)\s*(?:call|webinar|meet)|"
    r"(?:earnings|conference|investor|analyst|results)?\s*call)\b(?P<tail>.*)[.!?]?$",
    re.I,
)

_PRAISE_QUESTION_RE = re.compile(
    r"^(?:(?:yes|yeah|no|well|so|okay|ok|sure|right|actually|firstly|first|sir|madam|i\s+think|"
    r"[A-Z][a-z]+(?:\s+ji)?)[,\s]+){0,3}"
    r"(?:(?:that|this|it)(?:\s+is|'s|’s)\s+)?"
    r"(?:(?:a|an)\s+)?(?:(?:very|really|quite|pretty|truly|super)\s+)?"
    r"(?:fine|good|great|pertinent|excellent|valid|fair|important|interesting|relevant|nice|wonderful|brilliant|apt)"
    r"\s+question\b(?P<tail>.*)[.!?]?$",
    re.I,
)

_SUBSTANTIVE_CLAUSE_RE = re.compile(
    r";|\b(?:but|however|though|although|yet|whereas|meanwhile|because|since)\b"
    r"|,\s*(?:and|so)\s+(?:we|our|the|it|there|in|for|margins?|revenue|growth|demand|volume|cost|price|capex)\b",
    re.I,
)

_DEFER_PREAMBLE = (
    r"^(?:(?:yes|yeah|no|so|now|okay|ok|sure|well|and|with\s+this|with\s+that|maybe|perhaps|actually|honestly|"
    r"(?:on|for|regarding|as\s+far\s+as|in\s+terms\s+of)\s+[^.!?;]{1,60})[,\s]+){0,4}"
)
# Case-sensitive person names so pronouns like 'me'/'we'/'you' never match as a named colleague.
_PERSON_OR_ROLE = (
    r"(?:(?:my|our)\s+(?:colleague|team|cfo|ceo|coo|cto|cmd|md|ed|group\s+cfo|director|president|head)|"
    r"(?-i:(?:(?:Mr|Ms|Mrs|Dr|Shri|Sh)\.?\s+)?[A-Z][A-Za-z.'’-]+(?:\s+(?:[A-Z][A-Za-z.'’-]+|sir|ji))*))"
)
_THIRD_PERSON_OR_ROLE = (
    r"(?:(?:my|our)\s+(?:colleague|team|cfo|ceo|coo|cto|cmd|md|ed|group\s+cfo|director|president|head)|"
    r"(?-i:he|she|He|She|(?:(?:Mr|Ms|Mrs|Dr|Shri|Sh)\.?\s+)?[A-Z][A-Za-z.'’-]+(?:\s+(?:[A-Z][A-Za-z.'’-]+|sir|ji))*))"
)
_DEFER_HANDOVER_RE = re.compile(
    _DEFER_PREAMBLE + r"(?:"
    r"(?:(?:i|we)(?:'ll|'d|\s+will|\s+would|\s+might|\s+may|\s+can)?|let\s+(?:me|us))\s+(?:like\s+to\s+)?(?:maybe\s+)?defer\s+(?:this|that|it|the\s+question\s+)?to\s+" + _PERSON_OR_ROLE +
    r"|(?:(?:i|we)(?:'ll|'d|\s+will|\s+would|\s+now|\s+also)?(?:\s+now|\s+also)?\s+(?:like\s+to\s+(?:now\s+)?)?|let\s+(?:me|us)\s+(?:now\s+)?)(?:hand|pass)(?:\s+it|\s+the\s+(?:call|floor|mic|mike|discussion))?\s+over\s+to\s+" + _PERSON_OR_ROLE +
    r"|(?:(?:i|we)(?:'ll|'d|\s+will|\s+would|\s+now)?(?:\s+now)?\s+(?:like\s+to\s+)?|let\s+me\s+)?(?:request|ask|invite)\s+" + _PERSON_OR_ROLE + r"(?:\s+(?:sir|ji|ma'am|madam))?(?:,\s*[^.?!;]{1,40},)?\s+to\s+(?:answer|respond|take|address|comment|reply|clarify|elaborate|explain|speak|talk|share|walk|take\s+us|say)\b"
    r"|let\s+(?!me\b|us\b)" + _PERSON_OR_ROLE + r"\s+(?:answer|take|respond|address)\b"
    r"|(?!I\b|We\b|You\b|They\b|It\b|This\b|That\b)" + _THIRD_PERSON_OR_ROLE + r"\s+(?:will|can|would)\s+(?:now\s+)?(?:answer|take|respond\s+to|address)\s+(?:on\s+)?(?:that|this|it|the\s+(?:question|other|second\s+part|first\s+part)|your\s+question)\b"
    r")(?P<tail>.*)[.!?]?$",
    re.I,
)


def _greeting_sentence(sentence: str) -> bool:
    """One sentence that is only a greeting, praise of a question, or defer/hand-over with no figure or substance."""
    sent = _normalise_ligatures(sentence).strip()
    if not sent:
        return False
    match = _GREETING_SENTENCE_RE.match(sent)
    if match:
        tail = sent[match.end():]
        if not _has_figure(tail) and len(re.findall(r"[A-Za-z]+", tail)) <= _GREETING_TAIL_WORDS:
            return True
    if _has_figure(sent):
        return False
    m_praise = _PRAISE_QUESTION_RE.match(sent)
    if m_praise:
        tail = m_praise.group("tail")
        if not _SUBSTANTIVE_CLAUSE_RE.search(tail) and len(re.findall(r"[A-Za-z]+", tail)) <= 5:
            return True
    m_defer = _DEFER_HANDOVER_RE.match(sent)
    if m_defer and not _SUBSTANTIVE_CLAUSE_RE.search(m_defer.group("tail")):
        return True
    return False


# Opening welcome: any length when the sentence welcomes the audience ("... a warm welcome to all participants"),
# provided it states no figure (fy27_v3 ckpt_0003: "... for Q2FY27 and H1FY27").
_WELCOME_OPEN_RE = re.compile(r"^(?:good\s+(?:morning|afternoon|evening)|hello|hi|welcome|greetings)\b", re.I)

# Closing/opening housekeeping that names no figure (fy27_v3 ckpt_0003: "audio recording ... uploaded", "stay safe").
_LOGISTICS_SENTENCE_RE = re.compile(
    r"\bthank\s+you\b[^.]*\bfor\s+(?:joining|attending|taking\s+(?:your\s+)?(?:valuable\s+)?time|being\s+(?:here|with\s+us))"
    r"|\bkeep\s+(?:you|everyone)\s+(?:all\s+)?posted\b"
    r"|\bsend\s+(?:in\s+)?your\b[^.]{0,40}\b(?:questions?|queries)\b"
    r"|\b(?:questions?|queries)\b[^.]{0,40}\b(?:unanswered|unaddressed)\b"
    r"|\b(?:for\s+)?any\s+(?:further|other|more)\s+(?:questions?|queries)\b"
    r"|\b(?:audio\s+recording|transcripts?|webcast|recording|presentation)\b[^.]{0,80}\b(?:uploaded|available)\b"
    r"|\b(?:uploaded|available)\b[^.]{0,80}\b(?:website|stock\s+exchanges?)\b"
    r"|^looking\s+forward\s+to\b"
    r"|^(?:have\s+a\s+(?:good|great|nice|wonderful)\s+(?:night|evening|day|weekend)|good\s*night)\b"  # BAJAJ-AUTO p24
    r"|\bstay\s+(?:healthy|safe|well)\b"
    r"|^i\s+hope\s+you\b", re.I)


# T-242 (25 Nov): closing thanks and deferrals the greeting patterns above do not reach. A closing line ends after
# the thanks/wish (no answer tail), so these anchor at the end of the sentence.
_CLOSING_THANKS_RE = re.compile(
    r"^(?:(?:yes|yeah|no|well|okay|ok|right|sure|so|now|and|once\s+again|again|finally|lastly|with\s+that)[,\s]+)*"
    r"(?:thank\s+you|thanks)"
    r"(?:\s+(?:so\s+much|very\s+much|a\s+lot|all|everyone|everybody|one\s+and\s+all|folks|sir|madam))?"
    r"(?:\s+for\s+(?:joining(?:\s+(?:us|the\s+call|today))?|your\s+(?:time|questions|participation|continued\s+support)"
    r"|attending(?:\s+(?:the\s+call|today))?|being\s+(?:here|with\s+us)))?"
    r"(?:[,\s]+(?:and\s+)?(?:all\s+the\s+best|best\s+of\s+luck|good\s+luck|take\s+care|stay\s+safe))?\s*[.!]*$"
    r"|^(?:(?:so|now|and)[,\s]+)*(?:(?:we|i)\s+)?(?:wish|wishing)\s+(?:you|all\s+of\s+you|everyone)(?:\s+all)?\s+a\s+"
    r"(?:good|great|nice|lovely|wonderful)\s+(?:evening|day|night|weekend)\b"
    r"(?:[,\s]+(?:and\s+)?(?:take\s+care|stay\s+safe))?[.!?]*$"
    r"|^(?:(?:so|now|and)[,\s]+)*(?:we|i)\s+(?:look|are\s+looking)\s+forward\s+to\s+"
    r"(?:interacting|speaking|talking|engaging|meeting|seeing)(?:\s+with\s+(?:you|all\s+of\s+you))?"
    r"(?:\s+(?:again|soon|next\s+quarter|in\s+the\s+next\s+call)){0,2}[.!?]*$",
    re.I,
)

# A deferral to after the call / offline: a promise to answer later, not an answer. The deferral marker must be
# present ("to you", "offline", "post this call", ...), so "we will get back to growth" is never a deferral.
_DEFERRAL_SENTENCE_RE = re.compile(
    _DEFER_PREAMBLE + r"(?:"
    r"(?:(?:we|i)\s*(?:'ll|'d|\u2019ll|\u2019d|\s+will|\s+would|\s+can|\s+could|\s+may|\s+might)?\s*"
    r"(?:(?:be\s+able\s+to|try\s+to|like\s+to)\s+)?(?:get\s+back|come\s+back|revert|follow\s+up)\b"
    r"[^.!?;]{0,60}?\b(?:to\s+you|offline|post\s+(?:this|the)\s+call|after\s+(?:this|the)\s+call|separately|later|on\s+that)\b)"
    r"|please\s+(?:reach\s+out|get\s+in\s+touch)\b[^.!?;]*\b(?:ir|investor\s+relations)\b"
    r"|(?:we|i)\s+(?:can|could|will|would)\s+take\s+(?:it|this|that)\s+offline\b"
    r")[^.!?;]*[.!?]*$",
    re.I,
)

# A generic closing platitude: confidence, governance, team or gratitude language with no figure and no substantive
# clause. Deliberately excludes expect/hope/guidance/target so an outlook sentence is never read as a platitude.
_CLOSING_PLATITUDE_RE = re.compile(
    r"\b(?:confiden(?:t|ce)|positive|excited|assurance|mindful|transparen(?:t|cy)|well[- ]governed|governance"
    r"|nice\s+(?:talking|speaking|chatting)\s+to|(?:my|our)\s+team|humbled|grateful|proud|committed|commitment"
    r"|endeavour|endeavor|utmost\s+(?:care|integrity)|highest\s+standards?)\b", re.I)


def _sentences(text: str) -> list[str]:
    """Split on . ! ? followed by space, keeping a title's dot inside its sentence ("to Mr. Sohoni ...")."""
    guarded = _ABBREV_DOT_RE.sub(lambda m: m.group(0)[:-1] + "\u2024", _normalise_ligatures(text))
    return [x.replace("\u2024", ".").strip() for x in re.split(r"(?<=[.!?])\s+", guarded) if x.strip()]


def _boilerplate_sentence(sentence: str) -> bool:
    """A welcome or housekeeping sentence with no figure in it; only a sentence that says "welcome" may be long."""
    sent = _normalise_ligatures(sentence).strip()
    if _has_figure(sent):
        return False
    if re.search(r"\bwelcome\b", sent, re.I) and _WELCOME_OPEN_RE.match(sent):
        return True
    m_tw = _THANKS_WELCOME_RE.match(sent)
    if m_tw and not _SUBSTANTIVE_CLAUSE_RE.search(m_tw.group("tail")) and len(re.findall(r"[A-Za-z]+", m_tw.group("tail"))) <= 8:
        return True
    return bool(_LOGISTICS_SENTENCE_RE.search(sent))


def _closing_platitude(sentence: str) -> bool:
    """A figure-free generic closing line (confidence, governance, team) with no substantive clause."""
    sent = _normalise_ligatures(sentence).strip()
    if not sent or _has_figure(sent) or _SUBSTANTIVE_CLAUSE_RE.search(sent):
        return False
    return bool(_CLOSING_PLATITUDE_RE.search(sent))


def _closing_remarks_passage(sentences: list[str]) -> bool:
    """T-242 (25 Nov): a figure-free passage that opens or closes with a thanks/deferral and whose every other
    sentence is a figure-free platitude; any figure, outlook or substantive clause keeps it."""
    has_closing = False
    for sent in sentences:
        if _greeting_sentence(sent) or _boilerplate_sentence(sent) \
                or _CLOSING_THANKS_RE.match(_normalise_ligatures(sent)) \
                or _DEFERRAL_SENTENCE_RE.match(_normalise_ligatures(sent)):
            has_closing = True
            continue
        if not _closing_platitude(sent):
            return False
    return has_closing


# T-242 (26 Nov, tx394 ckpt_0014 J): the call's own logistics carries no statement -- opening the floor, a demo
# break, a walk to the products.  Figure-free only: a sentence that states a number stays, and a floor line that also
# carries a measure ("we keep our cost and capex guidance intact ... open the floor") is a statement.
_FLOOR_LOGISTICS_RE = re.compile(
    r"\bopen(?:s|ed|ing)?\s+(?:up\s+)?the\s+floor\b"
    r"|\b(?:take|taking|invite|inviting|field|fielding)\s+(?:some\s+|a\s+few\s+|your\s+|the\s+)?questions?\b",
    re.I,
)
_FLOOR_LOGISTICS_MAX_WORDS = 24
_DEMO_LOGISTICS_RE = re.compile(
    r"\b(?:take|taking|have|having)\s+(?:a\s+)?(?:few|short|small|quick|two|three|five)\s+(?:seconds?|minutes?)\s+break\b"
    r"|\bwalk(?:ing)?\s+(?:down|over|around|up)\s+to\s+(?:the|our)\s+products?\b"
    r"|\b(?:physically\s+)?(?:show|showing|demonstrate|demonstrating|demo|demoing)\s+(?:you\s+)?"
    r"(?:the|our|these)\s+products?\b"
    r"|\bproducts?\s+in\s+action\b"
    r"|\binformal\s+survey\b",
    re.I,
)

# A short figure-free forward pointer ("You will see that it does not end here"); a measure word, a named entity or
# a substantive clause keeps the sentence.
_FILLER_MAX_WORDS = 10
_MEASURE_WORD_RE = re.compile(
    r"\b(?:revenues?|sales|turnover|margins?|ebitda|pat|profits?|loss(?:es)?|growth|demand|orders?|order\s*book"
    r"|capex|capital\s+expenditure|capacity|volumes?|costs?|pricing|prices?|debt|borrowings?|cash|liquidity"
    r"|tax|eps|dividend|market\s+share|utilis(?:ation|ed)|utiliz(?:ation|ed)|inventory|receivables?|payables?"
    r"|working\s+capital|headcount|aum|nim|npa|production|shipments?|presales?|guidance|outlook)\b",
    re.I)
_TRANSITION_FILLER_RE = re.compile(
    r"\b(?:does\s+not|doesn't)\s+end\s+here\b"
    r"|\b(?:this|it)\s+is\s+(?:just|only|merely)\s+the\s+(?:beginning|start)\b", re.I)

# T-242 (26 Nov, tx394 ckpt_0014 J): a promise to answer later, anywhere in a figure-free sentence -- "get back to
# you on e-mail", "share the loss numbers offline".  A growth figure keeps its sentence ("get back to growth of 15%").
_DEFERRAL_MARKER_RE = re.compile(
    r"\bget\s+back\s+(?:to\s+(?:you|them|him|her)|on|via|by|over|in|with)\b"
    r"|\b(?:share|send|email|e-mail|mail|provide|answer|revert)\b[^.!?;]{0,40}?"
    r"\b(?:offline|separately|after\s+(?:the|this)\s+call|post\s+(?:the|this)\s+call|on\s+e-?mail"
    r"|by\s+e-?mail|over\s+e-?mail|in\s+writing)\b"
    r"|\btake\s+(?:it|this|that)\s+offline\b"
    r"|\be-?mail\s+you\b", re.I)
# "get back on a volume growth path" is a recovery, not a promise to answer later.
_NOT_A_DEFERRAL_RE = re.compile(r"\bget\s+back\s+on\b[^.!?;]{0,40}\b(?:growth\s+path|on\s+track|path\s+to|trajectory)\b", re.I)

# T-242 r2 (26 Nov): figure-free refusals/deferrals to quantify, concluding lines, and boilerplate wrap-up summaries.
_REFUSAL_QUANTIFY_RE = re.compile(
    r"\b(?:do\s+not|don't|don’t|cannot|can't|can’t|won't|won’t|would\s+not|wouldn't|wouldn’t|will\s+not"
    r"|(?:am|are)\s+(?:not\s+(?:in\s+a\s+position|able|willing|comfortable)|unable)|not\s+in\s+a\s+position"
    r"|(?:do\s+not|don't|don’t|would\s+not|wouldn't|wouldn’t)\s+(?:want|like))\s+(?:to\s+)?"
    r"(?:give(?:\s+you)?|share|provide|disclose|quantify|put|throw|commit(?:\s+to)?|offer|hazard|guess)\b[^.!?;]{0,50}?"
    r"\b(?:any\s+)?(?:(?:futuristic|forward[- ]looking|exact|specific|precise|particular|quarterly|annual"
    r"|segment[- ]wise|customer[- ]wise|product[- ]wise|such)\s+)*(?:numbers?|figures?|guidance|outlook|targets?"
    r"|estimates?|projections?|break[- ]?ups?|split|details?|data|comments?)\b"
    r"|\b(?:we|i)\s+(?:do\s+not|don't|don’t|cannot|can't|can’t)\s+"
    r"(?:calculate|track|measure|report|capture|break\s*(?:up|down)|split|disclose|give)\b[^.!?;]{0,60}?"
    r"\b(?:that\s+way|like\s+that|separately|at\s+that\s+level|by\s+(?:customer|segment|product)|on\s+(?:this|that)\s+basis)\b"
    r"|\b(?:(?:do\s+not|don't|don’t|won't|won’t|would\s+not|wouldn't|wouldn’t|cannot|can't|can’t)"
    r"\s+(?:be\s+able\s+to\s+)?(?:comment|speculate|guide|(?:give|share|provide)\s+(?:any\s+)?guidance)"
    r"|not\s+in\s+a\s+position\s+to\s+(?:comment|share|give|quantify|guide|disclose))\b"
    r"(?:\s+(?:on|about)\s+(?:that|this|it|the\s+same|those|further))?",
    re.I,
)
_CONCLUDE_SENTENCE_RE = re.compile(
    r"^(?:(?:so|now|and|with\s+this|with\s+that|on\s+that\s+note)[,\s]+)*(?:(?:i|we)(?:'d|'ll|\s+would|\s+will)?\s+"
    r"(?:like\s+to\s+)?)?(?:conclude|wrap\s+up|close|end)\b[^.!?;]*"
    r"\b(?:my|our|the)\s+(?:opening\s+|closing\s+|prepared\s+)?(?:remarks|comments|presentation|address|call|session|statement)\s*[.!?]*$"
    r"|^(?:so|now|and)?[,\s]*(?:with\s+this|with\s+that)[,\s]+(?:i|we)\s+conclude\b[^.!?;]{0,30}[.!?]*$"
    r"|^(?:that|this)\s+concludes\b[^.!?;]{0,40}[.!?]*$",
    re.I,
)
_WRAPUP_CUE_RE = re.compile(
    r"\b(?:version\s+\d+(?:\.\d+)?|growth\s+phase|resilient\s+and\s+diversified|operational\s+excellence"
    r"|market\s+leadership|sustainable\s+value\s+creation|new\s+growth\s+opportunities|focus\s+remains\s+on"
    r"|(?:enhancing|creating|delivering|maximi[sz]ing)\s+(?:long[- ]term\s+)?(?:shareholder|stakeholder)\s+value)\b",
    re.I,
)


def _call_logistics_sentence(sentence: str) -> bool:
    """A figure-free call-mechanics sentence: opening the floor, a demo break, a walk to the products."""
    sent = _normalise_ligatures(sentence).strip()
    if not sent or _has_figure(sent):
        return False
    if _DEMO_LOGISTICS_RE.search(sent) or _CONCLUDE_SENTENCE_RE.match(sent):
        return True
    return len(sent.split()) <= _FLOOR_LOGISTICS_MAX_WORDS and not _MEASURE_WORD_RE.search(sent) \
        and bool(_FLOOR_LOGISTICS_RE.search(sent))


def _filler_sentence(sentence: str) -> bool:
    """A short figure-free forward pointer that names no measure, product or place."""
    sent = _normalise_ligatures(sentence).strip()
    if not sent or _has_figure(sent) or _names_like_entity(sent):
        return False
    if len(sent.split()) > _FILLER_MAX_WORDS or _MEASURE_WORD_RE.search(sent) \
            or _SUBSTANTIVE_CLAUSE_RE.search(sent):
        return False
    return bool(_TRANSITION_FILLER_RE.search(sent))


def _deferral_sentence(sentence: str) -> bool:
    sent = _normalise_ligatures(sentence).strip()
    return bool(sent) and not _has_figure(sent) and bool(_DEFERRAL_MARKER_RE.search(sent)) \
        and not _NOT_A_DEFERRAL_RE.search(sent)


def _refusal_sentence(sentence: str) -> bool:
    """A figure-free refusal or inability to quantify/guide/comment, with no substantive clause."""
    sent = _normalise_ligatures(sentence).strip()
    return bool(sent) and not _has_figure(sent) and not _SUBSTANTIVE_CLAUSE_RE.search(sent) \
        and bool(_REFUSAL_QUANTIFY_RE.search(sent))


def _wrapup_summary_passage(statement: str) -> bool:
    """A figure-free generic corporate wrap-up summary ("version 2.0 ... enhancing shareholder value")."""
    text = _normalise_ligatures(statement).strip()
    if not text or _has_figure(text):
        return False
    return len({m.group(0).lower() for m in _WRAPUP_CUE_RE.finditer(text)}) >= 2


def _deferral_passage(sentences: list[str]) -> bool:
    """T-242 (26 Nov): a passage that only promises the answer later or refuses to quantify."""
    has_deferral = False
    for sent in sentences:
        if _greeting_sentence(sent) or _boilerplate_sentence(sent) or _call_logistics_sentence(sent) \
                or _filler_sentence(sent):
            continue
        if _deferral_sentence(sent) or _refusal_sentence(sent):
            has_deferral = True
            continue
        return False
    return has_deferral


def greeting_only(statement: str) -> bool:
    """T-242 (fy27_v3 ckpt_0002/0003 J): a passage made only of greetings, thanks, housekeeping and hand-overs
    carries no statement; any one sentence with substance keeps it. T-242 (25 Nov): also a figure-free closing-remarks
    or deferral passage whose other sentences are generic platitudes (never one carrying a figure or a substantive
    clause). T-242 (26 Nov, tx394 ckpt_0014 J / r2): also call logistics (floor, demo break, concluding line),
    deferral/refusal-to-quantify passages, corporate wrap-up summaries with no figure and short refer-back fillers."""
    sentences = _sentences(statement)
    if not sentences:
        return False
    return all(_greeting_sentence(x) or _boilerplate_sentence(x) or _call_logistics_sentence(x)
               or _filler_sentence(x) for x in sentences) \
        or _closing_remarks_passage(sentences) \
        or _deferral_passage(sentences) \
        or _wrapup_summary_passage(statement)


# T-242 (26 Nov, tx394 ckpt_0014 P / r2; r3; r4): only an explicit own-period cue anchors a prepared remark.
_REL_QUARTER_RE = re.compile(
    r"\b(?:this|the|current)\s+quarter(?:'s|’s)?\b(?!\s+(?:ago|earlier|before|prior|last|previous|-on-))", re.I)
_REL_YEAR_RE = re.compile(
    r"\b(?:this|the|current)\s+year(?:'s|’s)?\b(?!\s*(?:-?on-|ago\b|earlier\b|before\b|ended\b|ending\b|to\s+date\b))",
    re.I)
_NAMED_QUARTER_FY_RE = re.compile(
    r"\bQ([1-4])(?:\s*(?:and|&|,|/)\s*(?:9M|H[12]))?\s*FY\s*['’]?\s*(\d{2,4})\b", re.I)
_NAMED_FY_RE = re.compile(
    r"(?:\b(?:for|in|of|during)\s+(?:the\s+)?(?:full\s+|financial\s+|fiscal\s+)?year\s+FY\s*['’]?\s*(\d{2,4})"
    r"|\bfor\s+FY\s*['’]?\s*(\d{2,4}))\b", re.I)
_COMPARATIVE_CUE_RE = re.compile(
    r"\b(?:y-o-y|yoy|year[- ]on[- ]year|q-o-q|qoq|quarter[- ]on[- ]quarter|versus|vs\.?"
    r"|compared\s+(?:to|with)|last\s+year|previous\s+year|prior\s+year|corresponding\s+(?:quarter|period)"
    r"|same\s+period\s+last\s+year|last\s+quarter|previous\s+quarter)\b", re.I)
_CALL_PERIOD_RE = re.compile(r"^Q([1-4])\s+FY(\d{2,4})$")
_CALL_TITLE_CUE_RE = re.compile(
    r"\b(?:(?:earn(?:ing|ings)|eamnings?|results?|investor|analyst|post[- ]?earnings?|post[- ]?results?|conference)"
    r"\s+(?:conference\s+)?call|call\s+transcript|con[- ]?call)\b",
    re.I,
)
_HEADER_Q_RE = re.compile(
    r"\b(?:Q\s*([1-4])|([1-4])\s*Q)\s*(?:(?:and|&|/|,|-)\s*(?:H[12]|[12]H|9M|FY)\s*)?"
    r"(?:FY\s*['’-]?\s*|(?=(?:\d{2}|\d{4})\s*-\s*\d{2,4}\b))(?:(\d{2,4})\s*-\s*)?(\d{2,4})\b",
    re.I,
)
_MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_NAMES = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_PRINTED_DATE_RE = re.compile(
    rf"(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?[\s,.\-]+(?P<m1>{_MONTH_NAMES})\.?(?:[\s,.\-]+(?:of\s+)?['’]?(?P<y1>\d{{2,4}}))\b"
    rf"|(?P<m2>{_MONTH_NAMES})\.?\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?(?:,|\s)\s*['’]?(?P<y2>\d{{2,4}})\b"
    rf"|\b(?P<d3>\d{{1,2}})[./\-](?P<m3>\d{{1,2}})[./\-](?P<y3>\d{{2,4}})\b"
    rf"|\b(?P<y4>20\d{{2}})-(?P<m4>\d{{1,2}})-(?P<d4>\d{{1,2}})\b"
    rf"|(?P<m5>{_MONTH_NAMES})\.?(?:,?\s+|\s+of\s+)(?:['’](?P<y5a>\d{{2}})|(?P<y5b>20\d{{2}})|(?P<y5c>\d{{2}}))\b"
    rf"(?!\s*,?\s*(?:20\d{{2}}|['’]\d{{2}}))",
    re.I,
)
_FORWARD_CUE_RE = re.compile(
    r"\b(?:will|expect(?:s|ed|ing|ations?)?|target(?:s|ed|ing)?|guid(?:e|ing|ance)"
    r"|projected|projection|forecast(?:s|ed|ing)?"
    r"|next\s+(?:quarter|year|fiscal|financial\s+year|h[12]|half)|by\s+FY\s*['’]?\s*\d{2,4})\b",
    re.I,
)
_SAME_QUARTER_LAST_YEAR_RE = re.compile(r"\bsame\s+quarter\s+last\s+year\b", re.I)
_LAST_QUARTER_RE = re.compile(r"\blast\s+quarter(?:'s|’s)?\b", re.I)
_OTHER_HALF_9M_RE = re.compile(
    r"\b(?:H[12]|[12]H|9M)\b|\b(?:first|second)\s+half\b|\bhalf[- ]year\b|\bnine\s+months\b", re.I)
_EXPLICIT_Q_RE = re.compile(
    r"\bQ([1-4])(?:\s*FY\s*['’]?\s*(\d{2,4}))?\b"
    r"|\b([1-4])Q(?:\s*FY\s*['’]?\s*(\d{2,4}))?\b"
    r"|\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+of\s+(?:FY\s*['’]?\s*(\d{2,4})|(\d{4})))?\b",
    re.I,
)
_EXPLICIT_FY_RE = re.compile(r"\bFY\s*['’]?\s*(\d{2,4})(?:\s*[-–/]\s*['’]?(\d{2,4}))?\b", re.I)
_ORDINAL_QUARTER = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
_QUARTER_END = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}
_AS_ON_DATE_CUE_RE = re.compile(
    r"\b(?:as\s+(?:on|at|of)|basis)(?:\s+(?:the|of))?\s+(?=" + _PRINTED_DATE_RE.pattern + ")", re.I)
_QUARTERLY_METRIC_RE = re.compile(
    r"\bquarterly\b(?!\s+(?:basis|fluctuations?|trends?|sort\b|volatility|seasonality|run[- ]?rates?"
    r"|meetings?|calls?|updates?\b|operations\s+per\s+se\b))",
    re.I,
)
_OVER_BASE_VERB_RE = re.compile(r"\b(?:stood\s+at|stands\s+at|was|were|reached)\b", re.I)
_OVER_BASE_CMP_RE = re.compile(
    r"\b(?:growth|up|increase|increased)\b[^.!?;]{0,40}?\bover\s+(?:the\s+)?(?=" + _PRINTED_DATE_RE.pattern + ")", re.I)


def _parse_printed_date(match: re.Match[str]) -> tuple[int, int, int | None, bool] | None:
    """Parse ``_PRINTED_DATE_RE`` into ``(year, month, day_or_none, explicit_year)``."""
    if match.group("m1"):
        y = int(match.group("y1"))
        return (2000 + y if y < 100 else y, _MONTH_MAP[match.group("m1").lower()], int(match.group("d1")), True)
    if match.group("m2"):
        y = int(match.group("y2"))
        return (2000 + y if y < 100 else y, _MONTH_MAP[match.group("m2").lower()], int(match.group("d2")), True)
    if match.group("m3"):
        d, mo, y = int(match.group("d3")), int(match.group("m3")), int(match.group("y3"))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return (2000 + y if y < 100 else y, mo, d, True)
        return None
    if match.group("m4"):
        y, mo, d = int(match.group("y4")), int(match.group("m4")), int(match.group("d4"))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return (y, mo, d, True)
        return None
    if match.group("m5"):
        mo = _MONTH_MAP[match.group("m5").lower()]
        if match.group("y5a"):
            return (2000 + int(match.group("y5a")), mo, None, True)
        if match.group("y5b"):
            return (int(match.group("y5b")), mo, None, True)
        y2 = int(match.group("y5c"))
        if 18 <= y2 <= 35:
            return (2000 + y2, mo, None, False)
    return None


def _date_equals(parsed: tuple[int, int, int | None, bool] | None, target_y: int, target_m: int, target_d: int) -> bool:
    if not parsed:
        return False
    y, m, d, _ = parsed
    return y == target_y and m == target_m and (d is None or d == target_d)


def _period_end_date(q: int, fy: int) -> tuple[int, int, int]:
    end_year = 2000 + fy - (1 if q < 4 else 0)
    end_month, end_day = _QUARTER_END[q]
    return end_year, end_month, end_day


def printed_call_period(pages: Iterable[tuple[int, str]]) -> str:
    """The call's printed quarter ('Q2 FY26') from the transcript's header or first pages; '' when absent."""
    first_pages = [_normalise_ligatures(txt) for _pg, txt in sorted(pages, key=lambda item: int(item[0]))[:3] if txt]
    candidates: list[str] = []
    for txt in first_pages:
        for sent in _sentences(" ".join(txt.split())):
            if _CALL_TITLE_CUE_RE.search(sent):
                candidates.append(sent)
        candidates.append(" ".join(txt.splitlines()[:6]))
    for cand in candidates:
        m = _HEADER_Q_RE.search(cand)
        if m:
            q = int(m.group(1) or m.group(2))
            fy = int(m.group(4)) % 100
            return f"Q{q} FY{fy:02d}"
    return ""


def _sentence_has_future_date(sent: str, end_ym: int) -> bool:
    for dm in _PRINTED_DATE_RE.finditer(sent):
        parsed = _parse_printed_date(dm)
        if parsed and parsed[3]:
            ym = parsed[0] * 12 + parsed[1]
            if ym > end_ym + 2:
                return True
            before = sent[max(0, dm.start() - 6):dm.start()]
            if ym > end_ym and re.search(r"\bby\s+$", before, re.I):
                return True
    return False


def _sentence_blocked_for_anchor(sent: str, q: int, fy: int, end_ym: int, *, check_other_period: bool = True) -> bool:
    if _SAME_QUARTER_LAST_YEAR_RE.search(sent):
        return True
    for lm in _LAST_QUARTER_RE.finditer(sent):
        if not _COMPARATIVE_CUE_RE.search(sent[:lm.start()]):
            return True
    if _FORWARD_CUE_RE.search(sent) or _sentence_has_future_date(sent, end_ym):
        return True
    if not check_other_period:
        return False
    if _OTHER_HALF_9M_RE.search(sent):
        return True
    for qm in _EXPLICIT_Q_RE.finditer(sent):
        if _COMPARATIVE_CUE_RE.search(sent[:qm.start()]):
            continue
        if qm.group(1):
            mq = int(qm.group(1))
            mfy = int(qm.group(2)) % 100 if qm.group(2) else fy
        elif qm.group(3):
            mq = int(qm.group(3))
            mfy = int(qm.group(4)) % 100 if qm.group(4) else fy
        else:
            mq = _ORDINAL_QUARTER[qm.group(5).lower()]
            if qm.group(6):
                mfy = int(qm.group(6)) % 100
            elif qm.group(7):
                cy = int(qm.group(7))
                mfy = (cy + (1 if mq == 4 else 0)) % 100
            else:
                mfy = fy
        if (mq, mfy) != (q, fy):
            return True
    for fm in _EXPLICIT_FY_RE.finditer(sent):
        if _COMPARATIVE_CUE_RE.search(sent[:fm.start()]):
            continue
        fy_end = int(fm.group(2) or fm.group(1)) % 100
        if fy_end != fy:
            return True
    return False


def anchored_period(statement: str, call_period: str) -> str:
    """The fiscal label a prepared remark's own period resolves to on this call; '' when none or unknown.

    ``call_period`` is the label the reader was given for the call ("Q2 FY26").  Only an explicit own-period cue
    anchors: "this/the quarter", "this quarter's", "quarterly <metric/figure>", "as on/at/of/basis <date equal to
    period end>", or "<figure> stood at/was/reached ... (growth|up|increase) over <date 1 year or 1 quarter before
    period end>" resolve to the call quarter; "this/the year" and "for FYnn" (on Q4 calls) resolve to the call's
    fiscal year; a named "Qn FYnn" resolves to itself when it is the call's own period.  Never anchors when a
    comparative cue precedes a named period, or when a forward cue, "same quarter last year", "last quarter", an
    explicit other FY/H/Q, or a future date sits in the cue's sentence (empty beats wrong).
    """
    m = _CALL_PERIOD_RE.match(" ".join(str(call_period or "").split()))
    if not m:
        return ""
    q, fy = int(m.group(1)), int(m.group(2)) % 100
    text = _normalise_ligatures(statement)
    sentences = _sentences(text)
    for sent in sentences:
        if _SAME_QUARTER_LAST_YEAR_RE.search(sent):
            continue
        named = _NAMED_QUARTER_FY_RE.search(sent)
        if named and not _COMPARATIVE_CUE_RE.search(sent[:named.start()]) \
                and (int(named.group(1)), int(named.group(2)) % 100) == (q, fy):
            return f"Q{q} FY{fy:02d}"
    end_year, end_month, end_day = _period_end_date(q, fy)
    end_ym = end_year * 12 + end_month
    if q == 4:
        for sent in sentences:
            if _sentence_blocked_for_anchor(sent, q, fy, end_ym, check_other_period=False):
                continue
            named = _NAMED_FY_RE.search(sent)
            if named and not _COMPARATIVE_CUE_RE.search(sent[:named.start()]) \
                    and int(named.group(1) or named.group(2)) % 100 == fy:
                return f"FY{fy:02d}"
    for sent in sentences:
        if _sentence_blocked_for_anchor(sent, q, fy, end_ym):
            continue
        if _REL_QUARTER_RE.search(sent):
            return f"Q{q} FY{fy:02d}"
        for am in _AS_ON_DATE_CUE_RE.finditer(sent):
            if _COMPARATIVE_CUE_RE.search(sent[:am.start()]):
                continue
            dm = _PRINTED_DATE_RE.match(sent, am.end())
            if dm and _date_equals(_parse_printed_date(dm), end_year, end_month, end_day):
                return f"Q{q} FY{fy:02d}"
        if _QUARTERLY_METRIC_RE.search(sent) and _has_figure(sent):
            return f"Q{q} FY{fy:02d}"
        if _has_figure(sent):
            vm = _OVER_BASE_VERB_RE.search(sent)
            if vm and not _COMPARATIVE_CUE_RE.search(sent[:vm.start()]):
                cm = _OVER_BASE_CMP_RE.search(sent, vm.end())
                if cm:
                    dm = _PRINTED_DATE_RE.match(sent, cm.end())
                    if dm:
                        parsed = _parse_printed_date(dm)
                        pq = 4 if q == 1 else q - 1
                        pfy = fy - 1 if q == 1 else fy
                        pq_year, pq_month, pq_day = _period_end_date(pq, pfy)
                        if _date_equals(parsed, end_year - 1, end_month, end_day) \
                                or _date_equals(parsed, pq_year, pq_month, pq_day):
                            return f"Q{q} FY{fy:02d}"
    for sent in sentences:
        if _sentence_blocked_for_anchor(sent, q, fy, end_ym):
            continue
        if _REL_YEAR_RE.search(sent):
            return f"FY{fy:02d}"
    return ""


# T-242 (25 Nov, surprise audit J): a short figure-free remark that carries no statement.
_SHORT_REMARK_MAX_WORDS = 8
_GENERIC_ASSESSMENT_RE = re.compile(
    r"^(?:(?:so|and|yes|yeah|well|okay|ok)[,\s]+)?"
    r"(?:we\s+have\s+done\s+well|we\s+did\s+well|that(?:'s|’s|\s+is)\s+(?:a\s+)?(?:(?:very|really|quite|pretty)\s+)?"
    r"(?:good|great|fair|valid|interesting|pertinent|important|nice)\s+(?:point|question)"
    r"|good\s+(?:point|question)|fair\s+(?:point|enough))\b[^.!?]*[.!?]?$",
    re.I,
)
# A pointer to what someone else asked rather than an answer: "Kedar, I think his question was on products."
_POINTER_REMARK_RE = re.compile(
    r"\b(?:his|her|their|your)\s+(?:question|query)\b"
    r"|\b(?:question|query)\s+(?:was|is)\s+(?:on|about|around)\b"
    r"|\b(?:i\s+(?:think|believe|guess)|he|she|they)\s+(?:was\s+|is\s+|were\s+)?(?:asking|asked)\b"
    r"|\b(?:over|hand\s+over|pass\s+it\s+over)\s+to\s+(?:you|him|her|them)\b", re.I)
# A sentence whose subject is only a demonstrative: "So that's a meaningful swing", "That is the reason".
_REFER_BACK_RE = re.compile(
    r"^(?:(?:so|and|yes|yeah|well|okay|ok|but)[,\s]+)?"
    r"(?:that|this|it|which)(?:'s|’s|\s+is|\s+was|\s+means|\s+would\s+be|\s+will\s+be)\s+(?!for\b)", re.I)
_CONTENT_WORD_RE = re.compile(r"[A-Za-z]{4,}")
_CONTENT_STOP = frozenset({
    "that", "this", "with", "have", "been", "will", "would", "could", "should", "which", "there",
    "their", "about", "into", "from", "over", "very", "much", "more", "most", "what", "when",
    "where", "well", "good", "great", "meaning", "really", "quite", "just", "like", "also",
})


def _names_like_entity(text: str) -> bool:
    """A capitalised word after the first that is not "I": a product, person or place names substance."""
    for idx, tok in enumerate(text.split()):
        word = tok.strip(".,;:!?()[]\"'“”’")
        if idx > 0 and len(word) >= 2 and word[0].isupper() and word.lower() != "i":
            return True
    return False


def short_remark_reason(statement: str, question_context: str = "") -> str:
    """T-242 (25 Nov): '' unless ``statement`` is a short content-free remark that must be dropped.

    At most 8 words, no figure, no substantive clause and no named entity/product.  It is (a) generic praise or
    assessment ("We have done well", "That's a good point"), (b) a pointer to another speaker or question
    ("I think his question was on products") or (c) a sentence that only refers back ("So that's a meaningful
    swing") when ``question_context`` is empty or shares none of its content words.
    """
    text = " ".join(_normalise_ligatures(statement).split())
    if not text or len(text.split()) > _SHORT_REMARK_MAX_WORDS or _has_figure(text):
        return ""
    if _SUBSTANTIVE_CLAUSE_RE.search(text):
        return ""
    if _names_like_entity(text):
        return ""
    if _GENERIC_ASSESSMENT_RE.match(text):
        return "short_generic: a figure-free generic assessment"
    if _POINTER_REMARK_RE.search(text):
        return "short_pointer: a pointer to another speaker or question, not an answer"
    if _REFER_BACK_RE.match(text):
        fragment = {w.lower() for w in _CONTENT_WORD_RE.findall(text)} - _CONTENT_STOP
        context = {w.lower() for w in _CONTENT_WORD_RE.findall(question_context)}
        if not fragment & context:
            return "short_refer_back: a sentence that only refers back, with no referent stored with it"
    return ""


_COURTESY_OR_TAG_QUESTION_RE = re.compile(
    r"(?:(?:^|,\s*)(?:right|isn['’]t\s+it|no)"
    r"|\b(?:is\s+that\s+helpful"
    r"|am\s+i\s+able\s+to\s+answer\s+your\s+question"
    r"|does\s+(?:that|this)\s+answer\s+your\s+question"
    r"|what\s+was\s+your\s+(?:(?:second|next)\s+)?question)"
    r"(?:\s*,\s*[A-Za-z.\s]{1,30})?)\s*\?$",
    re.I,
)


_CONFIRMATION_QUESTION_RE = re.compile(
    r"\b(?:is\s+(?:that|this|it)\s+(?:correct|right|the\s+right\s+understanding)"
    r"|is\s+my\s+understanding\s+(?:correct|right)|am\s+i\s+(?:correct|right)\s+in\s+(?:understanding|assuming))"
    r"\s*\??[\"')”’]*$", re.I)


# "So is the margin going to be 20%, right?" asks: an inverted or wh- start is a question whatever its tail
_INTERROGATIVE_START_RE = re.compile(
    r"^(?:(?:so|and|but|okay|ok|now|then|sir)[,\s]+)*"
    r"(?:is|are|was|were|will|would|can|could|do|does|did|should|shall|has|have|had|may|might|what|how|why|when"
    r"|which|where|who)\b", re.I)
_TAG_TAIL_RE = re.compile(r"[\s,]+(?:right|okay|ok|no|isn['’]t\s+it)\s*\?[\"')”’]*$", re.I)


def _ends_in_question(text: str) -> bool:
    return str(text or "").rstrip().rstrip("\"')”’").endswith("?")


def _is_courtesy_or_tag_question(sentence: str) -> bool:
    cleaned = str(sentence or "").strip().rstrip("\"')”’").strip()
    return bool(_COURTESY_OR_TAG_QUESTION_RE.search(cleaned))


def question_passage(statement: str) -> bool:
    """T-242: True only when ``statement`` ends in '?' AND has at most 2 sentences or at least half its
    sentences end in '?' (a trailing courtesy or tag question never counts towards the half)."""
    text = str(statement or "")
    if not _ends_in_question(text):
        return False
    sentences = _sentences(text)
    if _CONFIRMATION_QUESTION_RE.search(sentences[-1]):
        return True
    # fy27_v3 r2 re-grade (25 Nov): "... order book is INR610 crores, right?" and "Okay? So ... CAPEX ... right?"
    # are managers' answers with a tag tail; a declarative of 8+ words before the tag is a statement (Wolf)
    tail = _TAG_TAIL_RE.search(sentences[-1])
    if tail and len(sentences[-1][:tail.start()].split()) >= 8 \
            and not _INTERROGATIVE_START_RE.match(sentences[-1]):
        return False
    if len(sentences) == 2 and _is_courtesy_or_tag_question(sentences[-1]) and not _ends_in_question(sentences[0]):
        return False
    if len(sentences) <= 2:
        return True                     # an analyst checking his reading: "..., is that correct?" (Wolf, 394 80805)
    last_idx = len(sentences) - 1
    q_count = sum(
        1 for idx, sent in enumerate(sentences)
        if _ends_in_question(sent) and not (idx == last_idx and _is_courtesy_or_tag_question(sent))
    )
    return q_count * 2 >= len(sentences)


_HANDOVER_RE = re.compile(
    r"(?i:over\s+to\s+you|hand(?:ing)?\s+(?:it\s+)?over\s+to|pass(?:ing)?\s+(?:it\s+)?(?:on\s+)?to|"
    r"(?:i\s+)?(?:now\s+)?invite)\s*,?\s+(?:(?i:our|the)\s+[A-Za-z ,&-]{0,60}?,?\s+)?"
    r"(?:(?i:mr|ms|mrs|dr|shri|sh)\.?\s+)?(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
_NOT_A_NAME = {"Sir", "Madam", "Ma", "Mam", "All", "Everyone", "Him", "Her", "Them", "Management", "Moderator",
               "The", "Our", "Q", "Questions", "Question", "Mr", "Ms", "Mrs", "Dr", "Shri", "Sh", "Chief",
               "Financial", "Executive", "Managing", "Officer", "Director", "Chairman", "Head", "President", "Group",
               "Joint", "Whole", "Time", "Company", "Investor", "Relations", "Mrs"}


def handover_conflict(statement: str, speaker: str, page_list: list[tuple[int, str]], page: int) -> str:
    """T-242 (fy27_v3 ckpt_0002, Wolf): the name a hand-over just before the passage passes the floor to, when it is
    not the stored speaker ("Over to you, Alok" then the MD's remarks stored under the IR head); '' otherwise.
    Needs no roster; "Thanks, X" is not used (a manager thanks the analyst who asked)."""
    texts = dict(page_list)
    here = texts.get(int(page), "")
    head = " ".join(str(statement or "").split())[:60]
    flat = " ".join(here.split())
    pos = flat.find(head) if head else -1
    if pos < 0:
        return ""
    before = (" ".join(texts.get(int(page) - 1, "").split()) + " " + flat[:pos])[-400:]
    hits = list(_HANDOVER_RE.finditer(before))
    if not hits:
        return ""
    name = hits[-1].group("name")
    first = name.split()[0]
    if first in _NOT_A_NAME:
        return ""
    spoken = _norm_name(speaker)
    tokens = spoken.split()
    squashed = spoken.replace(" ", "")
    for part in name.lower().split():
        # the same person: a token, a nickname prefix ("Srini" for Srinivas) or a name printed without spaces
        if part in tokens or (len(part) >= 4 and any(t.startswith(part) for t in tokens)) or part in squashed:
            return ""
    return name


_LABEL_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?P<name>(?:(?:Mr|Ms|Mrs|Dr|Shri|Sh)\.?[ \t]+)?[A-Z][A-Za-z.\'-]*(?:[ \t]+[A-Z][A-Za-z.\'-]*){1,4})"
    r"[ \t]*:")


def last_label_before(statement: str, page_list: list[tuple[int, str]], page: int, back: int = 2) -> str:
    """T-242: the last printed two-word-or-longer speaker label before the passage, looking back up to ``back`` pages;
    '' when the passage is not found or no such label precedes it.  One-word labels are skipped: they are mostly
    section headings ("Aerospace:", "Defense:") or "Moderator"."""
    texts = dict(page_list)
    here = texts.get(int(page), "")
    head = str(statement or "").strip()[:40]
    pos = here.find(head) if head else -1
    if pos < 0:
        return ""
    for pg in range(int(page), int(page) - back - 1, -1):
        text = texts.get(pg, "")
        if not text:
            continue
        upto = text[:pos] if pg == int(page) else text
        names = [m.group("name") for m in _LABEL_LINE_RE.finditer(upto)
                 if len(_norm_name(m.group("name")).split()) >= 2
                 and not re.search(r"\b(?:code|scrip|symbol|isin|sub|ref|date|time|venue)\b", m.group("name"), re.I)]
        if names:
            return names[-1]
    return ""


_QA_ANNOUNCE_RE = re.compile(
    r"\b(?:next|first|last|one\s+more)\s+question\s+(?:is\s+)?from"
    r"|\btake\s+(?:a|one)\s+question\s+from"
    r"|\bline\s+of\b", re.I)


def preceding_question(statement: str, page_list: list[tuple[int, str]], page: int,
                       analysts: Iterable[str], pool: Iterable[str]) -> str:
    """T-242: the analyst's printed question a statement answers, as ``Q (<name>): <text>``; '' when none.

    The statement is found on its page (the same flexible match as ``find_observation_pos``) and the printed labels
    before it are walked back at most two pages, nearest first.  The turn that holds the passage (its own management
    label on a page break, or the analyst label when the answer is unlabelled) is skipped; the turn BEFORE it must be
    a questioner -- an analyst on the doc roster, or a speaker the moderator has just announced -- else the passage is
    opening remarks or answers a manager and gets nothing.  Its text must carry a question cue and is trimmed to 300
    characters.
    """
    texts = dict(page_list)
    here = str(texts.get(int(page), "") or "")
    pos = find_observation_pos(here, "", "", statement) if here else None
    if pos is None:
        return ""
    analyst_list = [_norm_name(a) for a in analysts if a]
    pool_list = [_norm_name(p) for p in pool if p]
    known = set(analyst_list) | set(pool_list)
    seq: list[tuple[str, str]] = []          # printed turns before the passage, nearest first
    for pg in range(int(page), int(page) - 3, -1):
        text = str(texts.get(pg, "") or "")
        if not text:
            continue
        upto = text[:pos] if pg == int(page) else text
        turns = extract_turns(upto, pg, known_names=known)
        for idx in range(len(turns) - 1, -1, -1):
            end = turns[idx + 1].start if idx + 1 < len(turns) else len(upto)
            seq.append((turns[idx].name, " ".join(upto[turns[idx].end:end].split())))
        if len(seq) >= 3:
            break
    if not seq:
        return ""
    own = _norm_name(seq[0][0])
    if own in _ROLE_WORDS and own not in _MODERATOR_NAMES:
        return ""                            # a generic "Management:" label carries no question
    idx = 1 if _name_matches_list(seq[0][0], pool_list) else 0
    if idx >= len(seq):
        return ""
    name, body = seq[idx]
    if _name_matches_list(name, pool_list):
        return ""                            # a management turn sits between the passage and any question
    if not _name_matches_list(name, analyst_list):
        announced = seq[idx + 1][1] if idx + 1 < len(seq) else ""
        if not _QA_ANNOUNCE_RE.search(announced):
            return ""                        # opening remarks: no questioner was given the floor yet
    if len(body) < 8 or not _QUESTION_CUE_RE.search(body):
        return ""
    return f"Q ({name}): {body[:300]}"


# --------------------------------------------------------------------------- T-242 statement window (26 Nov 2026)
#
# A statement must read as a self-contained passage and stay a verbatim substring of its page.  The model sometimes
# starts it mid-sentence ("across the portfolio and you will get ...") or on the sentence after the words that give
# it meaning ("this materializes", "both of these", "The brand").  Both fixes are structural and page-local: snap
# the start back to the sentence start inside the same speaker turn, then prepend the previous sentence of that turn
# when the first sentence only refers back to it.  A statement whose sentence or referent starts on an earlier page
# (a turn carried across a page break) is left alone and noted with ``referent_outside_window``, never cut from
# another page, so every stored statement stays a substring of its own page.

_SENTENCE_BREAK_RE = re.compile(r"[.!?]\s+")
_ABBREV_END_RE = re.compile(r"(?:Mr|Mrs|Ms|Dr|Shri|Sh|Prof|Sr|Smt|Er|Capt|vs|etc)\.$", re.I)
_DATE_LINE_RE = re.compile(
    r"^(?:\d{1,2}(?:st|nd|rd|th)?[\s-]+)?"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,.-]+\d{2,4}$"
    r"|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$", re.I)
_LEAD_IN_RE = re.compile(
    r"^(?:(?:so|and|but|yes|yeah|well|okay|ok|now|then|also|however|therefore|thus|hence|actually|basically|"
    r"essentially|finally|first|firstly|second|secondly|again)\b[,\s]+)+", re.I)
# A pronoun or demonstrative that opens the sentence only works if an earlier sentence names its referent.
_OPEN_ANAPHOR_RE = re.compile(
    r"^(?:it|they|such|both|this|these|those)\b"
    r"|^that\s+(?:is|was|will|would|can|could|has|have|had|means|does|did|seems|appears|remains|should|may|"
    r"might|must)\b", re.I)
# A demonstrative carrying a noun names that noun's referent elsewhere ("this increase", "that range").
_DEMONSTRATIVE_NOUN_RE = re.compile(
    r"\b(?:this|these|those|that)\s+(?!(?:year|years|quarter|quarters|half|month|months|week|weeks|period|periods"
    r"|time|fiscal|season|morning|afternoon|evening|regard|context|point|view|sense|stage|extent|respect|manner"
    r"|way|place|case|juncture|being|maybe|perhaps|the|and|or|for|with|from|which|who|when|where"
    r"|why|how|as|in|on|of|to|by|at|is|was|are|were|be|been|will|would|can|could|has|have|had|does|did"
    r"|[a-z]{4,}ly)\b)[A-Za-z][A-Za-z-]{2,}\b", re.I)
_BOTH_OF_RE = re.compile(r"\bboth\s+of\s+(?:these|those|them)\b", re.I)
_THE_SAME_RE = re.compile(
    r"\bthe\s+same\b(?!\s+(?:time|way|manner|extent|level|pace|rate|quarter|year|month|period|day|place)\b)", re.I)
# T-242 r3: a passage that opens on a connector/demonstrative (or a cut "we will get" figure) is a fragment
# when the previous sentence of the same turn holds its figure/subject.
_FRAGMENT_OPEN_RE = re.compile(
    r"^(?:and|but|so|also|now|then|this|that|these|those|it|almost|with|despite|however|hence|therefore)\b"
    r"|^we\s+(?:are\s+expecting|will\s+get|will\s+do|expect\s+to|are\s+going\s+to)\b", re.I)
# A definite sentence subject ("The brand has ...") whose noun this whitelist does not claim is an anaphor.
_DEFINITE_OPEN_RE = re.compile(r"[Tt]he\s+([a-z][a-z-]{2,})\b")
_SELF_CONTAINED_NOUNS = frozenset({
    "company", "companies", "business", "group", "board", "management", "bank", "firm", "organisation",
    "organization", "market", "markets", "industry", "sector", "economy", "government", "regulator", "quarter",
    "quarters", "year", "years", "period", "periods", "half", "month", "months", "week", "time", "results",
    "result", "revenue", "revenues", "margin", "margins", "guidance", "outlook", "growth", "demand", "capex",
    "debt", "cash", "portfolio", "strategy", "plan", "plans", "team", "order", "orders", "book", "sales",
    "cost", "costs", "opex", "profit", "profitability", "balance", "sheet", "asset", "assets", "liability",
    "liabilities", "equity", "capital", "turnover", "volume", "volumes", "price", "prices", "inflation", "rate",
    "rates", "policy", "project", "projects", "plant", "plants", "facility", "facilities", "product", "products",
    "segment", "segments", "customer", "customers", "client", "clients", "employee", "employees", "share",
    "shares", "dividend", "buyback", "listing", "consolidated", "standalone", "domestic", "international",
    "export", "exports", "import", "imports", "first", "second", "third", "last", "next", "current", "previous",
    "same", "other", "only", "entire", "whole", "total", "overall", "main", "key", "new", "old", "above",
    "below", "remaining", "full", "strong", "weak", "best", "worst", "average", "normal", "usual", "reported",
    "adjusted", "underlying", "net", "gross", "latest", "healthy", "muted", "lower", "higher", "larger",
    "smaller", "domestic.", "consolidated.",
})
_ANAPHOR_STOP = _CONTENT_STOP | {"this", "that", "these", "those", "both", "they", "them", "such", "same", "which"}
_PREV_SENTENCE_MAX_WORDS = 60
_WINDOW_NOTE = "referent_outside_window: the sentence or its referent starts on an earlier page or turn"
# A page's cover/registration block (phone, email, CIN, dial-in line) is not speech: never snap or widen across it.
_FRONT_MATTER_RE = re.compile(
    r"@|https?://|www\.|\b(?:mobile|e-?mail|telephone|phone|fax|website|cin|registered\s+office|"
    r"corporate\s*&\s*registered|disclaimer|dial[- ]?in|passcode|webcast|note\s*:)\b|"
    r"^[ \t]*(?:management|analysts?|participants?|corporate\s+participants|management\s+participants|"
    r"executives|panelists)\b|"
    r"\b\d{7,}\b|(?:[\d+()\-]\s*){10,}\d|\b\d{1,2}:\d{2}\s*(?:am|pm|ist)\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b", re.I | re.M)
_LABEL_ONLY_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:[•−\-*][ \t]*)?[A-Za-z][A-Za-z0-9&.'-]*(?:[ \t]+[A-Za-z0-9&.'-]+){0,3}[ \t]*:[ \t]*$")
# A block of honourific name lines is a participant roster, not speech.
_ROSTER_LINE_RE = re.compile(r"(?m)^[ \t]*(?:MR|MRS|MS|DR|SHRI|SMT)\.?\s+[A-Z]")


def _content_heads(text: str) -> set[str]:
    """Content words of ``text`` as 5-letter stems, so "increase"/"increases" share a head."""
    return {w.lower().rstrip("s")[:5] for w in _CONTENT_WORD_RE.findall(text)} - {
        w.rstrip("s")[:5] for w in _ANAPHOR_STOP}


def _ends_at_sentence_break(text: str) -> bool:
    """True when ``text`` ends at . ! or ? that is not an abbreviation dot."""
    stripped = text.rstrip()
    if not stripped or stripped[-1] not in ".!?":
        return False
    return not (stripped[-1] == "." and _ABBREV_END_RE.search(stripped))


def _page_prose_start(text: str) -> int:
    """Offset of the first prose line on a page (past the running header: title, date, "Page N of M")."""
    pos = 0
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s and not _PAGE_HEADER_LINE.match(s) and not re.fullmatch(r"\d{1,3}", s) \
                and not _DATE_LINE_RE.match(s) and (s[0].islower() or len(s) >= 80
                                                    or len(s.split()) >= 6 or bool(re.search(r"[.!?]\s", s))):
            return pos
        pos += len(line)
    return 0


def _front_matter(text: str) -> bool:
    """True when ``text`` is a page's cover/registration block or a bare colon label, never speech."""
    return bool(_FRONT_MATTER_RE.search(text) or _LABEL_ONLY_LINE_RE.search(text)
                or len(_ROSTER_LINE_RE.findall(text)) >= 2)


def _sentence_starts(page_text: str, body: int, pos: int) -> list[int]:
    """Sentence starts inside one turn, from the turn body up to ``pos`` (the turn body counts as one)."""
    starts = [body]
    for m in _SENTENCE_BREAK_RE.finditer(page_text, body, pos):
        if m.start() > body and page_text[m.start()] == "." \
                and _ABBREV_END_RE.search(page_text[max(body, m.start() - 8):m.start() + 1]):
            continue
        if m.end() <= pos:
            starts.append(m.end())
    return sorted(set(starts))


def _statement_span(page_text: str, statement: str) -> tuple[int, int] | None:
    """Span of ``statement`` on its page, or None when it cannot be located there."""
    st = statement.strip()
    pos = find_observation_pos(page_text, "", "", st)
    if pos is None:
        return None
    if page_text.startswith(st, pos):
        return pos, pos + len(st)
    tail = st[-40:] if len(st) > 40 else st
    pat = _flex_regex(tail)
    m = pat.search(page_text, pos) if pat else None
    if m:
        return pos, m.end()
    return None


def _window_body_start(page_text: str, pos: int, page_num: int, analysts: Iterable[str],
                       known_names: set[str], question_context: str = "") -> tuple[int, bool] | None:
    """Start of the speaker turn holding ``pos``: (offset, whether a printed label starts it), or None when the
    nearest label is an analyst/moderator and widening would cross into a question.

    ``extract_turns`` is not the only source: a designation label it rejects (``Mr. Karan Bhagat - MD & CEO,
    360 ONE WAM:``, rejected there because its hint carries a digit from "360") is still a printed turn boundary,
    so every label form is scanned up to ``pos`` and the nearest one bounds the turn.
    """
    labels: list[tuple[str, int]] = []
    for t in extract_turns(page_text, page_num, known_names=known_names):
        if t.end <= pos:
            labels.append((t.name, t.end))
    for m in _DESIG_TURN_RE.finditer(page_text, 0, pos):
        labels.append((m.group(1).strip(), m.end()))
    for m in _LABEL_LINE_RE.finditer(page_text, 0, pos):
        labels.append((m.group("name").strip(), m.end()))
    for m in _COLON_TURN_RE.finditer(page_text, 0, pos):
        raw = m.group(1).strip()
        if _is_valid_speaker_name(raw):
            labels.append((raw, m.end()))
        else:                    # a section heading ("Outlook: Optimistic for FY26"): speech starts next line
            line_end = page_text.find("\n", m.end())
            labels.append(("", min(pos, line_end + 1 if line_end != -1 else pos)))
    analyst_list = list(analysts)
    quoted = re.match(r"Q\s*\(([^)]+)\)\s*:", question_context or "")
    if quoted:
        analyst_list.append(quoted.group(1).strip())   # the stored question names its asker
    if labels:
        name, end = max(labels, key=lambda item: item[1])
        if end <= pos and name and ((analyst_list and _name_matches_list(name, analyst_list))
                                    or _norm_name(name) in _MODERATOR_NAMES):
            return None
        return end, True
    return _page_prose_start(page_text), False


def _first_sentence_has_anaphor(sentence: str) -> bool:
    """True when the sentence opens on, or carries, a demonstrative whose referent it does not name."""
    text = _LEAD_IN_RE.sub("", sentence.strip())
    if _OPEN_ANAPHOR_RE.match(text):
        return True
    definite = _DEFINITE_OPEN_RE.match(text)
    if definite and definite.group(1).lower() not in _SELF_CONTAINED_NOUNS:
        return True
    return bool(_DEMONSTRATIVE_NOUN_RE.search(sentence) or _BOTH_OF_RE.search(sentence)
                or _THE_SAME_RE.search(sentence))


def _only_anaphor(sentence: str) -> bool:
    """True when a sentence carries an anaphor and no content of its own (``It was good.``)."""
    if not _first_sentence_has_anaphor(sentence):
        return False
    return len(_content_heads(sentence)) <= 2


def widen_statement(statement: str, page_text: str, page_num: int = 0, question_context: str = "",
                    *, analysts: Iterable[str] = (), known_names: Iterable[str] = (),
                    ) -> tuple[str, bool, bool, str]:
    """T-242: snap ``statement`` back to its sentence start, then prepend its referent's sentence; page-local.

    Returns ``(statement, snapped, widened, note)``.  The statement stays a verbatim substring of ``page_text``:
    a start is only moved back inside the same printed speaker turn (never across a label, into an analyst's
    question, or before the page), the prepended sentence is the previous one of that turn and at most 60 words,
    and ``note`` is ``referent_outside_window: ...`` when either move is impossible.  A fragment opening on a
    connector/demonstrative (r3) also takes the previous sentence when that sentence holds a figure;
    ``snapped``/``widened`` are True only when the text changes.
    """
    st = str(statement or "")
    if not st.strip() or not page_text:
        return st, False, False, ""
    span = _statement_span(page_text, st)
    if span is None:
        return st, False, False, ""
    pos, stmt_end = span
    body = _window_body_start(page_text, pos, page_num, analysts, set(known_names), question_context)
    if body is None:                          # the nearest label is the analyst asking: never widen into a question
        return st, False, False, ""
    body_start, labelled = body
    prefix = page_text[body_start:pos]
    snapped = False
    if prefix.strip() and not _ends_at_sentence_break(prefix):
        starts = _sentence_starts(page_text, body_start, pos)
        if (len(starts) > 1 or labelled) and not _front_matter(page_text[starts[-1]:pos]):
            pos = starts[-1]
            bullet = re.match(r"[•−\-*][ \t]+", page_text[pos:pos + 4])
            if bullet:                     # a printed bullet is not part of the sentence
                pos += bullet.end()
            snapped = True
        else:
            return st, False, False, _WINDOW_NOTE   # the sentence began on an earlier page or in a page header
    elif not prefix.strip() and not labelled and st.lstrip()[:1].islower():
        return st, False, False, _WINDOW_NOTE       # the page opens on the middle of a carried sentence
    if snapped:
        st = page_text[pos:stmt_end].strip()
    first = (_sentences(st) or [""])[0]
    if not first:
        return st, snapped, False, ""
    starts = _sentence_starts(page_text, body_start, pos)
    previous = [s for s in starts if s < pos]
    if not previous:
        if _first_sentence_has_anaphor(first) and not _content_heads(first) & _content_heads(question_context):
            return st, snapped, False, _WINDOW_NOTE  # the turn (or the carried sentence) starts on an earlier page
        return st, snapped, False, ""
    prev_start = previous[-1]
    prev_sentence = page_text[prev_start:pos].strip()
    if _FRAGMENT_OPEN_RE.match(first) and _has_figure(prev_sentence) and prev_sentence \
            and len(prev_sentence.split()) <= _PREV_SENTENCE_MAX_WORDS \
            and not _front_matter(page_text[prev_start:pos]) and not _only_anaphor(prev_sentence):
        # T-242 r3: a fragment opening on a connector/demonstrative takes the previous sentence that holds its
        # figure/subject, even when the stored question already names the topic (row 39).
        return " ".join(page_text[prev_start:stmt_end].split()), snapped, True, ""
    if not _first_sentence_has_anaphor(first) or _content_heads(first) & _content_heads(question_context):
        return st, snapped, False, ""            # no referent, or the question already holds it
    if not prev_sentence or len(prev_sentence.split()) > _PREV_SENTENCE_MAX_WORDS \
            or _front_matter(page_text[prev_start:pos]):
        return st, snapped, False, _WINDOW_NOTE
    if _only_anaphor(prev_sentence):
        return st, snapped, False, _WINDOW_NOTE  # the previous sentence is also only an anaphor
    widened = " ".join(page_text[prev_start:stmt_end].split())
    return widened, snapped, True, ""


_LABEL_DESIGNATION_CORE = (
    r"MD|CEO|CFO|COO|CMD|CTO|CMO|ED|Director|Managing\s+Director|Joint\s+Managing\s+Director"
    r"|Executive\s+Director|Chief\s+\w+(?:\s+\w+)?|Company\s+Secretary|Chairman|Chairperson|President"
    r"|Vice\s+President|Head|Officer|Moderator|Operator|Coordinator|Host|CGM|AGM|GM")
_LABEL_DESIGNATION = rf"(?:{_LABEL_DESIGNATION_CORE})"
_STRIP_ROLE_RE = re.compile(rf"\b(?:{_LABEL_DESIGNATION_CORE}|Management|Analyst)\b", re.I)
_EMBEDDED_LABEL_RE = re.compile(
    r"^\s*(?P<name>(?:(?:Shri|Shree|Mr|Mrs|Ms|Dr)\.?\s+)?[A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3})"
    r"\s*[-,–—]\s*(?=[^:\n]{0,60}\b" + _LABEL_DESIGNATION + r"\b)[^:\n]{0,60}(?::|\n)\s*", re.I)


def strip_leading_speaker_label(
    statement: str,
    speaker: str = "",
    known_names: Iterable[str] | None = None,
) -> tuple[str, bool]:
    """T-242 r3/r4: drop a speaker label the model copied into the passage's own start; returns ``(text, changed)``.

    Only a leading label is removed: a printed person label carrying a designation and ending at a colon or a
    line break (``Shri <Name>, MD & CEO`` + newline, ``<Name> - CFO:``), or a non-heading speaker label naming
    a roster speaker or carrying a role word followed by a colon or a line break.  What remains is still a
    verbatim substring of its page.
    """
    st = str(statement or "")
    if not st.strip():
        return st, False
    changed = False
    label = " ".join(str(speaker or "").split())
    roster = [_norm_name(n) for n in (known_names or ()) if n]
    label_allowed = False
    if label and not _is_heading_label(label):
        if _STRIP_ROLE_RE.search(label):
            label_allowed = True
        elif roster:
            label_allowed = _name_matches_list(label, roster)
        elif known_names is None:
            label_allowed = bool(_is_valid_speaker_name(label, allow_all_caps_name=True))
    for _ in range(3):                     # a roster block can print more than one label line
        m = _EMBEDDED_LABEL_RE.match(st)
        if m is not None and _is_heading_label(m.group("name")):
            m = None
        if m is None and label_allowed:
            words = [re.escape(word) for word in label.split()]
            m = re.match(r"\s*" + r"\s+".join(words) + r"(?:\s*[:\-–—]\s*|\s*\n\s*)", st)
        if m is None or not st[m.end():].strip():
            break
        st = st[m.end():].lstrip()
        changed = True
    return st, changed


def attach_statement_speakers(rows: list[dict[str, Any]], pages: list[tuple[int, str]],
                              symbol: str = "", company_names: Iterable[str] = (),
                              call_period: str = "") -> dict[str, int]:
    """T-242: carry a page-break speaker, resolve/flag a junk label and a referentless reply, in place.

    A statement with no speaker is re-attributed from this doc's pages (last label before it on the page, else the
    last label of an earlier page); a carried analyst or moderator label is refused.  What remains is resolved to
    one full management name or marked unverified ``speaker_unresolved`` -- a company name is not a person and is
    never re-attributed to a nearby label -- and a short yes/no reply is marked unverified ``no_referent``.  An empty
    ``question_context`` is filled from ``preceding_question``; a model-written one is never replaced.  A statement
    made only of call logistics, a deferral or filler is dropped, and a prepared remark whose own relative period
    ("this quarter", "the year") has an empty ``question_context`` gains the call's ``call_period``.
    """
    stats = {"statements": 0, "carried": 0, "resolved": 0, "empty": 0, "unverified": 0, "question_filled": 0,
             "not_a_call": 0, "moderator": 0, "not_a_person": 0, "short_remarks": 0, "content_free": 0,
             "period_anchored": 0, "snapped": 0, "widened": 0, "noted": 0, "labels_stripped": 0}
    indexes = [i for i, row in enumerate(rows) if str(row.get("record_type") or "") == "statement"]
    if not indexes:
        return stats
    page_list = [(int(p), str(t or "")) for p, t in pages]
    doc_is_call = is_call_document(page_list)
    pool = management_pool(page_list)
    try:                                    # Eagle, v3 ckpt_0001 W (AMTECH p9): an analyst's name on an answer
        doc_ctx = build_doc_context(page_list)
        analysts = [n for n in doc_ctx.analyst_names if not _name_matches_list(n, pool)]
        questioners = list(doc_ctx.analyst_names) + list(doc_ctx.moderator_names)
        moderator_names = list(doc_ctx.moderator_names)
    except Exception:                       # noqa: BLE001 -- no roster: in-page cues only, as before
        analysts, questioners, moderator_names = [], [], []
    company_keys = {_company_key(name) for name in company_names if name}
    if symbol:
        company_keys.add(_company_key(symbol))
    company_keys.discard("")
    need: list[tuple[int, int, str, str, str, str]] = []
    retry: set[int] = set()
    notes: dict[int, str] = {}
    texts = dict(page_list)
    known_names = {_norm_name(n) for n in [*pool, *analysts, *moderator_names] if n}
    for i in indexes:
        row = rows[i]
        page = int(row.get("page") or 0)
        page_text = texts.get(page, "")
        speaker = " ".join(str(row.get("speaker") or "").split())
        statement, label_stripped = strip_leading_speaker_label(
            str(row.get("statement") or ""), speaker, known_names=known_names)
        if page_text:                       # T-242 (26 Nov): sentence snap + referent widen, page-local
            statement, snapped, widened, note = widen_statement(
                statement, page_text, page, str(row.get("question_context") or ""),
                analysts=analysts, known_names=known_names)
            if snapped or widened:
                # T-242 r3: a snap can pull a printed label line into the passage; drop it again
                statement, label_after = strip_leading_speaker_label(
                    statement, speaker, known_names=known_names)
                label_stripped = label_stripped or label_after
                row["statement"] = statement
                if snapped:
                    stats["snapped"] += 1
                if widened:
                    stats["widened"] += 1
            if note:
                notes[i] = note
                stats["noted"] += 1
        if label_stripped:                  # T-242 r3: a label copied into the passage is not its first words
            row["statement"] = statement
            stats["labels_stripped"] += 1
        speaker = " ".join(str(row.get("speaker") or "").split())
        if not speaker:
            retry.add(i)
        # every statement is checked against the printed labels (fy27_v3 ckpt_0002: two W were a speaker carried past
        # an in-document handover, "Over to you, Alok" + "Alok Gupta:")
        need.append((i, page, "", "", str(row.get("statement") or ""), ""))
    found = attribute_document(page_list, need) if need else {}
    for i in indexes:
        stats["statements"] += 1
        row = rows[i]
        speaker = " ".join(str(row.get("speaker") or "").split())
        reasons: list[str] = []
        if i in retry:
            carried, role = found.get(i, ("", ""))
            if carried and role not in ("analyst", "moderator"):
                if carried != speaker:
                    stats["carried"] += 1
                speaker = carried
                row["speaker"] = speaker
        elif speaker:
            labelled, role = found.get(i, ("", ""))
            if labelled and not _name_matches_list(speaker, [_norm_name(labelled)]) \
                    and not _name_matches_list(labelled, [_norm_name(speaker)]):
                if _name_matches_list(labelled, pool) and len(_norm_name(speaker).split()) > 1 \
                        and len(_norm_name(labelled).split()) > 1 and _company_key(labelled) not in company_keys \
                        and _name_matches_list(speaker, pool):
                    # only a switch between two named managers is corrected; a first name, a role word or an
                    # analyst keeps the rules below (a page with shifted labels must not verify an analyst)
                    stats["relabelled"] = stats.get("relabelled", 0) + 1
                    row["speaker_model"] = speaker
                    speaker = labelled
                    row["speaker"] = speaker
        if speaker and not row.get("speaker_model"):
            handed = handover_conflict(str(row.get("statement") or ""), speaker, page_list, int(row.get("page") or 0))
            if handed:
                reasons.append(f"speaker_handover: the floor was just handed to {handed!r}, not {speaker!r}")
            elif not pool:                         # no roster to relabel from (AXISCADES p6): flag, never relabel
                label = last_label_before(str(row.get("statement") or ""), page_list, int(row.get("page") or 0))
                if label and not _name_matches_list(label, questioners) \
                        and not _name_matches_list(speaker, [_norm_name(label)]) \
                        and not _name_matches_list(label, [_norm_name(speaker)]):
                    reasons.append(f"speaker_label_conflict: the last printed label before this passage is {label!r}")
        cleared_heading = False
        if speaker:
            norm_sp = _norm_name(speaker)
            if norm_sp in _MODERATOR_NAMES or "moderator" in norm_sp or "operator" in norm_sp \
                    or _name_matches_list(speaker, moderator_names, allow_single_token=False):
                reasons.append(f"speaker_moderator: {speaker!r} is the call moderator/operator, not management")
                stats["moderator"] += 1
            elif not is_person_speaker(speaker):
                # T-242 surprise audit W: "Profit After Tax" is a slide heading, not a person; never a speaker
                reasons.append(f"speaker_not_a_person: {speaker!r} is a heading or a line with digits, not a person")
                row["speaker"] = ""
                speaker = ""
                cleared_heading = True
                stats["not_a_person"] += 1
        if speaker:
            name, reason = resolve_speaker_name(speaker, pool, company_keys)
            if name != speaker:
                stats["resolved"] += 1
                row["speaker"] = name
            if reason:
                reasons.append(reason)
            elif analysts and not _name_matches_list(name, pool) and _name_matches_list(name, analysts):
                reasons.append(f"speaker_is_analyst: {name!r} asks questions on this call; a statement needs management")
        elif not cleared_heading:
            stats["empty"] += 1
            reasons.append("speaker_unresolved: no speaker label on this page or an earlier one; speaker_generic: empty speaker")
        if not doc_is_call:
            # T-242 surprise audit J (AGM minutes typed as a transcript): no call turns -> no management statement
            reasons.append("not_a_call: the document prints fewer than 3 speaker-label lines, so it is not a call")
            stats["not_a_call"] += 1
        # T-242: an empty question_context is filled with the analyst's printed question; the model's is never replaced
        if not str(row.get("question_context") or "").strip():
            question = preceding_question(str(row.get("statement") or ""), page_list,
                                          int(row.get("page") or 0), analysts, pool)
            if question:
                row["question_context"] = question
                stats["question_filled"] += 1
        # T-242 surprise audit J: a short figure-free remark carries no statement (praise, a hand-over pointer, or a
        # sentence whose only referent sits in the previous sentence and is not stored with the row)
        if short_remark_reason(str(row.get("statement") or ""), str(row.get("question_context") or "")):
            row["_drop"] = True
            stats["short_remarks"] += 1
        # fy27_v3 r2 re-grade (25 Nov): all 39 no_referent demotions had the matching question in question_context
        no_ref = "" if str(row.get("question_context") or "").strip() \
            else no_referent_reason(str(row.get("statement") or ""))
        if no_ref:
            reasons.append(no_ref)
        if question_passage(str(row.get("statement") or "")):
            # Eagle v3 spot check (24 Nov, 1,436 pages): 43 verified passages ending in '?' were analysts'
            # questions; a manager's "Why? Because ..." inside an answer does not END in '?' (Wolf);
            # narrowed (25 Nov) via question_passage so multi-sentence answers ending in a tag/courtesy stay verified.
            reasons.append("question_end: a passage ending in a question is not a management statement")
        if reasons:
            row["status_reason"] = "; ".join(p for p in (str(row.get("status_reason") or ""), *reasons) if p)
            if row.get("status") == "verified":
                row["status"] = "unverified"
                stats["unverified"] += 1
        if i in notes:                    # a detail note only: the window rule never changes a status
            row["status_reason"] = "; ".join(p for p in (str(row.get("status_reason") or ""), notes[i]) if p)
    effective_period = ""
    cq_match = _CALL_PERIOD_RE.match(" ".join(str(printed_call_period(page_list) or call_period or "").split()))
    if cq_match:
        effective_period = f"Q{int(cq_match.group(1))} FY{int(cq_match.group(2)) % 100:02d}"
    for i in indexes:                              # 394_v3 ckpt_0001 J (NLCINDIA p1): a filing letter's closing line
        row = rows[i]
        statement, label_after = strip_leading_speaker_label(
            str(row.get("statement") or ""), str(row.get("speaker") or ""), known_names=known_names)
        if label_after:                # T-242 r3: the row's speaker is resolved by now; strip its label too
            row["statement"] = statement
            stats["labels_stripped"] += 1
        # only the letter's own wording, whoever signs it: a company secretary's real opening remarks stay (Wolf);
        # T-242 (26 Nov): a statement made only of call logistics, a deferral or filler carries no statement
        letter = int(row.get("page") or 0) <= 2 and bool(_FILING_LINE_RE.search(statement))
        content_free = greeting_only(statement)
        if letter or content_free:
            row["_drop"] = True
            stats["filing_lines"] = stats.get("filing_lines", 0) + 1
            if content_free:
                stats["content_free"] += 1
        # T-242 (26 Nov, tx394 ckpt_0014 P / r2; r3): only an explicit own-period cue anchors a prepared remark;
        # a figure alone never takes the call quarter (a comparative's or a full year's figure is not the call's).
        if not row.get("_drop") and effective_period and not str(row.get("question_context") or "").strip() \
                and not str(row.get("period") or "").strip():
            anchor = anchored_period(statement, effective_period)
            if anchor:
                row["period"] = anchor
                row["period_kind"] = "actual"
                row["period_source"] = "call_period"
                stats["period_anchored"] += 1
    seen: set[tuple[Any, Any, str, str]] = set()        # Eagle v3 spot check: 19 statements stored twice on one page
    keep: list[dict[str, Any]] = []
    statement_at = set(indexes)
    for i, row in enumerate(rows):
        if row.get("_drop"):
            continue
        if i in statement_at:
            key = (row.get("doc_key"), row.get("page"), str(row.get("speaker") or ""),
                   " ".join(str(row.get("statement") or "").split()).lower())
            if key in seen:
                stats["duplicates"] = stats.get("duplicates", 0) + 1
                continue
            seen.add(key)
        keep.append(row)
    rows[:] = keep
    return stats


def load_universe_map(universe_csv: Path) -> dict[str, str]:
    """Map ``symbol`` -> ``cNN`` folder name from 1-based row position in ``universe_csv``."""
    mapping: dict[str, str] = {}
    with universe_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            sym = (row.get("symbol") or "").strip()
            if sym and sym not in mapping:
                mapping[sym] = f"c{idx:02d}"
    return mapping


def _copy_db_backup(src_path: Path, dst_path: Path) -> None:
    if src_path.resolve() == dst_path.resolve():
        raise ValueError("--out must be a copy path distinct from --obs")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    for suf in ("", "-wal", "-shm"):
        p = Path(str(dst_path) + suf)
        if p.exists():
            p.unlink()
    src = connect_ro(src_path, timeout_s=30.0)
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _is_transcript_doc(doc_key: str) -> bool:
    low = (doc_key or "").lower()
    return any(k in low for k in _TRANSCRIPT_KEY)


def run(
    obs_db: Path,
    stores_root: Path,
    universe_csv: Path,
    out_db: Path,
    *,
    limit: int | None = None,
) -> dict[str, object]:
    """Copy ``obs_db`` to ``out_db`` and populate ``speaker`` and ``speaker_role``."""
    t0 = time.perf_counter()
    _copy_db_backup(obs_db, out_db)
    uni = load_universe_map(universe_csv)

    con = sqlite3.connect(str(out_db))
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA journal_mode=WAL")
    cols = {r[1] for r in con.execute("PRAGMA table_info(observation)").fetchall()}
    if "speaker_role" not in cols:
        con.execute("ALTER TABLE observation ADD COLUMN speaker_role TEXT NOT NULL DEFAULT ''")
        con.commit()

    all_rows = con.execute(
        """
        SELECT observation_id, symbol, doc_key, page, record_type,
               value_text, printed_label, statement, speaker
        FROM observation
        ORDER BY symbol, doc_key, page, observation_id
        """
    ).fetchall()

    # Group transcript rows by symbol -> doc_key
    by_sym_doc: dict[str, dict[str, list[tuple[int, int, str, str, str, str]]]] = {}
    empty_seen = 0
    for oid, sym, dk, pg, rt, vt, pl, st, sp in all_rows:
        if not _is_transcript_doc(dk):
            continue
        is_empty = not (sp or "").strip()
        if is_empty:
            if limit is not None and empty_seen >= limit:
                continue
            empty_seen += 1
        elif limit is not None:
            # Under --limit, only process docs touched by the limited slice
            if sym not in by_sym_doc or dk not in by_sym_doc[sym]:
                continue
        by_sym_doc.setdefault(sym, {}).setdefault(dk, []).append((oid, pg, vt, pl, st, sp))

    updates: list[tuple[str, str, int]] = []
    stores_opened = 0
    docs_processed = 0

    for sym, docs in by_sym_doc.items():
        cnn = uni.get(sym)
        if not cnn:
            continue
        store_path = stores_root / cnn / f"{cnn}.db"
        if not store_path.exists():
            continue
        sc = connect_ro(store_path, timeout_s=30.0)
        stores_opened += 1
        try:
            dk_list = list(docs.keys())
            placeholders = ",".join("?" for _ in dk_list)
            pages_by_dk: dict[str, list[tuple[int, str]]] = {dk: [] for dk in dk_list}
            for dk, pg, txt in sc.execute(
                f"SELECT doc_key, page, text FROM doc_page WHERE doc_key IN ({placeholders}) ORDER BY doc_key, page",
                dk_list,
            ):
                pages_by_dk[dk].append((pg, txt or ""))
        finally:
            sc.close()

        for dk, doc_rows in docs.items():
            docs_processed += 1
            res = attribute_document(pages_by_dk.get(dk, []), doc_rows)
            for oid, (sp, role) in res.items():
                updates.append((sp, role, oid))

    con.executemany(
        "UPDATE observation SET speaker = ?, speaker_role = ? WHERE observation_id = ?",
        updates,
    )
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")

    # Summary stats over the copy
    num_total, num_with_sp = con.execute(
        """
        SELECT COUNT(*), SUM(CASE WHEN speaker != '' THEN 1 ELSE 0 END)
        FROM observation
        WHERE (lower(doc_key) LIKE '%concall_transcript%' OR lower(doc_key) LIKE '%transcript%')
          AND record_type = 'number'
        """
    ).fetchone()
    all_num_total, all_num_with_sp = con.execute(
        """
        SELECT COUNT(*), SUM(CASE WHEN speaker != '' THEN 1 ELSE 0 END)
        FROM observation
        WHERE record_type = 'number'
        """
    ).fetchone()
    role_counts = dict(
        con.execute(
            """
            SELECT speaker_role, COUNT(*)
            FROM observation
            WHERE (lower(doc_key) LIKE '%concall_transcript%' OR lower(doc_key) LIKE '%transcript%')
            GROUP BY speaker_role
            """
        ).fetchall()
    )
    num_role_counts = dict(
        con.execute(
            """
            SELECT speaker_role, COUNT(*)
            FROM observation
            WHERE (lower(doc_key) LIKE '%concall_transcript%' OR lower(doc_key) LIKE '%transcript%')
              AND record_type = 'number'
            GROUP BY speaker_role
            """
        ).fetchall()
    )
    con.close()

    elapsed = time.perf_counter() - t0
    return {
        "out_db": str(out_db),
        "elapsed_s": round(elapsed, 2),
        "stores_opened": stores_opened,
        "docs_processed": docs_processed,
        "rows_updated": len(updates),
        "transcript_number_total": num_total or 0,
        "transcript_number_with_speaker": num_with_sp or 0,
        "all_number_total": all_num_total or 0,
        "all_number_with_speaker": all_num_with_sp or 0,
        "transcript_role_counts": role_counts,
        "transcript_number_role_counts": num_role_counts,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-241 speaker attribution post-pass for transcript observations.")
    ap.add_argument("--obs", required=True, type=Path, help="Input observations SQLite database (read-only)")
    ap.add_argument("--stores-root", required=True, type=Path, help="Root folder containing cNN/cNN.db stores")
    ap.add_argument("--universe", required=True, type=Path, help="Universe CSV mapping 1-based rows to cNN")
    ap.add_argument("--out", required=True, type=Path, help="Output copy SQLite database path")
    ap.add_argument("--limit", type=int, default=None, help="Optional cap on empty-speaker transcript rows")
    args = ap.parse_args(argv)

    stats = run(args.obs, args.stores_root, args.universe, args.out, limit=args.limit)
    t_tot = stats["transcript_number_total"]
    t_sp = stats["transcript_number_with_speaker"]
    a_tot = stats["all_number_total"]
    a_sp = stats["all_number_with_speaker"]
    t_pct = (100.0 * t_sp / t_tot) if t_tot else 0.0
    a_pct = (100.0 * a_sp / a_tot) if a_tot else 0.0
    print(f"obs_speaker done in {stats['elapsed_s']:.2f}s -> {stats['out_db']}")
    print(f"  stores={stats['stores_opened']}, docs={stats['docs_processed']}, rows_updated={stats['rows_updated']}")
    print(f"  transcript number rows with speaker: {t_sp}/{t_tot} ({t_pct:.1f}%)")
    print(f"  all number rows with speaker:        {a_sp}/{a_tot} ({a_pct:.1f}%)")
    print(f"  transcript role counts (all):        {stats['transcript_role_counts']}")
    print(f"  transcript role counts (number):     {stats['transcript_number_role_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
