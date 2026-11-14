"""T-210: factor-reward deep study (T-207 round 3).

Deepens the T-207 point-in-time reward study from the universe to sector groups
and single companies, and answers what round 1 could not: which factor exposures
move together or oppositely, which factors stop mattering once the others are
known, which factor pairs interact, and a sparse walk-forward combination per
sector against the fixed EQUAL convention score and the universe DYNAMIC set. A
thin sector-KPI arm reads the pilot stores and is labelled method pilot.

It imports the T-207 engine (:mod:`reality_engine.research.factor_rewards`) and
the T-118 panel builder (:mod:`reality_engine.research.factor_weights`) unchanged
and reads the dated DuckDB snapshot read-only. See
`docs/research/T-210_factor_deep_study.md`.

    python -m reality_engine.research.factor_deep --out .tmp/t210
"""

from __future__ import annotations

import argparse
import gc
import math
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from reality_engine.research.factor_rewards import (
    BH_Q,
    EQUAL_SIGN,
    MAIN_WINDOW,
    MIN_IC_NAMES,
    MIN_KNOWN_MONTHS,
    SIGN_SHARE_MIN,
    STAT_YEAR,
    STABLE_SHARE,
    T_MIN,
    bh_survivors,
    bh_table,
    build_rewarded,
    known_dates_for,
    mode_table,
    monthly_ic_grouped,
    normalise_sector,
    realised_ic,
    rewarded_sets,
    sector_map,
)
from reality_engine.research.factor_weights import (
    FACTORS,
    HORIZONS,
    NW_LAGS,
    connect,
    default_snapshot,
    newey_west_tstat,
)

# --------------------------------------------------------------------------- #
# Thresholds fixed before any result was seen (brief, 14 Nov)
# --------------------------------------------------------------------------- #
CORR_MOVE = 0.50          # |rho| at which a pair "moves together" / is opposite
CORR_CLUSTER = 0.70       # |rho| at which a pair joins one cluster
INTERACTION_T = 2.5       # |Newey-West t| of the top-minus-bottom IC difference
INTERACTION_MIN_NAMES = 20  # names in a tercile for its rank IC
INTERACTION_RUNS = 20     # within-date permutations of the conditioning factor
INTERACTION_PCT = 95.0    # observed |t| must beat this percentile of the null
REDUNDANT_T = 1.5         # multivariate |t| below which a rewarded factor is redundant
STEP_MAX = 6              # factors in a sparse combination
STEP_MIN_GAIN = 0.005     # trailing-window IC gain needed to add a factor
STEP_MIN_ABS_IC = 0.02    # candidate pool: trailing |univariate IC| floor
STEP_POOL = 8             # cap on the candidate pool when the floor leaves too few/many
COMPANY_MIN_MONTHS = 24   # usable months for a company's own estimate
COMPANY_DIFF = 0.10       # |shrunk - sector prior| that makes a company's gap reportable
COMBINE_T = 2.0           # sparse minus a baseline, paired NW |t|, says "beats"
MIN_TEST_MONTHS = 12      # walk-forward months needed before a combination is claimed
KPI_MIN_COMPANIES = 8     # companies a KPI metric needs inside a sector group
KPI_MIN_NAMES = 6         # cross-section a KPI rank IC needs (method pilot, thin)
PLACEBO_SEED = 20261114
PLACEBO_RUNS = 20
KPI_ROOT = "D:/RealityEngine"
KPI_STORES = (
    "p20/p20new.db", "u8/u8.db", "q12/q12.db", "n10/n10.db",
    "pilot10/pilot10.db", "aurobindo/aurobindo.db", "bluestar/bluestar.db",
)


# --------------------------------------------------------------------------- #
# Rank helpers (average ranks, so ties are handled like the engine's Spearman)
# --------------------------------------------------------------------------- #
def avg_ranks(values) -> np.ndarray:
    """Average ranks of the finite values; NaN stays NaN."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    ok = np.isfinite(v)
    if ok.sum() < 2:
        return out
    uniq, inv, counts = np.unique(v[ok], return_inverse=True, return_counts=True)
    cum = np.cumsum(counts)
    out[ok] = (cum - counts + (counts + 1.0) / 2.0)[inv]
    return out


def rank_ic(score, target, min_n: int = INTERACTION_MIN_NAMES) -> float:
    """Spearman rank correlation of two aligned series; NaN when unusable."""
    s = np.asarray(score, dtype=float)
    t = np.asarray(target, dtype=float)
    ok = np.isfinite(s) & np.isfinite(t)
    if int(ok.sum()) < min_n:
        return float("nan")
    rs, rt = avg_ranks(s[ok]), avg_ranks(t[ok])
    cs, ct = rs - rs.mean(), rt - rt.mean()
    den = math.sqrt(float(cs @ cs) * float(ct @ ct))
    if not np.isfinite(den) or den <= 0.0:
        return float("nan")
    return float(cs @ ct / den)


def two_sided_p(t: float) -> float:
    """Two-sided normal p for a t-stat (the NW t is the studentised mean)."""
    t = float(t)
    if not np.isfinite(t):
        return 1.0
    return float(math.erfc(abs(t) / math.sqrt(2.0)))


# --------------------------------------------------------------------------- #
# Panel split: sector groups, exactly as T-207 folded them
# --------------------------------------------------------------------------- #
def add_sector_group(panel: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Attach the T-207 sector group; no company_industry label stays NaN."""
    out = panel.copy()
    out["sector_group"] = out["sector"].map(normalise_sector).map(mapping)
    return out


def group_names(panel: pd.DataFrame) -> list[str]:
    """Sector groups present, without the NaN (unclassified) group."""
    values = [g for g in panel["sector_group"].dropna().unique()]
    return sorted(str(g) for g in values)


def permute_within_groups(
    panel: pd.DataFrame, group_col: str, seed: int, factors: list[str] | None = None
) -> pd.DataFrame:
    """Shuffle each factor's non-null values inside each (group, date).

    The null for an interaction question: the factor's own cross-sectional
    distribution and null mask survive, only its assignment to companies moves.
    """
    factors = factors or list(FACTORS)
    out = panel.copy()
    groups = list(out.groupby([group_col, "date"], observed=True, sort=False).indices.values())
    rng = np.random.default_rng(seed)
    for factor in factors:
        col = out[factor].to_numpy(dtype=float, copy=True)
        for positions in groups:
            values = col[positions]
            ok = ~np.isnan(values)
            if ok.sum() > 1:
                shuffled = values[ok].copy()
                rng.shuffle(shuffled)
                values[ok] = shuffled
                col[positions] = values
        out[factor] = col
    return out


# --------------------------------------------------------------------------- #
# Correlations: exposures (do the bets overlap?) and ICs (do the rewards?)
# --------------------------------------------------------------------------- #
def exposure_corr(
    panel: pd.DataFrame,
    factors: list[str] | None = None,
    group_col: str = "sector_group",
    min_names: int = INTERACTION_MIN_NAMES,
    min_months: int = MIN_KNOWN_MONTHS,
) -> pd.DataFrame:
    """Per sector: mean cross-sectional Spearman correlation of factor exposures.

    Correlations are pairwise-complete (a factor pair uses the companies carrying
    both), computed at every month-end and averaged over the months.
    """
    factors = factors or list(FACTORS)
    rows = []
    for group, g in panel.groupby(group_col, observed=True, sort=True):
        if not isinstance(group, str):
            continue
        mats = []
        for _, sub in g.groupby("date", observed=True, sort=True):
            if len(sub) < min_names:
                continue
            mats.append(sub[factors].corr(method="spearman"))
        if len(mats) < min_months:
            continue
        mean = pd.concat(mats, axis=0).groupby(level=0).mean(numeric_only=True)
        for i, a in enumerate(factors):
            for b in factors[i + 1:]:
                rows.append({"group": group, "factor_a": a, "factor_b": b,
                             "rho": float(mean.at[a, b]), "months": len(mats)})
    return pd.DataFrame(rows, columns=["group", "factor_a", "factor_b", "rho", "months"])


def ic_corr(
    ic_table: pd.DataFrame, horizon: str, min_months: int = MIN_KNOWN_MONTHS
) -> pd.DataFrame:
    """Per sector: time-series correlation of the monthly factor ICs.

    High positive rho: the two factors' rewards rise and fall together. High
    negative rho: when one is rewarded the other is not (an opposite pair).
    """
    d = ic_table[(ic_table["horizon"] == horizon) & (ic_table["split"] == "sector")]
    rows = []
    for group, g in d.groupby("group", observed=True, sort=True):
        p = g.pivot_table(index="date", columns="factor", values="ic")
        if len(p) < min_months or p.shape[1] < 2:
            continue
        c = p.corr(method="spearman")
        cols = list(c.columns)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                rows.append({"group": group, "horizon": horizon, "factor_a": a,
                             "factor_b": b, "rho": float(c.at[a, b]), "months": len(p)})
    return pd.DataFrame(rows, columns=["group", "horizon", "factor_a", "factor_b", "rho", "months"])


def _clusters(pairs: pd.DataFrame, rho_cluster: float = CORR_CLUSTER) -> dict[str, str]:
    """Connected components of the |rho| >= threshold graph: factor -> component.

    The component is named after its alphabetically first member. Twelve lines of
    union-find beat pulling scipy into a research script for one label.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for row in pairs.itertuples(index=False):
        if np.isfinite(row.rho) and abs(row.rho) >= rho_cluster:
            union(row.factor_a, row.factor_b)
    return {node: find(node) for node in list(parent)}


def pair_relations(table: pd.DataFrame, rho_move: float = CORR_MOVE) -> pd.DataFrame:
    """Label every pair: together / opposite / none, plus a within-group cluster id."""
    out = table.copy()
    out["relation"] = np.select(
        [out["rho"] >= rho_move, out["rho"] <= -rho_move],
        ["together", "opposite"],
        default="none",
    )
    cluster = {}
    if not out.empty:
        for group, g in out.groupby("group", observed=True):
            for factor, label in _clusters(g).items():
                cluster[(group, factor)] = label
    out["cluster"] = [cluster.get((row.group, row.factor_a), row.factor_a) for row in out.itertuples()]
    return out


# --------------------------------------------------------------------------- #
# Per-company estimates: own time-series IC, shrunk towards the sector's
# --------------------------------------------------------------------------- #
def company_estimates(
    panel: pd.DataFrame,
    calendar,
    horizon: str,
    as_of,
    factors: list[str] | None = None,
    min_months: int = COMPANY_MIN_MONTHS,
) -> pd.DataFrame:
    """Company x factor time-series rank IC over months realised by ``as_of``.

    The estimate is the rank correlation, across the months the company has, of
    its factor exposure with its own forward excess return. Only months whose
    forward window had closed by ``as_of`` are used (no look-ahead).
    """
    factors = factors or list(FACTORS)
    target = f"excess_{HORIZONS[horizon]}"
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    known = known_dates_for(pd.Series(dates), calendar, HORIZONS[horizon])
    usable = {d for d, k in zip(dates, known) if pd.notna(k) and pd.Timestamp(k) <= pd.Timestamp(as_of)}
    d0 = panel[panel["date"].isin(usable)]
    sector = d0.dropna(subset=["sector_group"]).groupby("entity_id", observed=True)["sector_group"].last()
    rows = []
    for factor in factors:
        d = d0[["entity_id", factor, target]].dropna()
        if d.empty:
            continue
        d = d.assign(rx=d.groupby("entity_id", observed=True)[factor].rank(),
                     ry=d.groupby("entity_id", observed=True)[target].rank())
        d = d.assign(cx=d["rx"] - d.groupby("entity_id", observed=True)["rx"].transform("mean"),
                     cy=d["ry"] - d.groupby("entity_id", observed=True)["ry"].transform("mean"))
        g = d.groupby("entity_id", observed=True)
        num = (d["cx"] * d["cy"]).groupby(d["entity_id"], observed=True).sum()
        vx = (d["cx"] ** 2).groupby(d["entity_id"], observed=True).sum()
        vy = (d["cy"] ** 2).groupby(d["entity_id"], observed=True).sum()
        den = np.sqrt(vx * vy)
        ic = (num / den.replace(0.0, np.nan)).rename("ic")
        n = g.size().rename("months")
        f = pd.concat([ic, n], axis=1).reset_index()
        f["factor"] = factor
        f["horizon"] = horizon
        f["sector_group"] = f["entity_id"].map(sector)
        rows.append(f[(f["months"] >= min_months) & np.isfinite(f["ic"])])
    if not rows:
        return pd.DataFrame(columns=["entity_id", "factor", "horizon", "ic", "months", "sector_group"])
    return pd.concat(rows, ignore_index=True)[
        ["entity_id", "factor", "horizon", "sector_group", "months", "ic"]
    ]


def shrink_estimates(own: pd.DataFrame, min_months: int = COMPANY_MIN_MONTHS) -> pd.DataFrame:
    """Empirical-Bayes shrinkage of each company's IC towards its sector's.

    Sampling variance s^2 = (1 - r^2) / (n - 2). Between-company variance tau^2 =
    max(0, var(own ICs) - mean(s^2)) over the sector's companies that have at
    least ``min_months``. Weight w = tau^2 / (tau^2 + s^2). A company below the
    month floor is reported sector-only (w = 0) and says so.
    """
    rows = []
    for (factor, horizon), fg in own.groupby(["factor", "horizon"], observed=True, sort=False):
        fg = fg.copy()
        fg["s2"] = ((1.0 - fg["ic"] ** 2) / (fg["months"] - 2).clip(lower=1)).clip(lower=1e-6)
        eligible = fg[fg["months"] >= min_months]
        universe_mean = float(eligible["ic"].mean()) if len(eligible) else float(fg["ic"].mean())
        priors: dict[str, float] = {}
        tau2s: dict[str, float] = {}
        for sector, sg in eligible.groupby("sector_group", observed=True):
            if len(sg) < 2:
                continue
            between = float(sg["ic"].var(ddof=1))
            if not np.isfinite(between):
                continue
            tau2 = max(0.0, between - float(sg["s2"].mean()))
            priors[str(sector)] = float(sg["ic"].mean())
            tau2s[str(sector)] = tau2
        for row in fg.itertuples(index=False):
            sector = str(row.sector_group) if isinstance(row.sector_group, str) else ""
            prior = priors.get(sector, universe_mean)
            tau2 = tau2s.get(sector, 0.0)
            thin = bool(row.months < min_months)
            weight = 0.0 if thin else float(tau2 / (tau2 + row.s2)) if (tau2 + row.s2) > 0 else 0.0
            rows.append({
                "entity_id": row.entity_id,
                "factor": factor,
                "horizon": horizon,
                "sector_group": row.sector_group,
                "months": int(row.months),
                "own_ic": float(row.ic),
                "sampling_var": float(row.s2),
                "sector_prior_ic": prior,
                "shrink_weight": weight,
                "shrunk_ic": weight * float(row.ic) + (1.0 - weight) * prior,
                "sector_only": thin,
            })
    return pd.DataFrame(rows)


def company_gaps(shrunk: pd.DataFrame, diff: float = COMPANY_DIFF,
                 top: int = 200) -> pd.DataFrame:
    """Factors where the shrunk estimate is materially away from the sector prior."""
    if shrunk.empty:
        return shrunk
    out = shrunk.assign(gap=shrunk["shrunk_ic"] - shrunk["sector_prior_ic"], abs_gap=lambda d: d["gap"].abs())
    out = out[out["abs_gap"] >= diff]
    return out.sort_values(["months", "abs_gap"], ascending=[False, False]).head(top).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Redundancy: univariate reward versus the joint Fama-MacBeth model
# --------------------------------------------------------------------------- #
def univariate_sector(ic_table: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """Per sector x factor: the T-207 test on the sector's full IC series.

    |NW t| >= 2 and the sign matching at least 60% of the months is the same rule
    T-207 applies to a trailing window; here it is applied to every usable month,
    which is the "univariate reward is significant" condition of the brief.
    """
    d = ic_table[(ic_table["horizon"] == horizon) & (ic_table["split"] == "sector")]
    rows = []
    for (group, factor), g in d.groupby(["group", "factor"], observed=True, sort=False):
        v = g["ic"].dropna()
        if len(v) < MIN_KNOWN_MONTHS:
            continue
        mean = float(v.mean())
        sign = 1 if mean > 0 else (-1 if mean < 0 else 0)
        share = float((np.sign(v) == sign).mean()) if sign else 0.0
        t = newey_west_tstat(v.to_numpy(dtype=float), NW_LAGS[horizon])
        rows.append({
            "group": group, "horizon": horizon, "factor": factor,
            "univariate_months": int(len(v)), "univariate_mean_ic": mean,
            "univariate_nw_t": t, "univariate_sign_share": share,
            "univariate_sign": sign,
            "univariate_significant": bool(np.isfinite(t) and abs(t) >= T_MIN and share >= SIGN_SHARE_MIN),
        })
    return pd.DataFrame(rows)


def fama_macbeth_sector(
    panel: pd.DataFrame,
    horizon: str,
    factors_by_group: dict[str, list[str]],
    group_col: str = "sector_group",
    min_names: int = 30,
    min_months: int = MIN_KNOWN_MONTHS,
) -> pd.DataFrame:
    """Monthly cross-sectional OLS inside each sector, then Newey-West on the coefs."""
    target = f"excess_{HORIZONS[horizon]}"
    rows = []
    for group, factors in factors_by_group.items():
        if not factors:
            continue
        zcols = [f + "_z" for f in factors]
        g = panel[(panel[group_col] == group)]
        coefs, sizes = [], []
        for _, sub in g.groupby("date", observed=True, sort=True):
            sub = sub.dropna(subset=zcols + [target])
            if len(sub) < min_names:
                continue
            X = np.column_stack([np.ones(len(sub))] + [sub[c].to_numpy(dtype=float) for c in zcols])
            beta, *_ = np.linalg.lstsq(X, sub[target].to_numpy(dtype=float), rcond=None)
            coefs.append(beta[1:])
            sizes.append(len(sub))
        if len(coefs) < min_months:
            continue
        coef = pd.DataFrame(coefs, columns=factors)
        for factor in factors:
            rows.append({
                "group": group, "horizon": horizon, "factor": factor,
                "multivariate_mean_coef": float(coef[factor].mean()),
                "multivariate_nw_t": newey_west_tstat(coef[factor], NW_LAGS[horizon]),
                "multivariate_months": int(coef[factor].notna().sum()),
                "mean_names": float(np.mean(sizes)),
            })
    return pd.DataFrame(rows)


def model_representatives(
    exposure: pd.DataFrame, univariate: pd.DataFrame, horizon: str,
    coverage: pd.DataFrame | None = None, min_coverage: float = 0.80,
    max_factors: int = 8, rho_cluster: float = CORR_CLUSTER,
) -> dict[str, list[str]]:
    """Per sector, the factors that enter the joint Fama-MacBeth model.

    One member per |rho| >= 0.7 cluster (its strongest univariate |t|, so the
    cluster's information survives and its twins are reported, never silently
    dropped), only factors with >= ``min_coverage`` non-null company-months in
    that sector, capped at ``max_factors``: a complete-case OLS over 30 names
    cannot carry thirty regressors.
    """
    uni = univariate[univariate["horizon"] == horizon].set_index(["group", "factor"])
    cov: dict[tuple[str, str], float] = {}
    if coverage is not None:
        cov = {(str(r.group), str(r.factor)): float(r.coverage) for r in coverage.itertuples(index=False)}

    def strength(group: str, factor: str) -> float:
        if (group, factor) in uni.index:
            t = uni.loc[(group, factor), "univariate_nw_t"]
            return abs(float(t)) if np.isfinite(t) else -1.0
        return -1.0

    out: dict[str, list[str]] = {}
    for group, g in exposure.groupby("group", observed=True):
        all_factors = sorted(set(g["factor_a"].astype(str)) | set(g["factor_b"].astype(str)))
        cluster_of = _clusters(g, rho_cluster)
        members: dict[str, list[str]] = {}
        for factor in all_factors:
            if cov and cov.get((str(group), factor), 0.0) < min_coverage:
                continue
            members.setdefault(cluster_of.get(factor, factor), []).append(factor)
        chosen = [max(fs, key=lambda f: strength(str(group), f)) for fs in members.values()]
        chosen = sorted(chosen, key=lambda f: -strength(str(group), f))[:max_factors]
        out[str(group)] = sorted(chosen)
    return out


def redundancy_table(
    univariate: pd.DataFrame, fm: pd.DataFrame, model: dict[str, list[str]],
    exposure: pd.DataFrame,
) -> pd.DataFrame:
    """Flag factors whose univariate reward does not survive the joint model."""
    fm_idx = fm.set_index(["group", "factor", "horizon"]).sort_index() if not fm.empty else None
    rows = []
    for row in univariate.itertuples(index=False):
        in_model = row.factor in model.get(str(row.group), [])
        mv_t = np.nan
        mv_months = 0
        key = (row.group, row.factor, row.horizon)
        if in_model and fm_idx is not None and key in fm_idx.index:
            mv_t = float(fm_idx.loc[key, "multivariate_nw_t"])
            mv_months = int(fm_idx.loc[key, "multivariate_months"])
        clustered = False
        if not in_model:
            sub = exposure[(exposure["group"] == row.group)
                           & ((exposure["factor_a"] == row.factor) | (exposure["factor_b"] == row.factor))]
            clustered = bool((sub["rho"].abs() >= CORR_CLUSTER).any())
        rows.append({
            "group": row.group, "horizon": row.horizon, "factor": row.factor,
            "univariate_nw_t": row.univariate_nw_t,
            "univariate_sign_share": row.univariate_sign_share,
            "univariate_significant": row.univariate_significant,
            "in_model": in_model,
            "clustered_out": bool(clustered and not in_model),
            "multivariate_nw_t": mv_t,
            "multivariate_months": mv_months,
            "redundant": bool(row.univariate_significant and in_model and np.isfinite(mv_t) and abs(mv_t) < REDUNDANT_T),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Interactions: IC of A inside the top and the bottom tercile of B
# --------------------------------------------------------------------------- #
def _tercile_masks(b: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Top and bottom tercile of ``b`` where both b and y are finite."""
    ok = np.isfinite(b) & np.isfinite(y)
    if int(ok.sum()) < 3 * INTERACTION_MIN_NAMES:
        return None
    values = b[ok]
    lo_q, hi_q = np.quantile(values, [1.0 / 3.0, 2.0 / 3.0])
    hi = ok & (b >= hi_q)
    lo = ok & (b <= lo_q)
    if int(hi.sum()) < INTERACTION_MIN_NAMES or int(lo.sum()) < INTERACTION_MIN_NAMES:
        return None
    return hi, lo


def _interaction_pass(
    panel: pd.DataFrame, horizon: str, factors: list[str],
    permuted: pd.DataFrame | None = None, group_col: str = "sector_group",
) -> pd.DataFrame:
    """Every unordered pair's monthly IC(top tercile of B) - IC(bottom tercile).

    ``permuted``, when given, supplies only the conditioning factor's values (the
    brief's within-date permutation of B); A and the target stay real.
    """
    target = f"excess_{HORIZONS[horizon]}"
    order = {f: i for i, f in enumerate(factors)}
    rows = []
    for group, g in panel.groupby(group_col, observed=True, sort=True):
        if not isinstance(group, str):
            continue
        for date, sub in g.groupby("date", observed=True, sort=True):
            sub = sub.dropna(subset=[target])
            if len(sub) < 3 * INTERACTION_MIN_NAMES:
                continue
            y = sub[target].to_numpy(dtype=float)
            for pivot in factors:
                later = [a for a in factors if order[a] > order[pivot]]
                if not later:
                    continue
                if permuted is None:
                    b = sub[pivot].to_numpy(dtype=float)
                else:
                    b = permuted.loc[sub.index, pivot].to_numpy(dtype=float)
                masks = _tercile_masks(b, y)
                if masks is None:
                    continue
                hi, lo = masks
                top = sub.loc[hi, later]
                bottom = sub.loc[lo, later]
                yt = y[hi]
                yb = y[lo]
                for a in later:
                    ic_hi = rank_ic(top[a].to_numpy(dtype=float), yt)
                    ic_lo = rank_ic(bottom[a].to_numpy(dtype=float), yb)
                    if np.isfinite(ic_hi) and np.isfinite(ic_lo):
                        rows.append((group, date, a, pivot, ic_hi - ic_lo))
    return pd.DataFrame(rows, columns=["group", "date", "factor_a", "factor_b", "diff"])


def _summarise_interactions(long: pd.DataFrame, horizon: str, lags: int | None = None) -> pd.DataFrame:
    """Per sector x pair: mean difference, its Newey-West t and the month count."""
    if long.empty:
        return pd.DataFrame(columns=["group", "horizon", "factor_a", "factor_b",
                                     "months", "mean_diff", "nw_t"])
    lags = NW_LAGS[horizon] if lags is None else lags
    rows = []
    for (group, a, b), g in long.groupby(["group", "factor_a", "factor_b"], observed=True, sort=False):
        v = g["diff"].to_numpy(dtype=float)
        rows.append({
            "group": group, "horizon": horizon, "factor_a": a, "factor_b": b,
            "months": int(len(v)), "mean_diff": float(v.mean()),
            "nw_t": newey_west_tstat(v, lags) if len(v) >= 3 else float("nan"),
        })
    return pd.DataFrame(rows)


def interaction_claims(
    observed: pd.DataFrame, null: pd.DataFrame | None = None,
    t_min: float = INTERACTION_T, q: float = BH_Q, pct: float = INTERACTION_PCT,
) -> pd.DataFrame:
    """Survivors of the three gates: |t|, BH over every test, and the permutation percentile."""
    if observed.empty:
        return observed.assign(bh_survive=[], placebo_pct=[], placebo_pass=[], claimed=[])
    out = observed.copy()
    tested = out[out["months"] >= MIN_KNOWN_MONTHS].copy()
    tested["p_value"] = [two_sided_p(t) for t in tested["nw_t"]]
    tested["bh_survive"] = bh_survivors(tested["p_value"].to_numpy(float), q, len(out))
    if null is not None and not null.empty:
        null_abs = null.assign(abs_t=lambda d: d["nw_t"].abs())
        pct_vals = (null_abs.groupby(["group", "horizon", "factor_a", "factor_b"], observed=True)["abs_t"]
                    .apply(lambda s: float(np.nanpercentile(s, pct)) if s.notna().any() else np.nan))
        tested["placebo_pct"] = [pct_vals.get((r.group, r.horizon, r.factor_a, r.factor_b), np.nan)
                                 for r in tested.itertuples()]
        tested["placebo_pass"] = tested["nw_t"].abs() > tested["placebo_pct"]
    else:
        tested["placebo_pct"] = np.nan
        tested["placebo_pass"] = True
    tested["claimed"] = (
        (tested["nw_t"].abs() >= t_min) & tested["bh_survive"].fillna(False).astype(bool)
        & tested["placebo_pass"].fillna(False).astype(bool)
    )
    return tested.sort_values(["claimed", "nw_t"], key=lambda s: s.abs() if s.name == "nw_t" else s,
                              ascending=[False, False]).reset_index(drop=True)


def interaction_placebo_counts(
    null: pd.DataFrame | None, t_min: float = INTERACTION_T, q: float = BH_Q
) -> list[int]:
    """Per permutation run, the cells that pass the |t| gate and BH inside that run.

    This is the honest null claim count: the same gates and the same multiplicity
    correction applied to a panel whose conditioning factors were permuted.
    """
    if null is None or null.empty:
        return []
    counts = []
    for _, g in null.groupby("run", observed=True, sort=True):
        tested = g[g["months"] >= MIN_KNOWN_MONTHS]
        if tested.empty:
            counts.append(0)
            continue
        p_values = np.array([two_sided_p(t) for t in tested["nw_t"]], dtype=float)
        survive = bh_survivors(p_values, q, len(g))
        counts.append(int(((tested["nw_t"].abs() >= t_min) & survive).sum()))
    return counts


def interaction_study(
    panel: pd.DataFrame, horizons: list[str], factors: list[str] | None = None,
    runs: int = INTERACTION_RUNS, seed: int = PLACEBO_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Observed interaction table plus the seeded permutation null (if runs > 0)."""
    factors = factors or list(FACTORS)
    observed = pd.concat(
        [_summarise_interactions(_interaction_pass(panel, h, factors), h) for h in horizons],
        ignore_index=True,
    )
    if runs <= 0:
        return observed, None
    frames = []
    slim = panel[["sector_group", "date"] + factors]
    for run in range(runs):
        permuted = permute_within_groups(slim, "sector_group", seed + run, factors)
        for horizon in horizons:
            s = _summarise_interactions(_interaction_pass(panel, horizon, factors, permuted), horizon)
            if not s.empty:
                s["run"] = run
                frames.append(s)
        del permuted
        gc.collect()
    null = pd.concat(frames, ignore_index=True) if frames else None
    return observed, null


# --------------------------------------------------------------------------- #
# Sparse combination per sector: forward stepwise, then walk forward
# --------------------------------------------------------------------------- #
def training_months(known: dict[pd.Timestamp, pd.Timestamp], t: pd.Timestamp,
                    window: int = MAIN_WINDOW) -> list[pd.Timestamp]:
    """Month-ends whose forward window had closed by ``t`` inside the trailing window."""
    start = pd.Timestamp(t) - pd.DateOffset(months=window)
    return sorted(m for m, k in known.items() if pd.notna(k) and pd.Timestamp(k) <= t and pd.Timestamp(k) > start)


def _score_ic(frames: list[pd.DataFrame], signs: dict[str, int], target: str) -> float:
    """Mean monthly rank IC of sum(sign x z) over the training months."""
    values = []
    for frame in frames:
        score = np.zeros(len(frame))
        used = 0
        for factor, sign in signs.items():
            if factor + "_z" not in frame.columns:
                continue
            score = score + sign * frame[factor + "_z"].to_numpy(dtype=float)
            used += 1
        if not used:
            continue
        ic = rank_ic(score, frame[target].to_numpy(dtype=float))
        if np.isfinite(ic):
            values.append(ic)
    return float(np.mean(values)) if values else float("nan")


def forward_stepwise(
    frames: list[pd.DataFrame], target: str, pools: dict[str, float],
    max_steps: int = STEP_MAX, min_gain: float = STEP_MIN_GAIN,
) -> tuple[dict[str, int], float]:
    """Greedy add while the trailing-window IC rises by at least ``min_gain``.

    ``pools`` maps each candidate factor to its trailing univariate IC (its sign
    is the direction the score bets in). Never searches subsets.
    """
    selected: dict[str, int] = {}
    current = 0.0
    for _ in range(max_steps):
        best_factor, best_ic = "", current + min_gain
        for factor, trailing in pools.items():
            if factor in selected or not np.isfinite(trailing):
                continue
            signs = dict(selected)
            signs[factor] = 1 if trailing > 0 else -1
            ic = _score_ic(frames, signs, target)
            if np.isfinite(ic) and ic > best_ic:
                best_factor, best_ic = factor, ic
        if not best_factor:
            break
        selected[best_factor] = 1 if pools[best_factor] > 0 else -1
        current = best_ic
    return selected, current


def candidate_pool(trailing: dict[str, float], floor: float = STEP_MIN_ABS_IC,
                   cap: int = STEP_POOL) -> dict[str, float]:
    """Candidates for one stepwise call: the |IC| floor, else the top ``cap``."""
    pool = {f: v for f, v in trailing.items() if np.isfinite(v) and abs(v) >= floor}
    if len(pool) < 3:
        ranked = sorted((f for f in trailing if np.isfinite(trailing[f])),
                        key=lambda f: -abs(trailing[f]))
        pool = {f: trailing[f] for f in ranked[:cap]}
    elif len(pool) > cap:
        pool = dict(sorted(pool.items(), key=lambda kv: -abs(kv[1]))[:cap])
    return pool


def sparse_walk_forward(
    panel: pd.DataFrame, rewarded: pd.DataFrame, calendar, horizon: str,
    group_col: str = "sector_group", window: int = MAIN_WINDOW,
    max_steps: int = STEP_MAX, min_gain: float = STEP_MIN_GAIN,
    equal_signs: dict[str, int] | None = None, factors: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per sector: stepwise picks from data known at t, scored out of sample.

    Returns the monthly rows (sparse / EQUAL / DYNAMIC IC beside each other) and
    the scoring summary. The DYNAMIC score is the universe rewarded set at t, the
    T-207 all-companies choice, applied inside the sector.
    """
    equal_signs = equal_signs or EQUAL_SIGN
    target = f"excess_{HORIZONS[horizon]}"
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    known_frame = known_dates_for(pd.Series(dates), calendar, HORIZONS[horizon])
    known = {pd.Timestamp(d): pd.Timestamp(k) for d, k in zip(dates, known_frame) if pd.notna(k)}
    dyn = rewarded_sets(rewarded, horizon)
    factors = [f for f in (factors or FACTORS) if f in panel.columns and f + "_z" in panel.columns]
    zcols = [f + "_z" for f in factors]
    need_cols = ["date", target] + factors + zcols
    monthly = []
    for group, g in panel.groupby(group_col, observed=True, sort=True):
        if not isinstance(group, str):
            continue
        g_slim = g[need_cols]
        cache = {}
        for date, sub in g_slim.groupby("date", observed=True, sort=True):
            sub = sub.dropna(subset=[target])
            if len(sub) >= INTERACTION_MIN_NAMES:
                cache[pd.Timestamp(date)] = sub
        if len(cache) < MIN_KNOWN_MONTHS:
            del cache
            continue
        ic_cache: dict[tuple[pd.Timestamp, str], float] = {}
        for t in sorted(cache):
            train = training_months(known, t, window)
            train = [m for m in train if m in cache]
            if len(train) < MIN_KNOWN_MONTHS:
                continue
            nxt = [m for m in sorted(cache) if m > t]
            if not nxt:
                continue
            nxt = nxt[0]
            trailing = {}
            for factor in factors:
                vals = []
                for m in train:
                    key = (m, factor)
                    val = ic_cache.get(key)
                    if val is None:
                        val = rank_ic(cache[m][factor].to_numpy(dtype=float),
                                      cache[m][target].to_numpy(dtype=float))
                        ic_cache[key] = val
                    if np.isfinite(val):
                        vals.append(val)
                if len(vals) >= MIN_KNOWN_MONTHS:
                    trailing[factor] = float(np.mean(vals))
            pool = candidate_pool(trailing)
            if len(pool) < 2:
                continue
            selected, train_ic = forward_stepwise([cache[m] for m in train], target, pool,
                                                  max_steps=max_steps, min_gain=min_gain)
            if not selected:
                continue
            oos = cache[nxt]
            sparse_ic = _score_ic([oos], selected, target)
            equal_ic = _score_ic([oos], equal_signs, target)
            dynamic_ic = _score_ic([oos], dyn.get(t, {}), target)
            monthly.append({
                "group": group, "horizon": horizon, "date": t, "test_month": nxt,
                "factors": len(selected), "selected": ";".join(f"{f}:{s:+d}" for f, s in selected.items()),
                "train_months": len(train), "train_ic": train_ic,
                "sparse_ic": sparse_ic, "equal_ic": equal_ic, "dynamic_ic": dynamic_ic,
            })
        del cache, ic_cache
        gc.collect()
    mdf = pd.DataFrame(monthly)
    rows = []
    for group, g in mdf.groupby("group", observed=True, sort=True) if not mdf.empty else []:
        rows.append(_score_summary(g, horizon, group))
    if not mdf.empty:
        rows.append(_score_summary(mdf, horizon, "ALL SECTORS"))
    return mdf, pd.DataFrame(rows)


def _score_summary(g: pd.DataFrame, horizon: str, group: str) -> dict:
    """Mean IC per score and the paired differences, Newey-West lags = h - 1 months."""
    lags = NW_LAGS[horizon]
    months = len(g)
    row = {"group": group, "horizon": horizon, "months": months,
           "mean_factors": float(g["factors"].mean())}
    for name in ("sparse_ic", "equal_ic", "dynamic_ic"):
        v = g[name].dropna()
        row[f"mean_{name}"] = float(v.mean()) if len(v) else np.nan
        row[f"t_{name}"] = newey_west_tstat(v.to_numpy(float), lags) if len(v) >= 3 else np.nan
    for left, right, label in (
        ("sparse_ic", "equal_ic", "sparse_minus_equal"),
        ("sparse_ic", "dynamic_ic", "sparse_minus_dynamic"),
    ):
        both = g[[left, right]].dropna()
        d = (both[left] - both[right]).to_numpy(float)
        row[f"mean_{label}"] = float(d.mean()) if len(d) else np.nan
        row[f"t_{label}"] = newey_west_tstat(d, lags) if len(d) >= 3 else np.nan
    row["beats_both"] = bool(
        horizon == "12m"  # the claim horizon; 6m / 24m are reported descriptively
        and months >= MIN_TEST_MONTHS
        and np.isfinite(row["t_sparse_minus_equal"]) and row["t_sparse_minus_equal"] >= COMBINE_T
        and np.isfinite(row["t_sparse_minus_dynamic"]) and row["t_sparse_minus_dynamic"] >= COMBINE_T
    )
    return row


# --------------------------------------------------------------------------- #
# Sector-KPI arm (thin by construction: 52 pilot companies)
# --------------------------------------------------------------------------- #
def fiscal_index(text) -> float:
    """Quarter index for QnFYyy (H1 -> Q2, 9M -> Q3, FY -> Q4); NaN otherwise."""
    if not isinstance(text, str):
        return float("nan")
    s = text.upper().replace(" ", "")
    m = re.search(r"Q([1-4])FY(\d{2,4})", s)
    if m:
        return _fy_year(int(m.group(2))) * 4 + int(m.group(1))
    m = re.search(r"(9M)(?:FY)?(\d{2,4})", s)
    if m:
        return _fy_year(int(m.group(2))) * 4 + 3
    m = re.search(r"H1(?:FY)?(\d{2,4})", s)
    if m:
        return _fy_year(int(m.group(1))) * 4 + 2
    m = re.search(r"FY(\d{2,4})", s)
    if m:
        return _fy_year(int(m.group(1))) * 4 + 4
    return float("nan")


def _fy_year(value: int) -> int:
    return value + 2000 if value < 100 else value


def kpi_raw(root: Path, stores: tuple[str, ...] = KPI_STORES) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read every pilot store's kpi_series read-only; report the coverage per store."""
    frames, coverage = [], []
    for store in stores:
        path = root / store
        if not path.exists():
            coverage.append({"store": store, "exists": False, "rows": 0, "companies": 0})
            continue
        con = None
        try:
            from reality_engine.db.readonly import connect_ro
            con = connect_ro(path, timeout_s=30)
        except Exception as exc:  # a broken or absent pilot store must not kill the study
            coverage.append({"store": store, "exists": True, "rows": 0, "companies": 0, "error": str(exc)})
            continue
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
            if "kpi_series" not in tables:
                coverage.append({"store": store, "exists": True, "rows": 0, "companies": 0})
                continue
            df = pd.read_sql_query("SELECT * FROM kpi_series", con)
        except Exception as exc:  # a broken pilot store must not kill the study
            coverage.append({"store": store, "exists": True, "rows": 0, "companies": 0, "error": str(exc)})
            continue
        finally:
            con.close()
        keep = [c for c in ("symbol", "metric", "dimension", "value", "unit", "scale",
                            "fiscal_period", "as_of_date", "basis", "known_at") if c in df.columns]
        df = df[keep].copy()
        df["store"] = store
        frames.append(df)
        coverage.append({"store": store, "exists": True, "rows": int(len(df)),
                         "companies": int(df["symbol"].nunique()) if "symbol" in df else 0})
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return raw, pd.DataFrame(coverage)


def kpi_factor_panel(raw: pd.DataFrame) -> pd.DataFrame:
    """Company x quarter KPI factors: level, YoY change, and change in YoY."""
    if raw.empty:
        return pd.DataFrame(columns=["symbol", "metric", "dimension", "quarter", "known_at",
                                     "level", "yoy", "yoy_chg", "unit", "store"])
    d = raw.copy()
    if "dimension" in d.columns:
        d["dimension"] = d["dimension"].fillna("")
    else:
        d["dimension"] = ""
    d["quarter"] = [fiscal_index(p) for p in d["fiscal_period"]] if "fiscal_period" in d.columns else np.nan
    if "known_at" in d.columns:
        d["known_at"] = pd.to_datetime(d["known_at"], errors="coerce")
    elif "as_of_date" in d.columns:
        d["known_at"] = pd.to_datetime(d["as_of_date"], errors="coerce")
    else:
        d["known_at"] = pd.NaT
    d = d[np.isfinite(d["quarter"])].sort_values(["symbol", "metric", "dimension", "quarter", "known_at"])
    # one row per company-quarter: the latest snapshot of that period wins
    d = d.drop_duplicates(["symbol", "metric", "dimension", "quarter"], keep="last")
    keys = ["symbol", "metric", "dimension"]
    g = d.groupby(keys, observed=True, sort=False)
    d["lag_value"] = g["value"].shift(4)
    d["yoy"] = d["value"] / d["lag_value"].replace(0.0, np.nan) - 1.0
    d["yoy_prev"] = g["yoy"].shift(4)
    d["yoy_chg"] = d["yoy"] - d["yoy_prev"]
    out = d.rename(columns={"value": "level"})[
        ["symbol", "metric", "dimension", "quarter", "known_at", "level", "yoy", "yoy_chg", "unit", "store"]
    ]
    return out.dropna(subset=["quarter"]).reset_index(drop=True)


def kpi_ic(
    kpi: pd.DataFrame, panel: pd.DataFrame, horizons: list[str],
    group_col: str = "sector_group", min_companies: int = KPI_MIN_COMPANIES,
    min_names: int = KPI_MIN_NAMES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cross-sectional KPI ICs at 6 / 12 months, per metric representation.

    The exposure is known at the quarter's known_at; it is paired with the first
    month-end on or after it, whose forward excess return is the target. A metric
    needs at least ``min_companies`` companies inside a sector group (method pilot
    gate); the pooled row needs the same count across all companies.
    """
    empty = pd.DataFrame(columns=["group", "metric", "representation", "horizon",
                                  "months", "mean_ic", "nw_t"])
    if kpi.empty:
        return empty, pd.DataFrame()
    month_ends = pd.DataFrame({"date": pd.DatetimeIndex(sorted(panel["date"].unique()))})
    k = kpi.dropna(subset=["known_at"]).sort_values("known_at")
    aligned = pd.merge_asof(
        k, month_ends, left_on="known_at", right_on="date", direction="forward", tolerance=pd.Timedelta(days=100)
    ).dropna(subset=["date"])
    price = panel[["date", "symbol"] + [f"excess_{HORIZONS[h]}" for h in horizons]].dropna(subset=["symbol"])
    aligned = aligned.merge(price, on=["date", "symbol"], how="inner", suffixes=("", "_px"))
    sector = (panel.dropna(subset=[group_col]).groupby("symbol", observed=True)[group_col].last())
    aligned["sector_group"] = aligned["symbol"].map(sector)
    rows, coverage = [], []
    reps = ["level", "yoy", "yoy_chg"]
    for (metric, dimension), g in aligned.groupby(["metric", "dimension"], observed=True, sort=True):
        for horizon in horizons:
            target = f"excess_{HORIZONS[horizon]}"
            for group_name, gg in [("ALL", g)] + [(str(s), sub) for s, sub in g.groupby("sector_group", observed=True)]:
                companies = int(gg["symbol"].nunique())
                needed = min_companies if group_name != "ALL" else min_companies
                if companies < needed:
                    continue
                for rep in reps:
                    vals = []
                    for _, sub in gg.groupby("date", observed=True):
                        ic = rank_ic(sub[rep].to_numpy(dtype=float),
                                     sub[target].to_numpy(dtype=float), min_names)
                        if np.isfinite(ic):
                            vals.append(ic)
                    if len(vals) >= 6:
                        rows.append({"group": group_name, "metric": metric, "dimension": dimension,
                                     "representation": rep, "horizon": horizon, "months": len(vals),
                                     "mean_ic": float(np.mean(vals)),
                                     "nw_t": newey_west_tstat(np.array(vals), NW_LAGS[horizon])})
                coverage.append({"group": group_name, "metric": metric, "dimension": dimension,
                                 "horizon": horizon, "companies": companies})
    return pd.DataFrame(rows), pd.DataFrame(coverage)


def kpi_interactions(kpi: pd.DataFrame, panel: pd.DataFrame, horizon: str = "12m",
                     min_companies: int = KPI_MIN_COMPANIES) -> pd.DataFrame:
    """IC of one KPI metric inside terciles of another, for metrics meeting the gate.

    The main arm's 20-name tercile rule cannot apply to 8-company pilot metrics, so
    each tercile needs only three names here; every row is labelled method pilot.
    """
    empty = pd.DataFrame(columns=["group", "metric_a", "metric_b", "months", "mean_diff", "nw_t"])
    if kpi.empty:
        return empty
    month_ends = pd.DataFrame({"date": pd.DatetimeIndex(sorted(panel["date"].unique()))})
    k = kpi.dropna(subset=["known_at"]).sort_values("known_at")
    aligned = pd.merge_asof(
        k, month_ends, left_on="known_at", right_on="date", direction="forward", tolerance=pd.Timedelta(days=100)
    ).dropna(subset=["date"])
    price = panel[["date", "symbol", f"excess_{HORIZONS[horizon]}"]].dropna(subset=["symbol"])
    aligned = aligned.merge(price, on=["date", "symbol"], how="inner")
    target = f"excess_{HORIZONS[horizon]}"
    pairs = []
    for date, d in aligned.groupby("date", observed=True, sort=True):
        counts = d.groupby("metric", observed=True)["symbol"].nunique()
        metrics = [m for m in counts.index if int(counts[m]) >= min_companies]
        for i, ma in enumerate(metrics):
            a = d[d["metric"] == ma].drop_duplicates("symbol")
            for mb in metrics[i + 1:]:
                b = d[d["metric"] == mb].drop_duplicates("symbol")
                joined = a.merge(b[["symbol", "level", "yoy"]], on="symbol", suffixes=("", "_b"))
                if len(joined) < min_companies:
                    continue
                y = joined[target].to_numpy(dtype=float)
                for ra in ("level", "yoy"):
                    for rb in ("level", "yoy"):
                        xa = joined[ra].to_numpy(dtype=float)
                        xb = joined[rb].to_numpy(dtype=float)
                        ok = np.isfinite(xa) & np.isfinite(xb) & np.isfinite(y)
                        if int(ok.sum()) < 2 * 3:
                            continue
                        lo_q, hi_q = np.quantile(xb[ok], [1.0 / 3.0, 2.0 / 3.0])
                        hi = ok & (xb >= hi_q)
                        lo = ok & (xb <= lo_q)
                        if int(hi.sum()) < 3 or int(lo.sum()) < 3:
                            continue
                        ic_hi = rank_ic(xa[hi], y[hi], 3)
                        ic_lo = rank_ic(xa[lo], y[lo], 3)
                        if np.isfinite(ic_hi) and np.isfinite(ic_lo):
                            pairs.append((f"{ra}:{ma}", f"{rb}:{mb}", date, ic_hi - ic_lo))
    if not pairs:
        return empty
    long = pd.DataFrame(pairs, columns=["metric_a", "metric_b", "date", "diff"])
    rows = []
    for (ma, mb), g in long.groupby(["metric_a", "metric_b"], observed=True):
        v = g["diff"].to_numpy(dtype=float)
        rows.append({"group": "ALL", "metric_a": ma, "metric_b": mb, "months": len(v),
                     "mean_diff": float(v.mean()),
                     "nw_t": newey_west_tstat(v, NW_LAGS[horizon]) if len(v) >= 3 else np.nan})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _sector_ic_table(
    panel: pd.DataFrame, dates: pd.DatetimeIndex, calendar, factors: list[str]
) -> pd.DataFrame:
    """All-companies and sector-group ICs (the two splits this study needs).

    Reuses the T-207 primitives (:func:`realised_ic`, :func:`monthly_ic_grouped`)
    and skips its size and regime splits, which T-210 does not report.
    """
    frames = []
    for horizon, sessions in HORIZONS.items():
        target = f"excess_{sessions}"
        for factor in factors:
            base = realised_ic(panel, factor, horizon, calendar, target)
            if base.empty:
                continue
            frames.append(base.assign(horizon=horizon, split="all", group="all", factor=factor))
            grouped = monthly_ic_grouped(panel, factor, target, "sector_group", 30)
            if grouped.empty:
                continue
            grouped = grouped.merge(base[["date", "known_date"]], on="date", how="inner")
            frames.append(grouped.assign(horizon=horizon, split="sector", factor=factor))
    out = pd.concat(frames, ignore_index=True)
    return out[["horizon", "split", "group", "factor", "date", "known_date", "ic"]]


def _needed_panel_columns() -> list[str]:
    """Only the columns factor_deep reads (drops *_sn and raw intermediate columns)."""
    return (
        ["date", "entity_id", "symbol", "sector", "excess_126", "excess_252", "excess_504"]
        + list(FACTORS)
        + [f + "_z" for f in FACTORS]
    )


def _load_panel_slice(panel_path: Path) -> pd.DataFrame:
    """Read only needed columns from parquet and downcast *_z columns to float32."""
    import pyarrow.parquet as pq

    available = set(pq.read_schema(panel_path).names)
    cols = [c for c in _needed_panel_columns() if c in available]
    panel = pd.read_parquet(panel_path, columns=cols)
    for f in FACTORS:
        zc = f + "_z"
        if zc in panel.columns:
            panel[zc] = panel[zc].astype(np.float32)
    return panel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-210 factor-reward deep study")
    ap.add_argument("--out", default=".tmp/t210")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--start", default="2019-06-01")
    ap.add_argument("--end", default="2026-11-03")
    ap.add_argument("--rebuild-panel", action="store_true")
    ap.add_argument("--placebo-runs", type=int, default=PLACEBO_RUNS)
    ap.add_argument("--no-placebo", action="store_true")
    ap.add_argument("--skip-kpi", action="store_true")
    ap.add_argument("--kpi-root", default=KPI_ROOT)
    ap.add_argument("--sector-groups", default=None,
                    help="optional comma-separated subset of sector groups to run")
    ap.add_argument("--project", action="store_true",
                    help="time one sector and print the full-run projection, then stop")
    args = ap.parse_args(argv)

    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = Path(args.snapshot) if args.snapshot else default_snapshot()
    panel_path = out / "panel.parquet"
    runs = 0 if args.no_placebo else max(0, args.placebo_runs)

    if panel_path.exists() and not args.rebuild_panel:
        panel = _load_panel_slice(panel_path)
        print(f"panel: {len(panel):,} rows loaded from {panel_path}")
    else:
        from reality_engine.research.factor_weights import build_panel_parquet
        meta = build_panel_parquet(snapshot, args.start, args.end, panel_path)
        panel = _load_panel_slice(panel_path)
        print(f"panel: {meta['rows']:,} rows x {meta['companies']:,} companies, "
              f"{meta['rebalances']} rebalances {meta['first_date']}..{meta['last_date']} "
              f"({time.time() - t0:.0f}s) -> {panel_path}")

    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["date"].dt.year >= STAT_YEAR].reset_index(drop=True)
    dates = pd.DatetimeIndex(panel["date"].drop_duplicates().sort_values())
    print(f"statistics: {len(panel):,} company-months, {panel['entity_id'].nunique():,} companies, "
          f"{len(dates)} month-ends {dates.min().date()}..{dates.max().date()}")

    con = connect(snapshot)
    try:
        calendar = con.execute(
            "SELECT DISTINCT date FROM px_daily WHERE exch = 'NSE' ORDER BY date"
        ).df()["date"]
    finally:
        con.close()

    from reality_engine.research.factor_rewards import reproduce_t118
    reproduction = reproduce_t118(panel)
    print("\nT-118 reproduction (pooled mean IC, 2021+):")
    print(reproduction.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    if not reproduction["ok"].all():
        print("\nSTOP: the rebuilt panel does not reproduce T-118; not continuing.")
        return 2
    reproduction.to_csv(out / "t118_reproduction.csv", index=False, float_format="%.6g")

    mapping, sector_report = sector_map(panel)
    panel["sector_group"] = panel["sector"].map(normalise_sector).map(mapping)
    panel.drop(columns=["sector"], inplace=True)
    if args.sector_groups:
        wanted = [s.strip() for s in args.sector_groups.split(",") if s.strip()]
        panel = panel[panel["sector_group"].isin(wanted)].reset_index(drop=True)
        sector_report = sector_report[sector_report["group"].isin(wanted)].reset_index(drop=True)
    groups = group_names(panel)
    print(f"\nsector groups ({len(groups)}): {', '.join(groups)}")
    sector_report.to_csv(out / "sector_groups.csv", index=False)

    if args.project:
        # Time one sector's heavy loops, then project the full panel run.
        heavy = ["interactions", "stepwise"]
        probe_group = groups[0]
        sub = panel[panel["sector_group"] == probe_group].reset_index(drop=True)
        t_int = time.time()
        _ = _interaction_pass(sub, "12m", [f for f in FACTORS if f in panel.columns])
        int_one = time.time() - t_int
        t_step = time.time()
        _mdf, _sdf = sparse_walk_forward(sub, pd.DataFrame(columns=["horizon", "split", "group",
                                                                    "factor", "window", "date",
                                                                    "rated", "rewarded", "sign",
                                                                    "mean_ic", "nw_t", "months",
                                                                    "sign_share"]),
                                         calendar, "12m")
        step_one = time.time() - t_step
        projection = pd.DataFrame([{
            "sector": probe_group, "interaction_seconds_12m": int_one,
            "stepwise_seconds_12m": step_one,
            "projected_minutes_all": (int_one * 3 * len(groups) + step_one * 3 * len(groups)
                                      + 60) / 60.0,
        }])
        projection.to_csv(out / "projection.csv", index=False)
        print("\nprojection:")
        print(projection.to_string(index=False, float_format=lambda v: f"{v:.1f}"))
        print(f"observed projection includes a 60 s allowance for the panel/corr/company tables; "
              f"completed in {time.time() - t0:.0f}s")
        return 0

    # ---- step 1-2: sector rewarded set, correlations, redundancy -------------- #
    factors = [f for f in FACTORS if f in panel.columns]
    ic_table = _sector_ic_table(panel, dates, calendar, factors)
    rewarded = build_rewarded(ic_table, dates, windows=(MAIN_WINDOW,))
    mode = mode_table(rewarded)
    tested = mode[mode["window"] == MAIN_WINDOW]
    rated = tested[tested["rated_months"] >= MIN_KNOWN_MONTHS]
    claims = bh_table(mode, m_total=len(rated))
    print(f"\nIC table: {len(ic_table):,} ICs; rewarded: {len(rewarded):,} rows ({time.time() - t0:.0f}s)")
    sector_mode = mode[(mode["split"] == "sector") & (mode["window"] == MAIN_WINDOW)]
    sector_mode = sector_mode.merge(
        claims[["horizon", "group", "factor", "bh_survive"]],
        on=["horizon", "group", "factor"], how="left",
    )
    sector_mode.to_csv(out / "sector_mode.csv", index=False, float_format="%.6g")
    claims.to_csv(out / "sector_claims.csv", index=False, float_format="%.6g")
    print(f"stable-70 sector cells: {int(sector_mode['stable_70'].sum())}, "
          f"BH survivors: {int(sector_mode['bh_survive'].fillna(False).sum())}")

    exposure = exposure_corr(panel)
    ic_corr_tables = pd.concat([ic_corr(ic_table, h) for h in HORIZONS], ignore_index=True)
    exposure.to_csv(out / "corr_exposure.csv", index=False, float_format="%.6g")
    ic_corr_tables.to_csv(out / "corr_ic.csv", index=False, float_format="%.6g")
    exposure_pairs = pair_relations(exposure)
    ic_pairs = pair_relations(ic_corr_tables)
    exposure_pairs.to_csv(out / "corr_exposure_pairs.csv", index=False, float_format="%.6g")
    ic_pairs.to_csv(out / "corr_ic_pairs.csv", index=False, float_format="%.6g")
    print(f"correlations: {int((exposure_pairs['relation'] != 'none').sum())} exposure pairs and "
          f"{int((ic_pairs['relation'] != 'none').sum())} IC pairs at |rho| >= {CORR_MOVE}")

    univariate = pd.concat([univariate_sector(ic_table, h) for h in HORIZONS], ignore_index=True)
    univariate.to_csv(out / "univariate_sector.csv", index=False, float_format="%.6g")
    coverage = (panel.groupby("sector_group", observed=True)[factors]
                .apply(lambda g: g.notna().mean()).stack().rename("coverage").reset_index())
    coverage.columns = ["group", "factor", "coverage"]
    coverage.to_csv(out / "factor_coverage_sector.csv", index=False, float_format="%.6g")
    model = model_representatives(exposure, univariate, "12m", coverage=coverage)
    fm_frames = [fama_macbeth_sector(panel, h, model) for h in HORIZONS]
    fm = pd.concat(fm_frames, ignore_index=True) if any(len(f) for f in fm_frames) else pd.DataFrame()
    fm.to_csv(out / "fama_macbeth_sector.csv", index=False, float_format="%.6g")
    redundancy = redundancy_table(univariate, fm, model, exposure)
    redundancy.to_csv(out / "redundancy.csv", index=False, float_format="%.6g")
    print(f"redundancy: {int(redundancy['redundant'].sum())} rewarded factors with joint |t| < {REDUNDANT_T}")
    del ic_table, exposure, ic_corr_tables, exposure_pairs, ic_pairs, univariate, coverage, fm_frames, fm, redundancy
    gc.collect()

    # ---- step 2: per-company shrunk estimates (as of the last month-end) ------ #
    as_of = pd.Timestamp(dates[-1])
    own = pd.concat([company_estimates(panel, calendar, h, as_of) for h in HORIZONS], ignore_index=True)
    if not own.empty:
        own = own.merge(
            panel.dropna(subset=["symbol"]).groupby("entity_id", observed=True)["symbol"].last().rename("symbol"),
            on="entity_id", how="left",
        )
    own.to_csv(out / "company_own_ic.csv", index=False, float_format="%.6g")
    shrunk = shrink_estimates(own)
    shrunk.to_csv(out / "company_shrunk.csv", index=False, float_format="%.6g")
    gaps = company_gaps(shrunk)
    gaps.to_csv(out / "company_gaps.csv", index=False, float_format="%.6g")
    print(f"companies: {own['entity_id'].nunique() if not own.empty else 0} with a >= {COMPANY_MIN_MONTHS}-month series; "
          f"{len(gaps)} reportable gaps (top {min(200, len(gaps))} in company_gaps.csv)")
    del own, shrunk, gaps
    gc.collect()

    # ---- step 3: interactions with the permutation gate ----------------------- #
    observed, null = interaction_study(panel, list(HORIZONS), runs=runs)
    observed.to_csv(out / "interactions.csv", index=False, float_format="%.6g")
    if null is not None:
        null.to_csv(out / "interactions_null.csv", index=False, float_format="%.6g")
    claims_int = interaction_claims(observed, null)
    claims_int.to_csv(out / "interaction_claims.csv", index=False, float_format="%.6g")
    print(f"interactions: {len(observed):,} pair x sector x horizon cells, "
          f"{int(claims_int['claimed'].sum()) if 'claimed' in claims_int else 0} claimed "
          f"({time.time() - t0:.0f}s)")
    observed_claims = int(claims_int["claimed"].sum()) if "claimed" in claims_int else 0
    del observed, claims_int
    gc.collect()

    # ---- step 4: sparse combinations, walk forward ---------------------------- #
    mdf, summary = sparse_walk_forward(panel, rewarded, calendar, "12m")
    mdf.to_csv(out / "sparse_monthly.csv", index=False, float_format="%.6g")
    summary.to_csv(out / "sparse_summary.csv", index=False, float_format="%.6g")
    observed_beats_both = int(summary["beats_both"].sum()) if not summary.empty else 0
    del mdf, summary
    for horizon in ("6m", "24m"):
        _m, s = sparse_walk_forward(panel, rewarded, calendar, horizon)
        if not s.empty:
            s.to_csv(out / f"sparse_summary_{horizon}.csv", index=False, float_format="%.6g")
        del _m, s
    gc.collect()

    # ---- placebo counts for every claim type ---------------------------------- #
    placebo_rows = []
    if runs:
        t_placebo = time.time()
        from reality_engine.research.factor_rewards import permute_panel
        claimed_obs = int(sector_mode["stable_70"].sum())
        claimed_null = []
        slim_rew = panel[["date", "sector_group", "excess_126", "excess_252", "excess_504"] + factors]
        for run in range(runs):
            shuffled = permute_panel(slim_rew, PLACEBO_SEED + run, factors=factors)
            ic_p = _sector_ic_table(shuffled, dates, calendar, factors)
            rew_p = build_rewarded(ic_p, dates, windows=(MAIN_WINDOW,))
            mode_p = mode_table(rew_p)
            claimed_null.append(int(mode_p[(mode_p["split"] == "sector")
                                           & (mode_p["window"] == MAIN_WINDOW)]["stable_70"].sum()))
            del shuffled, ic_p, rew_p, mode_p
            gc.collect()
        del slim_rew
        placebo_rows.append({"claim": "sector stable-70 cells", "observed": claimed_obs,
                             "placebo_mean": float(np.mean(claimed_null)),
                             "placebo_max": int(np.max(claimed_null)), "runs": runs})
        print(f"sector reward placebo: observed {claimed_obs}, null mean {np.mean(claimed_null):.2f} "
              f"max {int(np.max(claimed_null))} ({time.time() - t_placebo:.0f}s)")
        # interaction claims under the same permutation design (the null table)
        int_null_claims = interaction_placebo_counts(null)
        del null
        gc.collect()
        if not int_null_claims:
            int_null_claims = [0]
        placebo_rows.append({"claim": "interaction claims", "observed": observed_claims,
                             "placebo_mean": float(np.mean(int_null_claims)),
                             "placebo_max": int(np.max(int_null_claims)), "runs": runs})
        print(f"interaction placebo: observed {observed_claims}, "
              f"null mean {np.mean(int_null_claims):.2f} max {int(np.max(int_null_claims))}")
        # combination claims under permuted exposures
        combo_null = []
        slim_combo = panel[["date", "sector_group", "excess_252"] + factors + [f + "_z" for f in factors]]
        for run in range(runs):
            permuted = permute_within_groups(slim_combo, "sector_group", PLACEBO_SEED + run, factors=factors)
            _m, s = sparse_walk_forward(permuted, rewarded, calendar, "12m")
            combo_null.append(int(s["beats_both"].sum()) if not s.empty else 0)
            del permuted, _m, s
            gc.collect()
        del slim_combo
        placebo_rows.append({"claim": "sparse beats both baselines (12m)",
                             "observed": observed_beats_both,
                             "placebo_mean": float(np.mean(combo_null)),
                             "placebo_max": int(np.max(combo_null)), "runs": runs})
        print(f"combination placebo: observed {placebo_rows[-1]['observed']}, "
              f"null mean {np.mean(combo_null):.2f} max {int(np.max(combo_null))}")
        pd.DataFrame(placebo_rows).to_csv(out / "placebo.csv", index=False, float_format="%.6g")
    else:
        del null
        gc.collect()

    # ---- step 5: KPI arm ------------------------------------------------------ #
    if not args.skip_kpi:
        raw, kpi_cov = kpi_raw(Path(args.kpi_root))
        kpi_cov.to_csv(out / "kpi_coverage_stores.csv", index=False)
        kpi = kpi_factor_panel(raw)
        kpi.to_csv(out / "kpi_panel.csv", index=False, float_format="%.6g")
        kpi_ics, kpi_counts = kpi_ic(kpi, panel, ["6m", "12m"])
        kpi_ics.to_csv(out / "kpi_ic.csv", index=False, float_format="%.6g")
        kpi_counts.to_csv(out / "kpi_coverage.csv", index=False)
        kpi_pairs = kpi_interactions(kpi, panel, "12m")
        kpi_pairs.to_csv(out / "kpi_interactions.csv", index=False, float_format="%.6g")
        print(f"KPI arm: {len(raw):,} rows from {int(kpi_cov['exists'].sum())} stores, "
              f"{kpi['symbol'].nunique() if not kpi.empty else 0} companies; "
              f"{len(kpi_ics)} IC cells, {len(kpi_pairs)} interaction pairs (method pilot)")

    print(f"\nwrote {out}/*.csv ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
