"""Peer 4 — Supply Chain substrate promotion (isolated, parallel-safe).

Owner: reality_engine/processing/causal_engine.py, reality_engine/processing/event_graph.py,
       reality_engine/scripts/run_supply_peer.py

This runner densifies the SUPPLY-CHAIN peer substrate by:
  1. Ensuring the ``countries`` reference table exists with IND/USA/CHN/EU seeded.
  2. Seeding ``geographic_exposure`` for the top ~30 Nifty200 symbols (>=30 rows), using
     ``company_id = master_companies.rowid`` (the cross-peer convention shared with
     business_model_profiles / moat_evaluations) and country_id = ISO-3 code.
  3. Adding supplemental 3-level ripple_effects chains for STEEL_SAFEGUARD_DUTY,
     RAIL_CAPEX_PUSH and NUCLEAR_MISSION (each: 1st @0m, 2nd @3m, 3rd @6m), so that at
     least 3 events carry a 3-level forward/back supply-chain DAG (Wave0 keeps its 34 rows).
  4. Verifying: trace_ripple_chain returns S-ordered chain, fetch_supply_chain_neighbors
     returns up/down neighbors, get_geographic_exposure returns data.

It does NOT touch factor / quality / policy tables. All writes are idempotent.
"""

from __future__ import annotations

import os
import sys

# Make the project root importable regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from reality_engine.db.repository import Repository
from reality_engine.processing.causal_engine import CausalGraphEngine
from reality_engine.processing.event_graph import EventGraphSpawner

# ---------------------------------------------------------------------------
# Exporter overrides for scale derived path (ind_pct, export_split sensible values)
# Each entry maps symbol -> {country_id: revenue_share_pct}
# ---------------------------------------------------------------------------
EXPORTER_OVERRIDES = {
    "TCS":        {"IND": 30.0, "USA": 50.0, "EU": 15.0, "CHN": 5.0},
    "INFY":       {"IND": 28.0, "USA": 60.0, "EU": 10.0, "CHN": 2.0},
    "HCLTECH":    {"IND": 32.0, "USA": 55.0, "EU": 10.0, "CHN": 3.0},
    "WIPRO":      {"IND": 35.0, "USA": 50.0, "EU": 12.0, "CHN": 3.0},
    "TECHM":      {"IND": 30.0, "USA": 45.0, "EU": 20.0, "CHN": 5.0},
    "DRREDDY":    {"IND": 40.0, "USA": 40.0, "EU": 15.0, "CHN": 5.0},
    "SUNPHARMA":  {"IND": 35.0, "USA": 35.0, "EU": 25.0, "CHN": 5.0},
    "CIPLA":      {"IND": 45.0, "USA": 30.0, "EU": 20.0, "CHN": 5.0},
    "AUROPHARMA": {"IND": 30.0, "USA": 45.0, "EU": 20.0, "CHN": 5.0},
    "TATAMOTORS": {"IND": 45.0, "USA": 15.0, "EU": 30.0, "CHN": 10.0},
    "BAJAJ-AUTO": {"IND": 55.0, "USA": 10.0, "EU": 25.0, "CHN": 10.0},
    "BHARATFORGE":{"IND": 50.0, "USA": 25.0, "EU": 20.0, "CHN": 5.0},
    "HINDALCO":   {"IND": 60.0, "USA": 15.0, "EU": 15.0, "CHN": 10.0},
    "VEDL":       {"IND": 65.0, "USA": 15.0, "EU": 10.0, "CHN": 10.0},
    "NALCO":      {"IND": 80.0, "USA": 5.0, "EU": 10.0, "CHN": 5.0},
}

# ---------------------------------------------------------------------------
# Curated Nifty200 supply-chain geographic revenue splits (heuristic).
# country_id values must be in {IND, USA, CHN, EU, ...} (countries table).
# ---------------------------------------------------------------------------
GEO_MAP = {
    "HAL":         {"IND": 98.0, "USA": 1.8, "EU": 0.2},
    "RELIANCE":    {"IND": 68.0, "USA": 20.0, "EU": 8.0, "CHN": 4.0},
    "TATASTEEL":   {"IND": 62.0, "CHN": 10.0, "USA": 14.0, "EU": 14.0},
    "TITAGARH":    {"IND": 90.0, "EU": 7.0, "USA": 3.0},
    "BEML":        {"IND": 85.0, "USA": 8.0, "EU": 7.0},
    "BHEL":        {"IND": 82.0, "USA": 10.0, "EU": 8.0},
    "NTPC":        {"IND": 97.0, "USA": 1.5, "EU": 1.5},
    "RVNL":        {"IND": 95.0, "EU": 3.0, "USA": 2.0},
    "IRCON":       {"IND": 93.0, "USA": 4.0, "EU": 3.0},
    "TEXRAIL":     {"IND": 88.0, "USA": 6.0, "EU": 6.0},
    "ADANIPORTS":  {"IND": 90.0, "CHN": 5.0, "USA": 3.0, "EU": 2.0},
    "INFY":        {"IND": 55.0, "USA": 30.0, "EU": 10.0, "CHN": 5.0},
    "TCS":         {"IND": 50.0, "USA": 35.0, "EU": 12.0, "CHN": 3.0},
    "WIPRO":       {"IND": 52.0, "USA": 33.0, "EU": 12.0, "CHN": 3.0},
    "SUNPHARMA":   {"IND": 60.0, "USA": 25.0, "EU": 12.0, "CHN": 3.0},
    "TATAMOTORS":  {"IND": 55.0, "USA": 18.0, "EU": 20.0, "CHN": 7.0},
    "M&M":         {"IND": 70.0, "USA": 10.0, "EU": 15.0, "CHN": 5.0},
    "MARUTI":      {"IND": 75.0, "USA": 5.0, "EU": 15.0, "CHN": 5.0},
    "APLAPOLLO":   {"IND": 80.0, "USA": 12.0, "EU": 8.0},
    "AMBUJACEM":   {"IND": 96.0, "USA": 2.0, "CHN": 2.0},
    "LT":          {"IND": 72.0, "USA": 12.0, "EU": 12.0, "CHN": 4.0},
    "SIEMENS":     {"IND": 65.0, "USA": 18.0, "EU": 15.0, "CHN": 2.0},
    "ABB":         {"IND": 60.0, "USA": 20.0, "EU": 18.0, "CHN": 2.0},
    "HDFCBANK":    {"IND": 99.0, "USA": 0.5, "EU": 0.5},
    "ICICIBANK":   {"IND": 98.0, "USA": 1.0, "EU": 1.0},
    "ITC":         {"IND": 88.0, "USA": 6.0, "EU": 6.0},
    "ONGC":        {"IND": 92.0, "USA": 4.0, "CHN": 4.0},
    "COALINDIA":   {"IND": 99.0, "USA": 1.0},
    "BAJAJ-AUTO":  {"IND": 68.0, "USA": 8.0, "EU": 18.0, "CHN": 6.0},
    "ULTRACEMCO":  {"IND": 94.0, "CHN": 3.0, "USA": 3.0},
}

COUNTRIES = [
    ("IND", "India", 3.5, 3.2, "INR"),
    ("USA", "United States", 4.0, 4.5, "USD"),
    ("CHN", "China", 3.0, 2.8, "CNY"),
    ("EU", "European Union", 3.6, 4.0, "EUR"),
]

# Supplemental 3-level supply-chain ripple chains.
# Each event: root (order_level 1, lag 0) -> 2nd-order (order_level 2, lag 3) ->
# 3rd-order (order_level 3, lag 6). parent linking done via _ref/_parent_ref.
SUPPLY_EVENTS = {
    "STEEL_SAFEGUARD_DUTY": {
        "root": dict(target_company_id=None, target_type="Industry", raw=0.12, prob=0.90,
                     beta=1.0, lag=0, channel="safeguard_duty_protection|upstream|back"),
        "level2": [
            dict(target_company_id="TITAGARH", target_type="Company", raw=-0.08, prob=0.80,
                 beta=1.0, lag=3, channel="input_cost_up|downstream|forward"),
            dict(target_company_id="TATAMOTORS", target_type="Company", raw=-0.05, prob=0.70,
                 beta=1.0, lag=3, channel="input_cost_up|downstream|forward"),
            dict(target_company_id="TATASTEEL", target_type="Company", raw=0.06, prob=0.85,
                 beta=1.0, lag=3, channel="domestic_volume_pull|upstream|back"),
        ],
        "level3": dict(parent_ref="L2_0", target_company_id="RVNL", target_type="Company",
                       raw=-0.03, prob=0.60, beta=1.0, lag=6,
                       channel="margin_compression|downstream"),
    },
    "RAIL_CAPEX_PUSH": {
        "root": dict(target_company_id="RVNL", target_type="Company", raw=0.15, prob=0.90,
                     beta=1.0, lag=0, channel="capex_order_influx|downstream|forward"),
        "level2": [
            dict(target_company_id="TITAGARH", target_type="Company", raw=0.18, prob=0.85,
                 beta=1.0, lag=3, channel="wagon_order_influx|downstream|forward"),
            dict(target_company_id="BEML", target_type="Company", raw=0.10, prob=0.80,
                 beta=1.0, lag=3, channel="equipment_demand|downstream|forward"),
            dict(target_company_id="TATASTEEL", target_type="Company", raw=0.06, prob=0.75,
                 beta=1.0, lag=3, channel="steel_demand_pull|upstream|back"),
        ],
        "level3": dict(parent_ref="L2_0", target_company_id="TEXRAIL", target_type="Company",
                       raw=0.08, prob=0.70, beta=1.0, lag=6,
                       channel="component_demand|downstream"),
    },
    "NUCLEAR_MISSION": {
        "root": dict(target_company_id="NTPC", target_type="Company", raw=0.10, prob=0.85,
                     beta=1.0, lag=0, channel="nuclear_capacity_award|downstream|forward"),
        "level2": [
            dict(target_company_id="BHEL", target_type="Company", raw=0.14, prob=0.80,
                 beta=1.0, lag=3, channel="reactor_epc_demand|downstream|forward"),
            dict(target_company_id="LT", target_type="Company", raw=0.08, prob=0.75,
                 beta=1.0, lag=3, channel="epc_demand|downstream|forward"),
            dict(target_company_id=None, target_type="Industry", raw=0.05, prob=0.60,
                 beta=1.0, lag=3, channel="fuel_supply|upstream|back"),
        ],
        "level3": dict(parent_ref="L2_0", target_company_id="SIEMENS", target_type="Company",
                       raw=0.07, prob=0.65, beta=1.0, lag=6,
                       channel="component_demand|downstream"),
    },
}


def _resolve_company_id(repo: Repository, symbol: str):
    with repo.db.session() as conn:
        row = conn.execute(
            "SELECT rowid FROM master_companies WHERE nse_symbol=?", (symbol,)
        ).fetchone()
        return row["rowid"] if row else None


def seed_countries(repo: Repository) -> int:
    """Create countries table (postgres-aligned) + seed IND/USA/CHN/EU. Idempotent."""
    with repo.db.session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS countries (
                country_id VARCHAR(3) PRIMARY KEY,
                country_name VARCHAR(100) NOT NULL,
                political_stability_score NUMERIC(3,2),
                rule_of_law_index NUMERIC(3,2),
                currency VARCHAR(10)
            )
            """
        )
        for cid, name, ps, rl, cur in COUNTRIES:
            conn.execute(
                """
                INSERT INTO countries (country_id, country_name, political_stability_score,
                                       rule_of_law_index, currency)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(country_id) DO UPDATE SET
                    country_name=excluded.country_name,
                    political_stability_score=excluded.political_stability_score,
                    rule_of_law_index=excluded.rule_of_law_index,
                    currency=excluded.currency
                """,
                (cid, name, ps, rl, cur),
            )
    return len(COUNTRIES)


def seed_geographic_exposure(repo: Repository, universe: str = "nifty200", limit: int | None = None) -> int:
    """Upsert geographic_exposure rows. Extended to ALL master companies.

    - For symbols in GEO_MAP: use curated split.
    - For symbols in EXPORTER_OVERRIDES: use exporter override split.
    - For remaining companies in universe: default IND 96 / asset 92.
    Returns rows inserted/updated. Accepts universe {nifty200,nifty500,all} and limit.
    Back-compat: default universe=nifty200, limit=None seeds at least the curated ~30.
    """
    causal = CausalGraphEngine(repo.db)
    causal.ensure_geographic_exposure_schema(repo.db)
    inserted = 0

    # Resolve universe company list for extended seeding
    try:
        if universe == "nifty500":
            with repo.db.session() as conn:
                rows = conn.execute("SELECT nse_symbol FROM master_companies WHERE is_nifty500=1 AND is_active=1 ORDER BY nse_symbol ASC").fetchall()
                universe_symbols = [r["nse_symbol"] for r in rows if r["nse_symbol"]]
        elif universe == "all":
            with repo.db.session() as conn:
                rows = conn.execute("SELECT nse_symbol FROM master_companies WHERE is_active=1 ORDER BY nse_symbol ASC").fetchall()
                universe_symbols = [r["nse_symbol"] for r in rows if r["nse_symbol"]]
        else:  # nifty200 default
            try:
                comps = repo.get_nifty200_companies()
                universe_symbols = [c.get("nse_symbol") for c in comps if c.get("nse_symbol")]
                if not universe_symbols:
                    with repo.db.session() as conn:
                        rows = conn.execute("SELECT nse_symbol FROM master_companies WHERE is_nifty200=1 AND is_active=1 ORDER BY nse_symbol ASC").fetchall()
                        universe_symbols = [r["nse_symbol"] for r in rows if r["nse_symbol"]]
            except Exception:
                with repo.db.session() as conn:
                    rows = conn.execute("SELECT nse_symbol FROM master_companies WHERE is_nifty200=1 AND is_active=1 ORDER BY nse_symbol ASC").fetchall()
                    universe_symbols = [r["nse_symbol"] for r in rows if r["nse_symbol"]]
    except Exception:
        universe_symbols = list(GEO_MAP.keys())

    if limit is not None:
        try:
            universe_symbols = universe_symbols[: int(limit)]
        except Exception:
            pass

    # If universe list is empty (e.g. isolated test DB without nifty flags), fall back to GEO_MAP keys
    if not universe_symbols:
        universe_symbols = list(GEO_MAP.keys())

    # Ensure curated GEO_MAP symbols are always included even when universe is narrow
    # plus exporter overrides
    all_symbols = set(universe_symbols)
    all_symbols.update(GEO_MAP.keys())
    all_symbols.update(EXPORTER_OVERRIDES.keys())

    # When limit is set, we still respect it for universe_symbols but curated overrides are extra?
    # For deterministic counts we cap total when limit is set to universe_symbols size already.
    # To keep limit semantics simple, if limit is provided we slice the final sorted all_symbols
    if limit is not None:
        # universe_symbols already sliced; re-apply limit to overall? keep as is for back-compat
        # Instead only extend with non-universe curated symbols up to limit extra
        # Simplify: final list is sorted all_symbols limited to max(limit, len(GEO_MAP)) when limit supplied
        # We'll just keep previous all_symbols without extra slicing beyond universe_symbols
        pass

    # Upsert for each symbol in universe_symbols + curated + exporters
    # For universe=all, this will seed ALL master companies with defaults
    # For universe=nifty200, seeds nifty200 plus curated
    # Sorted for determinism
    for symbol in sorted(all_symbols):
        # Determine split: curated > exporter override > default
        if symbol in GEO_MAP:
            split = GEO_MAP[symbol]
        elif symbol in EXPORTER_OVERRIDES:
            split = EXPORTER_OVERRIDES[symbol]
        else:
            # Only seed default for symbols that are part of the requested universe
            if symbol not in set(universe_symbols):
                continue
            split = {"IND": 96.0}
        cid = _resolve_company_id(repo, symbol)
        if cid is None:
            continue
        for country_id, rev in split.items():
            if country_id == "IND" and len(split) == 1 and rev == 96.0:
                asset = 92.0
            else:
                asset = round(float(rev) * 0.9, 2)
            repo.upsert_geographic_exposure(cid, country_id, float(rev), float(asset))
            inserted += 1
    return inserted


def _translate_ripple(r: dict, repo: Repository) -> dict:
    """Normalize a curated ripple dict to ripple_effects canonical columns.

    Curated specs use short keys (raw/prob/beta/lag/channel) and symbol strings for
    target_company_id. Map them to the persisted column names and resolve symbol
    strings to master_companies.rowid so the supply-chain DAG joins correctly.
    """
    out = dict(r)
    # Resolve symbol -> company rowid for company-type targets.
    tcid = out.get("target_company_id")
    if isinstance(tcid, str) and repo is not None:
        out["target_company_id"] = _resolve_company_id(repo, tcid)
    # Map short keys to canonical ripple_effects columns.
    if "raw" in out:
        out["raw_magnitude"] = out.pop("raw")
    if "prob" in out:
        out["probability"] = out.pop("prob")
    if "beta" in out:
        out["transmission_elasticity"] = out.pop("beta")
    if "lag" in out:
        out["lag_time_months"] = out.pop("lag")
    if "channel" in out:
        out["transmission_channel"] = out.pop("channel")
    return out


def build_ripple_list(event_spec: dict, repo: Repository = None) -> list:
    """Build a ripple_effects row list (with _ref/_parent_ref) for a 3-level chain."""
    ripples = []
    root = _translate_ripple(dict(event_spec["root"]), repo)
    root.update(order_level=1, _ref="ROOT", _parent_ref=None)
    ripples.append(root)
    for i, l2 in enumerate(event_spec["level2"]):
        l2 = _translate_ripple(dict(l2), repo)
        l2.update(order_level=2, _ref=f"L2_{i}", _parent_ref="ROOT")
        ripples.append(l2)
    l3 = _translate_ripple(dict(event_spec["level3"]), repo)
    l3.update(order_level=3, _ref="L3_0", _parent_ref=l3.pop("parent_ref"))
    ripples.append(l3)
    return ripples


def seed_supply_ripples(repo: Repository) -> int:
    """Add 3-level supply-chain chains for steel/rail/nuclear. Returns total rows added."""
    total = 0
    for event_id, spec in SUPPLY_EVENTS.items():
        ripples = build_ripple_list(spec, repo)
        repo.ensure_ripple_effects_schema(repo.db)
        repo.upsert_ripple_effects(event_id, ripples)
        total += len(ripples)
    return total


def count_events_with_3level_chains(repo: Repository) -> int:
    with repo.db.session() as conn:
        rows = conn.execute(
            "SELECT event_id, MAX(order_level) mx FROM ripple_effects GROUP BY event_id"
        ).fetchall()
    return sum(1 for r in rows if (r["mx"] or 0) >= 3)


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--universe", choices=["nifty200", "nifty500", "all"], default="nifty200")
    p.add_argument("--limit", type=int, default=None)
    try:
        args, _ = p.parse_known_args()
    except SystemExit:
        # argparse calls sys.exit on error; fallback to defaults
        class _A: universe="nifty200"; limit=None
        args=_A()
    return args


def main(universe: str | None = None, limit: int | None = None) -> dict:
    # honor CLI args when called as script; also allow direct call with params
    cli_args = _parse_args()
    eff_universe = universe if universe is not None else cli_args.universe
    eff_limit = limit if limit is not None else cli_args.limit

    repo = Repository()
    causal = CausalGraphEngine(repo.db)
    spawner = EventGraphSpawner(repo.db)

    # --- Idempotent seeding -------------------------------------------------
    before_ripple = repo.get_all_ripple_effects()
    n_countries = seed_countries(repo)
    n_geo = seed_geographic_exposure(repo, universe=eff_universe, limit=eff_limit)
    n_supply_ripples = seed_supply_ripples(repo)

    # --- Counts -------------------------------------------------------------
    with repo.db.session() as conn:
        countries_n = conn.execute("SELECT count(*) FROM countries").fetchone()[0]
        geo_total = conn.execute("SELECT count(*) FROM geographic_exposure").fetchone()[0]
        geo_companies = conn.execute(
            "SELECT count(DISTINCT company_id) FROM geographic_exposure"
        ).fetchone()[0]
        ripple_total = conn.execute("SELECT count(*) FROM ripple_effects").fetchone()[0]

    three_level_events = count_events_with_3level_chains(repo)

    # --- Verification -------------------------------------------------------
    # 1) trace_ripple_chain returns S-ordered chain for a supply event.
    chain = causal.trace_ripple_chain("STEEL_SAFEGUARD_DUTY", max_hops=3)
    s_values = [c["s"] for c in chain]
    s_ordered = all(s_values[i] >= s_values[i + 1] for i in range(len(s_values) - 1))
    chain_levels = sorted({c["order_level"] for c in chain})

    # 2) fetch_supply_chain_neighbors returns up/down for steel.
    neighbors = spawner.fetch_supply_chain_neighbors("STEEL_SAFEGUARD_DUTY")
    neighbors_ok = bool(neighbors["upstream"]) and bool(neighbors["downstream"])

    # 3) get_geographic_exposure returns data for HAL.
    hal_cid = _resolve_company_id(repo, "HAL")
    geo_hal = repo.get_geographic_exposure(hal_cid) if hal_cid is not None else []

    return {
        "countries_seeded": n_countries,
        "countries_rows": countries_n,
        "geographic_exposure_rows": geo_total,
        "geographic_exposure_companies": geo_companies,
        "supply_ripples_added": n_supply_ripples,
        "ripple_effects_total_rows": ripple_total,
        "ripple_effects_before": len(before_ripple),
        "events_with_3level_chain": three_level_events,
        "verify_trace_chain_levels": chain_levels,
        "verify_trace_s_ordered": s_ordered,
        "verify_supply_neighbors_upstream": neighbors["upstream"],
        "verify_supply_neighbors_downstream": neighbors["downstream"],
        "verify_supply_neighbors_ok": neighbors_ok,
        "verify_geo_HAL_rows": len(geo_hal),
    }


if __name__ == "__main__":
    result = main()
    print("=" * 75)
    print("  PEER 4 (SUPPLY CHAIN) SUBSTRATE PROMOTION - COUNTS")
    print("=" * 75)
    for k, v in result.items():
        if isinstance(v, list):
            print(f"  {k:32s}: {len(v)} items -> {v}")
        else:
            print(f"  {k:32s}: {v}")
    print("=" * 75)
    ok = (
        result["geographic_exposure_rows"] >= 30
        and result["events_with_3level_chain"] >= 3
        and result["verify_trace_s_ordered"]
        and result["verify_supply_neighbors_ok"]
        and result["verify_geo_HAL_rows"] > 0
    )
    print("  ALL CHECKS PASSED:" if ok else "  CHECKS FAILED:", ok)
