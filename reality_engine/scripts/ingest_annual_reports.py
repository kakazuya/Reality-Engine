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


def readers(env):
    out = []
    if env.get("OPENCODE_GO_API_KEY"):
        out.append({"name": "longcat-2.5-preview-free", "kind": "chat", "url": "https://opencode.ai/zen/go/v1/chat/completions",
                    "key": env["OPENCODE_GO_API_KEY"], "model": "longcat-2.5-preview-free", "slots": 32, "pacer": None})
    for n, var in enumerate(["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 9)], 1):
        if env.get(var):
            out.append({"name": f"gemma-4-31b@g{n}", "kind": "gemini", "key": env[var], "model": "gemma-4-31b-it",
                        "slots": 6, "pacer": TokenPacer(15000)})   # Gemma answers in ~4 min; 6 in flight keeps the token pacer (not latency) the limit
    return out


def call(r, prompt, http):
    """Returns (text, in_tok, out_tok) or raises RuntimeError with a short reason."""
    t = time.time()
    if r["kind"] == "chat":
        resp = http.post(r["url"], timeout=900, json={"model": r["model"], "max_tokens": 32000,
                                                     "messages": [{"role": "user", "content": prompt}]},
                         headers={"Authorization": f"Bearer {r['key']}", "x-opencode-session": str(uuid.uuid4()),
                                  "User-Agent": "reality-engine-ar-ingest/1.0"})
        if resp.status_code != 200 or not resp.json().get("choices"):
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        j = resp.json(); u = j.get("usage", {})
        return j["choices"][0]["message"].get("content") or "", u.get("prompt_tokens"), u.get("completion_tokens")
    r["pacer"].wait(int(len(prompt) / 3.2) + 1500)
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


def pieces_of(path):
    doc = pymupdf.open(path)
    pages = [(i + 1, doc[i].get_text()) for i in range(len(doc))]
    n_pages = len(pages)
    doc.close()
    pages = [(n, t) for n, t in pages if len(t.strip()) >= 40]
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
    return n_pages, len(pages), out


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-docs", type=int, default=0)
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
    env = user_env(); rs = readers(env)
    store = Store()
    docs = inventory(a.limit_docs, [s for s in a.symbols.split(",") if s])
    done_docs = {r[0] for r in store.q("SELECT doc_id FROM ar_docs WHERE status='done'")}
    todo = [d for d in docs if d["doc_id"] not in done_docs]
    log.info("annual reports: %d in scope, %d done, %d to read | readers: %s", len(docs), len(done_docs), len(todo),
             ", ".join(f"{r['name']} x{r['slots']}" for r in rs))
    work = queue.Queue(maxsize=400)
    stats = {"pieces": 0, "pages": 0, "facts": 0, "errors": 0, "docs": 0}
    per = {r["name"]: 0 for r in rs}
    slock = threading.Lock(); t0 = time.time()
    remaining = {}   # doc_id -> pieces left

    def finish_piece(d, k, p_from, p_to, text, r, out, sec, it, ot, err):
        page_text = {int(m.group(1)): m.group(2) for m in re.finditer(r"=== PAGE (\d+) ===\n(.*?)(?=\n=== PAGE |\Z)", text, re.S)}
        facts = parse_lines(out) if out else []
        rows = [(d["doc_id"], k, d["isin"], d["symbol"], d["fiscal_year"], d["filed_at"],
                 int(f["page"]) if str(f.get("page", "")).isdigit() else None, str(f.get("category") or "")[:80],
                 str(f.get("item") or "")[:500], None if f.get("value") is None else str(f["value"])[:60], to_number(f.get("value")),
                 str(f.get("unit") or "")[:40], str(f.get("period") or "")[:40], str(f.get("basis") or "")[:20],
                 str(f.get("quote") or "")[:300], r["name"],
                 value_check(f.get("value"), page_text.get(int(f["page"])) if str(f.get("page", "")).isdigit() else None, text),
                 PROMPT_VERSION) for f in facts]
        store.x("DELETE FROM ar_facts WHERE doc_id=? AND piece=? AND prompt_version=?", (d["doc_id"], k, PROMPT_VERSION))
        if rows:
            store.x("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows, many=True)
        store.x("INSERT OR REPLACE INTO ar_pieces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d["doc_id"], k, PROMPT_VERSION, p_from, p_to, len(text), r["name"], sec, it, ot, len(rows),
                 "error" if err else "ok", err, out, datetime.now().isoformat(timespec="seconds")))
        with slock:
            stats["pieces"] += 1; stats["pages"] += p_to - p_from + 1; stats["facts"] += len(rows); per[r["name"]] += 1
            stats["errors"] += bool(err)
            remaining[d["doc_id"]] -= 1
            if remaining[d["doc_id"]] == 0:
                bad = store.q("SELECT COUNT(*) FROM ar_pieces WHERE doc_id=? AND prompt_version=? AND status!='ok'", (d["doc_id"], PROMPT_VERSION))[0][0]
                store.x("UPDATE ar_docs SET status=?, ts=? WHERE doc_id=?", ("partial" if bad else "done",
                        datetime.now().isoformat(timespec="seconds"), d["doc_id"]))
                stats["docs"] += 1

    def worker(r):
        http = requests.Session()
        while True:
            item = work.get()
            if item is None:
                work.put(None); return
            d, k, p_from, p_to, text, tries = item
            prompt = PROMPT.format(company=d["company"], symbol=d["symbol"], filed=str(d["filed_at"])[:10], text=text)
            t = time.time()
            try:
                out, it, ot = call(r, prompt, http)
                finish_piece(d, k, p_from, p_to, text, r, out, round(time.time() - t, 1), it, ot, None)
            except Exception as e:
                msg = str(e)[:300]
                if tries < 3:   # another reader (or this one later) takes it
                    time.sleep(65 if "429" in msg else 10)
                    work.put((d, k, p_from, p_to, text, tries + 1))
                else:
                    finish_piece(d, k, p_from, p_to, text, r, "", round(time.time() - t, 1), None, None, msg)

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
                         stats["facts"], {k.split("@")[-1] if "@" in k else "longcat": v for k, v in per.items()})
    threading.Thread(target=reporter, daemon=True).start()

    for d in todo:
        try:
            n_pages, n_text, ps = pieces_of(d["path"])
        except Exception as e:
            store.x("INSERT OR REPLACE INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d["doc_id"], d["isin"], d["symbol"], d["company"], d["fiscal_year"], d["fiscal_year_source"], d["filed_at"],
                     d["filed_at_source"], d["sha256"], d["path"], None, None, 0, "unreadable", str(e)[:200], datetime.now().isoformat(timespec="seconds")))
            continue
        ok = {r[0] for r in store.q("SELECT piece FROM ar_pieces WHERE doc_id=? AND prompt_version=? AND status='ok'", (d["doc_id"], PROMPT_VERSION))}
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
