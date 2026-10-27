"""Probe 2: segment representation, cap table, BSE codes (read-only)."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
ar = connect_ro(D / "ar_facts.db", timeout_s=60)
print("cats FY25:", ar.execute(
    "select category,count(*) c from ar_facts where fiscal_year>='2025-03-31' "
    "group by 1 order by c desc limit 25").fetchall())

eq = connect_ro(D / "equity_intelligence.db", timeout_s=60)
print("security_master cols:", [r[1] for r in eq.execute("PRAGMA table_info(security_master)")])
for t in ("company_forensic_health",):
    try:
        cols = [r[1] for r in eq.execute(f"PRAGMA table_info({t})")]
        n = eq.execute(f"select count(*) from {t}").fetchone()
        print(t, "cols:", cols, "rows:", n)
    except Exception as exc:
        print(t, "ERR", exc)
print("xbrl seg tables:", [r[0] for r in eq.execute(
    "select name from sqlite_master where type='table' and name like '%segment%'").fetchall()])
rx = connect_ro(D / "results_xbrl.db", timeout_s=60)
print("xbrl tables:", [r[0] for r in rx.execute(
    "select name from sqlite_master where type='table'").fetchall()])
print("xbrl concepts with segment:", rx.execute(
    "select concept,count(*) c from facts where concept like '%Segment%' group by 1 order by c desc limit 10").fetchall())
