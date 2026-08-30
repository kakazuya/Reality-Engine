"""Peer 3 (Policy Macro) — isolated substrate promotion runner.

Seeds the full canonical macro-policy canon into ``regulatory_political_risks``
and reports the policy peer gate so the ENI quantization (AggENI = SUM(severity*prob))
is queryable per stock. This is a standalone, additive peer runner — it does NOT
touch the factor / quality / ripple peers.

Usage:
    python reality_engine/scripts/run_policy_peer.py
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


def main() -> None:
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


if __name__ == "__main__":
    main()
