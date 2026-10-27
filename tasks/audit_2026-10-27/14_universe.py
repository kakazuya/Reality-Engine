"""A14 - FY25+ universe definition, results ISIN resolution, exchange split."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=90)
snap = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)

print("== results_xbrl objects")
rx = connect_ro(DATA / "results_xbrl.db", timeout_s=60)
print([r[0] for r in rx.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')")])
print("filings_isin columns:", [r[1] for r in rx.execute("PRAGMA table_info('filings_isin')")] if "filings_isin" in [r[0] for r in rx.execute("SELECT name FROM sqlite_master")] else "MISSING")
rx.close()

print("\n== FY25+ universe (events known_at >= 2024-04-01) and exchange split")
uni = [r[0] for r in snap.execute("SELECT DISTINCT isin FROM events WHERE known_at_utc >= TIMESTAMP '2024-04-01' AND isin IS NOT NULL").fetchall()]
print("distinct ISINs with any FY25+ event:", len(uni))
marks = ",".join("?" * len(uni))
rows = eq.execute(f"""SELECT
   CASE WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' AND bse_code IS NOT NULL AND bse_code<>'' THEN 'BSE+NSE'
        WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' THEN 'NSE-only' ELSE 'BSE-only' END k,
   COUNT(*), SUM(CASE WHEN substr(isin,1,3)='INE' AND isin NOT LIKE 'INE_AUTO_%' THEN 1 ELSE 0 END) equity
 FROM master_companies WHERE isin IN ({marks}) GROUP BY k""", uni).fetchall()
print("  split:", rows)
print("  FY25+ ISINs NOT in master_companies:", len(uni) - eq.execute(
    f"SELECT COUNT(*) FROM master_companies WHERE isin IN ({marks})", uni).fetchone()[0])

print("\n== universe sizes for coverage denominators")
print("master active:", eq.execute("SELECT COUNT(*) FROM master_companies WHERE is_active=1").fetchone())
print("master active + INE equity:", eq.execute(
    "SELECT COUNT(*) FROM master_companies WHERE is_active=1 AND substr(isin,1,3)='INE' AND isin NOT LIKE 'INE_AUTO_%'").fetchone())
print("FY25+ with >=1 results filing:", snap.execute(
    "SELECT COUNT(DISTINCT isin) FROM results_filings WHERE period_end >= '2024-03-31'").fetchone())
print("FY25+ with >=1 price bar:", snap.execute(
    "SELECT COUNT(DISTINCT isin) FROM px_daily WHERE date >= DATE '2024-04-01'").fetchone())
print("FY25+ with shp:", snap.execute(
    "SELECT COUNT(DISTINCT isin) FROM shp_index WHERE quarter_end >= '2024-03-31'").fetchone())
print("FY25+ with deck:", snap.execute(
    "SELECT COUNT(DISTINCT isin) FROM deck_sources WHERE CAST(known_at AS TIMESTAMP) >= TIMESTAMP '2024-04-01'").fetchone())
print("FY25+ with AR:", snap.execute(
    "SELECT COUNT(DISTINCT isin) FROM ar_docs WHERE CAST(known_at_utc AS TIMESTAMP) >= TIMESTAMP '2024-04-01'").fetchone())
print("FY25+ with concall doc:", eq.execute(
    "SELECT COUNT(DISTINCT isin) FROM corporate_documents WHERE doc_type='CONCALL_TRANSCRIPT' AND bse_dissem_ts >= '2024-04-01'").fetchone())

print("\n== results ISIN resolution already built (trading_isin)")
print(snap.execute("""SELECT trading_isin_method, COUNT(*), SUM(trading_isin IS NOT NULL) FROM results_filings GROUP BY 1""").fetchall())
print("same_issuer:", snap.execute("SELECT same_issuer, COUNT(*) FROM results_filings GROUP BY 1").fetchall())

print("\n== index flags are current-only: evidence")
print("index_membership as_of:", eq.execute("SELECT DISTINCT as_of FROM index_membership").fetchall())

print("\n== master_companies sector origin (which rows came from company_industry)")
print(eq.execute("""SELECT SUM(CASE WHEN mc.sector IN ('General Diversified','Other') THEN 1 ELSE 0 END) placeholder,
                           SUM(CASE WHEN mc.sector IN ('General Diversified','Other') AND ci.isin IS NOT NULL THEN 1 ELSE 0 END) placeholder_but_classified,
                           SUM(CASE WHEN ci.isin IS NOT NULL THEN 1 ELSE 0 END) nse_classified
                    FROM master_companies mc LEFT JOIN company_industry ci ON ci.isin=mc.isin""").fetchall())
eq.close()
snap.close()

