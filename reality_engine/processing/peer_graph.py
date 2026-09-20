"""Analog peer graph — precomputed nearest neighbours over the dense substrate.

The point of this module is to move *analogical reasoning* off the inference
call.  A frontier model asked "which listed company is the closest analog to
this one, and why" has to improvise; if that answer is computed here, in batch,
over quantified substrate, the model only has to read it.

Three design rules keep the output honest, all of them learned from what the
live substrate actually contains:

1. **Degenerate features are dropped, not weighted.**
   Several populated-looking columns are near-constant across the universe
   (``stage_conviction`` sd ~0.03 around 0.6, ``is_cyclical`` true for ~4% of
   companies, ``geographic_exposure`` ~96% India, business-model archetype
   ~89% one value).  Feeding those into a cosine adds noise that looks like
   signal.  Every feature is measured and gated before use, and the drop list
   is part of the output.

2. **Missing is missing.**  Nothing is imputed to zero.  Similarity is computed
   over the dimensions both companies actually have, and every pair reports its
   ``coverage`` so a 0.9 similarity on 4 of 18 dimensions is not mistaken for a
   strong analogy.

3. **No neighbours are emitted below a signal floor.**  If too few features
   survive gating, the run records ``insufficient_signal`` and writes nothing
   rather than confidently ranking companies on constants.

Drivers are reported per pair (which features made these two look alike, and in
which direction), because a bare similarity score is not usable evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger("reality_engine.peer_graph")

TOP_K_DEFAULT = 20
MIN_COVERAGE = 0.20          # a feature must be present for >=20% of the universe
MIN_UNIQUE = 3               # fewer than 3 distinct values cannot separate companies
MAX_DOMINANT_SHARE = 0.85    # one value covering >85% of rows is a default, not a signal
MIN_ACTIVE_FEATURES = 6      # below this, no peer ranking is emitted at all
MIN_ANCHOR_FEATURES = 6      # an anchor must have this many active features itself
MIN_PAIR_COVERAGE = 0.50     # a pair must share half the active dimensions to be evidence
MIN_PAIR_FAMILIES = 3        # ...spread over at least this many feature families
CLIP_Z = 3.0                 # robust z-scores are winsorized here
BLOCK_ROWS = 512             # anchors per similarity block (bounds peak memory)
SANITY_BANDS = {
    "margin_pct": (-100.0, 100.0),
    "growth_pct": (-100.0, 300.0),
}

PEER_DDL = """
CREATE TABLE IF NOT EXISTS company_peer_graph (
    anchor_symbol TEXT NOT NULL,
    peer_symbol TEXT NOT NULL,
    rank INTEGER NOT NULL,
    similarity REAL NOT NULL,
    coverage REAL NOT NULL,
    shared_features INTEGER NOT NULL,
    shared_families INTEGER NOT NULL DEFAULT 0,
    drivers_json TEXT,
    features_version TEXT NOT NULL,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (anchor_symbol, peer_symbol)
)
"""

FEATURE_DDL = """
CREATE TABLE IF NOT EXISTS company_peer_features (
    symbol TEXT PRIMARY KEY,
    features_json TEXT NOT NULL,
    present INTEGER NOT NULL,
    total INTEGER NOT NULL,
    quarantined INTEGER NOT NULL DEFAULT 0,
    baseline_similarity REAL,
    features_version TEXT NOT NULL,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

RUN_DDL = """
CREATE TABLE IF NOT EXISTS company_peer_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    reason TEXT,
    n_symbols INTEGER,
    n_active_features INTEGER,
    active_features_json TEXT,
    dropped_features_json TEXT,
    diagnostics_json TEXT,
    top_k INTEGER,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


@dataclass(frozen=True)
class FeatureSpec:
    """One dimension of the analogical vector space."""

    name: str
    family: str
    source: str
    description: str


FEATURE_SPECS: Tuple[FeatureSpec, ...] = (
    # --- business model archetype scores (business_model_profiles) -----------
    FeatureSpec("bmp.revenue_recurrence_pct", "business_model", "business_model_profiles",
                "share of revenue that is recurring"),
    FeatureSpec("bmp.pricing_power_score", "business_model", "business_model_profiles",
                "pricing power score (2-5)"),
    FeatureSpec("bmp.capital_intensity_score", "business_model", "business_model_profiles",
                "capital intensity score (2-5)"),
    FeatureSpec("bmp.operating_leverage_score", "business_model", "business_model_profiles",
                "operating leverage score (2-5)"),
    # --- moat components (moat_evaluations) ---------------------------------
    FeatureSpec("moat.switching_costs", "moat", "moat_evaluations", "switching-cost component (1-5)"),
    FeatureSpec("moat.network_effects", "moat", "moat_evaluations", "network-effect component (1-5)"),
    FeatureSpec("moat.cost_advantage", "moat", "moat_evaluations", "cost-advantage component (1-5)"),
    FeatureSpec("moat.intangible_assets", "moat", "moat_evaluations", "intangible-asset component (1-5)"),
    FeatureSpec("moat.efficient_scale", "moat", "moat_evaluations", "efficient-scale component (1-5)"),
    # --- distilled parameter scalars (company_distilled_parameters JSON) ----
    FeatureSpec("distilled.is_cyclical", "distilled", "company_distilled_parameters",
                "cyclicality flag from the cyclicality profile"),
    FeatureSpec("distilled.cycle_duration_years", "distilled", "company_distilled_parameters",
                "cycle duration in years"),
    FeatureSpec("distilled.stage_conviction", "distilled", "company_distilled_parameters",
                "conviction in the stated cycle stage"),
    FeatureSpec("distilled.moat_rating", "distilled", "company_distilled_parameters",
                "distilled moat rating (0-10)"),
    FeatureSpec("distilled.n_revenue_drivers", "distilled", "company_distilled_parameters",
                "count of named revenue drivers"),
    FeatureSpec("distilled.n_raw_material_links", "distilled", "company_distilled_parameters",
                "count of quantified raw-material sensitivities"),
    FeatureSpec("distilled.max_input_elasticity", "distilled", "company_distilled_parameters",
                "largest raw-material sensitivity coefficient"),
    FeatureSpec("distilled.n_supply_risks", "distilled", "company_distilled_parameters",
                "count of named transit-route risks"),
    # --- policy exposure (regulatory_political_risks) -----------------------
    FeatureSpec("policy.agg_eni", "policy", "regulatory_political_risks",
                "sum of severity x probability (ENI)"),
    FeatureSpec("policy.max_severity", "policy", "regulatory_political_risks",
                "largest single severity score"),
    FeatureSpec("policy.has_template", "policy", "regulatory_political_risks",
                "1 when a mapped policy template exists, 0 for no_template/unknown"),
    # --- geography (geographic_exposure) ------------------------------------
    FeatureSpec("geo.non_india_revenue_pct", "geo", "geographic_exposure",
                "revenue share outside India (100 - IND share)"),
    # --- solvency / valuation (company_forensic_health) ---------------------
    FeatureSpec("solvency.debt_to_equity", "solvency", "company_forensic_health", "debt/equity ratio"),
    FeatureSpec("solvency.interest_coverage", "solvency", "company_forensic_health", "interest coverage"),
    FeatureSpec("solvency.altman_z", "solvency", "company_forensic_health", "Altman Z score"),
    FeatureSpec("solvency.log_market_cap", "solvency", "company_forensic_health", "log10 market cap (INR Cr)"),
    # --- earnings (quarterly_financials, latest quarter) --------------------
    FeatureSpec("earnings.yoy_revenue_growth_pct", "earnings", "quarterly_financials",
                "latest YoY revenue growth (%)"),
    FeatureSpec("earnings.ebitda_margin_pct", "earnings", "quarterly_financials",
                "latest EBITDA margin (%)"),
    # --- market behaviour (daily_price_delivery, trailing window) -----------
    FeatureSpec("market.delivery_pct_60d", "market", "daily_price_delivery",
                "mean delivery share over the trailing window"),
    FeatureSpec("market.realized_vol_60d", "market", "daily_price_delivery",
                "annualized realized vol over the trailing window"),
)

FEATURE_NAMES: Tuple[str, ...] = tuple(s.name for s in FEATURE_SPECS)
FEATURE_BY_NAME: Dict[str, FeatureSpec] = {s.name: s for s in FEATURE_SPECS}
FAMILY_ORDER: Tuple[str, ...] = tuple(dict.fromkeys(s.family for s in FEATURE_SPECS))
FEATURE_SCALE_FLOOR = 0.05  # absolute sd below this is never informative

# The peer graph answers "which company is an economic analogue of this one".
# ``market`` behaviour (delivery share, realized vol) is deliberately excluded
# from that question: it describes how a stock has been *trading*, not what the
# business *is*, and left in it becomes the dominant driver of every pair.
# Pass ``families=...`` to build a behavioural view instead.
NON_STRUCTURAL_FAMILIES: Tuple[str, ...] = ("market",)
STRUCTURAL_FAMILIES: Tuple[str, ...] = tuple(
    f for f in FAMILY_ORDER if f not in NON_STRUCTURAL_FAMILIES
)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _rows(conn, sql: str, params: Sequence[Any] = ()) -> List[Any]:
    try:
        return conn.execute(sql, tuple(params)).fetchall()
    except Exception as exc:  # pragma: no cover - defensive on schema drift
        logger.debug("peer extraction query failed (%s): %s", sql.split()[1:3], exc)
        return []


def _table_exists(conn, table: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (table,)
        ).fetchone() is not None
    except Exception:  # pragma: no cover - defensive
        return False


def _json_load(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _json_list(raw: Any) -> List[Any]:
    """Parse a JSON array column; anything else degrades to an empty list."""
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except Exception:
        return []
    return loaded if isinstance(loaded, list) else []


def _finite(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def extract_business_model(conn) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in _rows(
        conn,
        "SELECT symbol, revenue_recurrence_pct, pricing_power_score, "
        "capital_intensity_score, operating_leverage_score FROM business_model_profiles "
        "WHERE symbol IS NOT NULL",
    ):
        sym = str(r[0]).upper().strip()
        for name, raw in zip(
            ("bmp.revenue_recurrence_pct", "bmp.pricing_power_score",
             "bmp.capital_intensity_score", "bmp.operating_leverage_score"),
            (r[1], r[2], r[3], r[4]),
        ):
            v = _finite(raw)
            if v is not None:
                out[sym][name] = v
    return out


def extract_moat(conn) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in _rows(
        conn,
        "SELECT ticker, switching_costs, network_effects, cost_advantage, "
        "intangible_assets, efficient_scale FROM moat_evaluations WHERE ticker IS NOT NULL",
    ):
        sym = str(r[0]).upper().strip()
        for name, raw in zip(
            ("moat.switching_costs", "moat.network_effects", "moat.cost_advantage",
             "moat.intangible_assets", "moat.efficient_scale"),
            (r[1], r[2], r[3], r[4], r[5]),
        ):
            v = _finite(raw)
            if v is not None:
                out[sym][name] = v
    return out


def extract_distilled(conn) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in _rows(
        conn,
        "SELECT symbol, parameter_key, value_json FROM company_distilled_parameters "
        "WHERE symbol IS NOT NULL",
    ):
        sym = str(r[0]).upper().strip()
        key = str(r[1] or "")
        payload = _json_load(r[2])
        if not payload:
            continue
        if key == "cyclicality_profile":
            flag = payload.get("is_cyclical")
            if flag is not None:
                out[sym]["distilled.is_cyclical"] = 1.0 if flag else 0.0
            for name, field in (
                ("distilled.cycle_duration_years", "cycle_duration_years"),
                ("distilled.stage_conviction", "stage_conviction"),
            ):
                v = _finite(payload.get(field))
                if v is not None:
                    out[sym][name] = v
        elif key == "business_sensitivities":
            v = _finite(payload.get("moat_rating"))
            if v is not None:
                out[sym]["distilled.moat_rating"] = v
            drivers = payload.get("key_revenue_drivers")
            if isinstance(drivers, list):
                out[sym]["distilled.n_revenue_drivers"] = float(len(drivers))
            rm = payload.get("raw_material_sensitivities")
            if isinstance(rm, dict):
                out[sym]["distilled.n_raw_material_links"] = float(len(rm))
                coeffs = [c for c in (_finite(v) for v in rm.values()) if c is not None]
                if coeffs:
                    out[sym]["distilled.max_input_elasticity"] = max(coeffs)
        elif key == "geopolitical_supply_chain":
            risks = payload.get("transit_route_risks")
            if isinstance(risks, list):
                out[sym]["distilled.n_supply_risks"] = float(len(risks))
    return out


def extract_policy(conn) -> Dict[str, Dict[str, float]]:
    agg: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in _rows(
        conn,
        "SELECT symbol, severity_score, probability, coverage_status "
        "FROM regulatory_political_risks WHERE symbol IS NOT NULL",
    ):
        sym = str(r[0]).upper().strip()
        sev = _finite(r[1])
        prob = _finite(r[2])
        cov = (str(r[3]) if r[3] is not None else "mapped").strip().lower()
        slot = agg[sym]
        if sev is not None and prob is not None:
            slot["policy.agg_eni"] = slot.get("policy.agg_eni", 0.0) + sev * prob
        if sev is not None:
            slot["policy.max_severity"] = max(slot.get("policy.max_severity", sev), sev)
        slot["policy.has_template"] = 1.0 if cov == "mapped" else 0.0
    return agg


def extract_geo(conn) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    rows = _rows(
        conn,
        "SELECT m.nse_symbol, g.country_id, g.revenue_share_pct "
        "FROM geographic_exposure g JOIN master_companies m ON m.rowid = g.company_id",
    )
    totals: Dict[str, float] = defaultdict(float)
    ind: Dict[str, float] = defaultdict(float)
    for r in rows:
        if not r[0]:
            continue
        sym = str(r[0]).upper().strip()
        share = _finite(r[2])
        if share is None:
            continue
        totals[sym] += share
        if str(r[1] or "").upper() == "IND":
            ind[sym] += share
    for sym, total in totals.items():
        if total > 0:
            out[sym]["geo.non_india_revenue_pct"] = max(0.0, 100.0 - ind.get(sym, 0.0))
    return out


def extract_solvency(conn) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in _rows(
        conn,
        "SELECT symbol, debt_to_equity_ratio, interest_coverage_ratio, altman_z_score, "
        "market_cap_inr_cr FROM company_forensic_health WHERE symbol IS NOT NULL",
    ):
        sym = str(r[0]).upper().strip()
        for name, raw in zip(
            ("solvency.debt_to_equity", "solvency.interest_coverage", "solvency.altman_z"),
            (r[1], r[2], r[3]),
        ):
            v = _finite(raw)
            if v is not None:
                out[sym][name] = v
        cap = _finite(r[4])
        if cap is not None and cap > 0:
            out[sym]["solvency.log_market_cap"] = math.log10(cap)
    return out


def extract_earnings(conn) -> Tuple[Dict[str, Dict[str, float]], int]:
    """Latest *valid* quarter per symbol.  Contaminated rows are counted and skipped.

    The live ``quarterly_financials`` table contains unit-contaminated rows
    (margins of 599,921%, revenue of -366 Cr).  Clipping those would keep the
    garbage and relabel it, so a period whose values fall outside their sanity
    band is skipped whole -- a row-level decision, never mixing fields from two
    different quarters -- and the next most recent valid period is used.  The
    count of rejected values is returned so the defect stays visible.
    """
    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    grouped: Dict[str, List[Tuple[str, Any, Any]]] = defaultdict(list)
    contaminated = 0
    for r in _rows(
        conn,
        "SELECT symbol, quarter_end_date, yoy_revenue_growth_pct, ebitda_margin_pct "
        "FROM quarterly_financials WHERE symbol IS NOT NULL",
    ):
        sym = str(r[0]).upper().strip()
        grouped[sym].append((str(r[1] or ""), r[2], r[3]))

    for sym, entries in grouped.items():
        entries.sort(key=lambda e: e[0], reverse=True)
        for _period, growth_raw, margin_raw in entries:
            values: Dict[str, float] = {}
            rejected = False
            for name, raw, band in (
                ("earnings.yoy_revenue_growth_pct", growth_raw, SANITY_BANDS["growth_pct"]),
                ("earnings.ebitda_margin_pct", margin_raw, SANITY_BANDS["margin_pct"]),
            ):
                v = _finite(raw)
                if v is None:
                    continue
                if not (band[0] <= v <= band[1]):
                    contaminated += 1
                    rejected = True
                    continue
                values[name] = v
            if rejected:
                continue
            out[sym].update(values)
            break
    return out, contaminated


def extract_market(conn, window: int = 60) -> Dict[str, Dict[str, float]]:
    """Trailing delivery share and realized vol from the last ``window`` sessions."""
    dates = [
        str(r[0]) for r in _rows(
            conn,
            "SELECT DISTINCT date FROM daily_price_delivery ORDER BY date DESC LIMIT ?",
            (int(window),),
        )
    ]
    if not dates:
        return {}
    cutoff = min(dates)
    closes: Dict[str, List[float]] = defaultdict(list)
    delivery: Dict[str, List[float]] = defaultdict(list)
    for r in _rows(
        conn,
        "SELECT symbol, close, delivery_pct FROM daily_price_delivery "
        "WHERE date >= ? AND symbol IS NOT NULL ORDER BY symbol, date",
        (cutoff,),
    ):
        sym = str(r[0]).upper().strip()
        c = _finite(r[1])
        if c is not None and c > 0:
            closes[sym].append(c)
        d = _finite(r[2])
        if d is not None:
            delivery[sym].append(d)

    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    for sym, series in closes.items():
        if len(series) >= 10:
            arr = np.asarray(series, dtype=float)
            rets = np.diff(np.log(arr))
            if rets.size:
                vol = float(np.std(rets, ddof=1)) * math.sqrt(252.0)
                if math.isfinite(vol):
                    out[sym]["market.realized_vol_60d"] = vol
    for sym, series in delivery.items():
        if series:
            out[sym]["market.delivery_pct_60d"] = float(np.mean(series))
    return out


def build_feature_frame(conn, include_quarantined: bool = False) -> Dict[str, Any]:
    """Assemble raw (un-normalized) feature values keyed by symbol."""
    merged: Dict[str, Dict[str, float]] = defaultdict(dict)
    for part in (
        extract_business_model(conn),
        extract_moat(conn),
        extract_distilled(conn),
        extract_policy(conn),
        extract_geo(conn),
        extract_solvency(conn),
        extract_market(conn),
    ):
        for sym, feats in part.items():
            merged[sym].update(feats)
    earnings, contaminated = extract_earnings(conn)
    for sym, feats in earnings.items():
        merged[sym].update(feats)

    symbols = sorted(merged)
    quarantined: List[str] = []
    if not include_quarantined:
        from reality_engine.processing.substrate_hygiene import quarantined_keys

        bad_isins = quarantined_keys(conn, "master_companies")
        if bad_isins:
            placeholders = ",".join("?" for _ in bad_isins)
            rows = _rows(
                conn,
                f"SELECT nse_symbol FROM master_companies WHERE isin IN ({placeholders})",
                tuple(bad_isins),
            )
            bad_syms = {str(r[0]).upper().strip() for r in rows if r[0]}
            quarantined = sorted(s for s in symbols if s in bad_syms)
            symbols = [s for s in symbols if s not in bad_syms]

    return {
        "symbols": symbols,
        "values": {s: merged[s] for s in symbols},
        "quarantined_excluded": quarantined,
        "contaminated_earnings_values": contaminated,
    }


# ---------------------------------------------------------------------------
# Feature gating
# ---------------------------------------------------------------------------
def analyze_features(frame: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Per-feature distribution stats and a gate verdict."""
    symbols: List[str] = frame["symbols"]
    values: Dict[str, Dict[str, float]] = frame["values"]
    n = len(symbols)
    stats: Dict[str, Dict[str, Any]] = {}
    for name in FEATURE_NAMES:
        col = [_finite(values[s].get(name)) for s in symbols]
        present = [v for v in col if v is not None]
        coverage = (len(present) / n) if n else 0.0
        entry: Dict[str, Any] = {
            "family": FEATURE_BY_NAME[name].family,
            "source": FEATURE_BY_NAME[name].source,
            "description": FEATURE_BY_NAME[name].description,
            "n": len(present),
            "coverage": round(coverage, 4),
        }
        if not present:
            entry.update({"uniq": 0, "status": "empty"})
            stats[name] = entry
            continue
        arr = np.asarray(present, dtype=float)
        sd = float(np.std(arr))
        uniq = int(np.unique(arr).size)
        counts = np.unique(arr, return_counts=True)[1]
        dominant = float(counts.max()) / float(arr.size)
        entry.update({
            "uniq": uniq,
            "mean": round(float(np.mean(arr)), 4),
            "sd": round(sd, 4),
            "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
            "dominant_share": round(dominant, 4),
        })
        if coverage < MIN_COVERAGE:
            entry["status"] = "sparse"
        elif uniq < 2 or sd <= 0:
            entry["status"] = "constant"
        elif dominant > MAX_DOMINANT_SHARE:
            entry["status"] = "near_constant"
        elif uniq < MIN_UNIQUE:
            entry["status"] = "coarse"
        elif sd < FEATURE_SCALE_FLOOR:
            entry["status"] = "flat"
        else:
            entry["status"] = "ok"
        stats[name] = entry
    return stats


def select_features(
    stats: Dict[str, Dict[str, Any]],
    families: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[str]]:
    """Pick features that clear the signal gate, optionally restricted to families."""
    allow = set(families) if families else None
    in_scope = [n for n in FEATURE_NAMES if allow is None or FEATURE_BY_NAME[n].family in allow]
    active = [n for n in in_scope if stats.get(n, {}).get("status") == "ok"]
    dropped = [n for n in FEATURE_NAMES if n not in active]
    return active, dropped


# ---------------------------------------------------------------------------
# Vectors and neighbours
# ---------------------------------------------------------------------------
def _anchor_mask(frame: Dict[str, Any], active: Sequence[str]) -> np.ndarray:
    """Symbols carrying enough active features to act as an anchor at all."""
    symbols: List[str] = frame["symbols"]
    values: Dict[str, Dict[str, float]] = frame["values"]
    out = np.zeros(len(symbols), dtype=bool)
    for i, sym in enumerate(symbols):
        row = values.get(sym) or {}
        out[i] = sum(1 for n in active if _finite(row.get(n)) is not None) >= MIN_ANCHOR_FEATURES
    return out


def family_weights(active: Sequence[str]) -> np.ndarray:
    """Per-feature scale giving every feature family an equal share of the cosine.

    Without this, a family that happens to carry four surviving dimensions
    (moat) would outvote a family that carries one (solvency) purely because of
    how many columns it contributed.
    """
    counts: Dict[str, int] = defaultdict(int)
    for name in active:
        counts[FEATURE_BY_NAME[name].family] += 1
    return np.asarray(
        [math.sqrt(1.0 / counts[FEATURE_BY_NAME[name].family]) for name in active],
        dtype=float,
    )


def build_matrix(frame: Dict[str, Any], active: Sequence[str]) -> Tuple[np.ndarray, np.ndarray]:
    """Robust z-scores (median/MAD, winsorized, family-weighted) plus a presence mask.

    Returns ``(Z, M)`` where missing entries are 0 in ``Z`` and False in ``M``.
    """
    symbols: List[str] = frame["symbols"]
    values: Dict[str, Dict[str, float]] = frame["values"]
    n, d = len(symbols), len(active)
    raw = np.full((n, d), np.nan, dtype=float)
    for i, sym in enumerate(symbols):
        row = values.get(sym) or {}
        for j, name in enumerate(active):
            v = _finite(row.get(name))
            if v is not None:
                raw[i, j] = v
    M = ~np.isnan(raw)
    Z = np.zeros((n, d), dtype=float)
    for j in range(d):
        col = raw[:, j]
        mask = M[:, j]
        if not mask.any():
            continue
        present = col[mask]
        med = float(np.median(present))
        mad = float(np.median(np.abs(present - med)))
        scale = 1.4826 * mad
        if scale <= 0:
            scale = float(np.std(present))
        if scale <= 0:
            continue
        z = (col - med) / scale
        z = np.where(mask, np.clip(z, -CLIP_Z, CLIP_Z), 0.0)
        Z[:, j] = z
    Z *= family_weights(active)
    return Z, M


def compute_neighbours(
    frame: Dict[str, Any],
    active: Sequence[str],
    top_k: int = TOP_K_DEFAULT,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """Masked-cosine top-k neighbours with per-pair coverage, drivers, and anchor baselines.

    Returns ``(rows, baselines)``.  ``baselines[symbol]`` is the mean similarity
    across every pair that passed the quality filter for that anchor.  Without it
    a bare similarity is uninterpretable: the universe sits in a tight cone
    (mean pairwise similarity ~0.94 on the current substrat), so a rank-1 score of
    0.79 means "closest available", not "close".
    """
    symbols: List[str] = frame["symbols"]
    n = len(symbols)
    if n < 2 or not active:
        return []
    Z, M = build_matrix(frame, active)
    # float32 keeps the n x d matrix and its square well inside cache-friendly
    # territory: z-scores are already winsorized to +/-3, so the precision loss
    # is immaterial while the working set halves.
    A = np.where(M, Z, 0.0).astype(np.float32)
    sq = (A * A).astype(np.float32)
    Mf = M.astype(np.float32)
    d_active = float(len(active))
    present = M.sum(axis=1).astype(np.int32)
    anchor_ok = present >= MIN_ANCHOR_FEATURES
    family_of = np.asarray(
        [FAMILY_ORDER.index(FEATURE_BY_NAME[name].family) for name in active], dtype=np.int32
    )
    family_cols = [np.where(family_of == f)[0] for f in range(len(FAMILY_ORDER))]
    k = int(min(top_k, n - 1))

    out: List[Dict[str, Any]] = []
    baselines: Dict[str, float] = {}
    for start in range(0, n, BLOCK_ROWS):
        end = min(start + BLOCK_ROWS, n)
        Ab = A[start:end]                     # (b, d)
        Mblk = M[start:end]
        num = Ab @ A.T                        # (b, n) shared dimensions only contribute
        s_ij = sq[start:end] @ Mf.T           # (b, n) ||a_i restricted to j's dims||^2
        s_ji = sq @ Mblk.T.astype(np.float32)  # (n, b) ||a_j restricted to i's dims||^2
        denom = np.sqrt(np.maximum(s_ij * s_ji.T, 1e-12))
        sim = np.where(denom > 0, num / denom, 0.0)
        cov = (Mblk.astype(np.float32) @ Mf.T) / d_active
        shared = (Mblk.astype(np.int32) @ M.T.astype(np.int32))
        shared_families = np.zeros_like(shared)
        for cols in family_cols:
            if cols.size:
                shared_families += (
                    Mblk[:, cols].astype(np.int32) @ M[:, cols].T.astype(np.int32)
                ) > 0
        # A pair is only evidence when it shares enough dimensions, spread over
        # enough families — otherwise one coincidental shared feature produces a
        # perfect score (observed: sim=1.0 at coverage=0.09).
        valid = (
            (cov >= MIN_PAIR_COVERAGE)
            & (shared_families >= MIN_PAIR_FAMILIES)
            & anchor_ok[start:end][:, None]
        )
        sim = np.where(valid, sim, -np.inf)
        for offset in range(end - start):
            sim[offset, start + offset] = -np.inf  # never self-match
        order = np.argsort(-sim, axis=1)[:, :k]
        finite = np.isfinite(sim)
        with np.errstate(invalid="ignore"):
            row_mean = np.where(finite, sim, np.nan)
        for offset, anon in enumerate(symbols[start:end]):
            valid_row = row_mean[offset]
            if np.isfinite(valid_row).any():
                baselines[anon] = float(np.nanmean(valid_row))
            i = start + offset
            ai = A[i]
            accepted = 0
            for j in order[offset]:
                j = int(j)
                value = float(sim[offset, j])
                if not math.isfinite(value):
                    continue
                accepted += 1
                contrib = ai * A[j]
                drv_idx = np.argsort(-contrib)[:3]
                drivers = [
                    {
                        "feature": active[int(idx)],
                        "family": FEATURE_BY_NAME[active[int(idx)]].family,
                        "anchor_z": round(float(ai[int(idx)]), 3),
                        "peer_z": round(float(A[j, int(idx)]), 3),
                        "contribution": round(float(contrib[int(idx)]), 3),
                    }
                    for idx in drv_idx
                    if contrib[int(idx)] > 0
                ]
                out.append({
                    "anchor_symbol": anon,
                    "peer_symbol": symbols[j],
                    "rank": accepted,
                    "similarity": round(value, 4),
                    "coverage": round(float(cov[offset, j]), 4),
                    "shared_features": int(shared[offset, j]),
                    "shared_families": int(shared_families[offset, j]),
                    "drivers": drivers,
                })
    return out, baselines


def feature_diagnostics(
    stats: Dict[str, Dict[str, Any]],
    active: Sequence[str],
    dropped: Sequence[str],
    neighbours: Sequence[Dict[str, Any]],
    baselines: Dict[str, float],
) -> Dict[str, Any]:
    """Machine-readable quality report for one build.

    Two signals matter when reading a neighbour list:

    ``hub_peers``
        A peer that is the rank-1 neighbour for an outsized share of anchors is
        a *hub* — the company sitting nearest the population mode — not a
        meaningful analogue.  With only twelve coarse dimensions one profile can
        absorb hundreds of anchors; the reader must see that.

    ``baseline_similarity_*``
        The anchor's mean similarity across every pair that passed the filter.
        A rank-1 score below the field's 90th percentile is "nearest available",
        not "close".
    """
    rank1_counts: Dict[str, int] = defaultdict(int)
    for row in neighbours:
        if int(row.get("rank", 0)) == 1:
            rank1_counts[str(row["peer_symbol"])] += 1
    n_anchors = max(1, len(baselines))
    hubs = [
        {"symbol": sym, "rank1_for_anchors": n, "share": round(n / n_anchors, 4)}
        for sym, n in sorted(rank1_counts.items(), key=lambda kv: -kv[1])[:10]
        if n > 1
    ]
    base_values = np.asarray(list(baselines.values()), dtype=float) if baselines else np.asarray([])
    dropped_reasons: Dict[str, List[str]] = defaultdict(list)
    for name in dropped:
        dropped_reasons[str(stats.get(name, {}).get("status", "unknown"))].append(name)
    return {
        "dropped_by_reason": {k: sorted(v) for k, v in sorted(dropped_reasons.items())},
        "active_by_family": {
            fam: sorted(n for n in active if FEATURE_BY_NAME[n].family == fam)
            for fam in sorted({FEATURE_BY_NAME[n].family for n in active})
        },
        "hub_peers": hubs,
        "baseline_similarity_median": round(float(np.median(base_values)), 4) if base_values.size else None,
        "baseline_similarity_p90": round(float(np.quantile(base_values, 0.90)), 4) if base_values.size else None,
    }


def features_version(active: Sequence[str]) -> str:
    payload = "|".join(active).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Persistence and read API
# ---------------------------------------------------------------------------
def ensure_schema(conn) -> None:
    conn.execute(PEER_DDL)
    conn.execute(FEATURE_DDL)
    conn.execute(RUN_DDL)
    # Idempotent column migration for peer tables created by an earlier build.
    for table, column, ddl in (
        ("company_peer_graph", "shared_families", "INTEGER NOT NULL DEFAULT 0"),
        ("company_peer_features", "baseline_similarity", "REAL"),
        ("company_peer_runs", "diagnostics_json", "TEXT"),
    ):
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if cols and column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        except Exception as exc:  # pragma: no cover - defensive on schema drift
            logger.debug("peer graph column migration %s.%s skipped: %s", table, column, exc)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_peer_graph_anchor ON company_peer_graph(anchor_symbol, rank)"
    )


def persist(
    conn,
    frame: Dict[str, Any],
    stats: Dict[str, Dict[str, Any]],
    active: Sequence[str],
    dropped: Sequence[str],
    neighbours: Sequence[Dict[str, Any]],
    top_k: int,
    contaminated: int,
    status: str,
    baselines: Optional[Dict[str, float]] = None,
    reason: Optional[str] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_schema(conn)
    version = features_version(active)
    n_features = len(FEATURE_NAMES)
    diag_json = json.dumps(diagnostics) if diagnostics else None

    if status != "ok":
        conn.execute(
            "INSERT INTO company_peer_runs (status, reason, n_symbols, n_active_features, "
            "active_features_json, dropped_features_json, diagnostics_json, top_k) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (status, reason, len(frame["symbols"]), len(active),
             json.dumps(list(active)), json.dumps(list(dropped)), diag_json, int(top_k)),
        )
        return {"written": 0, "features_written": 0, "status": status, "reason": reason}

    conn.execute("DELETE FROM company_peer_graph")
    conn.executemany(
        "INSERT OR REPLACE INTO company_peer_graph (anchor_symbol, peer_symbol, rank, "
        "similarity, coverage, shared_features, shared_families, drivers_json, features_version) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (r["anchor_symbol"], r["peer_symbol"], int(r["rank"]), float(r["similarity"]),
             float(r["coverage"]), int(r["shared_features"]), int(r.get("shared_families", 0)),
             json.dumps(r["drivers"]), version)
            for r in neighbours
        ],
    )
    conn.execute("DELETE FROM company_peer_features")
    baseline_map = baselines or {}
    conn.executemany(
        "INSERT OR REPLACE INTO company_peer_features (symbol, features_json, present, total, "
        "quarantined, baseline_similarity, features_version) VALUES (?,?,?,?,?,?,?)",
        [
            (
                sym,
                json.dumps({
                    k: v for k, v in (frame["values"][sym] or {}).items()
                }),
                sum(1 for k in active if _finite((frame["values"][sym] or {}).get(k)) is not None),
                n_features,
                0,
                baseline_map.get(sym),
                version,
            )
            for sym in frame["symbols"]
        ],
    )
    conn.execute(
        "INSERT INTO company_peer_runs (status, reason, n_symbols, n_active_features, "
        "active_features_json, dropped_features_json, diagnostics_json, top_k) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (status, reason, len(frame["symbols"]), len(active),
         json.dumps(list(active)), json.dumps(list(dropped)), diag_json, int(top_k)),
    )
    return {
        "written": len(neighbours),
        "features_written": len(frame["symbols"]),
        "status": status,
        "features_version": version,
        "contaminated_earnings_values": contaminated,
    }


def neighbours(conn, symbol: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """Read back precomputed analogue peers, drivers and lift included.

    ``lift`` is the pair similarity minus the anchor's own baseline (its mean
    similarity to every company that passed the quality filter).  A rank-1 peer
    with negative lift is the nearest neighbour in a sparse region — worth
    saying out loud rather than presenting as a strong analogue.
    """
    sym = str(symbol).upper().strip()
    if not _table_exists(conn, "company_peer_graph"):
        return []
    baseline = None
    if _table_exists(conn, "company_peer_features"):
        row = _rows(
            conn, "SELECT baseline_similarity FROM company_peer_features WHERE symbol = ?", (sym,)
        )
        if row and row[0][0] is not None:
            baseline = float(row[0][0])
    rows = _rows(
        conn,
        "SELECT peer_symbol, rank, similarity, coverage, shared_features, shared_families, "
        "drivers_json FROM company_peer_graph WHERE anchor_symbol = ? ORDER BY rank LIMIT ?",
        (sym, int(top_k)),
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        similarity = float(r[2])
        out.append({
            "peer": r[0],
            "rank": int(r[1]),
            "similarity": similarity,
            "baseline_similarity": round(baseline, 4) if baseline is not None else None,
            "lift": round(similarity - baseline, 4) if baseline is not None else None,
            "coverage": float(r[3]),
            "shared_features": int(r[4]),
            "shared_families": int(r[5] or 0),
            "drivers": _json_list(r[6]),
        })
    return out


def latest_run(conn) -> Optional[Dict[str, Any]]:
    if not _table_exists(conn, "company_peer_runs"):
        return None
    rows = _rows(conn, "SELECT * FROM company_peer_runs ORDER BY run_id DESC LIMIT 1")
    if not rows:
        return None
    rec = dict(rows[0])
    for key in ("active_features_json", "dropped_features_json"):
        if rec.get(key):
            try:
                rec[key.replace("_json", "")] = json.loads(rec[key])
            except Exception:
                pass
    return rec


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(
    top_k: int = TOP_K_DEFAULT,
    db=None,
    apply: bool = True,
    include_quarantined: bool = False,
    families: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build the analog peer graph over the dense substrate."""
    from reality_engine.db.database import db_manager

    manager = db or db_manager
    scope = tuple(families) if families else STRUCTURAL_FAMILIES
    with manager.session() as conn:
        frame = build_feature_frame(conn, include_quarantined=include_quarantined)
        stats = analyze_features(frame)
        active, dropped = select_features(stats, scope)

        if len(active) < MIN_ACTIVE_FEATURES:
            reason = (
                f"only {len(active)} of {len(FEATURE_NAMES)} substrate features clear the "
                f"signal gate (need >= {MIN_ACTIVE_FEATURES}); refusing to rank companies on "
                f"near-constant inputs"
            )
            # A refusal is a result: record it so the decision is auditable later
            # instead of leaving the absence of rows unexplained.
            if apply:
                persist(
                    conn, frame, stats, active, dropped, [], top_k,
                    frame["contaminated_earnings_values"], "insufficient_signal", reason=reason,
                )
            result = {
                "status": "insufficient_signal",
                "reason": reason,
                "feature_families": list(scope),
                "active_features": active,
                "dropped_features": dropped,
                "feature_stats": stats,
                "n_symbols": len(frame["symbols"]),
                "n_anchors": 0,
                "written": 0,
                "pairs": 0,
            }
        else:
            neighbours_rows, baselines = compute_neighbours(frame, active, top_k=top_k)
            diagnostics = feature_diagnostics(stats, active, dropped, neighbours_rows, baselines)
            if apply:
                written = persist(
                    conn, frame, stats, active, dropped, neighbours_rows, top_k,
                    frame["contaminated_earnings_values"], "ok", baselines=baselines,
                    diagnostics=diagnostics,
                )
            else:
                written = {"written": 0, "status": "dry_run"}
            anchored = len({r["anchor_symbol"] for r in neighbours_rows})
            base_values = np.asarray(list(baselines.values()), dtype=float) if baselines else np.asarray([])
            result = {
                "status": "ok" if anchored else "insufficient_signal",
                "reason": None if anchored else (
                    "no company carries the minimum feature support to act as an anchor"
                ),
                "feature_families": list(scope),
                "active_features": active,
                "dropped_features": dropped,
                "feature_stats": stats,
                "diagnostics": diagnostics,
                "n_symbols": len(frame["symbols"]),
                "n_anchors": anchored,
                "n_symbols_below_anchor_floor": len(frame["symbols"]) - int(
                    _anchor_mask(frame, active).sum()
                ),
                "baseline_similarity_median": round(float(np.median(base_values)), 4)
                if base_values.size else None,
                "baseline_similarity_p10": round(float(np.quantile(base_values, 0.10)), 4)
                if base_values.size else None,
                "top_k": int(top_k),
                "pairs": len(neighbours_rows),
                **written,
            }

        result["quarantined_excluded"] = len(frame["quarantined_excluded"])
        result["contaminated_earnings_values"] = frame["contaminated_earnings_values"]
    return result


if __name__ == "__main__":  # pragma: no cover - manual invocation
    print(json.dumps(main(), indent=2, default=str)[:4000])
