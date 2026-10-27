"""Print grading rows for manual review. Usage: python review.py wrong [n] ..."""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
rows = json.loads((OUT / "grades.json").read_text(encoding="utf-8"))
want = sys.argv[1] if len(sys.argv) > 1 else "wrong"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 60
if want == "stats":
    from collections import Counter
    for k in ("business_basis", "cap_tier", "bucket", "mathi"):
        pass
    print(Counter(r["business_basis"] for r in rows))
    print(Counter(r["bse_industry"][:0] or "" for r in rows))
    sys.exit()
sel = [r for r in rows if r["nse_sector_grade"] == want or r["nse_industry_grade"] == want]
if want == "soft":
    import sys as _s
    sys_path = None
    import taxonomy as tx
    sel = [r for r in rows if r["nse_sector_grade"] == "correct"
           and tx.family_of_label(r["nse_sector"]) != r["main_business"].upper()]
    print(f"{len(sel)} correct-via-family-set rows")
print(f"{len(sel)} rows")
for i, r in enumerate(sel[:limit]):
    print(f"{i:2d} {r['symbol']:<13} {r['nse_sector'][:32]:<32} "
          f"{r['nse_industry'][:28]:<28} {r['nse_basic_industry'][:26]:<26} -> "
          f"{r['main_business']:<15} {r['nse_sector_grade']:<10} | "
          f"{r['segment_split'][:64]}")
