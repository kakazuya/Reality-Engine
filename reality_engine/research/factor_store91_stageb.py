"""T-229 stage B: ICs on the 91 stores, selection control, placebo and T-228 text claims.

The stage-A panel (`.tmp/t229/panel.parquet`) supplies the store factors; the targets are rebuilt
from the truth snapshot's adjusted prices exactly as T-207 does (`tr_close` forward return minus the
NIFTY 500 TRI return), so a broken store `adj_factor` cannot move a target.  The store-price
targets are kept only as a check.  Factor ICs are measured twice on the same company-months: the
store value and the truth panel's value of the same factor.

Everything here is conditional on "91 companies picked in Nov 2026"; no number is a universe claim.

    python -m reality_engine.research.factor_store91_stageb --out .tmp/t229

Outputs under ``--out``: ``stage_b.md`` (full tables), ``target_check.csv``,
``target_check_flagged.csv``, ``ic_side_by_side.csv``, ``control.csv``, ``placebo.csv``,
``power.csv``, ``claims_coverage.csv``.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from reality_engine.research.factor_store91 import (
    FACTORS,
    PANEL_COUNTERPARTS,
    avail_sessions,
    session_calendar,
    store_paths,
)
from reality_engine.research.factor_weights import (
    default_snapshot,
    newey_west_tstat,
    spearman_ic,
)

STAGE_A_DEFAULT = Path(".tmp/t229")
CLAIMS_DEFAULT = Path("D:/RealityEngine/t228/claims_91.db")
HORIZONS = ("3m", "6m", "12m")
SESSIONS = {"3m": 63, "6m": 126, "12m": 252}
LAGS = {"3m": 2, "6m": 5, "12m": 11}
HORIZON_MONTHS = {"3m": 3, "6m": 6, "12m": 12}
TEXT_FACTORS = ("claim_rev_growth", "claim_margin_dir", "claim_debt_dir", "claim_count_12m")
BENCHMARK = "NIFTY 500"
MIN_NAMES = 20
MIN_MONTHS = 12
POWER_Z = 1.959964 + 0.8416212  # two-sided 5% and 80% power
LABEL = "91 companies picked in Nov 2026"


# --------------------------------------------------------------------------- #
# Targets from the truth snapshot (T-207 arithmetic, never the store close)
# --------------------------------------------------------------------------- #
def _snapshot_connection(snapshot: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(snapshot), read_only=True)
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=2")
    return con


def truth_targets(snapshot: Path, dates: list[pd.Timestamp]) -> pd.DataFrame:
    """Forward total returns and NIFTY-500 excess for every ISIN at every rebalance date.

    Same arithmetic as ``factor_weights._price_panel_for_entities``: NSE row first, the return
    joins on the shared NSE session index (so a missing horizon session gives no target), and the
    benchmark is the NIFTY 500 TRI ratio.  3m is added to T-207's 6m/12m.

    The query reads only the ~120 price dates that the 30 rebalances and their three horizons can
    touch (a full ``px_daily`` hash join at this CPU load stalls), then the calendar arithmetic is
    a column ratio in pandas.
    """
    con = _snapshot_connection(snapshot)
    try:
        cal = pd.to_datetime(con.execute(
            "SELECT DISTINCT date FROM px_daily WHERE exch = 'NSE' ORDER BY date").df()["date"])
        position = {day: index for index, day in enumerate(cal)}
        rebal = [day for day in dates if day in position]
        needed: set[pd.Timestamp] = set(rebal)
        future: dict[tuple[pd.Timestamp, str], pd.Timestamp] = {}
        for day in rebal:
            for label, offset in SESSIONS.items():
                index = position[day] + offset
                if index < len(cal):
                    future[(day, label)] = cal[index]
                    needed.add(cal[index])
        benchmark = con.execute(
            f"SELECT date, tri FROM index_tri WHERE index_name = '{BENCHMARK}' AND tri IS NOT NULL"
        ).df()
        day_list = ", ".join(f"DATE '{day.date()}'" for day in sorted(needed))
        px = con.execute(
            f"SELECT isin, date, tr_close, exch FROM px_daily "
            f"WHERE date IN ({day_list}) AND tr_close IS NOT NULL").df()
    finally:
        con.close()

    px["date"] = pd.to_datetime(px["date"])
    px["_nse"] = (px["exch"].astype("string").str.upper() == "NSE").astype(int)
    px = px.sort_values(["isin", "date", "_nse"]).drop_duplicates(["isin", "date"], keep="last")
    close = px.pivot_table(index="isin", columns="date", values="tr_close", aggfunc="last")
    tri = benchmark.assign(date=pd.to_datetime(benchmark["date"])).set_index("date")["tri"].astype(float)

    rows: list[pd.DataFrame] = []
    for day in rebal:
        if day not in close.columns or day not in tri.index:
            continue
        base = close[day]
        tri0 = float(tri.loc[day])
        for label, offset in SESSIONS.items():
            horizon_day = future.get((day, label))
            if horizon_day is None or horizon_day not in close.columns or horizon_day not in tri.index:
                continue
            ret = close[horizon_day] / base - 1.0
            bm = float(tri.loc[horizon_day]) / tri0 - 1.0
            block = pd.DataFrame({"date": day, "isin": ret.index.astype(str),
                                  "horizon": label, "ret": ret.to_numpy(dtype=float)})
            block["excess"] = block["ret"] - bm
            rows.append(block.dropna(subset=["ret", "excess"]))
    if not rows:
        return pd.DataFrame(columns=["date", "isin", "horizon", "ret", "excess"])
    return pd.concat(rows, ignore_index=True)


def target_check(panel: pd.DataFrame, targets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Store-price vs truth-price forward returns: rho and the companies more than 5pp apart.

    The store excess is relative to the equal-weight mean of the 91; the truth excess is relative
    to NIFTY 500, so the pooled excess correlation carries that level wedge.  The price-integrity
    test is therefore the raw-return correlation (the two series should be the same return), and
    the >5pp list uses raw-return differences.
    """
    wide = targets.pivot_table(index=["date", "isin"], columns="horizon",
                               values=["ret", "excess"]).reset_index()
    wide.columns = ["date", "isin"] + [f"{how}_{hz}" for how, hz in wide.columns[2:]]
    wide = wide.rename(columns={f"ret_{h}": f"tret_{h}" for h in HORIZONS}
                       | {f"excess_{h}": f"texc_{h}" for h in HORIZONS})
    panel_key = panel[["store", "symbol", "date", "isin",
                       *[f"ret_{h}" for h in HORIZONS], *[f"excess_{h}" for h in HORIZONS]]].copy()
    merged = panel_key.merge(wide, on=["date", "isin"], how="inner")

    summary: list[dict[str, Any]] = []
    flagged: list[pd.DataFrame] = []
    pooled_store: list[np.ndarray] = []
    pooled_truth: list[np.ndarray] = []
    for horizon in HORIZONS:
        pair = merged[["date", "store", "symbol", f"ret_{horizon}", f"excess_{horizon}",
                       f"tret_{horizon}", f"texc_{horizon}"]].copy()
        pair.columns = ["date", "store", "symbol", "store_ret", "store_exc", "truth_ret", "truth_exc"]
        pair = pair.replace([np.inf, -np.inf], np.nan).dropna(subset=["store_ret", "truth_ret"])
        rho_raw = spearman_ic(pair["store_ret"], pair["truth_ret"], min_n=5) if len(pair) > 5 else np.nan
        monthly = pair.groupby("date").apply(
            lambda g: spearman_ic(g["store_ret"], g["truth_ret"], min_n=5)
        ).dropna()
        both = pair.dropna(subset=["store_exc", "truth_exc"])
        rho_exc = spearman_ic(both["store_exc"], both["truth_exc"], min_n=5) if len(both) > 5 else np.nan
        monthly_exc = both.groupby("date").apply(
            lambda g: spearman_ic(g["store_exc"], g["truth_exc"], min_n=5)
        ).dropna()
        diff = (pair["store_ret"] - pair["truth_ret"]).abs()
        per_company = pair.assign(diff=diff).groupby(["store", "symbol"], sort=False).agg(
            months=("diff", "size"), mean_abs_diff=("diff", "mean"), max_abs_diff=("diff", "max")
        ).reset_index()
        bad = per_company[(per_company["mean_abs_diff"] > 0.05) & (per_company["months"] >= 6)].copy()
        bad["horizon"] = horizon
        flagged.append(bad)
        pooled_store.append(pair["store_ret"].to_numpy(dtype=float))
        pooled_truth.append(pair["truth_ret"].to_numpy(dtype=float))
        summary.append({
            "horizon": horizon, "pairs": int(len(pair)),
            "rho_raw_pooled": rho_raw,
            "rho_raw_monthly_median": float(monthly.median()) if len(monthly) else np.nan,
            "months": int(len(monthly)),
            "rho_excess_pooled": rho_exc,
            "rho_excess_monthly_median": float(monthly_exc.median()) if len(monthly_exc) else np.nan,
            "companies_gt5pp": int(len(bad)),
            "mean_abs_diff": float(diff.mean()) if len(diff) else np.nan,
        })
    summary_df = pd.DataFrame(summary)
    flagged_df = pd.concat(flagged, ignore_index=True) if flagged else pd.DataFrame()
    if pooled_store:
        store_all = np.concatenate(pooled_store)
        truth_all = np.concatenate(pooled_truth)
        overall = spearman_ic(pd.Series(store_all), pd.Series(truth_all), min_n=5)
    else:  # pragma: no cover - prices exist in the panel by construction
        overall = float("nan")
    summary_df.attrs["overall_rho"] = overall
    return summary_df, flagged_df, overall


# --------------------------------------------------------------------------- #
# T-228 text claims -> four point-in-time factors
# --------------------------------------------------------------------------- #
def _sign_value(value: Any) -> float:
    text = str(value or "").strip()
    return {"+": 1.0, "-": -1.0, "0": 0.0}.get(text, np.nan)


def _midpoint(low: Any, high: Any) -> float:
    values = [float(v) for v in (low, high) if pd.notna(v)]
    return float(np.mean(values)) if values else np.nan


def text_factors(panel: pd.DataFrame, claims_path: Path,
                 sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per (store, month-end) with the four T-228 claim factors.

    ``status='verified'`` only; availability is the same ``known_at`` -> session rule as stage A.
    """
    empty = pd.DataFrame(columns=["store", "date", *TEXT_FACTORS])
    if not claims_path.exists():
        print(f"claims database missing: {claims_path}", flush=True)
        return empty
    con = sqlite3.connect(f"file:{claims_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        claims = pd.read_sql_query(
            """SELECT symbol, known_at, node, sign, value_low, value_high, unit, judge_forward
               FROM claim WHERE status = 'verified' AND known_at IS NOT NULL""",
            con,
        )
    except sqlite3.DatabaseError as exc:  # a half-written worker database is tolerated
        print(f"claims snapshot unreadable ({exc}); text factors skipped", flush=True)
        return empty
    finally:
        con.close()
    if claims.empty:
        return empty
    claims["avail"] = avail_sessions(claims["known_at"], sessions)
    claims = claims.dropna(subset=["avail"]).sort_values(["symbol", "avail", "known_at"])
    mapping = panel[["store", "symbol"]].drop_duplicates()
    store_of = dict(zip(mapping["symbol"], mapping["store"]))
    ttm = panel.set_index(["store", "date"])["ttm_rev_yoy"]

    rows: list[dict[str, Any]] = []
    for symbol, group in claims.groupby("symbol", sort=False):
        store = store_of.get(symbol)
        if store is None:
            continue
        for day in sorted(panel.loc[panel["store"] == store, "date"].unique()):
            day = pd.Timestamp(day)
            seen = group[group["avail"] <= day]
            if seen.empty:
                continue
            row: dict[str, Any] = {"store": store, "date": day,
                                   **{factor: np.nan for factor in TEXT_FACTORS}}
            pct = seen[(seen["node"] == "revenue.total") & (seen["unit"].astype("string") == "pct")]
            if not pct.empty:
                last = pct.iloc[-1]
                mid = _midpoint(last["value_low"], last["value_high"])
                growth = ttm.get((store, day), np.nan)
                if pd.notna(mid) and pd.notna(growth):
                    row["claim_rev_growth"] = mid / 100.0 - float(growth)
            margins = seen[seen["node"].astype("string").str.startswith("margin.", na=False)]
            if not margins.empty:
                row["claim_margin_dir"] = _sign_value(margins.iloc[-1]["sign"])
            debt = seen[(seen["node"] == "debt.level") & (seen["sign"].astype("string").isin(["+", "-"]))]
            if not debt.empty:
                row["claim_debt_dir"] = _sign_value(debt.iloc[-1]["sign"])
            window = seen[seen["avail"] > day - pd.Timedelta(days=365)]
            row["claim_count_12m"] = float(len(window))
            rows.append(row)
    return pd.DataFrame(rows) if rows else empty


# --------------------------------------------------------------------------- #
# ICs, store vs truth, on the same company-months
# --------------------------------------------------------------------------- #
def monthly_ic(frame: pd.DataFrame, factor: str, target: str) -> pd.Series:
    """Spearman per rebalance date, at least MIN_NAMES companies."""
    if factor not in frame.columns or target not in frame.columns:
        return pd.Series(dtype=float)
    work = frame[["date", factor, target]].dropna()
    if work.empty:
        return pd.Series(dtype=float)
    return work.groupby("date", sort=True).apply(
        lambda g: spearman_ic(g[factor], g[target], min_n=MIN_NAMES)
    ).dropna()


def ic_stats(series: pd.Series, horizon: str) -> dict[str, Any]:
    months = int(series.notna().sum())
    if months == 0:
        return {"months": 0, "mean_ic": np.nan, "nw_t": np.nan, "sign_share": np.nan}
    mean = float(series.mean())
    sign_share = float((np.sign(series) == np.sign(mean)).mean()) if mean != 0 else 0.5
    return {
        "months": months,
        "mean_ic": mean,
        "nw_t": newey_west_tstat(series, LAGS[horizon]),
        "sign_share": sign_share,
    }


def side_by_side(frame: pd.DataFrame) -> pd.DataFrame:
    """Store and truth ICs per factor/horizon on the same pairwise-complete company-months."""
    rows: list[dict[str, Any]] = []
    for factor in [*FACTORS, *TEXT_FACTORS]:
        truth_col = f"truth_{factor}"
        for horizon in HORIZONS:
            target = f"texcess_{horizon}"
            needs = ["date", factor, target] + ([truth_col] if truth_col in frame.columns else [])
            pair = frame[needs].replace([np.inf, -np.inf], np.nan).dropna()
            if factor in TEXT_FACTORS:
                wide_months = int(pair.groupby("date").size().ge(MIN_NAMES).sum())
                if wide_months < MIN_MONTHS:
                    continue  # the brief's coverage gate, applied per horizon
            mean_names = float(pair.groupby("date").size().mean()) if len(pair) else np.nan
            store = ic_stats(monthly_ic(pair, factor, target), horizon)
            rows.append({"factor": factor, "horizon": horizon, "side": "store", **store,
                         "mean_names": mean_names, "truth_counterpart": truth_col in frame.columns})
            if truth_col in frame.columns:
                truth = ic_stats(monthly_ic(pair, truth_col, target), horizon)
                rows.append({"factor": factor, "horizon": horizon, "side": "truth", **truth,
                             "mean_names": mean_names, "truth_counterpart": True})
    out = pd.DataFrame(rows)
    flag = {}
    for (factor, horizon), group in out.groupby(["factor", "horizon"]):
        both = group.set_index("side")
        if {"store", "truth"} <= set(both.index):
            s, t = both.loc["store", "mean_ic"], both.loc["truth", "mean_ic"]
            flag[(factor, horizon)] = bool(pd.notna(s) and pd.notna(t) and np.sign(s) != np.sign(t))
    out["sign_differs"] = [flag.get((f, h), False) for f, h in zip(out["factor"], out["horizon"])]
    return out


# --------------------------------------------------------------------------- #
# Selection control: 50 seeded 91-company draws matched on sector and size
# --------------------------------------------------------------------------- #
def _size_bucket(value: float, cuts: np.ndarray) -> str:
    if not np.isfinite(value):
        return "na"
    return "small" if value <= cuts[0] else ("mid" if value <= cuts[1] else "large")


def sector_map(snapshot: Path, isins: set[str]) -> dict[str, str]:
    """Snapshot company_industry label per ISIN (today's label, T-207's caveat)."""
    con = _snapshot_connection(snapshot)
    try:
        rows = con.execute(
            "SELECT isin, any_value(sector) AS sector FROM company_industry "
            "WHERE sector IS NOT NULL GROUP BY isin"
        ).df()
    finally:
        con.close()
    rows = rows[rows["isin"].astype("string").isin(isins)]
    return dict(zip(rows["isin"].astype(str), rows["sector"].astype(str)))


def _draw_one(cells: dict[tuple[str, str], list[str]], by_bucket: dict[str, list[str]],
              all_companies: list[str], wanted: dict[tuple[str, str], int],
              rng: np.random.Generator) -> list[str]:
    """One 91-company draw with the observed cell counts, falling back bucket-first."""
    chosen: list[str] = []
    for (sector, bucket), count in wanted.items():
        options = list(cells.get((sector, bucket), []))
        if len(options) < count:
            options = list(dict.fromkeys(options + by_bucket.get(bucket, [])))
        if len(options) < count:
            options = list(dict.fromkeys(options + all_companies))
        if not options:
            continue
        chosen.extend(rng.choice(options, size=count, replace=len(options) < count).tolist())
    return chosen


def control_check(truth_path: Path, targets: pd.DataFrame,
                  our_isins: set[str], our_attrs: pd.DataFrame,
                  our_truth_ic: pd.DataFrame, draws: int = 50,
                  seed: int = 229) -> tuple[pd.DataFrame, int]:
    """IC of the 91's truth factors vs 50 draws from the truth panel matched on sector + size."""
    cols = ["date", "entity_id", "isin", "symbol", "sector",
            *dict.fromkeys(PANEL_COUNTERPARTS.values())]
    truth = pd.read_parquet(truth_path, columns=cols)
    truth["date"] = pd.to_datetime(truth["date"])
    wide = targets.pivot_table(index=["date", "isin"], columns="horizon", values="excess").reset_index()
    wide.columns = ["date", "isin", *[f"texcess_{col}" for col in wide.columns[2:]]]
    truth = truth.merge(wide, on=["date", "isin"], how="left")
    truth["company"] = truth["entity_id"].astype("string")

    our_entity = set(truth.loc[truth["isin"].astype("string").isin(our_isins), "company"].dropna())
    pool = truth[~(truth["isin"].astype("string").isin(our_isins) | truth["company"].isin(our_entity))].copy()
    pool = pool.dropna(subset=["company"])
    attrs = pool.groupby("company", sort=False).agg(
        sector=("sector", lambda s: s.dropna().iloc[0] if s.notna().any() else "<none>"),
        size=("size", "median"),
    ).reset_index()

    pool_sizes = attrs["size"].dropna()
    cuts = np.quantile(pool_sizes, [1 / 3, 2 / 3]) if len(pool_sizes) > 10 else np.array([np.nan, np.nan])
    attrs["bucket"] = attrs["size"].apply(lambda v: _size_bucket(float(v), cuts))
    our = our_attrs.copy()
    our["bucket"] = our["size"].apply(lambda v: _size_bucket(float(v), cuts))
    our["sector"] = our["sector"].fillna("<none>")
    wanted = our.groupby(["sector", "bucket"]).size().to_dict()

    cells: dict[tuple[str, str], list[str]] = {}
    for (sector, bucket), group in attrs.groupby(["sector", "bucket"]):
        cells[(sector, bucket)] = group["company"].tolist()
    by_bucket: dict[str, list[str]] = {
        bucket: attrs.loc[attrs["bucket"] == bucket, "company"].tolist()
        for bucket in ("small", "mid", "large", "na")
    }
    all_companies = attrs["company"].tolist()
    fallbacks = sum(1 for cell, count in wanted.items() if len(cells.get(cell, [])) < count)

    rng = np.random.default_rng(seed)
    draw_frames = []
    for _ in range(draws):
        chosen = _draw_one(cells, by_bucket, all_companies, wanted, rng)
        draw_frames.append(truth[truth["company"].isin(chosen)].copy())

    rows: list[dict[str, Any]] = []
    for factor in PANEL_COUNTERPARTS:
        for horizon in HORIZONS:
            target = f"texcess_{horizon}"
            means = []
            for draw in draw_frames:
                ic = monthly_ic(draw, factor, target)
                if ic.notna().sum() >= MIN_MONTHS:
                    means.append(float(ic.mean()))
            if not means:
                continue
            ours = our_truth_ic[(our_truth_ic["factor"] == factor)
                                & (our_truth_ic["horizon"] == horizon)
                                & (our_truth_ic["side"] == "truth")]["mean_ic"]
            our_mean = float(ours.iloc[0]) if len(ours) else np.nan
            distribution = np.asarray(means, dtype=float)
            percentile = np.nan
            if np.isfinite(our_mean) and len(distribution):
                percentile = float(100.0 * np.mean(distribution < our_mean))
            rows.append({
                "factor": factor, "horizon": horizon, "draws": len(distribution),
                "our_mean_ic": our_mean, "draw_mean_ic": float(np.mean(distribution)),
                "draw_median_ic": float(np.median(distribution)),
                "draw_sd_ic": float(np.std(distribution, ddof=1)) if len(distribution) > 1 else np.nan,
                "percentile": percentile,
            })
    return pd.DataFrame(rows), fallbacks


# --------------------------------------------------------------------------- #
# Placebo (within-date target permutations), BH and power
# --------------------------------------------------------------------------- #
def _zranks(values: np.ndarray) -> np.ndarray:
    ranks = pd.Series(values).rank().to_numpy(dtype=float)
    sd = ranks.std(ddof=0)
    return (ranks - ranks.mean()) / sd if sd > 0 else np.zeros_like(ranks)


def placebo_check(frame: pd.DataFrame, factors: list[str], n_perm: int = 200,
                  seed: int = 229) -> pd.DataFrame:
    """Two-sided permutation p-value of each factor/horizon mean IC.

    One within-date permutation of the target ranks per draw (the factor values stay real).  Ties
    are broken by average ranks, exactly like ``spearman_ic``.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for factor in factors:
        for horizon in HORIZONS:
            target = f"texcess_{horizon}"
            if factor not in frame.columns or target not in frame.columns:
                continue
            truth_col = f"truth_{factor}"
            columns = ["date", factor, target] + ([truth_col] if truth_col in frame.columns else [])
            # the same pairwise-complete company-months the side-by-side table reports
            work = frame[columns].replace([np.inf, -np.inf], np.nan).dropna()
            blocks: list[tuple[np.ndarray, np.ndarray]] = []
            for _, group in work.groupby("date", sort=True):
                if len(group) < MIN_NAMES:
                    continue
                x, y = group[factor].to_numpy(float), group[target].to_numpy(float)
                if np.unique(x).size < 2 or np.unique(y).size < 5:
                    continue
                blocks.append((_zranks(x), _zranks(y)))
            months = len(blocks)
            observed = monthly_ic(work, factor, target)
            entry: dict[str, Any] = {"factor": factor, "horizon": horizon, "months": months,
                                     "mean_ic": float(observed.mean()) if months else np.nan,
                                     "p_value": np.nan, "bh_reject_10": False}
            if months >= MIN_MONTHS:
                null = np.zeros(n_perm)
                for rx, ry in blocks:
                    shuffled = rng.permuted(np.tile(ry, (n_perm, 1)), axis=1)
                    null += shuffled @ rx / len(rx)
                null /= months
                entry["p_value"] = float((1.0 + np.sum(np.abs(null) >= abs(entry["mean_ic"]))) / (n_perm + 1))
            rows.append(entry)
    out = pd.DataFrame(rows)
    tested = out["p_value"].notna()
    if tested.any():
        out.loc[tested, "bh_reject_10"] = _bh(out.loc[tested, "p_value"].to_numpy(), 0.10)
    return out


def _bh(pvalues: np.ndarray, q: float) -> np.ndarray:
    """Benjamini-Hochberg step-up at FDR ``q``; returns the rejection mask."""
    p = np.asarray(pvalues, dtype=float)
    n = len(p)
    order = np.argsort(p)
    threshold = q * np.arange(1, n + 1) / n
    rejects = np.zeros(n, dtype=bool)
    below = p[order] <= threshold
    if below.any():
        last = np.max(np.where(below)[0])
        rejects[order[: last + 1]] = True
    return rejects


def power_table(ic: pd.DataFrame) -> pd.DataFrame:
    """Smallest mean IC detectable at 80% power for 6m and 12m, given the overlap."""
    rows: list[dict[str, Any]] = []
    for horizon in ("6m", "12m"):
        block = ic[(ic["side"] == "store") & (ic["horizon"] == horizon)]
        for _, row in block.iterrows():
            if row["months"] < MIN_MONTHS:
                continue
            series = _ic_series_cache.get((row["factor"], horizon))
            sd = float(series.std(ddof=1)) if series is not None and series.notna().sum() > 1 else np.nan
            n_eff = row["months"] / HORIZON_MONTHS[horizon]
            rows.append({
                "factor": row["factor"], "horizon": horizon, "months": int(row["months"]),
                "effective_windows": n_eff, "sd_monthly_ic": sd,
                "min_detectable_mean_ic": POWER_Z * sd / np.sqrt(n_eff) if pd.notna(sd) and n_eff > 0 else np.nan,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    summary = [{
        "factor": "ALL (median sd)", "horizon": horizon,
        "months": int(group["months"].max()),
        "effective_windows": float(group["effective_windows"].max()),
        "sd_monthly_ic": float(group["sd_monthly_ic"].median()),
        "min_detectable_mean_ic": POWER_Z * float(group["sd_monthly_ic"].median())
        / np.sqrt(float(group["effective_windows"].max())),
    } for horizon, group in out.groupby("horizon")]
    return pd.concat([out, pd.DataFrame(summary)], ignore_index=True)


_ic_series_cache: dict[tuple[str, str], pd.Series] = {}


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _md(df: pd.DataFrame, columns: list[str] | None = None, floatfmt: str = ".4f") -> str:
    if df is None or df.empty:
        return "_none_\n"
    view = df[columns] if columns else df
    lines = ["| " + " | ".join(view.columns) + " |", "|" + "|".join("---" for _ in view.columns) + "|"]
    for _, row in view.iterrows():
        cells = []
        for value in row:
            if isinstance(value, (float, np.floating)):
                cells.append("" if pd.isna(value) else format(float(value), floatfmt))
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_stage_b_md(out_dir: Path, tables: dict[str, pd.DataFrame], headline: dict[str, Any]) -> None:
    parts = [f"# T-229 stage B full tables — {LABEL}\n",
             "Generated by `python -m reality_engine.research.factor_store91_stageb`.\n"]
    parts.append("## Targets check (store price vs truth snapshot price)\n")
    parts.append(_md(tables.get("target_check"), floatfmt=".4f"))
    parts.append("\n## ICs, store vs truth panel, same company-months\n")
    parts.append(_md(tables.get("ic"), floatfmt=".4f"))
    parts.append("\n## Selection control (50 draws, seed 229)\n")
    parts.append(_md(tables.get("control"), floatfmt=".4f"))
    parts.append("\n## Placebo (200 within-date permutations) and power\n")
    parts.append(_md(tables.get("placebo"), floatfmt=".4f"))
    parts.append("\n" + _md(tables.get("power"), floatfmt=".4f"))
    parts.append("\n## T-228 text-claim coverage\n")
    parts.append(_md(tables.get("claims"), floatfmt=".4f"))
    parts.append("\n## Headline numbers\n")
    for key, value in headline.items():
        parts.append(f"- {key}: {value}")
    (out_dir / "stage_b.md").write_text("\n".join(parts), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-229 stage B: ICs, control, placebo, text claims")
    parser.add_argument("--stage-a", "--out", dest="stage_a", default=str(STAGE_A_DEFAULT),
                        help="stage-A output directory")
    parser.add_argument("--claims", default=str(CLAIMS_DEFAULT), help="T-228 claims database")
    parser.add_argument("--stores", default="D:/RealityEngine/tg_build/measure10")
    parser.add_argument("--draws", type=int, default=50)
    parser.add_argument("--permutations", type=int, default=200)
    args = parser.parse_args(argv)

    out = Path(args.stage_a)
    panel = pd.read_parquet(out / "panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    dates = [pd.Timestamp(d) for d in sorted(panel["date"].unique())]
    print(f"{LABEL}; panel {len(panel)} rows, {panel['store'].nunique()} companies, "
          f"{len(dates)} month-ends", flush=True)

    # 1. targets from the truth snapshot, store targets only as a check
    targets = truth_targets(default_snapshot(), dates)
    print(f"truth targets: {len(targets)} rows, horizons {sorted(targets['horizon'].unique())}", flush=True)
    target_rows, flagged, overall_rho = target_check(panel, targets)
    print(target_rows.to_string(index=False), flush=True)
    print(f"overall store-vs-truth raw-return rho: {overall_rho:.4f}", flush=True)
    target_rows.to_csv(out / "target_check.csv", index=False)
    flagged.to_csv(out / "target_check_flagged.csv", index=False)
    if not (overall_rho >= 0.90):
        print("STOP: store-vs-truth target rho < 0.90; cause reported above, no IC computed", flush=True)
        return 2

    # 2. the joint frame: truth targets, truth factors, text factors
    truth = pd.read_parquet(out / "truth_panel.parquet")
    truth["date"] = pd.to_datetime(truth["date"])
    truth_factors = truth[["date", "isin", "sector",
                           *dict.fromkeys(PANEL_COUNTERPARTS.values())]].copy()
    truth_factors = truth_factors.rename(columns={
        **{name: f"truth_{name}" for name in PANEL_COUNTERPARTS.values()},
        "sector": "truth_sector", "size": "truth_size",
    })
    panel["truth_isin"] = panel["link_isin"].fillna(panel["isin"])
    wide = targets.pivot_table(index=["date", "isin"], columns="horizon", values="excess").reset_index()
    wide.columns = ["date", "truth_isin", *[f"texcess_{col}" for col in wide.columns[2:]]]
    frame = panel.merge(wide, on=["date", "truth_isin"], how="left")
    frame = frame.merge(truth_factors.rename(columns={"isin": "truth_isin"}),
                        on=["date", "truth_isin"], how="left")

    sessions = session_calendar(store_paths(args.stores))
    # T-228 is still writing; the foreign directory is not writable from this worktree, so SQLite
    # cannot create the WAL side files there.  A byte copy inside --out is a read-only snapshot.
    claims_src = Path(args.claims)
    claims_local = out / "claims_snapshot.db"
    if claims_src.exists():
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(claims_src) + suffix)
            target = Path(str(claims_local) + suffix)
            if source.exists():
                shutil.copy2(source, target)
            elif target.exists():
                target.unlink()  # a sidecar from the previous snapshot must not replay
    else:
        print(f"claims database missing: {claims_src}", flush=True)
    text = text_factors(panel, claims_local, sessions)
    if not text.empty:
        frame = frame.merge(text, on=["store", "date"], how="left")
    for factor in TEXT_FACTORS:
        if factor not in frame.columns:
            frame[factor] = np.nan

    # 3. text coverage first
    claim_rows = []
    for factor in TEXT_FACTORS:
        per_month = frame.groupby("date")[factor].apply(lambda s: s.notna().sum())
        claim_rows.append({
            "factor": factor,
            "companies_with_value": int(frame.loc[frame[factor].notna(), "store"].nunique()),
            "months_with_value": int((per_month > 0).sum()),
            "months_ge20": int((per_month >= MIN_NAMES).sum()),
            "median_names": float(per_month[per_month > 0].median()) if (per_month > 0).any() else 0.0,
            "max_names": int(per_month.max()) if len(per_month) else 0,
        })
    claims_cov = pd.DataFrame(claim_rows)
    print(claims_cov.to_string(index=False), flush=True)
    claims_cov.to_csv(out / "claims_coverage.csv", index=False)

    # 4. ICs, store vs truth on the same company-months
    ic = side_by_side(frame)
    ic.to_csv(out / "ic_side_by_side.csv", index=False)
    tested = ic[ic["months"] >= MIN_MONTHS]
    print(tested.to_string(index=False), flush=True)

    # cache the store IC series for the power table
    _ic_series_cache.clear()
    for factor in [*FACTORS, *TEXT_FACTORS]:
        for horizon in HORIZONS:
            target = f"texcess_{horizon}"
            pair = frame[["date", factor, target]].replace([np.inf, -np.inf], np.nan).dropna()
            _ic_series_cache[(factor, horizon)] = monthly_ic(pair, factor, target)

    # 5. selection control
    snapshot = default_snapshot()
    our_isins = set(panel["isin"].dropna().astype(str)) | set(panel["link_isin"].dropna().astype(str))
    our_attrs = frame.groupby("store", sort=False).agg(
        sector=("truth_sector", lambda s: s.dropna().iloc[0] if s.notna().any() else "<none>"),
        size=("truth_size", "median"),
    )
    store_size = frame.groupby("store", sort=False)["size"].median()
    our_attrs["size"] = our_attrs["size"].fillna(store_size)
    labels = sector_map(snapshot, {isin for isin in panel["isin"].dropna().astype(str)})
    store_isin = panel.dropna(subset=["isin"]).groupby("store", sort=False)["isin"].first()
    our_attrs["sector"] = [
        sector if sector != "<none>" else labels.get(str(store_isin.get(store)), "<none>")
        for store, sector in zip(our_attrs.index, our_attrs["sector"])
    ]
    our_attrs = our_attrs.reset_index()
    control, fallbacks = control_check(out / "truth_panel.parquet", targets, our_isins, our_attrs, ic,
                                       draws=args.draws)
    control.to_csv(out / "control.csv", index=False)
    print(f"control draws: {args.draws}; sector x size cells needing a fallback: {fallbacks}", flush=True)

    # 6. placebo, BH and power
    placebo = placebo_check(frame, [*FACTORS, *TEXT_FACTORS], n_perm=args.permutations)
    placebo.to_csv(out / "placebo.csv", index=False)
    power = power_table(ic)
    power.to_csv(out / "power.csv", index=False)

    tables = {"target_check": target_rows, "ic": ic, "control": control,
              "placebo": placebo, "power": power, "claims": claims_cov}
    headline = {
        "universe": LABEL,
        "panel rows": len(frame),
        "target months 3m/6m/12m": {
            h: int(frame[f"texcess_{h}"].notna().sum()) for h in HORIZONS},
        "store-vs-truth target rho (all horizons pooled)": round(overall_rho, 4),
        "IC cells tested (months >= 12)": len(tested),
        "control draws": args.draws,
        "control cells needing a fallback": fallbacks,
        "placebo cells BH 10%": int(placebo["bh_reject_10"].sum()),
        "sign differences store vs truth": int(ic.drop_duplicates(["factor", "horizon"])["sign_differs"].sum()),
    }
    write_stage_b_md(out, tables, headline)
    print(f"\nwrote {out/'stage_b.md'}; placebo BH rejections {headline['placebo cells BH 10%']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
