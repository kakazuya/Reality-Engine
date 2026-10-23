#!/usr/bin/env python3
"""Live smoke for query_embed.py (one short query per provider) + a ranking check.

Run from the repo root:
    python plugins/reality-data/tests/embed_smoke.py

Costs one embedding call per provider; keys are read from the User environment
and never printed.  The qwen8b_ar done-row coverage is reported explicitly.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "server"))
import query_embed  # noqa: E402

DATA = Path(os.environ.get("REALITY_DATA_ROOT") or
            PLUGIN_ROOT.parents[1] / "reality_engine" / "data")

QUERIES = {
    "nemotron8b": "management commentary on demand slowdown in pipes",
    "qwen8b_ar": "segment revenue PVC pipes and flexible packaging",
}


def _ppl_chunks(index: str) -> list[int]:
    ids = np.load(query_embed.index_path(index) / "chunk_ids.npy")
    done = np.load(query_embed.index_path(index) / "done.npy")
    selected = {int(x) for x in ids[done]}
    con = sqlite3.connect(f"file:{DATA / 'equity_intelligence.db'}?mode=ro", uri=True)
    try:
        out = []
        for row in con.execute(
            "select chunk_id from document_chunks where symbol='PPL' or isin='INE050001010'"
        ):
            if int(row[0]) in selected:
                out.append(int(row[0]))
        return out
    finally:
        con.close()


def _rank_of(target: int, hits: list[dict]) -> int | None:
    for pos, hit in enumerate(hits, 1):
        if int(hit["chunk_id"]) == int(target):
            return pos
    return None


def main() -> int:
    report: dict[str, object] = {"providers": {}, "ranking": {}}
    for index, question in QUERIES.items():
        query_embed.clear_cache()
        try:
            t = time.perf_counter()
            vector = query_embed.embed_query(question, index)
            ms = round((time.perf_counter() - t) * 1000, 1)
            info = query_embed.index_info(index)
            report["providers"][index] = {
                "ok": True,
                "latency_ms": ms,
                "dim": int(vector.shape[0]),
                "norm": round(float(np.linalg.norm(vector)), 6),
                "done_rows": info["done_rows"],
                "rows": info["rows"],
                "coverage_pct": info["coverage_pct"],
            }
        except Exception as exc:
            report["providers"][index] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
            }

    # Ranking evidence against the nemotron index.  PPL has no chunk in the
    # index (annual reports live in ar_facts, tier 3); report that data gap and
    # fall back to a known pipe-sector concall chunk.
    ppl = _ppl_chunks("nemotron8b")
    report["ranking"]["ppl_chunks_in_nemotron"] = len(ppl)
    target = None
    question = None
    if ppl:
        target = ppl[0]
        question = "Prakash Pipes management commentary"
    else:
        target = 2140146  # PRINCEPIPE concall chunk, known from the index
        question = "management commentary on demand slowdown in pipes"
    report["ranking"]["target_chunk_id"] = target
    report["ranking"]["query"] = question
    if report["providers"].get("nemotron8b", {}).get("ok"):
        vector = query_embed.embed_query(question, "nemotron8b")
        hits = query_embed.search_index(vector, "nemotron8b", top_k=50)
        report["ranking"]["rank_in_top50"] = _rank_of(target, hits)
        report["ranking"]["top5"] = hits[:5]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
