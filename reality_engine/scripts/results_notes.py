"""Quarterly results PDFs -> notes chunks, one fiscal quarter at a time (newest first), with a gate per quarter.

Source list: BSE announcements (`bse_announcements.db:ann`, CATEGORYNAME='Result'), FY2024-25 onward.
Each filing is assigned to the latest quarter end before it was disseminated, then confirmed (or moved) by the
"quarter ended ..." date printed in the PDF.

    python -m reality_engine.scripts.results_notes run   --quarter 2026-06-30 [--limit N]
    python -m reality_engine.scripts.results_notes gate  --quarter 2026-06-30
    python -m reality_engine.scripts.results_notes quarters

Writes: PDFs to D:\\RealityEngine\\raw\\results_pdfs\\<quarter_end>\\<sha256>.pdf and the store
reality_engine/data/results_notes.db (docs, notes + FTS5, gate). Reads the live DBs read-only.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pymupdf as fitz
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from reality_engine.config import BSE_HEADERS  # noqa: E402
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = os.path.join(ROOT, "reality_engine", "data")
STORE = os.path.join(DATA, "results_notes.db")
PDF_ROOT = r"D:\RealityEngine\raw\results_pdfs"
URL = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={}"
WINDOW_START = "2024-04-01"  # company data scope: FY2024-25 onward (Shivam, 2026-10-27)
RATE_PER_MIN = 76  # measured sustainable on BSE, 2026-10-27 probe (0 blocks)
PARSER_VERSION = "notes-v2"  # bump when parsing changes; `reparse` redoes older rows from the stored PDFs

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  news_id TEXT PRIMARY KEY, scrip_cd INTEGER, isin TEXT, symbol TEXT, company TEXT,
  known_at TEXT, quarter_end TEXT, fy_q TEXT, quarter_source TEXT, filed_quarter_end TEXT,
  headline TEXT, attachment TEXT, url TEXT, http_status INTEGER, sha256 TEXT, bytes INTEGER,
  pages INTEGER, text_chars INTEGER, upper_share REAL, low_text_pages INTEGER,
  doc_class TEXT, has_standalone INTEGER, has_consolidated INTEGER, notes_found INTEGER,
  auditor_report INTEGER, needs_ocr INTEGER, dup_of TEXT, xbrl_files TEXT, local_path TEXT,
  drive_path TEXT, status TEXT, error TEXT, fetched_at TEXT, processed_at TEXT);
CREATE INDEX IF NOT EXISTS ix_docs_q ON docs(quarter_end);
CREATE INDEX IF NOT EXISTS ix_docs_isin_q ON docs(isin, quarter_end);
CREATE INDEX IF NOT EXISTS ix_docs_sha ON docs(sha256);
CREATE TABLE IF NOT EXISTS notes (
  chunk_id TEXT PRIMARY KEY, news_id TEXT, isin TEXT, symbol TEXT, company TEXT, known_at TEXT,
  quarter_end TEXT, fy_q TEXT, basis TEXT, section TEXT, note_no INTEGER, page_from INTEGER, page_to INTEGER,
  header TEXT, body TEXT, char_len INTEGER, has_numbers INTEGER, refers_notes TEXT, xbrl_files TEXT);
CREATE INDEX IF NOT EXISTS ix_notes_isin_q ON notes(isin, quarter_end);
CREATE INDEX IF NOT EXISTS ix_notes_news ON notes(news_id);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(header, body, content='notes', content_rowid='rowid');
CREATE TABLE IF NOT EXISTS gate (quarter_end TEXT PRIMARY KEY, report TEXT, passed INTEGER, created_at TEXT);
"""


# ---------------------------------------------------------------- quarters
def quarter_end_before(ts: str) -> str:
    """Latest quarter end (Mar 31 / Jun 30 / Sep 30 / Dec 31) strictly before the dissemination date."""
    d = dt.date.fromisoformat(ts[:10])
    for y in (d.year, d.year - 1):
        for m, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
            q = dt.date(y, m, day)
            if q < d:
                return q.isoformat()
    raise ValueError(ts)


def fy_q(quarter_end: str) -> str:
    d = dt.date.fromisoformat(quarter_end)
    q = {6: 1, 9: 2, 12: 3, 3: 4}[d.month]
    fy = d.year + 1 if d.month != 3 else d.year
    return f"Q{q}FY{fy % 100:02d}"


_DATE_PATTERNS = [
    re.compile(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-.,/]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
               r"[\s\-.,/']*(20\d{2})", re.I),
    re.compile(r"(\d{1,2})[\-./](\d{1,2})[\-./](20\d{2})"),
]
_ENDED = re.compile(r"(?:quarter|period|year|months|half[\s-]*year)\s+ended\s*(?:on\s*)?[:\-]?\s*(.{0,30})", re.I)


def _as_quarter_end(day: int, month: int, year: int) -> str | None:
    if (month, day) in ((3, 31), (6, 30), (9, 30), (12, 31)):
        return dt.date(year, month, day).isoformat()
    return None


_QTR_ENDED = re.compile(r"(?:quarter|three\s+months|3\s+months|period)\s+ended\s*(?:on\s*)?[:\-]?\s*(.{0,30})", re.I)
_MDY = re.compile(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})", re.I)


def _dates_in(frag: str) -> list[str]:
    out = []
    g = _MDY.search(frag)
    if g:
        b, a, y = g.groups()
        q = _as_quarter_end(int(a), MONTHS[b[:3].lower()], int(y))
        if q:
            out.append(q)
    for p in _DATE_PATTERNS:
        g = p.search(frag)
        if g:
            a, b, y = g.groups()
            try:
                month = MONTHS[b[:3].lower()] if not b.isdigit() else int(b)
                q = _as_quarter_end(int(a), month, int(y))
            except (KeyError, ValueError):
                q = None
            if q:
                out.append(q)
    return out


def detect_quarter(text: str, filed_q: str) -> str | None:
    """The reporting quarter: the LATEST quarter-end written after 'quarter / three months / period ended', not
    after the filing date. Comparative columns (previous quarter, year ended March) are older, so latest wins.
    'Year ended' counts only when it is the filed quarter itself (annual results for March)."""
    found = {q for m in _QTR_ENDED.finditer(text[:200000]) for q in _dates_in(m.group(1)) if q <= filed_q}
    if not found:
        found = {q for m in _ENDED.finditer(text[:200000]) for q in _dates_in(m.group(1)) if q == filed_q}
    return max(found) if found else None


# ---------------------------------------------------------------- PDF parsing
# a new statement table starts: a title line, not a sentence that mentions "financial results"
STATEMENT = re.compile(r"^\s*(?:part\s*[-–]?\s*i+\s*[:\-–]?\s*)?statement\s+of\b[^\n]{0,100}financial\s+results",
                       re.I | re.M)
NOTES_HEAD = re.compile(r"^\s*(?:notes?\s*[:\-–]?\s*$|notes?\s+(?:to|forming(?:\s+part\s+of)?|on)\s+(?:the\s+)?"
                        r"(?:statement|standalone|consolidated|financial|unaudited|audited|results)[^\n]*$)", re.I)
NOTES_HEAD_M = re.compile(NOTES_HEAD.pattern, re.I | re.M)
CONTD = re.compile(r"contd|continued", re.I)
NOTES_INLINE = re.compile(r"^\s*notes?\s*[:\-–]\s*(\S.*)$", re.I)
# notes end where the auditor's report begins (signature lines are removed, not used as a stop: in two-column
# layouts the extracted text puts the signature block before the notes). A stop counts only as a heading line, so
# "... along with the Limited Review Report" inside a sentence does not cut the note.
STOP = re.compile(r"independent\s+auditor|limited\s+review\s+report|review\s+report\s+to|report\s+on\s+the\s+audit|"
                  r"basis\s+for\s+(?:qualified\s+)?opinion|auditor'?s?\s+report", re.I)
# auditor, press-release and cover-letter text: these end a notes block wherever they appear
STOP_ANY = re.compile(r"we\s+have\s+(?:reviewed|audited)\s+the\s+accompanying|we\s+conducted\s+our\s+review|"
                      r"forward[\s-]+looking\s+statements?|for\s+further\s+(?:details|information),?\s+please\s+contact|"
                      r"^\s*(?:dear\s+sir|yours\s+(?:faithfully|truly|sincerely)|thanking\s+you)", re.I | re.M)
# other material that follows the notes in a board-outcome PDF: annexures, disclosures, next page header
AFTER_NOTES = re.compile(r"^\s*(?:annexure\b|part\s*[-–]?\s*i+\b|regd\.?\s*office|registered\s+office|cin\s*[:\-]|"
                         r"brief\s+profile|details\s+(?:of|with\s+respect)|disclosure\s+(?:of|under|pursuant)|"
                         r"reason\s+for\s+change|name\s+of\s+the\s+|statement\s+of\s+(?:assets|cash|deviation)|"
                         r"segment\s*(?:wise|information|reporting|revenue)|sr\.?\s*no\b)", re.I | re.M)
AUDITOR = re.compile(r"independent\s+auditor'?s?\s+(?:review\s+)?report|limited\s+review\s+report|"
                     r"review\s+report\s+to\s+the\s+board", re.I)
NOTE_NO = re.compile(r"^\s*(?:note\s*(?:no\.?)?\s*)?\(?(\d{1,2})(?:[\.\):]\s*|\s+(?=[A-Z(])|\s*$)(?=\S|$)", re.I)
NOTE_BARE = re.compile(r"^\s*\(?\d{1,2}[\.\):]?\s*$")
ROMAN = {r: i for i, r in enumerate(
    "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split(), 1)}
NOTE_ROMAN = re.compile(r"^\s*\(?([ivx]{1,5})[\.\)]\s+(?=\S)", re.I)
LIST_MARK = re.compile(r"^\s*(?:\(?[a-z]\)|[a-z]\.|\(?[ivx]{1,5}\)|[ivx]{1,5}\.|[•\-–])\s*$", re.I)
# a notes list with no "Notes" heading above it: "Note 1:" or "1. The above results ..."
NOTE_ONE = re.compile(r"^\s*(?:note\s*(?:no\.?)?\s*1\s*[:.\-–]|1[\.\)]\s+the\s+(?:above|financial|standalone|"
                      r"consolidated|un-?audited|audited|results|statement))", re.I)
REFERS = re.compile(r"refer(?:\s+to)?\s+note\s*(?:no\.?\s*)?(\d{1,2})", re.I)
NUM = re.compile(r"\d[\d,]*\.?\d*")
WORD = re.compile(r"[A-Za-z]{3,}")
FUNC = re.compile(r"\b(?:the|of|and|to|in|for|has|have|been|is|are|was|were|by|with|on|as|which|that|from|at)\b",
                  re.I)

# ------------------------------------------------ line cleaning (signatures, letterheads, table cells, OCR noise)
SIG_STRONG = re.compile(r"digitally\s+signed|\+0?5'?\s?30'?|\bdin\s*(?:no\.?)?\s*[:\-–.]?\s*\d{6,}|"
                        r"chartered\s+accountants|firm\s+reg(?:istration|n)?\.?\s*(?:no|number)|membership\s+no|"
                        r"for\s+and\s+on\s+(?:the\s+)?behalf|on\s+behalf\s+of\s+the\s+board|"
                        r"by\s+(?:the\s+)?order\s+of\s+the\s+board|^\s*of\s+the\s+board|for\s+identification|"
                        r"as\s+per\s+our\s+(?:attached\s+)?report|&\s*co\.?\s*(?:llp)?\.?\s*$|\(retd\.?\)|"
                        r"^\s*for\s+[^\n]{2,60}"
                        r"(?:limited|ltd\.?|llp)\s*[,.]?\s*$|^\s*\(?formerly\s+know", re.I)
SIG_WEAK = re.compile(r"^\s*(?:place|date|dated|din|cin|pan|gstin|tel|phone|fax|e-?mail|website|web|regd|"
                      r"registered\s+office|corporate\s+office|m\.?\s*no)\b\s*[:.\-–]?|"
                      r"\b(?:cin|pan|gstin)\s*(?:no\.?)?\s*[:\-–]?\s*[A-Z0-9]{8,}|www\.|https?://|@[\w-]+\.(?:com|in|co)|"
                      r"^\s*page\s+\d+(?:\s+of\s+\d+)?\s*$|[-–]\s*\d{3}\s?\d{3}\b|^\s*\+\d|"
                      r"^\s*\(?(?:managing\s+director|joint\s+managing|"
                      r"whole[\s-]*time\s+director|executive\s+director|non[\s-]*executive|independent\s+director|"
                      r"director|chairman|chairperson|chief\s+executive|chief\s+financial|ceo|cfo|company\s+secretary|"
                      r"compliance\s+officer|partner|proprietor|vice\s+chair|md\s*(?:&|and)\s*ceo)\b|"
                      r"(?:director|chairman|chairperson|ceo|cfo|secretary|officer|partner)\s*\)?\s*$", re.I)
# signature openers are never note text, however many words they have
SIG_LEAD = re.compile(r"^\s*(?:for\s+and\s+on|on\s+behalf|by\s+(?:the\s+)?order|for\s+[A-Z][^\n]{2,60}"
                      r"(?:limited|ltd\.?|llp)\b)", re.I)
CONTACT = re.compile(r"[\w.\-]+@[\w\-]+\.\w|regd\.?\s*off|registered\s+office|corporate\s+office|"
                     r"\bcin\s*(?:no\.?)?\s*[:\-–]?\s*[lu]\s?\d{5}|\b(?:tel|ph|phone|fax)\s*[.:]?\s*[+\d(]", re.I)
COMPANY_LINE = re.compile(r"(?:limited|ltd\.?|llp|corporation|industries)\s*[,.]?\s*\)?\s*$", re.I)
DATE_LINE = re.compile(r"^\s*(?:[A-Za-z .]{0,25}[:,]\s*)?(?:\d{1,2}(?:st|nd|rd|th)?[\s./-]*(?:[A-Za-z]{3,9}|\d{1,2})"
                       r"[\s.,/-]*\d{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\s*$")
CELL = re.compile(r"^[\s\d,.()\[\]{}%₹$*#@'\"\-–—/:|+=~]*$")
SENT_END = re.compile(r"[.;!?][\"'”)]*\s*$")


def _numeric(s: str) -> bool:
    s = s.strip()
    return bool(s) and (bool(CELL.match(s)) and bool(re.search(r"\d", s)) or s.lower() in {"-", "–", "—", "nil"})


def _wordy(s: str) -> float:
    toks = s.split()
    if not toks:
        return 0.0
    good = sum(1 for t in toks if re.fullmatch(r"[(\"'“‘]?[A-Za-z][A-Za-z'’\-&]*[A-Za-z]?[)\"'”’.,:;]*", t)
               and re.search(r"[aeiouyAEIOUY]", t))
    return good / len(toks)


def _name_like(s: str) -> bool:
    toks = s.strip().strip("()").split()
    return 1 <= len(toks) <= 5 and all(re.fullmatch(r"[A-Z][A-Za-z.\-']*,?", t) for t in toks)


def _continues(lines: list[str], i: int) -> bool:
    """Line i finishes a sentence the previous line left open ('... visit our website and' / 'www.bseindia.com')."""
    j = next((k for k in range(i - 1, -1, -1) if lines[k].strip()), None)
    if j is None:
        return False
    prev = lines[j]
    return (not SENT_END.search(prev) and not prev.rstrip().endswith(":") and len(FUNC.findall(prev)) >= 2
            and len(prev.split()) >= 6)


def clean_block(block: str) -> str:
    """Drop signature/letterhead lines, table regions, column headers and OCR noise; keep the note prose."""
    lines = [ln.rstrip() for ln in block.splitlines()]
    n = len(lines)
    nw = [len(ln.split()) for ln in lines]
    drop = [False] * n
    strong = [False] * n
    nxt = lambda i: next((j for j in range(i + 1, n) if lines[j].strip()), None)  # noqa: E731
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        marker = bool(NOTE_BARE.match(s) or LIST_MARK.match(s))
        if CONTACT.search(s) and len(FUNC.findall(s)) <= 2:
            drop[i] = strong[i] = True  # letterhead / address / contact line, however long
            continue
        if nw[i] >= 8 and len(FUNC.findall(s)) >= 3 and not SIG_LEAD.match(s):
            continue  # a sentence that names the auditors or a website is note text
        if SIG_STRONG.search(s) and nw[i] <= 14:
            drop[i] = strong[i] = True
        elif SIG_WEAK.search(s) and nw[i] <= 8 and not (i and _continues(lines, i)):
            drop[i] = strong[i] = True
        elif marker:
            continue
        elif nw[i] <= 10 and _wordy(s) < 0.5 and not _numeric(s) and not (i and _continues(lines, i)):
            drop[i] = True  # OCR noise, stamps
    # names, cities, dates and company lines next to a signature marker
    for i, ln in enumerate(lines):
        s = ln.strip()
        if drop[i] or not s:
            continue
        near = any(strong[j] for j in range(max(0, i - 3), min(n, i + 4)))
        pk = next((j for j in range(i - 1, -1, -1) if lines[j].strip() and not drop[j]), None)
        if (pk is not None and not SENT_END.search(lines[pk]) and not lines[pk].rstrip().endswith(":")
                and len(FUNC.findall(lines[pk])) >= 2):
            continue  # "... meeting held on" / "February 04, 2026." is the end of a sentence
        prev_list = i > 0 and bool(LIST_MARK.match(lines[i - 1].strip()))
        if nw[i] <= 7 and COMPANY_LINE.search(s) and not prev_list and len(FUNC.findall(s)) <= 1:
            drop[i] = True
        elif near and nw[i] <= 5 and (_name_like(s) or DATE_LINE.match(s)):
            drop[i] = True
    # table regions: >=3 numeric cell lines with gaps of at most 3 short lines; bare note numbers followed by prose
    # are markers, not cells
    def cell(i):
        s = lines[i].strip()
        if not _numeric(s) or drop[i]:
            return False
        if NOTE_BARE.match(s):
            j = nxt(i)
            return not (j is not None and nw[j] >= 5 and not _numeric(lines[j]))
        return True
    cells = [i for i in range(n) if cell(i)]
    k = 0
    while k < len(cells):
        j = k
        while j + 1 < len(cells) and cells[j + 1] - cells[j] <= 4 and all(
                nw[t] <= 10 or _numeric(lines[t]) for t in range(cells[j] + 1, cells[j + 1])):
            j += 1
        if j - k + 1 >= 3:
            a, b = cells[k], cells[j]
            while a > 0 and lines[a - 1].strip() and nw[a - 1] <= 8 and not SENT_END.search(lines[a - 1]) \
                    and not lines[a - 1].rstrip().endswith(":") and not NOTE_NO.match(lines[a - 1]) \
                    and a > cells[k] - 6:
                a -= 1  # column headers above the table
            for t in range(a, b + 1):
                drop[t] = True
        k = j + 1
    # short title / column-header lines after a finished sentence
    kept_prev = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if drop[i] or not s:
            continue
        if (kept_prev is not None and nw[i] <= 4 and not SENT_END.search(s) and not s.endswith(":")
                and not NOTE_NO.match(s) and not LIST_MARK.match(s) and SENT_END.search(lines[kept_prev])
                and nw[kept_prev] >= 4):
            j = nxt(i)
            if j is None or not lines[j].strip()[:1].islower():
                drop[i] = True
                continue
        kept_prev = i
    out = [ln for i, ln in enumerate(lines) if not drop[i]]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _basis_near(text_before: str) -> str:
    tail = text_before[-6000:].lower()
    s, c = tail.rfind("standalone"), tail.rfind("consolidated")
    if s < 0 and c < 0:
        return "unknown"
    return "standalone" if s > c else "consolidated"


COVER = re.compile(r"enclos(?:ed|ing)\s+herewith|we\s+are\s+enclosing|please\s+find\s+(?:enclosed|attached)|"
                   r"kindly\s+take\s+(?:the\s+)?(?:same\s+)?on\s+(?:your\s+)?record|request(?:ed)?\s+you\s+to\s+take", re.I)
AUD_TEXT = re.compile(r"we\s+conducted\s+our\s+review|we\s+have\s+reviewed\s+the\s+accompanying|"
                      r"standard\s+on\s+review\s+engagements|nothing\s+has\s+come\s+to\s+our\s+attention|"
                      r"we\s+do\s+not\s+express\s+an\s+audit\s+opinion", re.I)


def is_prose(body: str) -> bool:
    """A note is sentences: at least 8 real words, function words, letters outweigh digits, mostly full lines."""
    words = WORD.findall(body)
    letters = sum(len(w) for w in words)
    digits = sum(ch.isdigit() for ch in body)
    if len(words) < 8 or letters < 1.5 * digits or len(FUNC.findall(body)) < 2:
        return False
    # narrow columns wrap a sentence over many short lines, so judge the words, not the line lengths: prose has
    # function words; table row labels ("Purchase of investments measured under amortised cost") have few
    nwords = len(re.findall(r"[A-Za-z]{2,}", body))
    if len(FUNC.findall(body)) >= 0.10 * nwords:
        return True
    # a list of entities or ratios still counts when it carries one real sentence
    flat = re.sub(r"\s+", " ", body)
    return any(len(s.split()) >= 10 and len(FUNC.findall(s)) >= 3 for s in re.findall(r"[^.;]+[.;]", flat))


def trim_tail(body: str) -> str:
    """Drop short non-sentence lines after the last finished sentence (names, stamps, 'Indore', '1.:.')."""
    lines = body.splitlines()
    last = max((i for i, ln in enumerate(lines) if SENT_END.search(ln) and re.search(r"[A-Za-z0-9]{3}", ln)),
               default=None)
    if last is None or last == len(lines) - 1:
        return body
    tail = [ln for ln in lines[last + 1:] if ln.strip()]
    if all(len(ln.split()) <= 6 for ln in tail) and sum(len(ln) for ln in tail) < 120:
        return "\n".join(lines[:last + 1]).strip()
    return body


def is_note(body: str) -> bool:
    """Prose that is a results note, not the auditor's review text or the cover letter."""
    return is_prose(body) and not AUD_TEXT.search(body) and not COVER.search(body)


def _seq_from(nums: list[int], s: int) -> int:
    n, e = 0, s
    for a in nums:
        if a == e:
            n, e = n + 1, e + 1
    return n


def split_notes(block: str) -> list[tuple[int | None, str]]:
    """Split a notes block on an increasing 1., 2., 3. numbering at line start. Unnumbered -> one note.
    A block that continues on a later page may start at 7., 8., ...: numbering starts at the value that gives the
    longest increasing run."""
    lines = block.splitlines()
    arabic = [int(m.group(1)) for m in (NOTE_NO.match(ln) for ln in lines) if m]
    first = 1
    if arabic and _seq_from(arabic, 1) < 2:
        cands = list(dict.fromkeys(arabic))[:5]
        best = max(cands, key=lambda s: (_seq_from(arabic, s), -s))
        if _seq_from(arabic, best) >= 2:
            first = best
    roman = sum(1 for ln in lines if NOTE_ROMAN.match(ln)) >= 2 and _seq_from(arabic, first) < 2
    out, cur_no, cur, expect = [], None, [], first
    for ln in lines:
        if roman:
            mr = NOTE_ROMAN.match(ln)
            num = ROMAN.get(mr.group(1).lower()) if mr else None
        else:
            m = NOTE_NO.match(ln)
            num = int(m.group(1)) if m else None
            if num is None and expect == 1 and ln.strip() in ("I", "l", "I.", "l.", "I)"):
                num = 1  # OCR reads a lone "1" as I or l
        if num == expect:
            carry = []
            # a number printed beside the middle of its paragraph: the note began after the last finished sentence
            if (NOTE_BARE.match(ln) and cur and (len(cur) > 1 or cur_no is None) and not SENT_END.search(cur[-1])
                    and not cur[-1].rstrip().endswith(":") and len(cur[-1].split()) >= 8):
                k = len(cur) - 1
                while k > 1 and not SENT_END.search(cur[k - 1]):
                    k -= 1
                if SENT_END.search(cur[k - 1]):
                    carry, cur = cur[k:], cur[:k]
                elif cur_no is None:
                    carry, cur = cur, []  # the opening paragraph belongs to the first number
            if cur and "".join(cur).strip():
                out.append((cur_no, "\n".join(cur).strip()))
            cur_no, cur, expect = expect, [ln] + carry, expect + 1
        else:
            cur.append(ln)
    if cur and "\n".join(cur).strip():
        out.append((cur_no, "\n".join(cur).strip()))
    return out


def _caps_title(body: str, start: int) -> int:
    """Position of the next all-capitals statement title ('UNAUDITED CONSOLIDATED FINANCIAL RESULTS FOR ...')."""
    pos = 0
    for ln in body.splitlines(keepends=True):
        s = ln.strip()
        if pos >= start and 3 <= len(s.split()) <= 25 and re.search(r"financial\s+results|statement\s+of", s, re.I):
            letters = [ch for ch in s if ch.isalpha()]
            if letters and sum(ch.isupper() for ch in letters) / len(letters) >= 0.7:
                return pos
        pos += len(ln)
    return len(body)


def _heading_stop(rx, body: str, start: int = 0, allow_after_colon: bool = True) -> int:
    """First match of rx that is a heading line (line starts with it, short, after a finished line)."""
    for m in rx.finditer(body, start):
        ls = body.rfind("\n", 0, m.start()) + 1
        le = body.find("\n", m.start())
        line = body[ls: len(body) if le < 0 else le].strip()
        if m.start() - ls > 6 or len(line.split()) > 20:
            continue
        prev = body[:ls].rstrip().rsplit("\n", 1)[-1].strip()
        if prev.endswith(":") and not allow_after_colon:
            continue
        pl = [ch for ch in prev if ch.isalpha()]
        if (not prev or re.search(r"[.;:)]$", prev) or len(prev.split()) <= 3 or NOTE_BARE.match(prev)
                or _wordy(prev) < 0.5 or (pl and sum(ch.isupper() for ch in pl) / len(pl) > 0.7)):
            return m.start()
    return len(body)


def block_basis(head: str, block: str, before: str, res: dict) -> str:
    head = head.lower()
    if "standalone" in head or "consolidated" in head:
        return "standalone" if "standalone" in head else "consolidated"
    basis = _basis_near(before)
    if basis != "unknown":
        return basis
    if not res["has_consolidated"]:
        return "standalone"  # a company with no subsidiaries files standalone results only
    if res["has_standalone"] != res["has_consolidated"]:
        return "standalone" if res["has_standalone"] else "consolidated"
    low = block[:3000].lower()
    s, c = "standalone" in low, "consolidated" in low
    if s != c:
        return "standalone" if s else "consolidated"
    return _basis_near(before[:-6000] if len(before) > 6000 else "")


def parse_pdf(path: str) -> dict:
    doc = fitz.open(path)
    pages = [p.get_text("text") for p in doc]
    doc.close()
    full = "\n".join(pages)
    letters = re.findall(r"[A-Za-z]", full)
    upper = sum(ch.isupper() for ch in letters) / len(letters) if letters else 0.0
    low_pages = sum(1 for t in pages if len(t.strip()) < 100)
    has_stmt = bool(re.search(r"financial\s+results", full, re.I)) and len(NUM.findall(full)) > 150
    res = {"pages": len(pages), "text_chars": len(full), "upper_share": round(upper, 4),
           "low_text_pages": low_pages, "has_standalone": int(bool(re.search(r"standalone", full, re.I))),
           "has_consolidated": int(bool(re.search(r"consolidated", full, re.I))), "sections": [],
           "full_text": full}
    # notes blocks: from a 'Notes' heading to the next stop marker or statement title
    offsets, acc = [], 0
    for t in pages:
        offsets.append(acc)
        acc += len(t) + 1
    page_of = lambda pos: max(i for i, o in enumerate(offsets) if o <= pos) + 1  # noqa: E731
    pos = 0
    lines = full.splitlines(keepends=True)
    starts = []
    for ln in lines:
        if NOTES_HEAD.match(ln) or NOTES_INLINE.match(ln) or NOTE_ONE.match(ln):
            starts.append(pos)
        pos += len(ln)
    last_end = -1
    for st in starts:
        if st < last_end:  # a "Note" line inside a block already taken
            continue
        tail = full[st:]
        head_end = tail.find("\n") + 1 if NOTES_HEAD.match(tail.split("\n", 1)[0]) else 0
        body = tail[head_end:]
        ends = [_heading_stop(STOP, body), _heading_stop(AFTER_NOTES, body, 200, allow_after_colon=False),
                _caps_title(body, 200)]
        for rx in (STOP_ANY, STATEMENT):
            m = rx.search(body, 200 if rx is STATEMENT else 0)
            ends.append(m.start() if m else len(body))
        # the next basis' notes start a new block (a "(continued)" page header does not)
        m = next((x for x in NOTES_HEAD_M.finditer(body, 200) if not CONTD.search(x.group(0))), None)
        ends.append(m.start() if m else len(body))
        end = min(min(ends), 15000)
        block = clean_block(body[:end])
        last_end = st + head_end + end
        if len(block) < 40:
            continue
        basis = block_basis(tail.split("\n", 1)[0], block, full[:st], res)
        res["sections"].append({"section": "notes", "basis": basis, "page_from": page_of(st),
                                "page_to": page_of(st + head_end + end), "text": block})
    am = AUDITOR.search(full)
    if am:
        block = full[am.start():am.start() + 12000]
        res["sections"].append({"section": "auditor_report", "basis": _basis_near(full[:am.start()] + block[:600]),
                                "page_from": page_of(am.start()), "page_to": page_of(am.start() + len(block)),
                                "text": block.strip()})
    notes_found = sum(1 for s in res["sections"] if s["section"] == "notes")
    if notes_found and has_stmt:
        res["doc_class"] = "results_with_notes"
    elif has_stmt:
        res["doc_class"] = "results_no_notes_found"
    elif len(full.strip()) < 300 * max(1, len(pages)) and low_pages >= max(1, len(pages) // 2):
        res["doc_class"] = "scanned_needs_ocr"
    else:
        res["doc_class"] = "not_results"
    res["notes_found"] = notes_found
    res["needs_ocr"] = int(res["doc_class"] == "scanned_needs_ocr")
    return res


# ---------------------------------------------------------------- store
def store() -> sqlite3.Connection:
    con = sqlite3.connect(STORE, timeout=120, check_same_thread=False)  # writes are serialised by a lock
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    if "parser_version" not in {r[1] for r in con.execute("pragma table_info(docs)")}:
        con.execute("alter table docs add column parser_version TEXT")
    return con


def isin_map() -> dict[int, tuple[str, str, str]]:
    c = connect_ro(os.path.join(DATA, "equity_intelligence.db"))
    out = {}
    for isin, sym, code, name in c.execute(
            "select isin, nse_symbol, bse_code, company_name from master_companies where coalesce(bse_code,'')<>''"):
        try:
            out[int(code)] = (isin, sym, name)
        except ValueError:
            pass
    # BSE-only names missing from master: ISIN from BSE daily price files (every 5th session since the window start)
    dates = [d for (d,) in c.execute("select distinct date from mkt_bse_eq_daily where date >= ? order by date desc",
                                     (WINDOW_START,))][::5]
    for d in dates:
        for sc, isin, sym, name in c.execute("select sc_code, isin, symbol, name from mkt_bse_eq_daily where date=?",
                                             (d,)):
            try:
                out.setdefault(int(sc), (isin, sym, (name or "").title() or sym))
            except (TypeError, ValueError):
                pass
    return out


def xbrl_files(isin: str | None, scrip: int, quarter_end: str) -> list[str]:
    """XBRL filings for the same company and quarter: by ISIN, else by BSE code (ISINs change, e.g. renames)."""
    x = connect_ro(os.path.join(DATA, "results_xbrl.db"))
    rows = x.execute("select file, consolidated from filings where isin=? and period_end=?",
                     (isin, quarter_end)).fetchall() if isin else []
    if not rows:
        rows = x.execute("select file, consolidated from filings where scrip_code in (?, ?) and period_end=?",
                         (scrip, str(scrip), quarter_end)).fetchall()
    return [f"{f}:{'C' if c else 'S'}" for f, c in rows]


def candidates(quarter: str | None = None) -> list[tuple]:
    b = connect_ro(os.path.join(DATA, "bse_announcements.db"))
    rows = b.execute("""select NEWSID, SCRIP_CD, symbol, ATTACHMENTNAME, HEADLINE, DissemDT, Fld_Attachsize
        from ann where CATEGORYNAME='Result' and SUBCATNAME='Financial Results' and DissemDT >= ?
        and coalesce(ATTACHMENTNAME,'')<>''""", (WINDOW_START,)).fetchall()
    if quarter:
        rows = [r for r in rows if quarter_end_before(r[5]) == quarter]
    return rows


# ---------------------------------------------------------------- run
class Bucket:
    """Global request pacing across threads."""

    def __init__(self, per_min: float):
        self.gap, self.next, self.lock = 60.0 / per_min, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next)
            self.next = t + self.gap
        time.sleep(max(0.0, t - time.time()))


def fetch_one(sess, bucket, att: str, dest_dir: str) -> dict:
    for attempt in range(4):
        bucket.wait()
        try:
            r = sess.get(URL.format(att), timeout=120)
        except requests.RequestException as e:
            err = str(e)[:150]
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code in (403, 429, 503):
            time.sleep(60 * (attempt + 1))  # back off, never rotate
            err = f"http {r.status_code}"
            continue
        body = r.content
        if r.status_code != 200 or body[:4] != b"%PDF":
            return {"http_status": r.status_code, "error": f"not a pdf ({r.headers.get('Content-Type','')})",
                    "status": "fetch_failed"}
        sha = hashlib.sha256(body).hexdigest()
        p = os.path.join(dest_dir, sha + ".pdf")
        if not os.path.exists(p):
            with open(p + ".part", "wb") as fh:
                fh.write(body)
            os.replace(p + ".part", p)
        return {"http_status": 200, "sha256": sha, "bytes": len(body), "local_path": p, "status": "fetched"}
    return {"http_status": None, "error": err, "status": "fetch_failed"}


def chunk_rows(news_id, meta, parsed, xfiles):
    rows = []
    for si, s in enumerate(parsed["sections"]):
        parts = split_notes(s["text"]) if s["section"] == "notes" else [(None, s["text"])]
        for k, (no, body) in enumerate(parts):
            if s["section"] == "notes":
                body = trim_tail(body)
            if not (is_note(body) if s["section"] == "notes" else is_prose(body)):  # table cells, auditor text
                continue
            label = "Results notes" if s["section"] == "notes" else "Auditor's review report"
            note = f" · note {no}" if no else ""
            header = (f"{meta['company']} ({meta['symbol'] or meta['scrip_cd']}) · {label} · {meta['fy_q']} "
                      f"(quarter ended {meta['quarter_end']}) · {s['basis']}{note} · filed {meta['known_at'][:10]}")
            cid = hashlib.sha1(f"{news_id}|{si}|{s['section']}|{k}".encode()).hexdigest()[:20]
            rows.append((cid, news_id, meta["isin"], meta["symbol"], meta["company"], meta["known_at"],
                         meta["quarter_end"], meta["fy_q"], s["basis"], s["section"], no, s["page_from"], s["page_to"],
                         header, body, len(body), int(len(NUM.findall(body)) >= 3),
                         ",".join(sorted(set(REFERS.findall(body)))), ",".join(xfiles)))
    return rows


def run(quarter: str, limit: int | None, workers: int):
    con = store()
    imap = isin_map()
    done = {r[0] for r in con.execute("select news_id from docs where status in ('processed','fetch_failed')")}
    rows = [r for r in candidates(quarter) if r[0] not in done]
    random.Random(7).shuffle(rows)
    if limit:
        rows = rows[:limit]
    dest = os.path.join(PDF_ROOT, quarter)
    os.makedirs(dest, exist_ok=True)
    sess = requests.Session()
    sess.headers.update(BSE_HEADERS)
    sess.headers.setdefault("Referer", "https://www.bseindia.com/")
    bucket = Bucket(RATE_PER_MIN)
    lock = threading.Lock()
    stats = collections.Counter()
    t0 = time.time()

    def work(r):
        news_id, scrip, sym_ann, att, headline, dissem, size = r
        isin, sym, name = imap.get(int(scrip), (None, sym_ann, None))
        filed_q = quarter_end_before(dissem)
        meta = {"news_id": news_id, "scrip_cd": scrip, "isin": isin, "symbol": sym or sym_ann, "company": name or (sym or sym_ann or str(scrip)),
                "known_at": dissem, "headline": headline, "attachment": att, "url": URL.format(att),
                "filed_quarter_end": filed_q}
        f = fetch_one(sess, bucket, att, dest)
        meta.update(f)
        parsed, notes = None, []
        if f["status"] == "fetched":
            try:
                parsed = parse_pdf(f["local_path"])
                pq = detect_quarter(parsed["full_text"], filed_q)
                meta["quarter_end"], meta["quarter_source"] = (pq, "pdf_text") if pq else (filed_q, "filing_date")
                meta["fy_q"] = fy_q(meta["quarter_end"])
                xf = xbrl_files(isin, scrip, meta["quarter_end"])
                meta["xbrl_files"] = ",".join(xf)
                notes = chunk_rows(news_id, meta, parsed, xf)
                meta["status"] = "processed"
            except Exception as e:  # a broken PDF must not stop the run
                meta.update(status="parse_failed", error=str(e)[:150])
        if "quarter_end" not in meta:
            meta["quarter_end"], meta["quarter_source"], meta["fy_q"] = filed_q, "filing_date", fy_q(filed_q)
        with lock:
            p = parsed or {}
            con.execute("""insert or replace into docs (news_id, scrip_cd, isin, symbol, company, known_at,
                quarter_end, fy_q, quarter_source, filed_quarter_end, headline, attachment, url, http_status, sha256,
                bytes, pages, text_chars, upper_share, low_text_pages, doc_class, has_standalone, has_consolidated,
                notes_found, auditor_report, needs_ocr, xbrl_files, local_path, status, error, fetched_at, processed_at,
                parser_version) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (news_id, scrip, meta["isin"], meta["symbol"], meta["company"], dissem, meta["quarter_end"],
                         meta["fy_q"], meta["quarter_source"], filed_q, headline, att, meta["url"],
                         meta.get("http_status"), meta.get("sha256"), meta.get("bytes"), p.get("pages"),
                         p.get("text_chars"), p.get("upper_share"), p.get("low_text_pages"), p.get("doc_class"),
                         p.get("has_standalone"), p.get("has_consolidated"), p.get("notes_found"),
                         int(any(s["section"] == "auditor_report" for s in p.get("sections", []))),
                         p.get("needs_ocr"), meta.get("xbrl_files"), meta.get("local_path"), meta["status"],
                         meta.get("error"), dt.datetime.now().isoformat(timespec="seconds"),
                         dt.datetime.now().isoformat(timespec="seconds"), PARSER_VERSION if parsed else None))
            con.execute("delete from notes where news_id=?", (news_id,))
            con.executemany("insert into notes values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", notes)
            con.commit()  # per document, so a concurrent `reparse` can take the write lock between documents
            stats[meta["status"]] += 1
            stats["notes"] += len(notes)
            n = sum(v for k, v in stats.items() if k != "notes")
            if n % 100 == 0:
                rate = n / max(1e-9, (time.time() - t0) / 60)
                print(f"{quarter} {n}/{len(rows)} {dict(stats)} {rate:.1f}/min", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, rows))
    con.commit()
    con.execute("insert into notes_fts(notes_fts) values('rebuild')")
    con.commit()
    print(f"{quarter} done {dict(stats)} in {(time.time() - t0) / 60:.1f} min", flush=True)


# ---------------------------------------------------------------- gate
def gate(quarter: str) -> dict:
    con = store()
    q = lambda s, *a: con.execute(s, a).fetchall()  # noqa: E731
    filed = q("select count(*), count(distinct scrip_cd) from docs where filed_quarter_end=?", quarter)[0]
    status = dict(q("select status, count(*) from docs where filed_quarter_end=? group by 1", quarter))
    classes = dict(q("select coalesce(doc_class,'-'), count(*) from docs where quarter_end=? group by 1", quarter))
    moved = q("select count(*) from docs where filed_quarter_end=? and quarter_end<>filed_quarter_end", quarter)[0][0]
    res_docs = q("""select count(*), count(distinct isin), sum(isin is not null), sum(xbrl_files<>''),
        sum(upper_share>0.02) from docs where quarter_end=? and doc_class like 'results%'""", quarter)[0]
    with_notes = q("select count(distinct isin) from docs where quarter_end=? and doc_class='results_with_notes'",
                   quarter)[0][0]
    dups = q("""select count(*) - count(distinct sha256) from docs where quarter_end=? and sha256 is not null""",
             quarter)[0][0]
    n_notes = q("select count(*), sum(section='notes'), sum(note_no is not null), avg(char_len) from notes "
                "where quarter_end=?", quarter)[0]
    basis = dict(q("select basis, count(*) from notes where quarter_end=? group by 1", quarter))
    sample = q("""select header, substr(body,1,300) from notes where quarter_end=? and section='notes'
        order by random() limit 8""", quarter)
    fetched = sum(v for k, v in status.items() if k != "fetch_failed")
    r = {
        "quarter_end": quarter, "fy_q": fy_q(quarter), "filings": filed[0], "companies_filing": filed[1],
        "status": status, "fetch_ok_share": round(fetched / filed[0], 3) if filed[0] else None,
        "doc_class": classes, "moved_by_pdf_date": moved,
        "results_docs": res_docs[0], "results_companies": res_docs[1],
        "isin_share": round((res_docs[2] or 0) / res_docs[0], 3) if res_docs[0] else None,
        "xbrl_link_share": round((res_docs[3] or 0) / res_docs[0], 3) if res_docs[0] else None,
        "cased_text_share": round((res_docs[4] or 0) / res_docs[0], 3) if res_docs[0] else None,
        "companies_with_notes": with_notes,
        "notes_company_share": round(with_notes / res_docs[1], 3) if res_docs[1] else None,
        "duplicate_files": dups, "chunks": n_notes[0], "note_chunks": n_notes[1], "numbered_notes": n_notes[2],
        "avg_chunk_chars": round(n_notes[3] or 0), "basis": basis,
        "sample": [{"header": h, "body": b} for h, b in sample],
    }
    unresolved = q("select count(*) from docs where quarter_end=? and doc_class like 'results%' and isin is null",
                   quarter)[0][0]
    r["no_isin_docs"] = unresolved  # identity still held by the BSE code; listed in the morning report
    checks = {"fetch_ok>=0.95": (r["fetch_ok_share"] or 0) >= 0.95, "isin>=0.97": (r["isin_share"] or 0) >= 0.97,
              "notes_company>=0.80": (r["notes_company_share"] or 0) >= 0.80,
              "cased>=0.95": (r["cased_text_share"] or 0) >= 0.95}
    r["checks"] = checks
    r["passed"] = all(checks.values())
    con.execute("insert or replace into gate values (?,?,?,?)", (quarter, json.dumps(r, ensure_ascii=False),
                                                                int(r["passed"]), dt.datetime.now().isoformat()))
    con.commit()
    return r


RCLONE = r"C:\Users\warri\AppData\Local\Microsoft\WinGet\Links\rclone.exe"
DRIVE_ROOT = "gdrive:InfoDiffusion_archive/results_pdfs"


def to_drive(quarter: str) -> bool:
    """Move a passed quarter's PDFs to Google Drive (rclone checks each file's hash before removing it locally)."""
    import subprocess
    src, dst = os.path.join(PDF_ROOT, quarter), f"{DRIVE_ROOT}/{quarter}"
    r = subprocess.run([RCLONE, "move", src, dst, "--transfers", "4", "--checksum", "--include", "*.pdf",
                        "--log-level", "NOTICE"], capture_output=True, text=True)
    ok = r.returncode == 0
    con = store()
    if ok:
        con.execute("update docs set drive_path=? || '/' || sha256 || '.pdf' where filed_quarter_end=? and sha256 is not null",
                    (dst, quarter))
        con.commit()
    print(f"{quarter} drive move {'ok' if ok else 'FAILED'} {r.stderr[-300:]}", flush=True)
    return ok


def _reparse_one(d: dict):
    """Parse one stored PDF with the current parser; runs in a worker process."""
    parsed = parse_pdf(d["path"])
    pq = detect_quarter(parsed["full_text"], d["filed_quarter_end"])
    d["quarter_end"], d["quarter_source"] = (pq, "pdf_text") if pq else (d["filed_quarter_end"], "filing_date")
    d["fy_q"] = fy_q(d["quarter_end"])
    xf = xbrl_files(d["isin"], d["scrip_cd"], d["quarter_end"])
    d["xbrl_files"] = ",".join(xf)
    rows = chunk_rows(d["news_id"], d, parsed, xf)
    parsed["auditor_report"] = int(any(s["section"] == "auditor_report" for s in parsed["sections"]))
    parsed.pop("full_text")
    parsed.pop("sections")
    return d, parsed, rows


def reparse(quarter: str, workers: int, from_drive: bool = True) -> dict:
    """Re-parse a filed quarter's processed docs still on an older parser version, from the stored PDFs (no BSE
    refetch). Copies the quarter back from Drive first when files are missing locally, swaps docs+notes rows in one
    transaction, and moves the PDFs back to Drive afterwards."""
    import subprocess
    con = store()
    cols = ["news_id", "scrip_cd", "isin", "symbol", "company", "known_at", "filed_quarter_end", "sha256"]
    stale = [dict(zip(cols, r)) for r in con.execute(
        f"select {', '.join(cols)} from docs where filed_quarter_end=? and status='processed' "
        "and coalesce(parser_version,'')<>?", (quarter, PARSER_VERSION))]
    if not stale:
        print(f"{quarter} reparse: nothing stale", flush=True)
        return {"stale": 0}
    src = os.path.join(PDF_ROOT, quarter)
    for d in stale:
        d["path"] = os.path.join(src, f"{d['sha256']}.pdf")
        d["scrip_cd"] = int(d["scrip_cd"])
    missing = [d for d in stale if not os.path.exists(d["path"])]
    copied = False
    if missing and from_drive:
        t0 = time.time()
        r = subprocess.run([RCLONE, "copy", f"{DRIVE_ROOT}/{quarter}", src, "--transfers", "8", "--checksum",
                            "--include", "*.pdf", "--log-level", "NOTICE"], capture_output=True, text=True)
        copied = r.returncode == 0
        print(f"{quarter} reparse: drive copy {'ok' if copied else 'FAILED'} for {len(missing)} missing in "
              f"{(time.time() - t0) / 60:.1f} min {r.stderr[-300:]}", flush=True)
    todo = [d for d in stale if os.path.exists(d["path"])]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(_reparse_one, todo, chunksize=8))
    now = dt.datetime.now().isoformat(timespec="seconds")
    n_notes = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for d, p, rows in out:
            con.execute("""update docs set quarter_end=?, fy_q=?, quarter_source=?, pages=?, text_chars=?,
                upper_share=?, low_text_pages=?, doc_class=?, has_standalone=?, has_consolidated=?, notes_found=?,
                auditor_report=?, needs_ocr=?, xbrl_files=?, processed_at=?, parser_version=? where news_id=?""",
                        (d["quarter_end"], d["fy_q"], d["quarter_source"], p["pages"], p["text_chars"],
                         p["upper_share"], p["low_text_pages"], p["doc_class"], p["has_standalone"],
                         p["has_consolidated"], p["notes_found"], p["auditor_report"],
                         p["needs_ocr"], d["xbrl_files"], now, PARSER_VERSION, d["news_id"]))
            con.execute("delete from notes where news_id=?", (d["news_id"],))
            con.executemany("insert into notes values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            n_notes += len(rows)
        con.commit()
    except Exception:
        con.rollback()
        raise
    con.execute("insert into notes_fts(notes_fts) values('rebuild')")
    con.commit()
    res = {"stale": len(stale), "reparsed": len(out), "unreadable": len(stale) - len(todo), "notes": n_notes}
    print(f"{quarter} reparse {res} in {(time.time() - t0) / 60:.1f} min", flush=True)
    if copied:
        to_drive(quarter)
    return res


def run_all(quarters: list[str], workers: int):
    for qe in quarters:
        run(qe, None, workers)
        reparse(qe, workers, from_drive=False)  # docs parsed by an older version before a restart
        g = gate(qe)
        print(f"GATE {qe} {fy_q(qe)} passed={g['passed']} checks={g['checks']} "
              f"notes_company={g['notes_company_share']} results_companies={g['results_companies']}", flush=True)
        if not g["passed"]:
            print(f"STOP: gate failed for {qe}; later quarters not started", flush=True)
            return
        to_drive(qe)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "gate", "quarters", "all", "reparse"])
    ap.add_argument("--quarter")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.cmd == "quarters":
        c = collections.Counter(quarter_end_before(r[5]) for r in candidates())
        for qe in sorted(c, reverse=True):
            print(qe, fy_q(qe), c[qe])
    elif a.cmd == "run":
        run(a.quarter, a.limit, a.workers)
    elif a.cmd == "reparse":
        reparse(a.quarter, a.workers)
        g = gate(a.quarter)
        print(f"GATE {a.quarter} {fy_q(a.quarter)} passed={g['passed']} checks={g['checks']} "
              f"notes_company={g['notes_company_share']} basis={g['basis']}", flush=True)
    elif a.cmd == "all":
        qs = sorted({quarter_end_before(r[5]) for r in candidates()}, reverse=True)
        run_all(qs, a.workers)
    else:
        print(json.dumps(gate(a.quarter), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
