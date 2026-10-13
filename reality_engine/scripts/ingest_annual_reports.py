"""Annual-report fact extraction with the free readers that passed the AR must-find test (tasks/ar_study/free_test):
LongCat 2.5 Preview (OpenCode Go free) and Gemma 4 31B (Google AI Studio, one reader per GEMINI_API_KEY[_n]).

Started 2026-10-12 on Shivam's instruction ("start churning the annual reports through passed models ... keep the labels
attached ... scrip identifiers and date published"). Every page with text is read (no prose filter: quality over
efficiency); the CPU table stage and XBRL ties of tasks/AR_INGESTION_PROTOCOL.md can be layered on later as checks.

Per report (newest filing first): PDF text per page -> pieces of <= PIECE_CHARS cut at page boundaries (Gemma's free tier
is 16k tokens/min per project, so a request must stay small) -> a reader returns JSON lines -> each number is checked
against its cited page (check = page / piece / not_found; nothing is dropped) -> stored in data/ar_facts.db.
Every fact row carries isin, symbol, doc_id, fiscal_year (+ how it was derived), filed_at (point-in-time filing
timestamp, + its source), page, quote and the reader model.

  python -m reality_engine.scripts.ingest_annual_reports [--limit-docs N] [--symbols A,B]
Resumable: finished pieces are never re-read. Log: data/logs/ingest_annual_reports.log (progress every 30 s).
"""
import argparse
import collections
import json
import logging
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pymupdf
import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
LIVE_DB = DATA / "equity_intelligence.db"
OUT_DB = DATA / "ar_facts.db"
LOG = DATA / "logs" / "ingest_annual_reports.log"
PIECE_CHARS = 36000
PROMPT_VERSION = "ar-v1"
log = logging.getLogger("ar_ingest")

PROMPT = """You are reading part of {company}'s annual report (Indian listed company, NSE/BSE symbol {symbol}), filed
{filed}. Pages are marked "=== PAGE n ===" (n = PDF page number).

Extract EVERY fact in this text that an investor database should store and that is NOT just a standard line item of the
main balance sheet or P&L. Include:
- auditor's report: modified opinion, qualification, emphasis of matter, key audit matters (with amounts), audit-trail /
  edit-log remarks; CARO remarks; C&AG comments; secretarial-audit (MR-3) qualifications
- contingent liabilities and claims by type, disputed tax/duty demands, capital commitments, capital advances
- cash flow statement totals (operating, investing, financing) for both years
- order book / contract liabilities / unbilled revenue, receivables and their ageing buckets
- related-party shares (BRSR Section A) and related-party transactions by party, loans/investments in related parties
- subsidiaries / JVs (AOC-1) figures, credit ratings (agency, instrument, rating, change), borrowings maturity
- CSR obligation / spent / unspent / transfers, remuneration ratios, employee counts
- fleet / capacity / asset lists, delayed or disputed contracts, grants or claims reversed or disallowed,
  regulatory or policy changes, any sign of stress
Skip boilerplate (accounting policies, statutory wording, AGM procedure) unless it states a specific fact.

Output ONLY JSON objects, one per line, no other text:
{{"category": "...", "item": "...", "value": "<the number exactly as printed, or null for a prose fact>", "unit": "...",
"period": "...", "basis": "standalone|consolidated|-", "page": <PDF page number>, "quote": "<at most 15 words from the page>"}}
- value: copy the digits exactly as printed (keep Indian grouping like 22,30,000 and the minus sign or brackets); never
  recompute, convert or add up numbers. For a prose fact put null and describe the fact in item.
- unit: as stated on that page or table header (Rs crore, Rs lakh, Rs, %, MT, number, ...). period: FY24, FY23, as on date.
- For signs of stress, related-party leakage, auditor unease or a policy change, also add a line with category "signal".
Do not invent anything; if the text has nothing worth storing, output nothing.

TEXT:
{text}
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS ar_skipped_pages (doc_id INTEGER, page INTEGER, ref_doc_id INTEGER, containment REAL, ts TEXT,
  PRIMARY KEY (doc_id, page));
CREATE TABLE IF NOT EXISTS ar_docs (doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, company TEXT, fiscal_year TEXT,
  fiscal_year_source TEXT, filed_at TEXT, filed_at_source TEXT, sha256 TEXT, path TEXT, n_pages INTEGER, n_text_pages INTEGER,
  n_pieces INTEGER, status TEXT, error TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS ar_pieces (doc_id INTEGER, piece INTEGER, prompt_version TEXT, page_from INTEGER, page_to INTEGER,
  chars INTEGER, model TEXT, seconds REAL, in_tok INTEGER, out_tok INTEGER, n_facts INTEGER, status TEXT, error TEXT,
  raw_output TEXT, ts TEXT, PRIMARY KEY (doc_id, piece, prompt_version));
CREATE TABLE IF NOT EXISTS ar_facts (doc_id INTEGER, piece INTEGER, isin TEXT, symbol TEXT, fiscal_year TEXT, filed_at TEXT,
  page INTEGER, category TEXT, item TEXT, value_raw TEXT, value REAL, unit TEXT, period TEXT, basis TEXT, quote TEXT,
  model TEXT, value_check TEXT, prompt_version TEXT);
CREATE INDEX IF NOT EXISTS ar_facts_isin ON ar_facts(isin, fiscal_year);
CREATE INDEX IF NOT EXISTS ar_facts_doc ON ar_facts(doc_id, piece);
"""


# ---------------------------------------------------------------- environment and readers
def user_env():
    from reality_engine.scripts.resource_watchdog import user_env as ue
    return ue()


class TokenPacer:
    """Keeps a (key, model) under its tokens-per-minute limit, estimated from the prompt length."""

    def __init__(self, tpm):
        self.tpm, self.lock, self.log = tpm, threading.Lock(), []

    def wait(self, tokens):
        while True:
            with self.lock:
                now = time.time(); self.log = [(t, n) for t, n in self.log if now - t < 60]
                if not self.log or sum(n for _, n in self.log) + tokens <= self.tpm:
                    self.log.append((now, tokens)); return
                pause = 60 - (now - self.log[0][0]) + 0.5
            time.sleep(pause)


class DailyCap(RuntimeError):
    """A key/model hit its requests-per-day limit (rpd in reader_profiles.json)."""


class RateGate:
    """Per key and model: requests/min, tokens/min (estimated from the prompt) and requests/day, from reader_profiles.json.
    Waits inside the minute limits; raises DailyCap at the day limit (the caller rests that reader until PT midnight)."""

    def __init__(self, rpm=None, tpm=None, rpd=None):
        self.rpm, self.tpm, self.rpd = rpm, tpm, rpd
        self.lock, self.log, self.day, self.day_n = threading.Lock(), [], None, 0

    def wait(self, tokens):
        while True:
            with self.lock:
                now = time.time(); self.log = [(t, n) for t, n in self.log if now - t < 60]
                day = int((now - 7 * 3600) // 86400)   # Pacific-time day: free-tier daily quotas reset at PT midnight
                if day != self.day:
                    self.day, self.day_n = day, 0
                if self.rpd and self.day_n >= self.rpd:
                    raise DailyCap(f"429 per day: {self.day_n} requests today (rpd {self.rpd})")
                ok_r = not self.rpm or len(self.log) < self.rpm
                ok_t = not self.tpm or not self.log or sum(n for _, n in self.log) + tokens <= self.tpm
                if ok_r and ok_t:
                    self.log.append((now, tokens)); self.day_n += 1; return
                pause = 60 - (now - self.log[0][0]) + 0.5
            time.sleep(pause)


PROFILES = Path(__file__).with_name("reader_profiles.json")   # per-model prompt / piece size / limits / slots (2026-10-13)


def load_profiles():
    return json.loads(PROFILES.read_text(encoding="utf-8"))


def prompt_for(variant):
    """(template, prompt_version) for a profile's prompt variant."""
    if variant == "exhaustive":
        from reality_engine.scripts.ar_queue import EXHAUSTIVE, TEXT_MARK
        return PROMPT.replace(TEXT_MARK, EXHAUSTIVE + TEXT_MARK), "ar-v1x"
    if variant == "exhaustive_core":   # exhaustive + an always-include list of core items (2026-10-13)
        from reality_engine.scripts.ar_queue import CORE, EXHAUSTIVE, TEXT_MARK
        return PROMPT.replace(TEXT_MARK, EXHAUSTIVE + CORE + TEXT_MARK), "ar-v1xc"
    return PROMPT, "ar-v1"


def gate_for(prof):
    return RateGate(prof.get("rpm"), prof.get("tpm"), prof.get("rpd"))


ZEN_MODELS = Path(__file__).with_name("zen_models.json")   # route zen: register of PASSED models {"<zen model id>": {"slots": n, ...}}
ZEN_BENCH_SEC = 20 * 60   # a rate-limited Zen model rests this long, then tries again by itself (no retest, no restart)


GOOGLE_PIECES = {"gemini-3.5-flash-lite": 18000, "gemini-3.1-flash-lite": 9000,   # per-model piece size that passed the test
                 "gemma-4-26b-a4b-it": 36000}   # 2026-10-13 exhaustive: 25/25, 10,072 facts, 0.1% not in text, no regrouping
GOOGLE_TPM = {"gemma-4-26b-a4b-it": 13500}   # Gemma's free tier is 16k tokens/min per key (Flash-Lite: 250k)
GOOGLE_SLOTS = {"gemma-4-26b-a4b-it": 2}
# Google routes use the EXHAUSTIVE instruction (ar_queue.EXHAUSTIVE; 2026-10-13: 3.5 Flash-Lite 5,459 -> 18,352 facts on the
# test pieces, 0.0% not in text; 3.1 Flash-Lite at 9k chars 3,126 -> 7,632, 25/25), stored as prompt version ar-v1x
GOOGLE_PROMPT_VERSION = "ar-v1x"
GOOGLE_PRIMARY = "gemini-3.5-flash-lite"   # route google (2026-10-13): AR test at 18k-char pieces 25/25, 0.1% not in text,
GOOGLE_FALLBACK = "gemma-4-31b-it"           # 5,459 facts, 7 s/piece; but ~14% of pieces come back empty (finish STOP, no
GOOGLE_PIECE_CHARS = 18000                   # text), so an empty answer is re-read at once by Gemma 31B (tagged as Gemma)


def seconds_to_pacific_midnight():
    from datetime import timedelta, timezone
    pt = datetime.now(timezone(timedelta(hours=-7)))   # Pacific daylight time; free-tier daily quotas reset at PT midnight
    return ((pt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) - pt).total_seconds() + 120


def gemini_keys(env):
    return [v for v in ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 31)] if env.get(v)]


def readers(env, route="python", google_model=None):
    """Readers for a worker, built from reader_profiles.json: each carries its prompt template + version, slots and a
    RateGate (rpm/tpm/rpd per key). Google routes: one reader per key for the route's model, with the worker's fallback
    model (same key) re-reading empty answers."""
    P = load_profiles(); M = P["models"]

    def g_reader(model, n, v, with_fallback=None):
        prof = M[model]; tmpl, pv = prompt_for(prof["prompt"])
        short = "gemma-4-31b" if model == "gemma-4-31b-it" else model
        r = {"name": f"{short}@g{n}", "kind": "gemini", "key": env[v], "model": model, "slots": prof["slots"],
             "pacer": gate_for(prof), "bench_until": 0.0, "tmpl": tmpl, "pv": pv}
        if with_fallback:
            fp = dict(M[with_fallback], rpd=None)
            fshort = "gemma-4-31b" if with_fallback == "gemma-4-31b-it" else with_fallback
            r["fallback"] = {"name": f"{fshort}@g{n}", "kind": "gemini", "key": env[v], "model": with_fallback,
                             "pacer": gate_for(fp)}
        return r

    if route == "google":
        gm = google_model or GOOGLE_PRIMARY
        w = P["workers"]["google" + google_tag(gm)]
        return [g_reader(gm, n, v, w.get("fallback")) for n, v in enumerate(gemini_keys(env), 1)]
    if route == "zen":   # OpenCode Zen free models; they answer only inside OpenCode, so each call is an `opencode run`
        cfg = json.loads(ZEN_MODELS.read_text(encoding="utf-8"))
        cfg = {m: (v if isinstance(v, dict) else {"slots": v}) for m, v in cfg.items() if not m.startswith("_")}
        out = []
        for m, v in cfg.items():
            if v.get("slots", 0) <= 0 or v.get("status", "passed") != "passed":
                continue
            prof = M.get(f"{m}@zen", M.get(m, {}))
            tmpl, pv = prompt_for(prof.get("prompt", "plain"))
            out.append({"name": f"zen:{m}", "kind": "cli", "model": m, "slots": v["slots"], "pacer": None,
                        "bench_until": 0.0, "tmpl": tmpl, "pv": pv})
        return out
    out = []
    prof = M["longcat-2.5-preview-free"]; tmpl, pv = prompt_for(prof["prompt"])
    # one LongCat reader per OpenCode Go subscription key listed in the profile (2026-10-13: second Go account)
    for n, var in enumerate(prof.get("go_keys", ["OPENCODE_GO_API_KEY"]), 1):
        if env.get(var):
            out.append({"name": "longcat-2.5-preview-free" + ("" if n == 1 else f"@go{n}"), "kind": "chat",
                        "url": "https://opencode.ai/zen/go/v1/chat/completions", "key": env[var],
                        "model": "longcat-2.5-preview-free", "slots": prof["slots"], "pacer": None, "tmpl": tmpl, "pv": pv})
    for n, v in enumerate(gemini_keys(env), 1):
        out.append(g_reader("gemma-4-31b-it", n, v))
    return out


def google_tag(gm):
    return "" if gm == GOOGLE_PRIMARY else "_" + gm.replace("gemini-", "").replace("-flash-lite", "fl").replace("-a4b-it", "")


def call(r, prompt, http):
    """Returns (text, in_tok, out_tok) or raises RuntimeError with a short reason."""
    t = time.time()
    if r["kind"] == "cli":
        from reality_engine.scripts.ar_queue import opencode_exe, read_piece
        tmp = DATA / "ar_queue" / "tmp" / f"{uuid.uuid4().hex}.txt"
        tmp.parent.mkdir(parents=True, exist_ok=True); tmp.write_text(prompt, encoding="utf-8")
        try:
            out, rc, err = read_piece(opencode_exe(), r["model"], tmp)
        finally:
            tmp.unlink(missing_ok=True)
        if not parse_lines(out) and out.strip().upper() != "NONE":
            raise RuntimeError(f"rc={rc} {(err or out)[-200:]}")
        return out, None, None
    if r["kind"] == "chat":
        resp = http.post(r["url"], timeout=900, json={"model": r["model"], "max_tokens": 32000,
                                                     "messages": [{"role": "user", "content": prompt}]},
                         headers={"Authorization": f"Bearer {r['key']}", "x-opencode-session": str(uuid.uuid4()),
                                  "User-Agent": "reality-engine-ar-ingest/1.0"})
        if resp.status_code != 200 or not resp.json().get("choices"):
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        j = resp.json(); u = j.get("usage", {})
        return j["choices"][0]["message"].get("content") or "", u.get("prompt_tokens"), u.get("completion_tokens")
    if r.get("fallback"):
        text, it, ot = call({k: v for k, v in r.items() if k != "fallback"}, prompt, http)
        if parse_lines(text) or text.strip().upper().startswith("NONE"):
            return text, it, ot
        fb = r["fallback"]   # empty answer: the fallback reads the same piece; facts carry the fallback's name
        text, it, ot = call(fb, prompt, http)
        return text, it, ot, fb
    # answer allowance: exhaustive answers run ~3x longer (2026-10-13: 41 TPM 429s/h on Gemma 31B at the old 1,500)
    r["pacer"].wait(int(len(prompt) / 3.2) + (5000 if "Be EXHAUSTIVE" in prompt else 1500))
    resp = http.post(f"https://generativelanguage.googleapis.com/v1beta/models/{r['model']}:generateContent", timeout=900,
                     headers={"x-goog-api-key": r["key"]},
                     json={"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"maxOutputTokens": 32000, "thinkingConfig": {"thinkingLevel": "minimal"}}})
    if resp.status_code != 200 or not resp.json().get("candidates"):
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    j = resp.json(); u = j.get("usageMetadata", {}); c = j["candidates"][0]
    text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", []) if not p.get("thought"))
    return text, u.get("promptTokenCount"), u.get("candidatesTokenCount")


# ---------------------------------------------------------------- parsing and checks
def parse_lines(text):
    out = []
    for line in text.splitlines():
        line = line.strip().strip(",")
        if line.startswith("```") or not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and (o.get("item") or o.get("value")):
            out.append(o)
    return out


def to_number(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.startswith("−")
    d = re.sub(r"[^\d.]", "", s)
    if not d or d.count(".") > 1:
        return None
    try:
        v = float(d)
    except ValueError:
        return None
    return -v if neg else v


def digits(s):
    return re.sub(r"[^\d.]", "", str(s).replace(",", "")).strip(".")


def value_check(raw, page_text, piece_text):
    d = digits(raw) if raw is not None else ""
    if not d:
        return "prose"
    if d in digits(page_text or "") or d in re.sub(r"[^\d.]", "", (page_text or "").replace(",", "")):
        return "page"
    if d in re.sub(r"[^\d.]", "", piece_text.replace(",", "")):
        return "piece"
    return "not_found"


# ---------------------------------------------------------------- inventory and text
def inventory(limit=0, symbols=None):
    c = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True, timeout=60)
    q = """SELECT d.id, d.isin, d.symbol, d.local_file_path, d.sha256_hash, d.fiscal_period_end, d.doc_date,
             COALESCE(d.bse_dissem_ts, d.publication_date), CASE WHEN d.bse_dissem_ts IS NOT NULL THEN 'bse_feed'
             WHEN d.publication_date IS NOT NULL THEN COALESCE(d.pit_source, 'publication_date') ELSE 'doc_date' END,
             (SELECT m.company_name FROM master_companies m WHERE m.isin = d.isin LIMIT 1)
           FROM corporate_documents d WHERE d.doc_type = 'ANNUAL_REPORT' AND d.local_file_path IS NOT NULL
             AND COALESCE(d.bse_dissem_ts, d.publication_date, d.doc_date) >= '2019-07-01'"""
    args = []
    if symbols:
        q += f" AND d.symbol IN ({','.join('?' * len(symbols))})"; args = symbols
    q += " ORDER BY COALESCE(d.bse_dissem_ts, d.publication_date, d.doc_date) DESC"
    rows = c.execute(q, args).fetchall()
    seen, docs = set(), []
    for i, isin, sym, path, sha, fpe, ddate, filed, fsrc, company in rows:
        key = sha or path
        if key in seen or not Path(path).exists():
            continue
        seen.add(key)
        filed = filed or ddate
        if fpe:
            fy, fys = str(fpe)[:10], "fiscal_period_end"
        else:   # Indian reports are filed after a March year-end: filed Apr-Dec of year y -> FY ending 31 Mar y
            y, m = int(filed[:4]), int(filed[5:7])
            fy, fys = (f"{y}-03-31" if m >= 4 else f"{y - 1}-03-31"), "filing_month_rule"
        docs.append({"doc_id": i, "isin": isin, "symbol": sym, "path": path, "sha256": sha, "fiscal_year": fy,
                     "fiscal_year_source": fys, "filed_at": filed, "filed_at_source": fsrc, "company": company or sym})
        if limit and len(docs) >= limit:
            break
    return docs


def pieces_of(path, skip=None):
    """skip(pages) -> {page_no: ...} of pages to leave out (year-over-year repeats, ar_yoy.py); skipped pages still count
    in n_text_pages."""
    doc = pymupdf.open(path)
    pages = [(i + 1, doc[i].get_text()) for i in range(len(doc))]
    n_pages = len(pages)
    doc.close()
    pages = [(n, t) for n, t in pages if len(t.strip()) >= 40]
    n_text = len(pages)
    skipped = skip(pages) if skip else {}
    pages = [(n, t) for n, t in pages if n not in skipped]
    out, buf, first = [], "", None
    for n, t in pages:
        block = f"=== PAGE {n} ===\n{t}\n"
        if buf and len(buf) + len(block) > PIECE_CHARS:
            out.append((first, last, buf)); buf, first = "", None
        if first is None:
            first = n
        buf += block[:PIECE_CHARS]; last = n
    if buf:
        out.append((first, last, buf))
    return (n_pages, n_text, out, skipped) if skip else (n_pages, n_text, out)


PIECES_TIMEOUT = 180   # seconds for one report's text split (child process)


def pieces_isolated(path, prev_path=None):
    """pieces_of in a child process with a time limit. 2026-10-12 a malformed PDF made PyMuPDF spin for hours inside the
    run, holding the GIL, so every reader stood still (18:00-22:00). Returns pieces_of's tuple (always with `skipped`);
    raises RuntimeError on timeout or failure, so the report is marked unreadable and the run moves on."""
    import subprocess
    import sys
    args = [sys.executable, "-m", "reality_engine.scripts.ingest_annual_reports", "--pieces-json", path,
            "--piece-chars", str(PIECE_CHARS)]
    if prev_path:
        args += ["--prev", prev_path]
    try:
        p = subprocess.run(args, capture_output=True, timeout=PIECES_TIMEOUT, stdin=subprocess.DEVNULL, cwd=ROOT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"text split timed out after {PIECES_TIMEOUT} s (malformed PDF?)")
    if p.returncode != 0:
        raise RuntimeError(f"text split failed: {p.stderr.decode('utf-8', 'replace')[-200:]}")
    j = json.loads(p.stdout.decode("utf-8"))
    return j["n_pages"], j["n_text"], [tuple(x) for x in j["pieces"]], {int(k): v for k, v in j["skipped"].items()}


# ---------------------------------------------------------------- run
class Store:
    def __init__(self):
        self.con = sqlite3.connect(OUT_DB, check_same_thread=False, timeout=60)
        self.con.execute("PRAGMA journal_mode=WAL"); self.con.executescript(SCHEMA)
        self.lock = threading.Lock()

    def q(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).fetchall()

    def x(self, sql, args=(), many=False):
        with self.lock:
            (self.con.executemany if many else self.con.execute)(sql, args); self.con.commit()


def main():
    global LOG, PIECE_CHARS
    ap = argparse.ArgumentParser()
    ap.add_argument("--pieces-json", help=argparse.SUPPRESS)   # child mode for pieces_isolated
    ap.add_argument("--prev", help=argparse.SUPPRESS)
    ap.add_argument("--limit-docs", type=int, default=0)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--route", choices=["python", "zen", "google"], default="python",
                    help="zen: OpenCode Zen free models (zen_models.json), oldest filing first, claims each report in ar_claims")
    ap.add_argument("--google-model", default=GOOGLE_PRIMARY, choices=sorted(GOOGLE_PIECES),
                    help="route google: the Flash-Lite model (each has its own free quota per key)")
    ap.add_argument("--piece-chars", type=int, default=0, help="piece size override (zen route: attached files arrive whole)")
    a = ap.parse_args()
    if a.pieces_json:
        import sys
        PIECE_CHARS = a.piece_chars or PIECE_CHARS
        from reality_engine.scripts import ar_yoy
        if a.prev:
            n_pages, n_text, ps, skipped = pieces_of(a.pieces_json, lambda pg: ar_yoy.repeated_pages(pg, a.prev))
        else:
            (n_pages, n_text, ps), skipped = pieces_of(a.pieces_json), {}
        sys.stdout.buffer.write(json.dumps({"n_pages": n_pages, "n_text": n_text, "pieces": ps, "skipped": skipped}).encode("utf-8"))
        return
    global PROMPT, PROMPT_VERSION
    zen = a.route in ("zen", "google")   # both claim reports and read oldest-first; the Python run skips claimed reports
    gtag = "" if a.google_model == GOOGLE_PRIMARY else "_" + a.google_model.replace("gemini-", "").replace("-flash-lite", "fl").replace("-a4b-it", "")
    owner = f"google-flash{gtag}" if a.route == "google" else "opencode-zen"
    if zen:
        LOG = LOG.with_name(f"ingest_annual_reports_{a.route}{gtag if a.route == 'google' else ''}.log")
    # prompt variant, limits and slots come per reader from reader_profiles.json (readers()); the piece size per worker
    wkey = "google" + google_tag(a.google_model) if a.route == "google" else a.route
    PIECE_CHARS = a.piece_chars or load_profiles()["workers"][wkey]["piece_chars"]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
    env = user_env(); rs = readers(env, a.route, a.google_model)
    store = Store()
    docs = inventory(a.limit_docs, [s for s in a.symbols.split(",") if s])
    if zen:
        docs.reverse()   # oldest first: the Python run works newest-first, so the two meet only at the end
    done_docs = {r[0] for r in store.q("SELECT doc_id FROM ar_docs WHERE status='done'")}
    todo = [d for d in docs if d["doc_id"] not in done_docs]
    log.info("annual reports: %d in scope, %d done, %d to read | readers: %s", len(docs), len(done_docs), len(todo),
             ", ".join(f"{r['name']} x{r['slots']}" for r in rs))
    work = queue.Queue(maxsize=4 * sum(r["slots"] for r in rs) if zen else 400)   # zen claims reports only as it can read them
    # 2026-10-13: workers handing a piece back used work.put() on the bounded queue; when every reader was benched at once
    # (Zen quota out) all threads blocked on a full queue and the worker stood still for hours. Hand-backs go to this
    # unbounded list instead, taken before new work.
    retry = collections.deque()
    stats = {"pieces": 0, "pages": 0, "facts": 0, "errors": 0, "docs": 0}
    per = {r["name"]: 0 for r in rs}
    slock = threading.Lock(); t0 = time.time()
    remaining = {}   # doc_id -> pieces left

    def finish_piece(d, k, p_from, p_to, text, r, out, sec, it, ot, err, pv=None):
        pv = pv or r.get("pv", PROMPT_VERSION)   # the version of the prompt actually sent (fallbacks read the primary's)
        page_text = {int(m.group(1)): m.group(2) for m in re.finditer(r"=== PAGE (\d+) ===\n(.*?)(?=\n=== PAGE |\Z)", text, re.S)}
        facts = parse_lines(out) if out else []
        rows = [(d["doc_id"], k, d["isin"], d["symbol"], d["fiscal_year"], d["filed_at"],
                 int(f["page"]) if str(f.get("page", "")).isdigit() else None, str(f.get("category") or "")[:80],
                 str(f.get("item") or "")[:500], None if f.get("value") is None else str(f["value"])[:60], to_number(f.get("value")),
                 str(f.get("unit") or "")[:40], str(f.get("period") or "")[:40], str(f.get("basis") or "")[:20],
                 str(f.get("quote") or "")[:300], r["name"],
                 value_check(f.get("value"), page_text.get(int(f["page"])) if str(f.get("page", "")).isdigit() else None, text),
                 pv) for f in facts]
        store.x("DELETE FROM ar_facts WHERE doc_id=? AND piece=?", (d["doc_id"], k))   # a re-read replaces any earlier version
        if rows:
            store.x("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows, many=True)
        store.x("INSERT OR REPLACE INTO ar_pieces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d["doc_id"], k, pv, p_from, p_to, len(text), r["name"], sec, it, ot, len(rows),
                 "error" if err else "ok", err, out, datetime.now().isoformat(timespec="seconds")))
        with slock:
            stats["pieces"] += 1; stats["pages"] += p_to - p_from + 1; stats["facts"] += len(rows); per[r["name"]] = per.get(r["name"], 0) + 1
            stats["errors"] += bool(err)
            remaining[d["doc_id"]] -= 1
            if remaining[d["doc_id"]] == 0:
                bad = store.q("SELECT COUNT(*) FROM ar_pieces WHERE doc_id=? AND status!='ok'", (d["doc_id"],))[0][0]
                store.x("UPDATE ar_docs SET status=?, ts=? WHERE doc_id=?", ("partial" if bad else "done",
                        datetime.now().isoformat(timespec="seconds"), d["doc_id"]))
                if zen:   # done: claim kept for good; partial: renewed so a restart of this route re-reads the failed pieces
                    store.x("UPDATE ar_claims SET status=?, ts=? WHERE doc_id=?", ("claimed" if bad else "imported",
                            datetime.now().isoformat(timespec="seconds"), d["doc_id"]))
                stats["docs"] += 1

    def worker(r):
        http = requests.Session()
        while True:
            rest = r.get("bench_until", 0) - time.time()
            if rest > 0:   # rate-limited model: leave the queue to the others until the bench ends
                time.sleep(min(rest, 60)); continue
            try:
                item = retry.popleft()
            except IndexError:
                item = work.get()
            if item is None:
                work.put(None); return
            d, k, p_from, p_to, text, tries = item
            prompt = r.get("tmpl", PROMPT).format(company=d["company"], symbol=d["symbol"], filed=str(d["filed_at"])[:10], text=text)
            t = time.time()
            try:
                res = call(r, prompt, http)
                out, it, ot = res[:3]
                finish_piece(d, k, p_from, p_to, text, res[3] if len(res) > 3 else r, out, round(time.time() - t, 1), it, ot, None,
                             r.get("pv"))
            except Exception as e:
                msg = str(e)[:300]
                if isinstance(e, DailyCap) or (r.get("fallback") and "429" in msg):   # route google: a daily cap rests the key until Google's reset
                    daily = re.search(r"per ?day|PerDay|RequestsPerDay", msg)
                    # 2026-10-13: keys still refused after the 12:30 IST reset (quota looks rolling, not a clean PT-midnight
                    # reset), so a daily refusal rests the key 1 h and retries instead of sleeping until PT midnight
                    r["bench_until"] = time.time() + (3600 if daily else 65)
                    retry.append((d, k, p_from, p_to, text, tries)); continue
                if r["kind"] == "cli" and "rate limit" in msg.lower():   # quota, not a bad piece: bench the model and
                    if r["bench_until"] < time.time():                    # hand the piece back without counting a try
                        log.warning("%s rate-limited; benched %d min, retries by itself", r["name"], ZEN_BENCH_SEC // 60)
                    r["bench_until"] = time.time() + ZEN_BENCH_SEC
                    retry.append((d, k, p_from, p_to, text, tries)); continue
                transient = re.search(r"HTTP 50[023]|timed out|overloaded|Internal error", msg)   # server-side: try harder
                if tries < (6 if transient else 3):   # another reader (or this one later) takes it
                    time.sleep(65 if "429" in msg or "rate limit" in msg.lower() else 10)
                    retry.append((d, k, p_from, p_to, text, tries + 1))
                else:
                    finish_piece(d, k, p_from, p_to, text, r, "", round(time.time() - t, 1), None, None, msg, r.get("pv"))

    threads = [threading.Thread(target=worker, args=(r,), daemon=True) for r in rs for _ in range(r["slots"])]
    for th in threads:
        th.start()

    def reporter():
        while True:
            time.sleep(30)
            with slock:
                el = (time.time() - t0) / 60
                log.info("ar docs %d/%d | pieces %d (errors %d) | pages %d (%.0f/min) | facts %d | by reader %s",
                         stats["docs"], len(todo), stats["pieces"], stats["errors"], stats["pages"], stats["pages"] / max(el, 0.01),
                         stats["facts"], {k.split("@")[-1] if "@" in k else k.replace("zen:", "").replace("-preview-free", "").replace("-free", ""): v for k, v in per.items()})
    threading.Thread(target=reporter, daemon=True).start()

    from reality_engine.scripts.ar_queue import claim_for_zen, claimed_elsewhere
    from reality_engine.scripts import ar_yoy
    yoy_index = ar_yoy.index_inventory(docs)
    for d in todo:
        with store.lock:
            if zen:   # claim it, unless the Python run has started it (or another zen process holds it)
                if not claim_for_zen(store.con, d["doc_id"], f"route-{a.route}", ",".join(r["model"] for r in rs[:1]), owner):
                    continue
            elif claimed_elsewhere(store.con, d["doc_id"]):   # an OpenCode Zen worker holds this report: leave it
                continue
        prev = ar_yoy.previous_report(d, yoy_index)
        started = store.q("SELECT 1 FROM ar_pieces WHERE doc_id=? LIMIT 1", (d["doc_id"],))
        try:
            # pages repeated word for word (numbers included) from last year's report are skipped; a report already
            # part-read keeps its original pieces
            n_pages, n_text, ps, skipped = pieces_isolated(d["path"], prev["path"] if prev and not started else None)
            if skipped:
                store.x("INSERT OR REPLACE INTO ar_skipped_pages VALUES (?,?,?,?,?)",
                        [(d["doc_id"], n, prev["doc_id"], c, datetime.now().isoformat(timespec="seconds")) for n, c in skipped.items()],
                        many=True)
        except Exception as e:
            store.x("INSERT OR REPLACE INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d["doc_id"], d["isin"], d["symbol"], d["company"], d["fiscal_year"], d["fiscal_year_source"], d["filed_at"],
                     d["filed_at_source"], d["sha256"], d["path"], None, None, 0, "unreadable", str(e)[:200], datetime.now().isoformat(timespec="seconds")))
            continue
        ok = {r[0] for r in store.q("SELECT piece FROM ar_pieces WHERE doc_id=? AND status='ok'", (d["doc_id"],))}
        store.x("INSERT OR REPLACE INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d["doc_id"], d["isin"], d["symbol"], d["company"], d["fiscal_year"], d["fiscal_year_source"], d["filed_at"],
                 d["filed_at_source"], d["sha256"], d["path"], n_pages, n_text, len(ps),
                 "no_text" if not ps else ("reading" if len(ok) < len(ps) else "done"),   # no_text: scanned report, needs OCR later
                 None if ps else "no text layer", datetime.now().isoformat(timespec="seconds")))
        left = [(k, p) for k, p in enumerate(ps) if k not in ok]
        with slock:
            remaining[d["doc_id"]] = len(left)
        for k, (p_from, p_to, text) in left:
            work.put((d, k, p_from, p_to, text, 0))
    while True:   # drain
        with slock:
            if all(v <= 0 for v in remaining.values()):
                break
        time.sleep(10)
    log.info("finished: %s", stats)


if __name__ == "__main__":
    main()
