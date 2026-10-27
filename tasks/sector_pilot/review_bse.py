"""Print BSE grading rows for manual review: python review_bse.py wrong 40"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
rows = json.loads((OUT / "grades.json").read_text(encoding="utf-8"))
want = sys.argv[1] if len(sys.argv) > 1 else "wrong"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 60
sel = [r for r in rows if r[f"bse_industry_grade"] == want or r[f"bse_sector_grade"] == want]
print(f"{len(sel)} rows")
for i, r in enumerate(sel[:limit]):
    print(f"{i:2d} {r['symbol']:<13} BSE {r['bse_sector'][:16]:<16} / {r['bse_industry'][:30]:<30} "
          f"| NSE {r['nse_sector'][:22]:<22} -> {r['main_business']:<15} "
          f"{r['bse_sector_grade']:<9}/{r['bse_industry_grade']:<9} | {r['segment_split'][:50]}")
