"""NSE daily circuit hits, price bands and surveillance stages (PIPELINE_TODO phase C, 2026-10-19).

Sources (nsearchives, one pair per trading day; dates from mkt_nse_full_daily / mkt_nse_eq_daily):
  PR bundle  archives/equities/bhavcopy/pr/PRDDMMYY.zip (2019 ->): bh = securities that hit their price band that day
             (H = upper, L = lower circuit); hl = new 52-week highs / lows. Zips kept in raw_market/nse_pr/.
  band list  content/equities/sec_list_DDMMYYYY.csv (2021 ->; 404 for 2019): every security with a price band, its band
             % and Remarks (GSM / ASM stage when under surveillance). Kept gzipped in raw_market/nse_sec_list/.
Tables (equity_intelligence.db): circuit_hits (date, symbol, series, high_low), price_bands (date, symbol, series, band,
remarks). Both are end-of-day files (known after the close of that day).

    python -m reality_engine.scripts.fetch_nse_pr [--start 2019-01-01] [--end today]
"""
import argparse
import csv
import datetime as dt
import gzip
import io
import sqlite3
import time
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "equity_intelligence.db"
RAW = DATA / "raw_market"
PR = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{d:%d%m%y}.zip"
SEC = "https://nsearchives.nseindia.com/content/equities/sec_list_{d:%d%m%Y}.csv"
DDL = """
CREATE TABLE IF NOT EXISTS circuit_hits (date TEXT, symbol TEXT, series TEXT, high_low TEXT, PRIMARY KEY (date, symbol, series));
CREATE TABLE IF NOT EXISTS price_bands (date TEXT, symbol TEXT, series TEXT, band TEXT, remarks TEXT,
    PRIMARY KEY (date, symbol, series));
CREATE INDEX IF NOT EXISTS idx_circuit_sym ON circuit_hits(symbol, date);
CREATE INDEX IF NOT EXISTS idx_band_sym ON price_bands(symbol, date);
CREATE TABLE IF NOT EXISTS nse_pr_days (date TEXT PRIMARY KEY, pr INTEGER, sec_list INTEGER, done_at TEXT);
"""


def rows_csv(text):
    return [{(k or "").strip().upper(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    a = ap.parse_args()
    from reality_engine.scripts.fetch_nse_api_raw import NseFetcher
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    days = sorted({r[0] for r in db.execute(
        "SELECT DISTINCT date FROM mkt_nse_full_daily WHERE date BETWEEN ? AND ? UNION "
        "SELECT DISTINCT date FROM mkt_nse_eq_daily WHERE date BETWEEN ? AND ?", (a.start, a.end, a.start, a.end))})
    done = {r[0] for r in db.execute("SELECT date FROM nse_pr_days WHERE pr = 1 AND (sec_list = 1 OR date < '2021-01-01')")}
    todo = [d for d in days if d not in done]
    f = NseFetcher("nse_pr", dt.date.today(), dt.date.today())
    (RAW / "nse_pr").mkdir(parents=True, exist_ok=True)
    (RAW / "nse_sec_list").mkdir(parents=True, exist_ok=True)
    print(f"trading days {len(days)}, to fetch {len(todo)}", flush=True)
    for n, d in enumerate(todo, 1):
        day = dt.date.fromisoformat(d)
        got_pr = got_sec = 0
        zp = RAW / "nse_pr" / f"PR{day:%d%m%y}.zip"
        try:
            if not zp.exists():
                r = f.get(PR.format(d=day))
                if r.status_code == 200 and r.content[:2] == b"PK":
                    zp.write_bytes(r.content)
            if zp.exists():
                z = zipfile.ZipFile(zp)
                bh = [x for x in z.namelist() if x.lower().startswith("bh")]
                hits = []
                for x in bh:
                    for r in rows_csv(z.read(x).decode("utf-8", "replace")):
                        if r.get("SYMBOL"):
                            hits.append((d, r["SYMBOL"], r.get("SERIES"), r.get("HIGH/LOW")))
                with db:
                    db.executemany("INSERT OR REPLACE INTO circuit_hits VALUES (?,?,?,?)", hits)
                got_pr = 1
        except Exception:  # noqa: BLE001
            f.s = None
        time.sleep(0.4)
        sp = RAW / "nse_sec_list" / f"sec_list_{day:%d%m%Y}.csv.gz"
        try:
            if not sp.exists():
                r = f.get(SEC.format(d=day))
                if r.status_code == 200 and r.content[:6].lower().startswith(b"symbol"):
                    sp.write_bytes(gzip.compress(r.content))
            if sp.exists():
                rows = [(d, r.get("SYMBOL"), r.get("SERIES"), r.get("BAND"), r.get("REMARKS"))
                        for r in rows_csv(gzip.decompress(sp.read_bytes()).decode("utf-8", "replace")) if r.get("SYMBOL")]
                with db:
                    db.executemany("INSERT OR REPLACE INTO price_bands VALUES (?,?,?,?,?)", rows)
                got_sec = 1
        except Exception:  # noqa: BLE001
            f.s = None
        with db:
            db.execute("INSERT OR REPLACE INTO nse_pr_days VALUES (?,?,?,?)",
                       (d, got_pr, got_sec, dt.datetime.now().isoformat(timespec="seconds")))
        if n % 100 == 0:
            print(f"{n}/{len(todo)} {d}", flush=True)
        time.sleep(0.4)
    print("done", db.execute("SELECT COUNT(*), SUM(pr), SUM(sec_list), MIN(date), MAX(date) FROM nse_pr_days").fetchone(),
          db.execute("SELECT COUNT(*) FROM circuit_hits").fetchone(), db.execute("SELECT COUNT(*) FROM price_bands").fetchone())


if __name__ == "__main__":
    main()
