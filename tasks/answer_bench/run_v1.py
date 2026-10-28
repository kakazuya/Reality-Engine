"""Run the 150-case bench sample through the query layer v1.

v1 = sub-question decomposition (each sub-question gets its own planner chain
through the router), named/latest-document preference in FACTS/EVIDENCE,
metric-family relevance filtering in answer assembly, and a local BM25 +
entity/metric/date rerank of EVIDENCE passages.  Grading is the bench's own
``run_bench.finish`` (so the bench grade stays comparable with v0); the strict
v1 contract is applied separately by ``grade_v1.py``.

    python tasks/answer_bench/run_v1.py             # all 150
    python tasks/answer_bench/run_v1.py MB0001 ...  # a subset (RESULTS_v1_smoke)

Output: RESULTS_v1.jsonl next to this file.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import run_bench  # noqa: E402
from reality_engine.query import Ctx, answer  # noqa: E402


class Budget:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.n = 0
        self.spent = 0.0

    def add(self, tool: str, seconds: float) -> None:
        self.rows.append({"tool": tool, "args": [], "s": round(seconds, 3), "ok": True})
        self.n += 1
        self.spent += seconds


def case_map() -> dict[str, dict]:
    path = REPO / "tasks" / "arch_v3" / "CASE_MAP.jsonl"
    return {row["mid"]: row for row in
            (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def run_case(case: dict, ctx: Ctx, cmap: dict[str, dict]) -> dict:
    mid = case["mid"]
    case = dict(case)
    case["case_status"] = str(cmap.get(mid, {}).get("status") or "")
    case["status_reason"] = cmap.get(mid, {}).get("status_reason")
    started = time.perf_counter()
    out = answer(case, ctx, close=False)
    budget = Budget()
    results = []
    for hop in out["hops"]:
        budget.add(hop["hop"], hop.get("seconds", 0.0))
        if hop["hop"] == "resolve" and (hop["ok"] or hop["na"]):
            continue
        results.append({"hop": hop["hop"], "ok": hop["ok"], "na": hop["na"],
                        "detail": hop.get("detail"), "evidence": hop.get("evidence") or [],
                        "why": hop.get("why"), "gap": hop.get("gap")})
    graded = run_bench.finish(case, budget, results)
    body_ok = [hop for hop in out["hops"]
               if hop["hop"] != "resolve" and hop["ok"] and not hop["na"]]
    if graded["grade"] == "ANSWERED" and not body_ok:
        graded["grade"] = "PARTIAL"
        graded["blocker"] = "no planner produced evidence for this ask"
    if graded["grade"] == "ANSWERED" and not out["complete"]:
        graded["grade"] = "PARTIAL"
        graded["blocker"] = "a sub-question has no evidence-backed content"
    status = str(case.get("case_status") or "")
    if graded["grade"] == "ANSWERED" and status.startswith(("needs_new_fetch:",
                                                              "needs_new_table:")):
        kind, name = status.split(":", 1)
        graded["grade"] = "BLOCKED_TOOL" if kind == "needs_new_fetch" else "BLOCKED_SCHEMA"
        graded["blocker"] = f"CASE_MAP blocker {status}: v1 measured only an adjacent held-data part"
    if graded["grade"] == "NOT_IN_DATA" and status.startswith(("needs_new_fetch:",
                                                               "needs_new_table:")):
        kind, name = status.split(":", 1)
        graded["grade"] = "BLOCKED_TOOL" if kind == "needs_new_fetch" else "BLOCKED_SCHEMA"
        graded["blocker"] = f"{name} not held: " + (graded.get("blocker") or "")
    graded["seconds"] = round(time.perf_counter() - started, 3)
    graded["pit_violations"] = out["pit_violations"]
    graded["v1"] = {"chain": out["plan"]["chain"], "status": case["case_status"],
                    "nid": out["nid"], "complete": out["complete"],
                    "answer": out["answer"]}
    graded["subs"] = out["subs"]
    return graded


def main(argv: list[str]) -> int:
    cases = run_bench.load_cases()
    cmap = case_map()
    mid_gap = run_bench.gap_map()[1]
    only = {arg for arg in argv[1:] if arg.startswith("MB")}
    if only:
        cases = [case for case in cases if case["mid"] in only]
    ctx = Ctx()
    try:  # the MCP server warms these at startup; the harness must do the same
        sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))
        import search_docs as _search_docs
        _search_docs.warm()
    except Exception:  # noqa: BLE001 - corpus search will simply degrade
        pass
    started = time.perf_counter()
    rows = []
    for index, case in enumerate(cases, 1):
        row = run_case(case, ctx, cmap)
        row["gap"] = row.get("gap") or mid_gap.get(case["mid"])
        rows.append(row)
        print(f"{index:3d} {case['mid']} {row['grade']:14s} "
              f"{sum(1 for sub in row.get('subs') or [] if sub.get('answered'))}/"
              f"{len(row.get('subs') or [])}subs {row['tool_calls']}c "
              f"{row['seconds']:5.2f}s  {(case.get('question') or '')[:55]}", flush=True)
    ctx.close()
    elapsed = time.perf_counter() - started
    path = HERE / ("RESULTS_v1_smoke.jsonl" if only else "RESULTS_v1.jsonl")
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["grade"]] = counts.get(row["grade"], 0) + 1
    print(f"\n{len(rows)} rows in {elapsed:.1f}s  {counts}")
    print(f"PIT violations: {sum(1 for row in rows if row['pit_violations'])}")
    print(f"complete (all sub-questions): {sum(1 for row in rows if row['v1']['complete'])}")
    print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
