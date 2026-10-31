"""Run the frozen 40-question analyst-agent test.

The question list is checked against ``manifest.json`` before the first model call.
Results, every tool call/result and every transcript are written under ``runs/``.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import beam
from .agent import run_question
from .select_questions import check

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RESULTS = RUNS / "results.jsonl"
TOOL_LOG = RUNS / "tool_log.jsonl"
TRANSCRIPTS = RUNS / "transcripts"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--qid", action="append", default=[])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    questions = check()
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    todo = questions[: args.limit]
    if args.qid:
        todo = [q for q in questions if q["qid"] in set(args.qid)]
    done = {r["qid"] for r in load_jsonl(RESULTS)} if not args.force else set()
    if done:
        print(f"resume: {len(done)} questions already in results.jsonl")

    beam.api_key()  # fail before the first question if the key is missing
    RUNS.mkdir(parents=True, exist_ok=True)
    mode = "a" if RESULTS.exists() and not args.force else "w"
    started = datetime.now(timezone.utc).isoformat()
    print(f"frozen questions={len(questions)} sha256={manifest['sha256_questions_jsonl']} "
          f"start={started}")
    with open(RESULTS, mode, encoding="utf-8") as rf:
        for q in todo:
            if q["qid"] in done:
                continue
            t0 = time.time()
            row = run_question(q, transcript_path=TRANSCRIPTS / f"{q['qid']}.json",
                               tool_log_path=TOOL_LOG)
            rf.write(json.dumps(row, ensure_ascii=False) + "\n")
            rf.flush()
            print(f"{q['qid']} {q['mid']} {q.get('symbol') or q['entity_isin']:<12} "
                  f"{row['status']:<16} tools={row['n_tool_calls']:>2} "
                  f"num_flagged={len(row['number_check']['flagged'])} "
                  f"{time.time() - t0:.1f}s")
            if row["status"] == "free_tier_blocked":
                print("FREE TIER BLOCKED — stopping the run: " + str(row["error"]))
                break
    print(f"done at {datetime.now(timezone.utc).isoformat()} -> {RESULTS}")


if __name__ == "__main__":
    main()
