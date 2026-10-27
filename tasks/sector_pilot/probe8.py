"""Probe 8: labels taxonomy, document_chunks access, one-company evidence bundle."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(D / "equity_intelligence.db", timeout_s=30)
print("sectors:", [r[0] for r in eq.execute("select distinct sector from company_industry order by 1")])
print("macros:", [r[0] for r in eq.execute("select distinct macro from company_industry order by 1")])
print("industries:", [r[0] for r in eq.execute("select distinct industry from company_industry order by 1")])
print("dc cols:", [r[1] for r in eq.execute("PRAGMA table_info(document_chunks)")])
print("dc idx:", eq.execute("select name,sql from sqlite_master where type='index' and tbl_name='document_chunks'").fetchall())
