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
  etf_inav     (isin, date, underlying, idx_close, idx_date, fx, k, inav, close, premium_vs_inav_pct): international
               ETFs. The official NAV arrives at night; at the Indian close (15:30 IST) the latest underlying close is the
               previous session's (US / Europe close after India; Hong Kong / Tokyo close before 15:30 IST but we take
               the last close dated before the Indian session's date to stay point-in-time safe). Indicative NAV:
                   k_t   = NAV_t / (idx_{last close dated < t} x FX_t)          (units, expenses, cash drag)
                   iNAV_t = k_{t-1} x idx_{last close dated < t} x FX_t
               FX_t: Yahoo INR=X close of day t (taken at the Indian close; an approximation, logged as such).
               Accuracy is measured (--check): iNAV_t vs the official NAV_t.

    python -m reality_engine.scripts.fetch_etf_nav [--start 2019-01] [--end 2026-10] [--check]
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

import requests

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "equity_intelligence.db"
RAW = DATA / "raw_market"
AMFI = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt={a}&todt={b}"
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
    for z in sorted((RAW / "nse_cm_isin").glob("*.zip")):
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
    print("etf_px rows", db.execute("SELECT COUNT(*), COUNT(DISTINCT isin), MIN(date), MAX(date) FROM etf_px").fetchone())


def month_file(a):
    out = RAW / "amfi_nav" / f"{a:%Y-%m}.txt.gz"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    b = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    for attempt in range(4):
        try:
            r = requests.get(AMFI.format(a=a.strftime("%d-%b-%Y"), b=b.strftime("%d-%b-%Y")),
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=300)
            if r.status_code == 200 and "Scheme Code" in r.text[:200]:
                tmp = out.with_suffix(".tmp")
                tmp.write_bytes(gzip.compress(r.content))
                tmp.replace(out)
                return out
        except requests.RequestException:
            pass
        time.sleep(20 * (attempt + 1))
    return None


def load_nav(db, start, end):
    etf = {r[0] for r in db.execute("SELECT isin FROM etf_master")}
    a = start
    while a <= end:
        f = month_file(a)
        if f is None:
            print(a, "download failed")
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


def build_inav(db):
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
        d = yf.download(t, start="2018-12-01", progress=False, auto_adjust=False)
        c = d["Close"]
        c = c.iloc[:, 0] if hasattr(c, "columns") else c
        series[t] = sorted((i.date().isoformat(), float(v)) for i, v in c.dropna().items())
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
            idate, iclose = before(idx, d)
            _, fxv = before(fx, d, strict=False)
            if not iclose or not fxv:
                continue
            inav = k_prev * iclose * fxv if k_prev else None
            out.append((isin, d, idx, iclose, idate, fxv, k_prev, inav, close, nav,
                        100 * (close / inav - 1) if inav and close else None))
            if nav:
                k_prev = nav / (iclose * fxv)
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
            print("iNAV vs official NAV: underlying, days, mean |err| %, max |err| %:", r)
        print(db.execute("SELECT date, close, round(inav, 2), round(nav, 2), round(premium_vs_inav_pct, 1) FROM etf_inav "
                         "i JOIN etf_master m USING (isin) WHERE m.symbol = 'MONQ50' AND date BETWEEN '2026-09-16' "
                         "AND '2026-09-23' ORDER BY date").fetchall())
    except sqlite3.OperationalError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01")
    ap.add_argument("--end", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--inav", action="store_true", help="only rebuild etf_inav")
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    if a.inav:
        build_inav(db)
    elif not a.check:
        load_px(db)
        load_nav(db, dt.date.fromisoformat(a.start + "-01"), dt.date.fromisoformat(a.end + "-01"))
        build_inav(db)
    check(db)


if __name__ == "__main__":
    main()
