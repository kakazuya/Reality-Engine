"""Re-run the quote/number checks over saved answers (no model calls).

Used when the verifier itself is corrected (e.g. a fiscal-period label such as '25-'26 was
being treated as a company number).  The model answer and the retrieved chunks are exactly
those that were seen live, so this cannot make retrieval or reading easier.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from tasks.arch_v4.reader_test import verify  # noqa: E402


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    results = load(HERE / "results.jsonl")
    retrieval = {r["qid"]: r for r in load(HERE / "retrieval.jsonl")}
    before = Counter(r["status"] for r in results)
    for r in results:
        if r["status"] == "error" or "answer" not in r:
            continue
        chunks = retrieval[r["qid"]]["chunks"]
        ver = verify.verify_answer(r["answer"], r["quote"], chunks, r["question"])
        r["status"] = ver["status"]
        r["verify"] = ver
    (HERE / "results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    after = Counter(r["status"] for r in results)
    print("before", dict(before))
    print("after ", dict(after))
    for r in results:
        if r["status"] != "not_stated":
            print(r["qid"], r["status"], (r.get("verify") or {}).get("missing_numbers"))


if __name__ == "__main__":
    main()
