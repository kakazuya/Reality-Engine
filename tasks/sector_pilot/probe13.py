"""Probe 13: targeted business-description chunks."""
import json
import os
import re
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
OUT = Path(__file__).resolve().parent
eq = connect_ro(D / "equity_intelligence.db", timeout_s=60)
rows = {r["symbol"]: r for r in json.loads((OUT / "sample.json").read_text(encoding="utf-8"))["rows"]}
PHRASES = ["company is engaged", "engaged in the business", "business overview",
           "the company manufactures", "our products", "product portfolio",
           "we manufacture", "company overview", "about us", "core business",
           "our business", "engaged in"]
for sym in ("GSFC", "HINDOILEXP", "RRIL", "DIGITIDE", "KDDL", "SAICAPI"):
    r = rows.get(sym)
    if not r:
        continue
    print("=" * 90)
    print(sym, r["isin"], r["nse_sector"], "/", r["nse_industry"])
    doc = eq.execute(
        "select doc_id,published_date from raw_documents where isin=? and source_type='ANNUAL_REPORT' "
        "order by published_date desc limit 1", (r["isin"],)).fetchone()
    if not doc:
        print("  no AR raw doc")
        continue
    print("  doc", doc)
    where = " or ".join([f"lower(content) like '%{p}%'" for p in PHRASES])
    chunks = eq.execute(
        f"select chunk_index,content from document_chunks where doc_id=? and ({where}) "
        "order by chunk_index limit 6", (doc[0],)).fetchall()
    print("  hits:", [(c[0], len(c[1])) for c in chunks])
    for c in chunks[:3]:
        print("   ", c[0], re.sub(r"\s+", " ", c[1])[:500])
