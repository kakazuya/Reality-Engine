"""ETF prices, NAV and premium (PIPELINE_TODO B1, 2026-10-19). Tables in equity_intelligence.db:

  etf_px       (date, symbol, isin, close, volume, value_inr, source): NSE ETF rows (ISIN starting INF, series EQ) from
               the bhavcopy-with-ISIN files in raw_market/nse_cm_isin (Oct 2021 ->, old cm*bhav and UDiFF formats) and
               mkt_nse_eq_daily before that.
  etf_master   (isin, symbol, first_date, last_date, n_days, scheme_code, scheme_name): every ISIN seen in etf_px.
  fund_nav     (isin, date, nav, scheme_code, scheme_name): AMFI NAV history for those ISINs
               (portal.amfiindia.com DownloadNAVHistoryReport_Po.aspx, one calendar month per request, all schemes;
               raw kept gzipped in raw_market/amfi_nav/YYYY-MM.txt.gz). NAV of day d is struck after the close of d
               (published that night): known at the end of day d IST, never before.
  etf_premium  (view: isin, symbol, date, close, nav, premium_pct): close vs the same day's NAV.
  etf_inav     (isin, date, underlying, idx_close, idx_date, fx, k, inav, close, nav, premium_vs_inav_pct):
               international ETFs. Measured 2026-10-19: AMFI NAV dated t uses the underlying index close of the SAME
               date t (k = NAV / (idx x FX) moves a median 0.16%/day aligned that way vs 1.0% with a one-day lag), so
               for US-listed underlyings NAV_t is not knowable at the Indian close. Point-in-time indicative NAV at
               15:30 IST of day t:
                   k_t    = NAV_t / (idx_t x FX_t)                         (units, expenses, cash drag; same-date)
                   iNAV_t = k_{t-1} x idx_{last close dated < t} x FX_t
               Its gap to NAV_t is the underlying's day-t session (not yet traded), not an error. A unit split
               (k jumps > 30%) blanks that day's iNAV. FX_t: Yahoo INR=X close of t (approximation).

    python -m reality_engine.scripts.fetch_etf_nav [--start 2019-01] [--end 2026-10] [--check] [--db PATH]
        [--net-timeout 120] [--net-max-mb 128] [--db-timeout 15]
"""
import argparse
import csv
import datetime as dt
import gzip
import io
import os
import sqlite3
import time
import zipfile
from pathlib import Path
from reality_engine.config import raw_dir

import requests

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "equity_intelligence.db"
RAW = raw_dir("raw_market")
AMFI = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt={a}&todt={b}"
NET_TIMEOUT = 120.0             # total wall-clock cap for ONE response (timeout= is per socket read only)
NET_MAX_BYTES = 128 * 2**20     # one AMFI month is ~18 MB; past this the response is not a NAV report
NET_ATTEMPTS = 4                # one try + 3 retries
DB_TIMEOUT = 15.0               # seconds to wait for the SQLite write lock, then fail with who holds it


class DownloadTooSlow(requests.RequestException):
    """A streamed response outlived its wall-clock or byte cap."""


DDL = """
CREATE TABLE IF NOT EXISTS etf_px (date TEXT, symbol TEXT, isin TEXT, close REAL, volume REAL, value_inr REAL,
    source TEXT, PRIMARY KEY (date, symbol));
CREATE TABLE IF NOT EXISTS etf_master (isin TEXT PRIMARY KEY, symbol TEXT, first_date TEXT, last_date TEXT, n_days INTEGER,
    scheme_code TEXT, scheme_name TEXT);
CREATE TABLE IF NOT EXISTS fund_nav (isin TEXT, date TEXT, nav REAL, scheme_code TEXT, scheme_name TEXT,
    PRIMARY KEY (isin, date));
CREATE TABLE IF NOT EXISTS amfi_months (month TEXT PRIMARY KEY, rows INTEGER, fetched_at TEXT);
"""


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_px(db):
    rows = []
    zips = sorted((RAW / "nse_cm_isin").glob("*.zip"))
    print(f"etf_px: reading {len(zips)} raw zips from {RAW / 'nse_cm_isin'}", flush=True)
    for z in zips:
        try:
            with zipfile.ZipFile(z) as zf:
                text = zf.read(zf.namelist()[0]).decode("utf-8", "replace")
        except (zipfile.BadZipFile, OSError):
            continue
        for r in csv.DictReader(io.StringIO(text)):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if "TckrSymb" in r:     # UDiFF
                isin, sym, ser = r.get("ISIN", ""), r.get("TckrSymb"), r.get("SctySrs")
                d, close, vol, val = r.get("TradDt"), num(r.get("ClsPric")), num(r.get("TtlTradgVol")), num(r.get("TtlTrfVal"))
            else:                   # old cmDDMONYYYYbhav.csv
                isin, sym, ser = r.get("ISIN", ""), r.get("SYMBOL"), r.get("SERIES")
                try:
                    d = dt.datetime.strptime(r.get("TIMESTAMP", ""), "%d-%b-%Y").date().isoformat()
                except ValueError:
                    continue
                close, vol, val = num(r.get("CLOSE")), num(r.get("TOTTRDQTY")), num(r.get("TOTTRDVAL"))
            if isin.startswith("INF") and ser == "EQ":
                rows.append((d, sym, isin, close, vol, val, "nse_cm_isin"))
    rows += db.execute("SELECT date, symbol, isin, close, volume, turnover_inr, 'mkt_nse_eq_daily' FROM mkt_nse_eq_daily "
                       "WHERE isin LIKE 'INF%' AND series = 'EQ'").fetchall()
    with db:
        db.executemany("INSERT OR IGNORE INTO etf_px VALUES (?,?,?,?,?,?,?)", rows)
        db.execute("DELETE FROM etf_master")
        db.execute("INSERT INTO etf_master (isin, symbol, first_date, last_date, n_days) SELECT isin, "
                   "max(symbol), min(date), max(date), count(*) FROM etf_px GROUP BY isin")
    print("etf_px rows", db.execute("SELECT COUNT(*), COUNT(DISTINCT isin), MIN(date), MAX(date) FROM etf_px").fetchone(),
          flush=True)


def fetch(url, total_seconds=NET_TIMEOUT, max_bytes=NET_MAX_BYTES):
    """GET url streaming, so a trickle cannot outlast total_seconds or max_bytes.

    requests' ``timeout=`` is per socket read: a server sending one byte every 29s
    never trips it. The wall clock below is what bounds the call.
    """
    started = time.monotonic()
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=(15, 30))
    try:
        if r.status_code != 200:
            raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
        chunks, size = [], 0
        for chunk in r.iter_content(65536):
            size += len(chunk)
            if size > max_bytes:
                raise DownloadTooSlow(f"response passed {max_bytes // 2**20} MB")
            if time.monotonic() - started > total_seconds:
                raise DownloadTooSlow(f"response passed {total_seconds:.0f}s wall clock at {size // 1024} KB")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        r.close()


def month_file(a, net_timeout=NET_TIMEOUT, max_bytes=NET_MAX_BYTES, attempts=NET_ATTEMPTS):
    month = f"{a:%Y-%m}"
    out = RAW / "amfi_nav" / f"{month}.txt.gz"
    if out.exists() and month < dt.date.today().strftime("%Y-%m"):   # the running month is re-fetched
        print(f"{month}: cached {out.name}", flush=True)
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    b = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    url = AMFI.format(a=a.strftime("%d-%b-%Y"), b=b.strftime("%d-%b-%Y"))
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            body = fetch(url, net_timeout, max_bytes)
            if b"Scheme Code" not in body[:200]:
                raise ValueError(f"not an AMFI NAV report: {body[:60]!r}")
            tmp = out.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(body))
            tmp.replace(out)
            print(f"{month}: {len(body) / 1e6:.1f} MB in {time.monotonic() - started:.0f}s -> {out.name}", flush=True)
            return out
        except (requests.RequestException, ValueError, OSError) as e:
            print(f"{month}: attempt {attempt}/{attempts} failed after {time.monotonic() - started:.0f}s: "
                  f"{type(e).__name__}: {e}", flush=True)
            if attempt < attempts:
                time.sleep(min(5 * 2 ** (attempt - 1), 30))
    print(f"{month}: download failed after {attempts} attempts: {url}", flush=True)
    return None


def load_nav(db, start, end, net_timeout=NET_TIMEOUT, max_bytes=NET_MAX_BYTES):
    etf = {r[0] for r in db.execute("SELECT isin FROM etf_master")}
    a = start
    while a <= end:
        f = month_file(a, net_timeout, max_bytes)
        if f is None:
            print(f"{a:%Y-%m}: download failed", flush=True)
        else:
            rows = []
            for line in gzip.decompress(f.read_bytes()).decode("utf-8", "replace").splitlines():
                p = line.split(";")
                if len(p) < 8:
                    continue
                code, name, isin1, isin2, nav, d = p[0], p[1], p[4].strip(), p[5].strip(), num(p[6]), p[7].strip()
                try:
                    d = dt.datetime.strptime(d, "%d-%b-%Y").date().isoformat()
                except ValueError:
                    continue
                for isin in {isin1, isin2} & etf:
                    if nav:
                        rows.append((isin, d, nav, code, name))
            with db:
                db.executemany("INSERT OR REPLACE INTO fund_nav VALUES (?,?,?,?,?)", rows)
                db.execute("INSERT OR REPLACE INTO amfi_months VALUES (?,?,?)",
                           (f"{a:%Y-%m}", len(rows), dt.datetime.now().isoformat(timespec="seconds")))
            print(f"{a:%Y-%m}: {len(rows)} ETF NAV rows", flush=True)
        a = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    with db:
        db.execute("UPDATE etf_master SET scheme_code = (SELECT max(scheme_code) FROM fund_nav n WHERE n.isin = etf_master.isin), "
                   "scheme_name = (SELECT max(scheme_name) FROM fund_nav n WHERE n.isin = etf_master.isin)")
        db.execute("DROP VIEW IF EXISTS etf_premium")
        db.execute("CREATE VIEW etf_premium AS SELECT p.isin, p.symbol, p.date, p.close, n.nav, "
                   "100.0 * (p.close / n.nav - 1) AS premium_pct, p.value_inr FROM etf_px p "
                   "JOIN fund_nav n ON n.isin = p.isin AND n.date = p.date")


UNDERLYING = [   # AMFI scheme-name pattern -> (Yahoo index, Yahoo FX to INR)
    ("nasdaq q 50|nasdaq q50", "^NXTQ", "INR=X"), ("nasdaq 100|nasdaq-100|nasdaq100", "^NDX", "INR=X"),
    ("fang", "^NYFANG", "INR=X"), ("s&p 500|s&p500", "^GSPC", "INR=X"), ("hang seng(?! tech)", "^HSI", "HKDINR=X"),
    ("nikkei|japan", "^N225", "JPYINR=X"), ("euro stoxx|eurostoxx", "^STOXX50E", "EURINR=X")]


def build_inav(db, net_timeout=NET_TIMEOUT):
    import re
    import yfinance as yf
    etfs = []
    for isin, sym, name in db.execute("SELECT isin, symbol, scheme_name FROM etf_master WHERE scheme_name IS NOT NULL"):
        for pat, idx, fx in UNDERLYING:
            if re.search(pat, name.lower()) and "fund of fund" not in name.lower() and "fof" not in name.lower():
                etfs.append((isin, sym, idx, fx)); break
    need = {x for e in etfs for x in e[2:]}
    series = {}
    for t in need:
        print(f"iNAV: fetching Yahoo series {t}", flush=True)
        d = yf.download(t, start="2018-12-01", progress=False, auto_adjust=False,
                        timeout=min(net_timeout, 60))
        c = d["Close"]
        c = c.iloc[:, 0] if hasattr(c, "columns") else c
        series[t] = sorted((i.date().isoformat(), float(v)) for i, v in c.dropna().items())
        print(f"iNAV: {t} {len(series[t])} closes", flush=True)
    import bisect
    def before(t, day, strict=True):
        s = series[t]; ks = [x[0] for x in s]
        i = bisect.bisect_left(ks, day) - 1 if strict else bisect.bisect_right(ks, day) - 1
        return s[i] if i >= 0 else (None, None)
    db.execute("CREATE TABLE IF NOT EXISTS etf_inav (isin TEXT, date TEXT, underlying TEXT, idx_close REAL, idx_date TEXT, "
               "fx REAL, k REAL, inav REAL, close REAL, nav REAL, premium_vs_inav_pct REAL, PRIMARY KEY (isin, date))")
    out = []
    for isin, sym, idx, fx in etfs:
        rows = db.execute("SELECT p.date, p.close, n.nav FROM etf_px p LEFT JOIN fund_nav n ON n.isin = p.isin "
                          "AND n.date = p.date WHERE p.isin = ? ORDER BY p.date", (isin,)).fetchall()
        k_prev = None
        for d, close, nav in rows:
            idate, iclose = before(idx, d)                    # last close dated before t: known at 15:30 IST
            _, fxv = before(fx, d, strict=False)
            if not iclose or not fxv:
                continue
            inav = k_prev * iclose * fxv if k_prev else None
            k_now = None
            if nav:
                _, same = before(idx, d, strict=False)        # same-date close: what NAV_t is struck on
                k_now = nav / (same * fxv) if same else None
                if k_now and k_prev and abs(k_now / k_prev - 1) > 0.3:
                    inav = None                               # unit split / face-value change on this day
            out.append((isin, d, idx, iclose, idate, fxv, k_prev, inav, close, nav,
                        100 * (close / inav - 1) if inav and close else None))
            if k_now:
                k_prev = k_now
    with db:
        db.execute("DELETE FROM etf_inav")
        db.executemany("INSERT OR REPLACE INTO etf_inav VALUES (?,?,?,?,?,?,?,?,?,?,?)", out)
    print("etf_inav:", len(etfs), "international ETFs,", len(out), "rows")


def check(db):
    print(db.execute("SELECT COUNT(*), SUM(scheme_code IS NOT NULL) FROM etf_master").fetchone(), "ETFs / with AMFI NAV")
    for sym in ("MONQ50", "MON100", "NIFTYBEES", "GOLDBEES"):
        rows = db.execute("SELECT date, close, round(nav, 4), round(premium_pct, 2) FROM etf_premium WHERE symbol = ? "
                          "AND date BETWEEN '2026-09-15' AND '2026-09-30' ORDER BY date", (sym,)).fetchall()
        print(sym, rows)
    try:
        for r in db.execute("SELECT underlying, COUNT(*), ROUND(AVG(ABS(inav / nav - 1)) * 100, 3), "
                            "ROUND(MAX(ABS(inav / nav - 1)) * 100, 2) FROM etf_inav WHERE inav IS NOT NULL AND nav IS NOT NULL "
                            "GROUP BY 1"):
            print("iNAV vs same-day NAV (gap = underlying's day-t session): underlying, days, mean |gap| %, max %:", r)
        print(db.execute("SELECT date, close, round(inav, 2), round(nav, 2), round(premium_vs_inav_pct, 1) FROM etf_inav "
                         "i JOIN etf_master m USING (isin) WHERE m.symbol = 'MONQ50' AND date BETWEEN '2026-09-16' "
                         "AND '2026-09-23' ORDER BY date").fetchall())
    except sqlite3.OperationalError:
        pass


def lock_holders(db_path):
    """Best-effort pid/name of processes holding the DB (SQLite itself does not expose the writer)."""
    try:
        import psutil
    except ImportError:
        return []
    target = str(Path(db_path).resolve())
    names = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if not any(k in (p.info["name"] or "").lower() for k in ("python", "sqlite", "dsh", "node")):
                continue
            if any(f.path in (target, target + "-wal", target + "-shm") for f in p.open_files()):
                names.append(f"pid {p.pid} ({p.info['name']})")
        except (psutil.Error, OSError):
            continue
    return names


def queue_lock_state(db_path):
    """('held'|'free'|'absent'|'unreadable', path): the ingest-queue OS lock that serialises DB writers."""
    path = Path(db_path).parent / "ingestion_queue.lock"
    if not path.exists():
        return "absent", path
    try:
        with path.open("a+b") as h:
            h.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(h.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return "free", path
            except OSError:
                return "held", path
    except OSError:
        return "unreadable", path


def connect(db_path, timeout=DB_TIMEOUT):
    """Open the DB, create the tables and prove the writer lock is free now.

    The probe is an empty BEGIN IMMEDIATE/ROLLBACK (no rows written): without it a
    busy DB would only surface 10 minutes later inside load_px's first INSERT.
    """
    db = sqlite3.connect(db_path, timeout=timeout)
    try:
        db.executescript(DDL)
        db.execute("BEGIN IMMEDIATE")
        db.rollback()
        db.execute("PRAGMA busy_timeout = 600000")   # fail fast only at startup; later brief locks wait as before
        return db
    except sqlite3.OperationalError as e:
        db.close()
        if "lock" not in str(e).lower() and "busy" not in str(e).lower():
            raise
        holders = lock_holders(db_path)
        queue, queue_path = queue_lock_state(db_path)
        wal = Path(str(db_path) + "-wal")
        wal_info = (f"WAL {wal.stat().st_size / 1e6:.0f} MB, last write "
                    f"{dt.datetime.fromtimestamp(wal.stat().st_mtime):%Y-%m-%d %H:%M:%S}") if wal.exists() else "no WAL"
        raise SystemExit(
            f"ERROR: {db_path} is locked (waited {timeout:.0f}s): {e}. "
            f"Holder: {'; '.join(holders) if holders else 'another process (handle names not visible to this user)'}; "
            f"ingestion queue lock {queue_path}: {queue}; {wal_info}. "
            f"Check the running dsh-worker job, then rerun (or raise --db-timeout).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01")
    ap.add_argument("--end", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--inav", action="store_true", help="only rebuild etf_inav")
    ap.add_argument("--db", default=str(DB), help="SQLite path (point at a temp DB for probes)")
    ap.add_argument("--net-timeout", type=float, default=NET_TIMEOUT, help="wall-clock cap per HTTP response (s)")
    ap.add_argument("--net-max-mb", type=float, default=NET_MAX_BYTES / 2**20, help="max bytes per month file")
    ap.add_argument("--db-timeout", type=float, default=DB_TIMEOUT, help="seconds to wait for the DB write lock")
    a = ap.parse_args()
    db = connect(a.db, a.db_timeout)
    if a.inav:
        build_inav(db, a.net_timeout)
    elif not a.check:
        load_px(db)
        load_nav(db, dt.date.fromisoformat(a.start + "-01"), dt.date.fromisoformat(a.end + "-01"),
                 a.net_timeout, int(a.net_max_mb * 2**20))
        build_inav(db, a.net_timeout)
    check(db)


if __name__ == "__main__":
    main()
