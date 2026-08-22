"""SQLite-backed causal knowledge graph operations."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from reality_engine.db.database import db_manager


class CausalGraphEngine:
    """Maintains and traverses the directed causal graph."""

    def __init__(self, manager=None):
        self.db = manager or db_manager

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM graph_nodes ORDER BY name"
            )]

    def get_all_edges(self) -> List[Dict[str, Any]]:
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM graph_causal_edges ORDER BY created_at, edge_id"
            )]

    def add_graph_node(
        self,
        node_id: str,
        node_type: str,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self.db.session() as conn:
            conn.execute(
                """INSERT INTO graph_nodes(node_id, node_type, name, metadata_json)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(node_id) DO UPDATE SET node_type=excluded.node_type,
                   name=excluded.name, metadata_json=excluded.metadata_json""",
                (node_id, node_type, name, json.dumps(metadata or {}, ensure_ascii=False)),
            )
        return node_id

    def add_causal_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        relationship_type: str = "CAUSAL",
        impact_direction: Any = 1.0,
        elasticity_score: float = 1.0,
        transmission_mechanism: str = "direct transmission",
        evidence_document_ref: Optional[str] = None,
        confidence_score: float = 1.0,
        edge_id: Optional[str] = None,
    ) -> str:
        edge_id = edge_id or f"EDGE_{uuid.uuid4().hex}"
        with self.db.session() as conn:
            conn.execute(
                """INSERT INTO graph_causal_edges
                   (edge_id, source_node_id, target_node_id, relationship_type,
                    impact_direction, elasticity_score, transmission_mechanism,
                    evidence_document_ref, confidence_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(edge_id) DO UPDATE SET source_node_id=excluded.source_node_id,
                   target_node_id=excluded.target_node_id, relationship_type=excluded.relationship_type,
                   impact_direction=excluded.impact_direction, elasticity_score=excluded.elasticity_score,
                   transmission_mechanism=excluded.transmission_mechanism,
                   evidence_document_ref=excluded.evidence_document_ref,
                   confidence_score=excluded.confidence_score""",
                (edge_id, source_node_id, target_node_id, relationship_type,
                 impact_direction, elasticity_score, transmission_mechanism,
                 evidence_document_ref, confidence_score),
            )
        return edge_id

    def trace_causal_chain(
        self, start_node_id: str, max_hops: int = 3, impact_filter: str = "ALL"
    ) -> List[Dict[str, Any]]:
        if max_hops < 1:
            return []
        impact_filter = impact_filter.upper()
        if impact_filter not in {"ALL", "BENEFICIARIES_ONLY", "VICTIMS_ONLY"}:
            raise ValueError("impact_filter must be ALL, BENEFICIARIES_ONLY, or VICTIMS_ONLY")
        predicate = ""
        if impact_filter == "BENEFICIARIES_ONLY":
            predicate = " AND cumulative_impact > 0"
        elif impact_filter == "VICTIMS_ONLY":
            predicate = " AND cumulative_impact < 0"
        query = f"""
            WITH RECURSIVE causal_path(source_node_id, current_node_id,
                cumulative_impact, depth, mechanisms, visited) AS (
                SELECT ?, ?, CAST(1.0 AS REAL), 0, '', '|' || ? || '|'
                UNION ALL
                SELECT cp.source_node_id, e.target_node_id,
                    cp.cumulative_impact * CAST(
                        CASE WHEN e.impact_direction IN ('NEGATIVE', 'VICTIM', '-1') THEN -1.0
                             WHEN e.impact_direction IN ('POSITIVE', 'BENEFICIARY', '1') THEN 1.0
                             ELSE COALESCE(e.impact_direction, '1.0') END AS REAL
                    ) * COALESCE(e.elasticity_score, 1.0),
                    cp.depth + 1,
                    CASE WHEN cp.mechanisms = '' THEN e.transmission_mechanism
                         ELSE cp.mechanisms || ' | ' || e.transmission_mechanism END,
                    cp.visited || e.target_node_id || '|'
                FROM causal_path cp
                JOIN graph_causal_edges e ON e.source_node_id = cp.current_node_id
                WHERE cp.depth < ?
                  AND instr(cp.visited, '|' || e.target_node_id || '|') = 0
            )
            SELECT cp.current_node_id AS node_id, n.name, n.node_type, n.metadata_json,
                   cp.cumulative_impact, cp.depth, cp.mechanisms
            FROM causal_path cp
            JOIN graph_nodes n ON n.node_id = cp.current_node_id
            WHERE cp.depth > 0 {predicate}
            ORDER BY cp.depth, ABS(cp.cumulative_impact) DESC, cp.current_node_id
        """
        with self.db.session() as conn:
            rows = conn.execute(query, (start_node_id, start_node_id, start_node_id, max_hops)).fetchall()
            return [dict(row) for row in rows]


causal_engine = CausalGraphEngine()
