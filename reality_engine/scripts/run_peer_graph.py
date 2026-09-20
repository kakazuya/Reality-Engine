"""Analog peer graph promotion — precompute substrate nearest neighbours.

Run:
    python -m reality_engine.scripts.run_peer_graph [--top-k 20] [--dry-run]
"""

from __future__ import annotations

import json
import logging
import os
import sys

# Make the project root importable regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from reality_engine.db.repository import Repository
from reality_engine.processing import peer_graph

logger = logging.getLogger("reality_engine.scripts.run_peer_graph")


def _parse_args():
    import argparse

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--top-k", type=int, default=peer_graph.TOP_K_DEFAULT)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--include-quarantined", action="store_true")
    try:
        args, _ = p.parse_known_args()
    except SystemExit:  # pragma: no cover - argparse fallback
        class _A:
            top_k = peer_graph.TOP_K_DEFAULT
            dry_run = False
            include_quarantined = False
        args = _A()
    return args


def main(top_k: int | None = None, apply: bool = True, include_quarantined: bool = False) -> dict:
    cli = _parse_args()
    eff_top_k = top_k if top_k is not None else cli.top_k
    eff_apply = apply and not cli.dry_run
    eff_include = include_quarantined or cli.include_quarantined

    repo = Repository()
    result = peer_graph.main(
        top_k=eff_top_k,
        db=repo.db,
        apply=eff_apply,
        include_quarantined=eff_include,
    )

    # --- Verification -------------------------------------------------------
    with repo.db.session() as conn:
        probe = peer_graph.neighbours(conn, "TITAGARH", top_k=5)
        run = peer_graph.latest_run(conn) or {}
        max_sim = conn.execute(
            "SELECT MAX(similarity) FROM company_peer_graph"
        ).fetchone()[0] if eff_apply and result.get("status") == "ok" else None
        total_pairs = conn.execute(
            "SELECT COUNT(*) FROM company_peer_graph"
        ).fetchone()[0] if eff_apply and result.get("status") == "ok" else 0

    return {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "n_symbols": result.get("n_symbols"),
        "n_anchors": result.get("n_anchors"),
        "n_active_features": len(result.get("active_features") or []),
        "dropped_features": result.get("dropped_features"),
        "baseline_similarity_median": result.get("baseline_similarity_median"),
        "pairs_written": result.get("written", 0),
        "pairs_in_table": total_pairs,
        "max_similarity": max_sim,
        "quarantined_excluded": result.get("quarantined_excluded"),
        "contaminated_earnings_values": result.get("contaminated_earnings_values"),
        "latest_run_status": run.get("status"),
        "probe_TITAGARH": probe,
    }


if __name__ == "__main__":
    res = main()
    print("=" * 75)
    print("  PEER GRAPH (ANALOG NEIGHBOURS OVER THE DENSE SUBSTRATE)")
    print("=" * 75)
    print(f"  status                 : {res['status']}")
    if res.get("reason"):
        print(f"  reason                 : {res['reason']}")
    print(f"  symbols                : {res['n_symbols']}")
    print(f"  anchors (>= floor)     : {res['n_anchors']}")
    print(f"  active features        : {res['n_active_features']}")
    print(f"  dropped features       : {res['dropped_features']}")
    print(f"  pairs written          : {res['pairs_written']} (table now {res['pairs_in_table']})")
    print(f"  max similarity         : {res['max_similarity']}")
    print(f"  median baseline sim    : {res['baseline_similarity_median']}")
    print(f"  quarantined excluded   : {res['quarantined_excluded']}")
    print(f"  contaminated earnings  : {res['contaminated_earnings_values']}")
    print("  probe: TITAGARH analogues")
    for p in res["probe_TITAGARH"]:
        driver = p["drivers"][0]["feature"] if p["drivers"] else "-"
        print(f"    #{p['rank']:<2} {p['peer']:<14} sim={p['similarity']:<7} "
              f"lift={p['lift']:<8} coverage={p['coverage']:<6} top_driver={driver}")
    print("=" * 75)
    if res["status"] == "insufficient_signal":
        ok = res["pairs_written"] == 0
    else:
        ok = (
            res["pairs_written"] > 0
            and res["pairs_in_table"] == res["pairs_written"]
            and (res["max_similarity"] or 0) <= 1.0001
            and bool(res["probe_TITAGARH"])
        )
    print("  ALL CHECKS PASSED:" if ok else "  CHECKS FAILED:", ok)
    print(json.dumps(res["probe_TITAGARH"][:1], indent=2)[:900])
