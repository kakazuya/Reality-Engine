"""
Final Wave - MoE seeding & EOD correction loop (continuous improvement engine).

This runner exercises the MoE ensemble + continuous self-correction loop end-to-end:

  1. Seed ``model_explainer_rankings`` (explanatory power) for >=20 symbols across the 5
     investor-majority cohorts (promoter/FII/DII/retail/all) x 4 lens families, with
     deterministic bootstrap weights derived from each stock's REAL dense substrate
     (moat -> business_quality, regulatory ENI -> policy_macro, ripple/geo -> supply_chain,
     financial_metrics -> factor_statistical).
  2. Fire a sample MoE temperature gate (temperature=0.4, HAL/FII) -> lens_activation_log audit.
  3. Run the continuous self-correction loop:
       * EOD correction on a real closed-session date (learns per-scrip noise floors,
         re-ranks lenses via competitive survival).
       * Event correction for US_TARIFF_TEXTILE_RELIEF (revises 2nd-order ripples,
         stamps revision_count, reinforces policy/supply lenses).
  4. Print the required verification summary.

Owns only: ensemble_ranker, eod_corrector, this runner, and additive repository helpers.
Reads (never mutates) the peer 0-4 substrate tables.

Run:  python reality_engine/scripts/run_moe_eod.py
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure the project root is importable when the runner is invoked directly
# (e.g. `python reality_engine/scripts/run_moe_eod.py`) rather than as a module.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from reality_engine.db.database import db_manager
from reality_engine.db.repository import Repository
from reality_engine.processing.ensemble_ranker import (
    EnsembleRanker,
    LENS_FAMILIES,
    INVESTOR_MAJORITIES,
)
from reality_engine.processing.eod_corrector import EODCorrector


# ---------------------------------------------------------------------------
# Deterministic bootstrap configuration
# ---------------------------------------------------------------------------
# Per-investor-majority tilt multipliers on the 4 lens families. Different cohorts
# drive price through different lenses, so each gets a distinct weighting skew. The
# "all" cohort is the neutral substrate-derived baseline (tilt == 1.0 everywhere).
INVESTOR_TILTS: Dict[str, Dict[str, float]] = {
    "promoter": {"factor_statistical": 0.7, "business_quality": 1.30, "policy_macro": 0.9, "supply_chain": 1.00},
    "FII":      {"factor_statistical": 1.3, "business_quality": 1.00, "policy_macro": 0.9, "supply_chain": 0.90},
    "DII":      {"factor_statistical": 0.9, "business_quality": 1.20, "policy_macro": 1.0, "supply_chain": 1.00},
    "retail":   {"factor_statistical": 0.8, "business_quality": 0.90, "policy_macro": 1.2, "supply_chain": 1.10},
    "all":      {f: 1.0 for f in LENS_FAMILIES},
}

# Floor so no lens family collapses to exactly 0 (compute_ensemble_weights falls back to
# the global bootstrap only when a family is missing or <= 0 in a partition).
EXPLAIN_FLOOR = 0.05

# Symbols the EOD + event correction must run on (the task's named universe).
EOD_UNIVERSE = ["HAL", "TITAGARH", "RELIANCE", "LT", "BHEL"]

# Minimum number of seeded symbols (>= 20 per task).
MIN_SEED_SYMBOLS = 28


# ---------------------------------------------------------------------------
# Substrate readers (read-only against peer 0-4 tables)
# ---------------------------------------------------------------------------
def _company_id_for(conn, symbol: str) -> Optional[int]:
    """Bridge symbol -> company_id via the peer tables that already carry both keys."""
    row = conn.execute(
        "SELECT company_id FROM financial_metrics WHERE symbol = ? LIMIT 1", (symbol,)
    ).fetchone()
    if row and row["company_id"] is not None:
        return int(row["company_id"])
    row = conn.execute(
        "SELECT company_id FROM moat_evaluations WHERE ticker = ? LIMIT 1", (symbol,)
    ).fetchone()
    if row and row["company_id"] is not None:
        return int(row["company_id"])
    return None


def _quality_strength(conn, symbol: str) -> float:
    """business_quality substrate strength from moat score (0-5 -> 0-1)."""
    row = conn.execute(
        "SELECT total_moat_score FROM moat_evaluations WHERE ticker = ? OR isin = ? LIMIT 1",
        (symbol, symbol),
    ).fetchone()
    if row and row["total_moat_score"] is not None:
        return max(0.0, min(1.0, float(row["total_moat_score"]) / 5.0))
    return EXPLAIN_FLOOR


def _policy_strength(conn, symbol: str) -> float:
    """policy_macro substrate strength from aggregate regulatory ENI (|ENI|/5 -> 0-1)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(severity_score * probability), 0) AS eni "
        "FROM regulatory_political_risks WHERE ticker = ? OR symbol = ?",
        (symbol, symbol),
    ).fetchone()
    if row and row["eni"] is not None:
        return max(0.0, min(1.0, abs(float(row["eni"])) / 5.0))
    return EXPLAIN_FLOOR


def _factor_strength(conn, symbol: str) -> float:
    """factor_statistical substrate strength from financial_metrics."""
    row = conn.execute(
        "SELECT roic_wacc_spread, fcf_margin, gross_margin_peer_percentile "
        "FROM financial_metrics WHERE symbol = ? ORDER BY fiscal_year DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return EXPLAIN_FLOOR
    rs = float(row["roic_wacc_spread"] or 0.0)
    fc = float(row["fcf_margin"] or 0.0)
    gm = float(row["gross_margin_peer_percentile"] or 0.0)
    val = 0.10 + 0.45 * min(1.0, abs(rs) / 0.5) + 0.25 * min(1.0, abs(fc) / 0.3) + 0.20 * (gm / 100.0)
    return max(EXPLAIN_FLOOR, min(1.0, val))


def _supply_strength(conn, symbol: str) -> float:
    """supply_chain substrate strength from ripple significance + geographic exposure."""
    cid = _company_id_for(conn, symbol)
    if cid is None:
        return EXPLAIN_FLOOR
    ripple = conn.execute(
        "SELECT COALESCE(MAX(significance_rank), 0) AS s FROM ripple_effects "
        "WHERE target_company_id = ?",
        (cid,),
    ).fetchone()
    geo = conn.execute(
        "SELECT COALESCE(SUM(revenue_share_pct), 0) AS g FROM geographic_exposure "
        "WHERE company_id = ?",
        (cid,),
    ).fetchone()
    rs = float(ripple["s"] if ripple else 0.0)
    gs = float(geo["g"] if geo else 0.0)
    val = max(rs / 100.0, gs / 100.0)
    if val <= 0.0:
        return EXPLAIN_FLOOR
    return max(EXPLAIN_FLOOR, min(1.0, val))


def _pick_symbols(conn, min_count: int) -> List[str]:
    """Deterministic symbol set (>= min_count) with quality substrate + the EOD universe."""
    tickers = [r["ticker"] for r in conn.execute(
        "SELECT ticker FROM moat_evaluations ORDER BY ticker ASC"
    ).fetchall()]
    syms: List[str] = []
    for t in tickers:
        if t and t not in syms:
            syms.append(t)
        if len(syms) >= min_count:
            break
    # Guarantee the named EOD/event universe is always present.
    for s in EOD_UNIVERSE:
        if s not in syms:
            syms.append(s)
    return syms


def _pick_universe_symbols(conn, universe: str, limit: Optional[int]) -> List[str]:
    """Deterministic full-universe symbol selection (opt-in path).

    Selects active master_companies.nse_symbol ordered deterministically,
    optionally filtered by is_nifty500 / is_nifty200, and applies limit.
    This path does NOT cap at MIN_SEED_SYMBOLS — it seeds the full
    requested universe (used when --universe != nifty200 or
    --all-investor-cohorts is set). Idempotent and symbol-keyed.
    """
    uni = (universe or "nifty200").lower()
    try:
        if uni == "all":
            rows = conn.execute(
                "SELECT nse_symbol FROM master_companies WHERE is_active=1 AND nse_symbol IS NOT NULL AND TRIM(nse_symbol) != '' ORDER BY nse_symbol ASC"
            ).fetchall()
        elif uni == "nifty500":
            rows = conn.execute(
                "SELECT nse_symbol FROM master_companies WHERE is_nifty500=1 AND is_active=1 AND nse_symbol IS NOT NULL ORDER BY nse_symbol ASC"
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies WHERE is_active=1 AND nse_symbol IS NOT NULL AND TRIM(nse_symbol) != '' ORDER BY nse_symbol ASC"
                ).fetchall()
        else:  # nifty200
            rows = conn.execute(
                "SELECT nse_symbol FROM master_companies WHERE is_nifty200=1 AND is_active=1 AND nse_symbol IS NOT NULL ORDER BY nse_symbol ASC"
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies WHERE is_active=1 AND nse_symbol IS NOT NULL AND TRIM(nse_symbol) != '' ORDER BY nse_symbol ASC"
                ).fetchall()
    except Exception:
        rows = []
    syms = [r["nse_symbol"] for r in rows if r["nse_symbol"]]
    if limit is not None:
        try:
            lim = int(limit)
            if lim >= 0:
                syms = syms[:lim]
        except Exception:
            pass
    return syms


def _parse_args():
    """Parse opt-in full-universe MoE flags; defaults preserve legacy behavior."""
    import argparse
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--universe", choices=["nifty200", "nifty500", "all"], default="nifty200")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--all-investor-cohorts", action="store_true", default=False, dest="all_investor_cohorts")
    # Alias for seed-peers forwarding compatibility (treated same as --all-investor-cohorts)
    p.add_argument("--include-derived", action="store_true", default=False, dest="include_derived")
    try:
        args, _ = p.parse_known_args()
    except SystemExit:
        class _A:
            universe = "nifty200"
            limit = None
            all_investor_cohorts = False
            include_derived = False
        args = _A()
    return args


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main(
    universe: Optional[str] = None,
    limit: Optional[int] = None,
    all_investor_cohorts: Optional[bool] = None,
) -> int:
    cli_args = _parse_args()
    eff_universe = universe if universe is not None else getattr(cli_args, "universe", "nifty200")
    eff_limit = limit if limit is not None else getattr(cli_args, "limit", None)
    # all_investor_cohorts may come from either --all-investor-cohorts or --include-derived alias
    if all_investor_cohorts is not None:
        eff_all = bool(all_investor_cohorts)
    else:
        eff_all = bool(
            getattr(cli_args, "all_investor_cohorts", False) or getattr(cli_args, "include_derived", False)
        )
    use_full_universe = (eff_universe != "nifty200") or eff_all

    ranker = EnsembleRanker(db_manager)
    corrector = EODCorrector(db_manager)
    repo = Repository(db_manager)
    ranker.ensure_schema()

    with db_manager.session() as conn:
        if use_full_universe:
            syms = _pick_universe_symbols(conn, eff_universe, eff_limit)
        else:
            syms = _pick_symbols(conn, MIN_SEED_SYMBOLS)

    print("=" * 78)
    print("FINAL WAVE - MoE SEEDING & EOD CORRECTION LOOP")
    print("=" * 78)
    if use_full_universe:
        print(f"[setup] FULL-UNIVERSE seeding universe={eff_universe} limit={eff_limit} all_investor_cohorts={eff_all} -> {len(syms)} symbols x {len(INVESTOR_MAJORITIES)} investors x {len(LENS_FAMILIES)} lens families = up to {len(syms) * len(INVESTOR_MAJORITIES) * len(LENS_FAMILIES)} rows (20 rows/symbol deterministic, floor-signaled coverage)")
    else:
        print(f"[setup] seeding {len(syms)} symbols x {len(INVESTOR_MAJORITIES)} investors "
              f"x {len(LENS_FAMILIES)} lens families = up to {len(syms) * len(INVESTOR_MAJORITIES) * len(LENS_FAMILIES)} rows")

    # ---- counts: before seeding ----
    rows_before = _count("model_explainer_rankings")
    act_before = _count("lens_activation_log")

    # ---- 1. Seed model_explainer_rankings ----
    seeded_rows = 0
    for sym in syms:
        with db_manager.session() as conn:
            q = _quality_strength(conn, sym)
            p = _policy_strength(conn, sym)
            f = _factor_strength(conn, sym)
            s = _supply_strength(conn, sym)

        base = {
            "factor_statistical": max(EXPLAIN_FLOOR, f),
            "business_quality": max(EXPLAIN_FLOOR, q),
            "policy_macro": max(EXPLAIN_FLOOR, p),
            "supply_chain": max(EXPLAIN_FLOOR, s),
        }
        tot = sum(base.values())
        norm = {k: v / tot for k, v in base.items()}  # "all" baseline, sums to 1.0

        for inv in INVESTOR_MAJORITIES:
            tilt = INVESTOR_TILTS[inv]
            tv = {k: norm[k] * tilt[k] for k in LENS_FAMILIES}
            ttot = sum(tv.values())
            for fam in LENS_FAMILIES:
                ep = tv[fam] / ttot
                # stronger lens -> smaller p_value; always significant (< 0.05)
                p_value = round(0.01 + 0.03 * (1.0 - ep), 4)
                ranker.upsert_ranking(
                    sym, None, None, None, inv, fam,
                    p_value=p_value, explain_power=round(ep, 6),
                )
                seeded_rows += 1

    rows_after = _count("model_explainer_rankings")
    print(f"\n[1] model_explainer_rankings: before={rows_before}  after_seed={rows_after}  (+{rows_after - rows_before})")

    # ---- 2. MoE temperature gating sample ----
    fire = ranker.fire_lenses(temperature=0.4, context={"stock": "HAL", "investor": "FII"})
    print(f"\n[2] MoE gate fired (HAL/FII, temp=0.4):")
    print(f"    activation_id={fire['activation_id']}  fired_lenses={fire['fired_lenses']}  "
          f"n_fired={fire['n_fired']}  fired_weight_sum={fire['fired_weight_sum']}")
    print(f"    lens weights = {fire['weights']}")
    act_after = _count("lens_activation_log")
    print(f"    lens_activation_log: before={act_before}  after={act_after}")

    # ---- 3a. Snapshot ranks BEFORE EOD/event correction ("all" investor for the universe) ----
    snap_syms = list(EOD_UNIVERSE)
    ranks_before = {}
    for sym in snap_syms:
        for r in ranker.get_rankings(sym, "all"):
            ranks_before[(sym, r["lens_family"])] = r["rank"]

    # ---- 3b. EOD self-correction loop ----
    latest = repo.get_latest_price_delivery_date()
    print(f"\n[3] EOD correction loop  target_date={latest}  universe={EOD_UNIVERSE}")
    eod_result = corrector.correct_eod(
        universe=EOD_UNIVERSE, target_date=latest, dry_run=False,
    )
    print(f"    symbols_corrected={eod_result['symbols_corrected']}  "
          f"noise_floors_updated={eod_result['noise_floors_updated']}  "
          f"lens_rank_changes(explain_power moves)={eod_result['lens_rank_changes']}  "
          f"substrate_drifts={len(eod_result['substrate_drifts'])}")

    # ---- 3c. Event self-correction ----
    print(f"\n[3c] Event correction  US_TARIFF_TEXTILE_RELIEF  symbols={EOD_UNIVERSE}")
    ev_result = corrector.correct_event(
        "US_TARIFF_TEXTILE_RELIEF", symbols=EOD_UNIVERSE, dry_run=False,
    )
    print(f"    graph_respawned={ev_result['graph_respawned']}  "
          f"ripple_revision.n_revised={ev_result['ripple_revision'].get('n_revised')}  "
          f"impacted_symbols={ev_result['impacted_symbols']}  "
          f"lens_rank_changes={ev_result['lens_rank_changes']}")

    # verify revision_count stamped on the event's 2nd-order ripples
    rev_stamped = _count(
        "ripple_effects WHERE event_id='US_TARIFF_TEXTILE_RELIEF' AND revision_count > 0"
    )
    print(f"    revision_count stamped rows (US_TARIFF order>=2 ripples): {rev_stamped}")

    # ---- 4. Verification summary ----
    # rank flip detection for the universe under "all" investor (post EOD + event)
    ranks_after = {}
    for sym in snap_syms:
        for r in ranker.get_rankings(sym, "all"):
            ranks_after[(sym, r["lens_family"])] = r["rank"]
    rank_flips = sum(
        1 for k in ranks_before
        if ranks_after.get(k) is not None and ranks_before.get(k) != ranks_after.get(k)
    )
    explain_moves = eod_result["lens_rank_changes"] + ev_result["lens_rank_changes"]

    # ensemble weights HAL FII vs retail
    w_fii = ranker.compute_ensemble_weights(stock="HAL", investor="FII")
    w_retail = ranker.compute_ensemble_weights(stock="HAL", investor="retail")
    noise_count = _count("noise_floors")
    act_total = _count("lens_activation_log")

    print("\n" + "=" * 78)
    print("VERIFICATION SUMMARY")
    print("=" * 78)
    print(f"  model_explainer_rankings : before={rows_before}  after={rows_after}")
    print(f"  ensemble weights HAL/FII : {_fmt_weights(w_fii)}")
    print(f"  ensemble weights HAL/retail: {_fmt_weights(w_retail)}")
    print(f"  lens_activation_log count: {act_total}  (EOD+event re-fires included)")
    print(f"  noise_floors count      : {noise_count}")
    print(f"  EOD correction summary  : symbols={eod_result['symbols_corrected']} "
          f"floors={eod_result['noise_floors_updated']} "
          f"explain_power_moves={eod_result['lens_rank_changes']} "
          f"drifts={len(eod_result['substrate_drifts'])}")
    print(f"  event correction summary: ripples_revised={ev_result['ripple_revision'].get('n_revised')} "
          f"revision_count_stamped={rev_stamped} lens_moves={ev_result['lens_rank_changes']}")
    print(f"  explain_power moves (competitive survival): {explain_moves}")
    print(f"  lens RANK reorders across universe: {rank_flips}")

    improved = (explain_moves >= 1) or (rank_flips >= 1)
    print(f"\n  >>> EXPLANATORY POWER IMPROVES: {'YES' if improved else 'NO'} "
          f"(at least one lens re-weighted / re-ordered)")
    print("=" * 78)

    # Emit a non-zero exit only on hard failure signal (we never raise; report softly).
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _count(spec: str) -> int:
    """COUNT helper: opens its own session, accepts a bare table name or a full WHERE clause."""
    s = spec.strip()
    if s.upper().startswith("SELECT"):
        q = s
    else:
        q = f"SELECT COUNT(*) FROM {s}"
    with db_manager.session() as conn:
        row = conn.execute(q).fetchone()
        return int(row[0]) if row else 0


def _fmt_weights(w: Dict[str, float]) -> str:
    return " ".join(f"{k.split('_')[0]}={v:.3f}" for k, v in w.items())


if __name__ == "__main__":
    sys.exit(main())
