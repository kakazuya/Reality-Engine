"""Load official index constituent CSVs (niftyindices.com) into index_membership.
TODAY'S members only (no history) - any backtest using it has survivorship bias; as_of records the download date.
    python reality_engine/scripts/load_index_membership.py"""
import csv, datetime as dt, sqlite3
from pathlib import Path
from reality_engine.config import raw_dir
ROOT = Path(__file__).resolve().parents[2]
D = raw_dir("index_constituents")
c = sqlite3.connect(ROOT / "reality_engine/data/equity_intelligence.db", timeout=300)
c.execute("""create table if not exists index_membership(index_name text, symbol text, isin text, company_name text, industry text,
             as_of text, source text, primary key(index_name, symbol))""")
n = 0
with c:
    for f in sorted(D.glob("*_current.csv")):
        idx = f.name.replace("_current.csv", "")
        as_of = dt.date.fromtimestamp(f.stat().st_mtime).isoformat()
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            c.execute("insert or replace into index_membership values (?,?,?,?,?,?,?)",
                      (idx, r["Symbol"].strip(), r["ISIN Code"].strip(), r["Company Name"].strip(), r["Industry"].strip(), as_of,
                       f"niftyindices.com/IndexConstituent/ind_{idx}list.csv (current members only)"))
            n += 1
print("rows:", n)
for r in c.execute("select index_name, count(*), sum(isin in (select isin from master_companies)) from index_membership group by 1"): print(r)
