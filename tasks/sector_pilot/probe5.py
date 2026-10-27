"""Probe 5: cap table + XBRL segment concepts."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(D / "equity_intelligence.db", timeout_s=30)
print("forensic cols:", [r[1] for r in eq.execute("PRAGMA table_info(company_forensic_health)")])
print("forensic rows:", eq.execute("select count(*) from company_forensic_health").fetchone())
print("forensic sample:", eq.execute(
    "select isin,market_cap_inr_cr from company_forensic_health where market_cap_inr_cr is not null limit 3").fetchall())

rx = connect_ro(D / "results_xbrl.db", timeout_s=30)
print("seg concept families:", rx.execute(
    "select concept, count(*) c from facts where concept like '%Segment%' group by 1 order by c desc limit 40").fetchall())
