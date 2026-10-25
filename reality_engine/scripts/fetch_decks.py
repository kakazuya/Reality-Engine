"""
Download historical investor-presentation PDFs (2021 onwards) from BSE and, for companies listed only on NSE,
from NSE. Files go to ``RAW_ROOT/decks/{bse,nse}/``; every file is recorded in the ``deck_sources``
table of ``reality_engine/data/deck_figures.db`` with the exchange dissemination time, so the deck extractor
(``extract_deck_figures.py``) can read them point-in-time. The live DB is only read, never written.

BSE: candidates come from the harvested announcement feed (``analysis/bse_announcements.db``): sub-category
"Investor Presentation" (23,609 filings 2021-01 -> 2026-09), plus "Analyst / Investor Meet" filings whose subject
mentions a presentation (1,069). PDFs are served from ``xml-data/corpfiling/AttachHis/<ATTACHMENTNAME>`` (old and
new; AttachLive 404s on older files). Files already on disk via ``corporate_documents`` are reused, not refetched.

NSE: NSE has no presentation category; decks are filed as "General Updates" / investor-meet updates and are
recognisable only by the attachment text or file name. For each NSE-only company (no BSE ISIN in the truth
snapshot: 733 on 2026-10-08, 131 main board + 578 SME) the full announcement list 2021 -> today is pulled
(raw JSON kept under ``raw_market/nse_announcements/``), filtered by keyword and size (>= 0.3 MB), and downloaded.

Resumable: rows already 'ok' in deck_sources are skipped. BSE/Akamai answers 403 when pushed; every worker then
waits out a 10-minute penalty box.

Usage:
    python -m reality_engine.scripts.fetch_decks bse  [--since 2021-01-01] [--workers 4] [--limit N]
    python -m reality_engine.scripts.fetch_decks nse  [--since 2021-01-01] [--limit N]
    python -m reality_engine.scripts.fetch_decks status
"""

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from reality_engine.config import raw_dir
from reality_engine.raw_store import store_bytes

import duckdb
import requests
from curl_cffi import requests as cr

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
FEED = ROOT / "analysis" / "bse_announcements.db"
LIVE_DB = DATA / "equity_intelligence.db"
OUT_DB = DATA / "deck_figures.db"
SNAPSHOT = DATA / "snapshots" / "truth_2026-10-08.duckdb"
DECKS = raw_dir("decks")
NSE_RAW = raw_dir("raw_market") / "nse_announcements"
LOG = DATA / "logs" / "fetch_decks.log"

BSE_PDF = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"
BSE_H = {"Referer": "https://www.bseindia.com/"}
NSE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NSE_API = "https://www.nseindia.com/api/corporate-announcements?index={idx}&symbol={sym}&from_date={a}&to_date={b}"
NSE_PACE = 1.5
PENALTY_SEC = 600

# NSE filings that are decks: the attachment text or file name says presentation / investor update.
NSE_DECK = re.compile(r"presentation|investor[s]?\s*update|earnings\s*update|quarterly\s*update|investor[_\s]*deck", re.I)
NSE_NOT_DECK = re.compile(r"transcript|audio|recording|newspaper|schedule of", re.I)
NSE_MIN_MB = 0.3

log = logging.getLogger("fetch_decks")

SCHEMA = """
CREATE TABLE IF NOT EXISTS deck_sources (
  source TEXT, source_id TEXT, symbol TEXT, isin TEXT, exch_code TEXT, known_at TEXT, title TEXT, url TEXT,
  local_path TEXT, sha256 TEXT, size_bytes INTEGER, status TEXT, error TEXT, fetched_at TEXT,
  PRIMARY KEY (source, source_id));
"""


def out_db():
    con = sqlite3.connect(OUT_DB, check_same_thread=False, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


class Writer:
    """Serialised writes to deck_sources (the extractor writes to the same file from another process)."""

    def __init__(self):
        self.con, self.lock = out_db(), threading.Lock()

    def done(self, source):
        return {r[0] for r in self.con.execute("SELECT source_id FROM deck_sources WHERE source=? AND status='ok'", (source,))}

    def put(self, row):
        with self.lock:
            for attempt in range(10):
                try:
                    self.con.execute("INSERT OR REPLACE INTO deck_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
                    self.con.commit()
                    return
                except sqlite3.OperationalError:   # brief lock while the extractor commits
                    time.sleep(1 + attempt)


def save_pdf(content, path):
    if not content.startswith(b"%PDF"):
        raise ValueError(f"not a PDF ({content[:20]!r})")
    path.parent.mkdir(parents=True, exist_ok=True)
    store_bytes(path, content)
    return hashlib.sha256(content).hexdigest(), len(content)


def isin_maps():
    con = duckdb.connect(str(SNAPSHOT), read_only=True)
    bse = dict(con.sql("SELECT sc_code, arg_max(isin, last_date) FROM bse_code_isin WHERE isin LIKE 'INE%' GROUP BY 1").fetchall())
    nse_only = con.sql("""
        WITH b AS (SELECT DISTINCT substr(isin,1,7) e FROM bse_code_isin WHERE isin LIKE 'INE%')
        SELECT symbol, isin, segment FROM nse_master WHERE isin LIKE 'INE%' AND substr(isin,1,7) NOT IN (SELECT e FROM b)
        ORDER BY symbol""").fetchall()
    con.close()
    return bse, nse_only


# ---------------------------------------------------------------- BSE
def bse_candidates(since):
    c = sqlite3.connect(f"file:{FEED}?mode=ro", uri=True)
    rows = c.execute("""
        SELECT NEWSID, SCRIP_CD, symbol, ATTACHMENTNAME, DissemDT, COALESCE(NEWSSUB, HEADLINE) FROM ann
        WHERE DissemDT >= ? AND ATTACHMENTNAME LIKE '%.pdf' AND (
              SUBCATNAME = 'Investor Presentation'
           OR (SUBCATNAME = 'Analyst / Investor Meet' AND (HEADLINE LIKE '%presentation%' OR NEWSSUB LIKE '%presentation%')))
        ORDER BY DissemDT DESC""", (since,)).fetchall()
    c.close()
    return rows


def existing_bse_files():
    """ATTACHMENTNAME -> local path for decks already downloaded into corporate_documents."""
    c = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True, timeout=60)
    out = {}
    for url, path in c.execute("SELECT source_url, local_file_path FROM corporate_documents WHERE local_file_path IS NOT NULL AND source_url LIKE '%Pname=%'"):
        m = re.search(r"Pname=([^&]+\.pdf)", url or "")
        if m and path and Path(path).exists():
            out[m.group(1)] = path
    c.close()
    return out


class BseDownloader:
    def __init__(self, workers):
        self.local = threading.local()
        self.blocked_until = 0.0
        self.lock = threading.Lock()
        self.workers = workers

    def session(self):
        if getattr(self.local, "s", None) is None:
            for attempt in range(8):
                try:
                    s = cr.Session(impersonate="chrome120")
                    s.get("https://www.bseindia.com/corporates/ann.html", headers=BSE_H, timeout=30)
                    self.local.s = s
                    break
                except Exception:
                    time.sleep(min(15 * (attempt + 1), 120))
        return self.local.s

    def get(self, url):
        for attempt in range(5):
            wait = self.blocked_until - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.session().get(url, headers=BSE_H, timeout=120)
            except Exception as e:
                self.local.s = None; time.sleep(5 * (attempt + 1)); last = str(e); continue
            if r.status_code == 403:
                with self.lock:
                    if self.blocked_until < time.time():
                        self.blocked_until = time.time() + PENALTY_SEC
                        log.warning("BSE 403: pausing all workers %d min", PENALTY_SEC // 60)
                self.local.s = None
                continue
            if r.status_code == 200:
                return r.content
            last = f"HTTP {r.status_code}"
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(last)


def run_bse(since, workers, limit):
    w = Writer(); done = w.done("bse")
    bse_isin, _ = isin_maps(); have = existing_bse_files()
    cands = [r for r in bse_candidates(since) if r[0] not in done]
    if limit:
        cands = cands[:limit]
    log.info("BSE: %d candidate filings to fetch (%d already done, %d reusable from corporate_documents)",
             len(cands), len(done), sum(1 for r in cands if r[3] in have))
    dl = BseDownloader(workers); stats = {"ok": 0, "error": 0, "bytes": 0}; t0 = time.time(); slock = threading.Lock()

    def one(r):
        newsid, code, sym, name, dissem, title = r
        code = str(code); now = datetime.now().isoformat(timespec="seconds"); url = BSE_PDF.format(name=name)
        try:
            if name in have:
                path = Path(have[name]); content = path.read_bytes()
                sha, size = hashlib.sha256(content).hexdigest(), len(content)
            else:
                path = DECKS / "bse" / code / f"{dissem[:10].replace('-', '')}_{name}"
                if path.exists() and path.read_bytes()[:4] == b"%PDF":
                    content = path.read_bytes(); sha, size = hashlib.sha256(content).hexdigest(), len(content)
                else:
                    sha, size = save_pdf(dl.get(url), path)
                    time.sleep(0.15)
            w.put(("bse", newsid, sym, bse_isin.get(code), code, dissem, title, url, str(path), sha, size, "ok", None, now))
            with slock:
                stats["ok"] += 1; stats["bytes"] += size
        except Exception as e:
            w.put(("bse", newsid, sym, bse_isin.get(code), code, dissem, title, url, None, None, None, "error", str(e)[:300], now))
            with slock:
                stats["error"] += 1
        with slock:
            n = stats["ok"] + stats["error"]
            if n % 200 == 0:
                el = time.time() - t0
                log.info("BSE %d/%d (ok %d, error %d) %.1f GB, %.1f files/min, ETA %.0f min", n, len(cands), stats["ok"], stats["error"],
                         stats["bytes"] / 1e9, n / el * 60, (len(cands) - n) / max(n / el, 1e-9) / 60)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, cands))
    log.info("BSE finished: %s", stats)


# ---------------------------------------------------------------- NSE
class NseSession:
    def __init__(self):
        self.s, self.calls = None, 0

    def get(self, url, **kw):
        if self.s is None or self.calls % 150 == 0:
            s = requests.Session()
            s.headers.update({"User-Agent": NSE_UA, "Accept": "application/json,application/pdf,*/*",
                              "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"})
            s.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements", timeout=30)
            time.sleep(NSE_PACE); self.s = s
        self.calls += 1
        for attempt in range(4):
            try:
                r = self.s.get(url, timeout=kw.get("timeout", 60))
                if r.status_code in (401, 403):
                    self.s = None; time.sleep(30 * (attempt + 1)); return self.get(url, **kw) if attempt < 3 else r
                return r
            except requests.RequestException:
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"NSE unreachable: {url}")


def iso_ts(s):
    """NSE '03-Aug-2026 17:56:28' / '2026-08-03 17:56:28' -> '2026-08-03T17:56:28' (IST, same form as BSE DissemDT)."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).isoformat()
        except ValueError:
            pass
    return s


def nse_size_mb(a):
    m = re.match(r"([\d.]+)\s*(KB|MB|GB)", str(a.get("fileSize") or ""), re.I)
    if not m:
        return None
    v = float(m.group(1)); u = m.group(2).upper()
    return v / 1024 if u == "KB" else v * 1024 if u == "GB" else v


def nse_is_deck(a):
    text = f"{a.get('attchmntText') or ''} {a.get('attchmntFile') or ''} {a.get('desc') or ''}"
    size = nse_size_mb(a)
    return (bool(a.get("attchmntFile", "").lower().endswith(".pdf")) and bool(NSE_DECK.search(text))
            and not NSE_NOT_DECK.search(text) and (size is None or size >= NSE_MIN_MB))


def run_nse(since, limit):
    w = Writer(); done = w.done("nse")
    _, nse_only = isin_maps()
    if limit:
        nse_only = nse_only[:limit]
    NSE_RAW.mkdir(parents=True, exist_ok=True)
    s = NseSession(); a = datetime.strptime(since, "%Y-%m-%d").strftime("%d-%m-%Y"); b = date.today().strftime("%d-%m-%Y")
    stats = {"companies": 0, "announcements": 0, "decks": 0, "ok": 0, "error": 0}
    log.info("NSE: %d NSE-only companies", len(nse_only))
    for sym, isin, seg in nse_only:
        raw = NSE_RAW / f"{sym}.json"
        if raw.exists() and time.time() - raw.stat().st_mtime < 7 * 86400:
            ann = json.loads(raw.read_text(encoding="utf-8"))
        else:
            idx = "sme" if seg == "SME" else "equities"
            r = s.get(NSE_API.format(idx=idx, sym=requests.utils.quote(sym), a=a, b=b))
            time.sleep(NSE_PACE)
            try:
                ann = r.json() if r.status_code == 200 else []
            except ValueError:
                ann = []
            if not ann and idx == "equities":   # some companies moved board; try the other index once
                r = s.get(NSE_API.format(idx="sme", sym=requests.utils.quote(sym), a=a, b=b)); time.sleep(NSE_PACE)
                try:
                    ann = r.json() if r.status_code == 200 else []
                except ValueError:
                    ann = []
            raw.write_text(json.dumps(ann), encoding="utf-8")
        stats["companies"] += 1; stats["announcements"] += len(ann)
        for x in ann:
            if not nse_is_deck(x):
                continue
            sid = str(x.get("seq_id") or x.get("attchmntFile"))
            stats["decks"] += 1
            if sid in done:
                continue
            known = iso_ts(x.get("exchdisstime") or x.get("sort_date") or x.get("an_dt"))
            url = x["attchmntFile"]; now = datetime.now().isoformat(timespec="seconds")
            path = DECKS / "nse" / sym / Path(url).name
            try:
                if path.exists() and path.read_bytes()[:4] == b"%PDF":
                    content = path.read_bytes(); sha, size = hashlib.sha256(content).hexdigest(), len(content)
                else:
                    r = s.get(url, timeout=180); time.sleep(0.5)
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")
                    sha, size = save_pdf(r.content, path)
                w.put(("nse", sid, sym, isin, sym, known, x.get("attchmntText"), url, str(path), sha, size, "ok", None, now))
                stats["ok"] += 1
            except Exception as e:
                w.put(("nse", sid, sym, isin, sym, known, x.get("attchmntText"), url, None, None, None, "error", str(e)[:300], now))
                stats["error"] += 1
        if stats["companies"] % 25 == 0:
            log.info("NSE %d/%d companies, %d announcements, %d decks found (ok %d, error %d)", stats["companies"], len(nse_only),
                     stats["announcements"], stats["decks"], stats["ok"], stats["error"])
    log.info("NSE finished: %s", stats)


def status():
    con = out_db()
    for r in con.execute("SELECT source, status, count(*), round(sum(size_bytes)/1e9,2), min(known_at), max(known_at) FROM deck_sources GROUP BY 1,2"):
        print(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["bse", "nse", "status"])
    ap.add_argument("--since", default="2021-01-01")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
    if a.what == "bse":
        run_bse(a.since, a.workers, a.limit)
    elif a.what == "nse":
        run_nse(a.since, a.limit)
    else:
        status()


if __name__ == "__main__":
    main()
