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
from concurrent.futures import ThreadPoolExecutor

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
NOTES_INLINE = re.compile(r"^\s*notes?\s*[:\-–]\s*(\S.*)$", re.I)
# notes end where the auditor's report begins (signature lines are removed, not used as a stop: in two-column
# layouts the extracted text puts the signature block before the notes)
STOP = re.compile(r"independent\s+auditor|limited\s+review\s+report|review\s+report\s+to", re.I)
# other material that follows the notes in a board-outcome PDF: annexures, disclosures, next page header
AFTER_NOTES = re.compile(r"^\s*(?:annexure\b|part\s*[-–]?\s*i+\b|regd\.?\s*office|registered\s+office|cin\s*[:\-]|"
                         r"brief\s+profile|details\s+(?:of|with\s+respect)|disclosure\s+(?:of|under|pursuant)|"
                         r"reason\s+for\s+change|name\s+of\s+the\s+|statement\s+of\s+(?:assets|cash|deviation)|"
                         r"segment\s*(?:wise|information|reporting|revenue)|sr\.?\s*no\b)", re.I | re.M)
SIGLINE = re.compile(r"^\s*(?:place|date|din|cin)\s*[:\-.]|by\s+order\s+of\s+the\s+board|for\s+and\s+on\s+behalf|"
                     r"^\s*of\s+the\s+board|^\s*for\s+[A-Z][^\n]{2,70}(limited|ltd)\.?\s*,?\s*$|"
                     r"^\s*(?:managing|whole[\s-]*time|executive|independent)?\s*director\s*$|^\s*chairman|"
                     r"^\s*\(?formerly\s+known", re.I)
AUDITOR = re.compile(r"independent\s+auditor'?s?\s+(?:review\s+)?report|limited\s+review\s+report|"
                     r"review\s+report\s+to\s+the\s+board", re.I)
NOTE_NO = re.compile(r"^\s*(?:note\s*(?:no\.?)?\s*)?\(?(\d{1,2})(?:[\.\):]\s*|\s+(?=[A-Z(])|\s*$)(?=\S|$)", re.I)
ROMAN = {r: i for i, r in enumerate(
    "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split(), 1)}
NOTE_ROMAN = re.compile(r"^\s*\(?([ivx]{1,5})[\.\)]\s+(?=\S)", re.I)
# a notes list with no "Notes" heading above it: "Note 1:" or "1. The above results ..."
NOTE_ONE = re.compile(r"^\s*(?:note\s*(?:no\.?)?\s*1\s*[:.\-–]|1[\.\)]\s+the\s+(?:above|financial|standalone|"
                      r"consolidated|un-?audited|audited|results|statement))", re.I)
REFERS = re.compile(r"refer(?:\s+to)?\s+note\s*(?:no\.?\s*)?(\d{1,2})", re.I)
NUM = re.compile(r"\d[\d,]*\.?\d*")


def _basis_near(text_before: str) -> str:
    tail = text_before[-6000:].lower()
    s, c = tail.rfind("standalone"), tail.rfind("consolidated")
    if s < 0 and c < 0:
        return "unknown"
    return "standalone" if s > c else "consolidated"


WORD = re.compile(r"[A-Za-z]{3,}")


def is_prose(body: str) -> bool:
    """A note is sentences: at least 8 real words, and letters outweigh digits."""
    words = WORD.findall(body)
    letters = sum(len(w) for w in words)
    digits = sum(ch.isdigit() for ch in body)
    return len(words) >= 8 and letters >= 1.5 * digits


def split_notes(block: str) -> list[tuple[int | None, str]]:
    """Split a notes block on an increasing 1., 2., 3. numbering at line start. Unnumbered -> one note."""
    lines = block.splitlines()
    out, cur_no, cur, expect = [], None, [], 1
    roman = sum(1 for ln in lines if NOTE_ROMAN.match(ln)) >= 2 and not any(NOTE_NO.match(ln) for ln in lines[:3])
    for ln in lines:
        if roman:
            mr = NOTE_ROMAN.match(ln)
            num = ROMAN.get(mr.group(1).lower()) if mr else None
        else:
            m = NOTE_NO.match(ln)
            num = int(m.group(1)) if m else None
        if num == expect:
            if cur and "".join(cur).strip():
                out.append((cur_no, "\n".join(cur).strip()))
            cur_no, cur, expect = expect, [ln], expect + 1
        else:
            cur.append(ln)
    if cur and "\n".join(cur).strip():
        out.append((cur_no, "\n".join(cur).strip()))
    return out


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
        m = STOP.search(body)
        nxt = STATEMENT.search(body, 200)
        aft = AFTER_NOTES.search(body, 200)
        end = min(x.start() if x else len(body) for x in (m, nxt, aft))
        end = min(end, 15000)
        block = "\n".join(ln for ln in body[:end].splitlines() if not SIGLINE.search(ln)).strip()
        last_end = st + head_end + end
        if len(block) < 40:
            continue
        head = tail.split("\n", 1)[0].lower()
        basis = ("standalone" if "standalone" in head else "consolidated" if "consolidated" in head
                 else _basis_near(full[:st]))
        if basis == "unknown" and res["has_standalone"] != res["has_consolidated"]:
            basis = "standalone" if res["has_standalone"] else "consolidated"
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
            if not is_prose(body):  # table cells caught under a "Notes" column header
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
                notes_found, auditor_report, needs_ocr, xbrl_files, local_path, status, error, fetched_at, processed_at)
                values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (news_id, scrip, meta["isin"], meta["symbol"], meta["company"], dissem, meta["quarter_end"],
                         meta["fy_q"], meta["quarter_source"], filed_q, headline, att, meta["url"],
                         meta.get("http_status"), meta.get("sha256"), meta.get("bytes"), p.get("pages"),
                         p.get("text_chars"), p.get("upper_share"), p.get("low_text_pages"), p.get("doc_class"),
                         p.get("has_standalone"), p.get("has_consolidated"), p.get("notes_found"),
                         int(any(s["section"] == "auditor_report" for s in p.get("sections", []))),
                         p.get("needs_ocr"), meta.get("xbrl_files"), meta.get("local_path"), meta["status"],
                         meta.get("error"), dt.datetime.now().isoformat(timespec="seconds"),
                         dt.datetime.now().isoformat(timespec="seconds")))
            con.execute("delete from notes where news_id=?", (news_id,))
            con.executemany("insert into notes values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", notes)
            stats[meta["status"]] += 1
            stats["notes"] += len(notes)
            n = sum(v for k, v in stats.items() if k != "notes")
            if n % 100 == 0:
                con.commit()
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
    checks = {"fetch_ok>=0.95": (r["fetch_ok_share"] or 0) >= 0.95, "isin>=0.98": (r["isin_share"] or 0) >= 0.98,
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


def run_all(quarters: list[str], workers: int):
    for qe in quarters:
        run(qe, None, workers)
        g = gate(qe)
        print(f"GATE {qe} {fy_q(qe)} passed={g['passed']} checks={g['checks']} "
              f"notes_company={g['notes_company_share']} results_companies={g['results_companies']}", flush=True)
        if not g["passed"]:
            print(f"STOP: gate failed for {qe}; later quarters not started", flush=True)
            return
        to_drive(qe)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "gate", "quarters", "all"])
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
    elif a.cmd == "all":
        qs = sorted({quarter_end_before(r[5]) for r in candidates()}, reverse=True)
        run_all(qs, a.workers)
    else:
        print(json.dumps(gate(a.quarter), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
