"""A3 - DuckDB snapshot inventory + entity/ISIN mapping check. Read-only."""
import os
from pathlib import Path

import duckdb

DATA = Path(os.environ["REALITY_DATA_ROOT"])
SNAP = DATA / "snapshots" / "truth_2026-10-19.duckdb"
con = duckdb.connect(str(SNAP), read_only=True)

print("== tables")
tabs = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall()]
print(len(tabs), tabs)

for t in ("security_master", "symbol_isin_history", "px_daily", "px_nse", "px_bse",
          "price_bands", "results_filings", "index_membership", "events", "company_industry",
          "shp_index", "master_companies", "fno", "index_constituents", "entity_isin"):
    if t not in tabs:
        print(f"-- {t}: MISSING")
        continue
    cols = con.execute(f"DESCRIBE {t}").fetchall()
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"-- {t} [{n}] :: {[c[0] for c in cols]}")

print("\n== px_daily entity mapping")
print(con.execute("SELECT COUNT(DISTINCT entity_id), COUNT(*) FROM px_daily").fetchall())
for sql, label in [
    ("SELECT COUNT(*) FROM (SELECT entity_id FROM px_daily GROUP BY 1 HAVING COUNT(DISTINCT isin)>1)", "entities with >1 isin"),
    ("SELECT COUNT(*) FROM (SELECT isin FROM px_daily GROUP BY 1 HAVING COUNT(DISTINCT entity_id)>1)", "isins with >1 entity"),
    ("SELECT entity_id, isin, MIN(date), MAX(date), COUNT(*) FROM px_daily GROUP BY 1,2 HAVING COUNT(DISTINCT isin)>1 LIMIT 5", "sample multi-isin entities"),
    ("SELECT MIN(date), MAX(date), COUNT(DISTINCT entity_id) FROM px_daily", "px_daily range"),
]:
    try:
        print(f"-- {label}: {con.execute(sql).fetchall()[:6]}")
    except Exception as exc:  # noqa: BLE001
        print(f"-- {label}: ERR {exc}")

print("\n== symbol_isin_history in snapshot")
print(con.execute("SELECT exchange, COUNT(*), MIN(first_date), MAX(last_date) FROM symbol_isin_history GROUP BY 1").fetchall())
print("-- NSE symbols with >1 isin:",
      con.execute("SELECT COUNT(*) FROM (SELECT symbol FROM symbol_isin_history WHERE exchange='NSE' GROUP BY 1 HAVING COUNT(DISTINCT isin)>1)").fetchone())

print("\n== index-ish tables present")
for t in tabs:
    if any(k in t.lower() for k in ("index", "constitu", "fno", "future", "membership", "mcap", "market_cap")):
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
        print(f"  {t} [{n}] :: {cols}")

print("\n== events kinds")
print(con.execute("SELECT kind, COUNT(*), MIN(known_at_utc), MAX(known_at_utc) FROM events GROUP BY 1 ORDER BY 2 DESC LIMIT 25").fetchall())
con.close()
