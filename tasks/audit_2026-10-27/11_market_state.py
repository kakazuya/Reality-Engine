"""A11 - layer-2 sources: index/F&O history, sector fill, price bands, market cap."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
con = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)

print("== adj_factor_cum: is the split/bonus factor dated per entity?")
print([c[0] for c in con.execute("DESCRIBE adj_factor_cum").fetchall()])
print(con.execute("SELECT * FROM adj_factor_cum LIMIT 3").fetchall())
print("HDFCBANK 2:1 split 2019-09-20 -> dated log factors for its entity:")
print(con.execute("""SELECT ex_date, run_l, tot_l, round(exp(tot_l),4) FROM adj_factor_cum
    WHERE entity_id=(SELECT entity_id FROM px_daily WHERE isin='INE040A01034' LIMIT 1)
      AND ex_date BETWEEN DATE '2019-09-01' AND DATE '2019-10-31' ORDER BY ex_date""").fetchall())
print("factor rows:", con.execute("SELECT COUNT(*), COUNT(DISTINCT entity_id), MIN(ex_date), MAX(ex_date) FROM adj_factor_cum").fetchall())

print("\n== market cap inputs: price x shares")
print("px_daily ISIN coverage 2024-04-01+:", con.execute(
    "SELECT COUNT(DISTINCT entity_id), COUNT(*) FROM px_daily WHERE date >= DATE '2024-04-01'").fetchall())
print("close available 2026-10-17:", con.execute(
    "SELECT COUNT(*) FROM px_daily WHERE date = (SELECT MAX(date) FROM px_daily) AND close IS NOT NULL").fetchall())

print("\n== index membership: what exists")
print("equity_intelligence.index_membership:", eq.execute("SELECT index_name, as_of, COUNT(*) FROM index_membership GROUP BY 1,2").fetchall())
print("mkt_nse_index_daily is index LEVEL only; distinct indices:", eq.execute(
    "SELECT COUNT(DISTINCT index_name) FROM mkt_nse_index_daily").fetchone())
print("any table with constituents? scanning names:")
names = [r[0] for r in eq.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("  ", [n for n in names if "constitu" in n.lower() or "member" in n.lower() or "fno" in n.lower()])
print("F&O: master_companies.is_fno_eligible:", eq.execute(
    "SELECT is_fno_eligible, COUNT(*) FROM master_companies GROUP BY 1").fetchall())
print("index flags in master:", eq.execute(
    "SELECT SUM(is_nifty50), SUM(is_nifty100), SUM(is_nifty200), SUM(is_nifty500), COUNT(*) FROM master_companies").fetchall())
print("index_membership vs master nifty50 join:",
      eq.execute("""SELECT COUNT(*) FROM index_membership im JOIN master_companies mc ON mc.isin=im.isin WHERE im.index_name='nifty50'""").fetchone())

print("\n== index change notices in the local feeds?")
print("bse_ann categories containing 'index':", eq.execute("""
SELECT CATEGORYNAME, SUBCATNAME, COUNT(*) FROM bse_announcements.ann
WHERE lower(CATEGORYNAME) LIKE '%index%' OR lower(SUBCATNAME) LIKE '%index%' OR lower(HEADLINE) LIKE '%index%'
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10""").fetchall() if False else "cross-db: see separate")
boa = connect_ro(DATA / "bse_announcements.db", timeout_s=30)
print(boa.execute("""SELECT CATEGORYNAME, SUBCATNAME, COUNT(*) FROM ann
WHERE lower(CATEGORYNAME) LIKE '%index%' OR lower(SUBCATNAME) LIKE '%index%'
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 8""").fetchall())
print("headlines mentioning F&O / futures ban:",
      boa.execute("""SELECT COUNT(*) FROM ann WHERE lower(HEADLINE) LIKE '%futures%' OR lower(HEADLINE) LIKE '%f&o%'""").fetchone())
boa.close()

print("\n== price bands by month (last 24 months present)")
rows = eq.execute("""SELECT substr(date,1,7) m, COUNT(*) n, COUNT(DISTINCT symbol) s FROM price_bands
                     GROUP BY m ORDER BY m DESC LIMIT 18""").fetchall()
for r in rows:
    print("  ", r)
print("distinct months present:", eq.execute("SELECT COUNT(DISTINCT substr(date,1,7)) FROM price_bands").fetchone())
print("symbols in price_bands vs master:", eq.execute(
    "SELECT COUNT(DISTINCT symbol) FROM price_bands").fetchone(),
    eq.execute("SELECT COUNT(*) FROM master_companies WHERE nse_symbol IS NOT NULL AND nse_symbol<>''").fetchone())

print("\n== sector / industry fill split")
print(eq.execute("""
WITH base AS (SELECT isin, nse_symbol, bse_code, sector,
  CASE WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' AND bse_code IS NOT NULL AND bse_code<>'' THEN 'BSE+NSE'
       WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' THEN 'NSE-only' ELSE 'BSE-only' END k
  FROM master_companies WHERE is_active=1)
SELECT k, COUNT(*) n,
       SUM(CASE WHEN sector IS NOT NULL AND sector<>'' THEN 1 ELSE 0 END) has_sector,
       SUM(CASE WHEN sector IN ('General Diversified','Other') THEN 1 ELSE 0 END) placeholder
FROM base GROUP BY k""").fetchall())
print("company_industry (NSE 4-level) coverage of active master:",
      eq.execute("""SELECT COUNT(*), SUM(CASE WHEN ci.isin IS NOT NULL THEN 1 ELSE 0 END) FROM master_companies mc
                    LEFT JOIN company_industry ci ON ci.isin=mc.isin WHERE mc.is_active=1""").fetchone())
print("by exchange:")
print(eq.execute("""
SELECT CASE WHEN mc.nse_symbol IS NOT NULL AND mc.nse_symbol<>'' AND mc.bse_code IS NOT NULL AND mc.bse_code<>'' THEN 'BSE+NSE'
            WHEN mc.nse_symbol IS NOT NULL AND mc.nse_symbol<>'' THEN 'NSE-only' ELSE 'BSE-only' END k,
       COUNT(*) n, SUM(CASE WHEN ci.isin IS NULL THEN 1 ELSE 0 END) no_nse_class
FROM master_companies mc LEFT JOIN company_industry ci ON ci.isin=mc.isin WHERE mc.is_active=1 GROUP BY k""").fetchall())
con.close()
eq.close()

