"""Probe 10: joins between ar_docs / document_chunks / decks for sampled names."""
import json
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
OUT = Path(__file__).resolve().parent
rows = json.loads((OUT / "sample.json").read_text(encoding="utf-8"))["rows"]
eq = connect_ro(D / "equity_intelligence.db", timeout_s=60)
ar = connect_ro(D / "ar_facts.db", timeout_s=60)
df = connect_ro(D / "deck_figures.db", timeout_s=60)

print("deck tables:", [r[0] for r in df.execute("select name from sqlite_master where type='table'")])
print("pages cols:", [r[1] for r in df.execute("PRAGMA table_info(pages)")])

r0 = rows[0]
isin = r0["isin"]
docs = ar.execute(
    "select doc_id,symbol,fiscal_year,status,n_pages from ar_docs where isin=? "
    "and fiscal_year>='2025-03-31' order by fiscal_year desc", (isin,)).fetchall()
print(r0["symbol"], isin, "ar docs:", docs[:3])
if docs:
    did = docs[0][0]
    print("chunks for doc:", eq.execute(
        "select chunk_id,chunk_index,length(content),substr(content,1,300) from document_chunks "
        "where doc_id=? order by chunk_index limit 3", (did,)).fetchall())
    print("chunks by isin:", eq.execute(
        "select doc_id,count(*) from document_chunks where isin=? group by 1 order by 2 desc limit 5",
        (isin,)).fetchall() if False else "skip")
print("deck sources:", df.execute(
    "select source_id,known_at,doc_type,title from deck_sources where isin=? order by known_at desc limit 3",
    (isin,)).fetchall())
print("concall tables:", [r[0] for r in connect_ro(D / "concall_facts.db", timeout_s=30).execute(
    "select name from sqlite_master where type='table'").fetchall()])
