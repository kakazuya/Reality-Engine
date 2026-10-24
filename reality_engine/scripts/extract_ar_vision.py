"""Chart/image-aware vision pass for annual-report image pages and low-text deck leftovers.

Reuses the deck page-reader path (reality_engine/scripts/extract_deck_figures.py): the same routing
gate (text layer -> image coverage -> RapidOCR number count), the same renderer process isolation,
the same reader configs / adaptive limiters / 429 handling, and the same ``metric | period | number |
unit`` parser.  What is new is only what differs:

* AR results go to four NEW additive tables in ``ar_facts.db`` (``ar_vision_pages``,
  ``ar_vision_outputs``, ``ar_vision_facts``, ``ar_vision_chart_trends``) carrying
  doc_id/isin/symbol/fiscal_year/page_no/known_at.  The existing AR text tables are never written.
* Deck leftovers are the pages the first deck pass skipped as low-text/image-heavy; they are re-read
  into the existing deck tables under the prompt version ``leftover-<hash>``.
* Readers are FREE only: dots-3-note-preview on Kilo key 1, Kilo key 2 and OpenRouter free.  A reader
  is culled for 30 min after three consecutive failures (on top of the deck client's 429 bench).

Page selection (AR): docs whose text pipeline found text on < 50% of pages (the ~700 reports /
86k pages named in the readiness note), ordered newest filing first, plus FY26 reports whose text
layer is dense but garbage (the ~70 mis-encoded reports; a one-time sampled scan caches the verdict
in ar_vision_docs, so no hand-maintained list is needed).  Inside them a page is read when its text
layer is unusable (empty or mis-encoded) OR sparse, it is image-heavy, and RapidOCR finds numbers in
the image (when RapidOCR is unavailable every such page is read, never silently skipped).

Page selection (decks): previously skipped pages with text_chars < 100, image coverage >= 0.5 and
no vision output of any kind, newest deck first.  Deck PDFs are fetched from
``gdrive:InfoDiffusion_archive/decks`` on demand and deleted after their pages are read.

Queue sizes measured 2026-10-25 (--queue): AR FY26 128 docs / 17,568 pages (14,986 image-only);
older AR 572 docs / 68,485 pages (58,535 image-only); FY26 dense-text reports to scan 4,988;
deck leftovers 60,059 pages (86,151 with the looser text_chars<200/img_cov>=0.15 cutoff).
Throughput on the free readers: ~8,000-10,000 pages/hour with RapidOCR installed (OCR is the gate
bottleneck), ~10,000-12,000 without it; measured dots-3 latency 4-20 s/page, 64 requests in flight.

Usage (from the repository root; run_chart_pass.cmd loops this until done):

  python -m reality_engine.scripts.extract_ar_vision --target ar --scope fy26 --workers 60
  python -m reality_engine.scripts.extract_ar_vision --target decks --workers 60
  python -m reality_engine.scripts.extract_ar_vision --target all --workers 60
  python -m reality_engine.scripts.extract_ar_vision --queue          # queue sizes, no reads
  python -m reality_engine.scripts.extract_ar_vision --gate 30        # quality gate, writes no DB rows

Resumable: (doc_id, page, prompt_version) finished pages are skipped; a page gets three attempts
before its error is final.  One process per output DB (a lock file refuses a second writer).
Logs: reality_engine/data/logs/chart_pass.log.
"""
import argparse
import base64
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pymupdf

from reality_engine.scripts import extract_deck_figures as deck
from reality_engine.scripts.resource_watchdog import user_env

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT") or DATA)
AR_DB = DATA_ROOT / "ar_facts.db"
DECK_DB = DATA_ROOT / "deck_figures.db"
LIVE_DB = DATA_ROOT / "equity_intelligence.db"
LOG = DATA / "logs" / "chart_pass.log"
MARKER = DATA / "logs" / "chart_pass.current"   # PDF being rendered inline; left behind if MuPDF kills the process
DOWNLOAD_DIR = DATA / "chart_pdfs"
GATE_DIR = DATA / "chart_gate"
GDRIVE = "gdrive:InfoDiffusion_archive"
RCLONE = "rclone"

# Page gate.  AR pages with real prose are the text pipeline's job; a page is a vision candidate only
# when the text layer is unusable/sparse AND the image carries numbers.
AR_LOW_TEXT = 200            # chars; clearly a low-text page
AR_SPARSE_TEXT = 1000        # chars; sparse page with almost no numbers (captions around one chart)
GATE_OCR_NUMBERS = 2         # RapidOCR numbers in the image before a page is worth a reader call
DECK_LOW_TEXT = 100          # deck leftovers: the strict low-text class
DECK_MIN_IMG_COV = 0.5       # deck leftovers: genuinely image-heavy
MIN_IMG_COV = 0.15
OCR_SIDE = 2200              # RapidOCR longest side (table digits are small)
MAX_PAGE_ATTEMPTS = 3        # page cull after three failed reads
READER_STRIKES = 3           # reader cull after three consecutive failures
BENCH_SEC = 30 * 60
TEXT_LAYER_CHARS = 6000

# ---------------------------------------------------------------- prompts
# Two prompts are compared in the quality gate; the better one is used in production.  Both parse
# with the deck parser (metric | period | number | unit); CHART lines carry trend evidence without
# inventing figures (same rule as the deck chart_trends table).
AR_CONTEXT = ("Company: {company} (NSE/BSE symbol {symbol}), an Indian listed company. "
              "Document: annual report for the fiscal year ending {fiscal} filed {filed}. "
              "Indian fiscal year runs April-March (Q1 = Apr-Jun).")
PROMPT_A = ("List every business or financial number printed on this annual-report page, one per line, in this exact format:\n"
            "metric | period | number | unit\n"
            "Copy each number EXACTLY as printed, character for character, including commas, brackets, decimal points and % "
            "(e.g. 28,00,000 or (1.44) or 18.2%). Do not convert or round. Use - for an unknown period or unit. "
            "First line must be: TITLE | <page title>. If there are no numbers, output only the TITLE line.")
PROMPT_B = ("Read this annual-report page like an analyst building a fact table. Output one line per printed figure:\n"
            "metric | period | number | unit\n"
            "Work region by region: every table cell, chart data label, KPI box, note and body-text figure that a "
            "financial database would store. metric = the row/column/axis/legend label plus the segment or product it "
            "belongs to; period = the column header, axis or caption (e.g. FY26, FY25, Q1FY27, 9MFY26); unit = the "
            "unit printed in the cell or the table/chart header. Copy numbers exactly as printed (keep Indian grouping, "
            "brackets and %); never recompute or convert. Use - only when the page prints no period/unit. "
            "First line must be: TITLE | <page title>.\n"
            "For a chart whose values are not printed as labels, add one line per measurable trend: "
            "CHART | measure | span | trend (e.g. CHART | Revenue | FY22-FY26 | rising from ~1,200 to ~2,400). "
            "Never output a number that is not printed on the page.")
AR_RULES = deck.RULES + ("\n- CHART lines are only for charts with no printed data labels; put the measure, the period span "
                         "and the direction in words, never an invented value.")
VARIANTS = {"a": PROMPT_A, "b": PROMPT_B}
PROMPT_VERSION = hashlib.sha1(json.dumps([PROMPT_A, PROMPT_B, AR_RULES, TEXT_LAYER_CHARS, 1600, 85]).encode()).hexdigest()[:10]
DECK_LEFTOVER_VERSION = "leftover-" + hashlib.sha1(json.dumps([deck.PROMPT, deck.RULES, "leftover", 1600, 85]).encode()).hexdigest()[:8]

log = logging.getLogger("chart_pass")


def register_readers():
    """Free dots-3 readers.  Kilo entries already exist in the deck config; OpenRouter is added here."""
    deck.MODELS.setdefault("dots-3@openrouter", {
        "api": "chat", "id": "dots-studio/dots-3-note-preview:free", "base": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY", "price": (0.0, 0.0), "capped": False, "ceiling": 4,
        "body": {"temperature": 0, "max_tokens": 8000, "reasoning": {"enabled": False}}})
    return ["dots-studio/dots-3-note-preview:free", "dots-studio/dots-3-note-preview:free@kilo2", "dots-3@openrouter"]


# ---------------------------------------------------------------- parsing
CHART_LINE = re.compile(r"^\s*CHART\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*$", re.I)


def parse_chart_lines(output):
    out = []
    for line in (output or "").splitlines():
        m = CHART_LINE.match(line)
        if m and m.group(1) and m.group(3):
            out.append({"measure": m.group(1)[:300], "span": m.group(2)[:80], "trend": m.group(3)[:300]})
    return out


def facts_of(output):
    """Deck parser + a usability filter: a metric that is only digits is not a label (the reader lost the
    table row on a faint page), so those rows are dropped rather than stored as unidentifiable facts."""
    facts = []
    for f in deck.parse_facts(output or ""):
        if f["metric"].strip().upper() == "CHART" or not re.search(r"[A-Za-z]", f["metric"] or ""):
            continue
        f["unit"] = deck.currency_scale_unit(f["metric"], f["raw"], f["unit"]) or f["unit"]
        facts.append(f)
    return facts


def build_prompt(task, variant="a"):
    ctx = AR_CONTEXT.format(company=task.get("company") or task["symbol"], symbol=task["symbol"],
                            fiscal=str(task.get("fiscal_year") or "")[:10], filed=str(task.get("known_at") or "")[:10])
    p = ctx + "\n" + VARIANTS[variant] + "\n" + AR_RULES
    text = (task.get("text") or "").strip()
    if text and not task.get("garbled"):
        p += ("\n\nText extracted from this page's PDF text layer (order may be jumbled; use it to confirm exact digits, "
              "use the image for which label, period and unit each number belongs to):\n<<<\n" + text[:TEXT_LAYER_CHARS] + "\n>>>")
    return p


# ---------------------------------------------------------------- OCR and garbled text
_OCR = []
_OCR_LOCK = threading.Lock()


def ocr_text(page, side=OCR_SIDE):
    """RapidOCR (DirectML) text of the rendered page; '' when unavailable."""
    with _OCR_LOCK:
        if not _OCR:
            try:
                from rapidocr import RapidOCR
                _OCR.append(RapidOCR(params={"EngineConfig.onnxruntime.use_dml": True, "Global.log_level": "ERROR",
                                             "Global.max_side_len": side}))
            except Exception:
                _OCR.append(None)
    if _OCR[0] is None:
        return None
    try:
        zoom = side / max(page.rect.width, page.rect.height)
        png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
        r = _OCR[0](png)
        return " ".join(r.txts or ()) if r is not None else ""
    except Exception:
        return None


BAD_CAT = {"Cc", "Cf", "Co", "Cn", "Cs"}


def garbled(text):
    """True for a text layer that is unusable: control/private-use/replacement bytes dominate, or the
    printable-letter share is tiny.  A Hindi page is not garbled (Devanagari letters count)."""
    t = (text or "").strip()
    if len(t) < 40:
        return False
    bad = 0
    letters = 0
    for c in t:
        if c in "\n\r\t ":
            continue
        if c == "\ufffd" or unicodedata.category(c) in BAD_CAT:
            bad += 1
        elif c.isalpha():
            letters += 1
    return bad / len(t) > 0.02 or letters / len(t) < 0.25


def page_kind(page):
    text = page.get_text()
    g = garbled(text)
    truth = set() if g else deck.text_numbers(text)
    img_area = sum(abs(pymupdf.Rect(i["bbox"]) & page.rect) for i in page.get_image_info())
    img_cov = min(1.0, img_area / (abs(page.rect) or 1.0))
    return text, g, truth, img_cov


def ar_page_task(page, page_no):
    """Route one annual-report page.  Vision only for unusable/sparse text + image + numbers in the image."""
    text, g, truth, img_cov = page_kind(page)
    chars = len(text.strip())
    sparse = chars < AR_LOW_TEXT or (len(truth) < 3 and chars < AR_SPARSE_TEXT)
    if not (g or sparse) or img_cov < MIN_IMG_COV:
        return {"page_no": page_no, "text": text, "text_chars": chars, "truth": truth, "img_cov": round(img_cov, 3),
                "garbled": int(g), "ocr": None, "route": "skip"}
    ocr = ocr_text(page)
    if ocr is None:
        route = "vision"          # no OCR: do not guess, read it
    else:
        route = "vision" if len(deck.text_numbers(ocr)) >= GATE_OCR_NUMBERS else "skip_ocr"
    return {"page_no": page_no, "text": text, "text_chars": chars, "truth": truth, "ocr_truth": deck.text_numbers(ocr or ""),
            "img_cov": round(img_cov, 3), "garbled": int(g), "ocr": len(deck.text_numbers(ocr or "")), "route": route}


def render_ar_doc(path, skip_pages):
    """Runs in a child process: route/render every not-done page of one PDF."""
    out = []
    with pymupdf.open(path) as pdf:
        n = pdf.page_count
        for k, page in enumerate(pdf):
            if k + 1 in skip_pages:
                continue
            t = ar_page_task(page, k + 1)
            t["jpeg"] = deck.render_jpeg_b64(page) if t["route"] == "vision" else None
            out.append(t)
    return n, out


# ---------------------------------------------------------------- readers
class CullClient:
    """Deck client + a three-consecutive-failure cull per reader.  The deck client already benches quota
    429s; this adds a cull for repeated provider errors so a dead reader is not retried all night."""

    def __init__(self, client, models):
        self.client, self.models = client, models
        # deck.choose() reads these off the client it is handed
        self.limiters, self.ledger, self.pacer = client.limiters, client.ledger, getattr(client, "pacer", None)
        self.strikes, self.until = Counter(), {}
        self.lock = threading.Lock()

    def _fail(self, model):
        with self.lock:
            self.strikes[model] += 1
            if self.strikes[model] >= READER_STRIKES:
                self.until[model] = time.time() + BENCH_SEC
                self.client.ledger.block(model, BENCH_SEC, f"{READER_STRIKES} consecutive failures")
                self.strikes[model] = 0

    def _ok(self, model):
        with self.lock:
            self.strikes[model] = 0

    def culled(self, model):
        return self.until.get(model, 0) > time.time()

    def read(self, model, b64, prompt, tries=4, wait_on_cap=True):
        if self.culled(model):
            raise deck.CapReached(f"{model} culled")
        try:
            r = self.client.read(model, b64, prompt, tries=tries, wait_on_cap=wait_on_cap)
            self._ok(model)
            return r
        except Exception:
            self._fail(model)
            raise


def choose_reader(client, primaries, turn):
    return deck.choose(client, primaries[turn % len(primaries)], primaries)


def read_page(client, primaries, task, jpeg, prompt, turn):
    """One primary reading, with the other free primaries as fallback; the cull wrapper enforces strikes."""
    first = choose_reader(client, primaries, turn)
    try:
        return first, client.read(first, jpeg, prompt)
    except Exception:
        for m in primaries:
            if m == first or client.culled(m):
                continue
            try:
                return m, client.read(m, jpeg, prompt, tries=3)
            except Exception:
                continue
        raise


# ---------------------------------------------------------------- storage
AR_SCHEMA = """
CREATE TABLE IF NOT EXISTS ar_vision_pages (
  doc_id INTEGER, page_no INTEGER, prompt_version TEXT,
  isin TEXT, symbol TEXT, fiscal_year TEXT, known_at TEXT, sha256 TEXT, path TEXT,
  route TEXT, text_chars INTEGER, text_numbers INTEGER, img_cov REAL, garbled INTEGER, ocr_numbers INTEGER,
  primary_recall REAL, final_model TEXT, n_facts INTEGER, n_charts INTEGER,
  attempts INTEGER DEFAULT 1, status TEXT, error TEXT, run_ts TEXT,
  PRIMARY KEY (doc_id, page_no, prompt_version));
CREATE TABLE IF NOT EXISTS ar_vision_outputs (
  doc_id INTEGER, page_no INTEGER, prompt_version TEXT, model TEXT,
  isin TEXT, symbol TEXT, fiscal_year TEXT, known_at TEXT,
  settings TEXT, run_ts TEXT, seconds REAL, in_tok INTEGER, out_tok INTEGER, usd REAL, raw_output TEXT,
  PRIMARY KEY (doc_id, page_no, prompt_version, model));
CREATE TABLE IF NOT EXISTS ar_vision_facts (
  doc_id INTEGER, page_no INTEGER, prompt_version TEXT, model TEXT, line_no INTEGER,
  isin TEXT, symbol TEXT, fiscal_year TEXT, known_at TEXT,
  metric TEXT, period TEXT, raw_number TEXT, value REAL, unit TEXT, is_final INTEGER);
CREATE INDEX IF NOT EXISTS ar_vision_facts_doc ON ar_vision_facts(doc_id, page_no);
CREATE TABLE IF NOT EXISTS ar_vision_chart_trends (
  doc_id INTEGER, page_no INTEGER, prompt_version TEXT, model TEXT,
  isin TEXT, symbol TEXT, fiscal_year TEXT, known_at TEXT,
  measure TEXT, span TEXT, trend TEXT,
  PRIMARY KEY (doc_id, page_no, prompt_version, measure));
CREATE TABLE IF NOT EXISTS ar_vision_docs (
  doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, fiscal_year TEXT, known_at TEXT,
  n_pages INTEGER, n_text_pages INTEGER, garbled INTEGER, sample_pages INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS bad_docs (sha256 TEXT PRIMARY KEY, path TEXT, strikes INTEGER, last_page INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS doc_pages (sha256 TEXT PRIMARY KEY, n_pages INTEGER);
CREATE TABLE IF NOT EXISTS run_lock (name TEXT PRIMARY KEY, pid INTEGER, ts TEXT);
"""


class Store:
    """One writer connection (single-writer rule) with a thread lock, schema additive only."""

    def __init__(self, path, create=True):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, check_same_thread=False, timeout=60)
        self.con.execute("PRAGMA journal_mode=WAL")
        if create:
            self.con.executescript(AR_SCHEMA)
        self.lock = threading.Lock()

    def execute(self, sql, args=()):
        with self.lock:
            self.con.execute(sql, args)
            self.con.commit()

    def query(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).fetchall()

    def save_page(self, task, res):
        now = datetime.now().isoformat(timespec="seconds")
        facts = res.get("facts") or []
        charts = res.get("charts") or []
        with self.lock:
            c = self.con
            model = res.get("model") or "unknown"
            r = res.get("reading") or {}
            if r:
                c.execute("INSERT OR REPLACE INTO ar_vision_outputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (task["doc_id"], task["page_no"], PROMPT_VERSION, model, task.get("isin"), task["symbol"],
                           task.get("fiscal_year"), task.get("known_at"),
                           json.dumps(deck.MODELS.get(model, {}).get("body", {})),
                           now, r.get("seconds", 0), r.get("in_tok", 0), r.get("out_tok", 0), r.get("usd", 0.0),
                           r.get("output", "")))
            c.execute("DELETE FROM ar_vision_facts WHERE doc_id=? AND page_no=? AND prompt_version=?",
                      (task["doc_id"], task["page_no"], PROMPT_VERSION))
            c.executemany("INSERT INTO ar_vision_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          [(task["doc_id"], task["page_no"], PROMPT_VERSION, model, i, task.get("isin"), task["symbol"],
                            task.get("fiscal_year"), task.get("known_at"), f["metric"], f["period"], f["raw"],
                            f["value"], f["unit"], 1) for i, f in enumerate(facts)])
            c.execute("DELETE FROM ar_vision_chart_trends WHERE doc_id=? AND page_no=? AND prompt_version=?",
                      (task["doc_id"], task["page_no"], PROMPT_VERSION))
            c.executemany("INSERT OR REPLACE INTO ar_vision_chart_trends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          [(task["doc_id"], task["page_no"], PROMPT_VERSION, model, task.get("isin"), task["symbol"],
                            task.get("fiscal_year"), task.get("known_at"), ch["measure"], ch["span"], ch["trend"])
                           for ch in charts])
            prev = c.execute("SELECT attempts FROM ar_vision_pages WHERE doc_id=? AND page_no=? AND prompt_version=?",
                             (task["doc_id"], task["page_no"], PROMPT_VERSION)).fetchone()
            attempts = (prev[0] if prev else 0) + (0 if res.get("status") == "ok" else 1)
            c.execute("INSERT OR REPLACE INTO ar_vision_pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (task["doc_id"], task["page_no"], PROMPT_VERSION, task.get("isin"), task["symbol"],
                       task.get("fiscal_year"), task.get("known_at"), task.get("sha256"), task.get("path"), task["route"],
                       task["text_chars"], len(task.get("truth") or ()), task["img_cov"], task.get("garbled", 0),
                       task.get("ocr"), res.get("recall"), model, len(facts), len(charts), attempts, res["status"],
                       res.get("error"), now))
            c.commit()

    def done_keys(self):
        return {(r[0], r[1]) for r in self.query(
            "SELECT doc_id, page_no FROM ar_vision_pages WHERE prompt_version=? AND "
            "(status IN ('ok','skipped') OR (status='error' AND attempts>=?))", (PROMPT_VERSION, MAX_PAGE_ATTEMPTS))}

    def save_doc(self, d, garbled_flag=None, sample=0):
        self.execute("INSERT OR REPLACE INTO ar_vision_docs VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (d["doc_id"], d.get("isin"), d["symbol"], d.get("fiscal_year"), d.get("known_at"),
                      d.get("n_pages"), d.get("n_text_pages"), garbled_flag, sample,
                      datetime.now().isoformat(timespec="seconds")))


def process_page(client, primaries, task, jpeg, turn):
    prompt = build_prompt(task, PROMPT_VARIANT)
    try:
        model, p = read_page(client, primaries, task, jpeg, prompt, turn)
        facts = facts_of(p["output"])
        truth = set(task.get("truth") or ()) | set(task.get("ocr_truth") or ())
        return {"status": "ok", "model": model, "reading": p, "facts": facts,
                "charts": parse_chart_lines(p["output"]), "recall": deck.recall(deck.fact_numbers(facts), truth)}
    except deck.CapReached as e:
        return {"status": "error", "error": f"cap: {e}"[:400], "facts": [], "charts": []}
    except Exception as e:
        return {"status": "error", "error": str(e)[:400], "facts": [], "charts": []}


# ---------------------------------------------------------------- AR queue
AR_FY26_SQL = "substr(fiscal_year,1,4) >= '2026'"
AR_OLD_SQL = "substr(fiscal_year,1,4) < '2026'"


def load_ar_docs(con, scope="all", limit=0, min_text_share=0.5):
    where = "n_pages > 0 AND n_text_pages < ?*n_pages"
    args = [min_text_share]
    if scope == "fy26":
        where += " AND " + AR_FY26_SQL
    elif scope == "older":
        where += " AND " + AR_OLD_SQL
    elif scope == "fy26-all":            # every FY26 report: garbled-scan input
        where = "n_pages > 0 AND " + AR_FY26_SQL
        args = []
    q = f"""SELECT doc_id, isin, symbol, company, fiscal_year, filed_at, path, sha256, n_pages, n_text_pages
            FROM ar_docs WHERE {where} ORDER BY fiscal_year DESC, filed_at DESC"""
    rows = con.execute(q, args).fetchall()
    docs = [dict(zip(("doc_id", "isin", "symbol", "company", "fiscal_year", "known_at", "path", "sha256",
                      "n_pages", "n_text_pages"), r)) for r in rows]
    return docs[:limit] if limit else docs


def scan_garbled(store, src, sample=4):
    """One-time FY26 scan: flag reports whose text layer is dense but garbage (the ~70 mis-encoded
    reports).  Samples `sample` pages spread through each report, caches the verdict in
    ar_vision_docs, and returns the flagged doc ids.  Documents already scanned are not reopened."""
    seen = {r[0] for r in store.query("SELECT doc_id FROM ar_vision_docs")}
    docs = [d for d in load_ar_docs(src, "fy26-all") if d["doc_id"] not in seen and d.get("path")
            and Path(d["path"]).exists()]
    log.info("garbled scan: %d FY26 reports to sample", len(docs))
    flagged = set(r[0] for r in store.query("SELECT doc_id FROM ar_vision_docs WHERE garbled=1"))
    for i, d in enumerate(docs, 1):
        try:
            pdf = pymupdf.open(d["path"])
            try:
                n = pdf.page_count
                idxs = sorted({round(k * (n - 1) / max(1, sample - 1)) for k in range(min(sample, n))})
                share = sum(garbled(pdf[k].get_text()) for k in idxs) / max(1, len(idxs))
            finally:
                pdf.close()
        except Exception:
            continue
        bad = int(share >= 0.5)
        store.save_doc(d, garbled=bad, sample=len(idxs))
        if bad:
            flagged.add(d["doc_id"])
        if i % 250 == 0:
            log.info("garbled scan %d/%d (%d flagged)", i, len(docs), len(flagged))
    log.info("garbled scan done: %d flagged", len(flagged))
    return flagged


def local_paths(doc_ids):
    """Current corporate_documents.local_file_path for these doc ids (the path stored in ar_docs can be stale)."""
    if not doc_ids or not LIVE_DB.exists():
        return {}
    out = {}
    try:
        con = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True, timeout=60)
        try:
            for i in range(0, len(doc_ids), 400):
                chunk = doc_ids[i:i + 400]
                for did, p in con.execute(f"SELECT id, local_file_path FROM corporate_documents WHERE id IN "
                                          f"({','.join('?' * len(chunk))})", chunk):
                    if p:
                        out[did] = p
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("could not read corporate_documents paths: %s", e)
    return out


def resolve_path(doc, live_paths):
    p = doc.get("path")
    if p and Path(p).exists():
        return p
    p = live_paths.get(doc["doc_id"])
    if p and Path(p).exists():
        return p
    return doc.get("path") or live_paths.get(doc["doc_id"])


def _rel_after(path, marker):
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part.lower() == marker:
            return "/".join(parts[i + 1:])
    return None


def drive_rel(path, kind):
    """Remote relative path for an AR/deck PDF, from the local path the DB recorded."""
    marker = "decks" if kind == "decks" else "pdfs"
    rel = _rel_after(path, marker)
    if rel:
        if kind == "decks":
            return f"decks/{rel}"
        if str(path).lower().startswith("d:"):
            return f"D_pdfs/{rel}"
        return f"pdfs/{rel}"
    return None


def fetch_pdf(path, kind, dest_dir, fetch=True):
    """Bring one PDF into the worktree when it is missing locally.  Returns the local path or None.
    Gate mode copies nothing; the bulk launcher calls this for older ARs and deck leftovers only."""
    if path and Path(path).exists():
        return path
    rel = drive_rel(path or "", kind)
    if not rel:
        return None
    dest = Path(dest_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return str(dest)
    if not fetch:
        return None
    src = f"{GDRIVE}/{rel}"
    log.info("fetching %s", src)
    try:
        p = subprocess.run([RCLONE, "copyto", src, str(dest)], capture_output=True, text=True, timeout=900,
                           creationflags=0x08000000 if os.name == "nt" else 0)
    except Exception as e:
        log.warning("fetch failed %s: %s", src, e)
        return None
    if p.returncode != 0 or not dest.exists():
        log.warning("fetch failed %s: %s", src, (p.stderr or p.stdout or "")[-300:])
        return None
    return str(dest)


# ---------------------------------------------------------------- deck leftovers
def load_deck_pages(con, low_text=DECK_LOW_TEXT, min_cov=DECK_MIN_IMG_COV, limit_pages=0):
    """Low-text image-heavy pages the first deck pass skipped and no reader ever saw."""
    q = f"""SELECT p.sha256, p.page_no, p.doc_id, p.isin, p.symbol, p.doc_type, p.known_at, p.text_chars, p.img_cov
            FROM pages p
            WHERE p.status='skipped' AND p.text_chars < ? AND p.img_cov >= ?
              AND NOT EXISTS (SELECT 1 FROM outputs o WHERE o.sha256=p.sha256 AND o.page_no=p.page_no)
            ORDER BY p.known_at DESC, p.sha256, p.page_no"""
    rows = con.execute(q, (low_text, min_cov)).fetchall()
    if limit_pages:
        rows = rows[:limit_pages]
    cols = ("sha256", "page_no", "doc_id", "isin", "symbol", "doc_type", "known_at", "text_chars", "img_cov")
    return [dict(zip(cols, r)) for r in rows]


def deck_paths(rows, live_paths=None):
    """sha256 -> local/drive path from deck_sources, else corporate_documents."""
    out = {}
    shas = sorted({r["sha256"] for r in rows})
    if not shas:
        return out
    try:
        con = sqlite3.connect(f"file:{DECK_DB}?mode=ro", uri=True, timeout=60)
        try:
            for i in range(0, len(shas), 400):
                chunk = shas[i:i + 400]
                for sha, p in con.execute(f"SELECT sha256, local_path FROM deck_sources WHERE sha256 IN "
                                          f"({','.join('?' * len(chunk))})", chunk):
                    if p:
                        out[sha] = p
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("could not read deck_sources: %s", e)
    missing = [r["doc_id"] for r in rows if r["sha256"] not in out and r.get("doc_id")]
    live_paths = live_paths or local_paths(missing)
    for r in rows:
        if r["sha256"] not in out and r.get("doc_id") in live_paths:
            out[r["sha256"]] = live_paths[r["doc_id"]]
    return out


class DeckStore:
    """Writes the leftover pass into the existing deck tables under its own prompt version, plus the
    chart_trends table.  Additive: the first pass's rows are untouched."""

    def __init__(self, path):
        self.path = str(path)
        self.con = sqlite3.connect(self.path, check_same_thread=False, timeout=60)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(deck.SCHEMA + """
CREATE TABLE IF NOT EXISTS chart_trends (sha256 TEXT, page_no INT, symbol TEXT, isin TEXT, known_at TEXT,
  measure TEXT, span TEXT, trend TEXT, model TEXT, PRIMARY KEY (sha256, page_no, measure));
CREATE TABLE IF NOT EXISTS leftover_attempts (sha256 TEXT, page_no INTEGER, attempts INTEGER, ts TEXT,
  PRIMARY KEY (sha256, page_no));
""")
        self.lock = threading.Lock()

    def execute(self, sql, args=()):
        with self.lock:
            self.con.execute(sql, args)
            self.con.commit()

    def query(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).fetchall()

    def done(self):
        return {(r[0], r[1]) for r in self.query("SELECT sha256, page_no FROM pages WHERE prompt_version=? AND status IN "
                                                 "('ok','skipped')", (DECK_LEFTOVER_VERSION,))}

    def failed(self):
        """Pages that failed three times; do not keep re-reading them every pass."""
        return {(r[0], r[1]) for r in self.query("SELECT sha256, page_no FROM leftover_attempts WHERE attempts>=?",
                                                 (MAX_PAGE_ATTEMPTS,))}

    def save(self, task, res):
        now = datetime.now().isoformat(timespec="seconds")
        facts, charts = res.get("facts") or [], res.get("charts") or []
        model = res.get("model") or "unknown"
        with self.lock:
            c = self.con
            r = res.get("reading") or {}
            if r:
                c.execute("INSERT OR REPLACE INTO outputs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (task["sha256"], task["page_no"], DECK_LEFTOVER_VERSION, model,
                           json.dumps(deck.MODELS[model]["body"]), now, r.get("seconds", 0), r.get("in_tok", 0),
                           r.get("out_tok", 0), r.get("usd", 0.0), r.get("output", "")))
            c.execute("DELETE FROM facts WHERE sha256=? AND page_no=? AND prompt_version=?",
                      (task["sha256"], task["page_no"], DECK_LEFTOVER_VERSION))
            c.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          [(task["sha256"], task["page_no"], DECK_LEFTOVER_VERSION, model, i, f["metric"], f["period"],
                            f["raw"], f["value"], f["unit"], 1) for i, f in enumerate(facts)])
            c.executemany("INSERT OR REPLACE INTO chart_trends VALUES (?,?,?,?,?,?,?,?,?)",
                          [(task["sha256"], task["page_no"], task["symbol"], task.get("isin"), task.get("known_at"),
                            ch["measure"], ch["span"], ch["trend"], model) for ch in charts])
            c.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (task["sha256"], task["page_no"], DECK_LEFTOVER_VERSION, task.get("doc_id"), task.get("isin"),
                       task["symbol"], task.get("doc_type"), task.get("known_at"), "vision", task.get("text_chars", 0),
                       0, task.get("img_cov", 0), res.get("recall"), None, model, len(facts), res["status"],
                       res.get("error"), now))
            if res["status"] == "ok":
                c.execute("DELETE FROM leftover_attempts WHERE sha256=? AND page_no=?", (task["sha256"], task["page_no"]))
            else:
                c.execute("INSERT INTO leftover_attempts VALUES (?,?,1,?) ON CONFLICT(sha256,page_no) "
                          "DO UPDATE SET attempts=attempts+1, ts=excluded.ts", (task["sha256"], task["page_no"], now))
            c.commit()


# ---------------------------------------------------------------- queue counts
def queue_counts():
    out = {}
    if AR_DB.exists():
        con = sqlite3.connect(f"file:{AR_DB}?mode=ro", uri=True, timeout=60)
        try:
            for label, cond in (("ar_fy26", AR_FY26_SQL), ("ar_older", AR_OLD_SQL)):
                rows = con.execute(f"""SELECT COUNT(*), COALESCE(SUM(n_pages),0), COALESCE(SUM(n_pages-n_text_pages),0)
                    FROM ar_docs WHERE n_pages>0 AND n_text_pages < 0.5*n_pages AND {cond}""").fetchone()
                out[label] = {"docs": rows[0], "pages": rows[1], "image_only": rows[2]}
            # FY26 mis-encoded scan pool (documents with >=50% text: normally skipped)
            rows = con.execute(f"""SELECT COUNT(*) FROM ar_docs WHERE n_pages>0 AND n_text_pages >= 0.5*n_pages AND {AR_FY26_SQL}""").fetchone()
            out["fy26_text_rich_for_scan"] = rows[0]
        finally:
            con.close()
    if DECK_DB.exists():
        con = sqlite3.connect(f"file:{DECK_DB}?mode=ro", uri=True, timeout=60)
        try:
            out["decks_lowtext"] = con.execute(f"""SELECT COUNT(*) FROM pages p WHERE p.status='skipped'
                AND p.text_chars < ? AND p.img_cov >= ?
                AND NOT EXISTS (SELECT 1 FROM outputs o WHERE o.sha256=p.sha256 AND o.page_no=p.page_no)""",
                (DECK_LOW_TEXT, DECK_MIN_IMG_COV)).fetchone()[0]
            out["decks_looser"] = con.execute(f"""SELECT COUNT(*) FROM pages p WHERE p.status='skipped'
                AND p.text_chars < 200 AND p.img_cov >= 0.15
                AND NOT EXISTS (SELECT 1 FROM outputs o WHERE o.sha256=p.sha256 AND o.page_no=p.page_no)""").fetchone()[0]
        finally:
            con.close()
    return out


# ---------------------------------------------------------------- quality gate
def _digits(s):
    return re.sub(r"[^0-9.]", "", str(s).replace(",", ""))


def _ref_has_number(ref_text, f):
    """True when the fact's digits occur in the page reference text (OCR + text layer), grouping ignored.
    None when the page has no reference text at all (image-only page without OCR)."""
    if not (ref_text or "").strip():
        return None
    raw = (f.get("raw") or "").strip()
    d = _digits(raw).strip(".")
    if not d:
        return None
    flat = re.sub(r"[^0-9.]", "", ref_text.replace(",", ""))
    if d in flat:
        return True
    try:
        v = abs(float(d))
        return any(abs(v - n) < 0.011 for n in deck.text_numbers(ref_text))
    except ValueError:
        return False


STOP = {"the", "and", "for", "with", "from", "total", "other", "year", "years", "per", "net", "amount", "including"}


def _label_supported(metric, ref_text):
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z]{3,}", metric or "")]
    words = [w for w in words if w not in STOP]
    if not words:
        return None
    hay = ref_text.lower()
    return sum(1 for w in words if w in hay) >= 1


def gate(n=30, variant="both", workers=8, out_dir=None, docs_limit=12, doc_ids=None, pdf_dir=None):
    """30 AR image pages x two prompts by the same free reader; values checked against the rendered
    page's OCR text.  Writes a report + PNGs; NEVER writes to ar_facts.db.  ``pdf_dir`` lets the gate
    run on a few PDFs copied into the worktree (``<doc_id>.pdf``) instead of the read-only live tree."""
    os.environ.update({k: v for k, v in user_env().items() if k not in os.environ})
    primaries = register_readers()
    src = sqlite3.connect(f"file:{AR_DB}?mode=ro", uri=True, timeout=60)

    def usable(d):
        if pdf_dir and (Path(pdf_dir) / f"{d['doc_id']}.pdf").exists():
            return True
        return bool(d.get("path") and Path(d["path"]).exists())

    docs = [d for d in load_ar_docs(src, "fy26-all") if usable(d)]
    if doc_ids:
        docs = [d for d in docs if d["doc_id"] in set(doc_ids)]
    if pdf_dir:
        for d in docs:
            p = Path(pdf_dir) / f"{d['doc_id']}.pdf"
            if p.exists():
                d["path"] = str(p)
    if len(docs) < 2 and not doc_ids:
        docs = [d for d in load_ar_docs(src, "all") if usable(d)]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(out_dir) if out_dir else GATE_DIR / stamp
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "answers").mkdir(parents=True, exist_ok=True)
    tasks = []
    per_doc = max(1, (n + max(1, docs_limit) - 1) // max(1, docs_limit))
    for d in docs[:docs_limit]:
        if len(tasks) >= n:
            break
        try:
            pdf = pymupdf.open(d["path"])
        except Exception as e:
            log.warning("gate: unreadable %s: %s", d["path"], e); continue
        added = 0
        try:
            # Spread the gate pages through the report: the first pages are covers/AGM notices, the
            # financial tables sit deeper.  Pick up to `per_doc` evenly spaced image-heavy pages.
            cands = []
            for page in pdf:
                if page.number < 3:
                    continue
                text, g, truth, img_cov = page_kind(page)
                chars = len(text.strip())
                sparse = chars < AR_LOW_TEXT or (len(truth) < 3 and chars < AR_SPARSE_TEXT)
                if img_cov >= MIN_IMG_COV and (g or sparse):
                    cands.append(page.number)
            if per_doc == 1:
                picks = cands[:1]
            elif cands:
                picks = sorted({cands[round(i * (len(cands) - 1) / (per_doc - 1))] for i in range(per_doc)})
            else:
                picks = []
            for pn in picks:
                if len(tasks) >= n:
                    break
                page = pdf[pn]
                text, g, truth, img_cov = page_kind(page)
                chars = len(text.strip())
                ocr = ocr_text(page, OCR_SIDE)
                ref = ocr or ""
                nums = deck.text_numbers(ref)
                # RapidOCR is optional (rapidocr-onnxruntime).  When it is absent, the page is still a
                # valid gate page; the text layer and the two prompts are the reference instead.
                if ocr is not None and len(nums) < GATE_OCR_NUMBERS and not g:
                    continue
                t = {"page_no": pn + 1, "text": text, "text_chars": chars, "truth": truth,
                     "ocr_truth": nums, "img_cov": round(img_cov, 3), "garbled": int(g), "ocr": len(nums),
                     "ocr_available": ocr is not None,
                     "route": "vision", "ref_text": (page.get_text() + "\n" + ref)[:200000]}
                t["png"] = out / "pages" / f"{d['symbol']}_{d['doc_id']}_p{t['page_no']}.png"
                page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0), alpha=False).save(str(t["png"]))
                t["jpeg"] = deck.render_jpeg_b64(page)
                t["doc"] = d
                tasks.append(t); added += 1
        finally:
            pdf.close()
    if not tasks:
        raise SystemExit("gate: no eligible AR image pages found")

    store = Store(out / "gate.db")
    ledger = deck.SpendLedger(store, margin=1.0)
    limiters = {m: deck.AdaptiveLimiter(min(workers, deck.MODELS[m]["ceiling"]), 1, deck.MODELS[m]["ceiling"]) for m in primaries}
    client = CullClient(deck.Client(ledger, limiters), primaries)
    variants = ["a", "b"] if variant == "both" else [variant]
    results = {v: [] for v in variants}
    turns = [0]
    turns_lock = threading.Lock()

    def one(pair):
        t, v = pair
        f = out / "answers" / f"{t['doc']['symbol']}_{t['doc']['doc_id']}_p{t['page_no']}_{v}.json"
        if f.exists():
            return v, t, json.loads(f.read_text(encoding="utf-8"))
        task = {**t["doc"], **{k: t[k] for k in ("page_no", "text", "text_chars", "truth", "img_cov", "garbled", "ocr_truth")}}
        prompt = build_prompt(task, v)
        with turns_lock:
            turn = turns[0]; turns[0] += 1
        try:
            model, r = read_page(client, primaries, task, t["jpeg"], prompt, turn)
            res = {"model": model, "output": r["output"], "seconds": r["seconds"], "in_tok": r["in_tok"],
                   "out_tok": r["out_tok"]}
        except Exception as e:
            res = {"error": str(e)[:300]}
        f.write_text(json.dumps(res), encoding="utf-8")
        return v, t, res

    with ThreadPoolExecutor(max(1, workers)) as ex:
        for v, t, res in ex.map(one, [(t, v) for t in tasks for v in variants]):
            res["page"] = t
            results[v].append(res)

    ocr_ok = any(t.get("ocr_available") for t in tasks)
    report = [f"# AR vision quality gate — {datetime.now().isoformat(timespec='seconds')}", "",
              f"Pages: {len(tasks)} from {len({t['doc']['doc_id'] for t in tasks})} reports; reader: dots-3 free "
              f"({', '.join(primaries)}); variants: {', '.join(variants)}. Values checked against the rendered page's "
              f"RapidOCR text (2200 px) plus its PDF text layer; RapidOCR {'available' if ocr_ok else 'ABSENT — image-only pages have no automated reference'}.", ""]
    summary = []
    values = {}
    for v in variants:
        rows = [r for r in results[v] if "output" in r]
        facts = [(r, f) for r in rows for f in facts_of(r["output"])]
        values[v] = {round(abs(f["value"]), 2) for _, f in facts if f.get("value") is not None}
        vals = [(r, f, _ref_has_number(r["page"]["ref_text"], f)) for r, f in facts]
        checked = [x for x in vals if x[2] is not None]
        good = [x for x in checked if x[2]]
        strict = [x for x in checked if x[2] and _label_supported(x[1]["metric"], x[0]["page"]["ref_text"])]
        ident = deck.identifiable_share([f for _, f in facts])
        secs = sorted(r["seconds"] for r in rows)
        summary.append({"variant": v, "answered": f"{len(rows)}/{len(tasks)}", "facts": len(facts),
                        "values_checked": len(checked), "values_in_page": len(good),
                        "value_precision": (len(good) / len(checked)) if checked else None,
                        "strict_precision": (len(strict) / len(checked)) if checked else None,
                        "identifiable": ident, "median_s": secs[len(secs) // 2] if secs else None})
    for s in summary:
        if len(variants) == 2:
            other = "b" if s["variant"] == "a" else "a"
            mine, theirs = values[s["variant"]], values[other]
            s["cross"] = (len(mine & theirs) / len(mine)) if mine else None
        else:
            s["cross"] = None
    report += ["| prompt | answered | facts | values checked | values on page | value precision | strict precision | identifiable | cross-prompt agreement | median s |",
               "|---|---|---|---|---|---|---|---|---|---|"]
    for s in summary:
        report.append(f"| {s['variant'].upper()} | {s['answered']} | {s['facts']} | {s['values_checked']} | "
                      f"{s['values_in_page']} | {_pct(s['value_precision'])} | {_pct(s['strict_precision'])} | "
                      f"{_pct(s['identifiable'])} | {_pct(s['cross'])} | {s['median_s'] or '-'} |")
    report += ["", "Strict precision = value found in the page AND at least one label word found in the page. "
               "Cross-prompt agreement = share of this prompt's values also read by the other prompt (agreement, not truth). "
               "When RapidOCR is absent, image-only pages have no automated reference; use the PNG sample below.", ""]
    # 10-page sample (first 10 distinct pages), all facts for the better variant
    best = max(variants, key=lambda v: (_pct_num(next(s for s in summary if s["variant"] == v)["strict_precision"]),
                                        _pct_num(next(s for s in summary if s["variant"] == v)["value_precision"])))
    report += [f"## Sample — 10 pages, prompt {best.upper()} (review the PNG beside each row)", ""]
    other = "b" if best == "a" else "a"
    other_values = values.get(other, set())
    by_page = {}
    for r in results[best]:
        if "output" in r:
            key = (r["page"]["doc"]["doc_id"], r["page"]["page_no"])
            by_page.setdefault(key, (r, facts_of(r["output"])))
    sample = [(k, r, f) for k, (r, f) in by_page.items() if len(f) >= 2][:10]
    if not sample:
        sample = [(k, r, f) for k, (r, f) in list(by_page.items())[:10]]
    for key, r, fs in sample:
        t = r["page"]
        report += [f"### {t['doc']['symbol']} doc {t['doc']['doc_id']} page {t['page_no']} — `{t['png'].name}`",
                   f"route: garbled={t['garbled']} text_chars={t['text_chars']} ocr_numbers={t['ocr']} img_cov={t['img_cov']}", ""]
        for f in fs:
            ok = _ref_has_number(t["ref_text"], f)
            lab = _label_supported(f["metric"], t["ref_text"])
            agree = f.get("value") is not None and round(abs(f["value"]), 2) in other_values
            report.append(f"- `{f['raw']}` {f['unit']} | {f['metric'][:70]} | {f['period']} → value "
                          f"{'OK' if ok else 'CHECK'}, label {'OK' if lab else 'CHECK'}, other prompt "
                          f"{'AGREES' if agree else 'differs'}")
        report.append("")
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"gate report: {out / 'report.md'}")
    store.con.close()
    return summary


def _pct(v):
    return "-" if v is None else f"{100 * v:.1f}%"


def _pct_num(v):
    return -1 if v is None else v


# ---------------------------------------------------------------- AR run
PROMPT_VARIANT = "a"


def run_ar(store, client, primaries, scope="fy26", max_pages=0, limit_docs=0, fetch=True, delete_after=False,
           garbled_scan=True, inline=False):
    src = sqlite3.connect(f"file:{AR_DB}?mode=ro", uri=True, timeout=60)
    docs = load_ar_docs(src, scope, limit=limit_docs)
    if scope == "fy26" and garbled_scan:
        flagged = scan_garbled(store, src)
        have = {d["doc_id"] for d in docs}
        docs += [d for d in load_ar_docs(src, "fy26-all") if d["doc_id"] in flagged and d["doc_id"] not in have]
        docs.sort(key=lambda d: str(d.get("known_at") or ""), reverse=True)
    live = local_paths([d["doc_id"] for d in docs if not (d.get("path") and Path(d["path"]).exists())])
    done = store.done_keys()
    done_by_doc = {}
    for did, pg in done:
        done_by_doc.setdefault(did, set()).add(pg)
    if MARKER.exists():   # an inline render died with the process (MuPDF can kill it): one strike
        try:
            key, path = MARKER.read_text(encoding="utf-8").split("\t")[:2]
            store.execute("INSERT INTO bad_docs VALUES (?,?,1,NULL,?) ON CONFLICT(sha256) DO UPDATE SET strikes=strikes+1, ts=excluded.ts",
                          (key, path, datetime.now().isoformat(timespec="seconds")))
        except (ValueError, IndexError):
            pass
        MARKER.unlink(missing_ok=True)
    bad = {r[0] for r in store.query("SELECT sha256 FROM bad_docs WHERE strikes>=?", (deck.MAX_STRIKES,))}
    todo = []
    for d in docs:
        key = d.get("sha256") or f"ar-{d['doc_id']}"
        if key in bad:
            continue
        p = resolve_path(d, live)
        d["path"] = p
        if not p:
            continue
        if not Path(p).exists():
            if not fetch:
                continue
            p = fetch_pdf(p, "ar", DOWNLOAD_DIR / "ar", fetch=True)
            d["path"] = p
            if not p:
                continue
        if d.get("n_pages") and len(done_by_doc.get(d["doc_id"], ())) >= d["n_pages"]:
            continue
        todo.append(d)
    log.info("AR %s: %d reports to open (%d without a local PDF after fetch)", scope, len(todo), len(docs) - len(todo))
    stats = {"pages": 0, "ok": 0, "skipped": 0, "error": 0, "charts": 0, "facts": 0, "docs": 0}
    t0 = time.time()
    last = [t0]
    turns = [0]
    slock = threading.Lock()

    def finish(task, res):
        store.save_page(task, res)
        with slock:
            stats["pages"] += 1
            stats[res["status"]] = stats.get(res["status"], 0) + 1
            stats["facts"] += len(res.get("facts") or ())
            stats["charts"] += len(res.get("charts") or ())
            if time.time() - last[0] > 30:
                last[0] = time.time(); el = time.time() - t0
                log.info("AR %s pages %d (ok %d skipped %d error %d) %d facts %d charts | %.2f pages/s | %.0f pages/h",
                         scope, stats["pages"], stats["ok"], stats["skipped"], stats["error"], stats["facts"],
                         stats["charts"], stats["pages"] / max(1, el), 3600 * stats["pages"] / max(1, el))

    if inline:
        def run_docs():
            for d in todo:
                key = d.get("sha256") or f"ar-{d['doc_id']}"
                MARKER.parent.mkdir(parents=True, exist_ok=True)
                MARKER.write_text(f"{key}\t{d['path']}\n", encoding="utf-8")
                try:
                    n, pages = render_ar_doc(d["path"], done_by_doc.get(d["doc_id"], set()))
                except Exception as e:
                    log.warning("unreadable PDF %s: %s", d["path"], e)
                    store.execute("INSERT INTO bad_docs VALUES (?,?,1,NULL,?) ON CONFLICT(sha256) DO UPDATE SET strikes=strikes+1, ts=excluded.ts",
                                  (key, d["path"], datetime.now().isoformat(timespec="seconds")))
                    MARKER.unlink(missing_ok=True)
                    continue
                MARKER.unlink(missing_ok=True)
                yield d, n, pages
        rendered = run_docs()
        renderer = None
    else:
        renderer = deck.Renderer(store, fn=render_ar_doc)
        rendered = renderer.run(todo, lambda d: done_by_doc.get(d["doc_id"], set()))
    pending = threading.BoundedSemaphore(max(8, sum(deck.MODELS[m]["ceiling"] for m in primaries)))
    stop = [False]
    processed = set()
    try:
        with ThreadPoolExecutor(max(8, sum(deck.MODELS[m]["ceiling"] for m in primaries))) as ex:
            for d, n_pages, pages in rendered:
                store.execute("INSERT OR REPLACE INTO doc_pages VALUES (?,?)", (d.get("sha256") or f"ar-{d['doc_id']}", n_pages))
                stats["docs"] += 1
                processed.add(d["doc_id"])
                for t in pages:
                    if stop[0]:
                        break
                    task = {**d, **{k: v for k, v in t.items() if k != "jpeg"}}
                    if t["route"] != "vision":
                        finish(task, {"status": "skipped", "facts": [], "charts": []})
                        continue
                    with slock:
                        turn = turns[0]; turns[0] += 1
                    pending.acquire()
                    fut = ex.submit(lambda task=task, jpeg=t["jpeg"], turn=turn:
                                    finish(task, process_page(client, primaries, task, jpeg, turn)))
                    fut.add_done_callback(lambda f: (pending.release(), f.exception() and log.error("AR worker: %s", f.exception())))
                    with slock:
                        if max_pages and stats["pages"] >= max_pages:
                            stop[0] = True
                if stop[0]:
                    break
    finally:
        if renderer is not None:
            renderer.close()
        src.close()
    if delete_after and not scope.startswith("fy26"):
        for d in todo:
            if d["doc_id"] in processed and d.get("path") and str(d["path"]).startswith(str(DOWNLOAD_DIR)):
                Path(d["path"]).unlink(missing_ok=True)
    log.info("AR %s pass: %s in %.1f min", scope, stats, (time.time() - t0) / 60)
    return stats


# ---------------------------------------------------------------- deck run
def run_decks(store, client, primaries, max_pages=0, fetch=True, delete_after=True):
    src = sqlite3.connect(f"file:{DECK_DB}?mode=ro", uri=True, timeout=60)
    queue = load_deck_pages(src)
    done = store.done() | store.failed()
    queue = [r for r in queue if (r["sha256"], r["page_no"]) not in done]
    paths = deck_paths(queue)
    by_sha = {}
    for r in queue:
        by_sha.setdefault(r["sha256"], []).append(r)
    log.info("decks: %d low-text pages in %d decks", len(queue), len(by_sha))
    stats = {"pages": 0, "ok": 0, "error": 0, "facts": 0, "charts": 0, "decks": 0}
    t0 = time.time()
    last = [t0]
    turns = [0]
    slock = threading.Lock()

    def finish(task, res):
        store.save(task, res)
        with slock:
            stats["pages"] += 1
            stats[res["status"]] = stats.get(res["status"], 0) + 1
            stats["facts"] += len(res.get("facts") or ())
            stats["charts"] += len(res.get("charts") or ())
            if time.time() - last[0] > 30:
                last[0] = time.time(); el = time.time() - t0
                log.info("decks pages %d (ok %d error %d) %d facts %d charts | %.2f pages/s | %.0f pages/h",
                         stats["pages"], stats["ok"], stats["error"], stats["facts"], stats["charts"],
                         stats["pages"] / max(1, el), 3600 * stats["pages"] / max(1, el))

    with ThreadPoolExecutor(max(8, sum(deck.MODELS[m]["ceiling"] for m in primaries))) as ex:
        for sha, rows in by_sha.items():
            if max_pages and stats["pages"] >= max_pages:
                break
            local = paths.get(sha)
            if not local or not Path(local).exists():
                local = fetch_pdf(local, "decks", DOWNLOAD_DIR / "decks", fetch=fetch)
            if not local:
                continue
            stats["decks"] += 1
            try:
                pdf = pymupdf.open(local)
            except Exception as e:
                log.warning("deck unreadable %s: %s", local, e); continue
            complete = True
            try:
                for r in rows:
                    if max_pages and stats["pages"] >= max_pages:
                        complete = False
                        break
                    try:
                        page = pdf[r["page_no"] - 1]
                    except Exception:
                        continue
                    text, g, truth, img_cov = page_kind(page)
                    if img_cov < MIN_IMG_COV:
                        continue
                    task = {**r, "route": "vision", "text": text, "text_chars": len(text.strip()), "truth": truth,
                            "ocr_truth": set(), "img_cov": round(img_cov, 3), "garbled": int(g)}
                    prompt = deck.build_prompt(task)
                    with slock:
                        turn = turns[0]; turns[0] += 1
                    ex.submit(lambda task=task, jpeg=deck.render_jpeg_b64(page), prompt=prompt, turn=turn:
                              finish(task, process_deck(client, primaries, task, jpeg, prompt, turn)))
            finally:
                pdf.close()
                if complete and delete_after and str(local).startswith(str(DOWNLOAD_DIR)):
                    Path(local).unlink(missing_ok=True)
    src.close()
    log.info("decks pass: %s in %.1f min", stats, (time.time() - t0) / 60)
    return stats


def process_deck(client, primaries, task, jpeg, prompt, turn):
    try:
        model, p = read_page(client, primaries, task, jpeg, prompt, turn)
        facts = facts_of(p["output"])
        truth = set(task.get("truth") or ()) | set(task.get("ocr_truth") or ())
        return {"status": "ok", "model": model, "reading": p, "facts": facts,
                "charts": parse_chart_lines(p["output"]), "recall": deck.recall(deck.fact_numbers(facts), truth)}
    except Exception as e:
        return {"status": "error", "error": str(e)[:400], "facts": [], "charts": []}


# ---------------------------------------------------------------- lock and main
def _pid_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        k32.CloseHandle(h); return True
    return False


def acquire_lock(path):
    """One writer per DB.  A stale lock (dead pid) is taken over; a live lock refuses the run."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            pid = int(path.read_text().strip().split()[0])
            if _pid_alive(pid):
                return False
        except (ValueError, IndexError):
            pass
        path.unlink(missing_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n".encode())
    os.close(fd)
    return True


def release_lock(path):
    Path(path).unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=["ar", "decks", "all"], default="ar")
    ap.add_argument("--scope", choices=["fy26", "older", "all"], default="all", help="AR selection when --target ar")
    ap.add_argument("--db", default=str(AR_DB), help="AR output DB (ar_facts.db; new tables only)")
    ap.add_argument("--deck-db", default=str(DECK_DB), help="deck DB to extend with leftover readings")
    ap.add_argument("--workers", type=int, default=60, help="parallel reader requests across all free readers")
    ap.add_argument("--max-pages", type=int, default=0, help="stop a target after this many pages (0 = all)")
    ap.add_argument("--limit-docs", type=int, default=0)
    ap.add_argument("--no-fetch", action="store_true", help="never call rclone; skip reports/decks not on disk")
    ap.add_argument("--keep-local", action="store_true", help="keep fetched older AR PDFs")
    ap.add_argument("--no-garbled-scan", action="store_true",
                    help="skip the one-time FY26 scan for reports whose text layer is dense but garbage")
    ap.add_argument("--inline-render", action="store_true",
                    help="route/render in this process (no ProcessPoolExecutor; needed under a sandbox that blocks pipes)")
    ap.add_argument("--queue", action="store_true", help="print queue sizes and exit")
    ap.add_argument("--gate", type=int, default=0, metavar="N", help="quality gate on N AR image pages; writes no DB")
    ap.add_argument("--gate-dir")
    ap.add_argument("--gate-pdf-dir", help="directory of <doc_id>.pdf copies for the gate (worktree, not the data tree)")
    ap.add_argument("--gate-docs", default="", help="comma-separated doc_ids to gate on")
    ap.add_argument("--variant", choices=["a", "b", "both"], default="a", help="production prompt variant")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    global PROMPT_VARIANT
    PROMPT_VARIANT = "a" if a.variant == "both" else a.variant

    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
    os.environ.update({k: v for k, v in user_env().items() if k not in os.environ})
    primaries = register_readers()

    if a.queue:
        print(json.dumps(queue_counts(), indent=1))
        return 0
    if a.gate:
        gate(a.gate, "both", workers=min(a.workers, 16), out_dir=a.gate_dir,
             doc_ids=[int(x) for x in a.gate_docs.split(",") if x.strip()], pdf_dir=a.gate_pdf_dir)
        return 0
    if a.dry_run:
        print(json.dumps(queue_counts(), indent=1)); return 0

    lock = DATA / "logs" / "chart_pass.lock"
    if not acquire_lock(lock):
        log.error("another chart pass is running (lock %s); refusing to start a second writer", lock)
        return 2
    try:
        store = Store(a.db)
        ledger = deck.SpendLedger(store, margin=1.0)
        limiters = {}
        for m in primaries:
            ceiling = deck.MODELS[m]["ceiling"]
            limiters[m] = deck.AdaptiveLimiter(min(a.workers, ceiling), 1, ceiling)
        client = CullClient(deck.Client(ledger, limiters), primaries)
        rc = 0
        if a.target in ("ar", "all"):
            scopes = ["fy26", "older"] if a.scope == "all" else [a.scope]
            for scope in scopes:
                st = run_ar(store, client, primaries, scope=scope, max_pages=a.max_pages, limit_docs=a.limit_docs,
                            fetch=not a.no_fetch, delete_after=not a.keep_local, garbled_scan=not a.no_garbled_scan,
                            inline=a.inline_render)
                rc = 3 if st["pages"] or st["ok"] or st["error"] else rc
        if a.target in ("decks", "all"):
            dstore = DeckStore(a.deck_db)
            try:
                st = run_decks(dstore, client, primaries, max_pages=a.max_pages, fetch=not a.no_fetch,
                               delete_after=not a.keep_local)
            finally:
                dstore.con.close()
            rc = 3 if st["pages"] else rc
        return rc
    finally:
        release_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
