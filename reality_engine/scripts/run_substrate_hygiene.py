"""Substrate trust layer promotion — materialize quarantine keys, print degradation.

Run:
    python -m reality_engine.scripts.run_substrate_hygiene
"""

from __future__ import annotations

import json
import logging
import os
import sys

# Make the project root importable regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from reality_engine.db.repository import Repository
from reality_engine.processing import substrate_hygiene as hygiene

logger = logging.getLogger("reality_engine.scripts.run_substrate_hygiene")


def main() -> dict:
    repo = Repository()
    with repo.db.session() as conn:
        before = hygiene.audit(conn)
        written = hygiene.apply(conn)
        after = hygiene.audit(conn)
        summary = hygiene.quarantine_summary(conn)
        demo_tables = hygiene.quarantined_tables(conn)

        # Verification: a known fixture key must be filterable, and a production
        # key must NOT be.
        fixture_keys = hygiene.quarantined_keys(conn, "graph_nodes")
        edge_keys = hygiene.quarantined_keys(conn, "graph_causal_edges")
        isin_keys = hygiene.quarantined_keys(conn, "master_companies")
        production_node_clear = conn.execute(
            "SELECT 1 FROM graph_nodes WHERE node_id = 'UNION_BUDGET_2026_RAIL_CAPEX'"
        ).fetchone() is not None

    return {
        "written_total": sum(written.values()),
        "written_by_rule": written,
        "quarantine_rule_counts": before["quarantined"],
        "quarantined_rows_reported": before["totals"]["quarantined_rows"],
        "materialized_groups": len(summary),
        "demo_tables": demo_tables,
        "degradation": after["degraded"],
        "verify_fixture_node_keys": len(fixture_keys),
        "verify_fixture_edge_keys": len(edge_keys),
        "verify_synthetic_isin_keys": len(isin_keys),
        "verify_production_node_excluded": production_node_clear and (
            "UNION_BUDGET_2026_RAIL_CAPEX" not in fixture_keys
        ),
    }


if __name__ == "__main__":
    result = main()
    print("=" * 75)
    print("  SUBSTRATE TRUST LAYER - QUARANTINE + DEGRADATION")
    print("=" * 75)
    print(f"  quarantine rules reported: {result['quarantined_rows_reported']} rows")
    for rule, count in (result["quarantine_rule_counts"] or {}).items():
        print(f"    {rule:28s}: {count}")
    print(f"  materialized groups      : {result['materialized_groups']}")
    print(f"  demo tables excluded     : {result['demo_tables']}")
    print("  degradation (real but structurally weak rows):")
    for rule, payload in (result["degradation"] or {}).items():
        if isinstance(payload, dict):
            print(f"    {rule:36s}: {payload.get('count')} / {payload.get('denominator')} "
                  f"(share {payload.get('share')}) - {payload.get('description')}")
    print("=" * 75)
    ok = (
        result["verify_fixture_node_keys"] > 0
        and result["verify_fixture_edge_keys"] > 0
        and result["verify_synthetic_isin_keys"] > 0
        and result["verify_production_node_excluded"]
    )
    print("  ALL CHECKS PASSED:" if ok else "  CHECKS FAILED:", ok)
    print(json.dumps({"written_by_rule": result["written_by_rule"]}, indent=2))
