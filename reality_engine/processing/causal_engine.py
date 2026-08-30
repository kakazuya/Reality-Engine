"""SQLite-backed causal knowledge graph operations."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any, Dict, List, Optional

from reality_engine.db.database import db_manager
from reality_engine.db.repository import Repository


class CausalGraphEngine:
    """Maintains and traverses the directed causal graph."""

    def __init__(self, manager=None):
        self.db = manager or db_manager
        self.repo = Repository(self.db)

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

    # ------------------------------------------------------------------
    # Fundamental Reality Engine: Ripple DAG PN/MN/S (PDF p5)
    #
    #   PN = ∏ Pi            (product of probabilities along the path root->node)
    #   MN = RawN × PN × β   (β = transmission_elasticity)
    #   S  = |MN| × 20 / (1 + ln(1 + Lag))   (Lag = cumulative lag along path)
    #
    # A recursive CTE (PostgreSQL / SQLite-with-math-functions) is attempted
    # first; if ln() is unavailable the same math is computed in Python over the
    # real ripple_effects rows. When an event has no ripple rows we fall back to
    # the canonical steel-duty demo chain so callers always get a deterministic
    # ordered S DESC result.
    # ------------------------------------------------------------------
    def ensure_ripple_schema(self, manager=None) -> None:
        """Idempotently ensure ripple_effects + geographic_exposure tables exist."""
        mgr = manager or self.db
        self.repo.ensure_ripple_effects_schema(mgr)
        self.repo.ensure_geographic_exposure_schema(mgr)

    def trace_ripple_chain(self, event_id: int, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Recursive CTE for ripple_effects: PN=∏Pi, MN=RawN×PN×β, S=|MN|×20/(1+ln(1+Lag)).

        Returns the chain ordered by S DESC. Uses the real ripple_effects table
        when rows exist for ``event_id``; otherwise falls back to the steel-duty
        demo chain. Each entry carries ``pn``, ``mn``, ``lag`` (cumulative), ``s``
        and a ``pruned`` flag (PN < 0.08 or S < 5.0).
        """
        return self._compute_chain(event_id, max_hops)

    def get_ripple_chain_for_event(self, event_id: Any, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Return the full PN/MN/lag/S chain for an event (additive alias of trace)."""
        return self._compute_chain(event_id, max_hops)

    def should_prune_ripple_row(self, pn: float, s: float,
                                pn_cutoff: float = 0.08, s_floor: float = 5.0) -> bool:
        """Wave B2 pruning rule: prune when PN<0.08 or S(t)<5.0.

        Distinct from pruning_engine.should_prune_ripple (which also gates on
        raw*prob<0.5); here the gate is purely the PN and S thresholds per the
        causal DAG spec.
        """
        return (pn is not None and pn < pn_cutoff) or (s is not None and s < s_floor)

    # --- geographic_exposure stubs (supply-chain peer) -----------------
    def ensure_geographic_exposure_schema(self, manager=None) -> None:
        self.repo.ensure_geographic_exposure_schema(manager or self.db)

    def upsert_geographic_exposure(self, company_id: int, country_id: Any,
                                   revenue_share_pct: float = 0.0,
                                   asset_exposure_pct: float = 0.0,
                                   manager=None) -> None:
        self.repo.upsert_geographic_exposure(
            company_id, country_id, revenue_share_pct, asset_exposure_pct,
            manager or self.db,
        )

    # ------------------------------------------------------------------
    # Internal chain computation
    # ------------------------------------------------------------------
    def _fetch_ripple_rows(self, event_id: Any) -> List[Dict[str, Any]]:
        self.ensure_ripple_schema()
        try:
            with self.db.session() as conn:
                rows = conn.execute(
                    """SELECT ripple_id, parent_ripple_id, order_level, raw_magnitude,
                              probability, lag_time_months, transmission_elasticity
                       FROM ripple_effects WHERE event_id=?""",
                    (event_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def _compute_chain(self, event_id: Any, max_hops: int) -> List[Dict[str, Any]]:
        rows = self._fetch_ripple_rows(event_id)
        if not rows:
            return self._demo_chain()
        # Attempt the recursive CTE (PG / SQLite-with-ln). Fall back to Python.
        try:
            with self.db.session() as conn:
                cte_rows = self._run_ripple_cte(conn, event_id, max_hops)
            if cte_rows:
                return cte_rows
        except Exception:
            pass
        return self._python_chain(rows, max_hops)

    def _run_ripple_cte(self, conn, event_id: Any, max_hops: int) -> List[Dict[str, Any]]:
        # Probe ln() availability; raises if the math functions are not compiled in.
        conn.execute("SELECT ln(1.0)").fetchone()
        query = """
            WITH RECURSIVE ripple_chain(
                ripple_id, parent_ripple_id, order_level, raw_magnitude, probability,
                lag_time_months, transmission_elasticity, depth, pn, cumulative_lag, mn, s
            ) AS (
                SELECT ripple_id, parent_ripple_id, order_level, raw_magnitude, probability,
                       lag_time_months, transmission_elasticity, 1,
                       CAST(probability AS REAL),
                       CAST(lag_time_months AS REAL),
                       raw_magnitude * probability * COALESCE(transmission_elasticity, 1.0),
                       ABS(raw_magnitude * probability * COALESCE(transmission_elasticity, 1.0))
                           * 20.0 / (1.0 + ln(1.0 + lag_time_months))
                FROM ripple_effects
                WHERE event_id = ? AND parent_ripple_id IS NULL
                UNION ALL
                SELECT r.ripple_id, r.parent_ripple_id, r.order_level, r.raw_magnitude,
                       r.probability, r.lag_time_months, r.transmission_elasticity,
                       rc.depth + 1,
                       rc.pn * r.probability,
                       rc.cumulative_lag + r.lag_time_months,
                       r.raw_magnitude * rc.pn * r.probability * COALESCE(r.transmission_elasticity, 1.0),
                       ABS(r.raw_magnitude * rc.pn * r.probability * COALESCE(r.transmission_elasticity, 1.0))
                           * 20.0 / (1.0 + ln(1.0 + rc.cumulative_lag + r.lag_time_months))
                FROM ripple_effects r
                JOIN ripple_chain rc ON r.parent_ripple_id = rc.ripple_id
                WHERE rc.depth < ?
            )
            SELECT * FROM ripple_chain WHERE depth <= ? ORDER BY s DESC
        """
        rows = conn.execute(query, (event_id, max_hops, max_hops)).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            pn = float(r["pn"])
            s = float(r["s"])
            out.append({
                "ripple_id": r["ripple_id"],
                "order_level": r["order_level"],
                "raw": r["raw_magnitude"],
                "prob": r["probability"],
                "beta": r["transmission_elasticity"],
                "lag": r["cumulative_lag"],
                "pn": round(pn, 6),
                "mn": round(float(r["mn"]), 4),
                "s": round(s, 4),
                "pn_raw": pn,
                "s_raw": s,
                "pruned": self.should_prune_ripple_row(pn, s),
            })
        return out

    def _python_chain(self, rows: List[Dict[str, Any]], max_hops: int) -> List[Dict[str, Any]]:
        by_id = {r["ripple_id"]: r for r in rows}
        children: Dict[Any, List[Any]] = {}
        roots: List[Any] = []
        for r in rows:
            pid = r["parent_ripple_id"]
            if pid is None or pid not in by_id:
                roots.append(r["ripple_id"])
            children.setdefault(pid, []).append(r["ripple_id"])

        out: List[Dict[str, Any]] = []

        def rec(rid, cum_pn, cum_lag, depth):
            if depth > max_hops or rid not in by_id:
                return
            r = by_id[rid]
            prob = float(r["probability"]) if r["probability"] is not None else 1.0
            beta = float(r["transmission_elasticity"]) if r["transmission_elasticity"] is not None else 1.0
            raw = float(r["raw_magnitude"]) if r["raw_magnitude"] is not None else 0.0
            lag = int(r["lag_time_months"]) if r["lag_time_months"] is not None else 0

            pn = cum_pn * prob
            cum_lag2 = cum_lag + lag
            mn = raw * pn * beta
            denom = (1.0 + math.log(1.0 + cum_lag2)) if cum_lag2 > 0 else 1.0
            s = abs(mn) * 20.0 / denom

            out.append({
                "ripple_id": rid,
                "order_level": r["order_level"],
                "raw": raw,
                "prob": prob,
                "beta": beta,
                "lag": cum_lag2,
                "pn": round(pn, 6),
                "mn": round(mn, 4),
                "s": round(s, 4),
                "pn_raw": pn,
                "s_raw": s,
                "pruned": self.should_prune_ripple_row(pn, s),
            })
            for child in children.get(rid, []):
                rec(child, pn, cum_lag2, depth + 1)

        for root in roots:
            rec(root, 1.0, 0, 1)

        out.sort(key=lambda x: x["s_raw"], reverse=True)
        return out

    @staticmethod
    def _demo_chain() -> List[Dict[str, Any]]:
        """Canonical steel-duty 3-level demo chain (used when no ripple rows exist)."""
        demo = [
            {"raw": 3.8, "prob": 1.0, "beta": 1.0, "lag": 0, "order_level": 1},
            {"raw": -2.43, "prob": 1.0, "beta": 1.0, "lag": 3, "order_level": 2},
            {"raw": -1.41, "prob": 1.0, "beta": 1.0, "lag": 6, "order_level": 3},
        ]
        out: List[Dict[str, Any]] = []
        cum_pn = 1.0
        cum_lag = 0
        for i, d in enumerate(demo, start=1):
            prob = d["prob"]
            beta = d["beta"]
            raw = d["raw"]
            cum_pn *= prob
            cum_lag += d["lag"]
            mn = raw * cum_pn * beta
            denom = (1.0 + math.log(1.0 + cum_lag)) if cum_lag > 0 else 1.0
            s = abs(mn) * 20.0 / denom
            out.append({
                "ripple_id": f"demo_{i}",
                "order_level": d["order_level"],
                "raw": raw,
                "prob": prob,
                "beta": beta,
                "lag": cum_lag,
                "pn": round(cum_pn, 6),
                "mn": round(mn, 4),
                "s": round(s, 4),
                "pn_raw": cum_pn,
                "s_raw": s,
                "pruned": False,
                "is_demo": True,
            })
        out.sort(key=lambda x: x["s_raw"], reverse=True)
        return out


causal_engine = CausalGraphEngine()
