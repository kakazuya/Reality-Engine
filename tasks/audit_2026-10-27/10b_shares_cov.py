"""A10b - XBRL facts indexes + cheap coverage counts (duckdb for aggregates)."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
rx = connect_ro(DATA / "results_xbrl.db", timeout_s=120)
print("facts indexes:", rx.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='facts'").fetchall())
print("filings indexes:", rx.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='filings'").fetchall())

con = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
print("\n== duckdb.results_facts concept coverage")
rows = con.execute("""
SELECT concept, COUNT(*) n, COUNT(DISTINCT file) files FROM results_facts
WHERE concept IN ('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital',
                  'NumberOfShares','EquityShareCapital','PaidUpValueOfPreferenceShareCapital')
GROUP BY 1 ORDER BY 2 DESC
""").fetchall()
for r in rows:
    print("  ", r)
print("\n== files with both paid-up and face value")
print(con.execute("""
WITH f AS (SELECT file, COUNT(DISTINCT concept) k FROM results_facts
           WHERE concept IN ('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital')
           GROUP BY 1 HAVING k=2)
SELECT COUNT(*) FROM f
""").fetchall())
print("== filings joined, FY25+")
print(con.execute("""
WITH f AS (SELECT file FROM results_facts
           WHERE concept IN ('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital')
           GROUP BY 1 HAVING COUNT(DISTINCT concept)=2)
SELECT COUNT(*) filings, COUNT(DISTINCT rf.isin) isins,
       SUM(CASE WHEN rf.period_end >= DATE '2024-03-31' THEN 1 ELSE 0 END) fy25,
       SUM(rf.isin IS NULL OR rf.isin='') null_isin
FROM results_filings rf JOIN f USING(file)
""").fetchall())
print("\n== paid-up units: sample values (are they thousands?)")
print(con.execute("""
SELECT file, value, unit FROM results_facts
WHERE concept='PaidUpValueOfEquityShareCapital' AND value IS NOT NULL LIMIT 8
""").fetchall())
print("\n== face value values")
print(con.execute("SELECT value, COUNT(*) FROM results_facts WHERE concept='FaceValueOfEquityShareCapital' GROUP BY 1 ORDER BY 2 DESC LIMIT 12").fetchall())
con.close()
rx.close()
