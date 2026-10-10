"""
Extract the figures printed on investor-presentation slides with OpenCode Go vision models.

Pipeline (one pass per PDF page):
  1. Route locally with PyMuPDF: pages with no numbers in the text layer and little image area (dividers,
     disclaimers) are skipped; every other page is rendered (JPEG, longest side 1600 px) and sent to the model.
  2. Primary reader (default LongCat 2.5 Preview, free and uncapped while the promotion lasts; --primary to change;
     earlier default Muse Spark 1.3 Contributor at minimal reasoning). The prompt carries the company, filing
     date and Indian fiscal-year convention, strict rules for label/period/unit, and the page's PDF text layer
     (to confirm digits; the image gives structure). Quality test 2026-10-09 on 40 pilot pages: 93.5% of figures
     identifiable (unique label+period+unit on the page) vs 64.9% for the first design (MiMo, image only), and
     zero junk rows (slide numbers, addresses) vs 50. Values matched the text layer equally well (no misreads).
  3. Second reader (default Step 5 Preview, free; a capped second reader such as Muse is skipped, not waited for,
     once its spend cap is reached), same prompt, only where
     the primary looks weak
     (recall vs the text layer < 0.4 on a page with 10+ numbers, under 70% of figures identifiable, or no figures on a page that clearly has
     numbers or large images). The better reading is marked final: higher text-layer recall, ties broken by
     identifiability.
  4. Every request is logged with model, settings, prompt version, run time, tokens and estimated cost.

Throughput and limits (measured 2026-10-09): no throttling up to 120 parallel requests; queueing at 200;
upstream "Rate limit exceeded" (HTTP 429) at 300. The API sends no rate-limit headers, so an adaptive limiter
starts at --workers, cuts to 60% on any 429 and creeps back up after clean runs. A spend ledger enforces the
OpenCode Go per-model dollar caps ($12 per 5 h, $30 per week, $60 per month; rolling windows, x --cap-margin)
and pauses until the window frees. Spend from other OpenCode Go clients on the same key is not visible here,
so keep the margin below 1.

Inputs are read-only: documents come from ``corporate_documents`` in the live DB (opened with mode=ro).
Output: ``reality_engine/data/deck_figures.db`` (own SQLite file, so the annual-report drain is never locked).
Idempotent: a (sha256, page, prompt version) already finished is skipped, so reruns resume.

Public filings only: Muse Spark Contributor traffic is used by Meta for model training (OpenCode docs).
Needs OPENCODE_GO_API_KEY in the environment.

Usage:
    python -m reality_engine.scripts.extract_deck_figures --dry-run
    python -m reality_engine.scripts.extract_deck_figures --limit-docs 20
    python -m reality_engine.scripts.extract_deck_figures --symbols TITAGARH,HAL --workers 60
"""

import argparse
import hashlib
import itertools
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timedelta
from pathlib import Path

import pymupdf
import requests

DATA = Path(__file__).resolve().parents[1] / "data"
LIVE_DB = DATA / "equity_intelligence.db"
OUT_DB = DATA / "deck_figures.db"
LOG = DATA / "logs" / "extract_deck_figures.log"
MARKER = DATA / "logs" / "extract_deck_figures.current"   # PDF being rendered; left behind if MuPDF crashes the process
MAX_STRIKES = 2
BASE = "https://opencode.ai/zen/go/v1"

PROMPT = ("List every number on this investor-presentation slide, one per line, in this exact format:\n"
          "metric | period | number | unit\n"
          "Copy each number EXACTLY as printed, character for character, including commas, brackets, decimal points and % "
          "(e.g. 28,00,000 or (1.44) or 18.2%). Do not convert or round. Use - for an unknown period or unit. "
          "First line must be: TITLE | <slide title>. If there are no numbers, output only the TITLE line.")
RULES = ("Rules for each line:\n"
         "- metric: the specific label from the slide (row/column/axis/legend/caption text, including the segment or product it belongs to). "
         "Never write the word 'metric'.\n"
         "- period: the period the number refers to, as printed in the column/axis header or caption (e.g. Q1FY27, FY26, 9MFY26, Jun-26). "
         "Use - only if the slide gives no period for it.\n"
         "- unit: the unit printed next to the number or in the table/chart header (e.g. Rs Cr, %, MT, homes, sft). Use - only if none is printed.\n"
         "- Skip page numbers, footnote markers, phone numbers, addresses and registration numbers.")
TEXT_LAYER_CHARS = 6000
# Readers available on OpenCode Go. price = $ per 1M tokens (input, output) from the Go docs (2026-10-09); capped = counts
# against the Go plan's per-model dollar caps; ceiling = parallel requests before the provider throttles (measured
# 2026-10-09: MiMo none up to 120; LongCat first 429 at 40; Muse throttled from ~30). Quality on the 40-page test
# (share of figures identifiable / unit filled): Step 96.3% / 94.0%, Muse 93.5% / 80.5%, LongCat 85.2% / 90.6%,
# MiMo 82.7% / 80.0%. No reader misread a number that was in the text layer.
# Free models change over time: check https://opencode.ai/v2/docs/console/go and re-run the quality test first.
MODELS = {
    "muse-spark-1.3-contributor": {"api": "responses", "price": (0.10, 0.20), "capped": True, "ceiling": 40,
                                   "body": {"max_output_tokens": 8000, "reasoning": {"effort": "minimal"}}},
    "mimo-v2.6-flash": {"api": "chat", "price": (0.14, 0.28), "capped": True, "ceiling": 120,
                        "body": {"temperature": 0, "max_tokens": 4000, "thinking": {"type": "disabled"}}},
    "longcat-2.5-preview-free": {"api": "chat", "price": (0.0, 0.0), "capped": False, "ceiling": 35,
                                 "body": {"temperature": 0, "max_tokens": 8000, "thinking": {"type": "disabled"}}},
    # best labels on the 40-page test (96.3% identifiable, units 94%) but reasoning cannot be switched off:
    # median 54 s, worst 337 s, 1 of 40 empty. Slow, so it needs many requests in flight; ceiling not measured, the
    # adaptive limiter backs off on 429.
    "step-5-preview-free": {"api": "chat", "price": (0.0, 0.0), "capped": False, "ceiling": 60,
                            "body": {"max_tokens": 32000, "reasoning_effort": "low"}},
    # Local GPU (RX 6700 XT) via llama.cpp: start C:\Users\warri\llama-rocm-gfx103X\llama-server.exe with the Ornith
    # GGUF + mmproj, --port 8091 -np 4 -c 65536 --reasoning off --image-min-tokens 1024. 40-page test 2026-10-09:
    # 85.6% identifiable, units 85.6%, no misreads, 7 junk rows, 23 s per page with 4 in parallel (~0.11 pages/s).
    "ornith-1.5-9b": {"api": "chat", "base": "http://127.0.0.1:8091/v1", "price": (0.0, 0.0), "capped": False, "ceiling": 4,
                      "body": {"max_tokens": 4000, "repeat_penalty": 1.1}},
    # Kilo gateway (free, own rate limit, KILO_API_KEY). 40-page test 2026-10-09: 90.4% identifiable, units 68.6%,
    # no misreads, ~11 s median; 1 of 40 calls returned a provider error. Prompts may be used for training (public filings).
    "dots-studio/dots-3-note-preview:free": {"api": "chat", "base": "https://api.kilo.ai/api/gateway", "key_env": "KILO_API_KEY",
                                             "price": (0.0, 0.0), "capped": False, "ceiling": 30,
                                             "body": {"temperature": 0, "max_tokens": 8000, "reasoning": {"enabled": False}}},
    # Same Dots model on a second Kilo account (KILO_API_KEY_2), own adaptive limiter. Probe 2026-10-10: the throttle is
    # shared across both keys (extra load on key 2 also drew 429s on key 1): clean at 60 in flight in total, 16% 429 at
    # 80, 46% at 100. Hence 30 per key.
    # "id" is the model name sent to the gateway; the entry name (with @kilo2) is what outputs and logs record.
    "dots-studio/dots-3-note-preview:free@kilo2": {"api": "chat", "id": "dots-studio/dots-3-note-preview:free",
                                                   "base": "https://api.kilo.ai/api/gateway", "key_env": "KILO_API_KEY_2",
                                                   "price": (0.0, 0.0), "capped": False, "ceiling": 30,
                                                   "body": {"temperature": 0, "max_tokens": 8000, "reasoning": {"enabled": False}}},
    # Step 5 Preview (free) through Kilo: same model as the OpenCode second reader, so its quality is known; Kilo answered
    # 14/40 on 2026-10-10 (median 41 s; 94.9% identifiable, 98.8% of Haiku's numbers, no unsupported numbers), the rest
    # refused by StepFun's own shared cap ("TPM limit 250,000,000"), which every gateway's free Step traffic hits.
    "stepfun/step-5-preview-free@kilo": {"api": "chat", "id": "stepfun/step-5-preview-free", "base": "https://api.kilo.ai/api/gateway",
                                         "key_env": "KILO_API_KEY", "price": (0.0, 0.0), "capped": False, "ceiling": 10,
                                         "body": {"max_tokens": 32000, "reasoning": {"effort": "low"}}},
    # Claude Haiku 5.5, run as Claude Code helper agents through scripts/claude_page_queue.py (export -> agents ->
    # import), not called from this process. Best reader on the 40-page test: 100% identifiable, units 90.8%, no misreads.
    "claude-haiku-5-5": {"api": "agent", "price": (0.0, 0.0), "capped": False, "ceiling": 0,
                         "body": {"via": "Claude Code subagent, scripts/claude_page_queue.py"}},
}
CLAIM_HOURS = 24   # pages exported to the Claude queue are left to it this long before the extractor takes them back
PRIMARY, SECOND = "longcat-2.5-preview-free", "step-5-preview-free"   # overridable with --primary / --second
# Paid overflow readers are off by default. The OpenCode Go limits are one budget for the whole account (rolling 5 h,
# weekly, monthly; console screenshot 2026-10-09), not per model, and the same budget serves Shivam's own coding: the
# first full run used 99% of the weekly and 93% of the monthly allowance. Opt in per run with --also-primary/--also-second.
# Ornith (local GPU) was dropped 2026-10-09: ~0.11 pages/s for 85.6% identifiable, and the GPU is kept for the RapidOCR
# page gate. Add mimo-v2.6-flash etc. to spend plan budget.
ALSO_PRIMARY = ["dots-studio/dots-3-note-preview:free"]
if os.environ.get("KILO_API_KEY_2"):   # second Kilo account joins the primaries only when its key is set
    ALSO_PRIMARY.append("dots-studio/dots-3-note-preview:free@kilo2")
ALSO_SECOND = ["stepfun/step-5-preview-free@kilo"]   # takes second readings whenever the OpenCode Step reader is at its limit
# Kilo routes free models through its own OpenRouter account: every Kilo key shares one quota per model (a 1,000/day cap on
# Inkling Small was already used up on 2026-10-10 for both keys), so extra Kilo accounts add no free-model capacity.
RENDER_PROCS, RENDER_AHEAD, RENDER_TIMEOUT = 2, 4, 900
# Second readings run in their own pool from the persistent second_queue table, so a slow or throttled second reader
# no longer holds primary workers (2026-10-09: Step throttled to 10 in flight left ~90 of 110 workers waiting on it and
# cut the run to 0.5 pages/s). Above SECOND_QUEUE_MAX waiting pages (~150 KB JPEG each) workers wait inline again.
# 2026-10-10: Step answered every call with an upstream HTTP 429 for over an hour; at the old 5,000 cap workers waited
# inline again and the run fell to 0.5 pages/s. Cap raised to 100,000 (~15 GB) and a 429 pauses second readings
# (pages stay queued, no try is spent) instead of burning their retries.
SECOND_QUEUE_MAX = 100_000
SECOND_PAUSE_429 = 300
# 2026-10-10: Step's queue reached ~20,800 pages while it cleared ~1,000 a night. New pages no longer join the queue
# (the pool keeps draining it); a page that wanted a second reading keeps its primary one and is marked with this
# error text (status stays 'ok') so a later pass can find it. --enqueue-second turns queueing back on.
SECOND_DEFERRED = "second reading deferred (queue paused)"
SECOND_TRIES = 3   # a queued page whose second reading keeps failing keeps its primary reading after this many tries
BENCH_402_SEC = 30 * 60
CAPS = {5 * 3600: 12.0, 7 * 86400: 30.0, 30 * 86400: 60.0}   # rolling window (s) -> $ cap, per capped model
# The version identifies what was asked and how the page was rendered, not which model answered (outputs store the
# model), so switching readers does not re-read pages that are already done.
PROMPT_VERSION = hashlib.sha1(json.dumps([PROMPT, RULES, TEXT_LAYER_CHARS, 1600, 85]).encode()).hexdigest()[:10]
LEGACY_VERSIONS = ["a062f038d8"]   # same prompt and rendering, version hash used to include the model names
MAX_SIDE, JPEG_Q = 1600, 85
SECOND_READER_RECALL = 0.4
SECOND_READER_IDENTIFIABLE = 0.7

log = logging.getLogger("deck_figures")


# ---------------------------------------------------------------- parsing (same rules as the bake-off scorer)
NUM = re.compile(r"^[~≈+]?(?:₹|Rs\.?|INR)?\s*\(?[-+]?\d[\d,]*\.?\d*\)?\+?\s*%?(\s*[A-Za-z][A-Za-z .()/]*)?$")
PERIOD_LIKE = re.compile(r"^(FY|Q[1-4]|H[12]|[1-4]QFY|9MFY)", re.I)


def keep(v):
    """Drop numbers that carry no information for scoring: < 1 and bare years."""
    return v is not None and v >= 1 and not (1900 <= v <= 2100 and float(v).is_integer())


def parse_number(s):
    """'28,00,000' -> 2800000.0; '(1.44)' -> -1.44; 'Rs 18.2%' -> 18.2. Commas are dropped, so lakh grouping
    cannot shift the magnitude. A single comma followed by 1-2 digits and no dot ('9,7', '-7,95') is a decimal comma:
    no thousands or lakh grouping ends in fewer than 3 digits."""
    s = re.sub(r"^(₹|Rs\.?|INR)\s*", "", s.strip().lstrip("~≈+"))
    m = re.search(r"-?\d[\d,]*\.?\d*", s)
    if not m:
        return None
    tok = m.group(0).rstrip(",")
    if re.fullmatch(r"-?\d+,\d{1,2}", tok):
        tok = tok.replace(",", ".")
    v = float(tok.replace(",", "").rstrip(".") or "nan")
    return -abs(v) if s.startswith("(") and s.rstrip("%").endswith(")") else v


def parse_facts(output):
    """Model output -> list of facts (metric, period, raw_number, value, unit). TITLE/header lines are dropped."""
    facts = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split("|")]
        # skip the title and the echoed template header; MiMo sometimes also uses the word "metric" as a literal
        # label on real fact lines (1.4% of lines in the 2026-10-09 pilot), so match the header on the number slot
        if len(parts) < 3 or parts[0].upper() == "TITLE" or parts[2].lower() == "number":
            continue
        raw = parts[2]
        if not NUM.match(raw) or PERIOD_LIKE.match(raw):
            cand = [p for p in parts if NUM.match(p) and not PERIOD_LIKE.match(p)]
            if not cand:
                continue
            raw = cand[0]
        unit = parts[3] if len(parts) > 3 else "-"
        facts.append({"metric": parts[0], "period": parts[1], "raw": raw, "value": parse_number(raw),
                      "unit": currency_scale_unit(parts[0], raw, unit) or unit})
    return facts


# Readers often write a bare currency unit ("Rs", "₹", "INR") when the scale is printed elsewhere: as a suffix on the
# number ("7,571MM"), in the label ("Capex (Mn)") or in a table/chart header ("Rs. in Lacs"). 2026-10-10: ~67k final
# facts had a bare currency unit; checked samples show most are genuine rupee amounts (prices, ADR, ticket size), so
# a scale is only added when one is printed in the number, the label or (page-level) the page's text layer.
BARE_CURRENCY = re.compile(r"^\s*(rs\.?|₹|inr|rupees?)\s*$", re.I)
SCALE_WORDS = [("lakh", r"lakhs?|lacs?|lkh"), ("crore", r"crores?|crs?"), ("million", r"mn|mm|million|mio"),
               ("billion", r"bn|billion"), ("thousand", r"thousands?|'000|000s")]
SCALE_NAME = {"lakh": "Rs Lakh", "crore": "Rs Cr", "million": "Rs Mn", "billion": "Rs Bn", "thousand": "Rs '000"}
PER_UNIT = re.compile(r"eps|per share|dividend|price|cmp|nav\b|book value|mrp|asp\b|arp|adr\b|average daily rate|ticket|"
                      r"realis|realiz|per |/|rate\b|fare|rent", re.I)


def _scale_in(text, where):
    """Scales named in `text`: where='number' a suffix on a digit; 'label' also 'in Mn' / '(Mn)'; 'page' only a scale
    tied to a currency word ('Rs. in Lacs', '₹ Cr', 'INR Mn') or a bracketed '(Cr)', so 'in million tonnes' is ignored."""
    found = set()
    for name, pat in SCALE_WORDS:
        cur = rf"(?:rs\.?|₹|inr|rupees?)\s*(?:in\s*)?(?:{pat})\b|\((?:{pat})\.?\)"
        rx = {"number": rf"\d\s*(?:{pat})\b", "label": rf"{cur}|\bin\s*(?:{pat})\b", "page": cur}[where]
        if re.search(rx, text, re.I):
            found.add(name)
    return found


NOT_MONEY = re.compile(r"shares|o/s|volume|lakh\s*crore|units|nos\b", re.I)


def currency_scale_unit(metric, raw, unit, page_text=None):
    """A unit with the scale for a fact whose unit is a bare currency, or None: the number's own suffix ('7,571MM')
    wins, then the label ('Capex (Mn)'). A scale found only in the page text is NOT used: tried 2026-10-10 on 6.3k
    facts, a spot check showed EPS, face value and per-unit prices wrongly scaled. `page_text` is kept for the call
    signature only. Share counts, volumes and 'lakh crore' amounts are left alone."""
    if not BARE_CURRENCY.match(unit or "") or NOT_MONEY.search(f"{metric} {raw}"):
        return None
    for found in (_scale_in(raw or "", "number"), _scale_in(metric or "", "label")):
        if len(found) == 1:
            return SCALE_NAME[found.pop()]
    return None


def fact_numbers(facts):
    return {round(abs(f["value"]), 2) for f in facts if f["value"] is not None and keep(round(abs(f["value"]), 2))}


def text_numbers(text):
    """Numbers in the PDF text layer, normalised the same way (the recall reference for text-layer pages)."""
    out = set()
    # digits glued to letters are labels (1QFY26, Q1, 63A, A51119), not values; dd.mm.yyyy / yyyy.mm.dd are dates
    text = re.sub(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b", " ", text)
    for tok in re.findall(r"(?<![A-Za-z\d.])\(?\d[\d,]*\.?\d*\)?%?(?![A-Za-z\d])", text):
        try:
            v = round(abs(float(tok.replace(",", "").replace("%", "").strip("()").rstrip("."))), 2)
        except ValueError:
            continue
        if keep(v):
            out.add(v)
    return out


def recall(found, truth):
    return None if not truth else len(found & truth) / len(truth)


def identifiable_share(facts):
    """Share of figures that can be told apart on the page: a specific label and a (label, period, unit) key no
    other figure on the page shares. A figure that collapses into its section header cannot be used downstream."""
    if not facts:
        return None
    keys = [(f["metric"].strip().lower(), f["period"].strip().lower(), f["unit"].strip().lower()) for f in facts]
    counts = {k: keys.count(k) for k in set(keys)}
    return sum(1 for k in keys if k[0] not in ("", "-", "metric") and counts[k] == 1) / len(keys)


def build_prompt(task):
    """Context + extraction rules + the page's PDF text layer (when present)."""
    ctx = (f"Company: {task.get('company') or task['symbol']} (NSE/BSE symbol {task['symbol']}), an Indian listed company. "
           f"Document: investor presentation filed {str(task.get('known_at') or '')[:10]}. "
           "Indian fiscal year runs April-March (Q1 = Apr-Jun).")
    p = ctx + "\n" + PROMPT + "\n" + RULES
    if task.get("text", "").strip():
        p += ("\n\nText extracted from this page's PDF text layer (order may be jumbled; use it to confirm exact digits, "
              "use the image for which label, period and unit each number belongs to):\n<<<\n" + task["text"][:TEXT_LAYER_CHARS] + "\n>>>")
    return p


# ---------------------------------------------------------------- spend caps and adaptive concurrency
class CapReached(Exception):
    pass


class SpendLedger:
    """Rolling-window dollar caps per model, persisted in the output DB so they survive restarts.
    In-flight requests reserve an estimate so a burst of 100 cannot overshoot the cap."""

    def __init__(self, db, margin, est_usd=0.0006):
        self.db, self.margin, self.est = db, margin, est_usd
        self.lock = threading.Lock()
        self.inflight = {m: 0 for m in MODELS}
        self.lock_choice = threading.Lock()
        self.blocked_until = {}   # model -> time; set when OpenCode itself refuses with HTTP 402

    def block(self, model, seconds):
        """OpenCode's own accounting runs ahead of this ledger (2026-10-09: MiMo refused with 402 'Insufficient account
        funds' when the ledger showed ~$7.6 of the $12 5-hour cap), so a 402 benches the model for a while."""
        with self.lock:
            first = self.blocked_until.get(model, 0) < time.time()
            self.blocked_until[model] = max(self.blocked_until.get(model, 0), time.time() + seconds)
        if first:
            log.warning("%s refused by OpenCode (HTTP 402, plan limit); benched for %.0f min", model, seconds / 60)

    def _spent(self, model, window, now):
        return self.db.query("SELECT COALESCE(SUM(usd),0) FROM spend WHERE model=? AND ts>=?", (model, now - window))[0][0]

    def wait_seconds(self, model, now=None):
        """0 if a request may start now, else seconds until the tightest window has room."""
        now = now or time.time()
        if self.blocked_until.get(model, 0) > now:
            return self.blocked_until[model] - now
        if not MODELS[model]["capped"]:
            return 0.0
        with self.lock:
            for window, cap in CAPS.items():
                spent = self._spent(model, window, now) + self.inflight[model] * self.est
                if spent >= cap * self.margin:
                    oldest = self.db.query("SELECT MIN(ts) FROM spend WHERE model=? AND ts>=?", (model, now - window))[0][0]
                    return max(60.0, (oldest or now) + window - now)
            self.inflight[model] += 1
            return 0.0

    def has_room(self, model, now=None):
        """True if a capped model is under every cap (no reservation; used to choose between readers)."""
        now = now or time.time()
        if self.blocked_until.get(model, 0) > now:
            return False
        if not MODELS[model]["capped"]:
            return True
        return all(self._spent(model, w, now) + self.inflight[model] * self.est < cap * self.margin for w, cap in CAPS.items())

    def record(self, model, in_tok, out_tok):
        pi, po = MODELS[model]["price"]
        usd = in_tok / 1e6 * pi + out_tok / 1e6 * po
        if not MODELS[model]["capped"]:
            return usd
        with self.lock:
            self.inflight[model] = max(0, self.inflight[model] - 1)
        self.db.execute("INSERT INTO spend(ts, model, in_tok, out_tok, usd) VALUES (?,?,?,?,?)", (time.time(), model, in_tok, out_tok, usd))
        return usd

    def release(self, model):
        with self.lock:
            self.inflight[model] = max(0, self.inflight[model] - 1)

    def summary(self, model):
        now = time.time()
        return {f"{w // 3600}h": round(self._spent(model, w, now), 3) for w in CAPS}


class AdaptiveLimiter:
    """Concurrency gate. On a 429: limit -> 60% (not below the floor) and everyone pauses; after `step_every`
    clean responses the limit rises by `step` up to the ceiling."""

    def __init__(self, start, floor, ceiling, step=5, step_every=50, pause=20.0):
        self.limit, self.floor, self.ceiling = start, floor, ceiling
        self.step, self.step_every, self.pause = step, step_every, pause
        self.inflight, self.clean, self.resume_at = 0, 0, 0.0
        self.cv = threading.Condition()

    def acquire(self):
        with self.cv:
            while self.inflight >= self.limit or time.time() < self.resume_at:
                self.cv.wait(timeout=max(0.05, self.resume_at - time.time()) if time.time() < self.resume_at else 1.0)
            self.inflight += 1

    def has_room(self):
        with self.cv:
            return self.inflight < self.limit and time.time() >= self.resume_at

    def release(self, throttled=False):
        with self.cv:
            self.inflight -= 1
            if throttled:
                self.limit = max(self.floor, int(self.limit * 0.6))
                self.clean = 0
                self.resume_at = time.time() + self.pause
            else:
                self.clean += 1
                if self.clean >= self.step_every and self.limit < self.ceiling:
                    self.limit = min(self.ceiling, self.limit + self.step)
                    self.clean = 0
            self.cv.notify_all()


# ---------------------------------------------------------------- storage
SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  sha256 TEXT, page_no INTEGER, prompt_version TEXT, doc_id INTEGER, isin TEXT, symbol TEXT, doc_type TEXT,
  known_at TEXT, route TEXT, text_chars INTEGER, text_numbers INTEGER, img_cov REAL,
  primary_recall REAL, second_recall REAL, final_model TEXT, n_facts INTEGER, status TEXT, error TEXT, run_ts TEXT,
  PRIMARY KEY (sha256, page_no, prompt_version));
CREATE TABLE IF NOT EXISTS outputs (
  sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT, settings TEXT, run_ts TEXT, seconds REAL,
  in_tok INTEGER, out_tok INTEGER, usd REAL, raw_output TEXT,
  PRIMARY KEY (sha256, page_no, prompt_version, model));
CREATE TABLE IF NOT EXISTS facts (
  sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT, line_no INTEGER,
  metric TEXT, period TEXT, raw_number TEXT, value REAL, unit TEXT, is_final INTEGER);
CREATE INDEX IF NOT EXISTS ix_facts_page ON facts(sha256, page_no);
CREATE TABLE IF NOT EXISTS spend (ts REAL, model TEXT, in_tok INTEGER, out_tok INTEGER, usd REAL);
CREATE TABLE IF NOT EXISTS bad_docs (sha256 TEXT PRIMARY KEY, path TEXT, strikes INTEGER, last_page INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS doc_pages (sha256 TEXT PRIMARY KEY, n_pages INTEGER);
CREATE INDEX IF NOT EXISTS ix_spend ON spend(model, ts);
CREATE TABLE IF NOT EXISTS second_queue (
  sha256 TEXT, page_no INTEGER, prompt_version TEXT, task TEXT, jpeg TEXT, primary_res TEXT, queued_ts TEXT, tries INTEGER DEFAULT 0,
  PRIMARY KEY (sha256, page_no, prompt_version));
"""


class Store:
    def __init__(self, path):
        self.con = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        self.lock = threading.Lock()

    def execute(self, sql, args=()):
        with self.lock:
            self.con.execute(sql, args)
            self.con.commit()

    def query(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).fetchall()

    def complete_docs(self):
        """PDFs whose every page is finished under the current version: skipped without reopening."""
        return {r[0] for r in self.query("""SELECT d.sha256 FROM doc_pages d JOIN pages p ON p.sha256 = d.sha256
            AND p.prompt_version = ? AND p.status IN ('ok','skipped') GROUP BY d.sha256, d.n_pages
            HAVING COUNT(*) >= d.n_pages""", (PROMPT_VERSION,))}

    def done_keys(self):
        """Pages finished, plus pages claimed by the Claude page queue within CLAIM_HOURS (so the two never overlap)."""
        cutoff = (datetime.now() - timedelta(hours=CLAIM_HOURS)).isoformat(timespec="seconds")
        return {(s, p) for s, p in self.query("SELECT sha256, page_no FROM pages WHERE prompt_version=? AND (status IN ('ok','skipped') "
                                               "OR (status='claimed' AND run_ts >= ?))", (PROMPT_VERSION, cutoff))}

    def save_page(self, task, res):
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            c = self.con
            for model, r in res.get("readings", {}).items():
                c.execute("INSERT OR REPLACE INTO outputs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (task["sha256"], task["page_no"], PROMPT_VERSION, model, json.dumps(MODELS[model]["body"]), now,
                           r["seconds"], r["in_tok"], r["out_tok"], r["usd"], r["output"]))
                c.execute("DELETE FROM facts WHERE sha256=? AND page_no=? AND prompt_version=? AND model=?",
                          (task["sha256"], task["page_no"], PROMPT_VERSION, model))
                text = task.get("text") or ""
                c.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                              [(task["sha256"], task["page_no"], PROMPT_VERSION, model, i, f["metric"], f["period"], f["raw"],
                                f["value"], currency_scale_unit(f["metric"], f["raw"], f["unit"], text) or f["unit"],
                                int(model == res.get("final_model"))) for i, f in enumerate(r["facts"])])
            c.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (task["sha256"], task["page_no"], PROMPT_VERSION, task["doc_id"], task["isin"], task["symbol"], task["doc_type"],
                       task["known_at"], task["route"], task["text_chars"], len(task["truth"]), task["img_cov"],
                       res.get("primary_recall"), res.get("second_recall"), res.get("final_model"), res.get("n_facts", 0),
                       res["status"], res.get("error"), now))
            c.commit()

    def enqueue_second(self, task, jpeg_b64, res):
        t = {k: (sorted(v) if isinstance(v, set) else v) for k, v in task.items()}
        self.execute("INSERT OR REPLACE INTO second_queue VALUES (?,?,?,?,?,?,?,0)",
                     (task["sha256"], task["page_no"], PROMPT_VERSION, json.dumps(t), jpeg_b64, json.dumps(res),
                      datetime.now().isoformat(timespec="seconds")))

    def second_queue_size(self):
        return self.query("SELECT COUNT(*) FROM second_queue WHERE prompt_version=?", (PROMPT_VERSION,))[0][0]

    def next_second(self, exclude, n):
        """Oldest queued pages not already being read: (sha256, page_no, task, jpeg_b64, primary result, tries)."""
        rows = self.query("SELECT sha256, page_no, task, jpeg, primary_res, tries FROM second_queue WHERE prompt_version=? "
                          "ORDER BY tries, queued_ts LIMIT ?", (PROMPT_VERSION, n + len(exclude)))
        out = []
        for sha, pg, t, jpeg, r, tries in rows:
            if (sha, pg) not in exclude:
                task = json.loads(t); task["truth"] = set(task["truth"])
                out.append((sha, pg, task, jpeg, json.loads(r), tries))
        return out[:n]

    def drop_second(self, sha, page_no):
        self.execute("DELETE FROM second_queue WHERE sha256=? AND page_no=? AND prompt_version=?", (sha, page_no, PROMPT_VERSION))

    def bump_second(self, sha, page_no):
        self.execute("UPDATE second_queue SET tries=tries+1 WHERE sha256=? AND page_no=? AND prompt_version=?",
                     (sha, page_no, PROMPT_VERSION))


# ---------------------------------------------------------------- model calls
class Client:
    def __init__(self, ledger, limiters, timeout=300):
        self.ledger, self.limiters, self.timeout = ledger, limiters, timeout   # one adaptive limiter per model
        self.session_id = str(uuid.uuid4())
        self.http = requests.Session()
        self.http.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=256))
        self.keys = {}   # per gateway; OpenCode Go by default, Kilo for its models

    def _post(self, model, jpeg_b64, prompt):
        env = MODELS[model].get("key_env", "OPENCODE_GO_API_KEY")
        key = self.keys.setdefault(env, os.environ.get(env, ""))
        hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "x-opencode-session": self.session_id, "User-Agent": "reality-engine-deck-figures/1.0"}
        url = "data:image/jpeg;base64," + jpeg_b64
        if MODELS[model]["api"] == "agent":
            raise RuntimeError(f"{model} runs through scripts/claude_page_queue.py, not the extractor")
        if MODELS[model]["api"] == "chat":
            body = {"model": MODELS[model].get("id", model), **MODELS[model]["body"],
                    "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                                              {"type": "text", "text": prompt}]}]}
            r = self.http.post(f"{MODELS[model].get('base', BASE)}/chat/completions", headers=hdr, json=body, timeout=self.timeout)
            if r.status_code != 200:
                return r.status_code, r.text[:300], None
            j = r.json(); u = j.get("usage", {})
            if not j.get("choices"):   # gateways sometimes return HTTP 200 with an upstream error body
                return 502, r.text[:300], None
            return 200, j["choices"][0]["message"].get("content") or "", (u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        body = {"model": model, **MODELS[model]["body"],
                "input": [{"role": "user", "content": [{"type": "input_image", "image_url": url}, {"type": "input_text", "text": prompt}]}]}
        r = self.http.post(f"{BASE}/responses", headers=hdr, json=body, timeout=self.timeout)
        if r.status_code != 200:
            return r.status_code, r.text[:300], None
        j = r.json(); u = j.get("usage", {})
        txt = "".join(c.get("text", "") for o in j.get("output", []) if o.get("type") == "message" for c in o.get("content", []))
        return 200, txt, (u.get("input_tokens", 0), u.get("output_tokens", 0))

    def read(self, model, jpeg_b64, prompt, tries=6, wait_on_cap=True):
        """One reading with spend-cap handling, 429 backoff and retries on transient failures. A capped second reader
        raises CapReached instead of waiting, so the primary keeps the run moving."""
        last = None
        limiter = self.limiters[model]
        for attempt in range(tries):
            wait = self.ledger.wait_seconds(model)
            if wait:
                if not wait_on_cap:
                    raise CapReached(model)
                log.warning("spend cap reached for %s (%s); pausing %.0f min", model, self.ledger.summary(model), wait / 60)
                time.sleep(min(wait, 1800))
                continue
            limiter.acquire(); t = time.time(); throttled = False
            try:
                code, out, usage = self._post(model, jpeg_b64, prompt)
            except requests.RequestException as e:
                code, out, usage = -1, f"{type(e).__name__}: {e}"[:300], None
            throttled = code == 429
            limiter.release(throttled=throttled)
            if code == 200:
                usd = self.ledger.record(model, *usage)
                return {"output": out, "seconds": time.time() - t, "in_tok": usage[0], "out_tok": usage[1], "usd": usd,
                        "facts": parse_facts(out)}
            self.ledger.release(model)
            last = f"HTTP {code}: {out}"
            if code == 402:
                self.ledger.block(model, BENCH_402_SEC)
                raise CapReached(f"{model}: HTTP 402 plan limit")
            if code == -1 and "127.0.0.1" in MODELS[model].get("base", ""):
                self.ledger.block(model, 600)   # local server not running: set it aside, the others take the pages
                raise CapReached(f"{model}: local server unreachable")
            if code in (400, 401, 403, 404):
                break
            time.sleep(min(60, 2 ** attempt) if not throttled else 1)
        raise RuntimeError(last)


# ---------------------------------------------------------------- routing and rendering
GATE_TEXT_NUMBERS = 3   # pages with this many numbers in the text layer always go to a reader
GATE_OCR_NUMBERS = 2    # image-heavy pages with fewer text numbers go only if RapidOCR sees this many in the image
# Gate measured 2026-10-09: pages with <=2 text-layer numbers were 34% of pages but 55-79% empty. On 194 image-heavy
# such pages read by Haiku, an OCR count >= 2 kept 77% of pages with figures, skipped 80% of empty ones and lost 3.4% of
# that class's figures (under 0.2% of all figures), while sending 33% of them to a reader.


def page_task(doc, page, page_no, ocr=None):
    text = page.get_text()
    area = abs(page.rect) or 1.0
    img_area = sum(abs(pymupdf.Rect(i["bbox"]) & page.rect) for i in page.get_image_info())
    truth = text_numbers(text)
    img_cov = min(1.0, img_area / area)
    if len(truth) >= GATE_TEXT_NUMBERS:
        route = "vision"
    elif img_cov < 0.15:
        route = "skip"           # text page with at most 2 numbers: nothing for a reader
    elif ocr is None:
        route = "vision"         # no OCR available: do not guess, read it
    else:
        n = ocr(page)
        route = "vision" if n is None or n >= GATE_OCR_NUMBERS else "skip_ocr"
    return {**doc, "page_no": page_no, "text": text, "text_chars": len(text.strip()), "truth": truth, "img_cov": round(img_cov, 3),
            "route": route}


def render_jpeg_b64(page):
    import base64
    zoom = MAX_SIDE / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return base64.b64encode(pix.tobytes("jpeg", jpg_quality=JPEG_Q)).decode()


_OCR = []


def ocr_number_count(page):
    """Numbers RapidOCR (DirectML on the GPU) finds in the rendered page, counted like the text-layer reference.
    None when OCR is unavailable, so the caller reads the page instead of skipping it."""
    if not _OCR:
        try:
            from rapidocr import RapidOCR
            _OCR.append(RapidOCR(params={"EngineConfig.onnxruntime.use_dml": True, "Global.log_level": "ERROR",
                                         "Global.max_side_len": MAX_SIDE}))
        except Exception:
            _OCR.append(None)
    if _OCR[0] is None:
        return None
    try:
        zoom = MAX_SIDE / max(page.rect.width, page.rect.height)
        png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
        r = _OCR[0](png)
        return len(text_numbers(" ".join(r.txts or ()))) if r is not None else 0
    except Exception:
        return None


def render_doc(path, skip_pages):
    """Runs in a child process: route and render every page of one PDF that is not done yet. MuPDF can kill the
    process on a malformed PDF (it did on 2026-10-09, with no Python traceback); here that only kills the child."""
    out = []
    with pymupdf.open(path) as pdf:
        n = pdf.page_count
        for k, page in enumerate(pdf):
            if k + 1 in skip_pages:
                continue
            t = page_task({}, page, k + 1, ocr=ocr_number_count)
            t["jpeg"] = render_jpeg_b64(page) if t["route"] == "vision" else None
            out.append(t)
    return n, out


class Renderer:
    """Renders PDFs ahead of the API workers in a small process pool. A crash or hang breaks only the pool: the
    in-flight PDFs are then re-rendered one at a time in a fresh single-process pool, and the one that crashes again is
    recorded in bad_docs and skipped from then on. API work in the main process is never interrupted."""

    def __init__(self, store, procs=RENDER_PROCS, ahead=RENDER_AHEAD, timeout=RENDER_TIMEOUT, fn=None):
        self.store, self.procs, self.ahead, self.timeout = store, procs, ahead, timeout
        self.fn = fn or render_doc   # top-level, picklable; tests pass a stand-in
        self.pool = ProcessPoolExecutor(procs)

    def _kill(self, pool):
        for pr in list(getattr(pool, "_processes", {}).values()):
            try:
                pr.kill()
            except Exception:
                pass
        pool.shutdown(wait=False, cancel_futures=True)

    def _isolated(self, d, skip):
        pool = ProcessPoolExecutor(1)
        try:
            return pool.submit(self.fn, d["path"], skip).result(timeout=self.timeout)
        except (BrokenProcessPool, FutureTimeout) as e:
            self.store.execute("INSERT INTO bad_docs VALUES (?,?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET strikes=excluded.strikes, ts=excluded.ts",
                               (d["sha256"], d["path"], MAX_STRIKES, None, datetime.now().isoformat(timespec="seconds")))
            log.warning("renderer %s on %s; file skipped from now on", "crashed" if isinstance(e, BrokenProcessPool) else "hung", d["path"])
            return None
        except Exception as e:
            log.warning("unreadable PDF %s: %s", d["path"], e)
            return None
        finally:
            self._kill(pool)

    def run(self, docs, skip_of):
        """Yield (doc, page_count, rendered pages) in order, rendering up to `ahead` PDFs in advance."""
        window = deque()
        it = iter(docs)
        exhausted = False
        while True:
            while not exhausted and len(window) < self.ahead:
                d = next(it, None)
                if d is None:
                    exhausted = True; break
                skip = skip_of(d)
                try:
                    fut = self.pool.submit(self.fn, d["path"], skip)
                except BrokenProcessPool:   # broken by a crash in a PDF already in the window: rebuild, resubmit
                    self._kill(self.pool); self.pool = ProcessPoolExecutor(self.procs)
                    fut = self.pool.submit(self.fn, d["path"], skip)
                window.append((d, skip, fut))
            if not window:
                return
            d, skip, fut = window.popleft()
            try:
                n, pages = fut.result(timeout=self.timeout)
                yield d, n, pages
            except (BrokenProcessPool, FutureTimeout):
                # one of the PDFs in flight killed or hung the pool: rebuild it and redo the in-flight PDFs singly
                self._kill(self.pool); self.pool = ProcessPoolExecutor(self.procs)
                for dd, sk, _ in [(d, skip, None)] + list(window):
                    r = self._isolated(dd, sk)
                    if r:
                        yield dd, r[0], r[1]
                window.clear()
            except Exception as e:
                log.warning("unreadable PDF %s: %s", d["path"], e)

    def close(self):
        self._kill(self.pool)


def needs_second_reader(task, primary_facts, primary_recall):
    # With the rich prompt the primary rightly skips slide numbers, addresses and footnote markers that the text-layer
    # reference still counts, so only a large shortfall on a number-heavy page triggers (pilot 2026-10-09: the looser
    # 0.6 / 5-number rule fired on 42% of pages and moved final recall by 2 points).
    if primary_recall is not None and len(task["truth"]) >= 10 and primary_recall < SECOND_READER_RECALL:
        return True
    ident = identifiable_share(primary_facts)
    if ident is not None and len(primary_facts) >= 5 and ident < SECOND_READER_IDENTIFIABLE:
        return True
    # an image-only page with no figures is usually a title/product slide: on 30 such pages (AARON, 2026-10-09) the
    # second reader agreed every time, so only a figure-less page whose text layer shows numbers is re-read
    return not primary_facts and len(task["truth"]) >= 5


def choose(client, preferred, alternates):
    """The preferred reader if it has a free slot, else the first alternate with a free slot and spend room, else the
    preferred one (the caller then waits on its limiter). Keeps every reader busy without overrunning any of them."""
    order = [preferred] + [m for m in alternates if m != preferred]
    with client.ledger.lock_choice:
        for m in order:
            if m in client.limiters and client.limiters[m].has_room() and client.ledger.has_room(m):
                return m
    return preferred


def process(task, jpeg_b64, client, use_second, primaries=None, seconds=None, defer=None, turn=0):
    """Primary reading, then a second reading where the primary looks weak. `turn` rotates which primary is tried
    first, so every free primary carries part of the load (not only when the first is full). With `defer` (a callable
    saying whether the second queue has room) a needed second reading is not done here: the result comes back with
    second_pending=True and the caller queues the page for the second-reader pool."""
    primaries = primaries or [PRIMARY]; seconds = seconds or [SECOND]
    readings = {}
    prompt = build_prompt(task)
    first = None
    try:
        first = choose(client, primaries[turn % len(primaries)], primaries)
        try:
            p = client.read(first, jpeg_b64, prompt, wait_on_cap=(first == primaries[0]))
        except Exception:
            if first == primaries[0]:
                raise
            # an alternate primary hit its plan limit or failed (Kilo/Dots answers ~20% of calls with a provider-side
            # HTTP 400, 2026-10-09): the main primary takes the page
            first = primaries[0]
            p = client.read(first, jpeg_b64, prompt)
        readings[first] = p
        pr = recall(fact_numbers(p["facts"]), task["truth"])
        res = {"readings": readings, "primary_recall": pr, "final_model": first, "status": "ok", "n_facts": len(p["facts"])}
        if use_second and needs_second_reader(task, p["facts"], pr):
            if defer is not None and defer():
                res["second_pending"] = True
                return res
            return second_read(task, jpeg_b64, client, res, seconds, prompt)
        return res
    except CapReached as e:   # an alternate primary ran out of cap between the choice and the call: retry next pass
        return {"readings": readings, "status": "error", "error": f"cap reached: {e}", "final_model": None}
    except Exception as e:   # keep the reading(s) that did finish; status 'error' so a rerun retries the page
        return {"readings": readings, "status": "error", "error": str(e)[:500],
                "final_model": first if first in readings else None}


def second_read(task, jpeg_b64, client, res, seconds, prompt=None):
    """Adds a second reading to a primary result and marks the better reading final. A failed second reading leaves
    the primary reading standing, with the failure in res['error']."""
    readings = res["readings"]; first = res["final_model"]; p = readings[first]
    pr = res.get("primary_recall")
    prompt = prompt or build_prompt(task)
    res.pop("second_pending", None); res["error"] = None
    second = choose(client, seconds[0], [m for m in seconds[1:] if m != first])
    if second == first:
        second = next((m for m in seconds if m != first), None)
    try:
        if second is None:
            raise CapReached("no second reader")
        s = client.read(second, jpeg_b64, prompt, wait_on_cap=False)
    except Exception as e:   # the primary reading stands; the page is not failed because a second read did not happen
        res["second_recall"] = None; res["n_facts"] = len(p["facts"])
        res["error"] = f"second reader skipped: {str(e)[:200]}"
        return res
    readings[second] = s
    sr = recall(fact_numbers(s["facts"]), task["truth"])
    res["second_recall"] = sr
    score = lambda rc, f: (rc if rc is not None else -1, identifiable_share(f) or 0, len(f))
    if score(sr, s["facts"]) > score(pr, p["facts"]):
        res["final_model"] = second
    res["n_facts"] = len(readings[res["final_model"]]["facts"])
    return res


# ---------------------------------------------------------------- driver
def load_docs(doc_types, symbols, limit, include_intimations=False):
    """Documents to read, newest first. 463 of the 1,615 INVESTOR_PRESENTATION rows (2026-10-09) are
    'Analyst / Investor Meet - Intimation' letters (meeting schedules, no deck), skipped unless asked for."""
    con = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True, timeout=60)
    q = ("SELECT d.id, d.isin, d.symbol, d.doc_type, d.local_file_path, d.sha256_hash, "
         "COALESCE(d.bse_dissem_ts, d.publication_date, d.doc_date), "
         "(SELECT m.company_name FROM master_companies m WHERE m.isin = d.isin LIMIT 1) "
         "FROM corporate_documents d "
         f"WHERE d.local_file_path IS NOT NULL AND d.doc_type IN ({','.join('?' * len(doc_types))})")
    if not include_intimations:
        q += " AND COALESCE(d.title,'') NOT LIKE '%Intimation%'"
    args = list(doc_types)
    if symbols:
        q += f" AND d.symbol IN ({','.join('?' * len(symbols))})"; args += symbols
    q += " ORDER BY COALESCE(d.bse_dissem_ts, d.publication_date, d.doc_date) DESC"
    rows = con.execute(q, args).fetchall()
    names = {i: n for i, n in con.execute("SELECT isin, company_name FROM master_companies WHERE isin IS NOT NULL")}
    con.close()
    # historical decks downloaded by fetch_decks.py (BSE 2021+, NSE-only companies), recorded in deck_sources
    if "INVESTOR_PRESENTATION" in doc_types and OUT_DB.exists():
        o = sqlite3.connect(OUT_DB, timeout=60)
        if o.execute("SELECT 1 FROM sqlite_master WHERE name='deck_sources'").fetchone():
            sq = "SELECT source || ':' || source_id, isin, symbol, local_path, sha256, known_at FROM deck_sources WHERE status='ok'"
            sargs = []
            if symbols:
                sq += f" AND symbol IN ({','.join('?' * len(symbols))})"; sargs = list(symbols)
            rows += [(i, isin, sym, "INVESTOR_PRESENTATION", p, sha, known, names.get(isin))
                     for i, isin, sym, p, sha, known in o.execute(sq, sargs)]
        o.close()
    rows.sort(key=lambda r: str(r[6] or ""), reverse=True)
    docs, seen = [], set()
    for i, isin, sym, dt, path, sha, known, company in rows:
        if not path or not Path(path).exists():
            continue
        sha = sha or hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if sha in seen:   # same PDF filed twice
            continue
        seen.add(sha)
        docs.append({"doc_id": i, "isin": isin, "symbol": sym, "doc_type": dt, "path": path, "sha256": sha, "known_at": known,
                     "company": company})
        if limit and len(docs) >= limit:
            break
    return docs


def main():
    global PRIMARY, SECOND
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc-types", default="INVESTOR_PRESENTATION")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--limit-docs", type=int, default=0)
    ap.add_argument("--primary", default=PRIMARY, choices=sorted(MODELS))
    ap.add_argument("--second", default=SECOND, choices=sorted(MODELS))
    ap.add_argument("--also-primary", default=",".join(ALSO_PRIMARY), help="comma list; '' to use the primary alone")
    ap.add_argument("--also-second", default=",".join(ALSO_SECOND), help="comma list; '' to use the second reader alone")
    ap.add_argument("--workers", type=int, default=0, help="starting parallel requests for the primary (default: its ceiling)")
    ap.add_argument("--min-workers", type=int, default=10)
    ap.add_argument("--enqueue-second", action="store_true", help="queue new pages for the second reader (paused by default)")
    ap.add_argument("--cap-margin", type=float, default=0.85, help="fraction of each OpenCode Go $ cap this run may use")
    ap.add_argument("--no-second-reader", action="store_true")
    ap.add_argument("--include-intimations", action="store_true", help="also read 'Investor Meet - Intimation' letters")
    ap.add_argument("--dry-run", action="store_true", help="route pages and report counts; no API calls, no writes")
    ap.add_argument("--db", default=str(OUT_DB))
    a = ap.parse_args()
    PRIMARY, SECOND = a.primary, a.second

    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
    docs = load_docs([d.strip() for d in a.doc_types.split(",")], [s.strip() for s in a.symbols.split(",") if s.strip()], a.limit_docs,
                     a.include_intimations)
    primaries = [PRIMARY] + [m.strip() for m in a.also_primary.split(",") if m.strip() and m.strip() != PRIMARY]
    seconds = [SECOND] + [m.strip() for m in a.also_second.split(",") if m.strip() and m.strip() != SECOND]
    for m in primaries + seconds:
        if m not in MODELS:
            raise SystemExit(f"unknown model {m}")
    log.info("documents: %d (prompt version %s) | primary readers %s, second readers %s", len(docs), PROMPT_VERSION, primaries, seconds)

    if a.dry_run:
        n_pages = n_vision = bad = 0
        for d in docs:
            try:
                with pymupdf.open(d["path"]) as pdf:
                    for k, page in enumerate(pdf):
                        n_pages += 1; n_vision += page_task(d, page, k + 1)["route"] == "vision"
            except Exception:
                bad += 1
        pi, po = MODELS[PRIMARY]["price"]
        est = n_vision * 3000 / 1e6 * pi + n_vision * 1000 / 1e6 * po   # prompt + text layer ~3k in, ~1k out (quality test means)
        log.info("dry run: %d pages, %d to vision, %d skipped, %d unreadable PDFs; est. primary cost $%.2f",
                 n_pages, n_vision, n_pages - n_vision, bad, est)
        return

    store = Store(a.db)
    for old in LEGACY_VERSIONS:   # same prompt under an older version hash: keep those pages as done
        for t in ("pages", "outputs", "facts"):
            store.execute(f"UPDATE OR IGNORE {t} SET prompt_version=? WHERE prompt_version=?", (PROMPT_VERSION, old))
    ledger = SpendLedger(store, a.cap_margin)
    limiters = {}
    for m in primaries + seconds:
        c = MODELS[m]["ceiling"]
        start = min(a.workers or c, c) if m == PRIMARY else c
        limiters.setdefault(m, AdaptiveLimiter(start, min(a.min_workers, c), c))
    limiter = limiters[PRIMARY]
    ceil_p = sum(MODELS[m]["ceiling"] for m in primaries)
    ceil_s = sum(MODELS[m]["ceiling"] for m in dict.fromkeys(seconds))
    client = Client(ledger, limiters)
    done = store.done_keys()
    stats = {"pages": 0, "ok": 0, "skipped": 0, "error": 0, "second": 0}
    slock = threading.Lock(); t0 = time.time(); last_report = [t0]

    def finish(task, res):
        store.save_page(task, res)
        with slock:
            stats["pages"] += 1; stats[res["status"]] = stats.get(res["status"], 0) + 1
            stats["second"] += len(res.get("readings", {})) > 1
            if time.time() - last_report[0] > 30:
                last_report[0] = time.time(); el = time.time() - t0
                log.info("pages %d (ok %d, skipped %d, error %d, second reads %d, second queue %d) | %.1f pages/s | in flight/limit %s | capped spend %s",
                         stats["pages"], stats["ok"], stats["skipped"], stats["error"], stats["second"], store.second_queue_size(),
                         stats["pages"] / el,
                         {m.split("-")[0] + m.partition("@")[1] + m.partition("@")[2]: f"{l.inflight}/{l.limit}" for m, l in limiters.items()},
                         {m.split("-")[0]: ledger.summary(m)["5h"] for m in limiters if MODELS[m]["capped"]})

    turns = itertools.count()
    defer = lambda: store.second_queue_size() < SECOND_QUEUE_MAX

    def work(task, b64):
        res = process(task, b64, client, not a.no_second_reader, primaries, seconds, defer=defer, turn=next(turns))
        if res.get("second_pending") and not a.enqueue_second:   # queue paused: keep the primary reading, mark the page
            res.pop("second_pending"); res["error"] = SECOND_DEFERRED
        finish(task, res)   # saved first, so a quick second reading can never be overwritten by the primary one
        if res.get("second_pending"):
            store.enqueue_second(task, b64, res)

    reading2, lock2, stop2 = set(), threading.Lock(), threading.Event()
    pause2 = [0.0]   # second readings wait until this time after an upstream 429

    def second_job(sha, pg, task, b64, res, tries):
        try:
            res = second_read(task, b64, client, res, seconds)
            if "HTTP 429" in (res.get("error") or ""):   # throttled, not a bad page: keep it queued, pause the pool
                if time.time() >= pause2[0]:
                    log.warning("second reader throttled (HTTP 429); second readings paused %d s", SECOND_PAUSE_429)
                pause2[0] = time.time() + SECOND_PAUSE_429
                return
            if res.get("error") and tries + 1 < SECOND_TRIES:
                store.bump_second(sha, pg); return
            store.save_page(task, res); store.drop_second(sha, pg)
            with slock:
                stats["second"] += len(res["readings"]) > 1
        except Exception as e:
            log.error("second reading crashed on %s p%s: %s", sha[:12], pg, e)
            store.bump_second(sha, pg)
        finally:
            with lock2:
                reading2.discard((sha, pg))

    def dispatch_second():
        """Keeps the second readers at their current limits from second_queue (which survives restarts); once the
        primary pass is over, drains the queue and returns."""
        with ThreadPoolExecutor(max(1, ceil_s)) as ex2:
            while True:
                if time.time() < pause2[0]:
                    if stop2.is_set():
                        return   # throttled at the end of a pass: the queue persists for the next pass
                    time.sleep(5); continue
                with lock2:
                    room = sum(limiters[m].limit for m in dict.fromkeys(seconds)) - len(reading2)
                    rows = store.next_second(set(reading2), room) if room > 0 else []
                    reading2.update((r[0], r[1]) for r in rows)
                for r in rows:
                    ex2.submit(second_job, *r)
                if not rows:
                    with lock2:
                        idle = not reading2
                    if stop2.is_set() and idle and store.second_queue_size() == 0:
                        return
                    time.sleep(1)

    if not a.no_second_reader:
        n2 = store.second_queue_size()
        if n2:
            log.info("%d pages waiting for a second reading from an earlier run", n2)
        t2 = threading.Thread(target=dispatch_second, name="second-readers", daemon=True); t2.start()

    if MARKER.exists():   # left by a pre-isolation run that died mid-render: count it as a strike
        try:
            sha, path, pg = MARKER.read_text(encoding="utf-8").split("\t")
            store.execute("INSERT INTO bad_docs VALUES (?,?,1,?,?) ON CONFLICT(sha256) DO UPDATE SET strikes=strikes+1, ts=excluded.ts",
                          (sha, path, int(pg), datetime.now().isoformat(timespec="seconds")))
        except ValueError:
            pass
        MARKER.unlink()
    bad = {r[0] for r in store.query("SELECT sha256 FROM bad_docs WHERE strikes >= ?", (MAX_STRIKES,))}
    complete = store.complete_docs()
    todo = [d for d in docs if d["sha256"] not in bad and d["sha256"] not in complete]
    log.info("%d documents already complete, %d skipped as unrenderable, %d to open", sum(d["sha256"] in complete for d in docs),
             sum(d["sha256"] in bad for d in docs), len(todo))
    done_pages = {}
    for sha, pg in done:
        done_pages.setdefault(sha, set()).add(pg)
    renderer = Renderer(store)
    pending = threading.BoundedSemaphore(ceil_p * 2)   # rendered pages waiting for a slot
    try:
        with ThreadPoolExecutor(ceil_p * 2) as ex:
            for d, n_pages, pages in renderer.run(todo, lambda d: done_pages.get(d["sha256"], set())):
                store.execute("INSERT OR REPLACE INTO doc_pages VALUES (?,?)", (d["sha256"], n_pages))
                for t in pages:
                    task = {**d, **{k: v for k, v in t.items() if k != "jpeg"}}
                    if task["route"].startswith("skip"):
                        finish(task, {"status": "skipped"}); continue
                    pending.acquire()
                    fut = ex.submit(work, task, t["jpeg"])
                    fut.add_done_callback(lambda f: (pending.release(), f.exception() and log.error("worker crashed: %s", f.exception())))
    finally:
        renderer.close()
        stop2.set()
    if not a.no_second_reader:
        log.info("primary pass done; finishing %d queued second readings", store.second_queue_size())
        t2.join()
    el = time.time() - t0
    log.info("finished: %s in %.1f min | spend %s (primary) %s (second)", stats, el / 60, ledger.summary(PRIMARY), ledger.summary(SECOND))
    return 3 if stats["pages"] else 0   # 3 = did work this pass; run_deck_extract.cmd goes round again for new files


if __name__ == "__main__":
    raise SystemExit(main())
