"""Fetch the BSE document history for a pilot universe (default: the pilot-60 names).

Raw fetch only (no extraction, chunking or LLM): BSE announcement metadata -> bucket
-> attachment PDFs under ``D:\\RealityEngine\\raw\\pilot60_history\\<symbol>\\<bucket>\\<newsid>.pdf``
with a CSV manifest and a SQLite manifest at ``reality_engine/data/pilot/pilot60_history_manifest.db``.

The universe is ``tasks/pilot60/UNIVERSE.csv`` by default; ``--universe`` points at another
CSV (e.g. ``tasks/pilot60/UNIVERSE_ADD3.csv`` for the three names added on 2026-11-01).
``--window-start/--window-end`` move the filing window (default 2019-01-01..2024-04-01, the
period the 60's FY2024-25-onward documents were already held).

Metadata comes from the existing ``bse_announcements.db`` plus the BSE
``AnnSubCategoryGetData`` API (the DB feed starts 2020-01-01, the window starts
2019-01-01).  Files already held by another store (``corporate_documents`` /
``deck_figures.deck_sources``) are hard-linked in instead of re-downloaded.

Modes::

    python -m reality_engine.scripts.fetch_pilot60_history --measure   # metadata + counts only
    python -m reality_engine.scripts.fetch_pilot60_history --fetch     # download (resumable)
    python -m reality_engine.scripts.fetch_pilot60_history --scan      # is_scanned_guess pass
    python -m reality_engine.scripts.fetch_pilot60_history --coverage  # tasks/pilot60/HISTORY_COVERAGE_*.md

Every mode is resumable: a row with ``status='ok`` and a present PDF is never fetched again.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from reality_engine.config import DATA_DIR, RAW_ROOT
from reality_engine.db.readonly import connect_ro

logger = logging.getLogger("reality_engine.pilot60_history")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_CSV = PROJECT_ROOT / "tasks" / "pilot60" / "UNIVERSE.csv"
ROOT = RAW_ROOT / "pilot60_history"
MANIFEST_CSV = ROOT / "manifest.csv"
# Live databases are read from REALITY_DATA_ROOT (the worktree data dir is empty); the
# manifest DB is the one database this job writes, and it lives with the live data.
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT") or DATA_DIR)
MANIFEST_DB = DATA_ROOT / "pilot" / "pilot60_history_manifest.db"
LOG_DIR = ROOT / "logs"
CACHE_DIR = PROJECT_ROOT / ".tmp" / "pilot60_meta"

WINDOW_START = date(2019, 1, 1)
WINDOW_END = date(2024, 4, 1)  # exclusive: 2024-04-01 onward is already held

BUCKETS = ("annual_report", "investor_presentation", "concall_transcript",
           "concall_audio_link", "quarterly_results", "results_press_release",
           "material_filing")
BUCKET_ORDER = {b: i for i, b in enumerate(BUCKETS)}

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/"
ANN_URL = (BSE_API + "AnnSubCategoryGetData/w?pageno={p}&strCat=-1&strPrevDate={f}"
           "&strScrip={c}&strSearch=P&strToDate={t}&strType=C&subcategory=-1")
PDF_URLS = ("https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}",
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Referer": "https://www.bseindia.com/",
     "Accept": "application/json, text/plain, */*",
     "Origin": "https://www.bseindia.com"}
PDF_MAGIC = b"%PDF"
PAGE = 50  # BSE announcement page size
MIN_FREE_BYTES = 50 * 1024 ** 3  # stop below 50 GB free on D: (brief rule)


def free_bytes(path):
    import shutil
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return float("inf")

FIELDS = ["isin", "symbol_at_time", "scrip_code", "newsid", "bucket", "headline",
          "category", "subcat", "dissem_ts", "url", "source", "local_path", "bytes",
          "sha256", "http_status", "attempts", "is_pdf", "is_scanned_guess",
          "skip_reason", "fetched_at", "status", "error"]
# ``status``/``error`` are additions the brief needs for the failure and resume checks.

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    isin TEXT, symbol_at_time TEXT, scrip_code TEXT, newsid TEXT PRIMARY KEY,
    bucket TEXT, headline TEXT, category TEXT, subcat TEXT, dissem_ts TEXT,
    url TEXT, source TEXT, local_path TEXT, bytes INTEGER, sha256 TEXT,
    http_status INTEGER, attempts INTEGER DEFAULT 0, is_pdf INTEGER,
    is_scanned_guess INTEGER, skip_reason TEXT, fetched_at TEXT,
    status TEXT DEFAULT 'pending', error TEXT)
"""
CSV_FIELDS = FIELDS


# ----------------------------------------------------------------- quiet helpers
def parse_ts(value):
    """BSE timestamps are naive IST ISO strings -> 'YYYY-MM-DDTHH:MM:SS' or None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(microsecond=0).isoformat()
    except ValueError:
        return None


def in_window(ts):
    if not ts:
        return False
    d = date.fromisoformat(ts[:10])
    return WINDOW_START <= d < WINDOW_END


def clean(text):
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()


_AUDIO_RE = re.compile(r"audio|voice.?record|recording", re.I)
_CALL_RE = re.compile(r"earnings call|con-?call|analyst call|investor call|"
                      r"investor (?:meet|conference)|analyst / investor", re.I)
_TRANSCRIPT_RE = re.compile(r"\btranscript\b", re.I)
_INVITE_RE = re.compile(r"intimation|invite|schedule|will be held|is scheduled|to be held", re.I)
_PPT_RE = re.compile(r"investor presentation|earnings presentation|corporate presentation|"
                     r"investor ppt", re.I)
_RESULTS_RE = re.compile(r"financial results?|unaudited results|audited results|"
                         r"results for the (?:quarter|year|period)|quarterly results|"
                         r"annual results|q[1-4]\s*(?:fy)?\s*\d{0,4}", re.I)
_RESULTS_NOISE = re.compile(r"voting|scrutiniz|e-voting|postal ballot|newspaper|"
                            r"annual report|book closure|record date", re.I)
_PRESS_RE = re.compile(r"press release|media release", re.I)
_AR_WORDS = re.compile(r"annual report", re.I)
_AR_NOTICE = re.compile(r"notice|proceedings|voting|scrutiniz|book closure|"
                        r"business responsibility|brsr|esg", re.I)

# Applied to SUBCATNAME (BSE's own taxonomy) plus NEWSSUB, never to the long headline:
# a routine certificate mentioned inside a material headline must not skip it.
SKIP_RULES = (
    (re.compile(r"trading window", re.I), "routine: trading window closure"),
    (re.compile(r"newspaper (?:publication|advertisement)|publication of (?:notice|advertisement)", re.I),
     "routine: newspaper publication"),
    (re.compile(r"loss of (?:share )?certificate|duplicate certificate|reg\.?\s*39\s*\(\s*3\s*\)", re.I),
     "routine: loss of share certificates"),
    (re.compile(r"reg\.?\s*74\s*\(\s*5\s*\)", re.I), "routine: Reg 74(5) certificate"),
    (re.compile(r"reg\.?\s*(?:7\s*\(\s*3\s*\)|40\s*\(\s*9\s*\))", re.I),
     "routine: Reg 7(3)/40(9) certificate"),
    (re.compile(r"compliance certificate", re.I), "routine: compliance certificate"),
    (re.compile(r"investor complaints|reg\.?\s*13\s*\(\s*3\s*\)", re.I),
     "routine: investor complaints statement"),
    (re.compile(r"pcs certificate|reg\.?\s*40\s*\(\s*10\s*\)", re.I),
     "routine: PCS certificate for transfer/transmission"),
    (re.compile(r"annual secretarial compliance", re.I),
     "routine: annual secretarial compliance"),
    (re.compile(r"large corporate", re.I), "routine: large-corporate disclosure"),
    (re.compile(r"code of conduct under sebi", re.I), "routine: PIT code of conduct"),
    (re.compile(r"certificate from ceo\s*/?\s*cfo", re.I), "routine: CEO/CFO certificate"),
)
# Exact certificate title phrases are safe to match in the headline; other routine
# words (e.g. "compliance certificate") are only trusted in the BSE subcategory.
SKIP_HEADLINE = (
    (re.compile(r"certificate under (?:regulation|reg\.?)\s*74\s*\(\s*5\s*\)", re.I),
     "routine: Reg 74(5) certificate"),
    (re.compile(r"certificate under (?:regulation|reg\.?)\s*(?:7\s*\(\s*3\s*\)|40\s*\(\s*9\s*\))", re.I),
     "routine: Reg 7(3)/40(9) certificate"),
)


def skip_reason(row):
    text = " ".join((row.get("subcat") or "", row.get("newssub") or ""))
    for pattern, reason in SKIP_RULES:
        if pattern.search(text):
            return reason
    headline = row.get("headline") or ""
    for pattern, reason in SKIP_HEADLINE:
        if pattern.search(headline):
            return reason
    return None


def classify(row):
    """(bucket, skip_reason). Buckets are the seven the brief names; BSE taxonomy first."""
    reason = skip_reason(row)
    if reason:
        return "skip", reason
    subcat = (row.get("subcat") or "").strip()
    low = subcat.lower()
    headline = row.get("headline") or ""
    cat = (row.get("category") or "").strip().lower()
    text = f"{subcat} {headline}"

    if _AR_WORDS.search(text) and (not _AR_NOTICE.search(headline) or "annual report" in low):
        return "annual_report", None
    if _AUDIO_RE.search(text) and _CALL_RE.search(text):
        return "concall_audio_link", None
    if "transcript" in low or (_TRANSCRIPT_RE.search(headline) and not _INVITE_RE.search(headline)
                               and _CALL_RE.search(text)):
        return "concall_transcript", None
    if "investor presentation" in low or _PPT_RE.search(headline):
        return "investor_presentation", None
    if cat == "result" and "financial results" in low:
        return ("results_press_release" if _PRESS_RE.search(text) else "quarterly_results"), None
    results = bool(_RESULTS_RE.search(text)) and not _RESULTS_NOISE.search(text)
    if _PRESS_RE.search(text):
        return ("results_press_release" if results else "material_filing"), None
    if results and low in ("outcome of board meeting", "meeting updates",
                           "revision of outcome", "general", "financial results",
                           "financial result updates"):
        return "quarterly_results", None
    return "material_filing", None


_AY_RE = re.compile(r"\b(20\d{2})\s*[-/]\s*(\d{2,4})\b")


def fiscal_year(ts, bucket, text=""):
    """Fiscal year the filing belongs to (FY ends in March).

    annual_report: the 2022-23 label if the headline has it, else the filing year;
    quarterly_results: inferred from the filing month (Q4 Apr-Jun, Q1 Jul-Sep ...);
    everything else: the fiscal year in which the filing was made.
    """
    d = date.fromisoformat(str(ts)[:10])
    if bucket == "annual_report":
        m = _AY_RE.search(text or "")
        if m:  # "2022-23" / "2022-2023" -> FY23 (the year the fiscal year ends)
            end = m.group(2)
            return 2000 + int(end) if len(end) == 2 else int(end)
        return d.year if d.month >= 4 else d.year - 1
    if bucket == "quarterly_results":
        return d.year + 1 if d.month >= 7 else d.year
    return d.year + 1 if d.month >= 4 else d.year


# --------------------------------------------------------------------- universe
def load_universe(path=UNIVERSE_CSV):
    """Rows of the universe CSV; nine MICRO rows carry only an ISIN, so the NSE symbol is
    resolved from the live master (name/symbol history first, then symbol history)."""
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("isin")]
    blanks = [r for r in rows if not (r.get("symbol") or "").strip()]
    if blanks:
        conn = connect_ro(DATA_ROOT / "equity_intelligence.db", timeout_s=60)
        queries = ("SELECT nse_symbol FROM security_master WHERE isin=? AND nse_symbol IS NOT NULL",
                   "SELECT nse_symbol FROM master_companies WHERE isin=? AND nse_symbol IS NOT NULL",
                   "SELECT symbol FROM symbol_isin_history WHERE isin=? AND exchange='NSE'")
        for row in blanks:
            for sql in queries:
                try:
                    got = conn.execute(sql, (row["isin"],)).fetchone()
                except sqlite3.Error:
                    continue
                if got and got[0]:
                    row["symbol"] = str(got[0]).strip()
                    break
            if not row.get("symbol"):
                row["symbol"] = row["isin"]
                logger.warning("no NSE symbol for %s; keeping the ISIN as the key", row["isin"])
    return rows


def _query(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def resolve(universe):
    """symbol -> dict(isin, code, scrip_name) with the BSE scrip code of the ISIN."""
    conn = connect_ro(DATA_ROOT / "equity_intelligence.db", timeout_s=120)
    isins = [r["isin"] for r in universe]
    marks = ",".join("?" * len(isins))
    found = {}
    for table, cols in (("master_companies", "isin, nse_symbol, bse_code, company_name"),
                        ("security_master", "isin, nse_symbol, bse_code, issuer")):
        try:
            rows = _query(conn, f"SELECT {cols} FROM {table} WHERE isin IN ({marks})", isins)
        except sqlite3.Error:
            continue
        for isin, sym, code, name in rows:
            if code:
                found.setdefault(isin, {"code": str(code).strip(), "name": name})
    out = {}
    for row in universe:
        hit = found.get(row["isin"], {})
        if not hit.get("code"):
            logger.warning("no BSE scrip code for %s (%s)", row["symbol"], row["isin"])
            continue
        out[row["symbol"]] = {"isin": row["isin"], "code": hit["code"],
                              "name": hit.get("name") or row["symbol"],
                              "symbol": row["symbol"]}
    return out, conn


def symbol_windows(conn, symbols):
    """symbol -> [(first_date, last_date, symbol)] from the NSE symbol/ISIN history."""
    marks = ",".join("?" * len(symbols))
    try:
        rows = _query(conn, "SELECT symbol, first_date, last_date FROM symbol_isin_history "
                            f"WHERE exchange='NSE' AND symbol IN ({marks}) ORDER BY first_date",
                     list(symbols))
    except sqlite3.Error:
        return {}
    out = {}
    for sym, first, last in rows:
        out.setdefault(sym, []).append((first or "", last or "", sym))
    return out


def symbol_at(symbol, windows, ts):
    d = str(ts)[:10]
    for first, last, sym in windows.get(symbol, []):
        if (not first or first <= d) and (not last or d <= last):
            return sym
    return symbol


# ------------------------------------------------------------------ metadata
def year_windows():
    w = []
    for year in range(WINDOW_START.year, WINDOW_END.year + 1):
        a = max(date(year, 1, 1), WINDOW_START)
        b = min(date(year, 12, 31), WINDOW_END - timedelta(days=1))
        if a <= b:
            w.append((a, b))
    return w


class Pacer:
    """One shared request rate for every worker, plus a global penalty box."""

    def __init__(self, interval, sleep=time.sleep, clock=time.monotonic):
        self.interval = max(0.0, float(interval))
        self.sleep = sleep
        self.clock = clock
        self._lock = threading.Lock()
        self._next = 0.0
        self._blocked_until = 0.0

    def wait(self):
        with self._lock:
            now = self.clock()
            ready = max(self._next, self._blocked_until)
            delay = max(0.0, ready - now)
            self._next = max(now, ready) + self.interval
        if delay:
            self.sleep(delay)

    def block(self, seconds):
        with self._lock:
            self._blocked_until = max(self._blocked_until, self.clock() + seconds)


def new_session():
    from curl_cffi import requests as cr
    s = cr.Session(impersonate="chrome120")
    try:
        s.get("https://www.bseindia.com/corporates/ann.html", headers=H, timeout=30)
    except Exception:  # warm-up is best effort
        pass
    return s


def http_get(session, url, pacer, tries=4, timeout=120, want_json=False):
    """(body|None, http_status|None, attempts, error). Retries blocks/5xx; 404 is final."""
    attempts, last, status = 0, None, None
    for attempt in range(tries):
        pacer.wait()
        attempts += 1
        try:
            resp = session.get(url, headers=H, timeout=timeout)
            status = getattr(resp, "status_code", None)
            body = getattr(resp, "content", b"") or b""
        except Exception as exc:  # noqa: BLE001 - transient network
            last, status = f"{type(exc).__name__}: {exc}", None
            time.sleep(min(3.0 * 2 ** attempt, 60.0))
            continue
        if status == 200:
            if want_json:
                try:
                    return json.loads(body.decode("utf-8", "replace")), status, attempts, None
                except ValueError as exc:
                    return None, status, attempts, f"bad json: {exc}"
            return body, status, attempts, None
        last = f"HTTP {status}"
        if status in (403, 429):  # rate block: rest the whole stream
            wait = min(60.0 * 2 ** attempt, 600.0)
            pacer.block(wait)
            logger.warning("%s on %s - pausing every stream for %.0fs",
                           last, url.split("?")[0], wait)
            continue
        if isinstance(status, int) and status >= 500:  # server hiccup: this request only
            time.sleep(min(3.0 * 2 ** attempt, 60.0))
            continue
        return None, status, attempts, last
    return None, status, attempts, last


def api_rows(session, pacer, code, a, b):
    """Every row of one scrip/year window (50 per page until a short page)."""
    rows, page = [], 1
    while page <= 200:
        url = ANN_URL.format(p=page, f=a.strftime("%Y%m%d"), c=code, t=b.strftime("%Y%m%d"))
        payload, status, _n, error = http_get(session, url, pacer, want_json=True)
        if payload is None and status == 400 and (b - a).days > 14:
            # T-130: the API refuses deep pages (PERSISTENT 2024 at page 6) and some whole years (INDHOTEL 2024 at page 1):
            # fetch the window again as two halves, each shallow enough
            mid = a + (b - a) / 2
            logger.info("%s %s/%s: page %d refused, splitting at %s", code, a, b, page, mid)
            return api_rows(session, pacer, code, a, mid) + api_rows(session, pacer, code, mid + timedelta(days=1), b)
        if payload is None:
            raise RuntimeError(f"{code} {a}/{b} page {page}: {error or status}")
        table = payload.get("Table") or []
        rows.extend(table)
        if len(table) < PAGE:
            return rows
        page += 1
    return rows


def metadata(universe, resolved, symbols_at, pacer, refresh=False):
    """Deduped metadata rows for the window, from the local DB feed and the BSE API."""
    by_newsid = {}

    def add(row, origin):
        newsid = str(row.get("newsid") or "").strip()
        if not newsid or newsid in by_newsid:
            return
        ts = parse_ts(row.get("dissem_ts"))
        if not in_window(ts):
            return
        row = dict(row, newsid=newsid, dissem_ts=ts, source=origin)
        by_newsid[newsid] = row

    conn = connect_ro(DATA_ROOT / "bse_announcements.db", timeout_s=180)
    codes = sorted({r["code"] for r in resolved.values()})
    marks = ",".join("?" * len(codes))
    for newsid, code, attach, newssub, headline, cat, subcat, dt_tm, dissem, atype in _query(
            conn, "SELECT NEWSID, SCRIP_CD, ATTACHMENTNAME, NEWSSUB, HEADLINE, CATEGORYNAME, "
                  f"SUBCATNAME, DT_TM, DissemDT, ANNOUNCEMENT_TYPE FROM ann "
                  f"WHERE SCRIP_CD IN ({marks}) AND DissemDT >= ? AND DissemDT < ?",
            codes + [WINDOW_START.isoformat(), WINDOW_END.isoformat()]):
        add({"newsid": newsid, "code": str(code), "attachment": attach, "newssub": newssub,
             "headline": clean(headline), "category": cat, "subcat": subcat,
             "dt_tm": dt_tm, "dissem_ts": dissem, "ann_type": atype}, "bse_ann")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    session = new_session()
    for sym, info in sorted(resolved.items()):
        for a, b in year_windows():
            cache = CACHE_DIR / f"{info['code']}_{a.year}.json"
            if cache.exists() and not refresh:
                table = json.loads(cache.read_text(encoding="utf-8"))
            else:
                table = api_rows(session, pacer, info["code"], a, b)
                cache.write_text(json.dumps(table), encoding="utf-8")
            for raw in table:
                add({"newsid": raw.get("NEWSID"), "code": str(raw.get("SCRIP_CD") or info["code"]),
                     "attachment": raw.get("ATTACHMENTNAME"), "newssub": raw.get("NEWSSUB"),
                     "headline": clean(raw.get("HEADLINE")), "category": raw.get("CATEGORYNAME"),
                     "subcat": raw.get("SUBCATNAME"), "dt_tm": raw.get("DT_TM"),
                     "dissem_ts": raw.get("DissemDT"), "ann_type": raw.get("ANNOUNCEMENT_TYPE")},
                    "bse_api")
        logger.info("metadata %s: %d rows so far", sym, len(by_newsid))

    code_to_symbol = {info["code"]: sym for sym, info in resolved.items()}
    for row in by_newsid.values():
        row["symbol"] = code_to_symbol.get(str(row.get("code")), "")
        if not row["symbol"]:
            continue
        row["isin"] = resolved[row["symbol"]]["isin"]
        row["symbol_at_time"] = symbol_at(row["symbol"], symbols_at, row["dissem_ts"])
    return {k: v for k, v in by_newsid.items() if v.get("symbol")}


def nse_metadata(universe_rows, symbols, pacer, refresh=False):
    """NSE corporate announcements for names the BSE feed cannot serve.

    Only for pilot names with no BSE scrip code (NSE-only / SME). NSE already
    resolves the attachment URL, so the row carries ``url_direct``.
    """
    import curl_cffi.requests as cr
    from reality_engine.config import NSE_HEADERS

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    session = cr.Session(impersonate="chrome120", verify=False)
    try:
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=30)
    except Exception:  # warm-up is best effort
        pass
    out = {}
    for row in universe_rows:
        sym = row["symbol"]
        if sym not in symbols:
            continue
        cache = CACHE_DIR / f"nse_{sym}.json"
        if cache.exists() and not refresh:
            table = json.loads(cache.read_text(encoding="utf-8"))
        else:
            url = ("https://www.nseindia.com/api/corporate-announcements"
                   f"?index=equities&symbol={sym}"
                   f"&from_date={WINDOW_START:%d-%m-%Y}&to_date={WINDOW_END - timedelta(days=1):%d-%m-%Y}")
            body, status, _n, error = http_get(session, url, pacer, want_json=True)
            if isinstance(body, dict):
                body = body.get("data") or []
            if not isinstance(body, list):
                logger.warning("NSE metadata %s failed: %s", sym, error or status)
                body = []
            cache.write_text(json.dumps(body), encoding="utf-8")
            table = body
        for raw in table:
            ts = parse_ts(raw.get("sort_date") or raw.get("an_dt"))
            seq = str(raw.get("seq_id") or "").strip()
            url = str(raw.get("attchmntFile") or "").strip()
            if url in ("", "-"):  # NSE text-only announcement, no attachment
                url = ""
            if not (seq and in_window(ts)):
                continue
            headline = clean(raw.get("attchmntText") or raw.get("desc"))
            out["nse:" + seq] = {
                "newsid": "nse:" + seq, "code": "", "attachment": None,
                "newssub": "", "headline": headline, "category": "",
                "subcat": clean(raw.get("desc")), "dt_tm": ts, "dissem_ts": ts,
                "ann_type": "", "url": url, "url_direct": bool(url), "source": "nse",
                "symbol": sym, "isin": row["isin"], "symbol_at_time": sym,
            }
        logger.info("NSE metadata %s: %d rows so far", sym, len(out))
    return out


def plan(metadata_rows, symbol_to_code):
    """(bucket, skip) for every metadata row, sorted so AR/results land first."""
    jobs = []
    for row in metadata_rows.values():
        bucket, reason = classify(row)
        row = dict(row, bucket=bucket, skip_reason=reason,
                   code=symbol_to_code.get(row["symbol"], row.get("code")))
        if not row.get("url_direct"):
            row["url"] = (PDF_URLS[0].format(name=row["attachment"])
                          if row.get("attachment") else "")
        jobs.append(row)
    jobs.sort(key=lambda r: (BUCKET_ORDER.get(r["bucket"], 9),
                             0 if r.get("skip_reason") else 1,
                             r["dissem_ts"] or "", r["newsid"]))
    return jobs


# --------------------------------------------------------------- existing files
def existing_index():
    """BSE attachment name / NEWSID -> local file already on disk (read-only stores)."""
    by_name, by_id = {}, {}
    try:
        con = connect_ro(DATA_ROOT / "equity_intelligence.db", timeout_s=180)
        for url, path, newsid in _query(
                con, "SELECT source_url, local_file_path, bse_newsid FROM corporate_documents "
                     "WHERE local_file_path IS NOT NULL AND source_url LIKE '%Pname=%'"):
            name = re.sub(r".*Pname=", "", url or "").split("&")[0]
            if name and path and Path(path).exists():
                by_name.setdefault(name.lower(), path)
                if newsid:
                    by_id.setdefault(str(newsid), path)
    except sqlite3.Error as exc:
        logger.warning("existing index (corporate_documents) unavailable: %s", exc)
    try:
        con = connect_ro(DATA_ROOT / "deck_figures.db", timeout_s=180)
        for newsid, path in _query(
                con, "SELECT source_id, local_path FROM deck_sources "
                     "WHERE source='bse' AND local_path IS NOT NULL"):
            if path and Path(path).exists():
                by_id.setdefault(str(newsid), path)
    except sqlite3.Error as exc:
        logger.warning("existing index (deck_sources) unavailable: %s", exc)
    return by_name, by_id


def is_pdf_file(path):
    try:
        with Path(path).open("rb") as f:
            return f.read(4) == PDF_MAGIC
    except OSError:
        return False


# ------------------------------------------------------------------- manifest
class Manifest:
    def __init__(self, path=MANIFEST_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        self.con = sqlite3.connect(str(path), timeout=120, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")  # one fsync per transaction is not worth it
        self.con.execute(SCHEMA)
        self.con.execute("CREATE INDEX IF NOT EXISTS ix_docs_bucket ON docs(bucket, status)")
        self.con.commit()

    def done(self):
        out = {}
        for newsid, status, path, attempts in self.con.execute(
                "SELECT newsid, status, local_path, attempts FROM docs"):
            out[newsid] = (status, path, attempts or 0)
        return out

    def put(self, row):
        cols = [c for c in FIELDS if c in row]
        values = [row[c] for c in cols]
        with self.lock:
            self.con.execute(
                f"INSERT OR REPLACE INTO docs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                values)
            self.con.commit()

    def put_many(self, rows):
        """One transaction for bulk inserts (30k pending rows at the start of a run)."""
        if not rows:
            return
        with self.lock:
            self.con.executemany(
                f"INSERT OR REPLACE INTO docs({','.join(FIELDS)}) VALUES({','.join('?' * len(FIELDS))})",
                [[r.get(c) for c in FIELDS] for r in rows])
            self.con.commit()

    def rows(self):
        cur = self.con.execute(f"SELECT {','.join(FIELDS)} FROM docs")
        return [dict(zip(FIELDS, r)) for r in cur]

    def write_csv(self, path=MANIFEST_CSV):
        rows = sorted(self.rows(), key=lambda r: (r["symbol_at_time"] or "",
                                                  r["dissem_ts"] or "", r["newsid"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".csv.part")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)
        return len(rows)


# ------------------------------------------------------------------ downloader
def target_path(symbol, bucket, newsid):
    # ":" is an NTFS alternate-data-stream separator, so an NSE "nse:123" id must be
    # sanitised or write_bytes() silently writes a stream instead of a file.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(newsid))
    return ROOT / symbol / bucket / f"{safe}.pdf"


def download(row, session, pacer, tries=4):
    """(status, body, http_status, attempts, error) for one metadata row."""
    if row.get("url_direct"):
        templates = [row["url"]]
    elif row.get("attachment"):
        templates = [t.format(name=row["attachment"]) for t in PDF_URLS]
    else:
        return "no_file", None, None, 0, "no attachment (text-only announcement)"
    attempts, last, status = 0, None, None
    for url in templates:
        body, status, n, error = http_get(session, url, pacer, tries=tries)
        attempts += n
        row["url"] = url
        if body is not None:
            if body.startswith(PDF_MAGIC):
                return "ok", body, status, attempts, None
            if body.startswith(b"PK"):  # NSE results XBRL package, already in results_xbrl
                return "no_file", None, status, attempts, "attachment is a ZIP (XBRL package), not a PDF"
            return "error", None, status, attempts, f"not a PDF ({body[:16]!r})"
        last = error
        if status != 404:
            break
    return "error", None, status, attempts, last


def fetch_rows(jobs, manifest, workers=8, interval=0.3, tries=4, limit=0):
    """Download every planned row, resuming from the manifest. Returns counts."""
    done = manifest.done()
    by_name, by_id = existing_index()
    todo = []
    reused = already = skipped = 0
    pending = []
    skip_rows = []
    for row in jobs:
        newsid = row["newsid"]
        status, path, _attempts = done.get(newsid, (None, None, 0))
        if status is None:
            # Every listed metadata row gets a manifest row at once, so the coverage
            # matrix can distinguish "not listed" from "listed, not fetched yet".
            pending.append(_record(row, "pending"))
        if status == "ok" and path and is_pdf_file(path):
            already += 1
            continue
        if status == "no_file" and not (row.get("attachment") or row.get("url_direct")):
            already += 1
            continue
        if row["skip_reason"]:
            skip_rows.append(_record(row, "skipped", skip=row["skip_reason"]))
            skipped += 1
            continue
        held = by_id.get(newsid) or by_name.get(str(row.get("attachment") or "").lower())
        if held and is_pdf_file(held):
            dest = target_path(row["symbol_at_time"], row["bucket"], newsid)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    try:
                        os.link(held, dest)
                    except OSError:
                        import shutil
                        shutil.copy2(held, dest)
                manifest.put(_record(row, "ok", local_path=dest, bytes=dest.stat().st_size,
                                     sha=hashlib.sha256(dest.read_bytes()).hexdigest(),
                                     source="existing_raw"))
                reused += 1
                continue
            except OSError as exc:
                logger.warning("reuse failed for %s: %s", newsid, exc)
        row['_prev_attempts'] = _attempts or 0
        todo.append(row)
    manifest.put_many(pending + skip_rows)
    if limit:
        todo = todo[:limit]
    logger.info("resume: %d already ok, %d routine skips, %d reused from disk, %d to fetch",
                already, skipped, reused, len(todo))
    if not todo:
        return {"ok": 0, "reused": reused, "skipped": skipped, "error": 0, "already": already}

    pacer = Pacer(interval)
    stats = {"ok": 0, "reused": reused, "skipped": skipped, "error": 0, "already": already}
    local = threading.local()
    counts_lock = threading.Lock()
    stop = threading.Event()

    def one(row):
        if stop.is_set():
            return None
        if getattr(local, "session", None) is None:
            local.session = new_session()
        status, body, http_status, attempts, error = download(row, local.session, pacer, tries)
        if status == "ok":
            dest = target_path(row["symbol_at_time"], row["bucket"], row["newsid"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            record = _record(row, "ok", http_status=http_status, attempts=attempts,
                             local_path=dest, bytes=len(body),
                             sha=hashlib.sha256(body).hexdigest(), is_pdf=1)
        else:
            record = _record(row, status, http_status=http_status,
                             attempts=attempts + row.get('_prev_attempts', 0),
                             error=error, is_pdf=0)
        manifest.put(record)
        with counts_lock:
            stats[record["status"]] = stats.get(record["status"], 0) + 1
            n = stats["ok"] + stats["error"]
            if n % 100 == 0:
                logger.info("progress: ok %d, error %d", stats["ok"], stats["error"])
            if n % 200 == 0 and free_bytes(ROOT) < MIN_FREE_BYTES:
                logger.critical("D: is below %d GB free - stopping; re-run to resume",
                                MIN_FREE_BYTES // 1024 ** 3)
                stop.set()
        return record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    if stop.is_set():
        stats["stopped_low_disk"] = 1
    return stats


def _record(row, status, http_status=None, attempts=0, local_path=None, bytes=None,
            sha=None, error=None, source=None, is_pdf=1, skip=None):
    return {
        "isin": row.get("isin"), "symbol_at_time": row.get("symbol_at_time"),
        "scrip_code": str(row.get("code") or ""), "newsid": row["newsid"],
        "bucket": row.get("bucket"), "headline": row.get("headline"),
        "category": row.get("category"), "subcat": row.get("subcat"),
        "dissem_ts": row.get("dissem_ts"), "url": row.get("url"),
        "source": source or row.get("source"), "local_path": str(local_path) if local_path else None,
        "bytes": bytes, "sha256": sha, "http_status": http_status, "attempts": attempts,
        "is_pdf": is_pdf, "is_scanned_guess": None, "skip_reason": skip or row.get("skip_reason"),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "status": status, "error": error,
    }


# ---------------------------------------------------------------- scanned guess
def scan_pass(manifest, limit=0):
    import fitz  # PyMuPDF

    rows = [r for r in manifest.rows()
            if r["status"] == "ok" and r.get("is_scanned_guess") is None and r.get("local_path")]
    if limit:
        rows = rows[:limit]
    n_scanned = 0
    for i, row in enumerate(rows, 1):
        try:
            with fitz.open(row["local_path"]) as doc:
                text = (doc[0].get_text() if doc.page_count else "") or ""
            guess = 1 if len(text.strip()) < 40 else 0
            row["is_scanned_guess"] = guess
            n_scanned += guess
            manifest.put(row)
        except Exception as exc:  # noqa: BLE001 - a broken PDF must not stop the pass
            logger.warning("scan failed %s: %s", row["local_path"], exc)
        if i % 500 == 0:
            logger.info("scan %d/%d (scanned guess %d)", i, len(rows), n_scanned)
    return {"examined": len(rows), "scanned_guess": n_scanned}


# --------------------------------------------------------------------- checks
STOPWORDS = {
    "limited", "ltd", "the", "and", "company", "private", "india", "annual", "report",
    "financial", "results", "announcement", "intimation", "pursuant", "regulation",
    "sebi", "listing", "obligations", "disclosure", "requirements", "2015", "board",
    "meeting", "this", "that", "has", "have", "will", "are", "was", "were", "been",
    "under", "with", "from", "for", "herewith", "enclosed", "please", "find", "attached",
}


def _tokens(text, min_len=4):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) >= min_len and w not in STOPWORDS}


def verify_files(manifest, resolved, sample=40, seed=20261030, out_path=None):
    """Open random held PDFs and check the company/headline and the timestamp.

    ``dissem_ts`` is cross-checked against the local ``ann`` row for the same
    NEWSID where one exists (the local feed starts 2020-01-01).
    """
    import random

    import fitz

    rows = [r for r in manifest.rows() if r["status"] == "ok" and r.get("local_path")]
    rows.sort(key=lambda r: r["newsid"])
    picked = random.Random(seed).sample(rows, min(sample, len(rows)))
    bse_ts = {}
    ids = [r["newsid"] for r in picked if not str(r["newsid"]).startswith("nse:")]
    if ids:
        try:
            con = connect_ro(DATA_ROOT / "bse_announcements.db", timeout_s=120)
            marks = ",".join("?" * len(ids))
            bse_ts = {newsid: parse_ts(dt) for newsid, dt in _query(
                con, f"SELECT NEWSID, DissemDT FROM ann WHERE NEWSID IN ({marks})", ids)}
        except sqlite3.Error as exc:
            logger.warning("ann timestamp lookup failed: %s", exc)
    results = []
    for row in picked:
        text, pages = "", 0
        try:
            with fitz.open(row["local_path"]) as doc:
                pages = doc.page_count
                text = "\n".join(doc[i].get_text() for i in range(min(3, pages)))
        except Exception as exc:  # noqa: BLE001 - a broken file is a finding
            results.append({"row": row, "verdict": f"unreadable: {exc}", "pages": 0})
            continue
        body = set(re.findall(r"[a-z0-9]+", text.lower()))
        name = (resolved.get(row["symbol_at_time"]) or {}).get("name") or ""
        company = _tokens(name, 3) | _tokens(row["symbol_at_time"])
        sym = (row["symbol_at_time"] or "").lower()
        code = str(row.get("scrip_code") or "")
        # The BSE scrip code is printed in most filing letters and is the strongest
        # company signal when the NSE symbol (e.g. HEGAM) differs from the brand (HEG).
        company_hit = (bool(company & body) or (len(sym) >= 3 and sym[:3] in text.lower())
                       or (len(code) >= 4 and code in text))
        headline_tokens = _tokens(row["headline"])
        headline_hit = bool(headline_tokens & body) if headline_tokens else None
        if len(text.strip()) < 40:
            verdict = "no text layer (scanned?)"
        elif headline_hit is None:
            verdict = "ok" if company_hit else "headline has no keywords; company not in text"
        elif company_hit and headline_hit:
            verdict = "ok"
        elif company_hit:
            verdict = "headline not in text"
        elif headline_hit:
            verdict = "company not in text"
        else:
            verdict = "MISMATCH: neither company nor headline"
        if row["newsid"] in bse_ts:
            ts_match = "yes" if bse_ts[row["newsid"]] == row["dissem_ts"] else "NO"
        elif str(row["newsid"]).startswith("nse:"):
            ts_match = "n/a (nse)"
        else:
            ts_match = "n/a (not in local feed)"
        results.append({"row": row, "verdict": verdict, "pages": pages,
                        "chars": len(text), "company": company_hit, "headline": headline_hit,
                        "ts_match": ts_match})

    lines = ["# Pilot-60 history: 40-file content check", "",
             f"Seed {seed}, {len(results)} files, drawn from `{MANIFEST_DB}`.", "",
             "| company | bucket | newsid | diss_ts vs BSE | pages | chars | company | headline | verdict |",
             "|---|---|---|---|---|---|---|---|---|"]
    bad = 0
    for r in results:
        row = r["row"]
        if r["verdict"] not in ("ok", "no text layer (scanned?)") or r["ts_match"] == "NO":
            bad += 1
        lines.append(f"| {row['symbol_at_time']} | {row['bucket']} | {row['newsid']} | "
                     f"{r['ts_match']} | {r.get('pages')} | {r.get('chars', 0)} | "
                     f"{r.get('company')} | {r.get('headline')} | {r['verdict']} |")
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    lines += ["", f"Verdicts: {counts}", ""]
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"checked": len(results), "flagged": bad, "verdicts": counts}


# -------------------------------------------------------------------- coverage
MATRIX_BUCKETS = BUCKETS


def fiscal_window():
    """(first FY, last FY) the fetch window touches; FY = the calendar year it ends in."""
    first = WINDOW_START.year + (1 if WINDOW_START.month >= 4 else 0)
    last = WINDOW_END - timedelta(days=1)
    return first, last.year + (1 if last.month >= 4 else 0)


def coverage(manifest, out_path, universe=None):
    rows = manifest.rows()
    universe = universe if universe is not None else load_universe()
    symbols = [r["symbol"] for r in universe]
    fy_start, fy_end = fiscal_window()
    held = {b: {s: {fy: 0 for fy in range(fy_start, fy_end + 1)} for s in symbols}
            for b in MATRIX_BUCKETS}
    planned = {b: {s: {fy: set() for fy in range(fy_start, fy_end + 1)} for s in symbols}
               for b in MATRIX_BUCKETS}
    errors = {}
    no_file = set()
    for row in rows:
        sym = row["symbol_at_time"] or ""
        if sym not in held["annual_report"]:
            continue
        bucket = row["bucket"]
        if bucket not in held or not row["dissem_ts"]:
            continue
        fy = fiscal_year(row["dissem_ts"], bucket, row["headline"] or "")
        if fy not in held[bucket][sym]:
            continue
        planned[bucket][sym][fy].add(row["newsid"])
        if row["status"] == "ok" and row.get("local_path") and is_pdf_file(row["local_path"]):
            held[bucket][sym][fy] += 1
        elif row["status"] == "error":
            errors.setdefault((sym, bucket, fy), []).append(
                f"{row['newsid']}: {row.get('error')} (attempts {row.get('attempts')})")
        elif row["status"] == "no_file":
            no_file.add((sym, bucket, fy))

    def pct(n, d):
        return f"{n}/{d}" if d else "0/0"

    lines = [f"# {out_path.stem}: document coverage "
             f"({WINDOW_START} .. {WINDOW_END - timedelta(days=1)} filing window)", "",
             f"Generated {datetime.now().isoformat(timespec='seconds')} from "
             f"`{MANIFEST_DB}`.", "",
             "FY = the fiscal year the filing belongs to (FY ends in March). Annual reports use the",
             "2022-23 label in the headline when present; quarterly results are inferred from the",
             "filing month (Q4 Apr-Jun, Q1 Jul-Sep, Q2 Oct-Dec, Q3 Jan-Mar); other buckets use the",
             "fiscal year in which the filing was made. A cell is held/listed; empty cells are",
             "broken down below.", ""]
    fys = list(range(fy_start, fy_end + 1))
    for bucket in MATRIX_BUCKETS:
        lines += [f"## {bucket}", "",
                  "| company | " + " | ".join(f"FY{fy % 100:02d}" for fy in fys) + " | total |",
                  "|---|" + "---|" * (len(fys) + 1)]
        for sym in symbols:
            cells = [pct(held[bucket][sym][fy], len(planned[bucket][sym][fy])) for fy in fys]
            total = sum(held[bucket][sym][fy] for fy in fys)
            lines.append(f"| {sym} | " + " | ".join(cells) + f" | {total} |")
        lines.append("")

    lines += ["## Empty annual-report / quarterly-results cells", ""]
    for bucket in ("annual_report", "quarterly_results"):
        lines += [f"### {bucket}", "",
                  "| company | FY | held/listed | reason |", "|---|---|---|---|"]
        for sym in symbols:
            for fy in fys:
                n = held[bucket][sym][fy]
                if n:
                    continue
                listed = len(planned[bucket][sym][fy])
                if not listed:
                    reason = "not listed in the announcement feed for this window"
                elif (sym, bucket, fy) in errors:
                    reason = "fetch failed: " + "; ".join(errors[(sym, bucket, fy)][:2])
                elif (sym, bucket, fy) in no_file:
                    reason = "listed as a text-only announcement (no attachment)"
                else:
                    reason = "listed but no file held"
                lines.append(f"| {sym} | FY{fy % 100:02d} | 0/{listed} | {reason} |")
        lines.append("")

    failures = [r for r in rows if r["status"] == "error"]
    skipped = [r for r in rows if r["status"] == "skipped"]
    text_only = [r for r in rows if r["status"] == "no_file"]
    pending = [r for r in rows if r["status"] == "pending"]
    by_reason = {}
    for r in failures:
        key = (r.get("error") or "")[:60]
        by_reason[key] = by_reason.get(key, 0) + 1
    lines += [f"## Status totals", "",
              f"- held: {sum(1 for r in rows if r['status'] == 'ok')}",
              f"- routine skips: {len(skipped)}",
              f"- text-only announcements (no attachment): {len(text_only)}",
              f"- fetch failures: {len(failures)}",
              f"- still pending: {len(pending)}", "",
              "### Failures by reason", "", "| reason | count |", "|---|---|"]
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {reason} | {n} |")
    lines += ["", f"## Failures ({len(failures)})", ""]
    if failures:
        lines += ["| company | bucket | newsid | diss_ts | http | attempts | error |",
                  "|---|---|---|---|---|---|---|"]
        for r in sorted(failures, key=lambda x: (x["symbol_at_time"] or "", x["dissem_ts"] or "")):
            lines.append(f"| {r['symbol_at_time']} | {r['bucket']} | {r['newsid']} | "
                         f"{r['dissem_ts']} | {r.get('http_status')} | {r.get('attempts')} | "
                         f"{(r.get('error') or '').replace('|', '/')[:120]} |")
    else:
        lines.append("None.")
    lines += ["", f"## Routine skips ({len(skipped)})", "",
              "| SUBCATNAME | reason | count |", "|---|---|---|"]
    counts = {}
    for r in skipped:
        counts[(r.get("subcat") or "", r.get("skip_reason") or "")] = \
            counts.get((r.get("subcat") or "", r.get("skip_reason") or ""), 0) + 1
    for (subcat, reason), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {subcat} | {reason} | {n} |")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"rows": len(rows), "failures": len(failures), "skipped": len(skipped)}


# ------------------------------------------------------------------------ main
def setup_logging(log_path=None):
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)


def main(argv=None):
    global WINDOW_START, WINDOW_END
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measure", action="store_true", help="metadata only; no downloads")
    ap.add_argument("--fetch", action="store_true", help="download attachments (resumable)")
    ap.add_argument("--scan", action="store_true", help="set is_scanned_guess for held PDFs")
    ap.add_argument("--coverage", action="store_true", help="write the coverage matrix markdown")
    ap.add_argument("--nse-fallback", action="store_true",
                    help="also list NSE announcements for names with no BSE feed")
    ap.add_argument("--verify", type=int, default=0,
                    help="open N random held PDFs and write the content check markdown")
    ap.add_argument("--universe", default=str(UNIVERSE_CSV),
                    help="universe CSV (default: tasks/pilot60/UNIVERSE.csv)")
    ap.add_argument("--window-start", default=WINDOW_START.isoformat())
    ap.add_argument("--window-end", default=WINDOW_END.isoformat(),
                    help="exclusive end date (default 2024-04-01)")
    ap.add_argument("--symbols", default="", help="comma list to limit the run")
    ap.add_argument("--limit", type=int, default=0, help="download at most N rows")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--interval", type=float, default=0.3,
                    help="seconds between BSE requests overall (0.3 = 200/min)")
    ap.add_argument("--tries", type=int, default=4)
    ap.add_argument("--refresh-meta", action="store_true", help="ignore the .tmp metadata cache")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "tasks" / "pilot60" /
                                         "HISTORY_COVERAGE_2026-10-30.md"))
    args = ap.parse_args(argv)
    setup_logging(LOG_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.log" if args.fetch else None)

    WINDOW_START = date.fromisoformat(args.window_start)
    WINDOW_END = date.fromisoformat(args.window_end)
    universe = load_universe(Path(args.universe))
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        universe = [r for r in universe if r["symbol"].upper() in wanted]
    resolved, conn = resolve(universe)
    if len(resolved) < len(universe):
        missing = [r["symbol"] for r in universe if r["symbol"] not in resolved]
        logger.warning("%d names without a BSE scrip code: %s", len(missing), ", ".join(missing))
    symbols_at = symbol_windows(conn, list(resolved))
    pacer = Pacer(args.interval)
    rows = metadata(universe, resolved, symbols_at, pacer, refresh=args.refresh_meta)
    if args.nse_fallback:
        bse_done = {row["symbol"] for row in rows.values()}
        nse_syms = {r["symbol"] for r in universe if r["symbol"] not in bse_done}
        if nse_syms:
            logger.info("NSE fallback for %d names: %s", len(nse_syms), ", ".join(sorted(nse_syms)))
            rows.update(nse_metadata(universe, nse_syms, pacer, refresh=args.refresh_meta))
    jobs = plan(rows, {s: i["code"] for s, i in resolved.items()})

    if args.measure:
        by_bucket, by_year, subcats = {}, {}, {}
        skips = {}
        for row in jobs:
            by_bucket[row["bucket"]] = by_bucket.get(row["bucket"], 0) + 1
            year = date.fromisoformat(row["dissem_ts"][:10]).year
            by_year[year] = by_year.get(year, 0) + 1
            subcats[row["subcat"] or ""] = subcats.get(row["subcat"] or "", 0) + 1
            if row["skip_reason"]:
                skips[row["skip_reason"]] = skips.get(row["skip_reason"], 0) + 1
        print(json.dumps({"rows": len(jobs), "by_bucket": by_bucket, "by_year": by_year,
                          "skip_reasons": skips,
                          "top_subcats": dict(sorted(subcats.items(),
                                                     key=lambda kv: -kv[1])[:60])},
                         indent=2))
        return 0

    manifest = Manifest()
    if args.verify:
        out = PROJECT_ROOT / "tasks" / "pilot60" / "HISTORY_CHECK40_2026-10-30.md"
        logger.info("verify: %s", verify_files(manifest, resolved, sample=args.verify,
                                               out_path=out))
        return 0
    if args.fetch:
        stats = fetch_rows(jobs, manifest, workers=args.workers, interval=args.interval,
                           tries=args.tries, limit=args.limit)
        n = manifest.write_csv()
        logger.info("fetch done: %s; manifest rows %d", stats, n)
        if not args.limit:
            scan_pass(manifest)
            manifest.write_csv()
    if args.scan and not args.fetch:
        logger.info("scan: %s", scan_pass(manifest))
    if args.coverage:
        logger.info("coverage: %s", coverage(manifest, Path(args.out), universe))
        manifest.write_csv()
    if not (args.fetch or args.scan or args.coverage or args.measure):
        ap.error("pick one of --measure, --fetch, --scan, --coverage, --verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
