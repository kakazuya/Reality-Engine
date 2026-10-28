"""Run the answer bench on the pilot-30 case subset, with and without chunks_v3.

    python tasks/pilot_t2/run_bench_subset.py --label before
    python tasks/pilot_t2/run_bench_subset.py --label after

`after` sets REALITY_CHUNKS_V3 to the pilot store (default `.tmp/pilot/chunks_v3_pilot.db`),
so the EVIDENCE planner reads chunks_v3 first.  The grading contract is the
bench's own: this only filters cases and reuses `run_v0.run_case`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "tasks" / "answer_bench"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(BENCH))

import run_bench  # noqa: E402
import run_v0  # noqa: E402
from reality_engine.query import Ctx  # noqa: E402

OUT = Path(__file__).resolve().parent
DB = Path(os.environ.get("REALITY_CHUNKS_V3") or (REPO / ".tmp" / "pilot" / "chunks_v3_pilot.db"))
ISIN_RE = re.compile(r"INE[A-Z0-9]{9}")


def pilot_isins() -> set[str]:
    spec = (REPO / "tasks" / "arch_v3" / "PILOT_SPEC.md").read_text(encoding="utf-8")
    return set(ISIN_RE.findall(spec))


def isins_of(case: dict, resolve) -> set[str]:
    found = set(ISIN_RE.findall(case.get("question") or ""))
    for entity in case.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        for key in ("isin", "symbol", "nse_symbol", "bse_symbol"):
            value = entity.get(key)
            if not value:
                continue
            text = str(value).strip()
            if text.startswith("INE"):
                found.add(text)
                continue
            try:
                result = resolve(text)
                matches = result.get("matches") or []
                if matches and matches[0].get("isin"):
                    found.add(matches[0]["isin"])
            except Exception:  # noqa: BLE001 - an unresolved entity is just not selected
                pass
    return found


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * pct))]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", choices=("before", "after"), required=True)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv[1:])

    if args.label == "after":
        if not DB.is_file():
            print(f"missing chunks_v3 store: {DB}")
            return 2
        os.environ["REALITY_CHUNKS_V3"] = str(DB)
    else:
        os.environ.pop("REALITY_CHUNKS_V3", None)

    cases = run_bench.load_cases()
    ctx = Ctx()
    resolve = ctx.tool("resolve")
    pilot = pilot_isins()
    subset = []
    for case in cases:
        if isins_of(case, resolve) & pilot:
            subset.append(case)
    ctx.close()
    if args.limit:
        subset = subset[:args.limit]
    print(f"{args.label}: {len(subset)} of {len(cases)} cases touch a pilot ISIN; "
          f"chunks_v3={os.environ.get('REALITY_CHUNKS_V3') or 'off'}")

    ctx = Ctx()
    try:
        sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))
        import search_docs as _search
        _search.warm()
    except Exception:  # noqa: BLE001 - corpus search degrades on its own
        pass
    cmap = run_v0.case_map()
    started = time.perf_counter()
    rows = []
    for i, case in enumerate(subset, 1):
        row = run_v0.run_case(case, ctx, cmap)
        rows.append(row)
        print(f"{i:3d} {case['mid']} {row['grade']:14s} {row['seconds']:5.2f}s "
              f"{(case.get('question') or '')[:60]}", flush=True)
    ctx.close()
    elapsed = time.perf_counter() - started
    run_v0.apply_recheck(rows)
    out = OUT / f"bench_{args.label}.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    counts = Counter(r["grade"] for r in rows)
    ev = [c["s"] for r in rows for c in (r.get("calls") or [])
          if c.get("tool") == "EVIDENCE" and c.get("s") is not None]
    summary = {
        "label": args.label, "cases": len(rows),
        "chunks_v3": os.environ.get("REALITY_CHUNKS_V3") or "",
        "grades": dict(counts), "wall_s": round(elapsed, 1),
        "evidence_calls": len(ev),
        "evidence_p50_s": round(percentile(ev, 0.50), 3),
        "evidence_p95_s": round(percentile(ev, 0.95), 3),
        "evidence_max_s": round(max(ev), 3) if ev else 0.0,
        "answered": sum(1 for r in rows if r["grade"] == "ANSWERED"),
        "partial": sum(1 for r in rows if r["grade"] == "PARTIAL"),
        "mids": [r["mid"] for r in rows],
    }
    (OUT / f"bench_{args.label}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
