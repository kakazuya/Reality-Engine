"""Build the business-substance analog cross-map over the embedded corpus.

    python -m reality_engine.scripts.run_business_peer_graph --top-k 20
    python -m reality_engine.scripts.run_business_peer_graph --dry-run      # gate report only

Idempotent (rows are keyed by features_version), prints an `ALL CHECKS PASSED`
block like the sibling peer-graph scripts, and never writes when --dry-run.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.db.database import db_manager  # noqa: E402
from reality_engine.processing import business_peer_graph as bpg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Business-substance analog cross-map.")
    ap.add_argument("--top-k", type=int, default=bpg.TOP_K_DEFAULT)
    ap.add_argument("--min-chunks", type=int, default=bpg.MIN_CHUNKS)
    ap.add_argument("--min-similarity", type=float, default=0.0)
    ap.add_argument("--terms-limit", type=int, default=0, help="cap companies given term extraction (0=all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    started = time.time()
    with db_manager.session() as conn:
        centroids = bpg.build_centroids(conn, min_chunks=args.min_chunks)
        n_anchorable = len(centroids.symbols)
        print(f"companies with >= {args.min_chunks} embedded chunks: {n_anchorable}")
        print(f"chunks represented: {int(centroids.chunks.sum()):,}")
        if n_anchorable < bpg.MIN_PEERS + 1:
            print(json.dumps({"status": "refused", "reason": "too few companies with enough chunks"}, indent=2))
            print("ALL CHECKS PASSED: False")
            return 1

        pairs = bpg.compute_pairs(centroids, top_k=args.top_k, min_similarity=args.min_similarity)
        n_pairs = sum(len(v) for v in pairs.values())
        print(f"anchors ranked: {len(pairs)} | pairs: {n_pairs:,}")

        target = centroids.symbols if not args.terms_limit else centroids.symbols[: args.terms_limit]
        t0 = time.time()
        terms = bpg.build_terms(conn, target)
        print(f"term profiles built for {len(terms)} companies in {time.time()-t0:.0f}s")

        result = bpg.persist(
            conn, centroids, pairs, terms,
            top_k=args.top_k, min_chunks=args.min_chunks, dry_run=args.dry_run,
        )
        print(json.dumps({"result": result, "seconds": round(time.time() - started, 1),
                          "dry_run": args.dry_run}, indent=2))

    ok = n_pairs > 0 if args.dry_run else (result.get("pairs", 0) > 0)
    print(f"ALL CHECKS PASSED: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
