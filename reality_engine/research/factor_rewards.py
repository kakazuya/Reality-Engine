"""T-207: point-in-time factor rewards (round 1).

For every month-end, which factors were being rewarded over 6 / 12 / 24 months,
using only factor ICs whose forward return had already been realised by that
date. Reports the rewarded set, the share of months each factor is rewarded, the
dates the set shifts, per sector group and market regime, and a walk-forward
test of dynamic against static factor choice.

Reads the T-118 panel builder from :mod:`reality_engine.research.factor_weights`
(unchanged) and the dated DuckDB snapshot read-only. See
`docs/research/T-207_factor_rewards.md`.

    python -m reality_engine.research.factor_rewards --out .tmp/t207
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from reality_engine.research.factor_weights import (
    BENCHMARK,
    FACTORS,
    HORIZONS,
    NW_LAGS,
    build_panel,
    connect,
    default_snapshot,
    monthly_ic,
    newey_west_tstat,
    quintile_spread,
    spearman_ic,
)

STAT_YEAR = 2021          # T-118: growth factors cannot exist before 2021
MAIN_WINDOW = 24          # months of realised ICs in the main rewarded set
WINDOWS = (24, 12, 36)    # main plus the two sensitivities
MIN_KNOWN_MONTHS = 12     # fewer known IC months than this: not rated
T_MIN = 2.0               # |Newey-West t| of the mean IC
SIGN_SHARE_MIN = 0.60     # share of IC months matching the mean's sign
STABLE_SHARE = 0.70       # "rewarded in at least 70% of months"
BH_Q = 0.10               # Benjamini-Hochberg false-discovery rate
MIN_IC_NAMES = 20         # cross-section needed for a rank IC
SECTOR_MIN_NAMES = 30     # a sector group needs this many names a month
MIN_REGIME_MONTHS = 12    # a regime cell thinner than this is reported, not pooled
SIZE_TERCILES = ("small", "mid", "large")

# Fixed a-priori signs for the EQUAL baseline, from finance convention alone
# (never from the results). +1: high value should earn a higher return.
#   growth / profitability up, margin change up, leverage cost down;
#   cheap (earnings and sales yield up, P/S and P/E down, premium to sector down);
#   multiple momentum up; ownership up; momentum up; short-term reversal up
#   (reversal_1m is positive after a fall, so its convention sign is +);
#   low volatility and small size up; delivery up.
# sector P/S and P/E changes are multiple momentum, so +.
EQUAL_SIGN = {
    "ttm_rev_yoy": 1, "ttm_pat_yoy": 1, "q_pat_yoy": 1, "pat_accel": 1,
    "op_margin": 1, "op_margin_chg": 1, "fin_cost_to_rev": -1,
    "earnings_yield": 1, "sales_yield": 1, "ps_ratio": -1, "pe_ratio": -1,
    "ps_chg_3m": 1, "ps_chg_6m": 1, "ps_chg_12m": 1,
    "pe_chg_3m": 1, "pe_chg_6m": 1, "pe_chg_12m": 1,
    "rerating_share_12m": 1, "sales_share_12m": 1,
    "sector_ps_chg_12m": 1, "sector_ps_chg_36m": 1,
    "sector_pe_chg_12m": 1, "sector_pe_chg_36m": 1, "ps_vs_sector": -1,
    "op_margin_pctile": -1, "pat_pctile": -1, "peak_growth_trap": -1,
    "promoter_chg_1q": 1, "promoter_chg_4q": 1, "insider_net_to_mcap": 1,
    "mom_12_1": 1, "reversal_1m": 1, "vol_12m": -1, "size": -1, "delivery_3m": 1,
}

# T-118's block table (doc section 1), used by the round-2 block decomposition and
# the block-balanced scores. Every factor belongs to exactly one block.
BLOCKS = {
    "growth": ["ttm_rev_yoy", "ttm_pat_yoy", "q_pat_yoy", "pat_accel"],
    "quality": ["op_margin", "op_margin_chg", "fin_cost_to_rev"],
    "valuation": ["earnings_yield", "sales_yield", "ps_ratio", "pe_ratio"],
    "re-rating": ["ps_chg_3m", "ps_chg_6m", "ps_chg_12m", "pe_chg_3m", "pe_chg_6m",
                  "pe_chg_12m", "rerating_share_12m", "sales_share_12m"],
    "sector": ["sector_ps_chg_12m", "sector_ps_chg_36m", "sector_pe_chg_12m",
               "sector_pe_chg_36m", "ps_vs_sector"],
    "cyclical peak": ["op_margin_pctile", "pat_pctile", "peak_growth_trap"],
    "ownership": ["promoter_chg_1q", "promoter_chg_4q", "insider_net_to_mcap"],
    "price": ["mom_12_1", "reversal_1m", "vol_12m", "size", "delivery_3m"],
}
assert sorted(f for fs in BLOCKS.values() for f in fs) == sorted(FACTORS), "BLOCKS must cover FACTORS"

PLACEBO_SEED = 20261113
PLACEBO_RUNS = 20

# T-118 pooled mean ICs this study must reproduce before it trusts its own panel.
T118_IC = {
    ("earnings_yield", "6m"): 0.056,
    ("earnings_yield", "12m"): 0.071,
    ("earnings_yield", "24m"): 0.098,
    ("op_margin_pctile", "6m"): 0.052,
    ("promoter_chg_4q", "12m"): 0.050,
}


# --------------------------------------------------------------------------- #
# Dates (pandas 3 keeps datetimes in microseconds: always name the unit)
# --------------------------------------------------------------------------- #
def to_ns(values) -> np.ndarray:
    """Date-like values -> numpy datetime64[ns], never through a raw .view()."""
    return pd.to_datetime(pd.Series(values), errors="coerce").to_numpy(dtype="datetime64[ns]")


def np_date(value) -> np.datetime64:
    """One date -> datetime64[ns] (month-ends have no time of day)."""
    return np.datetime64(str(pd.Timestamp(value).date()), "ns")


def known_dates_for(dates: pd.Series, calendar, horizon_sessions: int) -> pd.Series:
    """The session on which each rebalance's forward window ends (NaT past the end).

    ``calendar`` is the ordered NSE session list the T-118 panel was built on, so
    ``i + horizon_sessions`` is exactly the session its forward return uses.
    """
    cal = pd.DatetimeIndex(pd.to_datetime(pd.Series(calendar)).sort_values().unique())
    pos = cal.get_indexer(pd.DatetimeIndex(pd.to_datetime(dates)))
    out = np.full(len(pos), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    ok = (pos >= 0) & (pos + horizon_sessions < len(cal))
    out[ok] = cal.to_numpy(dtype="datetime64[ns]")[pos[ok] + horizon_sessions]
    return pd.Series(pd.to_datetime(out), index=dates.index)


# --------------------------------------------------------------------------- #
# Realised IC with the date it became known
# --------------------------------------------------------------------------- #
def realised_ic(panel: pd.DataFrame, factor: str, horizon: str, calendar, target: str | None = None) -> pd.DataFrame:
    """Rank IC per rebalance date, tagged with the session that realised it."""
    target = target or f"excess_{HORIZONS[horizon]}"
    ic = monthly_ic(panel, factor, target)
    if ic.empty:
        return pd.DataFrame(columns=["date", "ic", "known_date"])
    out = ic.rename("ic").reset_index()
    out.columns = ["date", "ic"]
    out["known_date"] = known_dates_for(out["date"], calendar, HORIZONS[horizon])
    return out.dropna(subset=["ic", "known_date"]).reset_index(drop=True)


def monthly_ic_grouped(
    frame: pd.DataFrame, factor: str, target: str, group_col: str, min_n: int = MIN_IC_NAMES
) -> pd.DataFrame:
    """Rank IC per (rebalance date, group); groups thinner than ``min_n`` are skipped."""
    d = frame[["date", group_col, factor, target]].dropna()
    rows = []
    for (date, group), g in d.groupby(["date", group_col], observed=True, sort=True):
        ic = spearman_ic(g[factor], g[target], min_n)
        if np.isfinite(ic):
            rows.append((date, group, ic))
    return pd.DataFrame(rows, columns=["date", "group", "ic"])


def build_ic_table(
    panel: pd.DataFrame,
    calendar,
    dates: pd.DatetimeIndex,
    regime: pd.DataFrame,
    factors: list[str] | None = None,
) -> pd.DataFrame:
    """Realised ICs for every split: all companies, sector group, size tercile, regime cell."""
    factors = factors or list(FACTORS)
    frames = []
    for horizon, sessions in HORIZONS.items():
        target = f"excess_{sessions}"
        for factor in factors:
            base = realised_ic(panel, factor, horizon, calendar, target)
            if base.empty:
                continue
            frames.append(base.assign(horizon=horizon, split="all", group="all", factor=factor))
            reg = base.merge(regime[["date", "regime"]].dropna(), on="date", how="inner")
            if not reg.empty:
                frames.append(reg.assign(horizon=horizon, split="regime", group=reg["regime"], factor=factor))
            for split, group_col in (("sector", "sector_group"), ("size", "size_bucket")):
                grouped = monthly_ic_grouped(
                    panel, factor, target, group_col,
                    SECTOR_MIN_NAMES if split == "sector" else MIN_IC_NAMES,
                )
                if grouped.empty:
                    continue
                grouped = grouped.merge(base[["date", "known_date"]], on="date", how="inner")
                frames.append(grouped.assign(horizon=horizon, split=split, factor=factor))
    out = pd.concat(frames, ignore_index=True)
    return out[["horizon", "split", "group", "factor", "date", "known_date", "ic"]]


# --------------------------------------------------------------------------- #
# Rewarded set at every month-end
# --------------------------------------------------------------------------- #
def rewarded_at(
    ic: pd.DataFrame,
    dates: pd.DatetimeIndex,
    window_months: int = MAIN_WINDOW,
    lags: int = 5,
    min_months: int = MIN_KNOWN_MONTHS,
    t_min: float = T_MIN,
    sign_share: float = SIGN_SHARE_MIN,
) -> pd.DataFrame:
    """State of one factor at every evaluation date.

    Uses only ICs whose ``known_date`` is in (t - window_months, t]. A factor is
    rewarded when |Newey-West t| >= t_min and the sign of the mean IC matches at
    least ``sign_share`` of the IC months. Fewer than ``min_months`` known months:
    rated=False, rewarded=False.
    """
    d = ic.dropna(subset=["known_date", "ic"]).sort_values("known_date")
    kd = to_ns(d["known_date"])
    vals = d["ic"].to_numpy(dtype=float)
    rows = []
    for t in pd.DatetimeIndex(dates):
        cut = np_date(pd.Timestamp(t) - pd.DateOffset(months=window_months))
        end = np_date(t)
        lo = int(np.searchsorted(kd, cut, side="right"))
        hi = int(np.searchsorted(kd, end, side="right"))
        w = vals[lo:hi]
        n = len(w)
        if n < min_months:
            rows.append((t, False, False, 0, np.nan, np.nan, n, np.nan))
            continue
        mean = float(w.mean())
        tstat = newey_west_tstat(w, lags)
        sign = 1 if mean > 0 else (-1 if mean < 0 else 0)
        share = float((np.sign(w) == sign).mean()) if sign else 0.0
        rewarded = bool(sign != 0 and np.isfinite(tstat) and abs(tstat) >= t_min and share >= sign_share)
        rows.append((t, True, rewarded, sign if rewarded else 0, mean, tstat, n, share))
    return pd.DataFrame(
        rows,
        columns=["date", "rated", "rewarded", "sign", "mean_ic", "nw_t", "months", "sign_share"],
    )


def build_rewarded(ic_table: pd.DataFrame, dates: pd.DatetimeIndex, windows=WINDOWS) -> pd.DataFrame:
    """Rewarded state per (split, group, factor, horizon, window, date)."""
    frames = []
    keys = ["horizon", "split", "group", "factor"]
    for (horizon, split, group, factor), g in ic_table.groupby(keys, observed=True, sort=False):
        for window in windows:
            r = rewarded_at(g, dates, window, NW_LAGS[horizon])
            r["horizon"] = horizon
            r["split"] = split
            r["group"] = group
            r["factor"] = factor
            r["window"] = window
            frames.append(r)
    out = pd.concat(frames, ignore_index=True)
    return out[
        ["horizon", "split", "group", "factor", "window",
         "date", "rated", "rewarded", "sign", "mean_ic", "nw_t", "months", "sign_share"]
    ]


# --------------------------------------------------------------------------- #
# Mode and shifts
# --------------------------------------------------------------------------- #
def mode_table(rewarded: pd.DataFrame) -> pd.DataFrame:
    """Per cell: share of rated months rewarded, split by sign, and the 70% flag."""
    rows = []
    keys = ["horizon", "split", "group", "factor", "window"]
    for (horizon, split, group, factor, window), g in rewarded.groupby(keys, observed=True, sort=False):
        rated = g[g["rated"]]
        n = int(len(rated))
        pos = int((rated["sign"] > 0).sum())
        neg = int((rated["sign"] < 0).sum())
        best = max(pos, neg) / n if n else np.nan
        rows.append(
            {
                "horizon": horizon,
                "split": split,
                "group": group,
                "factor": factor,
                "window": window,
                "rated_months": n,
                "rewarded_pos": pos,
                "rewarded_neg": neg,
                "share_rewarded": (pos + neg) / n if n else np.nan,
                "share_pos": pos / n if n else np.nan,
                "share_neg": neg / n if n else np.nan,
                "dominant_sign": (1 if pos > neg else (-1 if neg > pos else 0)),
                "stable_70": bool(n >= MIN_KNOWN_MONTHS and np.isfinite(best) and best >= STABLE_SHARE),
                "mean_ic": float(rated["mean_ic"].mean()) if n else np.nan,
                "median_abs_t": float(rated["nw_t"].abs().median()) if n else np.nan,
                "mean_months_used": float(rated["months"].mean()) if n else np.nan,
            }
        )
    return pd.DataFrame(rows)


def shifts_table(rewarded: pd.DataFrame) -> pd.DataFrame:
    """Every date a factor enters or leaves the rewarded set, or flips sign."""
    rows = []
    keys = ["horizon", "split", "group", "factor", "window"]
    for (horizon, split, group, factor, window), g in rewarded.groupby(keys, observed=True, sort=False):
        g = g.sort_values("date")
        state = pd.Series(np.where(g["rated"], g["sign"], np.nan), index=g.index, dtype=float)
        prev = state.shift(1)
        changed = state.notna() & prev.notna() & (state != prev)
        for idx in g.index[changed]:
            was, now = int(prev[idx]), int(state[idx])
            change = "enter" if was == 0 else ("leave" if now == 0 else "flip")
            rows.append(
                {
                    "horizon": horizon,
                    "split": split,
                    "group": group,
                    "factor": factor,
                    "window": window,
                    "date": g.loc[idx, "date"],
                    "change": change,
                    "from_sign": was,
                    "to_sign": now,
                }
            )
    out = pd.DataFrame(rows)
    return out.sort_values(["horizon", "split", "group", "factor", "window", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Splits known at the month-end
# --------------------------------------------------------------------------- #
def normalise_sector(value) -> str:
    """Case and whitespace only: company_industry carries TEXTILES beside Textiles."""
    if pd.isna(value):
        return "Unclassified"
    return " ".join(str(value).strip().title().split())


def sector_map(
    panel: pd.DataFrame, min_names: int = SECTOR_MIN_NAMES, min_months: int = MIN_KNOWN_MONTHS
) -> tuple[dict[str, str], pd.DataFrame]:
    """Fold thin company_industry sectors into one merged group.

    A company-month with no sector is left out of the sector split (not invented
    as a sector). A sector stays its own group when it has at least ``min_names``
    names in at least ``min_months`` months - the minimum history a rewarded
    window needs; every other sector is folded into "Other (merged)". Sector ICs
    use only months with >= min_names names, so a reported group is never rated
    on a thinner month. The returned table reports the merge.
    """
    p = panel[["date", "sector"]].copy()
    p["sector"] = p["sector"].map(normalise_sector)
    p = p[p["sector"] != "Unclassified"]
    monthly = p.groupby(["date", "sector"], observed=True).size()
    qualifying = monthly[monthly >= min_names].groupby("sector").size()
    sectors = sorted(p["sector"].unique())
    keep = [s for s in sectors if int(qualifying.get(s, 0)) >= min_months]
    thin = [s for s in sectors if s not in keep]
    mapping = {s: s for s in keep}
    mapping.update({s: "Other (merged)" for s in thin})
    p["group"] = p["sector"].map(mapping)
    grouped_min = p.groupby(["date", "group"], observed=True).size().groupby("group").min()
    if "Other (merged)" in grouped_min.index and grouped_min["Other (merged)"] < min_names:
        # Nothing left to merge it with; fold it into the largest kept group and say so.
        largest = max(keep, key=lambda s: int(qualifying.get(s, 0)))
        mapping = {s: (largest if v == "Other (merged)" else v) for s, v in mapping.items()}
        p["group"] = p["sector"].map(mapping)
        grouped_min = p.groupby(["date", "group"], observed=True).size().groupby("group").min()
    report = pd.DataFrame(
        {
            "sector": sectors,
            "months_at_least_30": [int(qualifying.get(s, 0)) for s in sectors],
            "min_names_month": [int(monthly.groupby("sector").min().get(s, 0)) for s in sectors],
            "group": [mapping[s] for s in sectors],
        }
    )
    report.attrs["group_min"] = grouped_min.to_dict()
    report.attrs["thin"] = thin
    return mapping, report


def add_size_buckets(panel: pd.DataFrame) -> pd.DataFrame:
    """Size terciles within each month-end (never pooled across dates)."""
    labels = list(SIZE_TERCILES)

    def bucket(values: pd.Series) -> pd.Series:
        if values.notna().sum() < 3 * MIN_IC_NAMES:
            return pd.Series(np.nan, index=values.index)
        return pd.qcut(values, 3, labels=labels).astype(object)

    out = panel.copy()
    out["size_bucket"] = out.groupby("date", observed=True)["size"].transform(bucket)
    return out


def regime_labels(dates: pd.DatetimeIndex, tri: pd.DataFrame) -> pd.DataFrame:
    """Nifty 500 TRI regime known at each month-end.

    above/below = TRI vs its 200-session mean; up/down = trailing 12-month TRI
    return. Both use only sessions up to that date. Rows past the TRI series get
    no label (never forward-filled).
    """
    d = tri.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date")
    series = d.set_index("date")["tri"]
    sma = series.rolling(200, min_periods=200).mean()
    ret = series / series.shift(252) - 1.0
    out = pd.DataFrame({"date": pd.DatetimeIndex(dates)})
    out["tri"] = series.reindex(out["date"]).to_numpy()
    out["sma200"] = sma.reindex(out["date"]).to_numpy()
    out["ret_12m"] = ret.reindex(out["date"]).to_numpy()
    above = out["tri"] > out["sma200"]
    up = out["ret_12m"] > 0
    cell = np.select(
        [above & up, above & ~up, ~above & up, ~above & ~up],
        ["above_up", "above_down", "below_up", "below_down"],
        default=None,
    )
    out["regime"] = pd.Series(cell, index=out.index, dtype=object).where(
        out["tri"].notna() & out["sma200"].notna() & out["ret_12m"].notna()
    )
    return out


# --------------------------------------------------------------------------- #
# Walk-forward: dynamic vs static vs fixed-convention choice
# --------------------------------------------------------------------------- #
def signed_score(frame: pd.DataFrame, signed: dict[str, int]) -> pd.Series:
    """Sum of sign x within-date z over the available factors (NaN if none)."""
    if not signed:
        return pd.Series(np.nan, index=frame.index)
    parts = {f: s * pd.to_numeric(frame[f + "_z"], errors="coerce") for f, s in signed.items()}
    return pd.DataFrame(parts).sum(axis=1, min_count=1)


def block_scores(
    frame: pd.DataFrame, signed: dict[str, int], blocks: dict[str, list[str]] | None = None
) -> pd.DataFrame:
    """Per block, the mean of sign x z over that block's factors in the set."""
    blocks = blocks or BLOCKS
    out = {}
    for block, factors in blocks.items():
        present = [f for f in factors if f in signed]
        if not present:
            continue
        out[block] = pd.DataFrame(
            {f: signed[f] * pd.to_numeric(frame[f + "_z"], errors="coerce") for f in present}
        ).mean(axis=1)
    return pd.DataFrame(out, index=frame.index)


def block_score(
    frame: pd.DataFrame, signed: dict[str, int], blocks: dict[str, list[str]] | None = None
) -> pd.Series:
    """Sum of the block means: every block contributes equally, not by factor count."""
    bs = block_scores(frame, signed, blocks)
    if bs.shape[1] == 0:
        return pd.Series(np.nan, index=frame.index)
    return bs.sum(axis=1, min_count=1)


def reward_sets(rewarded_all: pd.DataFrame) -> dict[pd.Timestamp, dict[str, int]]:
    """date -> {factor: sign} from the rewarded rows of the all-companies split."""
    sets: dict[pd.Timestamp, dict[str, int]] = {}
    for date, g in rewarded_all.groupby("date", observed=True, sort=True):
        sets[date] = {f: int(s) for f, s in zip(g.loc[g["rewarded"], "factor"], g.loc[g["rewarded"], "sign"])}
    return sets


def all_states(rewarded: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """The all-companies, main-window state rows for one horizon."""
    return rewarded[
        (rewarded["horizon"] == horizon)
        & (rewarded["split"] == "all")
        & (rewarded["group"] == "all")
        & (rewarded["window"] == MAIN_WINDOW)
    ]


def rewarded_sets(rewarded: pd.DataFrame, horizon: str) -> dict[pd.Timestamp, dict[str, int]]:
    """date -> {factor: sign} for one horizon's all-companies rewarded set."""
    return reward_sets(all_states(rewarded, horizon))


def persistent_sets(rewarded: pd.DataFrame, horizon: str) -> dict[pd.Timestamp, dict[str, int]]:
    """Expanding mode: a sign in >= 70% of the factor's rated states up to t.

    Uses only states dated on or before t and needs at least 12 rated months; this
    is the "mode" selector, not the trailing-window set.
    """
    r = all_states(rewarded, horizon)
    if r.empty:
        return {}
    sign = r.pivot(index="date", columns="factor", values="sign")
    rated = r.pivot(index="date", columns="factor", values="rated").astype(float)
    pos = (sign > 0).astype(float).where(rated > 0).cumsum()
    neg = (sign < 0).astype(float).where(rated > 0).cumsum()
    n = rated.fillna(0.0).cumsum()
    out: dict[pd.Timestamp, dict[str, int]] = {}
    for date in sign.index:
        chosen = {}
        for factor in sign.columns:
            k = float(n.loc[date, factor])
            if k < MIN_KNOWN_MONTHS:
                continue
            p, q = float(pos.loc[date, factor]), float(neg.loc[date, factor])
            if max(p, q) / k >= STABLE_SHARE:
                chosen[factor] = 1 if p >= q else -1
        out[pd.Timestamp(date)] = chosen
    return out


def months_between(start, end) -> int:
    """Whole calendar months from start to end (negative when end is earlier)."""
    a, b = pd.Timestamp(start), pd.Timestamp(end)
    return int((b.year - a.year) * 12 + (b.month - a.month))


def staleness_table(ic_table: pd.DataFrame, rewarded: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """Newest and oldest IC start date in the rewarded window, per test month-end."""
    r = all_states(rewarded, horizon)
    rated_dates = sorted(pd.to_datetime(r.loc[r["rated"], "date"]).unique())
    first_rated = pd.Timestamp(rated_dates[0]) if rated_dates else None
    ic = ic_table[
        (ic_table["horizon"] == horizon)
        & (ic_table["split"] == "all")
        & (ic_table["group"] == "all")
    ].copy()
    ic["date"] = pd.to_datetime(ic["date"])
    ic["known_date"] = pd.to_datetime(ic["known_date"])
    usable = set(ic["date"])
    rows = []
    for value in sorted(set(pd.to_datetime(r["date"])) & usable):
        t = pd.Timestamp(value)
        if first_rated is None or t <= first_rated:
            continue
        cut = t - pd.DateOffset(months=MAIN_WINDOW)
        window = ic[(ic["known_date"] > cut) & (ic["known_date"] <= t)]
        if window.empty:
            continue
        newest = window["date"].max()
        oldest = window["date"].min()
        rows.append(
            {
                "horizon": horizon,
                "date": t,
                "newest_start": newest,
                "oldest_start": oldest,
                "newest_age_months": months_between(newest, t),
                "oldest_age_months": months_between(oldest, t),
                "ic_months": int(window["date"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def block_decomposition(
    panel: pd.DataFrame,
    rewarded: pd.DataFrame,
    horizon: str,
    blocks: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Per block: realised IC of sign x block-mean z in the DYNAMIC set, per test month."""
    blocks = blocks or BLOCKS
    target = f"excess_{HORIZONS[horizon]}"
    r = all_states(rewarded, horizon)
    sets = reward_sets(r)
    rated_dates = sorted(pd.to_datetime(r.loc[r["rated"], "date"]).unique())
    first_rated = pd.Timestamp(rated_dates[0]) if rated_dates else None
    rows = []
    for date in sorted(t for t in sets if first_rated is not None and t > first_rated):
        sub = panel[panel["date"] == date]
        if sub.empty or sub[target].notna().sum() < MIN_IC_NAMES:
            continue
        signed = sets[date]
        scores = block_scores(sub, signed, blocks)
        for block in scores.columns:
            ic = spearman_ic(scores[block], sub[target].to_numpy(), MIN_IC_NAMES)
            rows.append(
                {
                    "date": date,
                    "block": block,
                    "ic": ic,
                    "factors": sum(1 for f in blocks[block] if f in signed),
                    "names": int(scores[block].notna().sum()),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=["horizon", "block", "months", "mean_ic", "nw_t", "hit_rate",
                     "mean_factors", "mean_names"]
        )
    d = pd.DataFrame(rows)
    out = []
    for block, g in d.groupby("block", sort=False):
        ic = g["ic"].dropna()
        out.append(
            {
                "horizon": horizon,
                "block": block,
                "months": int(len(ic)),
                "mean_ic": float(ic.mean()) if len(ic) else np.nan,
                "nw_t": newey_west_tstat(ic, NW_LAGS[horizon]) if len(ic) >= 3 else np.nan,
                "hit_rate": float((ic > 0).mean()) if len(ic) else np.nan,
                "mean_factors": float(g["factors"].mean()),
                "mean_names": float(g["names"].mean()),
            }
        )
    return pd.DataFrame(out)


def permute_panel(
    panel: pd.DataFrame, seed: int, factors: list[str] | None = None
) -> pd.DataFrame:
    """Shuffle each factor's non-null values across companies within each date.

    The random stream is seeded once per call; the null mask and each date's value
    multiset are preserved, and the target columns are untouched.
    """
    factors = factors or list(FACTORS)
    out = panel.copy()
    groups = list(out.groupby("date", sort=True).groups.values())
    rng = np.random.default_rng(seed)
    for factor in factors:
        col = out[factor].to_numpy(dtype=float, copy=True)
        for labels in groups:
            positions = out.index.get_indexer(labels)
            values = col[positions]
            ok = ~np.isnan(values)
            if ok.sum() > 1:
                shuffled = values[ok].copy()
                rng.shuffle(shuffled)
                values[ok] = shuffled
                col[positions] = values
        out[factor] = col
    return out


def placebo_counts(
    panel: pd.DataFrame,
    calendar,
    dates: pd.DatetimeIndex,
    runs: int = PLACEBO_RUNS,
    seed: int = PLACEBO_SEED,
) -> pd.DataFrame:
    """Cross-sectional permutation placebo: per run, horizon and factor, the stable-70 flag."""
    rows = []
    for run in range(runs):
        shuffled = permute_panel(panel, seed + run)
        for horizon in HORIZONS:
            for factor in FACTORS:
                ic = realised_ic(shuffled, factor, horizon, calendar)
                states = rewarded_at(ic, dates, MAIN_WINDOW, NW_LAGS[horizon])
                rated = states[states["rated"]]
                n = int(len(rated))
                pos = int((rated["sign"] > 0).sum())
                neg = int((rated["sign"] < 0).sum())
                best = max(pos, neg) / n if n else np.nan
                rows.append(
                    {
                        "run": run,
                        "horizon": horizon,
                        "factor": factor,
                        "rated_months": n,
                        "best_share": best,
                        "stable_70": bool(
                            n >= MIN_KNOWN_MONTHS and np.isfinite(best) and best >= STABLE_SHARE
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _metric(values, horizon: str) -> dict:
    v = pd.Series(values, dtype=float).dropna()
    return {
        "months": int(len(v)),
        "mean_ic": float(v.mean()) if len(v) else np.nan,
        "nw_t_ic": newey_west_tstat(v, NW_LAGS[horizon]) if len(v) >= 3 else np.nan,
        "hit_rate_ic": float((v > 0).mean()) if len(v) else np.nan,
    }


def walk_forward(
    panel: pd.DataFrame,
    rewarded: pd.DataFrame,
    horizon: str,
    equal_signs: dict[str, int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Plain, block-balanced, PERSISTENT and cross-horizon scores per test month.

    Scores: DYNAMIC / STATIC / EQUAL (round 1), their _BLOCK versions (mean of
    sign x z inside each T-118 block, then summed across blocks), PERSISTENT (the
    expanding 70% mode) and, at 24m, CROSS_6M / CROSS_12M (the 6m / 12m rewarded
    set applied to the 24m outcome). The summary also carries the requested paired
    differences with their Newey-West t.
    """
    equal_signs = equal_signs or EQUAL_SIGN
    target = f"excess_{HORIZONS[horizon]}"
    dyn = rewarded_sets(rewarded, horizon)
    pers = persistent_sets(rewarded, horizon)
    r = all_states(rewarded, horizon)
    rated_dates = sorted(pd.to_datetime(r.loc[r["rated"], "date"]).unique())
    first_rated = pd.Timestamp(rated_dates[0]) if rated_dates else None
    static = dyn.get(first_rated, {}) if first_rated is not None else {}
    cross: dict[str, dict[pd.Timestamp, dict[str, int]]] = {}
    if horizon == "24m":
        cross["CROSS_6M"] = rewarded_sets(rewarded, "6m")
        cross["CROSS_12M"] = rewarded_sets(rewarded, "12m")

    score_kind = {
        "DYNAMIC": "plain",
        "DYNAMIC_BLOCK": "block",
        "STATIC": "plain",
        "STATIC_BLOCK": "block",
        "EQUAL": "plain",
        "EQUAL_BLOCK": "block",
        "PERSISTENT": "plain",
        "PERSISTENT_BLOCK": "block",
    }
    if horizon == "24m":
        score_kind["CROSS_6M"] = "plain"
        score_kind["CROSS_12M"] = "plain"

    def sets_for(name: str, date) -> dict[str, int]:
        if name in ("DYNAMIC", "DYNAMIC_BLOCK"):
            return dyn.get(date, {})
        if name in ("STATIC", "STATIC_BLOCK"):
            return static
        if name in ("EQUAL", "EQUAL_BLOCK"):
            return equal_signs
        if name in ("PERSISTENT", "PERSISTENT_BLOCK"):
            return pers.get(date, {})
        return cross[name].get(date, {})

    monthly = []
    for date in sorted(t for t in dyn if first_rated is not None and t > first_rated):
        sub = panel[panel["date"] == date]
        if sub.empty or sub[target].notna().sum() < MIN_IC_NAMES:
            continue
        row = {"date": date}
        for name, kind in score_kind.items():
            signed = sets_for(name, date)
            score = block_score(sub, signed) if kind == "block" else signed_score(sub, signed)
            pair = pd.DataFrame({"score": score, "target": sub[target].to_numpy()}).dropna()
            row[f"{name}_ic"] = spearman_ic(pair["score"], pair["target"], MIN_IC_NAMES)
            row[f"{name}_spread"] = quintile_spread(pair, "score", "target")
            row[f"{name}_factors"] = len(signed)
        monthly.append(row)
    mdf = pd.DataFrame(monthly)

    def score_row(name: str, ic: dict, sp: dict, mean_factors: float = np.nan) -> dict:
        return {
            "horizon": horizon,
            "score": name,
            "months": ic["months"],
            "mean_ic": ic["mean_ic"],
            "nw_t_ic": ic["nw_t_ic"],
            "hit_rate_ic": ic["hit_rate_ic"],
            "mean_q5_q1": sp["mean_ic"],
            "nw_t_q5_q1": sp["nw_t_ic"],
            "hit_rate_q5_q1": sp["hit_rate_ic"],
            "mean_factors": mean_factors,
        }

    rows = []
    for name in score_kind:
        if f"{name}_ic" not in mdf:
            continue
        ic = _metric(mdf[f"{name}_ic"], horizon)
        sp = _metric(mdf[f"{name}_spread"], horizon)
        fac = pd.to_numeric(mdf[f"{name}_factors"], errors="coerce")
        mean_fac = float(fac[fac > 0].mean()) if (fac > 0).any() else np.nan
        rows.append(score_row(name, ic, sp, mean_fac))

    pairs = [
        ("DYNAMIC", "STATIC"),
        ("DYNAMIC", "EQUAL"),
        ("PERSISTENT", "EQUAL"),
        ("PERSISTENT", "DYNAMIC"),
        ("DYNAMIC_BLOCK", "DYNAMIC"),
        ("STATIC_BLOCK", "STATIC"),
        ("EQUAL_BLOCK", "EQUAL"),
    ]
    if horizon == "24m":
        pairs += [("CROSS_6M", "DYNAMIC"), ("CROSS_12M", "DYNAMIC")]
    for left, right in pairs:
        if f"{left}_ic" not in mdf or f"{right}_ic" not in mdf:
            continue
        both = mdf[[f"{left}_ic", f"{right}_ic", f"{left}_spread", f"{right}_spread"]].dropna()
        d_ic = (both[f"{left}_ic"] - both[f"{right}_ic"]).to_numpy()
        d_sp = (both[f"{left}_spread"] - both[f"{right}_spread"]).to_numpy()
        rows.append(score_row(f"{left}-{right}", _metric(d_ic, horizon), _metric(d_sp, horizon)))

    mdf.attrs["static_factors"] = static
    mdf.attrs["first_rated"] = first_rated
    mdf.attrs["persistent_first"] = next((t for t in sorted(pers) if pers[t]), None)
    return pd.DataFrame(rows), mdf


# --------------------------------------------------------------------------- #
# Benjamini-Hochberg over the mode claims
# --------------------------------------------------------------------------- #
def binom_two_sided(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-sided binomial p for k successes in n trials."""
    if n <= 0:
        return 1.0
    probs = [math.comb(n, i) * p**i * (1.0 - p) ** (n - i) for i in range(n + 1)]
    obs = probs[min(max(k, 0), n)]
    return float(min(1.0, sum(pr for pr in probs if pr <= obs * (1.0 + 1e-12) + 1e-15)))


def bh_survivors(pvals, q: float = BH_Q, m_total: int | None = None) -> np.ndarray:
    """Benjamini-Hochberg rejections at false-discovery rate q.

    ``m_total`` is the number of hypotheses tested (defaults to len(pvals)); the
    claims are a filtered subset of those tests, so pass the full count to keep
    the correction honest.
    """
    p = np.asarray(pvals, dtype=float)
    m = int(m_total) if m_total is not None else len(p)
    keep = np.zeros(len(p), dtype=bool)
    if len(p) == 0 or m <= 0:
        return keep
    order = np.argsort(p)
    cutoff = 0
    for rank, idx in enumerate(order, start=1):
        if np.isfinite(p[idx]) and p[idx] <= rank / m * q:
            cutoff = rank
    keep[order[:cutoff]] = True
    return keep


def bh_table(mode: pd.DataFrame, m_total: int | None = None) -> pd.DataFrame:
    """Step-5 claims (70% of rated months) for the main window, with BH survival."""
    claims = mode[(mode["window"] == MAIN_WINDOW) & mode["stable_70"]].copy()
    claims["k"] = claims[["rewarded_pos", "rewarded_neg"]].max(axis=1).astype(int)
    claims["p_value"] = [binom_two_sided(int(k), int(n)) for k, n in zip(claims["k"], claims["rated_months"])]
    claims["bh_survive"] = bh_survivors(claims["p_value"].to_numpy(), BH_Q, m_total)
    return claims.drop(columns=["k"])


# --------------------------------------------------------------------------- #
# T-118 reproduction gate
# --------------------------------------------------------------------------- #
def reproduce_t118(panel: pd.DataFrame) -> pd.DataFrame:
    """Recompute five pooled T-118 ICs on the built panel; < 0.005 is a match."""
    rows = []
    for (factor, horizon), expected in T118_IC.items():
        ic = monthly_ic(panel, factor, f"excess_{HORIZONS[horizon]}")
        got = float(ic.mean())
        rows.append(
            {
                "factor": factor,
                "horizon": horizon,
                "t118": expected,
                "reproduced": got,
                "diff": got - expected,
                "ok": bool(abs(got - expected) < 0.005),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-207 point-in-time factor rewards")
    ap.add_argument("--out", default=".tmp/t207")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--start", default="2019-06-01")
    ap.add_argument("--end", default="2026-11-03")
    ap.add_argument("--rebuild-panel", action="store_true")
    ap.add_argument("--placebo", action="store_true",
                    help="run the seeded cross-sectional permutation placebo (own timing)")
    ap.add_argument("--placebo-runs", type=int, default=PLACEBO_RUNS)
    args = ap.parse_args(argv)

    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = Path(args.snapshot) if args.snapshot else default_snapshot()
    panel_path = out / "panel.parquet"

    if panel_path.exists() and not args.rebuild_panel:
        panel = pd.read_parquet(panel_path)
        print(f"panel: {len(panel):,} rows loaded from {panel_path}")
    else:
        con = connect(snapshot)
        try:
            panel, meta = build_panel(con, args.start, args.end)
        finally:
            con.close()
        panel.to_parquet(panel_path, index=False)
        print(
            f"panel: {meta['rows']:,} rows x {meta['companies']:,} companies, "
            f"{meta['rebalances']} rebalances {meta['first_date']}..{meta['last_date']} "
            f"({time.time() - t0:.0f}s) -> {panel_path}"
        )

    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["date"].dt.year >= STAT_YEAR].reset_index(drop=True)
    dates = pd.DatetimeIndex(panel["date"].drop_duplicates().sort_values())
    print(
        f"statistics: {len(panel):,} company-months, {panel['entity_id'].nunique():,} companies, "
        f"{len(dates)} month-ends {dates.min().date()}..{dates.max().date()}"
    )
    for horizon, sessions in HORIZONS.items():
        usable = int(panel.groupby("date", observed=True)[f"excess_{sessions}"].apply(lambda s: s.notna().any()).sum())
        print(f"  {horizon}: {usable} month-ends with a realised target")

    reproduction = reproduce_t118(panel)
    print("\nT-118 reproduction (pooled mean IC, 2021+):")
    print(reproduction.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    if not reproduction["ok"].all():
        print("\nSTOP: the rebuilt panel does not reproduce T-118; not continuing.")
        return 2

    con = connect(snapshot)
    try:
        calendar = con.execute(
            "SELECT DISTINCT date FROM px_daily WHERE exch = 'NSE' ORDER BY date"
        ).df()
        tri = con.execute(
            f"SELECT CAST(date AS DATE) AS date, tri FROM index_tri "
            f"WHERE index_name = '{BENCHMARK}' AND tri IS NOT NULL ORDER BY 1"
        ).df()
    finally:
        con.close()

    mapping, sector_report = sector_map(panel)
    panel["sector_group"] = panel["sector"].map(normalise_sector).map(mapping)
    panel = add_size_buckets(panel)
    regime = regime_labels(dates, tri)
    print("\nsector groups (a sector stays whole with >= 30 names in >= 12 months;"
          " sector ICs use >= 30-name months):")
    print(sector_report.groupby("group", observed=True)
          .agg(sectors=("sector", "count"), months_30p=("months_at_least_30", "sum"),
               min_names=("min_names_month", "min"))
          .sort_values("months_30p", ascending=False).to_string())
    if sector_report.attrs.get("thin"):
        print(f"  folded into Other (merged): {', '.join(sector_report.attrs['thin'])}")
    print("  group min names a month:", sector_report.attrs["group_min"])
    unclassified = float(panel["sector_group"].isna().mean())
    print(f"  no company_industry sector: {unclassified:.0%} of company-months, excluded from the sector split")
    cell_counts = regime["regime"].value_counts(dropna=False).to_dict()
    print(f"\nregime cells (month-ends): {cell_counts}")

    ic_table = build_ic_table(panel, calendar["date"], dates, regime, list(FACTORS))
    print(f"\nIC table: {len(ic_table):,} (split, group, factor, horizon, month) ICs")
    reg = ic_table[ic_table["split"] == "regime"]
    print("regime IC months by cell/horizon:",
          {f"{h}/{g}": int(n)
           for (h, g), n in reg.groupby(["horizon", "group"])["date"].nunique().items()})
    rewarded = build_rewarded(ic_table, dates)
    print(f"rewarded table: {len(rewarded):,} rows over windows {WINDOWS} ({time.time() - t0:.0f}s)")

    mode = mode_table(rewarded)
    shifts = shifts_table(rewarded)
    tested = mode[mode["window"] == MAIN_WINDOW]
    rated_cells = tested[tested["rated_months"] >= MIN_KNOWN_MONTHS]
    claims = bh_table(mode, m_total=len(rated_cells))
    rewarded.to_csv(out / "rewarded_by_date.csv", index=False, float_format="%.6g")
    mode.to_csv(out / "mode.csv", index=False, float_format="%.6g")
    shifts.to_csv(out / "shifts.csv", index=False, float_format="%.6g")

    wf_frames = []
    for horizon in HORIZONS:
        summary, monthly = walk_forward(panel, rewarded, horizon)
        wf_frames.append(summary)
        static = monthly.attrs.get("static_factors", {})
        print(f"\nwalk-forward {horizon}: first rated {monthly.attrs.get('first_rated')}, "
              f"STATIC set {static}")
        print(summary.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    walk = pd.concat(wf_frames, ignore_index=True)
    walk.to_csv(out / "walk_forward.csv", index=False, float_format="%.6g")

    blocks = pd.concat(
        [block_decomposition(panel, rewarded, horizon) for horizon in HORIZONS],
        ignore_index=True,
    )
    blocks.to_csv(out / "round2_blocks.csv", index=False, float_format="%.6g")
    print("\nround 2: block decomposition, 24m (DYNAMIC set; IC of sign x block-mean z):")
    print(blocks[blocks["horizon"] == "24m"].to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    print("\nblock mean IC by horizon:")
    print(blocks.pivot(index="block", columns="horizon", values="mean_ic")
          .to_string(float_format=lambda v: f"{v:+.3f}"))

    stale = pd.concat(
        [staleness_table(ic_table, rewarded, horizon) for horizon in HORIZONS],
        ignore_index=True,
    )
    stale.to_csv(out / "staleness.csv", index=False)
    print("\nround 2: staleness (IC start age in months over the test months):")
    print(stale.groupby("horizon")[["newest_age_months", "oldest_age_months"]]
          .agg(["mean", "min", "max"]).to_string(float_format=lambda v: f"{v:.1f}"))

    main_mode = mode[(mode["window"] == MAIN_WINDOW) & (mode["split"] == "all")]
    print(f"\nrewarded in >= {STABLE_SHARE:.0%} of rated months (all companies, window {MAIN_WINDOW}):")
    for horizon in HORIZONS:
        sub = main_mode[(main_mode["horizon"] == horizon) & main_mode["stable_70"]]
        names = [f"{r.factor}({'+' if r.dominant_sign > 0 else '-'})"
                 for r in sub.itertuples(index=False)]
        print(f"  {horizon}: {', '.join(names) if names else 'none'}")

    split_cells = tested[["factor", "horizon", "split"]].drop_duplicates()
    print(
        f"\nBH at {BH_Q:.0%}: {len(claims)} stable-70 claims, "
        f"{int(claims['bh_survive'].sum())} survive; "
        f"{len(tested):,} group cells evaluated, {len(rated_cells):,} with a rated window "
        f"({len(split_cells):,} factor x horizon x split cells)"
    )
    if args.placebo:
        t_placebo = time.time()
        placebo = placebo_counts(panel, calendar["date"], dates, args.placebo_runs)
        placebo.to_csv(out / "placebo_factors.csv", index=False, float_format="%.6g")
        per_run = (
            placebo.groupby(["run", "horizon"], as_index=False)["stable_70"].sum()
            .rename(columns={"stable_70": "claims"})
        )
        per_run.to_csv(out / "placebo.csv", index=False)
        summary = per_run.groupby("horizon")["claims"].agg(["mean", "max", "count"])
        print(f"\nplacebo ({args.placebo_runs} runs, {time.time() - t_placebo:.0f}s): "
              f"factors reaching the 70% claim per run")
        print(summary.to_string(float_format=lambda v: f"{v:.2f}"))
    else:
        print(f"\nplacebo skipped (pass --placebo; {PLACEBO_RUNS} seeded cross-sectional permutations)")

    written = ["rewarded_by_date.csv", "mode.csv", "shifts.csv", "walk_forward.csv",
               "round2_blocks.csv", "staleness.csv"]
    if args.placebo:
        written += ["placebo.csv", "placebo_factors.csv"]
    print(f"\nwrote {out}/{{{', '.join(written)}}} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
