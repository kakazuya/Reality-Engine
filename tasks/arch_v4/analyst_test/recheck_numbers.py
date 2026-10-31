"""Recompute the number check from the saved tool log (unit-aware, after the run)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .number_check import check_answer

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    questions = {q["qid"]: q for q in load_jsonl(HERE / "questions.jsonl")}
    results = load_jsonl(RUNS / "results.jsonl")
    logs = defaultdict(list)
    for row in load_jsonl(RUNS / "tool_log.jsonl"):
        if row.get("tool") != "submit_answer":
            logs[row["qid"]].append(row["result"])
    out = []
    for row in results:
        q = questions[row["qid"]]
        chk = check_answer(row["answer"], logs[row["qid"]], row.get("calc_calls") or [], q["question"])
        out.append({"qid": row["qid"], "mid": row["mid"], "old_flagged": row["number_check"]["flagged"],
                    "new": chk})
        row["number_check"] = chk
    (RUNS / "number_recheck.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    # keep a copy of the results with the recomputed check; the transcript keeps the run-time one
    (RUNS / "results_rechecked.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    flagged = [r for r in out if r["new"]["flagged"]]
    print(f"rows={len(out)} flagged={len(flagged)} unsupported={sum(len(r['new']['unsupported']) for r in out)}")
    for r in out:
        if r["new"]["flagged"]:
            print(r["qid"], r["new"]["flagged"], "was", r["old_flagged"])


if __name__ == "__main__":
    main()
