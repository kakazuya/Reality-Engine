"""Independent check of the ripple bank that the acceptance test does not cover.

Verifies: every policy_events id cited in the questions exists with quote_ok=1; every entity came
from master_companies; every ground truth has its query; hop counts; trigger sourcing. Read-only.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

BANK = REPO / "tasks" / "QUESTION_BANK_RIPPLE_2026-10-28.jsonl"
rows = [json.loads(l) for l in BANK.open(encoding="utf-8")]

from reality_engine.db.readonly import connect_ro  # noqa: E402
DATA = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
con = connect_ro(DATA / "equity_intelligence.db", timeout_s=90)

fails = []
ids = sorted({int(x) for r in rows for x in re.findall(r"id=(\d{4,6})", json.dumps(r))})
for i in ids:
    row = con.execute("SELECT policy_name, quote_ok FROM policy_events WHERE id=?", (i,)).fetchone()
    if not row or row[1] != 1:
        fails.append(f"policy id {i} missing or not quote_ok=1: {row}")

for r in rows:
    for e in r["entities"]:
        got = con.execute("SELECT isin FROM master_companies WHERE nse_symbol=?", (e["symbol"],)).fetchone()
        if not got or got[0] != e["isin"]:
            fails.append(f"{r['qid']} entity {e['symbol']} does not resolve to {e['isin']}")
    if r["rubric"]["ground_truth"] and not r["rubric"]["ground_truth_query"]:
        fails.append(f"{r['qid']} ground truth without a query")
    if not r["trigger"]["sourced"]:
        fails.append(f"{r['qid']} unsourced trigger")

ext = [r for r in rows if not r["trigger"]["in_store"]]
nobad = [r["qid"] for r in ext if r["chain"][0]["exists_today"] == "yes"]
if nobad:
    fails.append(f"external trigger with an answerable hop 1: {nobad}")

dups = [q for q, n in Counter(r["question"] for r in rows).items() if n > 1]
if dups:
    fails.append(f"duplicate question text: {len(dups)}")

print(f"rows {len(rows)} · hops {sum(len(r['chain']) for r in rows)} · "
      f"symbols {len({e['symbol'] for r in rows for e in r['entities']})} · "
      f"industries {len({e['basic_industry'] for r in rows for e in r['entities']})} · "
      f"policy ids cited {len(ids)} · external triggers {len(ext)}")
print("hops per row:", dict(Counter(len(r["chain"]) for r in rows)))
print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails[:20]:
    print("  -", f)
sys.exit(1 if fails else 0)
