"""Writes tasks/night_loop/questions/<SYMBOL>.jsonl from common.py and co_*.py; prints counts and own checks.
Run: python tasks/night_loop/questions/gen/build.py"""
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import co_a, co_b, co_c, co_extra  # noqa: E402
from common import make, universal  # noqa: E402

COMPANIES = [(co_a.KEC, co_a.kec), (co_a.BAJ, co_a.baj), (co_a.HIN, co_a.hin), (co_b.HDFC, co_b.hdfc), (co_b.SBI, co_b.sbi),
             (co_b.INFY, co_b.infy), (co_b.SUN, co_b.sun), (co_c.MAR, co_c.maruti), (co_c.HUL, co_c.hul), (co_c.ETE, co_c.eternal)]
LENSES = ("results", "segments", "orders", "guidance", "balance_sheet", "capital_allocation", "ownership", "credit_ratings",
          "governance", "technical", "valuation")
VOC = json.loads((HERE.parent / "sector_vocab.json").read_text(encoding="utf-8"))


def toks(t):
    return frozenset(x for x in re.findall(r"[a-z0-9%]+", t.lower()) if len(x) > 1 or x.isdigit())


def main():
    summary = {}
    for co, fn in COMPANIES:
        rows = []
        for n, spec in enumerate(universal(co) + fn() + co_extra.ripple_all(co) + co_extra.EXTRA.get(co.sym, []), 1):
            row = make(co, n, spec)
            if co.sym == "HINDALCO":
                for key in ("text",):
                    row[key] = row[key].replace("last four quarters", "last three reported quarters").replace("last 4 results", "last 3 results")
                row["variations"] = [v.replace("last four quarters", "last three reported quarters").replace("last 4 results", "last 3 results") for v in row["variations"]]
            rows.append(row)
        (HERE.parent / f"{co.sym}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        allowed = set(VOC[co.sector]) | set(VOC["universal"]) | set(VOC["technical"])
        bad = sorted({m for r in rows for m in r["sector_fit"] if m not in allowed}
                     | {x["metric"] for r in rows for x in r["needs"] if x["kind"] == "row" and x.get("metric") and x["metric"] not in allowed})
        lens = collections.Counter(r["lens"] for r in rows)
        orders = collections.Counter(r["order"] for r in rows)
        sets = [(r["qid"], toks(r["text"])) for r in rows]
        dup = [(a[0], b[0]) for i, a in enumerate(sets) for b in sets[i + 1:] if len(a[1] & b[1]) / max(1, len(a[1] | b[1])) > 0.8]
        leftover = [r["qid"] for r in rows if "{" in r["text"]]
        docs = collections.Counter(x["doc_type"] for r in rows for x in r["needs"] if x["kind"] == "text")
        print(co.sym, len(rows), "orders", {k: round(v / len(rows), 2) for k, v in sorted(orders.items())},
              "lens<10", {k: lens[k] for k in LENSES if lens[k] < 10}, "dups", dup, "left", leftover, "docs", dict(docs))
        if bad:
            print("  NOT IN VOCAB", bad)
        summary[co.sym] = len(rows)
    print(summary, sum(summary.values()))


if __name__ == "__main__":
    main()
