"""Substrate trust layer — isolates rows that must never be served as production evidence.

The dense substrate is queried by an inference model that has no way to tell a
hand-curated parameter from a fixture row, a demo seed from a real transmission
edge, or a synthetic backfill ISIN from a listed company.  Without an explicit
trust layer those rows are indistinguishable from gold, so anything the model
retrieves from them is confident fabrication.

This module separates two distinct conditions:

``QUARANTINE``
    Rows that must not be presented as production evidence at all: test
    fixtures left in the graph, PHASE5 demo seeds, and companies carrying
    synthetic backfill ISINs.  Materialized into ``substrate_quarantine`` so
    any consumer can exclude them by key.

``DEGRADATION``
    Real rows that are structurally weak — an event with no extracted
    transmission, a ranking that only carries the unconditional ``'*'``
    regime, a company with no policy template.  These are *reported*, never
    hidden: they tell the reader how much of the answer the substrate can
    actually support.

Nothing here deletes or rewrites source rows.  Every operation is a read, plus
an idempotent write into this module's own tables.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("reality_engine.substrate_hygiene")

SEVERITY_QUARANTINE = "quarantine"
SEVERITY_DEGRADATION = "degradation"

# Tables whose entire contents are demo/seed material rather than derived facts.
# A consumer can exclude these wholesale instead of filtering row by row.
QUARANTINED_TABLES: Tuple[str, ...] = (
    "business_model_profiles_demo",
    "seed_countries_demo",
    "seed_industries_demo",
)

# Row-level quarantine rules.  ``key_expr`` selects the row identity that is
# materialized into ``substrate_quarantine``; ``where`` selects the rows.
#
# Rationale per rule (all verified against the production DB):
#   graph_fixture_nodes/edges  TEST_* cycles are reachable by any causal
#                              traversal and would be returned as a real
#                              transmission path.
#   demo_macro_events/ripples  PHASE5_DEMO_* seeds carry placeholder channels
#                              ("PHASE5_DEMO parent") and NULL targets.
#   unresolvable_ripples       Ripple rows with no target of any kind cannot
#                              be attributed to a company/sector/industry.
#   synthetic_isin_companies   INE_AUTO* placeholders are backfill scaffolding,
#                              not listed instruments.
QUARANTINE_RULES: Tuple[Dict[str, str], ...] = (
    {
        "rule_id": "graph_fixture_nodes",
        "table_name": "graph_nodes",
        "key_expr": "node_id",
        "where": "node_id LIKE 'TEST%'",
        "reason": "test fixture node left in the production causal graph",
    },
    {
        "rule_id": "graph_fixture_edges",
        "table_name": "graph_causal_edges",
        "key_expr": "edge_id",
        "where": "(source_node_id LIKE 'TEST%' OR target_node_id LIKE 'TEST%')",
        "reason": "causal edge touching a test fixture node",
    },
    {
        "rule_id": "demo_macro_events",
        "table_name": "macro_events",
        "key_expr": "event_id",
        "where": "event_id LIKE 'PHASE5%'",
        "reason": "demo-seeded macro event",
    },
    {
        "rule_id": "demo_ripples",
        "table_name": "ripple_effects",
        "key_expr": "CAST(ripple_id AS TEXT)",
        "where": "event_id LIKE 'PHASE5%'",
        "reason": "demo-seeded ripple transmission row",
    },
    {
        "rule_id": "unresolvable_ripples",
        "table_name": "ripple_effects",
        "key_expr": "CAST(ripple_id AS TEXT)",
        "where": (
            "target_type IS NULL AND target_sector_id IS NULL "
            "AND target_industry_id IS NULL AND target_company_id IS NULL"
        ),
        "reason": "ripple row with no resolvable target (cannot be attributed)",
    },
    {
        "rule_id": "synthetic_isin_companies",
        "table_name": "master_companies",
        "key_expr": "isin",
        "where": "isin LIKE 'INE_AUTO%'",
        "reason": "synthetic backfill ISIN, not a listed instrument",
    },
)

# Degradation probes: count-only structural weaknesses in otherwise real rows.
# ``sql`` must return a single integer.  ``denominator_sql`` is optional and
# used to report the affected share.
DEGRADATION_RULES: Tuple[Dict[str, str], ...] = (
    {
        "rule_id": "events_without_transmission",
        "table_name": "macro_events",
        "description": "macro event carrying no extracted affected-nodes payload",
        "sql": (
            "SELECT COUNT(*) FROM macro_events WHERE affected_nodes_json IS NULL "
            "OR TRIM(affected_nodes_json) IN ('', '[]', '{}', 'null')"
        ),
        "denominator_sql": "SELECT COUNT(*) FROM macro_events",
    },
    {
        "rule_id": "unconditional_lens_rankings",
        "table_name": "model_explainer_rankings",
        "description": "ranking rows carrying only the unconditional regime '*'",
        "sql": "SELECT COUNT(*) FROM model_explainer_rankings WHERE regime_tag = '*'",
        "denominator_sql": "SELECT COUNT(*) FROM model_explainer_rankings",
    },
    {
        "rule_id": "companies_without_policy_template",
        "table_name": "regulatory_political_risks",
        "description": "risk rows explicitly flagged no_template (no mapped policy peer)",
        "sql": (
            "SELECT COUNT(*) FROM regulatory_political_risks WHERE coverage_status = 'no_template'"
        ),
        "denominator_sql": "SELECT COUNT(*) FROM regulatory_political_risks",
    },
    {
        "rule_id": "single_country_geo_exposure",
        "table_name": "geographic_exposure",
        "description": "companies whose geographic revenue split names exactly one country",
        "sql": (
            "SELECT COUNT(*) FROM (SELECT company_id FROM geographic_exposure "
            "GROUP BY company_id HAVING COUNT(DISTINCT country_id) < 2)"
        ),
        "denominator_sql": "SELECT COUNT(DISTINCT company_id) FROM geographic_exposure",
    },
)

QUARANTINE_DDL = """
CREATE TABLE IF NOT EXISTS substrate_quarantine (
    rule_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_key TEXT NOT NULL,
    severity TEXT NOT NULL,
    reason TEXT,
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (rule_id, table_name, row_key)
)
"""


def _table_exists(conn, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (table,)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def ensure_schema(conn) -> None:
    """Create this module's own tables (idempotent)."""
    conn.execute(QUARANTINE_DDL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_substrate_quarantine_table ON substrate_quarantine(table_name)"
    )


def audit(conn) -> Dict[str, Any]:
    """Read-only trust snapshot: quarantine rule counts + degradation counts.

    Returns ``{"quarantined": {...}, "degraded": {...}, "quarantined_tables": [...],
    "totals": {...}}``.  Safe to call on a partially built DB — missing tables are
    reported as ``None`` rather than raising.
    """
    out: Dict[str, Any] = {"quarantined": {}, "degraded": {}, "quarantined_tables": [], "totals": {}}
    q_total = 0
    for rule in QUARANTINE_RULES:
        table = rule["table_name"]
        if not _table_exists(conn, table):
            out["quarantined"][rule["rule_id"]] = None
            continue
        try:
            n = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {rule['where']}"
            ).fetchone()[0]
        except Exception as exc:  # pragma: no cover - defensive on schema drift
            logger.debug("quarantine probe %s failed: %s", rule["rule_id"], exc)
            n = None
        out["quarantined"][rule["rule_id"]] = n
        q_total += int(n or 0)

    out["quarantined_tables"] = [t for t in QUARANTINED_TABLES if _table_exists(conn, t)]
    out["totals"]["quarantined_rows"] = q_total

    for rule in DEGRADATION_RULES:
        if not _table_exists(conn, rule["table_name"]):
            out["degraded"][rule["rule_id"]] = None
            continue
        try:
            n = conn.execute(rule["sql"]).fetchone()[0]
        except Exception as exc:  # pragma: no cover - defensive on schema drift
            logger.debug("degradation probe %s failed: %s", rule["rule_id"], exc)
            n = None
        denom = None
        if rule.get("denominator_sql"):
            try:
                denom = conn.execute(rule["denominator_sql"]).fetchone()[0]
            except Exception:  # pragma: no cover - defensive
                denom = None
        share = None
        if n is not None and denom:
            share = round(float(n) / float(denom), 4)
        out["degraded"][rule["rule_id"]] = {
            "table": rule["table_name"],
            "description": rule["description"],
            "count": n,
            "denominator": denom,
            "share": share,
        }
    out["totals"]["degradation_rules_flagged"] = sum(
        1 for v in out["degraded"].values() if isinstance(v, dict) and (v.get("count") or 0) > 0
    )
    return out


def apply(conn) -> Dict[str, Any]:
    """Materialize the quarantine key set.  Idempotent; never deletes source rows."""
    ensure_schema(conn)
    written: Dict[str, int] = {}
    for rule in QUARANTINE_RULES:
        table = rule["table_name"]
        if not _table_exists(conn, table):
            written[rule["rule_id"]] = 0
            continue
        try:
            rows = conn.execute(
                f"SELECT DISTINCT {rule['key_expr']} AS k FROM {table} WHERE {rule['where']}"
            ).fetchall()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("quarantine rule %s failed: %s", rule["rule_id"], exc)
            written[rule["rule_id"]] = 0
            continue
        keys = [str(r[0]) for r in rows if r[0] is not None]
        if keys:
            conn.executemany(
                "INSERT OR REPLACE INTO substrate_quarantine "
                "(rule_id, table_name, row_key, severity, reason) VALUES (?,?,?,?,?)",
                [(rule["rule_id"], table, k, SEVERITY_QUARANTINE, rule["reason"]) for k in keys],
            )
        written[rule["rule_id"]] = len(keys)
    return written


def quarantined_tables(conn) -> List[str]:
    """Tables whose entire contents are demo material (exclude wholesale)."""
    return [t for t in QUARANTINED_TABLES if _table_exists(conn, t)]


def quarantined_keys(conn, table: str, rule_ids: Optional[Sequence[str]] = None) -> set:
    """Key set quarantined for ``table``.  Empty when the trust layer was never applied."""
    if not _table_exists(conn, "substrate_quarantine"):
        return set()
    sql = "SELECT row_key FROM substrate_quarantine WHERE table_name = ?"
    params: List[Any] = [table]
    if rule_ids:
        placeholders = ",".join("?" for _ in rule_ids)
        sql += f" AND rule_id IN ({placeholders})"
        params.extend(rule_ids)
    try:
        return {str(r[0]) for r in conn.execute(sql, params).fetchall()}
    except Exception:  # pragma: no cover - defensive
        return set()


def quarantine_summary(conn, table: Optional[str] = None) -> List[Dict[str, Any]]:
    """Per-rule materialized counts, newest DB state."""
    if not _table_exists(conn, "substrate_quarantine"):
        return []
    sql = (
        "SELECT table_name, rule_id, severity, COUNT(*) AS n FROM substrate_quarantine "
        "WHERE 1=1"
    )
    params: List[Any] = []
    if table:
        sql += " AND table_name = ?"
        params.append(table)
    sql += " GROUP BY table_name, rule_id, severity ORDER BY table_name, rule_id"
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:  # pragma: no cover - defensive
        return []


def report(conn) -> Dict[str, Any]:
    """Full trust report for humans and inference models alike."""
    return {
        "audit": audit(conn),
        "materialized": quarantine_summary(conn),
        "tables": quarantined_tables(conn),
    }


def main(db=None) -> Dict[str, Any]:
    """Apply the trust layer and return the resulting report."""
    from reality_engine.db.database import db_manager

    manager = db or db_manager
    with manager.session() as conn:
        written = apply(conn)
        snap = report(conn)
        blocked = sum(1 for r in snap["audit"]["degraded"].values() if (r or {}).get("count", 0))
    return {"written": written, "blocked_degradation_rules": blocked, **snap}


if __name__ == "__main__":  # pragma: no cover - manual invocation
    print(json.dumps(main(), indent=2, default=str))
