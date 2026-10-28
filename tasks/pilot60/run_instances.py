"""Run the query layer over every pilot instance and every master-bank original.

    $env:REALITY_DATA_ROOT = '<live data root>'
    python tasks/pilot60/run_instances.py [--kind stock|peer_set|originals] [--limit N]

Environment pointed at the pilot builds (set here unless already set):
  REALITY_CHUNKS_V3   .tmp/pilot60/chunks_v3_pilot.db   (EVIDENCE)
  REALITY_PILOT_T1    .tmp/pilot_all                    (SCREEN T1 tier)

Grading is the bench's own strict rule (``run_v0.run_case`` -> ``run_bench.finish``):
every hop must be answered, PIT evidence <= as_of, list/ranking needs >= 2 names, and
a parent case whose CASE_MAP status is a missing feed/table stays blocked for its
instances.  Instances carry no ground truth, so the grade measures answerability +
evidence + PIT only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "tasks" / "answer_bench"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(BENCH))

os.environ.setdefault("REALITY_CHUNKS_V3", str(REPO / ".tmp" / "pilot60" / "chunks_v3_pilot.db"))
os.environ.setdefault("REALITY_PILOT_T1", str(REPO / ".tmp" / "pilot_all"))

import run_bench  # noqa: E402
import run_v0  # noqa: E402
from reality_engine.query import Ctx  # noqa: E402

OUT = REPO / "tasks" / "pilot60"
BANK = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
INSTANCES = OUT / "INSTANCES.jsonl"


def originals() -> list[dict]:
    return [json.loads(line) for line in BANK.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def instances(kind: str | None) -> list[dict]:
    rows = [json.loads(line) for line in INSTANCES.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    rows = [r for r in rows if r["kind"] != "as_is"]
    return [r for r in rows if kind is None or r["kind"] == kind]


def run(cases: list[dict], label: str, ctx: Ctx, cmap: dict, out_name: str) -> list[dict]:
    results = []
    started = time.perf_counter()
    for i, case in enumerate(cases, 1):
        row = run_v0.run_case(case, ctx, cmap)
        row.update({"bucket": case.get("bucket"), "sector": case.get("sector"),
                    "kind": case.get("kind", "original"), "parent_mid": case.get("parent_mid")})
        results.append(row)
        if i % 25 == 0 or i == len(cases):
            print(f"{label} {i}/{len(cases)} {row['grade']:14s} {row['seconds']:5.2f}s "
                  f"{(case.get('question') or '')[:50]}", flush=True)
    elapsed = time.perf_counter() - started
    path = OUT / out_name
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results),
                    encoding="utf-8")
    print(f"{label}: {len(results)} rows in {elapsed:.0f}s -> {path.name}")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("stock", "peer_set", "originals"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--combine", action="store_true")
    args = ap.parse_args(argv)
    if args.combine:
        parts = sorted(OUT.glob("RESULTS_INSTANCES_part*.jsonl"))
        rows = [line for path in parts for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        (OUT / "RESULTS_INSTANCES.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(f"combined {len(parts)} parts -> RESULTS_INSTANCES.jsonl ({len(rows)} rows)")
        return 0
    cmap = run_v0.case_map()
    if args.kind in (None, "stock", "peer_set"):
        for inst in instances(None):
            parent = cmap.get(inst["parent_mid"], {})
            cmap.setdefault(inst["mid"], parent)
    ctx = Ctx()
    try:
        sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))
        import search_docs as _search_docs
        _search_docs.warm()
    except Exception:  # noqa: BLE001 - corpus search will simply degrade
        pass
    if args.kind == "originals":
        cases = originals()
        if args.limit:
            cases = cases[:args.limit]
        run(cases, "originals", ctx, cmap, "RESULTS_ORIGINALS.jsonl")
    elif args.kind in ("stock", "peer_set") or args.kind is None:
        cases = instances(args.kind)
        if args.shards > 1:
            cases = cases[args.shard::args.shards]
        if args.limit:
            cases = cases[:args.limit]
        name = ("RESULTS_INSTANCES_part%d.jsonl" % args.shard if args.shards > 1
                else "RESULTS_INSTANCES.jsonl")
        run(cases, f"instances:{args.kind or 'all'}", ctx, cmap, name)
    ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
