"""Run the frozen 40-question reader test.

Order of operations per question: SQL filters (entity, doc_type, known_at) -> FTS ->
local rerank -> free Beam -> verbatim quote check -> number check.  Nothing is retrieved
after the model answers, so the quote can only come from the filtered excerpts.

The question list is read from ``questions.jsonl`` and its sha256 is checked against the
manifest before the first model call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(HERE.parents[2]))
    from tasks.arch_v4.reader_test import beam_client, db, gold, retrieve, verify
else:
    from . import beam_client, db, gold, retrieve, verify

QUESTIONS = HERE / "questions.jsonl"
MANIFEST = HERE / "questions.manifest.json"
RESULTS = HERE / "results.jsonl"
RETRIEVAL_LOG = HERE / "retrieval.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_frozen() -> tuple[list[dict], dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw = QUESTIONS.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != manifest["sha256_questions_jsonl"]:
        raise SystemExit(f"question list changed after freeze: {got} != {manifest['sha256_questions_jsonl']}")
    qs = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(qs) != manifest["n"]:
        raise SystemExit(f"expected {manifest['n']} questions, found {len(qs)}")
    return qs, manifest


def one(con, q: dict, *, use_model: bool = True) -> tuple[dict, dict]:
    t0 = time.time()
    retrieval = retrieve.retrieve_for_question(con, q, top_k=10)
    t_ret = time.time() - t0
    golden = gold.locate(con, q["isin"], q.get("ground_truth") or "", q["as_of"]) if q.get("ground_truth") else None
    top_ids = [c["chunk_id"] for c in retrieval["chunks"]]
    row = {
        "qid": q["qid"], "mid": q["mid"], "symbol": q["symbol"], "isin": q["isin"],
        "question": q["question"], "as_of": q["as_of"], "doc_types": q["doc_types"],
        "retrieval_secs": round(t_ret, 3),
        "retrieval": {k: v for k, v in retrieval.items() if k != "chunks"},
        "chunk_ids": top_ids,
        "chunk_summaries": [{"chunk_id": c["chunk_id"], "doc_type": c["doc_type"],
                             "known_at": c["known_at"], "score": c["rerank"],
                             "terms": c["term_coverage"], "page": c["page_from"]}
                            for c in retrieval["chunks"]],
        "gold": golden,
        "gold_in_topk": bool(golden and golden.get("chunk_id") in top_ids),
        "gold_rank": (top_ids.index(golden["chunk_id"]) + 1
                      if golden and golden.get("chunk_id") in top_ids else None),
    }
    if not use_model:
        row["status"] = "retrieval_only"
        row["total_secs"] = round(time.time() - t0, 3)
        return row, retrieval

    t1 = time.time()
    try:
        out = beam_client.call(q, retrieval["chunks"],
                               terms=retrieval["query_terms"]["words"])
    except Exception as exc:  # recorded per row; never silently drops a question
        row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                    "beam_secs": round(time.time() - t1, 2),
                    "total_secs": round(time.time() - t0, 3)})
        return row, retrieval

    ver = verify.verify_answer(out["answer"], out["quote"], retrieval["chunks"], q["question"])
    row.update({
        "status": ver["status"],
        "answer": out["answer"], "quote": out["quote"], "claimed_chunk_id": out.get("chunk_id"),
        "missing": out.get("missing") or "",
        "verify": ver,
        "beam": {"model": out["model"], "usage": out["usage"], "secs": out["secs"],
                 "reasoning_chars": out.get("reasoning_chars")},
        "beam_secs": round(time.time() - t1, 2),
        "total_secs": round(time.time() - t0, 3),
    })
    return row, retrieval


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--qid", action="append", default=[])
    ap.add_argument("--force", action="store_true", help="re-run qids already in results.jsonl")
    ap.add_argument("--no-model", action="store_true", help="retrieval baseline only")
    args = ap.parse_args()

    qs, manifest = check_frozen()
    todo = qs[: args.limit]
    if args.qid:
        todo = [q for q in qs if q["qid"] in set(args.qid)]
    done = {r["qid"] for r in load_jsonl(RESULTS)} if not args.force else set()
    if done:
        print(f"resume: {len(done)} questions already in results.jsonl")

    REALITY = os.environ.get("REALITY_DATA_ROOT")
    print(f"REALITY_DATA_ROOT={REALITY} frozen_sha={manifest['sha256_questions_jsonl'][:16]}")
    con = db.connect()
    results_path = RESULTS
    retrieval_path = RETRIEVAL_LOG
    if args.no_model:
        results_path = HERE / "retrieval_results.jsonl"
        retrieval_path = HERE / "retrieval.jsonl"
    mode = "a" if results_path.exists() and not args.force else "w"
    started = datetime.now(timezone.utc).isoformat()
    with open(results_path, mode, encoding="utf-8") as rf, \
            open(retrieval_path, mode, encoding="utf-8") as tf:
        for q in todo:
            if q["qid"] in done:
                continue
            t0 = time.time()
            row, retrieval = one(con, q, use_model=not args.no_model)
            rf.write(json.dumps(row, ensure_ascii=False) + "\n")
            rf.flush()
            tf.write(json.dumps({"qid": q["qid"], "mid": q["mid"], **retrieval},
                                ensure_ascii=False) + "\n")
            tf.flush()
            print(f"{q['qid']} {q['mid']} {q['symbol']:<12} {row['status']:<20} "
                  f"gold_top={row['gold_in_topk']} ret={row['retrieval_secs']:.1f}s "
                  f"total={time.time() - t0:.1f}s chunks={len(row['chunk_ids'])}")
    print(f"done at {started} -> {results_path}")


if __name__ == "__main__":
    main()
