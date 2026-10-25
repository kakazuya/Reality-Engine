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
import functools
import json
import logging
import os
import queue
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from reality_engine.config import raw_dir

import pymupdf
import requests
from reality_engine.scripts.go_session import session_id   # stable x-opencode-session (Shivam's rule 2026-10-20)

if __import__("sys").platform == "win32":
    # 2026-10-17: a start of the 213 MB opencode.exe now and then fails with 'not a valid Win32 application'; Windows then
    # opened an 'Unsupported 16-Bit Application' dialog per failure, which piled up on the desktop overnight. These runs
    # are unattended: fail the call (it is retried) instead of raising a dialog. Children inherit this error mode.
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)   # FAILCRITICALERRORS | NOGPFAULTERRORBOX | NOOPENFILEERRORBOX

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


class FallbackFailed(RuntimeError):
    """The primary reader answered (empty) and its fallback reader failed: retry the piece, do not rest the primary."""


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
GO_BENCH_SEC = 3 * 60     # a rate-limited Go reader (quota or too many slots) rests 3 min, then tries again


GOOGLE_PIECES = {"gemini-3.5-flash-lite": 18000, "gemini-3.1-flash-lite": 9000,   # per-model piece size that passed the test
                 "gemma-4-26b-a4b-it": 36000}   # 2026-10-13 exhaustive: 25/25, 10,072 facts, 0.1% not in text, no regrouping
GOOGLE_TPM = {"gemma-4-26b-a4b-it": 13500}
GOOGLE_REAL_TPM = {"gemma-4-26b-a4b-it": 16000, "gemma-4-31b-it": 16000}   # free-tier input tokens/min per key (429 quotaValue)   # Gemma's free tier is 16k tokens/min per key (Flash-Lite: 250k)
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
    """Every GEMINI_API_KEY[_n] that is set, in number order (2026-10-14: 37 keys; Shivam adds more projects over time)."""
    nums = sorted(int(k.rsplit("_", 1)[1]) for k in env if re.fullmatch(r"GEMINI_API_KEY_\d+", k))
    return [v for v in ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in nums] if env.get(v)]


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
    # every OpenCode Go reader of the python worker (LongCat; Cat Jam from 2026-10-14), one per Go subscription key
    for m in P["workers"]["python"]["readers"]:
        prof = M[m]
        if prof["api"] != "opencode-go":
            continue
        tmpl, pv = prompt_for(prof["prompt"])
        for n, var in enumerate(prof.get("go_keys", ["OPENCODE_GO_API_KEY"]), 1):
            if env.get(var):
                # bench_until is required: the 429 bench reads it (2026-10-14 02:25-06:53 it was missing, the bench raised
                # KeyError inside the except block and silently killed every Cat Jam thread at its first 429)
                # protocol 'responses' (2026-10-17): Muse Spark answers only on /responses (chat/completions and /messages
                # give 400 ModelProtocolUnsupported)
                proto = prof.get("protocol", "chat")
                out.append({"name": m + ("" if n == 1 else f"@go{n}"), "kind": "chat", "protocol": proto,
                            "url": "https://opencode.ai/zen/go/v1/" + ("responses" if proto == "responses" else "chat/completions"),
                            "key": env[var],
                            "model": m, "slots": prof["slots"], "pacer": None, "bench_until": 0.0, "tmpl": tmpl, "pv": pv})
    for n, v in enumerate(gemini_keys(env), 1):
        out.append(g_reader("gemma-4-31b-it", n, v))
    return out


def short_name(k):
    """Progress-log label: Gemma 31B keys stay 'g7'; other Google models carry the model ('26b@g7', '3.5fl@g7') so a
    worker's primary and its Gemma 31B fallback on the same key no longer share one label (2026-10-14: the 26B worker's
    log showed ~5 pieces on 28 of 30 keys while the database held ~410 each); Go/Zen readers keep the model."""
    base, _, tail = k.partition("@")
    if tail and not tail.startswith("go"):
        if base.startswith("gemma-4-31b"):
            return tail
        return base.replace("gemini-", "").replace("gemma-4-", "").replace("-flash-lite", "fl").replace("-a4b-it", "") + "@" + tail
    base = base.replace("zen:", "").replace("-preview-free", "").replace("-free", "")
    return f"{base}@{tail}" if tail else base


def google_tag(gm):
    return "" if gm == GOOGLE_PRIMARY else "_" + gm.replace("gemini-", "").replace("-flash-lite", "fl").replace("-a4b-it", "")


def call(r, prompt, http):
    """Returns (text, in_tok, out_tok) or raises RuntimeError with a short reason."""
    t = time.time()
    if r["kind"] == "cli":
        from reality_engine.scripts.ar_queue import opencode_exe, read_piece
        tmp = raw_dir("ar_queue") / "tmp" / f"{uuid.uuid4().hex}.txt"
        tmp.parent.mkdir(parents=True, exist_ok=True); tmp.write_text(prompt, encoding="utf-8")
        try:
            out, rc, err = read_piece(opencode_exe(), r["model"], tmp)
        finally:
            tmp.unlink(missing_ok=True)
        if not parse_lines(out) and out.strip().upper() != "NONE":
            raise RuntimeError(f"rc={rc} {(err or out)[-200:]}")
        return out, None, None
    if r["kind"] == "chat" and r.get("protocol") == "responses":   # OpenAI Responses shape (Muse Spark on Go)
        resp = http.post(r["url"], timeout=900, json={"model": r["model"], "input": prompt, "max_output_tokens": 32000},
                         headers={"Authorization": f"Bearer {r['key']}", "x-opencode-session": session_id("ar_ingest", r["model"], r["key"]),
                                  "User-Agent": "reality-engine-ar-ingest/1.0"})
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        j = resp.json(); u = j.get("usage") or {}
        if j.get("status") != "completed":   # e.g. cut at max_output_tokens: a partial answer is not stored as complete
            raise RuntimeError(f"response {j.get('status')}: {str(j.get('incomplete_details') or j.get('error'))[:150]}")
        text = "".join(c.get("text", "") for o in j.get("output", []) if o.get("type") == "message"
                       for c in o.get("content", []) if c.get("type") == "output_text")
        return text, u.get("input_tokens"), u.get("output_tokens")
    if r["kind"] == "chat":
        resp = http.post(r["url"], timeout=900, json={"model": r["model"], "max_tokens": 32000,
                                                     "messages": [{"role": "user", "content": prompt}]},
                         headers={"Authorization": f"Bearer {r['key']}", "x-opencode-session": session_id("ar_ingest", r["model"], r["key"]),
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
        try:
            text, it, ot = call(fb, prompt, http)
        except Exception as e:
            # 2026-10-15: the fallback (Gemma 31B) is down most hours; its 500/429 were handled as the PRIMARY's error and
            # rested healthy 26B keys (55 of 74 threads asleep; 26B fell from ~900 to ~50 pieces/h from 10-14 13:00)
            raise FallbackFailed(str(e)[:200])
        return text, it, ot, fb
    # answer allowance: exhaustive answers run ~3x longer (2026-10-13: 41 TPM 429s/h on Gemma 31B at the old 1,500)
    r["pacer"].wait(est_tokens(prompt) + (5000 if "Be EXHAUSTIVE" in prompt else 1500))   # est_tokens: Devanagari-aware
    resp = http.post(f"https://generativelanguage.googleapis.com/v1beta/models/{r['model']}:generateContent", timeout=900,
                     headers={"x-goog-api-key": r["key"]},
                     json={"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"maxOutputTokens": 32000, "thinkingConfig": {"thinkingLevel": "minimal"}}})
    if resp.status_code == 429:   # name the exact quota (it sits past the first 200 characters of the body)
        q = re.findall(r'"quotaId": "([^"]+)"', resp.text)
        raise RuntimeError(f"HTTP 429 quota={','.join(q) or '?'}: {resp.text[:120]}")
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


# Some reports' fonts store digits as Coptic letters U+03EC-U+03F5 (0-9), '.' as U+0358 and '-' as U+0372 (2026-10-14:
# PSB FY2019 '54771' is 'ϱϰϳϳϭ' in the text layer). Readers decode them; the check must too, or right numbers read as
# not_found (PSB: 2,470 of 2,646 facts).
FONT_DIGITS = str.maketrans({**{chr(0x3EC + i): str(i) for i in range(10)}, "͘": ".", "Ͳ": "-"})


def value_check(raw, page_text, piece_text):
    d = digits(raw) if raw is not None else ""
    if not d:
        return "prose"
    page_text = (page_text or "").translate(FONT_DIGITS); piece_text = (piece_text or "").translate(FONT_DIGITS)
    if d in digits(page_text or "") or d in re.sub(r"[^\d.]", "", (page_text or "").replace(",", "")):
        return "page"
    if d in re.sub(r"[^\d.]", "", piece_text.replace(",", "")):
        return "piece"
    # shifted-digit fonts: decode, and compare without the decimal point (its glyph is encoded too)
    for where, text in (("page", page_text), ("piece", piece_text)):
        for tr in shifted_digit_maps(text):
            if d.replace(".", "") in re.sub(r"\D", "", text.translate(tr)):
                return where
    return "not_found"


@functools.lru_cache(maxsize=256)
def shifted_digit_maps(text, top=2):
    """Other fonts store 0-9 as ten consecutive code points elsewhere in Unicode: OIL FY2020 writes 31.03.2020 as
    'ŇŅčńŇčņńņń' (0 = U+0144), PPAP FY2024 as control characters (0 = U+0010), often next to normal digits on the same
    page (2026-10-16). Return a translation table for each of the (at most `top`) bases b whose block b..b+9 behaves like digits:
    >= 3 tokens made mostly of block characters, and >= 70% of the block's characters inside such tokens (a block of
    letters fails: its characters sit inside words). Tokens split at whitespace and at control characters outside the
    block (OIL encodes the space as U+0003, PPAP as U+0001)."""
    odd = {ord(ch) for ch in text if ord(ch) > 0x7E or (ord(ch) < 0x20 and ch not in "\n\r\t")}
    if len(odd) < 10:
        return ()
    scored = []
    for b in {o - i for o in odd for i in range(10)}:
        if not (0 < b and b + 9 < 0x20 or b > 0x7E):
            continue
        hi = b + 9
        seps = "".join(chr(x) for x in range(0x20) if not b <= x <= hi and chr(x) not in "\n\r\t")
        toks = [t.strip("()[]-,.;:") for t in re.split(r"[\s" + re.escape(seps) + r"]+", text)]
        n_tok = in_tok = total = 0
        for t in toks:
            nb = sum(b <= ord(ch) <= hi for ch in t)
            if not nb:
                continue
            total += nb
            if nb >= 2 and len(t) - nb <= max(2, nb // 2):
                n_tok += 1; in_tok += nb
        if n_tok >= 3 and in_tok >= 0.7 * total:
            tr = str.maketrans({chr(b + i): str(i) for i in range(10)})
            years = len(re.findall(r"(?<!\d)(?:19[89]\d|20[0-4]\d)(?!\d)", text.translate(tr)))
            scored.append((years, n_tok, b))
    # neighbouring bases share most characters (U+0143, U+0144 and U+0145 all pass for OIL); only the true one decodes the
    # years every report page is full of (2019, 2020), so rank by those, then drop bases overlapping a better one
    kept = []
    for *_, b in sorted(scored, reverse=True):
        if all(abs(b - k) > 9 for k in kept):
            kept.append(b)
    return tuple(str.maketrans({chr(b + i): str(i) for i in range(10)}) for b in kept[:top])


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


def devanagari_share(text):
    letters = [ch for ch in text if ch.isalpha()]
    return sum(1 for ch in letters if "ऀ" <= ch <= "ॿ") / len(letters) if letters else 0.0


def est_tokens(text):
    """Rough Gemma token count: ~3.2 Latin characters per token, ~2 tokens per Devanagari/other non-Latin character
    (2026-10-15 countTokens: a 32k-character bilingual piece = 46-76k tokens)."""
    non_latin = sum(1 for ch in text if ord(ch) > 0x24F)
    return int((len(text) - non_latin) / 3.2 + non_latin * 2)


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
    # 2026-10-15: bilingual reports (PSU banks etc.) repeat the English report in Hindi. Devanagari costs ~2 tokens per
    # character (vs ~0.35 for English), so those pieces broke Gemma's 16k tokens/min limit and only duplicated facts. A
    # mostly-Devanagari page is skipped when the report has at least as many English pages (Hindi-only reports are read).
    hindi = {n for n, t in pages if n not in skipped and devanagari_share(t) >= 0.5}
    if hindi and len(hindi) <= len(pages) - len(hindi):
        skipped = {**skipped, **{n: "hindi" for n in hindi}}
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


def unread_pieces(ps, covered, rows):
    """Resume by page (2026-10-16). ps: this run's split [(p_from, p_to, text)]; covered: pages an ok piece of any
    prompt_version/piece size has read; rows: existing (piece, page_from, page_to) of the report. Returns ([(k, (p_from,
    p_to, text))] still to read, cut down to their unread pages; the set of text pages the split holds). A piece keeps
    its index unless that number already belongs to another page range (then it takes a new one), so a piece number
    always means one page range and INSERT OR REPLACE / the facts DELETE never touch another split's piece."""
    by_range = {(f, t): k for k, f, t in rows}
    used_k = {k for k, _, _ in rows}
    next_k = max(used_k | {len(ps) - 1}) + 1
    left, need = [], set()
    for k, (p_from, p_to, text) in enumerate(ps):
        blocks = [(int(m.group(1)), m.group(0).rstrip("\n")) for m in re.finditer(r"=== PAGE (\d+) ===\n.*?(?=\n=== PAGE |\Z)", text, re.S)]
        need.update(n for n, _ in blocks)
        unread = [(n, b) for n, b in blocks if n not in covered]
        if not unread:
            continue
        if len(unread) < len(blocks):
            p_from, p_to, text = unread[0][0], unread[-1][0], "\n".join(b for _, b in unread) + "\n"
        if (p_from, p_to) in by_range:
            k = by_range[(p_from, p_to)]
        elif k in used_k:
            k = next_k; next_k += 1
        used_k.add(k); by_range[(p_from, p_to)] = k
        left.append((k, (p_from, p_to, text)))
    return left, need


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
    out = p.stdout.decode("utf-8", "replace")
    # 2026-10-15: MuPDF prints warnings such as "MuPDF error: format error: cmsOpenProfileFromMem failed" (a broken colour
    # profile) to STDOUT ahead of the JSON; ~60 good reports were marked unreadable ("Expecting value"). Parse from the JSON.
    start = out.find('{"n_pages"')
    if start < 0:
        raise RuntimeError(f"text split gave no JSON (rc {p.returncode}): {out[:200]!r} {p.stderr.decode('utf-8', 'replace')[-200:]!r}")
    j = json.loads(out[start:])
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
        pymupdf.TOOLS.mupdf_display_errors(False); pymupdf.TOOLS.mupdf_display_warnings(False)   # keep stdout pure JSON
        # 2026-10-14: restarting a worker by killing only its parent orphaned this child mid-way through a malformed PDF
        # (SDC); with the 3-min limit living in the parent, three orphans read the disk at ~1 GB/s for up to 15 h. The
        # child now enforces its own limit and exits as soon as its parent is gone.
        def _guard(parent=os.getppid(), deadline=time.time() + 200):
            import psutil
            while True:
                if time.time() > deadline or not psutil.pid_exists(parent):
                    os._exit(3)
                time.sleep(3)
        threading.Thread(target=_guard, daemon=True).start()
        PIECE_CHARS = a.piece_chars or PIECE_CHARS
        from reality_engine.scripts import ar_yoy
        if a.prev:
            n_pages, n_text, ps, skipped = pieces_of(a.pieces_json, lambda pg: ar_yoy.repeated_pages(pg, a.prev))
        else:
            n_pages, n_text, ps, skipped = pieces_of(a.pieces_json, lambda pg: {})   # still returns the Hindi skips
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
    need = {}        # doc_id -> text pages this run's split must see read
    oversize = set()  # doc_ids with a piece that alone exceeds a Google key's tokens/min: released to the main run when done
    too_big = set()   # main run: (doc_id, piece) a Gemma key refused alone (tokens/min); Gemma readers leave it to the others

    def covered_pages(doc_id):
        """Pages read by an ok piece of any prompt_version or piece size."""
        return {p for f, t in store.q("SELECT page_from, page_to FROM ar_pieces WHERE doc_id=? AND status='ok'", (doc_id,))
                for p in range(f, t + 1)}

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
                # page-based: an error row whose pages another piece has read is no hole (2026-10-16, see main())
                bad = len(need.pop(d["doc_id"], set()) - covered_pages(d["doc_id"]))
                store.x("UPDATE ar_docs SET status=?, ts=? WHERE doc_id=?", ("partial" if bad else "done",
                        datetime.now().isoformat(timespec="seconds"), d["doc_id"]))
                if zen and bad and d["doc_id"] in oversize:   # this route can never read the piece: the main run takes it
                    store.x("DELETE FROM ar_claims WHERE doc_id=?", (d["doc_id"],))
                elif zen:   # done: claim kept for good; partial: renewed so a restart of this route re-reads the failed pieces
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
            if r["kind"] == "gemini" and (d["doc_id"], k) in too_big:   # a Gemma key can never take it: hand it back
                retry.append(item); time.sleep(2); continue
            prompt =r.get("tmpl", PROMPT).format(company=d["company"], symbol=d["symbol"], filed=str(d["filed_at"])[:10], text=text)
            t = time.time()
            try:
                res = call(r, prompt, http)
                out, it, ot = res[:3]
                finish_piece(d, k, p_from, p_to, text, res[3] if len(res) > 3 else r, out, round(time.time() - t, 1), it, ot, None,
                             r.get("pv"))
            except Exception as e:
                msg = str(e)[:300]
                if isinstance(e, FallbackFailed):   # the primary answered (empty); only the fallback failed: no bench
                    if tries < 6:
                        retry.append((d, k, p_from, p_to, text, tries + 1)); continue
                    finish_piece(d, k, p_from, p_to, text, r, "", round(time.time() - t, 1), None, None, msg, r.get("pv"))
                    continue
                if isinstance(e, DailyCap) or (r.get("fallback") and "429" in msg):   # route google: a daily cap rests the key until Google's reset
                    daily = re.search(r"per ?day|PerDay|RequestsPerDay", msg)
                    g = r.get("pacer")
                    recent = [n for t_, n in g.log if time.time() - t_ < 60] if g else []
                    log.info("429 %s %s | pacer last-min est %s tokens, %s requests", r["name"], (re.search(r"quota=(\S+)", msg) or [None, "?"])[1],
                             sum(recent) if g else "-", len(g.log) if g else "-")
                    # 2026-10-17: a piece whose real token count alone tops the per-minute limit (est_tokens undercounts
                    # number-dense pages) was 429'd on every key, handed back uncounted and rested each key 65 s: Gemma 26B
                    # fell ~260 -> ~50 pages/min from 19:00 on 10-16 (4,594 such 429s in 3 h). After 2 refusals while it was
                    # the key's only request that minute, the piece is given up here and its report goes to the main run.
                    if "InputTokensPerModelPerMinute" in msg and len(recent) <= 1:
                        if tries >= 1:
                            with slock:
                                oversize.add(d["doc_id"])
                            log.info("%s piece %s: alone exceeds the key's tokens/min; left to the main run", d["symbol"], k)
                            finish_piece(d, k, p_from, p_to, text, r, "", round(time.time() - t, 1), None, None,
                                         "oversize for Google tokens/min: " + msg[:200], r.get("pv"))
                            continue
                        tries += 1
                    # 2026-10-13: keys still refused after the 12:30 IST reset (quota looks rolling, not a clean PT-midnight
                    # reset), so a daily refusal rests the key 1 h and retries instead of sleeping until PT midnight
                    # 2026-10-17: refusals at 12:28 rested every key to 13:28, an hour of fresh quota lost; a daily rest now
                    # ends 5 min after the next 07:00 UTC (12:30 IST, PDT; from Nov 2 PST it is 08:00 UTC) reset when sooner
                    to_reset = (7 * 3600 - time.time() % 86400) % 86400 + 300
                    r["bench_until"] = time.time() + (min(3600, to_reset) if daily else 65)
                    retry.append((d, k, p_from, p_to, text, tries)); continue
                # 2026-10-14: Go Cat Jam hit an upstream quota (HTTP 429 'Rate limit exceeded', both Go accounts in the same
                # second); with no bench its threads re-took the refused pieces and burnt their 3 tries in minutes (~1,900
                # pieces marked error). Go readers (kind 'chat') now bench like the Zen CLI.
                if r["kind"] in ("cli", "chat") and ("rate limit" in msg.lower() or "HTTP 429" in msg or "free tier can only be used" in msg):
                    # 2026-10-17 06:00: Zen refused every free-tier call ('free tier can only be used from within OpenCode',
                    # server-side; CLI 2.0.32 too): 352 pieces burnt in 15 min. Treated as a quota now: bench, piece uncounted.   # quota, not a bad piece: bench the model and
                    # Zen: one daily allowance, so a long bench. Go: 429s also come from too many slots (LongCat at 192,
                    # 2026-10-14 07:05), where a 20-min bench idled the whole reader; Go benches 3 min and retries.
                    if r["kind"] == "chat":   # Go: an occasional 429 is the per-request rate (2026-10-15: LongCat at 18k pieces
                        # was rested 30 times in 40 min, each idling all 128 threads for 3 min). Only this thread waits ~30 s;
                        # the whole reader rests only when 429s keep coming (a used-up budget such as Cat Jam's daily one).
                        now_ = time.time(); r["r429"] = [x for x in r.get("r429", []) if now_ - x < 60] + [now_]
                        if len(r["r429"]) < 20:
                            retry.append((d, k, p_from, p_to, text, tries)); time.sleep(20 + 20 * random.random()); continue
                    bench = ZEN_BENCH_SEC if r["kind"] == "cli" else GO_BENCH_SEC
                    # Zen and Cat Jam's Go budget reset at 00:00 UTC (05:30 IST, confirmed 2026-10-15): never rest past it
                    # (a 20-min bench from 05:19 idled Zen until 05:39 of its ~1.5 h daily window)
                    to_reset = 86400 - (time.time() % 86400) + 30
                    bench = min(bench, to_reset)
                    if r.get("bench_until", 0) < time.time():             # hand the piece back without counting a try
                        log.warning("%s rate-limited; benched %d min, retries by itself", r["name"], bench // 60)
                    r["bench_until"] = time.time() + bench
                    retry.append((d, k, p_from, p_to, text, tries)); continue
                # 2026-10-14: Google sheds free Gemma load in a daily cycle (31B fine ~04:00-10:00 IST, HTTP 500 on every
                # key most other hours; 26B from 13:00). Retrying every 10 s meant ~1,300 failing calls/min. A Google key
                # that answers 500/503 now rests 2 min and its piece goes back to the queue for any reader.
                # 2026-10-17: from ~19:00 on 10-16 Google refuses a single Gemma request over 16k input tokens (before it
                # took 35-47k); main-run Gemma 31B slept 65 s per refusal (~1,000 -> ~800 pieces/h). Such a piece now goes
                # straight back to the queue, uncounted, for LongCat/Beam, and no Gemma key takes it again.
                if r["kind"] == "gemini" and "InputTokensPerModelPerMinute" in msg and r.get("pacer") \
                        and len([1 for t_, _ in r["pacer"].log if time.time() - t_ < 60]) <= 1:
                    with slock:
                        too_big.add((d["doc_id"], k))
                    retry.append((d, k, p_from, p_to, text, tries)); continue
                if r["kind"] == "gemini" and re.search(r"HTTP 50[03]", msg) and tries < 6:
                    log.info("5xx %s: key rested 2 min", r["name"])   # 2026-10-17: these benches were invisible in the log
                    r["bench_until"] = time.time() + 120
                    retry.append((d, k, p_from, p_to, text, tries + 1)); continue
                transient = re.search(r"HTTP 50[023]|timed out|overloaded|Internal error", msg)   # server-side: try harder
                # 2026-10-17 16:35-16:40: a network blip reset every connection (OpenCode and Google alike); 3 tries 10 s
                # apart burnt 61 pieces. A connection failure is our network: wait it out with 6 tries 60 s apart.
                netdown = re.search(r"Connection aborted|ConnectionResetError|ConnectionError|Max retries exceeded|"
                                    r"NameResolution|getaddrinfo", msg)
                if tries < (6 if transient or netdown else 3):   # another reader (or this one later) takes it
                    time.sleep(65 if "429" in msg or "rate limit" in msg.lower() else 60 if netdown else 10)
                    retry.append((d, k, p_from, p_to, text, tries + 1))
                else:
                    finish_piece(d, k, p_from, p_to, text, r, "", round(time.time() - t, 1), None, None, msg, r.get("pv"))

    def guarded(r):
        """A reader thread must never die silently (2026-10-14: a KeyError in the 429 handler killed every Cat Jam
        thread for 4.5 h with nothing in the log). Log it and restart the loop."""
        while True:
            try:
                return worker(r)
            except Exception:
                log.exception("%s: reader thread crashed; restarting it", r["name"])
                time.sleep(30)

    threads = [threading.Thread(target=guarded, args=(r,), daemon=True) for r in rs for _ in range(r["slots"])]
    for th in threads:
        th.start()

    def reporter():
        while True:
            time.sleep(30)
            with slock:
                el = (time.time() - t0) / 60
                log.info("ar docs %d/%d | pieces %d (errors %d) | pages %d (%.0f/min) | facts %d | by reader %s",
                         stats["docs"], len(todo), stats["pieces"], stats["errors"], stats["pages"], stats["pages"] / max(el, 0.01),
                         stats["facts"], {short_name(k): v for k, v in per.items()})
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
            try:
                n_pages, n_text, ps, skipped = pieces_isolated(d["path"], prev["path"] if prev and not started else None)
            except Exception as e1:
                # 2026-10-15: children killed mid-way (jobs stopped at 22:17) left empty output ('Expecting value') or a
                # cut-off year-over-year list, and 37 good reports were marked unreadable for ever. Retry once without the
                # year-over-year skip; only a second failure (or a timeout: a genuinely malformed PDF) marks it.
                if "timed out" in str(e1):
                    raise
                log.warning("%s: text split failed (%s); retrying without the year-over-year skip", d["symbol"], str(e1)[:300])
                time.sleep(5)
                n_pages, n_text, ps, skipped = pieces_isolated(d["path"], None)
            if skipped:
                store.x("INSERT OR REPLACE INTO ar_skipped_pages VALUES (?,?,?,?,?)",
                        [(d["doc_id"], n, prev["doc_id"] if prev else None, c, datetime.now().isoformat(timespec="seconds")) for n, c in skipped.items()],
                        many=True)
        except Exception as e:
            store.x("INSERT OR REPLACE INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d["doc_id"], d["isin"], d["symbol"], d["company"], d["fiscal_year"], d["fiscal_year_source"], d["filed_at"],
                     d["filed_at_source"], d["sha256"], d["path"], None, None, 0, "unreadable", str(e)[:200], datetime.now().isoformat(timespec="seconds")))
            continue
        # Google's real input limit per key per minute (the pacer's tpm is set lower for headroom; comparing with it
        # released 1,163 ordinary reports in 25 min on 2026-10-15 04:34-05:00)
        tpm = GOOGLE_REAL_TPM.get(rs[0]["model"]) if a.route == "google" else None
        # 2026-10-17: x1.10 because est_tokens undercounts number-dense pages (pieces at est ~15.4k were refused alone)
        if tpm and ps and max(est_tokens(t) * 1.10 + 2000 for _, _, t in ps) > tpm:
            # 2026-10-15: a piece larger than the key's tokens/min limit can never be read here; it bounced between keys
            # for ever (429 hands it back uncounted) and starved Gemma 26B. Release the report to the main run (LongCat).
            store.x("DELETE FROM ar_claims WHERE doc_id=?", (d["doc_id"],))
            log.info("%s: a piece exceeds %s tokens/min; released to the main run", d["symbol"], tpm)
            continue
        # 2026-10-16: resume by page, not by piece index. Resuming by index (`ok = {piece ...}`) let an ok piece of one
        # split (another piece size or prompt_version) hide a failed piece with the same index from another split: 220
        # reports were marked 'done' with 3,005 pages never read. Now a page counts as read when any ok piece covers it,
        # only the unread pages of each piece are sent, and a piece takes a new number unless an existing row has
        # exactly its page range (a number shared by two ranges let INSERT OR REPLACE and the facts DELETE wipe the other).
        left, doc_need = unread_pieces(ps, covered_pages(d["doc_id"]),
                                       store.q("SELECT DISTINCT piece, page_from, page_to FROM ar_pieces WHERE doc_id=?", (d["doc_id"],)))
        store.x("INSERT OR REPLACE INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d["doc_id"], d["isin"], d["symbol"], d["company"], d["fiscal_year"], d["fiscal_year_source"], d["filed_at"],
                 d["filed_at_source"], d["sha256"], d["path"], n_pages, n_text, len(ps),
                 "no_text" if not ps else ("reading" if left else "done"),   # no_text: scanned report, needs OCR later
                 None if ps else "no text layer", datetime.now().isoformat(timespec="seconds")))
        if ps and not left and zen:   # every page already read (e.g. a re-marked report): release the claim for good
            store.x("UPDATE ar_claims SET status='imported', ts=? WHERE doc_id=?", (datetime.now().isoformat(timespec="seconds"), d["doc_id"]))
        with slock:
            remaining[d["doc_id"]] = len(left); need[d["doc_id"]] = doc_need
        for k, (p_from, p_to, text) in left:
            work.put((d, k, p_from, p_to, text, 0))
    while True:   # drain
        with slock:
            if all(v <= 0 for v in remaining.values()):
                break
        time.sleep(10)
    if zen:
        # 2026-10-17: a route that finished its queue exits for good (exit 0 ends its .cmd loop), but it kept 'claimed' on
        # its partial reports, meant for its own restart: 100 reports sat locked from the main run for 1.5 h. Hand them over.
        store.x("DELETE FROM ar_claims WHERE owner=? AND status='claimed'", (owner,))
        log.info("released this route's unfinished claims to the main run")
    log.info("finished: %s", stats)


if __name__ == "__main__":
    main()
