"""Build the unified entity cross-map (A + B + C) from substrate only.

    python -m reality_engine.scripts.run_entity_graph --top-k 20
    python -m reality_engine.scripts.run_entity_graph --dry-run   # report only, no writes
    python -m reality_engine.scripts.run_entity_graph --demo HAL --demo-k 8   # inspect one company

Idempotent (DELETE + rebuild inside one session), prints an ALL CHECKS PASSED block.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.processing import entity_graph as eg  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Unified entity cross-map builder.")
    ap.add_argument("--top-k", type=int, default=20, help="per-map analog edges kept per company")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--demo", default=None, help="show neighbours for this symbol after build")
    ap.add_argument("--demo-k", type=int, default=8)
    args = ap.parse_args(argv)

    stats = eg.build_graph(top_k_per_map=args.top_k) if not args.dry_run else _dry_stats(args.top_k)
    print(json.dumps(stats, indent=2))
    ok = stats.get("status") == "ok" and stats.get("edges", 0) > 0

    if args.demo:
        print(f"\n=== {args.demo.upper()} neighbours ===")
        for n in eg.neighbours(args.demo, top_k=args.demo_k):
            ev = n["evidence"]
            extra = ev.get("shared_terms") or ev.get("drivers") or ev.get("direction") or ""
            print(f"  {n['weight']:>8.3f}  {n['kind']:14s} {str(n['key'])[:46]:46s} {n['family']:16s} {str(extra)[:60]}")
    ok = stats.get("status") == "ok" and (stats.get("edges", 0) or stats.get("projected_edges", 0)) > 0


def _dry_stats(top_k: int) -> dict:
    from reality_engine.db.database import db_manager
    with db_manager.session() as conn:
        universe = eg._universe(conn)
        edges, diag = eg._analog_edges(conn, universe, top_k)
        edges2, diag2 = eg._sector_edges(universe)
        edges3, diag3 = eg._policy_edges(conn, universe)
        edges4, diag4 = eg._supply_edges(conn, universe)
        return {"status": "ok", "universe": len(universe),
                "projected_edges": len(edges) + len(edges2) + len(edges3) + len(edges4),
                "analogs": diag, "sector": diag2, "policy": diag3, "supply": diag4}


if __name__ == "__main__":
    raise SystemExit(main())
