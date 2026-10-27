"""Probe 7: ar_facts 'segment' rows shape for two known companies."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(D / "equity_intelligence.db", timeout_s=30)
ar = connect_ro(D / "ar_facts.db", timeout_s=30)
for sym in ("TITAGARH", "GRASIM", "JISLDVREQS"):
    row = eq.execute("select isin from master_companies where nse_symbol=? limit 1", (sym,)).fetchone()
    if not row:
        print(sym, "not in master"); continue
    isin = row[0]
    rows = ar.execute(
        "select fiscal_year,item,value,unit,period,basis,quote from ar_facts "
        "where isin=? and category='segment' and fiscal_year>='2025-03-31' limit 15", (isin,)).fetchall()
    print("==", sym, isin, "n=", len(rows))
    for r in rows:
        print("  ", r)
