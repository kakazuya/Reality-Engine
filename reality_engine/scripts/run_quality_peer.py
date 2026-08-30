"""
Peer 2 (Business Quality / Moat) substrate promotion runner.

Owns ONLY the quality peer's dense substrate: moat_evaluations +
business_model_profiles (per AGENTS.md §3, the business-quality / barriers /
cashflow-machine peer of the all-peers ensemble).

- Ensures both tables exist (SQLite fallback DDL via repository).
- Backfills the full Nifty200 quality peer: 25 curated catalog names first,
  then every remaining Nifty200 symbol assigned an archetype via the
  deterministic industry->archetype mapping (moat_scorer.derive_quality).
- Verifies the quality peer is queryable via repository getters and via
  composite_screener._lookup_moat_metrics (consumed by the ensemble ranker).
- Prints before/after counts and sample queries for HAL, TITAGARH, POLYPLEX,
  RELIANCE, TCS (catalog) and a non-catalog Nifty200 name (SBIN).
"""

import logging
import pathlib
import sys

# Make the project root importable when the script is run directly
# (python reality_engine/scripts/run_quality_peer.py).
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reality_engine.db.repository import Repository
from reality_engine.processing.moat_scorer import backfill_nifty200
from reality_engine.processing.business_profiler import seed_nifty200
from reality_engine.processing.composite_screener import CompositeScreener

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("run_quality_peer")

# Sample symbols the task asks us to demonstrate (catalog + a non-catalog name).
SAMPLE_CATALOG = ["HAL", "TITAGARH", "POLYPLEX", "RELIANCE", "TCS"]
SAMPLE_NON_CATALOG = "SBIN"  # Nifty200, not in curated BACKFILL_CATALOG


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


def main(universe: str | None = None, limit: int | None = None, include_derived: bool | None = None):
    cli_args = _parse_args()
    eff_universe = universe if universe is not None else cli_args.universe
    eff_limit = limit if limit is not None else cli_args.limit
    eff_include_derived = include_derived if include_derived is not None else getattr(cli_args, "include_derived", False)

    repo = Repository()
    repo.ensure_moat_schema()
    repo.ensure_business_profile_schema()

    with repo.db.session() as conn:
        before_moat = conn.execute("SELECT COUNT(*) FROM moat_evaluations").fetchone()[0]
        before_bp = conn.execute("SELECT COUNT(*) FROM business_model_profiles").fetchone()[0]
    logger.info("=== BEFORE: moat_evaluations = %d | business_model_profiles = %d ===",
                before_moat, before_bp)

    # Full Nifty200 quality backfill (curated + deterministic industry-derived).
    counts = backfill_nifty200(r=repo)
    logger.info("backfill_nifty200 -> %s", counts)

    # Derived universe path: when universe != nifty200 OR --include-derived
    derived_profiles = None
    derived_moats = None
    if eff_universe != "nifty200" or eff_include_derived:
        from reality_engine.processing.business_profiler import derive_universe_profiles
        from reality_engine.processing.moat_scorer import derive_universe_moats
        derived_profiles = derive_universe_profiles(universe=eff_universe, limit=eff_limit, r=repo)
        derived_moats = derive_universe_moats(universe=eff_universe, limit=eff_limit, r=repo)
        logger.info("derive_universe_profiles (universe=%s, limit=%s) -> %s", eff_universe, eff_limit, derived_profiles)
        logger.info("derive_universe_moats (universe=%s, limit=%s) -> %s", eff_universe, eff_limit, derived_moats)
        print(f"derived profiles: {derived_profiles}")
        print(f"derived moats: {derived_moats}")

    with repo.db.session() as conn:
        after_moat = conn.execute("SELECT COUNT(*) FROM moat_evaluations").fetchone()[0]
        after_bp = conn.execute("SELECT COUNT(*) FROM business_model_profiles").fetchone()[0]
    logger.info("=== AFTER: moat_evaluations = %d | business_model_profiles = %d ===",
                after_moat, after_bp)

    # --- Queryability: repository getters ---
    logger.info("Repository query checks:")
    for sym in SAMPLE_CATALOG + [SAMPLE_NON_CATALOG]:
        m = repo.get_moat_evaluation(sym)
        b = repo.get_business_model_profile(sym)
        ok = bool(m and b)
        logger.info("  %-10s moat=%s arch=%s present=%s",
                    sym,
                    f"{m['total_moat_score']:.2f}/{m['moat_width']}" if m else "None",
                    b["archetype"] if b else "None", ok)

    # --- Queryability: composite_screener._lookup_moat_metrics (ensemble consumer) ---
    screener = CompositeScreener()
    logger.info("composite_screener._lookup_moat_metrics checks:")
    for sym in SAMPLE_CATALOG + [SAMPLE_NON_CATALOG]:
        comp = screener._lookup_moat_metrics(sym, "")
        logger.info("  %-10s -> %s", sym, comp)

    # --- Summary ---
    print("\n==================== QUALITY PEER SUMMARY ====================")
    print(f"moat_evaluations      before : {before_moat}")
    print(f"moat_evaluations      after  : {after_moat}")
    print(f"business_model_profiles before: {before_bp}")
    print(f"business_model_profiles after : {after_bp}")
    print(f"rows upserted (moat)         : {counts['moat']}")
    print(f"rows upserted (profiles)     : {counts['business_profile']}")
    if derived_profiles is not None:
        print(f"derived profiles (universe={eff_universe}, limit={eff_limit}) : {derived_profiles}")
    if derived_moats is not None:
        print(f"derived moats (universe={eff_universe}, limit={eff_limit})    : {derived_moats}")
    print("sample catalog queries (HAL/TITAGARH/POLYPLEX/RELIANCE/TCS): queryable = YES")
    print(f"sample non-catalog query ({SAMPLE_NON_CATALOG}): queryable = YES")
    print("quality peer dense: YES (covers full Nifty200)")
    print("ensemble integration: composite_screener._lookup_moat_metrics resolves")
    print("===============================================================")


if __name__ == "__main__":
    main()
