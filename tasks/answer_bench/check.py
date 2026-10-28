"""Acceptance check for the answerability benchmark. Run: python tasks/answer_bench/check.py"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRADES = {"ANSWERED", "PARTIAL", "BLOCKED_SCHEMA", "BLOCKED_TOOL", "NOT_IN_DATA", "WRONG"}


def rows(name: str) -> list[dict]:
    p = HERE / name
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> int:
    bank = rows("../master_bank/MASTER_BANK.jsonl")
    sample = rows("SAMPLE.jsonl")
    results = rows("RESULTS.jsonl")

    assert len(sample) == 150, f"sample {len(sample)}"
    assert len({r["mid"] for r in sample}) == 150, "duplicate mid in sample"
    assert sum(1 for r in sample if r.get("regression")) == 30, "regressions"
    assert sum(1 for r in sample if r.get("source_bank") == "reddit200") == 30, "reddit200"

    fam_counts = Counter(f for r in bank for f in (r.get("family") or []))
    fam = Counter(f for r in sample for f in (r.get("family") or []))
    missing = [f for f in fam_counts if fam[f] < 3]
    assert not missing, f"family covered <3 times: {missing}"
    lvl = Counter(r["entity_level"] for r in sample)
    bank_lvl = Counter(r["entity_level"] for r in bank)
    short = [lv for lv in bank_lvl if lvl[lv] < min(5, bank_lvl[lv])]
    assert not short, f"entity level covered <5 times: {short}"

    assert len(results) == 150, f"results {len(results)}"
    assert {r["mid"] for r in results} == {r["mid"] for r in sample}, "results/sample mid mismatch"
    bad = [r["mid"] for r in results if r.get("grade") not in GRADES]
    assert not bad, f"bad grades: {bad}"
    for r in results:
        assert r.get("tool_calls", 0) <= 8, f"{r['mid']} over the 8-call budget"
        assert r.get("answer"), f"{r['mid']} has no answer text"

    print(f"ok — 150 rows, grades {dict(Counter(r['grade'] for r in results))}")
    print(f"answered {sum(1 for r in results if r['grade'] == 'ANSWERED')}/150, "
          f"regressions answered "
          f"{sum(1 for r in results if r['grade'] == 'ANSWERED' and r.get('regression'))}/30")
    return 0


if __name__ == "__main__":
    sys.exit(main())
