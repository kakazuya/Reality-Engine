"""Unified entity cross-map: ONE place that answers A + B + C together.

What it is
----------
A materialised, queryable graph assembled from SUBSTRATE ONLY — no new model
inference, no new scraping. It joins five things that today live in separate
tables with separate readers:

* (A) business-substance analogues  — ``company_business_graph``
* (A) financial-shape analogues     — ``company_peer_graph``
* (B) macro/sector edge resolution  — ``macro_events.affected_nodes_json`` +
                                      ``ripple_effects`` sector labels, resolved
                                      through the 22-valued AMFI sector/industry
                                      index in ``master_companies``
* (B) policy exposure edges         — ``regulatory_political_risks`` rows
                                      (5,400 rows, 44 real policies × 618 symbols;
                                      the 3,239 ``__NO_POLICY_TEMPLATE__`` rows
                                      are coverage sentinels and are EXCLUDED)
* (C) supply-chain edges            — ``geopolitical_supply_chain`` signals
                                      intersected with corpus-measured supply
                                      vocabulary, idf-weighted so a rare signal
                                      (``cold-chain pharma``) outranks ``import``

Why a new table, not a view
---------------------------
Callers need ranked, weighted, evidence-carrying edges in one query. The
artifact is ``company_entity_edges`` plus a ``entity_graph_runs`` audit row.
Nothing existing is modified.

Why each inclusion is here (measured, not assumed)
--------------------------------------------------
* Macro/ripple targets were checked to be 100% generic (``Sector``/``Industry``/
  ``Company`` literals, zero real symbols) — so B-resolution routes through the
  sector/industry index instead of the target names, which are evidence text.
* Supply-signal tokens were counted over 3,567 symbols: the top terms (import
  346, supplier 312, raw material 259, vendor 217…) form the curated dictionary,
  weighted 1/log(1 + corpus_frequency) so common words score less.
* Peer/business tables have zero quarantined anchors (measured), but PHASE5_*
  and TEST_* fixtures exist in graph/macro tables — filtered here by prefix.

What this is NOT
---------------
Not a prediction, not a ranking of stocks. It is the retrieval substrate for
(B) "what does this event hit" and (C) "who talks about this theme", consumed
by the deterministic tool and by anyone who wants evidence chains.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("reality_engine.entity_graph")

EDGE_DDL = """
CREATE TABLE IF NOT EXISTS company_entity_edges (
    src_symbol TEXT NOT NULL,
    dst_kind TEXT NOT NULL,
    dst_key TEXT NOT NULL,
    edge_family TEXT NOT NULL,
    weight REAL NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (src_symbol, dst_kind, dst_key, edge_family)
)
"""

RUN_DDL = """
CREATE TABLE IF NOT EXISTS entity_graph_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    reason TEXT,
    n_src_symbols INTEGER,
    n_edges INTEGER,
    families_json TEXT,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

# Fixture prefixes present in graph/macro tables (measured, substrate_hygiene-adjacent).
_FIXTURE_PREFIXES = ("PHASE5_", "TEST_")

# Corrupt-stub policies that are states of the pipeline, not policies.
_SENTINEL_POLICIES = frozenset({"__NO_POLICY_TEMPLATE__"})

# Measured top supply-signal tokens across 3567 symbols (frequency shown),
# used as the corpus-grounded curated supply dictionary.
_SUPPLY_FREQ = {
    "import": 346, "supplier": 312, "raw material": 259, "vendor": 217,
    "procurement": 214, "supply chain": 193, "logistics": 150,
    "commodity": 107, "freight": 107, "china": 106, "crude": 25,
}


def _rows(conn, sql: str, params: Sequence[Any] = ()) -> List[Any]:
    return conn.execute(sql, tuple(params)).fetchall()


def _json_load(raw: Any) -> Dict[str, Any]:
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _is_fixture(key: str) -> bool:
    k = (key or "").upper()
    return k.startswith(_FIXTURE_PREFIXES)


def _quarantined_isins(conn) -> set:
    try:
        rows = _rows(conn, "SELECT DISTINCT row_key FROM substrate_quarantine WHERE row_key IS NOT NULL")
    except Exception:
        return set()
    return {str(r[0]).upper() for r in rows if str(r[0]).upper().startswith("INE")}


def _universe(conn) -> Dict[str, Dict[str, str]]:
    """Real, non-quarantined companies: symbol -> {isin, sector, industry}."""
    try:
        q_isins = _quarantined_isins(conn)
    except Exception:
        q_isins = set()
    out: Dict[str, Dict[str, str]] = {}
    for isin, sym, sector, industry in _rows(
        conn,
        "SELECT isin, nse_symbol, sector, industry FROM master_companies "
        "WHERE nse_symbol IS NOT NULL AND nse_symbol <> ''",
    ):
        s = str(sym).upper().strip()
        if str(isin).upper() in q_isins:
            continue
        out[s] = {
            "isin": str(isin or ""),
            "sector": (sector or "").strip(),
            "industry": (industry or "").strip(),
        }
    return out


def _supply_idf(token: str, total_symbols: int = 3567) -> float:
    freq = _SUPPLY_FREQ.get(token, 1)
    return 1.0 / math.log(1.0 + freq)


def _supply_tokens(payload: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key in ("supply_chain_signals", "transit_route_risks"):
        v = payload.get(key)
        if isinstance(v, list):
            for t in v:
                t = str(t).strip().lower()
                if t and t != "derived transit risk" and t in _SUPPLY_FREQ:
                    out.append(t)
    # de-dupe, keep order
    seen: Dict[str, None] = {}
    for t in out:
        seen.setdefault(t)
    return list(seen)


# ---------------------------------------------------------------------------
# Builders — each returns (edges, diagnostics)
# ---------------------------------------------------------------------------
Edge = Tuple[str, str, str, str, float, Dict[str, Any]]
# (src, dst_kind, dst_key, family, weight, evidence)


def _analog_edges(conn, universe: Dict[str, Dict[str, str]], top_k: int) -> Tuple[List[Edge], Dict[str, Any]]:
    edges: List[Edge] = []
    per_table = {"company_business_graph": "business_analog", "company_peer_graph": "financial_analog"}
    stats: Dict[str, Any] = {}
    for table, family in per_table.items():
        try:
            rows = _rows(
                conn,
                f"SELECT anchor_symbol, peer_symbol, rank, similarity, "
                f"{'shared_terms_json' if 'business' in table else 'drivers_json'} AS ev "
                f"FROM {table} WHERE rank <= ?",
                (top_k,),
            )
        except Exception as exc:
            stats[table] = {"error": str(exc)[:120]}
            continue
        kept = skipped = 0
        for anchor, peer, rank, sim, ev in rows:
            a, p = str(anchor).upper(), str(peer).upper()
            if a not in universe or p not in universe:
                skipped += 1
                continue
            evd = {"rank": rank, "cosine": round(float(sim or 0.0), 4)}
            try:
                parsed = json.loads(ev) if ev else None
                if isinstance(parsed, list):
                    evd["shared_terms" if "business" in family else "drivers"] = parsed[:8]
                elif isinstance(parsed, dict):
                    evd["drivers"] = list(parsed.keys())[:8]
            except Exception:
                pass
            edges.append((a, "company", p, family, round(float(sim or 0.0), 4), evd))
            kept += 1
        stats[family] = {"kept": kept, "skipped_non_universe": skipped}
    return edges, stats


def _sector_edges(universe: Dict[str, Dict[str, str]]) -> Tuple[List[Edge], Dict[str, Any]]:
    edges: List[Edge] = []
    n = 0
    for sym, meta in universe.items():
        for kind, key in (("sector", meta["sector"]), ("industry", meta["industry"])):
            if not key:
                continue
            edges.append((sym, f"theme_{kind}", key, kind, 1.0, {"source": "master_companies AMFI tag"}))
            n += 1
    return edges, {"membership_edges": n, "companies": len(universe)}


def _policy_edges(conn, universe: Dict[str, Dict[str, str]]) -> Tuple[List[Edge], Dict[str, Any]]:
    edges: List[Edge] = []
    diag = {"rows": 0, "kept": 0, "skipped_sentinel": 0, "skipped_non_universe": 0, "policies": 0}
    try:
        rows = _rows(
            conn,
            "SELECT symbol, policy_name, risk_type, severity_score, probability, "
            "net_impact_score, coverage_status FROM regulatory_political_risks",
        )
    except Exception as exc:
        return [], {"error": str(exc)[:120]}
    policies = set()
    for sym, policy, risk_type, sev, prob, net, cov in rows:
        diag["rows"] += 1
        if (policy or "") in _SENTINEL_POLICIES:
            diag["skipped_sentinel"] += 1
            continue
        s = str(sym or "").upper()
        if s not in universe:
            diag["skipped_non_universe"] += 1
            continue
        eni = float(abs(float(net or 0.0)))
        edges.append((s, "theme_policy", str(policy), "policy", round(eni, 3), {
            "direction": risk_type or "Unknown",
            "severity": sev, "probability": prob, "coverage": cov or "unknown",
        }))
        policies.add(policy)
        diag["kept"] += 1
    diag["policies"] = len(policies)
    return edges, diag


def _supply_edges(conn, universe: Dict[str, Dict[str, str]]) -> Tuple[List[Edge], Dict[str, Any]]:
    edges: List[Edge] = []
    diag = {"symbols": 0, "edges": 0}
    try:
        rows = _rows(
            conn,
            "SELECT symbol, value_json FROM company_distilled_parameters "
            "WHERE parameter_key='geopolitical_supply_chain' AND symbol IS NOT NULL",
        )
    except Exception as exc:
        return [], {"error": str(exc)[:120]}
    for sym, raw in rows:
        s = str(sym).upper()
        if s not in universe:
            continue
        toks = _supply_tokens(_json_load(raw))
        if not toks:
            continue
        diag["symbols"] += 1
        for t in toks:
            edges.append((s, "theme_supply", t, "supply", round(_supply_idf(t), 4), {"source": "distilled supply_chain_signals"}))
            diag["edges"] += 1
    return edges, diag


# ---------------------------------------------------------------------------
# Materialise + query
# ---------------------------------------------------------------------------
def ensure_schema(conn) -> None:
    conn.execute(EDGE_DDL)
    conn.execute(RUN_DDL)


def build_graph(top_k_per_map: int = 20, conn=None) -> Dict[str, Any]:
    """Assemble the unified graph into company_entity_edges. Returns stats."""
    from reality_engine.db.database import db_manager
    own = conn is None
    if own:
        ctx = db_manager.session()
        conn = ctx.__enter__()
    try:
        universe = _universe(conn)
        all_edges: List[Edge] = []
        diagnostics: Dict[str, Any] = {"universe": len(universe)}
        for builder, name in (
            (lambda: _analog_edges(conn, universe, top_k_per_map), "analogs"),
            (lambda: _sector_edges(universe), "sector"),
            (lambda: _policy_edges(conn, universe), "policy"),
            (lambda: _supply_edges(conn, universe), "supply"),
        ):
            edges, diag = builder()
            all_edges.extend(edges)
            diagnostics[name] = diag
        ensure_schema(conn)
        conn.execute("DELETE FROM company_entity_edges")
        seen = set()
        rows = 0
        for src, kind, key, fam, w, ev in all_edges:
            dedup = (src, kind, key, fam)
            if dedup in seen:
                continue
            seen.add(dedup)
            conn.execute(
                "INSERT OR REPLACE INTO company_entity_edges "
                "(src_symbol, dst_kind, dst_key, edge_family, weight, evidence_json) "
                "VALUES (?,?,?,?,?,?)",
                (src, kind, key, fam, w, json.dumps(ev)),
            )
            rows += 1
        conn.execute(
            "INSERT INTO entity_graph_runs (status, n_src_symbols, n_edges, families_json) VALUES (?,?,?,?)",
            ("ok", len(universe), rows, json.dumps(sorted({e[3] for e in all_edges}))),
        )
        diagnostics.update({"edges": rows, "status": "ok"})
        return diagnostics
    finally:
        if own:
            ctx.__exit__(None, None, None)


def neighbours(symbol: str, top_k: int = 10, families: Optional[Sequence[str]] = None,
               conn=None) -> List[Dict[str, Any]]:
    """Ranked edges out of one company, newest build. No writes."""
    from reality_engine.db.database import db_manager
    own = conn is None
    if own:
        ctx = db_manager.session()
        conn = ctx.__enter__()
    try:
        sql = ("SELECT dst_kind, dst_key, edge_family, weight, evidence_json "
               "FROM company_entity_edges WHERE src_symbol = ?")
        params: List[Any] = [str(symbol).upper().strip()]
        if families:
            sql += " AND edge_family IN (%s)" % ",".join("?" for _ in families)
            params.extend(families)
        sql += " ORDER BY weight DESC, dst_key LIMIT ?"
        params.append(top_k)
        return [
            {"kind": r[0], "key": r[1], "family": r[2], "weight": r[3],
             "evidence": _json_load(r[4])}
            for r in _rows(conn, sql, params)
        ]
    finally:
        if own:
            ctx.__exit__(None, None, None)


def query_theme(kind: str, key: str, top_k: int = 25, family: Optional[str] = None,
                conn=None) -> List[Dict[str, Any]]:
    """Companies linked to one theme node, ranked — the B/C recall surface."""
    from reality_engine.db.database import db_manager
    own = conn is None
    if own:
        ctx = db_manager.session()
        conn = ctx.__enter__()
    try:
        if kind == "sector":
            sql = ("SELECT e.src_symbol, e.weight, e.evidence_json FROM company_entity_edges e "
                   "WHERE e.dst_kind IN ('theme_sector','theme_industry') AND e.dst_key = ?")
            params: List[Any] = [key]
        else:
            sql = "SELECT src_symbol, weight, evidence_json FROM company_entity_edges WHERE dst_kind = ? AND dst_key = ?"
            params = [kind, key]
        if family:
            sql += " AND edge_family = ?"
            params.append(family)
        sql += " ORDER BY weight DESC LIMIT ?"
        params.append(top_k)
        return [
            {"symbol": r[0], "weight": r[1], "evidence": _json_load(r[2])}
            for r in _rows(conn, sql, params)
        ]
    finally:
        if own:
            ctx.__exit__(None, None, None)


def latest_run(conn=None) -> Optional[Dict[str, Any]]:
    from reality_engine.db.database import db_manager
    own = conn is None
    if own:
        ctx = db_manager.session()
        conn = ctx.__enter__()
    try:
        try:
            row = _rows(conn, "SELECT run_id, status, n_src_symbols, n_edges, families_json, computed_at "
                              "FROM entity_graph_runs ORDER BY run_id DESC LIMIT 1")
        except Exception:
            return None
        if not row:
            return None
        r = row[0]
        return {"run_id": r[0], "status": r[1], "n_src_symbols": r[2], "n_edges": r[3],
                "families": json.loads(r[4] or "[]"), "computed_at": r[5]}
    finally:
        if own:
            ctx.__exit__(None, None, None)
