"""Rule-based earnings-call statement extractor -> table transcript_statement (T-049 B). No model, no OCR, no network.

CLI: python -m reality_engine.pilot3.transcripts --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--sandbox-root DIR]

One row per sentence spoken by management (md/ceo/cfo/coo/chairman/mgmt) in a held earnings-call transcript; speaker, role,
section (prepared|qa), topic tags from lexicon/topics.yaml, numbers with unit and period, the exact sentence.
Analysts, Investor Relations, the moderator and boilerplate headers/footers are not stored. A sentence that is cut by a page break is
stored on the page where it starts with is_fragment=1; quote is always a literal slice of that page's text.
Page text comes from doc_text (method script_text); pages marked needs_ocr are skipped and counted.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import yaml

from . import schema
from .kpi import LEX_DIR, SANDBOX_ROOT, VAL_RX, _UNIT_BY_SUFFIX, parse_periods, to_float, _norm_cur, profile, _sector_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcript_statement (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, isin TEXT, doc_key TEXT NOT NULL, call_date TEXT, call_period TEXT, page INTEGER NOT NULL,
  seq INTEGER NOT NULL, speaker TEXT NOT NULL, role TEXT NOT NULL, section TEXT NOT NULL,
  topics TEXT NOT NULL, period_discussed TEXT, period_source TEXT, numbers_json TEXT NOT NULL,
  statement TEXT NOT NULL, quote TEXT NOT NULL, is_fragment INTEGER NOT NULL DEFAULT 0,
  entities TEXT NOT NULL DEFAULT '', answer_turn INTEGER NOT NULL DEFAULT 0,
  known_at TEXT, known_at_source TEXT, extractor_rule TEXT NOT NULL,
  UNIQUE(symbol, doc_key, page, seq)
);
CREATE INDEX IF NOT EXISTS ix_ts_sym_call ON transcript_statement(symbol, call_date);
CREATE INDEX IF NOT EXISTS ix_ts_turn ON transcript_statement(symbol, doc_key, answer_turn);
CREATE TABLE IF NOT EXISTS transcript_question (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, isin TEXT, doc_key TEXT NOT NULL, call_date TEXT, call_period TEXT, page INTEGER NOT NULL,
  analyst TEXT, firm TEXT, question TEXT NOT NULL, topics TEXT NOT NULL, entities TEXT NOT NULL DEFAULT '',
  answer_turn INTEGER NOT NULL DEFAULT 0, known_at TEXT, known_at_source TEXT, extractor_rule TEXT NOT NULL
);
CREATE VIEW IF NOT EXISTS analyst_question AS
  SELECT symbol, call_date, analyst, firm, question, topics, entities, call_period, doc_key, answer_turn
  FROM transcript_question;
CREATE VIEW IF NOT EXISTS analyst_questions AS SELECT * FROM analyst_question;
"""

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
# A speaker's name may open with an initial: "G Vivek:" (GS Investment) and "S. RANGANATHAN" are real labels
# the round-7 extractor missed, so the analyst's words ran on as management's (T-164 r8).
_SPEAKER_NAME = r"(?:[A-Z]\.?[ \t]+)?[A-Z][A-Za-z.'’\-]+(?:[ \t]+[A-Za-z.'’\-]+){0,4}"
SPEAKER_RX = re.compile(r"^[ \t]*(" + _SPEAKER_NAME + r"):(?=[ 	]|$)", re.M)
SPEAKER_MID_RX = re.compile(r"(?<=[.?!] )([A-Z][A-Za-z.'’\-]+(?: [A-Z][A-Za-z.'’\-]+){1,3}):(?=[ 	]|$)", re.M)
# a person name as printed in a participant block or an introduction, an initial-led one included
_PERSON_NAME = (r"(?:[A-Z]\.?\s+[A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3}"
                r"|[A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){1,3})")
# a bare name line, no colon: "Rishi Basu" / "Salil Parekh" (T-056; only used when colon marks are few)
NAME_ONLY_RX = re.compile(r"^[ \t]*(" + _PERSON_NAME + r")[ \t]*$", re.M)
SENTENCE_START_RX = re.compile(r"^[\"“‘']?[A-Z][a-z]+(?:[^.!?]*[a-z])")
# "1. Albinder Singh Dhindsa – Chief Executive Officer, Eternal Limited" (one-line participant entry)
NUM_TITLE_RX = re.compile(r"^[ \t]*\d{1,2}[.)]\s*(" + _PERSON_NAME + r")"
                          r"\s*[–—-]\s*(.+?)[ \t]*$", re.M)
TITLE_WORD_RX = re.compile(r"\b(?:chief|managing director|\bmd\b|\bceo\b|\bcfo\b|\bcoo\b|president|\bhead\b|director|"
                           r"vice president|investor relations|company secretary|executive)\b", re.I)
# participant-block headings, matched on the whole line (T-056: the block names management's titles and the
# analysts/journalists, so a speaker with no title in the transcript is still placed)
PARTICIPANT_HEADINGS = (
    ("moderator", re.compile(r"(?:call |conference )?(?:moderator|operator|host)", re.I)),
    ("analyst", re.compile(r"(?:research )?analysts?|j\w*nalists?|media|"
                           r"(?:q\s*&\s*a )?participants? from (?:the )?media", re.I)),
    ("mgmt", re.compile(r"(?:corporate |company |other |key )?participants?|management(?: representatives?| team)?|"
                        r"company representatives?|board of directors|key managerial personnel", re.I)),
)
# "From Eternal's management team, we have with us today Albinder Singh Dhindsa, Akshant Goyal and Kunal Swarup"
MOD_TEAM_RX = re.compile(r"\bwith us today\b[ \t]*,?[ \t]*([^.\n]{3,240})", re.I)
# DOI layout (BEL 30.07.2025): the heading shares its line with the first entry ("MANAGEMENT: MR. MANOJ JAIN –
# CHAIRMAN AND MANAGING DIRECTOR") and every entry starts with a title prefix (T-164 r7).
DOI_HEAD_RX = re.compile(r"^(management|moderator|analysts?|journalists?|participants?)\s*:\s*(.*)$", re.I)
DOI_ENTRY_RX = re.compile(r"^(?i:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Shri|Smt\.?)\s+(" + _PERSON_NAME + r")")
PERSON_RX = re.compile(r"[A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){1,3}")
# a line in a participants block that is a document label, not a person ("Investor Call Transcript" was stored as
# a speaker in a cover-letter page by the name look-ahead)
NON_NAME_RX = re.compile(r"\b(?:transcript|call|conference|investor|investors|presentation|earnings|results|"
                         r"dialogue|session)\b", re.I)
PAGE_NO_RX = re.compile(r"^[ \t]*Page \d+ of \d+[ \t]*$", re.M)
DIGITS_RX = re.compile(r"\d+")
DATE_LINE_RX = re.compile(r"^[ \t]*(?:" + MONTHS + r") \d{1,2}, \d{4}[ \t]*$", re.M)
CALL_DATE_RX = re.compile(r"(" + MONTHS + r") (\d{1,2}), (\d{4})")
ABBR = ("Mr", "Ms", "Mrs", "Dr", "Rs", "No", "vs", "Inc", "Ltd", "approx", "Sr", "Jr", "St", "Co", "Corp", "etc", "i.e", "e.g", "FY", "Q")
SENT_END_RX = re.compile(r"(?<=[.?!])[\"”’')]*\s+(?=[\"“‘'(A-Z0-9₹$])")
NOT_SPEAKERS = ("Corporate", "Registered", "Email", "Website", "Phone", "Tel", "Note", "Disclaimer", "Source", "CIN", "Page", "Symbol", "Scrip", "SCRIP", "Sub", "Date", "Ref", "MANAGEMENT", "To", "Dear", "Subject", "Attention")
# Words in an analyst's firm line ("Axis Capital", "Goldman Sachs", "ICICI Securities"); the firm is not the
# analyst's name (and its words must not poison the entity set) (T-164 r8).
_ANALYST_FIRM_WORDS = {"capital", "securities", "security", "investment", "investments", "bank", "financial",
                       "finance", "research", "partners", "advisors", "advisers", "broking", "limited", "ltd",
                       "inc", "llc", "services", "markets", "asset", "management", "global", "equities", "fund"}


def _not_speaker(name: str) -> bool:
    low = name.lower()
    # "Management:" is a real speaker label in a DOI call; "MANAGEMENT:" (the block heading) is not
    if low == "management" and name != "MANAGEMENT":
        return False
    return any(low.startswith(j) for j in (n.lower() for n in NOT_SPEAKERS))
QA_START_RX = re.compile(r"question[- ]and[- ]answer|first question|open the floor|q ?& ?a session|take (up )?(the )?questions", re.I)
NAME = r"(" + _PERSON_NAME + r")"
ANALYST_INTRO_RX = re.compile(r"(?i:line of|question (?:is )?from|next question comes from|first question is from)\s+(?i:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*" + NAME)
HOST_INTRO_RX = re.compile(r"(?i:over to|hand (?:the )?conference over to|hand it over to)\s+(?i:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*" + NAME + r"\s+(?i:from|of)\s+")
MGMT_INTRO_RX = re.compile(r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3})\s*[,–-]\s*(?:the\s+)?"
                           # "Vice Chairman and Managing Director", "COO and CFO": words may precede the role
                           r"(?:[A-Za-z][\w.'’\-]*\s+){0,5}?(Managing Director|MD|CEO|Chief Executive|CFO|"
                           r"Chief Financial|COO|Chief Operating|Head of Investor|Whole[- ]time Director|"
                           r"President|Executive Director|Group Chief)", re.I)
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def _sector_topics(sector: str | None) -> list[dict]:
    """The topic vocabulary of a sector family (T-194): a lexicon file's own ``topics:`` list when the file's
    ``sectors`` name the company's family.  Without a sector (no profile) no sector tag applies."""
    if not sector:
        return []
    out: list[dict] = []
    for path in sorted(LEX_DIR.glob("*.yaml")):
        if path.name == "topics.yaml":
            continue
        try:
            family = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        scopes = {str(s).lower() for s in (family.get("sectors") or [])}
        if sector.lower() not in scopes:
            continue
        out += [item for item in (family.get("topics") or []) if item.get("tag") and item.get("patterns")]
    return out


def _compiled(entries: list[dict]) -> list[tuple]:
    return [(t["tag"], [re.compile(p, re.I) for p in t["patterns"]], t.get("companies")) for t in entries]


def load_topics(sector: str | None = None):
    """General tags from ``topics.yaml`` plus, for a company of a lexicon family, that family's own tags (T-194)."""
    d = yaml.safe_load((LEX_DIR / "topics.yaml").read_text(encoding="utf-8"))
    return _compiled(list(d["topics"]) + _sector_topics(sector)), d.get("people", {})


def tag_topics(topics, company: str, sentence: str) -> list[str]:
    tags = []
    for tag, rxs, comps in topics:
        if comps and company not in comps:
            continue
        if any(rx.search(sentence) for rx in rxs):
            tags.append(tag)
    return tags or ["other"]


def _norm_name(n: str) -> str:
    return re.sub(r"[^a-z ]", "", n.lower()).strip()


def _same_person(a: str, b: str) -> bool:
    ta, tb = _norm_name(a).split(), _norm_name(b).split()
    if not ta or not tb:
        return False
    if set(ta) <= set(tb) or set(tb) <= set(ta):
        return True
    if ta[0] == tb[0] and (ta[-1][:4] == tb[-1][:4]):
        return True
    # OCR / spelling slip in one name of a known person ("Stish Pai" <-> "Satish Pai", "Dev" <-> "Devinder"):
    # same surname and a first name that is a prefix or nearly the same word.  A different first name with a
    # shared surname ("Sandeep Jain" / "Manish Jain") is not a match.
    if ta[-1] == tb[-1] and len(ta[-1]) >= 3:
        return (ta[0].startswith(tb[0]) or tb[0].startswith(ta[0])
                or difflib.SequenceMatcher(None, ta[0], tb[0]).ratio() >= 0.8)
    return False


def call_period_of(title: str, texts: list[str]) -> str | None:
    head = (title or "") + " \n" + " \n".join(texts[:2])
    ps = [p for p in parse_periods(head) if p.canon.startswith("Q")]
    if ps:
        return ps[0].canon
    m = re.search(r"FY\s?['’]?\s?(\d{2,4})\s+(first|second|third|fourth)\s+quarter", head, re.I) or \
        re.search(r"(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:the\s+)?(?:financial year|FY)\s?['’]?\s?(\d{2,4})", head, re.I)
    if m:
        g = m.groups()
        # group order depends on which alternative matched: (number, word) or (word, number)
        a, b = (g[0], g[1]) if g[0].isdigit() else (g[1], g[0])
        return f"Q{QUARTER_WORDS[b.lower()]}FY{int(a[-2:]):02d}"
    return None


def quarter_end_of(label: str | None) -> str | None:
    """The last day of the quarter a ``QxFYyy`` label names, or None for any other label."""
    m = re.fullmatch(r"Q([1-4])FY(\d{2})", (label or "").strip().upper())
    if not m:
        return None
    fy = 2000 + int(m.group(2))
    return {"1": f"{fy - 1}-06-30", "2": f"{fy - 1}-09-30", "3": f"{fy - 1}-12-31", "4": f"{fy}-03-31"}[m.group(1)]


# a results/earnings call is about the company's own reported quarter; an acquisition, investor-day or
# capital-markets call is about a transaction or a plan and reports no quarter of the company (T-192 round 4)
_RESULTS_CALL = re.compile(r"\b(?:earnings?|results?)\b", re.I)
_CALL_WORD = re.compile(r"\b(?:call|conference|transcript)\b", re.I)


def reports_results(title: str | None) -> bool:
    """Does this call title name an earnings / results call?  An acquisition or investor-day call does not."""
    return bool(_RESULTS_CALL.search(title or ""))


def non_results_call(title: str | None) -> bool:
    """A title that is a call but not a results/earnings one: an acquisition, investor-day or similar briefing.

    A title that does not name a call at all is unknown, not evidence: the old filing-record rule stands for it."""
    return bool(title and _CALL_WORD.search(title) and not reports_results(title))


def filing_quarter(known_at: str | None) -> str | None:
    """The quarter a filing reports, from its own filing record: Apr-Jun files Q4, Jul-Sep Q1, Oct-Dec Q2, Jan-Mar
    Q3 of the fiscal year that ends in the following March."""
    m = re.match(r"(\d{4})-(\d{2})", (known_at or "")[:10])
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if 4 <= month <= 6:
        return f"Q4FY{year % 100:02d}"
    if 7 <= month <= 9:
        return f"Q1FY{(year + 1) % 100:02d}"
    if 10 <= month <= 12:
        return f"Q2FY{(year + 1) % 100:02d}"
    return f"Q3FY{year % 100:02d}"


def call_period_ok(period: str | None, known_at: str | None, title: str | None = None) -> str | None:
    """The period a call reports: the label its own text gives when that quarter had closed by the filing, else the
    quarter the filing record names.  A call cannot report a quarter that ends after it was filed, so a year the
    text happens to mention (a long-range ambition, a target year) never becomes the call's period (T-192).

    ``title`` names the call: only an earnings/results call takes the filing quarter, so an acquisition or
    investor-day call keeps ``None`` instead of borrowing the results quarter that closed near it (T-192 round 4).
    A document whose title the store does not hold keeps the old rule: unknown is not evidence of an acquisition."""
    end = quarter_end_of(period)
    if end and end <= (known_at or "")[:10]:
        return period
    if non_results_call(title):
        return None
    return filing_quarter(known_at)


def call_date_of(first_page: str, known_at: str | None) -> str | None:
    m = CALL_DATE_RX.search(first_page[:1500])
    if m:
        mon = [x.lower() for x in MONTHS.split("|")].index(m.group(1).lower()) + 1
        return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    return (known_at or "")[:10] or None


def boilerplate_lines(pages: list[str]) -> set[str]:
    """Lines that repeat on at least 60% of the pages (company name, running headers).  Digits are normalised
    before the comparison, so a footer whose page number changes ("… Limited 3", "… Limited 4") is one line
    (T-056 review)."""
    c = Counter()
    for t in pages:
        for l in {DIGITS_RX.sub("#", x.strip()) for x in t.split("\n") if x.strip()}:
            c[l] += 1
    n = max(len(pages), 1)
    return {l for l, k in c.items() if k >= max(3, 0.6 * n) and len(l) < 80}


def mask_noise(text: str, boiler: set[str]) -> str:
    """Same-length copy of text with page numbers, date lines and repeated headers blanked (offsets stay valid)."""
    w = list(text)
    def blank(a, b):
        for i in range(a, b):
            if w[i] != "\n":
                w[i] = " "
    for rx in (PAGE_NO_RX, DATE_LINE_RX):
        for m in rx.finditer(text):
            blank(m.start(), m.end())
    pos = 0
    for line in text.split("\n"):
        if DIGITS_RX.sub("#", line.strip()) in boiler and not SPEAKER_RX.match(line):
            blank(pos, pos + len(line))
        pos += len(line) + 1
    return "".join(w)


def split_sentences(seg: str, base: int):
    """[(start, end)] absolute offsets of sentences in seg (seg starts at base). Abbreviation/decimal safe."""
    spans, start = [], 0
    for m in SENT_END_RX.finditer(seg):
        pre = seg[max(0, m.start() - 8):m.start()]
        last = re.findall(r"([A-Za-z.]+)\.$", pre)
        if last and last[-1].rstrip(".") in ABBR:
            continue
        if re.search(r"\b[A-Z]\.$", pre):       # initials
            continue
        spans.append((base + start, base + len(seg[:m.end()].rstrip())))
        start = m.end()
    spans.append((base + start, base + len(seg)))
    return [(a, b) for a, b in spans if seg[a - base:b - base].strip()]


def numbers_in(sentence: str, default_period: str | None):
    out = []
    pers = parse_periods(sentence)
    spans = [(p.start, p.end) for p in pers]
    for m in VAL_RX.finditer(sentence):
        if any(a <= m.start("num") < b for a, b in spans):
            continue
        cur, suf = _norm_cur(m.group("cur")), (m.group("suf") or "").lower().rstrip(".")
        base = _UNIT_BY_SUFFIX.get(suf)
        if not cur and not base:
            continue
        v = to_float(m.group("num"))
        if v is None:
            continue
        if cur == "usd" and base == "mn":
            unit = "usd_mn"
        elif cur == "usd" and base == "bn":
            unit = "usd_bn"
        elif cur == "usd":
            unit = "usd"
        elif base == "inr_cr" or (cur == "inr" and base in (None, "inr_cr")):
            unit = "inr_cr" if base == "inr_cr" else "inr"
        else:
            unit = base or cur
        # nearest period in the sentence (after the number first), else None
        after = [p for p in pers if p.start >= m.end() and p.start - m.end() <= 40]
        before = [p for p in pers if p.end <= m.start() and m.start() - p.end <= 40]
        per = (after or before[-1:] or [None])[0]
        out.append({"value": v, "unit": unit, "period": per.canon if per else default_period, "raw": m.group(0).strip(),
                    "period_source": "sentence" if per else "call"})
    return out


def role_of(speaker: str, company: str, people: dict, analysts: list[str], mgmt: dict[str, str]) -> str:
    if speaker.lower().startswith("moderator") or speaker.lower() == "operator":
        return "moderator"
    if speaker.lower() in ("participant", "analyst", "questioner", "unidentified participant", "unidentified speaker"):
        return "analyst"
    if speaker.lower() in ("management", "company representative", "company management"):
        return "mgmt"
    for k in people.get(company, []):
        if _same_person(k["name"], speaker):
            return k["role"]
    for n, r in mgmt.items():
        if _same_person(n, speaker):
            return r
    if any(_same_person(a, speaker) for a in analysts):
        return "analyst"
    return "unknown"


def _title_role(title: str) -> str:
    t = (title or "").lower()
    # A DOI block prints "DIRECTOR, INVESTOR \nRELATIONS": the title wraps, so "investor" alone is enough.  An IR
    # or moderator title is never promoted to management (T-164 r8).
    if "investor" in t or re.search(r"(?:^|\W)i\.?r\.?(?:\W|$)", t) or "corporate communication" in t:
        return "ir"
    if "moderator" in t or "host" in t.split():
        return "moderator"
    if "chief financial" in t or t.startswith("cfo"):
        return "cfo"
    if "head of investor" in t or "investor relations" in t:
        return "ir"
    if "managing director" in t or t.startswith("md") or "chief executive" in t or t.startswith("ceo"):
        return "md"
    return "mgmt"       # COO, President, Executive Director, Whole-time Director


def _heading_class(line: str) -> str | None:
    """'mgmt' / 'analyst' / 'moderator' for a participant-block heading line, else None."""
    s = line.strip(" \t:")
    if not s or len(s) > 60 or len(s.split()) > 6:
        return None
    for kind, rx in PARTICIPANT_HEADINGS:
        if rx.fullmatch(s):
            return kind
    return None


def participants(pages: list[str], doi_mgmt: dict[str, str] | None = None) -> tuple[dict[str, str], list[str], set[str]]:
    """(management name -> role, analysts, every name named) from the participant blocks of the first pages.

    A block is a heading line (``CORPORATE PARTICIPANTS``, ``Management representatives:``, ``ANALYSTS``,
    ``JOURNALISTS``) and then name/title entries: a name line followed by its title line, or one line
    "1. Name – Title".  Management titles go through ``_title_role``; a name under an analysts/journalists
    heading is an analyst and is never stored (T-056).  A DOI-layout block shares the heading line with its first
    entry; those names are collected in ``doi_mgmt`` too, because the caller keeps them out of the speaker map
    unless the call itself put the management head in the analyst seat (T-164 r7)."""
    mgmt: dict[str, str] = {}
    analysts: list[str] = []
    names: set[str] = set()
    kind: str | None = None            # a block that starts on one page continues on the next
    doi_block = False                  # only a heading that shares its line with an entry opens the DOI layout
    for text in pages[:3]:
        lines = [l.strip() for l in text.split("\n")]
        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            if not line:
                continue
            inline = DOI_HEAD_RX.match(line)
            if inline:
                kind = _heading_class(inline.group(1)) or kind
                line = inline.group(2).strip()
                # a DOI-layout block may print its heading alone and then "Mr. Name – Title" entries
                # (ANANDRATHI 13.04.2022): the entries are read either way (T-164 r8)
                doi_block = kind == "mgmt"
                if not line:
                    continue
            head = _heading_class(line)
            if head:
                kind = head
                doi_block = False
                continue
            if kind is None:
                continue
            doi = DOI_ENTRY_RX.match(line) if doi_block and kind == "mgmt" else None
            if doi:
                name = " ".join(doi.group(1).split())
                if kind == "mgmt":
                    role = _title_role(line[doi.end():])
                    if doi_mgmt is not None:
                        doi_mgmt[name] = role    # the caller decides whether to trust the block (T-164 r7)
                    else:
                        mgmt.setdefault(name, role)
                        names.add(name)
                continue                # a moderator/as host is not management and is never stored
            m = NUM_TITLE_RX.match(line)
            if m:
                name, title = " ".join(m.group(1).split()), m.group(2)
            elif NAME_ONLY_RX.fullmatch(line) and not TITLE_WORD_RX.search(line):
                name, title = " ".join(line.split()), ""
                j = next((k for k in range(i, min(i + 3, len(lines))) if lines[k]), None)
                if j is not None and TITLE_WORD_RX.search(lines[j]) and not _heading_class(lines[j]):
                    title, i = lines[j], j + 1     # the title line, consumed with its name
            else:
                continue
            if NON_NAME_RX.search(name):
                continue
            # a legal company name in the block is not a participant, and its words must not poison the entity
            # set ("Tata Consumer Products Limited" made "Tata" a person token and lost "Tata Copper Plus")
            # (T-164 r8)
            if any(w.lower().strip(".,") in {"limited", "ltd", "inc", "corp", "corporation", "private", "pvt"}
                   for w in name.split()):
                continue
            # "Axis Capital" / "ICICI Securities" is the analyst's firm, not the analyst (T-164 r8)
            if kind == "analyst" and any(w.lower().strip(".,") in _ANALYST_FIRM_WORDS for w in name.split()):
                continue
            names.add(name)
            if kind == "mgmt":
                mgmt.setdefault(name, _title_role(title))
            elif kind == "analyst":
                analysts.append(name)
    return mgmt, analysts, names


def moderator_names(full: str) -> list[str]:
    """Names a moderator introduces in the "management team ... with us today A, B and C" sentence."""
    out: list[str] = []
    for m in MOD_TEAM_RX.finditer(full):
        for part in re.split(r",|\band\b|;|&", m.group(1)):
            name = part.strip(" .:()'\"“”")
            if PERSON_RX.fullmatch(name) and not TITLE_WORD_RX.search(name):
                out.append(" ".join(name.split()))
    return out


def name_line_counts(pages: list[str]) -> Counter:
    """How often each bare name line repeats in a document (a speaker mark needs 3 when it is not introduced)."""
    c: Counter = Counter()
    for text in pages:
        for line in text.split("\n"):
            m = NAME_ONLY_RX.fullmatch(line)
            if m and not TITLE_WORD_RX.search(m.group(1)) and not NON_NAME_RX.search(m.group(1)):
                c[" ".join(m.group(1).split())] += 1
    return c


def _starts_speech(line: str) -> bool:
    """A speaker's bare name is followed by speech, not by a title or an affiliation (the participant block)."""
    if len(line) < 25 or not SENTENCE_START_RX.match(line):
        return False
    return not (len(line) < 80 and TITLE_WORD_RX.search(line))


def name_marks(text: str, counts: Counter, known: set[str]) -> list[tuple[int, int, str]]:
    """Speaker marks on bare name lines: a name from the participant block, or a line repeated 3+ times in the
    document, when speech follows it (T-056; the six colon-style transcripts never get here)."""
    out: list[tuple[int, int, str]] = []
    lines = text.split("\n")
    pos = 0
    for i, line in enumerate(lines):
        m = NAME_ONLY_RX.fullmatch(line)
        if m:
            name = " ".join(m.group(1).split())
            nxt = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
            if not TITLE_WORD_RX.search(name) and not NON_NAME_RX.search(name) and _starts_speech(nxt) and (
                    any(_same_person(k, name) for k in known) or counts[name] >= 3):
                a = pos + line.find(m.group(1))
                out.append((a, a + len(m.group(1)), name))
        pos += len(line) + 1
    return out


# Finance-metric abbreviations that are NOT entities (they are in the lexicon).
_FINANCE_METRICS = {"EBITDA", "ROCE", "ROE", "PAT", "PBT", "EPS", "CAGR", "NIM", "AUM", "EBIT", "EBITDAR", "ROA", "ROIC", "ROI", "PE", "PB", "EV", "EPS", "TTM", "NPA", "NCD", "SIP", "YTD", "ARPU", "ARPP", "CAPEX", "OPEX", "WIP"}
# Section / slide words that are never entities.
_SLIDE_WORDS = {"slide", "slides", "section", "agenda", "contents", "overview", "summary", "highlights", "annexure"}
_LEADING_STOP = {"the", "a", "an", "our", "we", "this", "that", "these", "those", "my", "so", "but", "and", "for", "with", "from", "it", "its", "all", "any", "whereas", "whilst", "while", "though", "although", "however", "also", "then", "now", "thus", "hence", "therefore", "yet", "what", "who", "why", "how", "when", "where", "because", "including", "excluding", "compared", "given", "emerging", "actually", "see", "once", "best"}
_PERIOD_WORDS = {"FY", "Q1", "Q2", "Q3", "Q4", "QOQ", "YOY", "HOH", "MOM", "WOW"}
# Title words that are not names ("Mr", "Messrs" ...) (T-164 r6).
_TITLE_WORDS = {"mr", "ms", "mrs", "dr", "shri", "smt", "sr", "jr", "messrs", "late", "sir", "ji", "madam"}
# Direct address / introduction: the word after these is a person, not an entity ("I'll ask Rakesh") (T-164 r6).
_PERSON_CUE_RX = re.compile(
    r"\b(?:ask|asking|asked|over to|thank(?:s| you)?|line of|question (?:is )?from|"
    r"next question (?:comes )?from|hand (?:it |the call )?over to)\s*,?\s+"
    r"(?:(?:Mr|Ms|Mrs|Dr|Shri)\.?\s+)?([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,2})")
# "<Name>, who ...": a person clause; a place or company is followed by "which", never "who" (T-164 r7).
_PERSON_WHO_RX = re.compile(r"\b([A-Z][A-Za-z.'’\-]+),\s+who\b")
# "Jignesh's colleague": a relation names the person it belongs to (T-164 r7).
_PERSON_POSSESSIVE_RX = re.compile(r"\b([A-Z][A-Za-z.'’\-]+)(?:'s|’s)\s+"
                                   r"(?:colleague|team|cousin|brother|sister|son|daughter|wife|husband)\b")
# "Rakesh sir" / "Rawal ji": a person addressed by an honorific, never an entity (T-164 r6).
_PERSON_HONORIFIC_RX = re.compile(r"\b([A-Z][A-Za-z.'’\-]+)\s+(?:sir|ji|madam)\b", re.I)
_MONTH_WORDS = {"january", "february", "march", "april", "may", "june", "july", "august", "september",
                "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday"}
# Ordinary business words that are capitalised in headings ("Communications", "Board", "Tier") but name nothing.
_GENERIC_WORDS = {"board", "tier", "communications", "communication", "offerings", "offering", "segment", "segments",
                  "management", "office", "unit", "units", "solutions", "systems", "technologies", "services",
                  "group", "business", "company", "enterprises", "industries", "ventures", "holdings", "division",
                  "vertical", "verticals", "region", "regions", "operations", "corporate", "executive", "gen",
                  "fintech", "suite", "avionics", "campus", "integrated", "crore", "crores", "lakh", "lakhs", "million", "billion", "rupees", "rupee", "dollars", "inr", "usd", "additionally", "further", "overall", "similarly", "accordingly", "financial", "performance", "earnings", "page", "responsibility", "national", "awards", "award", "winner", "hub", "cloud", "genai", "iot", "aif", "amc", "sez", "lifesciences", "greenfield", "ministry", "media", "communication", "quarterly", "annual", "offices", "east", "west", "north", "south", "central", "eastern", "western", "northern", "southern", "finance", "god", "alpha", "category", "makhana", "risk", "gross", "adjusting", "equities", "moving", "life", "power", "sonar", "block", "association", "hero", "auto", "jacquard", "banking", "dollar", "euro", "corona", "fuzes", "spaces", "omicron",
                  "robusta", "arabica", "creative", "ind", "huddle"}
# Nouns a named organisation / programme / project / counterparty is followed by (T-164 r6).  An all-caps
# token before one of these names something; a metric or business abbreviation is never followed by them.
_NAMED_NOUNS = ("ltd", "limited", "bank", "finance", "corporation", "corp", "company", "authority", "ministry",
                "department", "board", "commission", "court", "council", "institute", "university", "foundation",
                "trust", "scheme", "mission", "programs?", "programmes?", "project", "act", "guidelines", "norms",
                "circular", "notification", "tender", "contract", "order", "orders", "plant", "refinery", "smelter",
                "mine", "airport", "port", "expressway", "metro", "grid", "corridor", "park", "zone", "phase",
                "tower", "plaza", "mall", "hospital", "committee", "regulator", "amendment", "deadline", "approval",
                "clearance", "licen[cs]e", "permission", "party", "parties", "act\\.", "report")
# Verbs only an organisation / programme / named thing performs (a metric never does).
_AGENCY_RX = (r"has|have|had|said|says|told|approved|awarded|signed|announced|issued|notified|sanctioned|"
              r"cleared|won|bagged|supplies|supplied|launched|plans|proposes|develops|manufactures|operates|"
              r"invited|directed|participated|conducted|visited|urged|released|floated|intends|declared|"
              r"recommended|seeks|sought|lodged|filed|imposed|waived|extended")
# "from X" / "with X": X is the object of the preposition, i.e. a named counterparty (T-164 r6).
_OBJ_PREPS = ("from", "with", "by", "at", "per", "to", "against", "including", "like", "under", "through")
# "in Pune" / "from C-DAC": a single capitalised word after a locative preposition is a place/counterparty name.
_LOC_CUE_RX = re.compile(r"\b(?:in|at|from|to|near|across|via|within|outside|into)\s+$")
# Place nouns a named city/site heads ("Bengaluru facility", "Pune market").
_LOC_NOUNS = ("facility", "facilities", "plant", "plants", "site", "city", "market", "branch", "branches", "hospital",
              "hospitals", "office", "campus", "region", "unit", "units", "stores?", "centre", "center", "airport",
              "court", "hub", "refinery", "smelter", "mine", "terminal", "port", "corridor", "expressway")
# Ordinary English vocabulary (lowercase) loaded from en_vocab.txt.
_EN_VOCAB = set()
_vp = Path(__file__).with_name("en_vocab.txt")
if _vp.exists():
    _EN_VOCAB.update(x.strip().lower() for x in _vp.read_text(encoding="utf-8").splitlines() if x.strip())
# Common words that the vocab file misses but are never entities.
_EN_VOCAB.update({"ai", "it", "perfect", "drink", "fruit", "inaudible", "army", "navy", "salt", "pakistani", "movies", "tv", "moderator", "trailing"})
# Demonyms, interjections and calendar words: ordinary language, never a named thing (T-164 r6).
_EN_VOCAB.update({"chinese", "indian", "japanese", "american", "european", "british", "german", "korean",
                  "russian", "arab", "asian", "african", "god", "diwali", "covid"})
# Generic technology nouns: a title-case phrase built only from these names a capability, not a thing
# ("Communication Suite", "Navigation Complex System", "Electronic Warfare Suite") (T-164 r8).
_GENERIC_TECH_WORDS = {"missile", "missiles", "torpedo", "combat", "navigation", "warfare", "electronic",
                       "weapon", "weapons", "control", "complex", "information", "fire", "system", "systems",
                       "youngest", "aircraft", "fleet", "desi", "jacquard", "mart", "suite", "communication",
                       "radar", "sensor", "sensors", "platform", "platforms", "naval", "sonar",
                       "infrastructure", "lab", "colocation", "command", "digital", "education", "sustainability",
                       "telephony", "carrier", "access", "messaging", "mobile", "telecom", "star"}
_EN_VOCAB.update(_GENERIC_TECH_WORDS)
_EN_VOCAB.update({"egyptian", "telecom", "carrier", "access", "messaging", "mobile", "telephony", "education",
                  "digital", "transformation", "enabler", "sustainability", "assessment", "scope", "star",
                  "planning", "concall"})
# Words a brand name is built from; alone they are the fragment, the longer printed name is the entity
# ("Copper" of "Tata Copper Plus", "Mart" of "SG Mart") (T-164 r8).
_FRAGMENT_WORDS = {"capital", "copper", "gluco", "mart"}
def _is_sentence_start(text: str, pos: int) -> bool:
    i = pos - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    if i < 0:
        return True
    # a bullet mark opens a sentence too ("• Moving on to ...") (T-164 r7)
    return text[i] in ".?!:\n•▪●–—"

def _hyphen_piece(text: str, m: re.Match) -> bool:
    start, end = m.start(), m.end()
    left = text[max(0, start - 3):start]
    right = text[end:end + 3]
    return ("-" in left) or ("-" in right)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


_GENERIC_LAST_WORDS = {"industry", "services", "sector", "market", "business", "group", "company", "limited",
                       "director", "manager", "officer", "president", "chairman", "secretary", "chief", "outlook",
                       "relations", "relationship", "head", "conference", "call", "fund", "mutual", "foundation",
                       "year", "board", "campus", "day", "airlines", "sciences", "healthcare", "fintech", "labs",
                       "office", "meeting", "committee", "department", "division", "unit", "units", "team", "teams", "responsibility", "secretaries", "awards", "performance", "earnings", "page", "media", "communication",
                       "suite", "fleet", "command", "debt", "highlights", "webcast", "retirement", "diwali",
                       "concall"}
# A span that is a job title names a role, never a thing: "Managing Director", "Chief Financial Officer" (T-164 r7).
_TITLE_ENTITY_WORDS = {"director", "directors", "managing", "officer", "officers", "chief", "president", "deputy",
                       "chairman", "chairperson", "secretary", "manager", "head", "executive", "vice", "founder",
                       "minister", "magistrate", "commissioner"}
# A span that ends in a metric, an accounting line or a generic event names a number or a concept, not a thing:
# "Earnings Per Share", "Other Intangibles", "Hyper Scaler Business", "18th Anniversary" (T-164 r7).
_METRIC_LAST_WORDS = {"share", "shares", "intangibles", "rate", "rates", "ratio", "margin", "cost", "costs",
                      "revenue", "revenues", "profit", "loss", "income", "earnings", "value", "growth", "business",
                      "shop", "anniversary", "independence", "season", "phase", "services",
                      "solutions", "day", "days", "week", "month", "quarter", "year", "sciences", "insurance",
                      "agreement", "radio", "beverages", "prescription", "jet", "injection", "injections",
                      "injectable", "granules", "tablets", "capsules", "syrup", "immunology", "oncology",
                      "cardiology", "neurology", "governance", "award", "awards", "automation", "industries", "stone",
                      "tax", "property", "region", "regions", "marketing", "campaign", "campaigns", "equity", "use",
                      "department", "departments", "partner", "partners", "lending", "security", "herbal",
                      "honor", "honour", "defense", "defence", "debt", "mark", "express", "planning",
                      "prescriptions", "airline", "hospital", "intelligence", "reality", "design", "package",
                      "trunk"}
# Generic business abbreviations: they label a metric, a segment or a process, never a named thing
# (T-164 r6 review: ARC, SEZ, TCV, ARPOB, RM ... graded wrong; programme names such as NGC, CSEL, PLI stay).
# Kept in a lexicon file like en_vocab.txt: an exchange-listed symbol that is also a business term is data, not code.
_BUSINESS_ABBREV: set[str] = set()
_bp = Path(__file__).with_name("lexicon") / "business_abbrev.txt"
if _bp.exists():
    _BUSINESS_ABBREV.update(x.strip().upper() for x in _bp.read_text(encoding="utf-8").splitlines() if x.strip())
# A token the document itself expands to a company name is that company's name, never a business term:
# "Sapien BioSciences Pvt Limited (SBPL)" (T-164 r8).
_COMPANY_TAIL_RX = re.compile(r"\b(?:Limited|Ltd\.?|Private|Pvt\.?)\b", re.I)


def _company_abbrevs_in(full_text: str) -> set[str]:
    """Abbreviations the call expands to a legal company name ("<Name> Pvt Limited (X)"), so the lexicon does
    not swallow a real company (T-164 r8)."""
    out: set[str] = set()
    for m in re.finditer(r"\(([A-Z]{2,10})\)", full_text):
        left = full_text[max(0, m.start() - 90):m.start()]
        if _COMPANY_TAIL_RX.search(left):
            out.add(m.group(1).upper())
    for m in re.finditer(r"\b([A-Z]{2,10})\s*\((?:[A-Z][A-Za-z&.'’\-]*\s+){1,6}"
                         r"(?:Pvt\.?|Private)?\s*(?:Limited|Ltd\.?)\s*\)", full_text):
        out.add(m.group(1).upper())
    return out


def _learned_generic_acronyms(docs: Iterable[str]) -> set[str]:
    """All-caps tokens used with a number or a percentage in at least two calls: a metric/unit, not a name
    (WHRS 26, GNPA 3.97%, RCC 1,000 tons ...).  A token that is mostly used without a figure (a programme name
    quoted beside an amount now and then) is left alone (T-164 r8)."""
    occ: Counter = Counter()
    occ_num: Counter = Counter()
    docs_num: Counter = Counter()
    for text in docs:
        seen_num: set[str] = set()
        for m in re.finditer(r"(?<![A-Za-z0-9])(?:[A-Z]{2,6}(?:-[A-Z]{1,6})+|[A-Z]{2,6})(?![A-Za-z0-9])", text):
            tok = m.group(0)
            occ[tok] += 1
            w = text[max(0, m.start() - 48):m.end() + 48]
            t = re.escape(tok)
            if (re.search(r"\b" + t + r"\b\s*(?:of|at|is|was|were|to|per|stood|reached)?\s*[₹$€£]?\s*\d", w)
                    or re.search(r"\d[\d,.]*\s*(?:%|bps)?\s*(?:of\s+)?" + t + r"\b", w)):
                occ_num[tok] += 1
                seen_num.add(tok)
        for tok in seen_num:
            docs_num[tok] += 1
    return {tok for tok, n in docs_num.items() if n >= 2 and occ_num[tok] * 2 >= occ[tok]}


def _name_evidence(windows: list[str], tok: str) -> bool:
    """A multi-word span names something when it is used as a name: a name noun after it, a possessive, an
    object preposition before it, or a verb of agency.  An ordinary phrase in a list has none of these
    ("Communication Suite", "Navigation Complex System", "Youngest Aircraft Fleet") (T-164 r8)."""
    t = re.escape(tok)
    for w in windows:
        if re.search(r"\b" + t + r"\s+(?:" + "|".join(_NAMED_NOUNS) + r")\b", w):
            return True
        if re.search(r"\b" + t + r"(?:'s|’s)\b", w):
            return True
        if re.search(r"\b(?:" + "|".join(_OBJ_PREPS) + r")\s+(?:the\s+)?" + t + r"\b", w):
            return True
        if re.search(r"\b" + t + r"\s+(?:" + _AGENCY_RX + r")\b", w):
            return True
    return False


_TITLE_SPAN_RX = re.compile(r"\b[A-Z][a-z]{2,}(?:(?:\s*&\s*|\s+)[A-Z][a-z]{2,}){1,5}\b")
# Demonyms: an adjective phrase ending in one names a nationality, not a thing (T-164 r8).
_DEMONYMS = {"american", "african", "european", "asian", "indian", "chinese", "japanese", "british", "german",
             "korean", "russian", "arab", "canadian", "australian", "briton"}
# "SG Mart", "BEML Soudha": an all-caps token that starts a printed name (T-164 r8).
_ACRONYM_SPAN_RX = re.compile(r"\b[A-Z]{2,6}\s+[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,4}\b")
# Title prefixes whose following name is a person (T-164 r5).
_TITLE_PREFIX_RX = re.compile(r"\b(?:Mr|Ms|Mrs|Dr|Shri)\.?\s+(" + _PERSON_NAME + r")", re.I)


def _windows(text: str, tok: str, positions: list[int]) -> list[str]:
    """The text around each occurrence, so a per-token test reads a few hundred chars, not the whole call."""
    return [text[max(0, p - 48):p + len(tok) + 48] for p in positions]


def _number_metric(windows: list[str], tok: str) -> bool:
    """A metric/unit abbreviation is used with a number: "ARPOB 12,000", "TCV of $1.2 billion", "10 MLD",
    "ARPOB will be around 38,000" - i.e. a number in the same clause (T-164 r6)."""
    t = re.escape(tok)
    for w in windows:
        if re.search(r"\b" + t + r"\b\s*(?:of|at|is|was|were|to|per|stood|reached)?\s*[₹$€£]?\s*\d", w):
            return True
        if re.search(r"\d[\d,.]*\s*(?:%|bps)?\s*(?:of\s+)?" + t + r"\b", w):
            return True
        if re.search(r"\b" + t + r"\b[^.;:!?]{0,40}\d", w):
            return True
    return False


def _named_cue(windows: list[str], tok: str) -> bool:
    """An all-caps token names something only when it is used as a name, not as a business modifier or metric:
    "with RBI", "HAL has", "DRDO's", "HAL order" - not "BFSI segment", "LAP book", "TCV was" (T-164 r6)."""
    t = re.escape(tok)
    head = r"\b" + t + r"(?=\s*(?:[,.;:)!?]|$|\s(?:has|have|had|is|was|were|will|would|can|could|"
    head += r"should|may|might|must|also|too|as|in|on|of|for|to|with|from|by|at|which|who|that|said|says|told)\b))"
    for w in windows:
        if re.search(r"\b" + t + r"\s+(?:" + "|".join(_NAMED_NOUNS) + r")\b", w):
            return True
        if re.search(r"\b" + t + r"(?:'s|’s)\b", w):
            return True
        if re.search(r"\b(?:" + "|".join(_OBJ_PREPS) + r")\s+(?:the\s+)?" + head, w):
            return True
        if re.search(r"\b" + t + r"\s+(?:" + _AGENCY_RX + r")\b", w):
            return True
        # a name in a list or before a comma ("So, NGC, there are ...", "NGC, P-75I and QRSAM") names something
        # even with no preposition in front of it (T-164 r7)
        if re.search(r"\b" + t + r"\s*(?:,|/|&|\band\b)", w):
            return True
    return False


def _strong_cue(windows: list[str], tok: str) -> bool:
    """Cues a business abbreviation never has: a name noun after it, a possessive, or a verb of agency."""
    t = re.escape(tok)
    for w in windows:
        if re.search(r"\b" + t + r"\s+(?:" + "|".join(_NAMED_NOUNS) + r")\b", w):
            return True
        if re.search(r"\b" + t + r"(?:'s|’s)\b", w):
            return True
        if re.search(r"\b" + t + r"\s+(?:" + _AGENCY_RX + r")\b", w):
            return True
    return False


def _modifier_use(windows: list[str], tok: str) -> bool:
    """More often than not the token is a modifier ("BFSI segment", "LAP book", "SME loans") rather than a name
    ("with RBI", "HAL has"): a business abbreviation, not an entity (T-164 r6)."""
    function = {"of", "at", "for", "in", "on", "to", "and", "or", "as", "is", "was", "were", "will", "would",
                "by", "from", "with", "that", "which", "who", "the", "a", "an", "has", "have", "had", "said",
                "says", "per", "vs", "versus", "is", "while", "where", "when", "but", "so", "if", "than"}
    t = re.escape(tok)
    mod = name = 0
    for w in windows:
        mid = w.find(tok)
        if mid < 0:
            continue
        after = w[mid + len(tok):]
        before = w[:mid]
        mx = re.match(r"\s+([a-z][a-z\-]+)", after)
        if mx and mx.group(1) not in function:
            mod += 1
        elif after.lstrip().startswith((",", ".", ";", ":", ")", "?", "!")) or re.match(
                r"\s+(?:has|have|had|is|was|were|will|would|said|says|told|approved|awarded|signed)\b", after):
            name += 1
        elif re.search(r"\b(?:from|with|by|at|per|to|under)\s+$", before):
            name += 1
    return mod > name


def _recurring_entities(full_text: str, speaker_names: set[str], own_tokens: set[str] | None = None,
                        learned_generic: set[str] | None = None) -> set[str]:
    own_tokens = own_tokens or set()
    name_tokens = set()
    for n in speaker_names:
        for t in n.split():
            name_tokens.add(t.lower().strip(".,'’-"))
    # tokens after Mr./Ms./Mrs./Dr./Shri are person names too
    for m in _TITLE_PREFIX_RX.finditer(full_text):
        for t in m.group(1).split():
            name_tokens.add(t.lower().strip(".,'’-"))
    # and the person introduced or directly addressed ("over to Rakesh", "I'll ask Prashant") (T-164 r6)
    for m in _PERSON_CUE_RX.finditer(full_text):
        for t in m.group(1).split():
            name_tokens.add(t.lower().strip(".,'’-"))
    for m in _PERSON_HONORIFIC_RX.finditer(full_text):
        name_tokens.add(m.group(1).lower().strip(".,'’-"))
    for m in _PERSON_WHO_RX.finditer(full_text):
        name_tokens.add(m.group(1).lower().strip(".,'’-"))
    for m in _PERSON_POSSESSIVE_RX.finditer(full_text):
        name_tokens.add(m.group(1).lower().strip(".,'’-"))
    speaker_lower = {n.lower() for n in speaker_names}
    sentences = _sentences(full_text)

    def _all_hyphen(cand: str) -> bool:
        occs = list(re.finditer(r"\b" + re.escape(cand) + r"\b", full_text))
        return bool(occs) and all(_hyphen_piece(full_text, mm) for mm in occs)

    def _lowercase_too(span: str) -> bool:
        """The same phrase exists in ordinary lowercase: the capitals are sentence position, not a name
        ("Copper" / "copper", "Wealth Management").  An all-caps acronym has no lowercase reading."""
        return (span != span.upper()
                and bool(re.search(r"\b" + re.escape(span.lower()) + r"\b", full_text)))

    def _prep_cue(tok: str) -> bool:
        """A single capitalised word names a place/counterparty when it follows a preposition ("to Pune"),
        follows a comma in a list ("Sarjapur, Bengaluru") or heads a place noun ("Bengaluru facility")."""
        t = re.escape(tok)
        if re.search(r"\b" + t + r"\s+(?:" + "|".join(_LOC_NOUNS) + r")\b", full_text):
            return True
        for m in re.finditer(r"\b" + t + r"\b", full_text):
            left = full_text[max(0, m.start() - 14):m.start()]
            if _LOC_CUE_RX.search(left) or re.search(r",\s+$", left):
                return True
        return False

    result: set[str] = set()
    # every longer name the call prints, even when the span itself is refused below: a single word that is only
    # part of it is a fragment, never an entity ("Capital" of "Capital Foods", "Mart" of "SG Mart") (T-164 r8).
    printed_spans = [" ".join(m.group(0).split())
                     for rx in (_TITLE_SPAN_RX, _ACRONYM_SPAN_RX) for m in rx.finditer(full_text)]
    spans = [(m, False) for m in _TITLE_SPAN_RX.finditer(full_text)]
    spans += [(m, True) for m in _ACRONYM_SPAN_RX.finditer(full_text)]
    # the call's own expansions ("Sapien BioSciences Pvt Limited (SBPL)") and the store-level metric words are not
    # business abbreviations for this call (T-164 r8)
    company_expansions = _company_abbrevs_in(full_text)
    generic_abbrev = (_BUSINESS_ABBREV | (learned_generic or set())) - company_expansions

    # (a) capitalised multi-word spans: entities if no person/company/lowercase-ordinary reading.
    for m, acronym_led in spans:
        span = " ".join(m.group(0).split())
        toks = span.lower().split()
        if toks and toks[0] in _LEADING_STOP:
            continue
        if span.lower() in speaker_lower:
            continue
        # drop any span that is a speaker name or part of one (exact token; a fuzzy match would eat names
        # that merely resemble a person's token, e.g. "Summit Plaza" vs "Sumit") (T-164 r6)
        if any(t in name_tokens for t in toks):
            continue
        if all(t in own_tokens for t in toks) and toks:
            continue
        # a job title or a span ending in a metric/accounting word names a role or a number, not a thing (T-164 r7)
        if any(t in _TITLE_ENTITY_WORDS for t in toks) or toks[-1] in _METRIC_LAST_WORDS:
            continue
        # a business abbreviation anywhere in the span ("SME Business") is a label, not a name (T-164 r7)
        if any(t.upper() in generic_abbrev for t in toks):
            continue
        # an acronym before a generic word is a label, not a name ("BEL Board", "HAL team") (T-164 r8)
        if acronym_led and any(t in _GENERIC_WORDS for t in toks[1:]):
            continue
        # a phrase ending in a demonym is an adjective, not a name ("North American business") (T-164 r8)
        if toks[-1] in _DEMONYMS:
            continue
        # a courtesy phrase from a speaker line ("Ravi Menon Thanks so much") is not a name (T-164 r8)
        if any(t in {"thanks", "thank", "welcome", "morning", "evening", "afternoon"} for t in toks):
            continue
        # hyphen-split pieces never
        if _hyphen_piece(full_text, m):
            continue
        # drop generic industry phrases whose every word is ordinary vocabulary
        if all(t in _EN_VOCAB for t in toks) and toks and toks[-1] in _GENERIC_LAST_WORDS:
            continue
        # a capability phrase built only from generic technology words names nothing unless the call uses it as
        # a name ("Communication Suite, Navigation Complex System, Torpedo Fire Control System") (T-164 r8)
        if all(t in _EN_VOCAB or t in _GENERIC_WORDS for t in toks) and \
                any(t in _GENERIC_TECH_WORDS for t in toks) and \
                not _name_evidence(_windows(full_text, span, [m.start()]), span):
            continue
        # drop spans that are months or date phrases
        if any(t in {"january","february","march","april","may","june","july","august","september","october","november","december"} for t in toks):
            continue
        if _lowercase_too(span):
            continue
        result.add(span)

    # single capitalised words (incl. CamelCase): entity only if not in vocab, not a person token,
    # not a hyphen piece, and recurring in >= 2 statements (or a place/counterparty after a preposition).
    # A comma next to one occurrence never drops the name for the whole call (T-164 r6: "Dahlias, ...").
    single_candidates = set()
    for rx in (r"\b[A-Z][a-z]{2,}\b", r"\b[A-Z][a-z]+[A-Z][A-Za-z]*\b"):
        for m in re.finditer(rx, full_text):
            tok = m.group(0)
            low = tok.lower()
            # a capitalised common word is caught by _lowercase_too below; excluding plain vocabulary here
            # would also drop place names that Indian English word lists carry ("Pune", "Bengaluru") (T-164 r6)
            if tok in _FINANCE_METRICS or tok.upper() in _PERIOD_WORDS or low in _SLIDE_WORDS or low in _LEADING_STOP:
                continue
            if low in _MONTH_WORDS or low in name_tokens or low in speaker_lower or low in _GENERIC_WORDS:
                continue
            # a title or a metric word is never a name on its own ("Director", "Phase", "Anniversary") (T-164 r7)
            if low in _TITLE_ENTITY_WORDS or low in _METRIC_LAST_WORDS or tok.upper() in generic_abbrev:
                continue
            # a word that only makes up a longer printed name in this call is a fragment ("Capital" of
            # "Capital Foods", "Mart" of "SG Mart") (T-164 r8)
            if (low in _EN_VOCAB or low in _GENERIC_WORDS or low in _FRAGMENT_WORDS) and any(
                    re.search(r"\b" + re.escape(tok) + r"\b", sp) for sp in printed_spans):
                continue
            # a demonym / ordinary adjective the word list holds ("European", "Turkish") is not a name
            if low in _EN_VOCAB and re.search(r"(?:an|ese|ish|ern)$", low):
                continue
            # a company word ("Cement", "Limited") is not a name, but the company's own CamelCase name is
            # ("UltraTech"): keep the exclusion for plain words only
            if low in own_tokens and not re.search(r"[a-z][A-Z]", tok):
                continue
            if not re.search(r"[a-z][A-Z]", tok) and any(
                    len(ot) >= 4 and (low in ot or ot in low) for ot in own_tokens):
                continue
            if any(len(nt) >= 4 and (low in nt or nt in low) for nt in name_tokens):
                continue
            if _hyphen_piece(full_text, m):
                continue
            # a CamelCase formation label ("DevCo", "RentCo") is a structure, not a named thing (T-164 r7)
            if re.search(r"(?:Co|Corp|Inc|Ltd)$", tok) and not tok.isupper():
                continue
            if _lowercase_too(tok):
                continue
            single_candidates.add(tok)
    for tok in single_candidates:
        if _all_hyphen(tok):
            continue
        non_initial = any(not _is_sentence_start(full_text, mm.start())
                          for mm in re.finditer(r"\b" + re.escape(tok) + r"\b", full_text))
        if not non_initial:
            continue
        n_stmt = sum(1 for st in sentences if re.search(r"\b" + re.escape(tok) + r"\b", st))
        if n_stmt >= 2 or _prep_cue(tok):
            # an ordinary English word is a name only with a place/counterparty cue ("in Pune"), never on its own
            # ("Moving", "Power", "Gross") (T-164 r7)
            if tok.lower() in _EN_VOCAB and not _prep_cue(tok):
                continue
            result.add(tok)

    # (b) all-caps tokens (2-6 letters, hyphenated runs kept whole: "C-DAC"): an entity only when it names
    # something - used as a name, not as a business modifier or metric - and recurs in >= 2 statements (T-164 r6).
    cap_positions: dict[str, list[int]] = {}
    for m in re.finditer(r"(?<![A-Za-z0-9])(?:[A-Z]{1,6}(?:-[A-Z]{1,6})+|[A-Z]{2,6})(?![A-Za-z0-9])", full_text):
        cap_positions.setdefault(m.group(0), []).append(m.start())
    cap_candidates = set()
    for tok, poss in cap_positions.items():
        low = tok.lower()
        if low in _EN_VOCAB or tok in _FINANCE_METRICS or tok.upper() in _PERIOD_WORDS or low in _SLIDE_WORDS:
            continue
        if low in name_tokens or low in own_tokens or low in _TITLE_WORDS:
            continue
        # a business abbreviation (ARC, SEZ, BFSI, TCV, LOI ...) is a label, not a named thing (T-164 r7)
        if tok.upper() in generic_abbrev:
            continue
        if len(re.sub(r"[^A-Z]", "", tok)) < 3:
            continue
        windows = _windows(full_text, tok, poss)
        n_stmt = sum(1 for s in sentences if re.search(r"\b" + re.escape(tok) + r"\b", s))
        # a token the call itself expands to a legal company name is that company, whatever the figures beside it
        doc_name = tok.upper() in company_expansions
        if not doc_name and _number_metric(windows, tok):
            # a metric sits beside its number (ARPOB 12,000); a programme name in a list or beside a programme noun
            # is still a name though an amount follows it ("NGC INR20,000 crores", "NGC, P-75I") (T-164 r7)
            t = re.escape(tok)
            list_cue = any(re.search(r"\b" + t + r"\s*(?:,|/|&|\band\b)", w) for w in windows)
            programme = any(re.search(r"\b" + t + r"\s+(?:programme|program|project|system|radar|missile|platform|"
                                      r"scheme)s?\b", w, re.I) for w in windows)
            if not (list_cue and (n_stmt >= 2 or programme)):
                continue
        if not doc_name and not _named_cue(windows, tok):
            continue
        if not doc_name and not _strong_cue(windows, tok) and _modifier_use(windows, tok):
            continue
        cap_candidates.add(tok)

    for tok in cap_candidates:
        if _all_hyphen(tok):
            continue
        n_stmt = sum(1 for s in sentences if re.search(r"\b" + re.escape(tok) + r"\b", s))
        if tok.upper() in company_expansions or n_stmt >= 2 or _strong_cue(_windows(full_text, tok, cap_positions[tok]), tok):
            result.add(tok)

    # the longest printed span wins across the call: a candidate whose every occurrence sits inside a longer
    # candidate is a fragment of it ("Aatma Nirbhar" of "Aatma Nirbhar Bharat", "Bokaro Steel" of "Bokaro Steel
    # Plant", "Valiyath" of "KIMS Valiyath") (T-164 r8)
    def _only_inside(short: str, long: str) -> bool:
        places = [(m.start(), m.end()) for m in re.finditer(r"\b" + re.escape(long) + r"\b", full_text)]
        occs = [m.start() for m in re.finditer(r"\b" + re.escape(short) + r"\b", full_text)]
        return bool(occs) and all(any(a <= p and p + len(short) <= b for a, b in places) for p in occs)

    for span in sorted(result, key=len):
        if any(span != other and len(other) > len(span) and re.search(r"\b" + re.escape(span) + r"\b", other)
               and _only_inside(span, other) for other in result):
            result.discard(span)

    return result


def _entities_in(sentence: str, ent_set: set[str]) -> list[str]:
    found = []
    for e in sorted(ent_set):        # a set's order is per-process: sort, so two builds write the same list (T-202)
        if re.search(r"\b" + re.escape(e) + r"\b", sentence):
            found.append(e)
    # de-dupe preserving order; prefer longer spans first; drop spans contained in a longer one
    found.sort(key=len, reverse=True)
    seen = set()
    out = []
    for e in found:
        if e in seen:
            continue
        if any(re.search(r"\b" + re.escape(e) + r"\b", sel) for sel in out):
            continue
        seen.add(e)
        out.append(e)
    return out

def extract_doc(sym: str, doc_key: str, title: str, known_at: str, pages: list[tuple[int, str]], topics, people, st: dict, company_name: str | None = None,
                learned_generic: set[str] | None = None):
    texts = [t for _, t in pages]
    boiler = boilerplate_lines(texts)
    cperiod = call_period_ok(call_period_of(title, texts), known_at, title)
    cdate = call_date_of(texts[0], known_at)
    full = "\n".join(texts)
    doi_mgmt: dict[str, str] = {}
    p_mgmt, p_analysts, p_names = participants(texts, doi_mgmt)
    # DOI-layout names are kept out of the speaker map: they take effect only through the correction below
    analysts = [m.group(1) for m in ANALYST_INTRO_RX.finditer(full) if m.group(1)] + \
               [m.group(1) for m in HOST_INTRO_RX.finditer(full)] + p_analysts
    mgmt = {n: "mgmt" for n in moderator_names(full)}
    mgmt.update({m.group(1): _title_role(m.group(2)) for m in MGMT_INTRO_RX.finditer(full)})
    mgmt.update(p_mgmt)
    # name-only speaker lines only when the document has almost no real colon marks (the colon-style transcripts
    # must not move); a bare name repeated 3+ times is a speaker mark otherwise (T-056)
    junk = tuple(n.lower() for n in NOT_SPEAKERS)
    colon = sum(len([n for n in rx.findall(t) if not n.lower().startswith(junk)])
                for rx in (SPEAKER_RX, SPEAKER_MID_RX) for t in texts)
    counts = name_line_counts(texts) if colon < 5 else Counter()
    known = set(p_names) | set(mgmt) | set(analysts)
    segments: list[list] = []
    speaker, section, prev_role = "unknown", "prepared", "moderator"
    st.setdefault("questions", [])
    full_text = "\n".join(t for _, t in pages)
    own_tokens = set()
    if company_name:
        for t in re.findall(r"[A-Za-z]{3,}", company_name):
            own_tokens.add(t.lower())
    for t in re.findall(r"[A-Za-z]{3,}", title or ""):
        own_tokens.add(t.lower())
    own_tokens.add(sym.lower())
    # every colon-mark speaker is a person, also when the participant block does not name him (T-164 r6)
    spoken = set(known) | {m.group(1) for rx in (SPEAKER_RX, SPEAKER_MID_RX) for m in rx.finditer(full_text)
                           if not _not_speaker(m.group(1))}
    ent_set = _recurring_entities(full_text, spoken, own_tokens, learned_generic)
    for page, raw in pages:
        w = mask_noise(raw, boiler)
        marks = sorted((m.start(1), m.end(), m.group(1)) for rx in (SPEAKER_RX, SPEAKER_MID_RX) for m in rx.finditer(w)
                       if not _not_speaker(m.group(1)))
        if colon < 5:
            marks = sorted(marks + [(a, b, n) for a, b, n in name_marks(raw, counts, known)
                                    if all(a != x for x, _b, _n in marks)])
        bounds = [(0, marks[0][0], speaker)] if marks and marks[0][0] > 0 else ([] if marks else [(0, len(w), speaker)])
        for k, (a, b, name) in enumerate(marks):
            end = marks[k + 1][0] if k + 1 < len(marks) else len(w)
            bounds.append((b, end, name))
            speaker = name
        for a, b, name in bounds:
            role = role_of(name, sym, people, analysts, mgmt)
            if role == "unknown" and section == "qa" and prev_role == "moderator":
                analysts.append(name)
                role = "analyst"
            segments.append([page, raw, w, a, b, name, role, section])
            if role == "moderator" and QA_START_RX.search(w[a:b]):
                section = "qa"
            prev_role = role
    # a media call has no moderator, so QA_START_RX (the moderator's words) never fires: the first participant
    # line from the journalists/analysts list opens the Q&A instead (T-056 review)
    if not any(seg[6] == "moderator" for seg in segments):
        first = next((k for k, seg in enumerate(segments)
                      if seg[6] == "analyst" and any(_same_person(n, seg[5]) for n in p_analysts)), None)
        if first is not None:
            for seg in segments[first:]:
                seg[7] = "qa"
    # structural fallback (T-056): in the Q&A a name that answers right after an analyst 3+ times, and that the
    # moderator never introduced as an analyst, is management.  Everyone else stays unknown and is only counted.
    after_analyst: Counter = Counter()
    for k in range(1, len(segments)):
        if segments[k][6] == "unknown" and segments[k - 1][6] == "analyst":
            after_analyst[segments[k][5]] += 1
    for seg in segments:
        if seg[6] == "unknown" and after_analyst[seg[5]] >= 3 \
                and not any(_same_person(a, seg[5]) for a in analysts):
            seg[6] = "mgmt"
    # A DOI-layout participants block names the management.  When the call itself puts one of those names in the
    # analyst seat (the moderator interrupts the MD and the "unknown after moderator" rule takes him for an
    # analyst) while another management voice is already placed, the block corrects the record: that speaker is
    # management, never a question (T-164 r7).  A corrected speaker is promoted only to a management role; an
    # "Investor Relations" or moderator title stays ir/moderator and its lines are not management statements
    # (T-164 r8).
    promoted = ("md", "ceo", "cfo", "coo", "chairman", "mgmt")

    def _exact_name(a: str, b: str) -> bool:
        return _norm_name(a) == _norm_name(b)

    # a speaker the call's own DOI block names keeps the block's role, so an initial-led label ("L Krishnakumar")
    # is that management person, not an unnamed stranger (T-164 r8)
    for seg in segments:
        if seg[6] == "unknown":
            for n, r in doi_mgmt.items():
                if _exact_name(seg[5], n):
                    if r in promoted or r in ("ir", "moderator"):
                        seg[6] = r
                    break

    misread = [n for n in doi_mgmt if any(seg[6] == "analyst" and _exact_name(seg[5], n) for seg in segments)]
    if misread:
        for seg in segments:
            if seg[6] in ("analyst", "unknown"):
                for n in misread:
                    if _exact_name(seg[5], n):
                        if doi_mgmt[n] in promoted or doi_mgmt[n] in ("ir", "moderator"):
                            seg[6] = doi_mgmt[n]
                        break
    seq, started = 0, False
    rows = []
    turn = 0
    prep = 0        # prepared remarks get their own turn ids (negative), never a Q&A answer's (T-164 r7)
    for page, raw, w, a, b, name, role, section in segments:
        if role not in ("unknown",):
            started = True      # cover letter / headers before the first real speaker are not call content
        if not started:
            continue
        if role in ("moderator", "ir"):
            continue
        if role == "analyst":
            turn += 1
            # store the analyst's question as one question row (sentences joined)
            qsentences = []
            for (s0, e0) in split_sentences(w[a:b], a):
                while s0 < e0 and not w[s0].strip():
                    s0 += 1
                qq = raw[s0:e0].strip()
                if len(qq) < 5 or not re.search(r"[A-Za-z]{3}", qq):
                    continue
                qsentences.append(" ".join(qq.split()))
            if qsentences:
                qtext = " ".join(qsentences)
                st["questions"].append((sym, None, doc_key, cdate, cperiod, page, name, None, qtext,
                                       ",".join(tag_topics(topics, sym, qtext)),
                                       ",".join(_entities_in(qtext, ent_set)), turn, known_at,
                                       "docs.known_at", "transcript_v1"))
            continue
        if role == "unknown":
            # cannot tell management from a stray analyst: counted, not stored
            st["unknown_speakers"][name] += 1
            continue
        if section == "qa":
            turn_id = turn           # the analyst question this answers
        else:
            prep -= 1
            turn_id = prep           # each prepared-remarks segment is one turn of its own
        for (s0, e0) in split_sentences(w[a:b], a):
            while s0 < e0 and not w[s0].strip():
                s0 += 1               # a masked running footer at the segment start ("… Limited 3") is not a quote
            q = raw[s0:e0].strip()
            if len(q) < 25 or not re.search(r"[A-Za-z]{3}", q):
                continue
            seq += 1
            sent = " ".join(q.split())
            per = parse_periods(sent)
            if per:
                pdisc, psrc = per[0].canon, "sentence"
            else:
                pdisc, psrc = cperiod, "call"
            frag = int(not re.search(r"[.?!][\"”’')]*$", q) or q[0].islower())
            rows.append((sym, None, doc_key, cdate, cperiod, page, seq, name, role, section,
                         ",".join(tag_topics(topics, sym, sent)), pdisc, psrc,
                         json.dumps(numbers_in(sent, cperiod), ensure_ascii=False), sent, q, frag,
                         ",".join(_entities_in(sent, ent_set)), turn_id, known_at,
                         "docs.known_at", "transcript_v1"))
    return rows


COLS = ("symbol isin doc_key call_date call_period page seq speaker role section topics period_discussed period_source "
        "numbers_json statement quote is_fragment entities answer_turn known_at known_at_source extractor_rule").split()
QUESTION_COLS = ("symbol isin doc_key call_date call_period page analyst firm question topics entities answer_turn "
                 "known_at known_at_source extractor_rule").split()


def _transcript_docs(con: sqlite3.Connection, sym: str, sandbox: Path | None):
    """(doc_key, title, known_at, [(page, text)]) for every transcript: the pilot3 db's own ``doc_page`` when it
    has been built (pages.db documents and their RapidOCR text, doc keys already the pilot3 ones), else the
    sandbox loop's ``docs``/``doc_text``.  A profile build has no sandbox: only the database's own pages."""
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='doc_page'").fetchone():
        docs = con.execute("SELECT d.doc_key, d.title, d.known_at FROM doc d JOIN doc_page p ON p.doc_key=d.doc_key "
                           "WHERE d.symbol=? AND d.doc_type='transcript' GROUP BY d.doc_key",
                           (sym,)).fetchall()
        for doc_key, title, known_at in docs:
            pages = con.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
            yield doc_key, title, known_at, pages
        return
    if sandbox is None or profile.under_profile():
        return
    src = sqlite3.connect(f"file:{(sandbox / f'{sym.lower()}_loop' / f'{sym.lower()}.db').as_posix()}?mode=ro",
                          uri=True)
    try:
        for doc_key, title, known_at in src.execute("SELECT doc_key, title, known_at FROM docs "
                                                    "WHERE doc_type='transcript' ORDER BY known_at"):
            pages = src.execute("SELECT page, text FROM doc_text WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
            yield doc_key, title, known_at, pages
    finally:
        src.close()


def run(out: str, symbols: list[str], sandbox: Path | None, limit_docs: int | None = None) -> dict:
    t0 = time.time()
    topics, people = load_topics()
    sector_topics = {sym: _compiled(_sector_topics(_sector_of(sym))) for sym in symbols}   # T-194
    con = sqlite3.connect(out)
    schema.migrate(con)          # T-202: transcript tables, the T-164 columns and the question views, one entry point
    stats: dict = {}
    # store-level metric words: a token used beside a figure in two or more calls is no company name
    # (WHRS 26, GNPA 3.97%, RCC 1,000 tons ...) (T-164 r8)
    learned_generic = _learned_generic_acronyms(
        "\n".join(t for _p, t in allp if (t or "").strip())
        for sym in symbols for _dk, _t, _na, allp in _transcript_docs(con, sym, sandbox))
    stats["learned_generic"] = len(learned_generic)
    sql = f"INSERT OR IGNORE INTO transcript_statement({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    qsql = f"INSERT INTO transcript_question({','.join(QUESTION_COLS)}) VALUES({','.join('?' * len(QUESTION_COLS))})"
    for sym in symbols:
        con.execute("DELETE FROM transcript_statement WHERE symbol=?", (sym,))
        con.execute("DELETE FROM transcript_question WHERE symbol=?", (sym,))
        st = stats[sym] = {"docs": 0, "pages": 0, "needs_ocr": 0, "unknown_speakers": Counter(), "questions": []}
        try:
            company_name = con.execute("SELECT name FROM company WHERE symbol=? LIMIT 1", (sym,)).fetchone()
            company_name = company_name[0] if company_name else None
        except Exception:
            company_name = None
        for index, (doc_key, title, known_at, allp) in enumerate(_transcript_docs(con, sym, sandbox)):
            if limit_docs and index >= limit_docs:
                break
            st["needs_ocr"] += sum(1 for _p, t in allp if not (t or "").strip())
            pages = [(p, t) for p, t in allp if (t or "").strip()]
            if not pages:
                continue
            st["docs"] += 1
            st["pages"] += len(pages)
            rows = extract_doc(sym, doc_key, title, known_at, pages, topics + sector_topics[sym], people, st,
                               company_name, learned_generic)
            con.executemany(sql, rows)
            qs = st.get("questions", [])
            # st["questions"] is list of tuples collected; reset per doc
            doc_qs = [q for q in qs if q[2] == doc_key]
            con.executemany(qsql, doc_qs)
            st["questions"] = [q for q in qs if q[2] != doc_key]
            st["questions_count"] = len(qs)
        con.commit()
        st["rows"] = con.execute("SELECT count(*) FROM transcript_statement WHERE symbol=?", (sym,)).fetchone()[0]
        st["questions"] = con.execute("SELECT count(*) FROM transcript_question WHERE symbol=?", (sym,)).fetchone()[0]
        st["unknown_speakers"] = dict(st["unknown_speakers"].most_common(5))
    stats["seconds"] = round(time.time() - t0, 1)
    con.close()
    return stats


def retag(out: str, symbols: list[str] | None = None) -> dict:
    """Re-run the topic tagger over the statements already stored in ``out`` (T-194), in place, with the company's
    sector vocabulary.  Returns the share of ``other`` before and after: the tags move, the quotes do not."""
    con = sqlite3.connect(out)
    con.execute("PRAGMA journal_mode=DELETE")
    stats: dict = {}
    try:
        known = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM transcript_statement WHERE symbol IS NOT NULL")]
        for sym in sorted(set(symbols or known)):
            topics, _people = load_topics(_sector_of(sym))
            rows = con.execute("SELECT rowid, quote, topics FROM transcript_statement WHERE symbol=?", (sym,)).fetchall()
            if not rows:
                continue
            before = sum(1 for _rid, _quote, tags in rows if "other" in (tags or ""))
            updates = [(",".join(tag_topics(topics, sym, quote or "")), rid) for rid, quote, _tags in rows]
            con.executemany("UPDATE transcript_statement SET topics=? WHERE rowid=?", updates)
            after = sum(1 for tags, _rid in updates if "other" in tags)
            stats[sym] = {"rows": len(rows), "other_before_pct": round(100.0 * before / len(rows), 1),
                          "other_after_pct": round(100.0 * after / len(rows), 1)}
        con.commit()
    finally:
        con.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None, help="default: every company of the profile, else every pilot3 company")
    ap.add_argument("--profile", default=None, help="build profile JSON (T-056): companies, pages db, raw root, output")
    ap.add_argument("--sandbox-root", default=str(SANDBOX_ROOT))
    ap.add_argument("--limit-docs", type=int, default=None)
    ap.add_argument("--retag", action="store_true",
                    help="re-tag the statements already in --out (T-194); writes only the topics column")
    a = ap.parse_args(argv)
    if a.profile:
        profile.activate(profile.load(a.profile))
    symbols = [s.strip().upper() for s in (a.symbols or ",".join(profile.symbols())).split(",") if s.strip()]
    if a.retag:
        print(json.dumps(retag(a.out, symbols), indent=1))
        return 0
    stats = run(a.out, symbols, None if a.profile else Path(a.sandbox_root), a.limit_docs)
    for k, v in stats.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
