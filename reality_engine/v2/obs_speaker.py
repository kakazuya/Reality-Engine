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
company-name / first-name / initials label to one full management name, and marks the row
unverified (``speaker_unresolved:``) or a referentless short reply (``no_referent:``).
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
    # Normalize curly vs straight quotes if present
    pat = pat.replace("'", "['’]").replace("’", "['’]")
    pat = pat.replace('"', '["“”]').replace("“", '["“”]').replace("”", '["“”]')
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


def resolve_speaker_name(speaker: str, pool: list[str],
                         company_keys: Iterable[str] = ()) -> tuple[str, str]:
    """T-242: resolve a company/first-name/initials label to one full management name; else keep it and say why.

    Returns ``(name, reason)``; ``reason`` is '' when the label (or its replacement) is a usable speaker.
    A full person name the roster does not list is kept as printed.
    """
    raw = " ".join((speaker or "").split()).strip()
    norm = _norm_name(raw)
    if not norm:
        return raw, ""
    keys = set(company_keys)
    if norm in _ROLE_WORDS or norm in _MODERATOR_NAMES:
        return raw, ""
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

_PERIOD_LABEL_RE = re.compile(r"\b(?:[QH][1-4]\s*FY\s*\d{2,4}|FY\s*\d{2,4}|[QH][1-4])\b", re.I)
_ABBREV_DOT_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Shri|Sh|Prof|Sr|Smt|Er|Capt|vs|etc)\.", re.I)


def _has_figure(text: str) -> bool:
    """A digit in the sentence, except a fiscal-period label ("Q2FY27 / H1FY27" is not a figure)."""
    return bool(re.search(r"\d", _PERIOD_LABEL_RE.sub(" ", text)))


def _greeting_sentence(sentence: str) -> bool:
    """One sentence that is only a greeting: the phrase plus a short tail with no figure ("Thank you, Vaibhav" is;
    "Thank you, Vaibhav, it is approximately INR5,400 crores ..." is not)."""
    match = _GREETING_SENTENCE_RE.match(sentence)
    if not match:
        return False
    tail = sentence[match.end():]
    return not _has_figure(tail) and len(re.findall(r"[A-Za-z]+", tail)) <= _GREETING_TAIL_WORDS


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


def _sentences(text: str) -> list[str]:
    """Split on . ! ? followed by space, keeping a title's dot inside its sentence ("to Mr. Sohoni ...")."""
    guarded = _ABBREV_DOT_RE.sub(lambda m: m.group(0)[:-1] + "\u2024", str(text or ""))
    return [x.replace("\u2024", ".").strip() for x in re.split(r"(?<=[.!?])\s+", guarded) if x.strip()]


def _boilerplate_sentence(sentence: str) -> bool:
    """A welcome or housekeeping sentence with no figure in it; only a sentence that says "welcome" may be long."""
    if _has_figure(sentence):
        return False
    if re.search(r"\bwelcome\b", sentence, re.I) and _WELCOME_OPEN_RE.match(sentence):
        return True
    return bool(_LOGISTICS_SENTENCE_RE.search(sentence))


def greeting_only(statement: str) -> bool:
    """T-242 (fy27_v3 ckpt_0002/0003 J): a passage made only of greetings, thanks, housekeeping and hand-overs
    carries no statement; any one sentence with substance keeps it."""
    sentences = _sentences(statement)
    return bool(sentences) and all(_greeting_sentence(x) or _boilerplate_sentence(x) for x in sentences)


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


def attach_statement_speakers(rows: list[dict[str, Any]], pages: list[tuple[int, str]],
                              symbol: str = "", company_names: Iterable[str] = ()) -> dict[str, int]:
    """T-242: carry a page-break speaker, resolve/flag a junk label and a referentless reply, in place.

    A statement with no speaker is re-attributed from this doc's pages (last label before it on the page, else the
    last label of an earlier page); a carried analyst or moderator label is refused.  What remains is resolved to
    one full management name or marked unverified ``speaker_unresolved`` -- a company name is not a person and is
    never re-attributed to a nearby label -- and a short yes/no reply is marked unverified ``no_referent``.
    """
    stats = {"statements": 0, "carried": 0, "resolved": 0, "empty": 0, "unverified": 0}
    indexes = [i for i, row in enumerate(rows) if str(row.get("record_type") or "") == "statement"]
    if not indexes:
        return stats
    page_list = [(int(p), str(t or "")) for p, t in pages]
    pool = management_pool(page_list)
    try:                                    # Eagle, v3 ckpt_0001 W (AMTECH p9): an analyst's name on an answer
        doc_ctx = build_doc_context(page_list)
        analysts = [n for n in doc_ctx.analyst_names if not _name_matches_list(n, pool)]
        questioners = list(doc_ctx.analyst_names) + list(doc_ctx.moderator_names)
    except Exception:                       # noqa: BLE001 -- no roster: in-page cues only, as before
        analysts, questioners = [], []
    company_keys = {_company_key(name) for name in company_names if name}
    if symbol:
        company_keys.add(_company_key(symbol))
    company_keys.discard("")
    need: list[tuple[int, int, str, str, str, str]] = []
    retry: set[int] = set()
    for i in indexes:
        row = rows[i]
        speaker = " ".join(str(row.get("speaker") or "").split())
        if not speaker:
            retry.add(i)
        # every statement is checked against the printed labels (fy27_v3 ckpt_0002: two W were a speaker carried past
        # an in-document handover, "Over to you, Alok" + "Alok Gupta:")
        need.append((i, int(row.get("page") or 0), "", "", str(row.get("statement") or ""), ""))
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
        if speaker:
            name, reason = resolve_speaker_name(speaker, pool, company_keys)
            if name != speaker:
                stats["resolved"] += 1
                row["speaker"] = name
            if reason:
                reasons.append(reason)
            elif analysts and not _name_matches_list(name, pool) and _name_matches_list(name, analysts):
                reasons.append(f"speaker_is_analyst: {name!r} asks questions on this call; a statement needs management")
        else:
            stats["empty"] += 1
            reasons.append("speaker_unresolved: no speaker label on this page or an earlier one")
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
    for i in indexes:                              # 394_v3 ckpt_0001 J (NLCINDIA p1): a filing letter's closing line
        row = rows[i]
        # only the letter's own wording, whoever signs it: a company secretary's real opening remarks stay (Wolf)
        if (int(row.get("page") or 0) <= 2 and _FILING_LINE_RE.search(str(row.get("statement") or ""))) \
                or greeting_only(str(row.get("statement") or "")):
            row["_drop"] = True
            stats["filing_lines"] = stats.get("filing_lines", 0) + 1
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
