"""Total-return indices for the benchmark rule (PIPELINE_TODO B2, 2026-10-19). Table `index_tri` in equity_intelligence.db.

  official  NSE indices from niftyindices.com (POST /BackPage/getTotalReturnIndexString, at most one year per call):
            Nifty Smallcap 250, Nifty Midcap 150 (benchmark candidates) + Nifty 50, Nifty 500 (reference).
  derived   BSE publishes no TRI on bseindia.com (Index archive = price only; asiaindex.co.in is parked, 2026-10-19), so
            BSE 250 SmallCap, Sensex and BSE IPO get a TRI built from the price index and BSE's own daily dividend
            yield (mkt_bse_index_daily.div_yield):
                TRI_t = TRI_{t-1} * (P_t / P_{t-1}) * (1 + YIELD_SCALE * dy_{t-1} / 100 / 365 * days)
            YIELD_SCALE = 0.8 is calibrated on the four NSE indices against their official TRI, 2020-2025 (mean annual
            error -0.02%, worst year 0.38%; unscaled +0.26% / 0.67%: the published trailing yield overstates paid-out
            dividends).
            The same method applied to the NSE price index + yield is compared with the official NSE TRI (--check), so
            the derived series' error is measured, not assumed.

Benchmark selector (FRAMEWORK s.3): trailing 12-month TRI return, chosen before each month; see benchmark_for_month().

    python -m reality_engine.scripts.fetch_index_tri [--start 2019-01-01] [--check]
"""
import argparse
import datetime as dt
import json
import sqlite3
import time
from pathlib import Path

import requests

DB = Path(__file__).resolve().parents[1] / "data" / "equity_intelligence.db"
NSE = ["NIFTY SMALLCAP 250", "NIFTY MIDCAP 150", "NIFTY 50", "NIFTY 500"]
BSE = {"SPB25SIP": "BSE 250 SmallCap", "SENSEX": "BSE Sensex", "IPO": "BSE IPO"}
NSE_PRICE = {"NIFTY SMALLCAP 250": "Nifty Smallcap 250", "NIFTY MIDCAP 150": "Nifty Midcap 150", "NIFTY 50": "Nifty 50",
             "NIFTY 500": "Nifty 500"}
YIELD_SCALE = 0.8
CANDIDATES = ["NIFTY SMALLCAP 250", "NIFTY MIDCAP 150", "BSE 250 SmallCap", "BSE Sensex", "BSE IPO"]
DDL = """CREATE TABLE IF NOT EXISTS index_tri (index_name TEXT, date TEXT, tri REAL, price REAL, source TEXT,
    method TEXT, fetched_at TEXT, PRIMARY KEY (index_name, date))"""


def nse_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
                      "Content-Type": "application/json; charset=utf-8",
                      "Referer": "https://niftyindices.com/reports/historical-data", "Origin": "https://niftyindices.com"})
    s.get("https://niftyindices.com/reports/historical-data", timeout=30)
    return s


def fetch_nse(db, start, end):
    s = nse_session()
    now = dt.datetime.now().isoformat(timespec="seconds")
    for name in NSE:
        a = start
        while a <= end:
            b = min(end, a.replace(year=a.year + 1) - dt.timedelta(days=1))
            cinfo = "{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}" % (
                name, a.strftime("%d-%b-%Y"), b.strftime("%d-%b-%Y"), name)
            r = s.post("https://niftyindices.com/BackPage/getTotalReturnIndexString", data=json.dumps({"cinfo": cinfo}),
                       timeout=90)
            rows = r.json() if r.text.startswith("[") else []
            out = [(name, dt.datetime.strptime(x["Date"], "%d %b %Y").date().isoformat(),
                    float(str(x["TotalReturnsIndex"]).replace(",", "")), None, "niftyindices.com", "official", now)
                   for x in rows if x.get("TotalReturnsIndex") not in (None, "", "-")]
            with db:
                db.executemany("INSERT OR REPLACE INTO index_tri VALUES (?,?,?,?,?,?,?)", out)
            print(f"{name} {a}..{b}: {len(out)} days", flush=True)
            a = b + dt.timedelta(days=1)
            time.sleep(1.0)


def derive(rows):
    """[(date, price, div_yield %)] -> [(date, tri)], TRI starting at the first price."""
    out, tri, prev = [], None, None
    for d, p, dy in rows:
        if p is None:
            continue
        if prev is None:
            tri = p
        else:
            pd_, pp, pdy = prev
            days = (dt.date.fromisoformat(d) - dt.date.fromisoformat(pd_)).days
            tri *= (p / pp) * (1 + YIELD_SCALE * (pdy or 0) / 100 / 365 * days)
        out.append((d, tri))
        prev = (d, p, dy)
    return out


def derive_bse(db):
    now = dt.datetime.now().isoformat(timespec="seconds")
    for code, name in BSE.items():
        rows = db.execute("SELECT date, close, div_yield FROM mkt_bse_index_daily WHERE trim(index_code) = ? "
                          "AND close IS NOT NULL ORDER BY date", (code,)).fetchall()
        price = {d: p for d, p, _ in rows}
        out = [(name, d, t, price[d], "bseindia.com price + div_yield", "derived", now) for d, t in derive(rows)]
        with db:
            db.execute("DELETE FROM index_tri WHERE index_name = ? AND method = 'derived'", (name,))
            db.executemany("INSERT OR REPLACE INTO index_tri VALUES (?,?,?,?,?,?,?)", out)
        print(f"{name}: {len(out)} derived days ({rows[0][0] if rows else '-'} .. {rows[-1][0] if rows else '-'})")


def ret(series, a, b):
    """return between the last values on or before a and b"""
    xa = [v for d, v in series if d <= a]
    xb = [v for d, v in series if d <= b]
    return xb[-1] / xa[-1] - 1 if xa and xb else None


def check(db):
    print("year  index                     TRI ret   price ret  TRI-price  avg yield | derived TRI ret  error")
    fails = []
    for name, pname in NSE_PRICE.items():
        tri = db.execute("SELECT date, tri FROM index_tri WHERE index_name = ? AND method = 'official' ORDER BY date",
                         (name,)).fetchall()
        px = db.execute("SELECT date, close, div_yield FROM mkt_nse_index_daily WHERE index_name = ? ORDER BY date",
                        (pname,)).fetchall()
        der = derive(px)
        pser = [(d, p) for d, p, _ in px]
        for y in range(2020, 2026):
            a, b = f"{y - 1}-12-31", f"{y}-12-31"
            rt, rp, rd = ret(tri, a, b), ret(pser, a, b), ret(der, a, b)
            dy = [x for d, _, x in px if a < d <= b and x]
            avg = sum(dy) / len(dy) if dy else None
            if rt is None or rp is None:
                continue
            gap = rt - rp
            err = (rd - rt) if rd is not None else None
            print(f"{y}  {name:<24} {rt:8.2%} {rp:10.2%} {gap:9.2%} {avg or 0:9.2f}% | {rd or 0:13.2%} {err or 0:7.2%}")
            if not (0.003 <= gap <= 0.03):
                fails.append((name, y, "TRI-price gap", round(gap, 4)))
            if err is not None and abs(err) > 0.004:
                fails.append((name, y, "derived error", round(err, 4)))
    print("ALL CHECKS PASSED" if not fails else f"FLAGS: {fails}")


def benchmark_for_month(db, month_start):
    """FRAMEWORK s.3: candidate with the best trailing 12-month TRI return, using data before month_start only."""
    m = dt.date.fromisoformat(month_start)
    a, b = (m - dt.timedelta(days=365)).isoformat(), (m - dt.timedelta(days=1)).isoformat()
    best = None
    for name in CANDIDATES:
        s = db.execute("SELECT date, tri FROM index_tri WHERE index_name = ? AND date <= ? ORDER BY date", (name, b)).fetchall()
        r = ret(s, a, b)
        if r is not None and (best is None or r > best[1]):
            best = (name, r)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    db.execute(DDL)
    if not a.check:
        fetch_nse(db, dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end))
        derive_bse(db)
    check(db)
    for mth in ("2024-01-01", "2025-01-01", "2026-01-01", "2026-10-01"):
        print("benchmark for", mth, benchmark_for_month(db, mth))


if __name__ == "__main__":
    main()
