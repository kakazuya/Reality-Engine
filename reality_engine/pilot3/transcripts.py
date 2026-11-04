"""Rule-based earnings-call statement extractor -> table transcript_statement (T-049 B). No model, no OCR, no network.

CLI: python -m reality_engine.pilot3.transcripts --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--sandbox-root DIR]

One row per sentence spoken by management (md/ceo/cfo/mgmt/ir) in a held earnings-call transcript: speaker, role,
section (prepared|qa), topic tags from lexicon/topics.yaml, numbers with unit and period, the exact sentence.
Analysts, the moderator and boilerplate headers/footers are not stored. A sentence that is cut by a page break is
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
from pathlib import Path

import yaml

from .kpi import COMPANIES, LEX_DIR, SANDBOX_ROOT, VAL_RX, _UNIT_BY_SUFFIX, parse_periods, to_float, _norm_cur, profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcript_statement (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, isin TEXT, doc_key TEXT NOT NULL, call_date TEXT, call_period TEXT, page INTEGER NOT NULL,
  seq INTEGER NOT NULL, speaker TEXT NOT NULL, role TEXT NOT NULL, section TEXT NOT NULL,
  topics TEXT NOT NULL, period_discussed TEXT, period_source TEXT, numbers_json TEXT NOT NULL,
  statement TEXT NOT NULL, quote TEXT NOT NULL, is_fragment INTEGER NOT NULL DEFAULT 0,
  known_at TEXT, known_at_source TEXT, extractor_rule TEXT NOT NULL,
  UNIQUE(symbol, doc_key, page, seq)
);
CREATE INDEX IF NOT EXISTS ix_ts_sym_call ON transcript_statement(symbol, call_date);
"""

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
SPEAKER_RX = re.compile(r"^[ 	]*([A-Z][A-Za-z.'’\-]+(?: [A-Za-z.'’\-]+){0,4}):(?=[ 	]|$)", re.M)
SPEAKER_MID_RX = re.compile(r"(?<=[.?!] )([A-Z][A-Za-z.'’\-]+(?: [A-Z][A-Za-z.'’\-]+){1,3}):(?=[ 	]|$)", re.M)
# a bare name line, no colon: "Rishi Basu" / "Salil Parekh" (T-056; only used when colon marks are few)
NAME_ONLY_RX = re.compile(r"^[ \t]*([A-Z][A-Za-z.'’\-]+(?:[ \t]+[A-Z][A-Za-z.'’\-]+){1,3})[ \t]*$", re.M)
SENTENCE_START_RX = re.compile(r"^[\"“‘']?[A-Z][a-z]+(?:[^.!?]*[a-z])")
# "1. Albinder Singh Dhindsa – Chief Executive Officer, Eternal Limited" (one-line participant entry)
NUM_TITLE_RX = re.compile(r"^[ \t]*\d{1,2}[.)]\s*([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){1,3})"
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
PERSON_RX = re.compile(r"[A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){1,3}")
# a line in a participants block that is a document label, not a person ("Investor Call Transcript" was stored as
# a speaker in a cover-letter page by the name look-ahead)
NON_NAME_RX = re.compile(r"\b(?:transcript|call|conference|investor|investors|presentation|earnings|results|"
                         r"dialogue|session)\b", re.I)
PAGE_NO_RX = re.compile(r"^[ \t]*Page \d+ of \d+[ \t]*$", re.M)
DATE_LINE_RX = re.compile(r"^[ \t]*(?:" + MONTHS + r") \d{1,2}, \d{4}[ \t]*$", re.M)
CALL_DATE_RX = re.compile(r"(" + MONTHS + r") (\d{1,2}), (\d{4})")
ABBR = ("Mr", "Ms", "Mrs", "Dr", "Rs", "No", "vs", "Inc", "Ltd", "approx", "Sr", "Jr", "St", "Co", "Corp", "etc", "i.e", "e.g", "FY", "Q")
SENT_END_RX = re.compile(r"(?<=[.?!])[\"”’')]*\s+(?=[\"“‘'(A-Z0-9₹$])")
NOT_SPEAKERS = ("Corporate", "Registered", "Email", "Website", "Phone", "Tel", "Note", "Disclaimer", "Source", "CIN", "Page", "Symbol", "Scrip", "SCRIP", "Sub", "Date", "Ref", "MANAGEMENT", "To", "Dear", "Subject", "Attention")
QA_START_RX = re.compile(r"question[- ]and[- ]answer|first question|open the floor|q ?& ?a session|take (up )?(the )?questions", re.I)
NAME = r"([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3})"
ANALYST_INTRO_RX = re.compile(r"(?i:line of|question (?:is )?from|next question comes from|first question is from)\s+(?i:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*" + NAME)
HOST_INTRO_RX = re.compile(r"(?i:over to|hand (?:the )?conference over to|hand it over to)\s+(?i:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*" + NAME + r"\s+(?i:from|of)\s+")
MGMT_INTRO_RX = re.compile(r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3})\s*[,–-]\s*(?:the\s+)?"
                           # "Vice Chairman and Managing Director", "COO and CFO": words may precede the role
                           r"(?:[A-Za-z][\w.'’\-]*\s+){0,5}?(Managing Director|MD|CEO|Chief Executive|CFO|"
                           r"Chief Financial|COO|Chief Operating|Head of Investor|Whole[- ]time Director|"
                           r"President|Executive Director|Group Chief)", re.I)
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def load_topics():
    d = yaml.safe_load((LEX_DIR / "topics.yaml").read_text(encoding="utf-8"))
    topics = [(t["tag"], [re.compile(p, re.I) for p in t["patterns"]], t.get("companies")) for t in d["topics"]]
    return topics, d.get("people", {})


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


def call_date_of(first_page: str, known_at: str | None) -> str | None:
    m = CALL_DATE_RX.search(first_page[:1500])
    if m:
        mon = [x.lower() for x in MONTHS.split("|")].index(m.group(1).lower()) + 1
        return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    return (known_at or "")[:10] or None


def boilerplate_lines(pages: list[str]) -> set[str]:
    """Lines that repeat on at least 60% of the pages (company name, running headers)."""
    c = Counter()
    for t in pages:
        for l in {x.strip() for x in t.split("\n") if x.strip()}:
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
        if line.strip() in boiler and not SPEAKER_RX.match(line):
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


def participants(pages: list[str]) -> tuple[dict[str, str], list[str], set[str]]:
    """(management name -> role, analysts, every name named) from the participant blocks of the first pages.

    A block is a heading line (``CORPORATE PARTICIPANTS``, ``Management representatives:``, ``ANALYSTS``,
    ``JOURNALISTS``) and then name/title entries: a name line followed by its title line, or one line
    "1. Name – Title".  Management titles go through ``_title_role``; a name under an analysts/journalists
    heading is an analyst and is never stored (T-056)."""
    mgmt: dict[str, str] = {}
    analysts: list[str] = []
    names: set[str] = set()
    kind: str | None = None            # a block that starts on one page continues on the next
    for text in pages[:3]:
        lines = [l.strip() for l in text.split("\n")]
        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            if not line:
                continue
            head = _heading_class(line)
            if head:
                kind = head
                continue
            if kind is None:
                continue
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


def extract_doc(sym: str, doc_key: str, title: str, known_at: str, pages: list[tuple[int, str]], topics, people, st: dict):
    texts = [t for _, t in pages]
    boiler = boilerplate_lines(texts)
    cperiod = call_period_of(title, texts)
    cdate = call_date_of(texts[0], known_at)
    full = "\n".join(texts)
    p_mgmt, p_analysts, p_names = participants(texts)
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
    for page, raw in pages:
        w = mask_noise(raw, boiler)
        marks = sorted((m.start(1), m.end(), m.group(1)) for rx in (SPEAKER_RX, SPEAKER_MID_RX) for m in rx.finditer(w)
                       if not m.group(1).startswith(NOT_SPEAKERS))
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
    seq, started = 0, False
    rows = []
    for page, raw, w, a, b, name, role, section in segments:
        if role not in ("unknown", "analyst"):
            started = True      # cover letter / headers before the first real speaker are not call content
        if not started:
            continue
        if role in ("moderator", "analyst"):
            continue
        if role == "unknown":      # cannot tell management from a stray analyst: counted, not stored
            st["unknown_speakers"][name] += 1
            continue
        for (s0, e0) in split_sentences(w[a:b], a):
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
                         json.dumps(numbers_in(sent, cperiod), ensure_ascii=False), sent, q, frag, known_at,
                         "docs.known_at", "transcript_v1"))
    return rows


COLS = ("symbol isin doc_key call_date call_period page seq speaker role section topics period_discussed period_source "
        "numbers_json statement quote is_fragment known_at known_at_source extractor_rule").split()


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
    src = sqlite3.connect(f"file:{(sandbox / (COMPANIES[sym] + '_loop') / (COMPANIES[sym] + '.db')).as_posix()}?mode=ro",
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
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    stats: dict = {}
    sql = f"INSERT OR IGNORE INTO transcript_statement({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    for sym in symbols:
        con.execute("DELETE FROM transcript_statement WHERE symbol=?", (sym,))
        st = stats[sym] = {"docs": 0, "pages": 0, "needs_ocr": 0, "unknown_speakers": Counter()}
        for index, (doc_key, title, known_at, allp) in enumerate(_transcript_docs(con, sym, sandbox)):
            if limit_docs and index >= limit_docs:
                break
            st["needs_ocr"] += sum(1 for _p, t in allp if not (t or "").strip())
            pages = [(p, t) for p, t in allp if (t or "").strip()]
            if not pages:
                continue
            st["docs"] += 1
            st["pages"] += len(pages)
            con.executemany(sql, extract_doc(sym, doc_key, title, known_at, pages, topics, people, st))
        con.commit()
        st["rows"] = con.execute("SELECT count(*) FROM transcript_statement WHERE symbol=?", (sym,)).fetchone()[0]
        st["unknown_speakers"] = dict(st["unknown_speakers"].most_common(5))
    stats["seconds"] = round(time.time() - t0, 1)
    con.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None, help="default: every company of the profile, else every pilot3 company")
    ap.add_argument("--profile", default=None, help="build profile JSON (T-056): companies, pages db, raw root, output")
    ap.add_argument("--sandbox-root", default=str(SANDBOX_ROOT))
    ap.add_argument("--limit-docs", type=int, default=None)
    a = ap.parse_args(argv)
    if a.profile:
        profile.activate(profile.load(a.profile))
    symbols = [s.strip().upper() for s in (a.symbols or ",".join(profile.symbols())).split(",") if s.strip()]
    stats = run(a.out, symbols, None if a.profile else Path(a.sandbox_root), a.limit_docs)
    for k, v in stats.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
