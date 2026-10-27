"""Probe 6: XBRL segment fact shape + one filing."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
rx = connect_ro(D / "results_xbrl.db", timeout_s=30)
print("facts cols:", [r[1] for r in rx.execute("PRAGMA table_info(facts)")])
print("filings cols:", [r[1] for r in rx.execute("PRAGMA table_info(filings)")])
rows = rx.execute(
    "select file,context,period_end,value,unit from facts "
    "where concept='SegmentRevenue' and period_end>='2025-03-31' order by period_end desc limit 8").fetchall()
for r in rows:
    print(r)
f = rx.execute("select file,isin,symbol,period_end from filings where period_end>='2025-03-31' limit 1").fetchone()
print("filing:", f)
if f:
    for r in rx.execute(
        "select concept,context,period_start,period_end,value,unit from facts where file=? and concept like 'Segment%' limit 12",
        (f[0],)).fetchall():
        print(r)
