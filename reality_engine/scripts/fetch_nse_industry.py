"""NSE industry classification per listed company (2026-10-19, for A3 policy -> company mapping and sector peers).

master_companies.industry / sector are unusable (2026-10-19: 1,868 'General Diversified', 1,751 'Other', 2,714 blank of
6,833). NSE's quote API (new site: /api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData) carries NSE's
four-level classification in secInfo: macro -> sector -> industryInfo -> basicIndustry, plus the index list.
BSE's company-header API refuses scripts (403), so NSE is the source; BSE-only companies stay unclassified for now.

Table company_industry (equity_intelligence.db): isin, symbol, series, macro, sector, industry, basic_industry,
index_list, listing_date, fetched_at. This is TODAY's classification (not point in time); classifications rarely change,
but a backtest should treat it as a current label.

    python -m reality_engine.scripts.fetch_nse_industry [--limit N]
"""
import argparse
import csv
import datetime as dt
import json
import sqlite3
import time
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "equity_intelligence.db"
MASTERS = DATA / "raw_market" / "masters"
URL = ("https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N"
       "&series={series}&symbol={symbol}")
DDL = """CREATE TABLE IF NOT EXISTS company_industry (isin TEXT, symbol TEXT PRIMARY KEY, series TEXT, macro TEXT,
    sector TEXT, industry TEXT, basic_industry TEXT, index_list TEXT, listing_date TEXT, fetched_at TEXT)"""


def listed():
    out = []
    for fn, sme in (("nse_EQUITY_L.csv", False), ("nse_SME_EQUITY_L.csv", True)):
        with open(MASTERS / fn, encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
                sym = r.get("SYMBOL")
                isin = r.get("ISIN NUMBER") or r.get("ISIN_NUMBER")
                series = r.get("SERIES") or ("ST" if sme else "EQ")
                if sym:
                    out.append((sym, isin, series, sme))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    from urllib.parse import quote

    from reality_engine.scripts.fetch_nse_api_raw import NseFetcher
    db = sqlite3.connect(DB, timeout=600)
    db.execute(DDL)
    have = {r[0] for r in db.execute("SELECT symbol FROM company_industry WHERE macro IS NOT NULL")}
    todo = [x for x in listed() if x[0] not in have]
    todo = todo[:a.limit] if a.limit else todo
    f = NseFetcher("nse_industry", dt.date.today(), dt.date.today())
    ok = miss = 0
    print(f"to fetch {len(todo)}", flush=True)
    for n, (sym, isin, series, sme) in enumerate(todo, 1):
        si, used = None, None
        for ser in dict.fromkeys([series, "ST" if sme else "EQ", "SM", "BE", "BZ", "EQ"]):
            try:
                j = f.get(URL.format(series=ser, symbol=quote(sym))).json()
                si = ((j.get("equityResponse") or [{}])[0] or {}).get("secInfo")
            except Exception:  # noqa: BLE001
                f.s = None; si = None; time.sleep(3)
            if si and (si.get("macro") or si.get("basicIndustry")):
                used = ser
                break
            time.sleep(0.5)
        row = (isin, sym, used, *(si.get(k) for k in ("macro", "sector", "industryInfo", "basicIndustry")),
               json.dumps(si.get("indexList")) if si and si.get("indexList") else None,
               si.get("listingDate") if si else None, dt.datetime.now().isoformat(timespec="seconds")) if si else \
            (isin, sym, None, None, None, None, None, None, None, dt.datetime.now().isoformat(timespec="seconds"))
        with db:
            db.execute("INSERT OR REPLACE INTO company_industry VALUES (?,?,?,?,?,?,?,?,?,?)", row)
        ok += bool(si); miss += (not si)
        if n % 200 == 0:
            print(f"{n}/{len(todo)} ok {ok} missing {miss}", flush=True)
        time.sleep(1.0)
    print("done", db.execute("SELECT COUNT(*), COUNT(macro), COUNT(DISTINCT basic_industry) FROM company_industry").fetchone())


if __name__ == "__main__":
    main()
