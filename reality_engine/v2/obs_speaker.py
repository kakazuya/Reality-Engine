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
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

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


_COVER_LETTER_RE = re.compile(
    r"\b(?:dear\s+sir|scrip\s+code|listing\s+department|compliance\s+department|"
    r"regulation\s+30|sub(?:ject)?\s*:)\b",
    re.I,
)


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
