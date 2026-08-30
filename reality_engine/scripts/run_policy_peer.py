"""Peer 3 (Policy Macro) — isolated substrate promotion runner.

Seeds the full canonical macro-policy canon into ``regulatory_political_risks``
and reports the policy peer gate so the ENI quantization (AggENI = SUM(severity*prob))
is queryable per stock. This is a standalone, additive peer runner — it does NOT
touch the factor / quality / ripple peers.

Usage:
    python reality_engine/scripts/run_policy_peer.py
    python reality_engine/scripts/run_policy_peer.py --universe all --include-derived --limit 10
"""

import os
import sys

# Ensure the project root (parent of reality_engine/) is importable when run as a
# standalone script (python reality_engine/scripts/run_policy_peer.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from reality_engine.processing.policy_engine import (
    seed_canonical_policy_risks_full,
    get_agg_eni,
    is_policy_approved,
    query_policy_adjusted_screen,
)


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--universe", choices=["nifty200", "nifty500", "all"], default="nifty200")
    p.add_argument("--include-derived", action="store_true", default=False, dest="include_derived")
    p.add_argument("--limit", type=int, default=None)
    try:
        args, _ = p.parse_known_args()
    except SystemExit:
        class _A: universe="nifty200"; include_derived=False; limit=None
        args=_A()
    return args


def main(universe: str | None = None, limit: int | None = None, include_derived: bool | None = None) -> None:
    cli_args = _parse_args()
    eff_universe = universe if universe is not None else cli_args.universe
    eff_limit = limit if limit is not None else cli_args.limit
    eff_include_derived = include_derived if include_derived is not None else getattr(cli_args, "include_derived", False)

    summary = seed_canonical_policy_risks_full()

    print("Peer 3 (Policy Macro) — dense substrate promotion summary")
    print("=" * 64)
    print(f"  rows_inserted     : {summary['rows_inserted']}")
    print(f"  symbols_seeded    : {summary['symbols_seeded']}")
    print(f"  policy_approved   : {len(summary['policy_approved'])} -> {summary['policy_approved']}")
    print(f"  policy_rejected   : {len(summary['policy_rejected'])} -> {summary['policy_rejected']}")

    print("\nPer-symbol AggENI (ENI = SUM(severity*prob)):")
    for sym in sorted(summary["per_symbol_counts"]):
        agg = get_agg_eni(sym)
        print(f"  {sym:12s} AggENI={agg:+7.2f}  approved={is_policy_approved(sym)}")

    print("\nv_policy_adjusted_screen emulation (net_policy_score >= 0):")
    rows = query_policy_adjusted_screen()
    for row in rows:
        print("  ", row)

    # Derived universe path: when universe != nifty200 OR --include-derived
    if eff_universe != "nifty200" or eff_include_derived:
        from reality_engine.processing.policy_engine import seed_derived_policy_risks
        from reality_engine.db.repository import Repository
        repo = Repository()
        derived = seed_derived_policy_risks(universe=eff_universe, limit=eff_limit, r=repo)
        print(f"\nderived policy risks (universe={eff_universe}, limit={eff_limit}) : {derived}")
        # Also report counts for verification
        print(f"derived inserted: {derived.get('inserted', derived.get('rows_inserted', 0))} scanned: {derived.get('scanned')}")


if __name__ == "__main__":
    main()
