"""Probe 12: look at real evidence for 3 sampled companies."""
import json
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
OUT = Path(__file__).resolve().parent
rows = json.loads((OUT / "sample.json").read_text(encoding="utf-8"))["rows"]
eq = connect_ro(D / "equity_intelligence.db", timeout_s=60)
ar = connect_ro(D / "ar_facts.db", timeout_s=60)

picks = [rows[0]]
picks += [r for r in rows if r["multi_segment"]][:1]
picks += [r for r in rows if r["bucket"].startswith("B")][:1]
for r in picks:
    isin = r["isin"]
    print("=" * 90)
    print(r["symbol"], isin, r["bucket"], r["cap_tier"], "nse=", r["nse_sector"], "/", r["nse_industry"],
          "/", r["nse_basic_industry"])
    docs = eq.execute(
        "select doc_id,title,source_type,published_date from raw_documents "
        "where isin=? and source_type='ANNUAL_REPORT' order by published_date desc limit 1", (isin,)).fetchall()
    print("ar doc:", docs)
    if docs:
        ch = eq.execute(
            "select chunk_index,substr(content,1,700) from document_chunks where doc_id=? "
            "order by chunk_index limit 3", (docs[0][0],)).fetchall()
        for x in ch:
            print("  chunk", x[0], repr(x[1][:400]))
    cats = ar.execute(
        "select category,count(*) from ar_facts where isin=? and fiscal_year>='2025-03-31' "
        "group by 1 order by 2 desc limit 12", (isin,)).fetchall()
    print("  categories:", cats)
    seg = ar.execute(
        "select item,value,unit,period,quote from ar_facts where isin=? and category='segment' "
        "and fiscal_year>='2025-03-31' limit 6", (isin,)).fetchall()
    for x in seg:
        print("  seg:", x)
