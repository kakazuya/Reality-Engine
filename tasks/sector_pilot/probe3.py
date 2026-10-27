"""Probe 3: indexes + tiny samples (read-only)."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
ar = connect_ro(D / "ar_facts.db", timeout_s=30)
print("idx:", ar.execute(
    "select name,tbl_name,sql from sqlite_master where type='index' and tbl_name='ar_facts'").fetchall())
print("doc idx:", ar.execute(
    "select name,sql from sqlite_master where type='index' and tbl_name='ar_docs'").fetchall())
rows = ar.execute("select doc_id from ar_docs where fiscal_year='2025-03-31' limit 3").fetchall()
print("docs:", rows)
ids = ",".join("'%s'" % r[0] for r in rows)
print("cats sample:", ar.execute(
    f"select doc_id,category,item,value_raw,period from ar_facts where doc_id in ({ids}) limit 25").fetchall())

eq = connect_ro(D / "equity_intelligence.db", timeout_s=30)
print("security_master cols:", [r[1] for r in eq.execute("PRAGMA table_info(security_master)")])
print("forensic:", eq.execute(
    "select name from sqlite_master where type='table' and name like '%forensic%'").fetchall())
