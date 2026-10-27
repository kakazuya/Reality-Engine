"""Probe 4: where segment data lives (read-only, bounded)."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])

rx = connect_ro(D / "results_xbrl.db", timeout_s=20)
print("rx idx:", rx.execute("select name,sql from sqlite_master where type='index'").fetchall())
try:
    print("rx seg concepts:", rx.execute(
        "select concept from facts where concept like '%Segment%' limit 5").fetchall())
except Exception as exc:
    print("rx seg ERR", type(exc).__name__)

df = connect_ro(D / "deck_figures.db", timeout_s=20)
print("df facts cols:", [r[1] for r in df.execute("PRAGMA table_info(facts)")])
try:
    print("df seg metrics:", df.execute(
        "select metric,count(*) c from facts where metric like '%segment%' group by 1 limit 10").fetchall())
except Exception as exc:
    print("df seg ERR", type(exc).__name__)

ar = connect_ro(D / "ar_facts.db", timeout_s=20)
# per-isin bounded lookups only
print("ar cats 20MICRONS:", ar.execute(
    "select category,count(*) c from ar_facts where isin='INE144J01027' and fiscal_year>='2025-03-31' group by 1 order by c desc limit 40").fetchall())
