"""Probe 11: raw_documents x document_chunks x ar_docs join."""
import json
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
OUT = Path(__file__).resolve().parent
rows = json.loads((OUT / "sample.json").read_text(encoding="utf-8"))["rows"]
eq = connect_ro(D / "equity_intelligence.db", timeout_s=60)
ar = connect_ro(D / "ar_facts.db", timeout_s=60)
print("raw_documents cols:", [r[1] for r in eq.execute("PRAGMA table_info(raw_documents)")])
isin = rows[0]["isin"]
r = eq.execute("select doc_id,title,source_type,published_date,hash,local_path from raw_documents "
               "where isin=? order by published_date desc limit 5", (isin,)).fetchall()
for x in r:
    print("raw:", x[:4], "hash:", x[4], "path:", str(x[5])[-60:])
print("ar_docs:", ar.execute("select doc_id,sha256,path from ar_docs where isin=?", (isin,)).fetchall())
print("chunks by isin:", eq.execute(
    "select doc_id,count(*),min(chunk_index),max(event_date) from document_chunks where isin=? "
    "group by 1 order by 2 desc limit 5", (isin,)).fetchall())
