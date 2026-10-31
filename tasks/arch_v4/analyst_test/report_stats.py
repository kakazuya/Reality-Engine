"""Performance and PIT statistics for the analyst-agent report."""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    rows = load_jsonl(RUNS / "results.jsonl")
    logs = load_jsonl(RUNS / "tool_log.jsonl")
    grades = load_jsonl(HERE / "grades.jsonl")
    questions = {q["qid"]: q for q in load_jsonl(HERE / "questions.jsonl")}
    secs = [r["total_secs"] for r in rows]
    usage_in = [r["usage"]["prompt_tokens"] for r in rows]
    usage_out = [r["usage"]["completion_tokens"] for r in rows]
    calls = [r["n_tool_calls"] for r in rows]
    errs = Counter()
    for log in logs:
        if log.get("error"):
            errs[log["error"]["code"]] += 1
    refused = sum(1 for log in logs if (log.get("error") or {}).get("code") == "as_of_refused")
    pit = sum(len(r.get("pit_breach") or []) for r in rows)
    recheck = {r["qid"]: r["new"] for r in load_jsonl(RUNS / "number_recheck.jsonl")}
    flagged = [qid for qid, c in recheck.items() if c["flagged"]]
    unsupported = [qid for qid, c in recheck.items() if c["unsupported"]]
    out = {
        "n": len(rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "secs_total": round(sum(secs), 2),
        "secs_mean": round(statistics.mean(secs), 2),
        "secs_median": round(statistics.median(secs), 2),
        "secs_min": round(min(secs), 2),
        "secs_max": round(max(secs), 2),
        "tool_calls_total": sum(calls),
        "tool_calls_mean": round(statistics.mean(calls), 2),
        "tool_calls_max": max(calls),
        "usage_in_total": sum(usage_in),
        "usage_out_total": sum(usage_out),
        "usage_in_mean": round(statistics.mean(usage_in), 1),
        "usage_out_mean": round(statistics.mean(usage_out), 1),
        "tool_error_codes": dict(errs),
        "as_of_refused": refused,
        "pit_breaches": pit,
        "number_flagged_rows": len(flagged),
        "number_unsupported_rows": len(unsupported),
        "flagged": flagged,
        "unsupported": unsupported,
        "estimate_2681_secs": round(sum(secs) / len(rows) * 2681, 0),
        "estimate_2681_hours": round(sum(secs) / len(rows) * 2681 / 3600, 2),
        "estimate_2681_in_tokens": round(sum(usage_in) / len(rows) * 2681),
        "estimate_2681_out_tokens": round(sum(usage_out) / len(rows) * 2681),
        "judgement_rows": sum(1 for q in questions.values() if q["judgement_or_study"]),
    }
    print(json.dumps(out, indent=1))
    (RUNS / "stats.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
