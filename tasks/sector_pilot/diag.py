"""Diagnose specific symbols: segments, text signals, core description."""
import json
import sys
from pathlib import Path

import grade

OUT = Path(__file__).resolve().parent
ev = json.loads((OUT / "evidence.json").read_text(encoding="utf-8"))
rows = {r["symbol"]: r for r in json.loads((OUT / "grades.json").read_text(encoding="utf-8"))}
for sym in sys.argv[1:]:
    r = rows.get(sym)
    if not r:
        print("missing", sym)
        continue
    e = ev[r["isin"]]
    p = grade.build_profile(e)
    print("=" * 100)
    print(sym, "|", r["nse_sector"], "/", r["nse_industry"], "/", r["nse_basic_industry"],
          "| primary:", p["primary"], "| basis:", p["mode"])
    print(" text:", dict(p["text"].most_common(6)))
    print(" core:", (p["core"] or "")[:260].replace("\n", " "))
    print(" segs:", [(s["name"][:60], s["cr"], round(s["share"], 2)) for s in p["segments"][:6]])
    raw = [(x['item'][:70], x['value'], x['unit']) for x in e['seg_rows'][:6]]
    print(" raws:", raw)
    for c in e["ar_chunks"][:2]:
        print("  chunk", c["chunk_index"], (c["text"][:280] or "").replace("\n", " "))
