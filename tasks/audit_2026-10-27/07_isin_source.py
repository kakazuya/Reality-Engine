"""A7 - which ISIN does an independent exchange source show, and what is the 2021-10-27 event?"""
import os
import sys
from collections import Counter
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
snap = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)

print("== independent BSE source for HAL (scrip 541154) and IPCALAB (524494)")
for sc in ("541154", "524494", "505200", "521064"):
    r = snap.execute("SELECT isin, MIN(date), MAX(date), COUNT(*) FROM px_bse WHERE sc_code=? GROUP BY 1 ORDER BY 2", (sc,)).fetchall()
    print(f"  scrip {sc}: {r}")
print("  bse_code_isin rows:")
for sc in ("541154", "524494", "505200", "521064"):
    print("   ", snap.execute("SELECT * FROM bse_code_isin WHERE sc_code=? ORDER BY first_date", (sc,)).fetchall())

print("\n== shp_index vs bhavcopy ISIN agreement for 2024+ quarter filings")
q = """
SELECT COUNT(*) n,
       SUM(CASE WHEN s.isin = h.isin THEN 1 ELSE 0 END) same
FROM (SELECT DISTINCT isin, symbol FROM shp_index WHERE quarter_end >= '2024-06-30') s
JOIN symbol_isin_history h ON h.exchange='NSE' AND h.symbol = s.symbol
"""
print(eq.execute(q).fetchone())

print("\n== 79 mass-switch of 2021-10-27: what does each store say?")
mass = snap.execute("""
    WITH w AS (
      SELECT entity_id, isin, MIN(date) d0, MAX(date) d1
      FROM px_daily GROUP BY 1,2
    ), seq AS (
      SELECT entity_id, isin, d0, d1,
             LEAD(isin) OVER (PARTITION BY entity_id ORDER BY d0) nxt,
             LEAD(d0) OVER (PARTITION BY entity_id ORDER BY d0) nxt0
      FROM w
    )
    SELECT s.entity_id, s.isin old_isin, s.nxt new_isin, s.nxt0 switch_date, p.symbol
    FROM seq s LEFT JOIN px_nse p ON p.entity_id = s.entity_id AND p.date = s.nxt0
    WHERE s.nxt IS NOT NULL AND s.nxt0 = DATE '2021-10-27' AND s.d1 = DATE '2021-10-26'
""").fetchall()
print("count", len(mass))
agg = Counter()
detail = []
for ent, old, new, sw, sym in mass:
    shp = eq.execute("SELECT DISTINCT isin FROM shp_index WHERE symbol=?", (sym,)).fetchall()
    shp_set = {r[0] for r in shp}
    de = snap.execute("SELECT DISTINCT isin FROM deck_sources WHERE symbol=?", (sym,)).fetchall()
    cc = snap.execute("SELECT DISTINCT isin FROM cc_docs WHERE symbol=?", (sym,)).fetchall()
    ar = snap.execute("SELECT DISTINCT isin FROM ar_docs WHERE symbol=?", (sym,)).fetchall()
    sm_bse = eq.execute("SELECT isin FROM security_master WHERE nse_symbol=? AND bse_code IS NOT NULL AND bse_code<>''", (sym,)).fetchall()
    detail.append((sym, old, new, shp_set, {r[0] for r in de}, {r[0] for r in cc}, {r[0] for r in ar},
                   {r[0] for r in sm_bse}))
for row in detail:
    sym, old, new, shp, de, cc, ar, smb = row
    agg["shp=old" if shp == {old} else "shp=new" if shp == {new} else f"shp=mixed/{len(shp)}"] += 1
    agg["docs=old" if de and de == {old} else "docs=new" if de and de == {new} else "docs=none/mixed"] += 1
    agg["secmaster_bse=old" if smb == {old} else "secmaster_bse=new" if smb == {new} else "secmaster_bse=none/mixed"] += 1
print(agg)
for row in detail[:8]:
    print("  ", row[0], "shp", row[3], "decks", row[4], "concall", row[5], "ar", row[6], "secmaster_bse", row[7])

print("\n== master_companies synthetic ISINs")
rows = eq.execute("""
SELECT CASE WHEN isin LIKE 'INE_AUTO_%' THEN 'INE_AUTO_*'
            WHEN isin LIKE 'INE999PHASE%' THEN 'INE999PHASE*'
            WHEN isin LIKE '%-RE' OR isin LIKE '%-%' THEN 'dash-suffix'
            WHEN length(isin)<>12 THEN 'bad-length'
            ELSE 'other' END k, COUNT(*), SUM(is_active)
FROM master_companies GROUP BY 1 ORDER BY 2 DESC
""").fetchall()
print(rows)
print(eq.execute("SELECT COUNT(*) FROM master_companies WHERE isin GLOB 'INE_AUTO_*'").fetchone(),
      eq.execute("SELECT COUNT(*) FROM master_companies WHERE isin LIKE 'INE_AUTO_%'").fetchone())
print("samples:", eq.execute("SELECT isin, nse_symbol, company_name, is_active FROM master_companies WHERE isin NOT LIKE 'INE%' OR isin LIKE 'INE_AUTO_%' LIMIT 8").fetchall())
snap.close()
eq.close()
