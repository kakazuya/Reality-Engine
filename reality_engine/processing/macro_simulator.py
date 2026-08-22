"""Macro shock propagation over the causal graph."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from reality_engine.db.database import db_manager
from reality_engine.processing.causal_engine import CausalGraphEngine
from reality_engine.processing.distillation_engine import DistillationEngine


class MacroSimulator:
    def __init__(self, manager=None):
        self.db = manager or db_manager
        self.graph = CausalGraphEngine(self.db)
        self.distillation = DistillationEngine(self.db)

    def seed_canonical_causal_graph(self) -> Dict[str, int]:
        nodes = {
            "UNION_BUDGET_2026_RAIL_CAPEX": ("MACRO_EVENT", "Union Budget 2026 Rail Capex"),
            "COMMODITY_CRUDE_OIL": ("COMMODITY", "Crude Oil"),
            "GEOPOLITICAL_RED_SEA_ATTACKS": ("GEOPOLITICAL_EVENT", "Red Sea Attacks"),
            "DEFENCE_INDIGENIZATION_DAP": ("POLICY", "Defence Indigenization DAP"),
            "PM_SURYA_GHAR_SOLAR": ("POLICY", "PM Surya Ghar Solar"),
            "HAL": ("COMPANY", "Hindustan Aeronautics"), "TITAGARH": ("COMPANY", "Titagarh Rail Systems"),
            "KAYNES": ("COMPANY", "Kaynes Technology"), "ASIAN_PAINTS": ("COMPANY", "Asian Paints"),
            "SCI": ("COMPANY", "Shipping Corporation of India"), "HAVELLS": ("COMPANY", "Havells India"),
            "PIDILITIND": ("COMPANY", "Pidilite Industries"),
        }
        for node_id, (node_type, name) in nodes.items():
            metadata = {"canonical": True}
            if node_type == "COMPANY":
                metadata["symbol"] = node_id
            self.graph.add_graph_node(node_id, node_type, name, metadata)
        edges = [
            ("UNION_BUDGET_2026_RAIL_CAPEX", "TITAGARH", 1.0, 1.3, "rail tender awards and order conversion"),
            ("UNION_BUDGET_2026_RAIL_CAPEX", "KAYNES", 1.0, 0.8, "rail electronics and embedded systems demand"),
            ("DEFENCE_INDIGENIZATION_DAP", "HAL", 1.0, 1.2, "domestic procurement and platform order visibility"),
            ("PM_SURYA_GHAR_SOLAR", "HAVELLS", 1.0, 0.7, "residential electrical and solar distribution demand"),
            ("PM_SURYA_GHAR_SOLAR", "PIDILITIND", 1.0, 0.3, "construction and installation activity"),
            ("COMMODITY_CRUDE_OIL", "ASIAN_PAINTS", -1.0, 0.9, "crude-linked input cost inflation"),
            ("GEOPOLITICAL_RED_SEA_ATTACKS", "SCI", 1.0, 0.8, "freight rates and route disruption pricing"),
            ("GEOPOLITICAL_RED_SEA_ATTACKS", "ASIAN_PAINTS", -1.0, 0.2, "import logistics disruption"),
        ]
        for source, target, impact, elasticity, mechanism in edges:
            self.graph.add_causal_edge(source, target, "MACRO_TRANSMISSION", impact, elasticity, mechanism,
                                       edge_id=f"CANONICAL_{source}_{target}")
        return {"nodes": len(nodes), "edges": len(edges)}

    def simulate_macro_shock(self, shock_scenario: str, sector_filter: str = "ALL") -> Dict[str, Any]:
        traces = self.graph.trace_causal_chain(shock_scenario, max_hops=5)
        by_symbol: Dict[str, Dict[str, Any]] = {}
        with self.db.session() as conn:
            for trace in traces:
                if trace["node_id"] == shock_scenario:
                    continue
                node = conn.execute("SELECT metadata_json FROM graph_nodes WHERE node_id = ?", (trace["node_id"],)).fetchone()
                metadata = json.loads(node[0]) if node and node[0] else {}
                symbol = metadata.get("symbol") or trace["node_id"]
                if sector_filter != "ALL" and metadata.get("sector", "").upper() != sector_filter.upper():
                    continue
                distilled_rows = conn.execute(
                    """SELECT parameter_key, value_json, confidence_score
                       FROM company_distilled_parameters WHERE symbol = ?
                       ORDER BY parameter_key""", (symbol,)
                ).fetchall()
                distilled = {}
                for parameter_key, value_json, confidence in distilled_rows:
                    try:
                        distilled[parameter_key] = {"value": json.loads(value_json), "confidence": confidence}
                    except (TypeError, json.JSONDecodeError):
                        distilled[parameter_key] = {"value": value_json, "confidence": confidence}
                candidate = {"symbol": symbol, "node_id": trace["node_id"],
                             "impact": trace["cumulative_impact"], "depth": trace["depth"],
                             "mechanisms": trace["mechanisms"], "resilient": trace["cumulative_impact"] >= 0,
                             "distilled_parameters": distilled}
                if symbol not in by_symbol or abs(trace["cumulative_impact"]) > abs(by_symbol[symbol]["impact"]):
                    by_symbol[symbol] = candidate
        companies = list(by_symbol.values())
        return {"shock_scenario": shock_scenario, "sector_filter": sector_filter,
                "beneficiaries": [x for x in companies if x["impact"] > 0],
                "victims": [x for x in companies if x["impact"] < 0],
                "resilient_companies": [x for x in companies if x["resilient"]],
                "impaired_companies": [x for x in companies if not x["resilient"]],
                "companies": companies, "trace_count": len(traces)}


macro_simulator = MacroSimulator()
seed_canonical_causal_graph = macro_simulator.seed_canonical_causal_graph
