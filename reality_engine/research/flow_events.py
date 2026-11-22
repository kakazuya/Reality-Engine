"""T-235 stage 2: what followed each capital-flow signal, and what preceded big moves.

Reads ``flow_signal.csv`` from stage 1 and the same read-only DuckDB snapshot,
and measures, per signal:

* forward excess return (stock total return minus Nifty 500 TRI) at 5 / 20 / 60 /
  120 / 250 sessions, signed by the signal's direction: n, mean, median, hit
  rate, Newey-West t with horizon-1 lags, and a same-stock placebo mean/p over
  20 seeded random dates;
* the same cells by size tercile (market-cap terciles within each calendar
  year), sector (thin sectors folded into Other), calendar year and market
  phase (Nifty 500 TRI above/below its 200-session mean, 12-month return sign);
* Benjamini-Hochberg at 10% over every return cell written;
* per year, the median measured horizon at which the signed excess peaks, so
  fading/strengthening and shortening lags are visible;
* a look-back: every +30% / -30% 60-session excess move, the share of moves a
  signal fired within the prior 90 sessions (recall) and the share of firings
  followed by a matching move within 60 sessions (precision), each against the
  same stock's random dates;
* same-direction signal pairs whose firings lie within 30 sessions, versus each
  signal alone.

Run:

    python -m reality_engine.research.flow_events --out .tmp/t235

Writes after_signal.csv, by_group.csv, by_year.csv, lookback.csv, moves.csv,
pairs.csv and event_counts.csv under --out. Read-only snapshot; every input row
is used only from its own availability session.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from reality_engine.research.factor_weights import connect, default_snapshot, newey_west_tstat
from reality_engine.research.flow_signals import load_shares, load_sectors

HORIZONS = (5, 20, 60, 120, 250)
PLACEBO_SEEDS = 20
MIN_CELL_N = 20
BH_Q = 0.10
WINSOR_PCT = (1, 99)  # pooled per horizon, before any cell: one bad adjustment cannot move a mean
PAIR_WINDOW = 30
MIN_PAIR_N = 20
TOP_PAIRS = 10
MOVE_PCT = 0.30
MOVE_WINDOW = 60
LOOKBACK_SESSIONS = 90
THIN_SECTOR_EVENTS = 300
PHASE_MEAN_SESSIONS = 200
PHASE_RETURN_SESSIONS = 250


# --------------------------------------------------------------------------- #
# Statistics helpers
# --------------------------------------------------------------------------- #
def two_sided_p(t: float) -> float:
    """Normal two-sided p for a t-statistic (scipy is not installed)."""
    if t is None or not np.isfinite(t):
        return float("nan")
    return float(math.erfc(abs(float(t)) / math.sqrt(2.0)))


def bh_adjust(pvalues) -> np.ndarray:
    """Benjamini-Hochberg adjusted p (q-values); NaN p stays NaN."""
    p = np.asarray(pvalues, dtype=float)
    out = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    if not ok.any():
        return out
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(p[idx])]
    m = len(order)
    adj = p[order] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    out[order] = np.minimum(adj, 1.0)
    return out


def cell_stats(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Per (keys, horizon): n, n stocks, mean, median, hit, Newey-West t and normal p."""
    columns = [*keys, "horizon", "n", "n_stocks", "mean", "median", "hit", "nw_t", "p_nw"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict] = []
    for name, group in frame.groupby(keys, sort=False, observed=True):
        name_tuple = name if isinstance(name, tuple) else (name,)
        group = group.sort_values("date_known")
        for horizon in HORIZONS:
            raw = (group[f"exc_{horizon}"].to_numpy(dtype=float)
                   * group["sign"].to_numpy(dtype=float))
            finite = np.isfinite(raw)
            values = raw[finite]
            if len(values) < MIN_CELL_N:
                continue
            t_stat = newey_west_tstat(values, lags=horizon - 1)
            rows.append({
                **dict(zip(keys, name_tuple)),
                "horizon": horizon,
                "n": int(len(values)),
                "n_stocks": int(group.loc[finite, "company"].nunique()),
                "mean": float(values.mean()),
                "median": float(np.median(values)),
                "hit": float((values > 0).mean()),
                "nw_t": float(t_stat),
                "p_nw": two_sided_p(t_stat),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Market / return plumbing
# --------------------------------------------------------------------------- #
def build_returns(con: duckdb.DuckDBPyConnection, end: str) -> None:
    """Temporary tables: calendar, prices with benchmark, forward excess returns."""
    con.execute(
        """CREATE OR REPLACE TEMP TABLE t235_cal AS
           SELECT date, CAST(row_number() OVER (ORDER BY date) - 1 AS BIGINT) AS i
           FROM (SELECT DISTINCT date FROM px_daily
                 WHERE exch = 'NSE' AND date <= CAST(? AS DATE))""",
        [end],
    )
    con.execute(
        """CREATE OR REPLACE TEMP TABLE t235_bm AS
           SELECT c.i, t.tri
           FROM t235_cal c
           JOIN (SELECT DISTINCT CAST(date AS DATE) AS date, tri FROM index_tri
                 WHERE index_name = 'NIFTY 500' AND tri IS NOT NULL) t ON t.date = c.date"""
    )
    con.execute(
        """CREATE OR REPLACE TEMP TABLE t235_pxi AS
           SELECT p.entity_id, p.date, c.i, p.close, p.tr_close, b.tri
           FROM px_daily p
           JOIN t235_cal c ON c.date = p.date
           LEFT JOIN t235_bm b ON b.i = c.i
           WHERE p.adj_close > 0 AND p.tr_close > 0"""
    )
    joins = "\n".join(
        f"LEFT JOIN t235_pxi p{h} ON p{h}.entity_id = p.entity_id AND p{h}.i = p.i + {h}\n"
        f"LEFT JOIN t235_bm b{h} ON b{h}.i = p.i + {h}"
        for h in HORIZONS
    )
    exc = ",\n".join(
        f"p{h}.tr_close / p.tr_close - b{h}.tri / b.tri AS exc_{h}" for h in HORIZONS
    )
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE t235_ret AS
            SELECT p.entity_id, p.date, p.i, p.close, p.tr_close,
                   p.tr_close / p_back.tr_close - b.tri / b_back.tri AS exc_60_lag,
                   {exc}
            FROM t235_pxi p
            JOIN t235_bm b ON b.i = p.i
            LEFT JOIN t235_pxi p_back ON p_back.entity_id = p.entity_id AND p_back.i = p.i - 60
            LEFT JOIN t235_bm b_back ON b_back.i = p.i - 60
            {joins}"""
    )
    # Winsorise each horizon once over every entity-day forward return, so the
    # event means and the placebo means read the same clipped distribution: one
    # bad corporate-action adjustment must not move a mean.
    for horizon in HORIZONS:
        quantiles = con.execute(
            f"""SELECT quantile_cont(exc_{horizon}, [{WINSOR_PCT[0] / 100}, {WINSOR_PCT[1] / 100}])
                FROM t235_ret WHERE exc_{horizon} IS NOT NULL"""
        ).fetchone()[0]
        lo, hi = float(quantiles[0]), float(quantiles[1])
        con.execute(
            f"""UPDATE t235_ret
                SET exc_{horizon} = GREATEST(LEAST(exc_{horizon}, ?), ?)
                WHERE exc_{horizon} IS NOT NULL""",
            [hi, lo],
        )


def event_returns(con: duckdb.DuckDBPyConnection, signals: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Join signals to the session return panel; keeps only real sessions."""
    work = signals[["company", "date_known", "signal", "direction", "strength"]].copy()
    work["date_known"] = pd.to_datetime(work["date_known"])
    con.register("t235_signals_df", work)
    try:
        joined = con.execute(
            """SELECT s.company, s.date_known, s.signal, s.direction, s.strength,
                      r.i, r.close, r.exc_60_lag,
                      {cols}
               FROM t235_signals_df s
               JOIN t235_ret r ON r.entity_id = s.company AND r.date = s.date_known"""
            .format(cols=", ".join(f"r.exc_{h}" for h in HORIZONS))
        ).df()
    finally:
        con.unregister("t235_signals_df")
    joined["date_known"] = pd.to_datetime(joined["date_known"]).astype("datetime64[ns]")
    joined["sign"] = np.where(joined["direction"].eq("down"), -1.0, 1.0)
    for horizon in HORIZONS:
        joined[f"sign_{horizon}"] = joined[f"exc_{horizon}"] * joined["sign"]
    joined = joined.reset_index(drop=True)
    return joined, int(len(work) - len(joined))


def placebo_frame(con: duckdb.DuckDBPyConnection, events: pd.DataFrame,
                  horizon: int, seeds: int = PLACEBO_SEEDS,
                  match_month: bool = False) -> pd.DataFrame:
    """Per (signal, seed) mean signed excess at ``horizon`` on random same-stock,
    same-calendar-year dates (the null keeps the event's market regime). With
    ``match_month`` the draw also stays inside the event's calendar month, which
    tests whether a signal only picks bad months for its own stock."""
    columns = ["signal", "seed", "placebo_mean", "n"]
    if events.empty:
        return pd.DataFrame(columns=columns)
    sub = events[["company", "signal", "direction", "date_known"]].drop_duplicates().copy()
    sub["year"] = pd.to_datetime(sub["date_known"]).dt.year
    sub["month"] = pd.to_datetime(sub["date_known"]).dt.month
    con.register("t235_ev_df", sub[["company", "signal", "direction", "year", "month"]])
    if match_month:
        list_sql = "SELECT entity_id, year, month, count(*) AS n FROM t235_sess GROUP BY 1, 2, 3"
        list_join = "s.entity_id = e.company AND s.year = e.year AND s.month = e.month"
        month_key = "AND ss.month = p.month"
        partition = "r.entity_id, year(c.date), month(c.date)"
    else:
        list_sql = "SELECT entity_id, year, count(*) AS n FROM t235_sess GROUP BY 1, 2"
        list_join = "s.entity_id = e.company AND s.year = e.year"
        month_key = ""
        partition = "r.entity_id, year(c.date)"
    try:
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE t235_sess AS
                SELECT r.entity_id, r.i, c.date, year(c.date) AS year, month(c.date) AS month,
                       CAST(row_number() OVER (PARTITION BY {partition} ORDER BY r.i) AS BIGINT) AS rn
                FROM t235_ret r JOIN t235_cal c ON c.i = r.i
                WHERE r.exc_{horizon} IS NOT NULL"""
        )
        con.execute(f"CREATE OR REPLACE TEMP TABLE t235_list AS {list_sql}")
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE t235_pos AS
                SELECT e.company, e.signal, e.direction, e.year, e.month, r.seed,
                       1 + CAST(floor(random() * s.n) AS BIGINT) AS rn
                FROM t235_ev_df e
                JOIN t235_list s ON {list_join}
                CROSS JOIN (SELECT range AS seed FROM range({int(seeds)})) r"""
        )
        out = con.execute(
            f"""SELECT p.signal, p.seed,
                       avg(CASE WHEN p.direction = 'down' THEN -r.exc_{horizon}
                                ELSE r.exc_{horizon} END) AS placebo_mean,
                       count(*) AS n
                FROM t235_pos p
                JOIN t235_sess ss ON ss.entity_id = p.company AND ss.year = p.year
                                 {month_key} AND ss.rn = p.rn
                JOIN t235_ret r ON r.entity_id = p.company AND r.i = ss.i
                GROUP BY 1, 2"""
        ).df()
    finally:
        con.unregister("t235_ev_df")
        con.execute("DROP TABLE IF EXISTS t235_sess")
        con.execute("DROP TABLE IF EXISTS t235_list")
        con.execute("DROP TABLE IF EXISTS t235_pos")
    return out


def attach_placebo(main: pd.DataFrame, con: duckdb.DuckDBPyConnection,
                   events: pd.DataFrame, seeds: int, match_month: bool = False,
                   suffix: str = "") -> pd.DataFrame:
    """Add placebo mean and one-sided empirical p to every main-table cell."""
    if main.empty:
        return main
    out = main.copy()
    out[f"placebo_mean{suffix}"] = np.nan
    out[f"placebo_diff{suffix}"] = np.nan
    out[f"placebo_p{suffix}"] = np.nan
    out[f"placebo_seeds{suffix}"] = np.nan
    for horizon in HORIZONS:
        if not out["horizon"].eq(horizon).any():
            continue
        placebo = placebo_frame(con, events[np.isfinite(events[f"exc_{horizon}"])], horizon, seeds,
                                match_month=match_month)
        if placebo.empty:
            continue
        grouped = placebo.groupby("signal")["placebo_mean"]
        for signal, row_index in out[out["horizon"].eq(horizon)].groupby("signal").groups.items():
            if signal not in grouped.groups:
                continue
            means = grouped.get_group(signal).to_numpy()
            observed = float(out.loc[row_index, "mean"].iloc[0])
            out.loc[row_index, f"placebo_mean{suffix}"] = float(means.mean())
            out.loc[row_index, f"placebo_diff{suffix}"] = observed - float(means.mean())
            out.loc[row_index, f"placebo_p{suffix}"] = float((1 + np.sum(means >= observed)) / (len(means) + 1))
            out.loc[row_index, f"placebo_seeds{suffix}"] = int(len(means))
    return out


# --------------------------------------------------------------------------- #
# Size, sector and market phase
# --------------------------------------------------------------------------- #
def size_terciles(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame,
                  shares: pd.DataFrame) -> pd.DataFrame:
    """Market-cap tercile cut points per calendar year from a mid-year cross-section."""
    dates = []
    for year in sorted(cal["date"].dt.year.unique()):
        candidates = cal.loc[(cal["date"].dt.year == year)
                             & (cal["date"] <= pd.Timestamp(year, 6, 30)), "date"]
        if not candidates.empty:
            dates.append(candidates.max())
    if not dates:
        return pd.DataFrame(columns=["year", "q33", "q66"])
    con.register("t235_june_df", pd.DataFrame({"date": pd.to_datetime(dates)}))
    try:
        cross = con.execute(
            """SELECT p.entity_id, p.date, p.close
               FROM px_daily p JOIN t235_june_df d ON d.date = p.date
               WHERE p.adj_close > 0"""
        ).df()
    finally:
        con.unregister("t235_june_df")
    cross["date"] = pd.to_datetime(cross["date"]).astype("datetime64[ns]")
    share_sorted = shares.assign(avail_date=lambda d: pd.to_datetime(d["avail_date"]).astype("datetime64[ns]"))
    share_sorted = share_sorted.sort_values("avail_date")
    merged = pd.merge_asof(
        cross.sort_values("date"), share_sorted,
        left_on="date", right_on="avail_date", by="entity_id", direction="backward")
    merged["mcap"] = merged["close"] * merged["shares"]
    merged = merged[merged["mcap"] > 0]
    merged["year"] = merged["date"].dt.year
    return pd.DataFrame([
        {"year": int(year), "q33": float(group["mcap"].quantile(1 / 3)),
         "q66": float(group["mcap"].quantile(2 / 3))}
        for year, group in merged.groupby("year")
    ])


def attach_groups(events: pd.DataFrame, con: duckdb.DuckDBPyConnection,
                  shares: pd.DataFrame, sectors: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    out = events.sort_values("date_known").copy()
    out["date_known"] = pd.to_datetime(out["date_known"]).astype("datetime64[ns]")
    share_frame = shares.assign(
        avail_date=lambda d: pd.to_datetime(d["avail_date"]).astype("datetime64[ns]")
    ).rename(columns={"entity_id": "company"}).sort_values("avail_date")
    merged = pd.merge_asof(out, share_frame, left_on="date_known", right_on="avail_date",
                           by="company", direction="backward")
    merged["mcap"] = merged["close"] * merged["shares"]
    out = merged.drop(columns=["avail_date"], errors="ignore")
    cuts = size_terciles(con, cal, shares)
    out["year"] = out["date_known"].dt.year
    out["size"] = "unknown"
    if not cuts.empty:
        cut_map = {int(row.year): (row.q33, row.q66) for row in cuts.itertuples()}
        for year, indexes in out.groupby("year").groups.items():
            if int(year) not in cut_map:
                continue
            q33, q66 = cut_map[int(year)]
            mcap = out.loc[indexes, "mcap"].to_numpy(dtype=float)
            out.loc[indexes, "size"] = np.where(
                ~np.isfinite(mcap), "unknown",
                np.where(mcap <= q33, "small", np.where(mcap <= q66, "mid", "large")))
    out = out.merge(sectors, on="company", how="left")
    counts = out["sector"].value_counts()
    keep = set(counts[counts >= THIN_SECTOR_EVENTS].index)
    out["sector"] = out["sector"].where(out["sector"].isin(keep), "Other")
    tri = con.execute(
        """SELECT date, tri FROM index_tri
           WHERE index_name = 'NIFTY 500' AND tri IS NOT NULL ORDER BY date"""
    ).df()
    tri["date"] = pd.to_datetime(tri["date"]).astype("datetime64[ns]")
    tri = tri.drop_duplicates("date").set_index("date").sort_index()
    mean200 = tri["tri"].rolling(PHASE_MEAN_SESSIONS, min_periods=PHASE_MEAN_SESSIONS).mean()
    ret12 = tri["tri"] / tri["tri"].shift(PHASE_RETURN_SESSIONS) - 1
    phase = pd.DataFrame({
        "phase_200dma": np.where(tri["tri"] > mean200, "above", "below"),
        "phase_12m": np.where(ret12 > 0, "up", "down"),
    }, index=tri.index).reset_index()
    out = out.merge(phase, left_on="date_known", right_on="date", how="left").drop(
        columns=["date"], errors="ignore")
    # The crossed regime the brief asks for: index above/below its 200-session mean x
    # 12-month return sign.
    out["phase_4"] = (out["phase_200dma"].fillna("na") + "_" + out["phase_12m"].fillna("na"))
    return out


# --------------------------------------------------------------------------- #
# Look-back: what fired before +-30% excess moves
# --------------------------------------------------------------------------- #
def moves_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Deduped +-30% 60-session excess moves (first crossing per 60-session episode)."""
    raw = con.execute(
        f"""SELECT entity_id AS company, date, i, exc_60_lag
            FROM t235_ret
            WHERE exc_60_lag IS NOT NULL
              AND (exc_60_lag >= {MOVE_PCT} OR exc_60_lag <= {-MOVE_PCT})"""
    ).df()
    raw["date"] = pd.to_datetime(raw["date"])
    raw["direction"] = np.where(raw["exc_60_lag"] > 0, "up", "down")
    raw["year"] = raw["date"].dt.year
    raw = raw.sort_values(["company", "direction", "i"]).reset_index(drop=True)
    keep = np.ones(len(raw), dtype=bool)
    for _, indexes in raw.groupby(["company", "direction"], sort=False).groups.items():
        positions = np.asarray(indexes)
        last = -10 ** 9
        for pos in positions:
            value = int(raw.at[pos, "i"])
            if value - last < MOVE_WINDOW:
                keep[pos] = False
            else:
                last = value
    return raw[keep][["company", "date", "direction", "i", "year"]].reset_index(drop=True)


def _has_in(sorted_values: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    if len(sorted_values) == 0:
        return np.zeros(np.shape(lo), dtype=bool)
    left = np.searchsorted(sorted_values, lo)
    right = np.searchsorted(sorted_values, hi, side="right")
    return right > left


def lookback_study(events: pd.DataFrame, moves: pd.DataFrame, sessions_by_year: dict,
                   seeds: int = PLACEBO_SEEDS) -> pd.DataFrame:
    """Per signal: recall and precision of +/-30% moves vs the same stocks' random
    dates in the same calendar year."""
    rng = np.random.default_rng(20261122)
    moves_by_entity_dir = {
        (company, direction): np.sort(group["i"].to_numpy())
        for (company, direction), group in moves.groupby(["company", "direction"])
    }
    rows: list[dict] = []
    for signal, sig_group in events.groupby("signal"):
        direction = str(sig_group["direction"].iloc[0])
        fire_by_entity = {company: np.sort(group["i"].to_numpy())
                          for company, group in sig_group.groupby("company")}
        matching = moves[moves["direction"].eq(direction)]
        hits, total, placebo_hits, placebo_total = 0, 0, 0, 0
        for company, move_group in matching.groupby("company"):
            fires = fire_by_entity.get(company, np.array([], dtype=np.int64))
            i_values = move_group["i"].to_numpy()
            hits += int(_has_in(fires, i_values - LOOKBACK_SESSIONS, i_values - 1).sum())
            total += len(i_values)
            for year, year_group in move_group.groupby("year"):
                sessions = sessions_by_year.get((company, int(year)))
                if sessions is None:
                    continue
                valid = sessions[sessions >= LOOKBACK_SESSIONS]
                if len(valid) == 0:
                    continue
                draws = valid[rng.integers(0, len(valid), size=(len(year_group), seeds))]
                placebo_hits += int(_has_in(fires, draws - LOOKBACK_SESSIONS, draws - 1).sum())
                placebo_total += draws.size
        precision_hits, precision_total, pp_hits, pp_total = 0, 0, 0, 0
        for company, fire_group in sig_group.groupby("company"):
            move_i = moves_by_entity_dir.get((company, direction), np.array([], dtype=np.int64))
            i_values = fire_group["i"].to_numpy()
            precision_hits += int(_has_in(move_i, i_values + 1, i_values + MOVE_WINDOW).sum())
            precision_total += len(i_values)
            for year, year_group in fire_group.groupby("year"):
                sessions = sessions_by_year.get((company, int(year)))
                if sessions is None:
                    continue
                valid = sessions[sessions <= sessions.max() - MOVE_WINDOW]
                if len(valid) == 0:
                    continue
                draws = valid[rng.integers(0, len(valid), size=(len(year_group), seeds))]
                pp_hits += int(_has_in(move_i, draws + 1, draws + MOVE_WINDOW).sum())
                pp_total += draws.size
        recall = hits / total if total else float("nan")
        recall_placebo = placebo_hits / placebo_total if placebo_total else float("nan")
        precision = precision_hits / precision_total if precision_total else float("nan")
        precision_placebo = pp_hits / pp_total if pp_total else float("nan")
        rows.append({
            "signal": signal, "direction": direction,
            "n_moves": total, "recall": recall, "recall_placebo": recall_placebo,
            "recall_lift": recall - recall_placebo if total else float("nan"),
            "n_firings": precision_total, "precision": precision,
            "precision_placebo": precision_placebo,
            "precision_lift": precision - precision_placebo if precision_total else float("nan"),
            "precision_p": _lift_p(precision, precision_placebo, precision_total),
        })
    return pd.DataFrame(rows)


def _lift_p(observed: float, placebo: float, n: int) -> float:
    """Two-sided normal p for an observed proportion against a placebo proportion."""
    if not all(np.isfinite(value) for value in (observed, placebo)) or n == 0:
        return float("nan")
    if not 0 < placebo < 1:
        return float("nan")
    se = math.sqrt(placebo * (1 - placebo) / n)
    if se == 0:
        return float("nan")
    return two_sided_p((observed - placebo) / se)


# --------------------------------------------------------------------------- #
# Pairs
# --------------------------------------------------------------------------- #
def pair_study(events: pd.DataFrame) -> pd.DataFrame:
    """Same-direction pairs whose firings lie within 30 sessions (first firing = event)."""
    rows: list[pd.DataFrame] = []
    for company, group in events.groupby("company"):
        per_signal = {key: sub.sort_values("i") for key, sub in group.groupby(["signal", "direction"])}
        keys = list(per_signal)
        for pos, a_key in enumerate(keys):
            for b_key in keys[pos + 1:]:
                if a_key[1] != b_key[1]:
                    continue
                a_frame, b_frame = per_signal[a_key], per_signal[b_key]
                first = a_frame["i"].to_numpy()
                second = b_frame["i"].to_numpy()
                order = np.searchsorted(second, first + 1)
                ok = order < len(second)
                ok[ok] &= second[order[ok]] <= first[ok] + PAIR_WINDOW
                if not ok.any():
                    continue
                selected = a_frame[ok]
                rows.append(pd.DataFrame({
                    "company": company,
                    "pair": f"{a_key[0]}+{b_key[0]}",
                    "signal_a": a_key[0], "signal_b": b_key[0], "direction": a_key[1],
                    "i": selected["i"].to_numpy(), "date_known": selected["date_known"].to_numpy(),
                    "sign": selected["sign"].to_numpy(),
                    **{f"exc_{h}": selected[f"exc_{h}"].to_numpy() for h in HORIZONS},
                }))
    if not rows:
        return pd.DataFrame(columns=["pair", "signal_a", "signal_b", "direction", "horizon", "n"])
    return pd.concat(rows, ignore_index=True)


def summarise_pairs(pairs: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Per pair x horizon: n, mean, median, hit, NW t, and each member's own mean."""
    if pairs.empty:
        return pairs
    cells = cell_stats(pairs, ["pair", "signal_a", "signal_b", "direction"])
    cells["pair"] = cells["signal_a"] + "+" + cells["signal_b"]
    own = cell_stats(events, ["signal", "direction"]).rename(
        columns={"signal": "signal_a", "mean": "mean_a", "n": "n_a",
                 "nw_t": "nw_t_a", "hit": "hit_a", "median": "median_a"})
    own_b = own.rename(columns={"signal_a": "signal_b", "mean_a": "mean_b", "n_a": "n_b",
                                "nw_t_a": "nw_t_b", "hit_a": "hit_b", "median_a": "median_b"})
    cells = cells.merge(own[["signal_a", "horizon", "mean_a", "n_a", "nw_t_a", "hit_a"]],
                        on=["signal_a", "horizon"], how="left")
    cells = cells.merge(own_b[["signal_b", "horizon", "mean_b", "n_b", "nw_t_b", "hit_b"]],
                        on=["signal_b", "horizon"], how="left")
    return cells


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run(out_dir: Path, signals_path: Path, snapshot: Path, start: str, end: str,
        seeds: int = PLACEBO_SEEDS) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    signals = pd.read_csv(signals_path, parse_dates=["date_known"])
    signals = signals[signals["date_known"].between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    if signals.empty:
        raise SystemExit(f"no signals in {signals_path} between {start} and {end}")
    print(f"  signals: {len(signals):,} rows, {signals['signal'].nunique()} kinds, "
          f"{signals['company'].nunique():,} companies")

    con = connect(snapshot)
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    try:
        build_returns(con, end)
        cal = con.execute("SELECT date, i FROM t235_cal ORDER BY i").df()
        cal["date"] = pd.to_datetime(cal["date"])
        events, dropped = event_returns(con, signals)
        print(f"  events with an entry session and price: {len(events):,} "
              f"({events['company'].nunique():,} companies, {dropped:,} dropped)")
        shares = load_shares(con, cal)
        sectors = load_sectors(con)
        enriched = attach_groups(events, con, shares, sectors, cal)

        main = cell_stats(enriched, ["signal"])
        main["direction"] = main["signal"].map(enriched.groupby("signal")["direction"].first())
        main = attach_placebo(main, con, enriched, seeds)
        main = attach_placebo(main, con, enriched, seeds, match_month=True, suffix="_month")
        print(f"  after-signal cells: {len(main):,}")

        groups: list[pd.DataFrame] = []
        for group_type, column in (("size", "size"), ("sector", "sector"),
                                   ("phase_200dma", "phase_200dma"),
                                   ("phase_12m", "phase_12m"), ("phase_4", "phase_4")):
            part = cell_stats(enriched, ["signal", column])
            if part.empty:
                continue
            part = part.rename(columns={column: "group"})
            if column == "size":
                # results_key starts in 2017-06, so events before the first share count
                # have no market cap; their "unknown" cells would duplicate the signal cell.
                part = part[part["group"].ne("unknown")]
                if part.empty:
                    continue
            part.insert(0, "group_type", group_type)
            groups.append(part)
        by_group = pd.concat(groups, ignore_index=True) if groups else pd.DataFrame()
        direction_map = enriched.groupby("signal")["direction"].first()
        if not by_group.empty:
            by_group["direction"] = by_group["signal"].map(direction_map)

        signed = enriched[[f"sign_{h}" for h in HORIZONS]].to_numpy(dtype=float)
        valid = np.isfinite(signed)
        peak = np.full(len(enriched), np.nan)
        any_valid = valid.any(axis=1)
        peak[any_valid] = np.asarray(HORIZONS)[np.where(valid, signed, -np.inf).argmax(axis=1)[any_valid]]
        enriched["peak_horizon"] = peak
        by_year = cell_stats(enriched, ["signal", "year"])
        if not by_year.empty:
            by_year["direction"] = by_year["signal"].map(direction_map)
        lead = (enriched.dropna(subset=["peak_horizon"])
                .groupby(["signal", "year"], as_index=False)["peak_horizon"].median()
                .rename(columns={"peak_horizon": "median_peak_horizon_sessions"}))
        by_year = by_year.merge(lead, on=["signal", "year"], how="left")
        print(f"  group cells: {len(by_group):,}; year cells: {len(by_year):,}")

        moves = moves_table(con)
        sessions = con.execute(
            """SELECT r.entity_id, r.i, c.date FROM t235_ret r
               JOIN t235_cal c ON c.i = r.i ORDER BY 1, 2"""
        ).df()
        sessions["date"] = pd.to_datetime(sessions["date"])
        sessions["year"] = sessions["date"].dt.year
        sessions_by_year = {(company, int(year)): group["i"].to_numpy()
                            for (company, year), group in sessions.groupby(["entity_id", "year"])}
        del sessions
        look = lookback_study(enriched, moves, sessions_by_year, seeds)
        print(f"  moves: {len(moves):,}; look-back rows: {len(look):,}")

        pairs = pair_study(enriched)
        pair_cells = summarise_pairs(pairs, enriched)
        if not pair_cells.empty:
            ranked = (pair_cells[pair_cells["horizon"].eq(60) & (pair_cells["n"] >= MIN_PAIR_N)]
                      .assign(abs_mean=lambda d: d["mean"].abs())
                      .sort_values("abs_mean", ascending=False).head(TOP_PAIRS))
            top_pairs = ranked["pair"].tolist()
            pair_cells["top_pair"] = pair_cells["pair"].isin(top_pairs)
            # Placebo for the selected pairs at the 60-session ranking horizon.
            pair_events = pairs[pairs["pair"].isin(top_pairs)].copy()
            pair_events["signal"] = pair_events["pair"]
            placebo = placebo_frame(con, pair_events, 60, seeds)
            if not placebo.empty:
                summary = placebo.groupby("signal")["placebo_mean"].mean()
                pair_cells["placebo_mean"] = np.where(
                    pair_cells["top_pair"] & pair_cells["horizon"].eq(60),
                    pair_cells["pair"].map(summary), np.nan)
            else:
                pair_cells["placebo_mean"] = np.nan
        else:
            pair_cells["top_pair"] = []
            pair_cells["placebo_mean"] = np.nan
        print(f"  pairs: {len(pairs):,} events; {len(pair_cells):,} cells")

        frames = [("after_signal", main), ("by_group", by_group), ("by_year", by_year),
                  ("pairs", pair_cells)]
        pooled = pd.concat([frame.assign(_table=name) for name, frame in frames if not frame.empty],
                           ignore_index=True)
        pooled["q_bh"] = bh_adjust(pooled["p_nw"])
        pooled["bh_pass"] = pooled["q_bh"] <= BH_Q
        for name, frame in frames:
            if frame.empty:
                continue
            block = pooled[pooled["_table"].eq(name)]
            frame["q_bh"] = block["q_bh"].to_numpy()
            frame["bh_pass"] = block["bh_pass"].to_numpy()

        main.to_csv(out_dir / "after_signal.csv", index=False)
        by_group.to_csv(out_dir / "by_group.csv", index=False)
        by_year.to_csv(out_dir / "by_year.csv", index=False)
        look.to_csv(out_dir / "lookback.csv", index=False)
        moves.to_csv(out_dir / "moves.csv", index=False)
        pair_cells.to_csv(out_dir / "pairs.csv", index=False)
        (signals.groupby(["signal", "direction"]).size().rename("firings").reset_index()
         .to_csv(out_dir / "event_counts.csv", index=False))
        print(f"  BH pass (q<=10%): {int(pooled['bh_pass'].sum())} of {len(pooled):,} cells")
        print(f"  wrote {out_dir}")
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-235 after-signal study")
    parser.add_argument("--out", default=".tmp/t235")
    parser.add_argument("--signals", default=None, help="flow_signal.csv path")
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--placebo-seeds", type=int, default=PLACEBO_SEEDS)
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    signals_path = Path(args.signals) if args.signals else out_dir / "flow_signal.csv"
    snapshot = Path(args.snapshot) if args.snapshot else default_snapshot()
    if args.end:
        end = args.end
    else:
        con = connect(snapshot)
        end = str(con.execute("SELECT max(date) FROM px_daily").fetchone()[0])
        con.close()
    run(out_dir, signals_path, snapshot, args.start, end, args.placebo_seeds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
