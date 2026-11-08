"""T-118: which point-in-time facts explain forward 6m / 12m / 24m excess returns.

Research prototype, not pipeline code. Reads the dated DuckDB snapshot read-only,
builds a monthly panel (universe x factors x forward total returns) and reports
rank-IC, quintile spread and Fama-MacBeth coefficients per horizon.

Point in time is the whole value of the study: a fact is usable only from the
first trading session on which it was public, and a filing published after
15:30 IST is usable from the next session.

    python -m reality_engine.research.factor_weights --out .tmp/t118

Outputs (only under --out): factor_ic.csv, fama_macbeth.csv, coverage_by_year.csv,
T-118_factor_weights.html.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from datetime import timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
CLOSE_IST_SECONDS = 15 * 3600 + 30 * 60  # 15:30 IST; a filing after this counts next session
SNAPSHOT_NAME = "truth_2026-11-04.duckdb"
BENCHMARK = "NIFTY 500"
MIN_VALUE_CRORE = 1.0
MIN_HISTORY_SESSIONS = 250
MIN_SECTOR_NAMES = 5  # names a sector needs before its median multiple is used
PEAK_WINDOW_MONTHS = 60
PEAK_MIN_MONTHS = 24

HORIZONS = {"6m": 126, "12m": 252, "24m": 504}
NW_LAGS = {"6m": 5, "12m": 11, "24m": 23}

# factor -> human label. Every one is either in the snapshot or derived from a
# filing we hold; the report lists the factors the ticket asked for that are not.
FACTORS = {
    "ttm_rev_yoy": "TTM revenue YoY",
    "ttm_pat_yoy": "TTM PAT YoY",
    "q_pat_yoy": "latest-quarter PAT YoY",
    "pat_accel": "PAT growth acceleration",
    "op_margin": "TTM operating margin",
    "op_margin_chg": "TTM operating margin YoY change",
    "fin_cost_to_rev": "TTM finance cost / revenue",
    "earnings_yield": "TTM earnings yield",
    "sales_yield": "TTM sales yield",
    "ps_ratio": "log P/S (market cap / TTM sales)",
    "ps_chg_3m": "log P/S change, 3 months",
    "ps_chg_6m": "log P/S change, 6 months",
    "ps_chg_12m": "log P/S change, 12 months",
    "pe_ratio": "log P/E (positive TTM PAT only)",
    "pe_chg_3m": "log P/E change, 3 months",
    "pe_chg_6m": "log P/E change, 6 months",
    "pe_chg_12m": "log P/E change, 12 months",
    "rerating_share_12m": "12m price move from P/S re-rating (share)",
    "sales_share_12m": "12m price move from sales growth (share)",
    "sector_ps_chg_12m": "sector median log P/S change, 12 months",
    "sector_ps_chg_36m": "sector median log P/S change, 36 months",
    "sector_pe_chg_12m": "sector median log P/E change, 12 months",
    "sector_pe_chg_36m": "sector median log P/E change, 36 months",
    "ps_vs_sector": "log P/S minus sector median",
    "op_margin_pctile": "TTM operating margin percentile, own 5 years",
    "pat_pctile": "TTM PAT percentile, own 5 years",
    "peak_growth_trap": "PAT growth top tercile x margin percentile > 80%",
    "promoter_chg_1q": "promoter % change, 1 quarter (pp)",
    "promoter_chg_4q": "promoter % change, 4 quarters (pp)",
    "insider_net_to_mcap": "insider net buy / market cap, prior 3 months",
    "mom_12_1": "12-1 month momentum",
    "reversal_1m": "1-month reversal",
    "vol_12m": "12-month volatility",
    "size": "log market cap",
    "delivery_3m": "delivery % 3-month mean",
}
GROWTH_FACTORS = ["ttm_rev_yoy", "ttm_pat_yoy", "q_pat_yoy", "pat_accel"]


# --------------------------------------------------------------------------- #
# Point in time
# --------------------------------------------------------------------------- #
def pit_sessions(known_at_utc: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """First trading session on which each UTC timestamp was usable.

    Same session when published at or before 15:30 IST on a trading day, the next
    session otherwise (weekends and holidays included). NaT past the last session.
    """
    src = pd.Series(known_at_utc)
    ts = pd.to_datetime(src, utc=True, errors="coerce")
    ist = ts.dt.tz_convert(IST)
    day = ist.dt.tz_localize(None).dt.normalize().to_numpy(dtype="datetime64[ns]")
    secs = ist.dt.hour.to_numpy() * 3600 + ist.dt.minute.to_numpy() * 60 + ist.dt.second.to_numpy()
    after_close = secs > CLOSE_IST_SECONDS
    days = pd.DatetimeIndex(sessions).to_numpy(dtype="datetime64[ns]")
    pos = np.searchsorted(days, day, side="left")
    pos = np.minimum(pos, len(days))
    on_session = (pos < len(days)) & (days[np.minimum(pos, len(days) - 1)] == day)
    pos = pos + (after_close & on_session).astype(np.int64)
    out = np.full(len(day), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    ok = pos < len(days)
    out[ok] = days[pos[ok]]
    return pd.Series(pd.to_datetime(out), index=src.index)


def ist_date(ts: pd.Series) -> pd.Series:
    """UTC timestamps -> the calendar date in IST (naive)."""
    s = pd.to_datetime(ts, utc=True, errors="coerce")
    return s.dt.tz_convert(IST).dt.tz_localize(None).dt.normalize()


def utc_ns(ts: pd.Series) -> pd.Series:
    """UTC timestamps as float nanoseconds (pandas 3 datetimes are microsecond based)."""
    s = pd.to_datetime(pd.Series(ts), utc=True, errors="coerce").astype("datetime64[ns, UTC]")
    return s.astype("int64").astype(float)


def ns_to_date(values: pd.Series) -> pd.Series:
    """Float nanoseconds -> the IST calendar date."""
    return ist_date(pd.to_datetime(values, unit="ns", utc=True))


# --------------------------------------------------------------------------- #
# Statistics helpers (numpy only: scipy is not installed in this checkout)
# --------------------------------------------------------------------------- #
def newey_west_tstat(x, lags: int) -> float:
    """t-stat of the mean with a Bartlett-kernel (Newey-West) variance."""
    v = np.asarray(pd.Series(x).dropna(), dtype=float)
    n = len(v)
    if n < 3:
        return float("nan")
    mu = v.mean()
    e = v - mu
    var = float(e @ e) / n
    lags = max(1, min(int(lags), n - 1))
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        var += 2.0 * weight * float(e[lag:] @ e[:-lag]) / n
    if var <= 0:
        return float("nan")
    return float(mu / np.sqrt(var / n))


def spearman_ic(x, y, min_n: int = 20) -> float:
    """Rank correlation of two same-length series; NaN when the sample is useless."""
    s = pd.DataFrame({"x": pd.Series(x).astype(float).to_numpy(), "y": pd.Series(y).astype(float).to_numpy()})
    s = s.dropna()
    if len(s) < min_n or s["x"].nunique() < 2 or s["y"].nunique() < 5:
        return float("nan")
    return float(s["x"].rank().corr(s["y"].rank()))


def monthly_ic(frame: pd.DataFrame, factor: str, target: str) -> pd.Series:
    """Spearman IC per rebalance date."""
    d = frame[["date", factor, target]].dropna()
    if d.empty:
        return pd.Series(dtype=float)
    return d.groupby("date", sort=True).apply(lambda g: spearman_ic(g[factor], g[target]))


def winsor_z(panel: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Winsorise at 1/99 within date, then z-score within date (NaN-safe)."""
    out = panel.copy()
    key = out["date"]
    for c in cols:
        x = pd.to_numeric(out[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
        low = x.groupby(key).transform(lambda s: s.quantile(0.01))
        high = x.groupby(key).transform(lambda s: s.quantile(0.99))
        x = x.clip(low, high)
        mean = x.groupby(key).transform("mean")
        sd = x.groupby(key).transform("std")
        out[c] = x
        out[c + "_z"] = (x - mean) / sd.replace(0.0, np.nan)
    return out


def sector_z(panel: pd.DataFrame, cols: list[str], min_names: int = 5) -> pd.DataFrame:
    """z within (date, sector); NaN where a sector has fewer than `min_names` names."""
    out = panel.copy()
    key = [out["date"], out["sector"].fillna("<none>")]
    for c in cols:
        x = pd.to_numeric(out[c], errors="coerce")
        mean = x.groupby(key, observed=True).transform("mean")
        sd = x.groupby(key, observed=True).transform("std")
        n = x.notna().astype(float).groupby(key, observed=True).transform("sum")
        out[c + "_sn"] = ((x - mean) / sd.replace(0.0, np.nan)).where(n >= min_names)
    return out


# --------------------------------------------------------------------------- #
# Facts: one basis series per company, quarters, TTM with its availability date
# --------------------------------------------------------------------------- #
def pick_basis(fin: pd.DataFrame) -> pd.DataFrame:
    """Keep exactly one reporting basis family per company (never mix).

    Consolidated when the company files it at least as often as standalone
    (Standalone and Non-Consolidated are the same family), else standalone.
    """
    fam = pd.Series(
        np.where(fin["consolidated"].astype("string").eq("Consolidated"), "Consolidated", "Standalone"),
        index=fin.index,
    )
    work = fin.assign(basis=fam)
    counts = work.groupby(["entity_id", "basis"]).size().unstack(fill_value=0)
    if counts.empty:
        raise ValueError("results_key has no usable consolidated/standalone flag")
    cons = counts.get("Consolidated", pd.Series(0, index=counts.index))
    stand = counts.get("Standalone", pd.Series(0, index=counts.index))
    prefer = pd.Series(np.where(cons >= stand, "Consolidated", "Standalone"), index=counts.index)
    return work[work["basis"].eq(work["entity_id"].map(prefer))].copy()


def fiscal_key(period_end: pd.Series, fy_start: pd.Series) -> pd.Series:
    """Fiscal-year label; falls back to the Indian fiscal year of period_end."""
    derived = np.where(
        period_end.dt.month >= 4, period_end.dt.year, period_end.dt.year - 1
    )
    return fy_start.astype("string").fillna(pd.Series(derived, index=period_end.index).astype("string"))


def quarter_facts(fin: pd.DataFrame) -> pd.DataFrame:
    """Quarter series -> TTM facts, each carrying the date its inputs were public.

    A quarter's value is the reported quarter figure, else the YTD delta
    (ytd_p - ytd_{p-1} inside one fiscal year), else the first-quarter YTD.
    A TTM needs four consecutive quarters (span 250-290 days) and the YoY
    columns need eight (620-660 days). Availability = latest known_at of inputs.
    """
    need = ["entity_id", "period_end", "fy_start", "known_at_utc"]
    d = fin.dropna(subset=need).copy()
    d["period_end"] = pd.to_datetime(d["period_end"])
    d["known_at_utc"] = pd.to_datetime(d["known_at_utc"], utc=True)
    d = d.sort_values(["entity_id", "period_end", "known_at_utc"]).drop_duplicates(
        ["entity_id", "period_end"], keep="last"
    )
    d = d.sort_values(["entity_id", "period_end"]).reset_index(drop=True)
    d["fy"] = fiscal_key(d["period_end"], d["fy_start"])
    ent = d["entity_id"]

    def prev(col, k=1):
        return d.groupby("entity_id", sort=False)[col].shift(k)

    def roll(col, window, how):
        return d.groupby("entity_id", sort=False)[col].transform(
            lambda x: getattr(x.rolling(window, min_periods=window), how)()
        )

    same_fy = prev("fy").astype("string").eq(d["fy"].astype("string"))
    rev_q = d["rev"].fillna((d["ytd_rev"] - prev("ytd_rev")).where(same_fy))
    rev_q = rev_q.fillna(d["ytd_rev"].where(~same_fy))
    pat_q = d["pat"].fillna((d["ytd_pat"] - prev("ytd_pat")).where(same_fy))
    pat_q = pat_q.fillna(d["ytd_pat"].where(~same_fy))

    fin_cost = d["fin_cost"].fillna(0.0)
    dep = d["dep"].fillna(0.0)
    d["rev_q"] = rev_q
    d["pat_q"] = pat_q
    d["op_q"] = (rev_q - (d["expense"] - fin_cost - dep)).where(d["expense"].notna())

    ttm_rev = roll("rev_q", 4, "sum")
    ttm_pat = roll("pat_q", 4, "sum")
    ttm_op = roll("op_q", 4, "sum")
    ttm_fin = roll("fin_cost", 4, "sum")
    ttm_rev_prev = ttm_rev.groupby(ent, sort=False).shift(4)
    ttm_pat_prev = ttm_pat.groupby(ent, sort=False).shift(4)
    ttm_op_prev = ttm_op.groupby(ent, sort=False).shift(4)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # NaT differences in short histories
        span4 = (d["period_end"] - prev("period_end", 3)).dt.days
        span8 = (d["period_end"] - prev("period_end", 7)).dt.days
    ok4 = span4.between(250, 290)
    ok8 = span8.between(620, 660)

    known_ns = utc_ns(d["known_at_utc"])
    d["known_ns"] = known_ns
    avail4 = roll("known_ns", 4, "max")
    avail8 = roll("known_ns", 8, "max")
    avail = avail8.where(ok8, avail4)

    d["ttm_rev"] = ttm_rev.where(ok4)
    d["ttm_rev_prev"] = ttm_rev_prev.where(ok4 & ok8)
    d["ttm_pat"] = ttm_pat.where(ok4)
    d["ttm_pat_prev"] = ttm_pat_prev.where(ok4 & ok8)
    d["ttm_op"] = ttm_op.where(ok4)
    d["ttm_op_prev"] = ttm_op_prev.where(ok4 & ok8)
    d["ttm_fin"] = ttm_fin.where(ok4)

    pat_yoy = (pat_q / prev("pat_q", 4) - 1.0).where(pat_q > 0)
    d["q_pat_yoy"] = pat_yoy.where(ok4)
    d["pat_accel"] = pat_yoy - pat_yoy.groupby(ent, sort=False).shift(1)
    d["ttm_rev_yoy"] = (ttm_rev / ttm_rev_prev - 1.0).where(ok4 & ok8 & (ttm_rev_prev > 0))
    d["ttm_pat_yoy"] = (ttm_pat / ttm_pat_prev - 1.0).where(ok4 & ok8 & (ttm_pat_prev > 0))

    fv = d["fv"].where(d["fv"] > 0)
    d["shares"] = d["pu"] / fv
    d["avail_date"] = ns_to_date(avail)

    keep = [
        "entity_id", "period_end", "avail_date", "ttm_rev", "ttm_rev_prev", "ttm_rev_yoy",
        "ttm_pat", "ttm_pat_prev", "ttm_pat_yoy", "q_pat_yoy", "pat_accel", "ttm_op",
        "ttm_op_prev", "ttm_fin", "shares",
    ]
    return d[keep].dropna(subset=["avail_date"]).reset_index(drop=True)


def promoter_history(shp: pd.DataFrame) -> pd.DataFrame:
    """Quarterly promoter %, with 1q and 4q changes and their availability date."""
    s = shp.dropna(subset=["entity_id", "quarter_end", "known_at_utc", "promoter_pct"]).copy()
    s["quarter_end"] = pd.to_datetime(s["quarter_end"])
    s["known_at_utc"] = pd.to_datetime(s["known_at_utc"], utc=True)
    s = s.sort_values(["entity_id", "quarter_end", "known_at_utc"]).drop_duplicates(
        ["entity_id", "quarter_end"], keep="last"
    )
    s = s.sort_values(["entity_id", "quarter_end"]).reset_index(drop=True)
    ent = s["entity_id"]
    s["promoter_chg_1q"] = s["promoter_pct"] - s.groupby("entity_id", sort=False)["promoter_pct"].shift(1)
    s["promoter_chg_4q"] = s["promoter_pct"] - s.groupby("entity_id", sort=False)["promoter_pct"].shift(4)
    known = utc_ns(s["known_at_utc"])
    avail = known.groupby(ent, sort=False).transform(lambda x: x.rolling(5, min_periods=1).max())
    s["avail_date"] = ns_to_date(avail)
    return s[["entity_id", "quarter_end", "avail_date", "promoter_pct", "promoter_chg_1q", "promoter_chg_4q"]]


def attach_asof(panel: pd.DataFrame, facts: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Attach the newest fact row whose availability date is on/before the rebalance."""
    left = panel.assign(date=pd.to_datetime(panel["date"]).astype("datetime64[ns]"))
    left = left.sort_values(["date", "entity_id"]).reset_index(drop=True)  # merge_asof needs the on-key sorted
    right = facts.dropna(subset=["avail_date"]).assign(
        avail_date=lambda f: pd.to_datetime(f["avail_date"]).astype("datetime64[ns]")
    )
    right = right.sort_values(["avail_date", "entity_id"]).reset_index(drop=True)
    merged = pd.merge_asof(
        left,
        right[["entity_id", "avail_date", *cols]],
        left_on="date",
        right_on="avail_date",
        by="entity_id",
        direction="backward",
    )
    return merged.drop(columns=["avail_date"]).sort_values(["date", "entity_id"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Panel from the DuckDB snapshot
# --------------------------------------------------------------------------- #
def default_snapshot() -> Path:
    root = os.environ.get("REALITY_DATA_ROOT")
    candidates = []
    if root:
        candidates.append(Path(root) / "snapshots" / SNAPSHOT_NAME)
    candidates.append(
        Path(r"C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data/snapshots") / SNAPSHOT_NAME
    )
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"{SNAPSHOT_NAME} not found in {[str(c) for c in candidates]}")


def connect(snapshot: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(snapshot), read_only=True)
    con.execute("SET memory_limit='5GB'")
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    return con


def _isin_entity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        "SELECT isin, any_value(entity_id) AS entity_id FROM px_daily WHERE isin IS NOT NULL GROUP BY isin"
    ).df()


def build_price_panel(con: duckdb.DuckDBPyConnection, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Universe + price factors per rebalance date, plus the trading calendar.

    Universe: a price that day, median daily traded value over the prior 60
    sessions >= Rs 1 crore, >= 250 sessions of history. Forward returns join on
    the session index, so a company with no price on the horizon date gets no
    target (dropped, never padded).
    """
    statements = [
        """CREATE OR REPLACE TEMP TABLE t118_pxp AS
           SELECT entity_id, date, close, adj_close, tr_close, value_inr, delivery_pct, isin, symbol
           FROM (SELECT *, row_number() OVER (PARTITION BY entity_id, date ORDER BY (exch = 'NSE') DESC) rn
                 FROM px_daily) WHERE rn = 1""",
        """CREATE OR REPLACE TEMP TABLE t118_cal AS
           SELECT date, CAST(row_number() OVER (ORDER BY date) AS BIGINT) AS i
           FROM (SELECT DISTINCT date FROM px_daily WHERE exch = 'NSE')""",
        """CREATE OR REPLACE TEMP TABLE t118_pxi AS
           SELECT p.entity_id, p.date, c.i, p.close, p.adj_close, p.tr_close, p.value_inr,
                  p.delivery_pct, p.isin, p.symbol
           FROM t118_pxp p JOIN t118_cal c USING (date)""",
        f"""CREATE OR REPLACE TEMP TABLE t118_rebal AS
            SELECT date, i FROM (
              SELECT date, i, row_number() OVER (PARTITION BY date_trunc('month', date) ORDER BY date DESC) m
              FROM t118_cal WHERE date BETWEEN DATE '{start}' AND DATE '{end}') WHERE m = 1""",
        """CREATE OR REPLACE TEMP TABLE t118_px AS
           SELECT entity_id, date, i, isin, symbol, close, adj_close, tr_close,
                  med_value_60, n_hist_250,
                  (lag(adj_close, 21) OVER w / lag(adj_close, 252) OVER w) - 1 AS mom_12_1,
                  (lag(adj_close, 21) OVER w / adj_close) - 1 AS reversal_1m,
                  lag(adj_close, 252) OVER w AS adj_close_252,
                  stddev_samp(dret) OVER (PARTITION BY entity_id ORDER BY i
                                          ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS vol_12m,
                  avg(delivery_pct) OVER (PARTITION BY entity_id ORDER BY i
                                          ROWS BETWEEN 62 PRECEDING AND CURRENT ROW) AS delivery_3m
           FROM (SELECT entity_id, date, i, isin, symbol, close, adj_close, tr_close, delivery_pct,
                        quantile_cont(value_inr, 0.5) OVER (PARTITION BY entity_id ORDER BY i
                                                            ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS med_value_60,
                        count(adj_close) OVER (PARTITION BY entity_id ORDER BY i
                                               ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS n_hist_250,
                        ln(adj_close) - ln(lag(adj_close, 1) OVER w) AS dret
                 FROM t118_pxi WINDOW w AS (PARTITION BY entity_id ORDER BY i))
           WINDOW w AS (PARTITION BY entity_id ORDER BY i)""",
        f"""CREATE OR REPLACE TEMP TABLE t118_univ AS
            SELECT r.date, p.* EXCLUDE (date)
            FROM t118_px p JOIN t118_rebal r ON r.i = p.i
            WHERE p.adj_close > 0
              AND p.med_value_60 >= {MIN_VALUE_CRORE * 1e7}
              AND p.n_hist_250 >= {MIN_HISTORY_SESSIONS}""",
        f"""CREATE OR REPLACE TEMP TABLE t118_bmi AS
            SELECT c.i, t.tri FROM index_tri t JOIN t118_cal c ON c.date = CAST(t.date AS DATE)
            WHERE t.index_name = '{BENCHMARK}' AND t.tri IS NOT NULL""",
    ]
    for sql in statements:
        con.execute(sql)

    cal = con.execute("SELECT date, i FROM t118_cal ORDER BY i").df()
    univ = con.execute(
        """SELECT date, entity_id, isin, symbol, close, adj_close, adj_close_252, tr_close,
                  med_value_60, n_hist_250, mom_12_1, reversal_1m, vol_12m, delivery_3m
           FROM t118_univ ORDER BY date, entity_id"""
    ).df()

    for h in HORIZONS.values():
        fwd = con.execute(
            f"""SELECT u.date, u.entity_id,
                       p1.tr_close / u.tr_close - 1.0 AS tr_ret,
                       b1.tri / b0.tri - 1.0 AS bm_ret
                FROM t118_univ u
                JOIN t118_pxi p1 ON p1.entity_id = u.entity_id AND p1.i = u.i + {h}
                JOIN t118_bmi b0 ON b0.i = u.i
                JOIN t118_bmi b1 ON b1.i = u.i + {h}"""
        ).df()
        univ = univ.merge(
            fwd.assign(excess= fwd["tr_ret"] - fwd["bm_ret"])[["date", "entity_id", "excess"]],
            on=["date", "entity_id"],
            how="left",
        ).rename(columns={"excess": f"excess_{h}"})

    univ["date"] = pd.to_datetime(univ["date"])
    cal["date"] = pd.to_datetime(cal["date"])
    return univ, cal


def build_facts(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Filing facts per company-quarter, with their PIT availability date."""
    raw = con.execute(
        """SELECT r.trading_isin, r.consolidated, r.period_end, r.fy_start, r.known_at_utc,
                  r.RevenueFromOperations AS rev, r.ProfitLossForPeriod AS pat,
                  r.InterestEarned AS interest, r.Expenses AS expense,
                  r.FinanceCosts AS fin_cost,
                  r.DepreciationDepletionAndAmortisationExpense AS dep,
                  r.ytd_RevenueFromOperations AS ytd_rev, r.ytd_ProfitLossForPeriod AS ytd_pat,
                  r.PaidUpValueOfEquityShareCapital AS pu, r.FaceValueOfEquityShareCapital AS fv
           FROM results_key r WHERE r.period_end >= '2016-01-01'"""
    ).df()
    raw = raw.merge(_isin_entity(con), left_on="trading_isin", right_on="isin", how="left")
    unmapped = int(raw["entity_id"].isna().sum())
    raw = raw.dropna(subset=["entity_id", "period_end", "known_at_utc"])
    raw["rev"] = raw["rev"].fillna(raw["interest"])  # a bank reports interest earned, not revenue
    raw["avail_date"] = pit_sessions(raw["known_at_utc"], pd.DatetimeIndex(cal["date"])).to_numpy()
    raw["fy_start"] = raw["fy_start"].astype(str)
    chosen = pick_basis(raw)
    return quarter_facts(chosen), {
        "filings": int(len(raw)),
        "unmapped_isin": unmapped,
        "chosen_basis_rows": int(len(chosen)),
    }


def build_ownership(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Promoter series and 3-month insider net buy per (rebalance date, company)."""
    isin_map = _isin_entity(con)
    shp = con.execute("SELECT isin, quarter_end, promoter_pct, known_at_utc FROM shp_index").df()
    shp = shp.merge(isin_map, on="isin", how="inner")
    promoter = promoter_history(shp)

    ins = con.execute(
        """SELECT symbol, known_at_utc, transaction_type, securities_value
           FROM nse_insider
           WHERE known_at_utc IS NOT NULL AND securities_value > 0
             AND transaction_type IN ('Buy', 'Sell')
             AND TRY_CAST(intimation_date AS DATE) >= DATE '2018-10-01'"""
    ).df()
    hist = con.execute(
        """SELECT symbol, isin, TRY_CAST(first_date AS DATE) AS first_date,
                  TRY_CAST(last_date AS DATE) AS last_date, n_days
           FROM symbol_isin_history"""
    ).df()
    ins = ins.merge(hist, on="symbol", how="inner")
    trade_date = ist_date(ins["known_at_utc"])
    ins = ins[(trade_date >= ins["first_date"]) & (trade_date <= ins["last_date"])]
    ins = ins.sort_values("n_days", ascending=False).drop_duplicates(["symbol", "known_at_utc", "securities_value"])
    ins = ins.merge(isin_map, on="isin", how="inner")
    ins["avail_date"] = pit_sessions(ins["known_at_utc"], pd.DatetimeIndex(cal["date"])).to_numpy()
    ins["net_value"] = np.where(ins["transaction_type"].eq("Buy"), ins["securities_value"], -ins["securities_value"])
    events = ins.dropna(subset=["avail_date", "entity_id"])[["entity_id", "avail_date", "net_value"]].copy()
    events["avail_date"] = pd.to_datetime(events["avail_date"])
    con.register("t118_ins_ev", events)
    try:
        insider = con.execute(
            """SELECT r.date, e.entity_id, sum(e.net_value) AS insider_net_3m
               FROM t118_ins_ev e JOIN t118_rebal r
                 ON e.avail_date <= r.date AND e.avail_date > r.date - INTERVAL 91 DAY
               GROUP BY 1, 2"""
        ).df()
    finally:
        con.unregister("t118_ins_ev")
    insider["date"] = pd.to_datetime(insider["date"])
    return promoter, insider


def build_sectors(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    ind = con.execute("SELECT isin, sector FROM company_industry WHERE sector IS NOT NULL").df()
    out = ind.merge(_isin_entity(con), on="isin", how="inner").drop_duplicates("entity_id")
    return out[["entity_id", "sector"]]


def rerating_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """Re-rating / discovery factors (Shivam, 8 Nov).

    P/S and P/E levels are market cap over the TTM figure *known on that date*
    (so a change includes newly reported revenue/earnings). Changes are log
    ratios over a 3/6/12-month panel lag, admitted only when the lag really is
    3/6/12 months. P/E exists only for positive TTM PAT. The 12-month price move
    splits into sales growth and P/S re-rating; their two shares sum to 1 except
    for share issuance and dividends.
    """
    out = panel.sort_values(["entity_id", "date"]).copy()
    mcap = out["shares"] * out["close"]
    ps = (mcap / out["ttm_rev"]).where((mcap > 0) & (out["ttm_rev"] > 0))
    pe = (mcap / out["ttm_pat"]).where((mcap > 0) & (out["ttm_pat"] > 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        out["ps_ratio"] = np.log(ps)
        out["pe_ratio"] = np.log(pe)

    ent = out["entity_id"]

    def lagged(col: str, lag: int):
        return out.groupby("entity_id", sort=False)[col].shift(lag)

    for months, low, high in ((3, 75, 105), (6, 165, 200), (12, 330, 400)):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # NaT differences in short histories
            gap = (out["date"] - lagged("date", months)).dt.days
        ok = gap.between(low, high)
        out[f"ps_chg_{months}m"] = (out["ps_ratio"] - lagged("ps_ratio", months)).where(ok)
        out[f"pe_chg_{months}m"] = (out["pe_ratio"] - lagged("pe_ratio", months)).where(ok)

    px12 = np.log(out["adj_close"] / out["adj_close_252"])
    with np.errstate(divide="ignore", invalid="ignore"):
        sales12 = np.log(out["ttm_rev"] / lagged("ttm_rev", 12))
    out["px_log_chg_12m"] = px12  # reporting columns for the sector split, not factors
    out["sales_log_chg_12m"] = sales12.where(out["ttm_rev"] > 0)
    denom = px12.where(px12.abs() >= 0.02)  # a near-flat price cannot be split into shares
    out["rerating_share_12m"] = out["ps_chg_12m"] / denom
    out["sales_share_12m"] = out["sales_log_chg_12m"] / denom
    return out.sort_values(["date", "entity_id"]).reset_index(drop=True)


def sector_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """Sector re-rating and the company's position inside its own history (Shivam, 8 Nov).

    (d) The sector's median log P/S (and median log P/E over names with positive
    earnings) each date, over at least MIN_SECTOR_NAMES names, and its 12- and
    36-month change. Both are the same number for every name in the sector that
    month, so their IC is a between-sector effect and their sector-neutral z is
    undefined (NaN). `ps_vs_sector` is company-specific.
    (e) TTM operating margin and TTM PAT as a percentile of the company's own
    trailing five years (60 monthly rows, at least PEAK_MIN_MONTHS), plus the
    "growth still in the top tercile at a peak margin" interaction.
    """
    out = panel.sort_values(["date", "entity_id"]).copy()
    grp = out.groupby(["date", "sector"], observed=True)
    out["sector_ps_median"] = grp["ps_ratio"].transform("median").where(
        grp["ps_ratio"].transform("count") >= MIN_SECTOR_NAMES
    )
    out["sector_pe_median"] = grp["pe_ratio"].transform("median").where(
        grp["pe_ratio"].transform("count") >= MIN_SECTOR_NAMES
    )
    out["ps_vs_sector"] = out["ps_ratio"] - out["sector_ps_median"]

    smed = (
        out.groupby(["date", "sector"], observed=True)
        .agg(ps=("sector_ps_median", "first"), pe=("sector_pe_median", "first"))
        .reset_index()
        .sort_values(["sector", "date"])
    )
    for col in ("ps", "pe"):
        for months, low, high in ((12, 330, 400), (36, 1040, 1160)):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # NaT differences
                gap = (smed["date"] - smed.groupby("sector", sort=False)["date"].shift(months)).dt.days
            change = smed[col] - smed.groupby("sector", sort=False)[col].shift(months)
            smed[f"sector_{col}_chg_{months}m"] = change.where(gap.between(low, high))
    keep = ["date", "sector", "sector_ps_chg_12m", "sector_ps_chg_36m",
            "sector_pe_chg_12m", "sector_pe_chg_36m"]
    out = out.merge(smed[keep], on=["date", "sector"], how="left")

    out = out.sort_values(["entity_id", "date"])
    for col, name in (("op_margin", "op_margin_pctile"), ("ttm_pat", "pat_pctile")):
        out[name] = out.groupby("entity_id", sort=False)[col].transform(
            lambda s: s.rolling(PEAK_WINDOW_MONTHS, min_periods=PEAK_MIN_MONTHS).rank(pct=True)
        )
    out = out.sort_values(["date", "entity_id"]).reset_index(drop=True)
    tercile = out.groupby("date")["q_pat_yoy"].transform(
        lambda s: pd.qcut(s, 3, labels=False, duplicates="drop") if s.notna().sum() >= 30 else np.nan
    )
    known = tercile.notna() & out["op_margin_pctile"].notna() & out["q_pat_yoy"].notna()
    hot = (tercile == 2) & (out["op_margin_pctile"] > 0.80)
    out["peak_growth_trap"] = np.where(known, hot.astype(float), np.nan)
    return out


def sector_split(panel: pd.DataFrame) -> pd.DataFrame:
    """(f) the 12-month price move split into sales growth and P/S re-rating, by sector.

    Pooled over every company-month and repeated for the latest rebalance date, so a
    sector whose multiple compressed while earnings grew is visible.
    """
    latest = panel["date"].max()
    frames = []
    for label, sub in (("pooled", panel), (str(latest.date()), panel[panel["date"] == latest])):
        rows = []
        sub = sub.dropna(subset=["sales_share_12m"])
        for sector, g in sub.groupby("sector", observed=True):
            rows.append(
                {
                    "window": label,
                    "sector": sector,
                    "names": int(len(g)),
                    "price_12m_log": float(g["px_log_chg_12m"].mean()),
                    "sales_12m_log": float(g["sales_log_chg_12m"].mean()),
                    "ps_12m_log": float(g["ps_chg_12m"].mean()),
                    "sales_share": float(g["sales_share_12m"].mean()),
                    "rerating_share": float(g["rerating_share_12m"].mean()),
                }
            )
        frames.append(pd.DataFrame(rows))
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["window", "rerating_share"], ascending=[True, True]).reset_index(drop=True)


def build_panel(con: duckdb.DuckDBPyConnection, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    """Full monthly panel: universe x price/fundamental/ownership factors x targets."""
    price, cal = build_price_panel(con, start, end)
    facts, fact_meta = build_facts(con, cal)
    promoter, insider = build_ownership(con, cal)
    sectors = build_sectors(con)

    panel = attach_asof(
        price,
        facts,
        ["ttm_rev", "ttm_rev_prev", "ttm_rev_yoy", "ttm_pat", "ttm_pat_prev", "ttm_pat_yoy",
         "q_pat_yoy", "pat_accel", "ttm_op", "ttm_op_prev", "ttm_fin", "shares", "period_end"],
    )
    panel = attach_asof(panel, promoter, ["promoter_pct", "promoter_chg_1q", "promoter_chg_4q", "quarter_end"])
    panel = panel.merge(insider, on=["date", "entity_id"], how="left")
    panel = panel.merge(sectors, on="entity_id", how="left")

    mcap = panel["shares"] * panel["close"]
    panel["size"] = np.log(mcap.where(mcap > 0))
    panel["earnings_yield"] = (panel["ttm_pat"] / panel["shares"]) / panel["close"]
    panel["sales_yield"] = (panel["ttm_rev"] / panel["shares"]) / panel["close"]
    panel["insider_net_to_mcap"] = panel["insider_net_3m"] / mcap
    panel["op_margin"] = panel["ttm_op"] / panel["ttm_rev"]
    panel["op_margin_chg"] = panel["op_margin"] - panel["ttm_op_prev"] / panel["ttm_rev_prev"]
    panel["fin_cost_to_rev"] = panel["ttm_fin"] / panel["ttm_rev"]

    # margin factors only for non-financials: a bank's "expenses" are not COGS
    is_fin = panel["sector"].fillna("").str.contains("Financial", case=False)
    for col in ("op_margin", "op_margin_chg", "fin_cost_to_rev"):
        panel.loc[is_fin, col] = np.nan

    panel = rerating_factors(panel)
    panel = sector_factors(panel)

    factor_cols = list(FACTORS)
    panel = winsor_z(panel, factor_cols)
    panel = sector_z(panel, factor_cols)

    meta = {
        **fact_meta,
        "rebalances": int(panel["date"].nunique()),
        "rows": int(len(panel)),
        "companies": int(panel["entity_id"].nunique()),
        "first_date": str(panel["date"].min().date()),
        "last_date": str(panel["date"].max().date()),
    }
    return panel, meta


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def quintile_spread(frame: pd.DataFrame, factor: str, target: str) -> float:
    """Top minus bottom bucket's mean target; for a low-cardinality factor (the
    peak/growth interaction is 0-1) the two buckets are the values themselves."""
    d = frame[[factor, target]].dropna()
    if len(d) < 25:
        return float("nan")
    if d[factor].nunique() <= 4:
        high, low = d[factor].max(), d[factor].min()
        return float(d[target][d[factor] == high].mean() - d[target][d[factor] == low].mean())
    bucket = pd.qcut(d[factor], 5, labels=False, duplicates="drop")
    if bucket.nunique() < 2:
        return float("nan")
    return float(d[target][bucket == bucket.max()].mean() - d[target][bucket == 0].mean())


def ic_stats(panel: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    """Per factor x horizon: monthly rank-IC (raw and sector-neutral), Newey-West
    t-stat, hit rate, top-minus-bottom quintile excess return, coverage, and the
    same IC split by period and by size tercile."""
    factors = factors or list(FACTORS)
    rows = []
    for hlabel, h in HORIZONS.items():
        target = f"excess_{h}"
        for factor in factors:
            if factor not in panel.columns or panel[factor].notna().sum() < 200:
                continue
            base = panel[["date", "entity_id", factor, factor + "_sn", target]].copy()
            base["_size"] = panel["size"].to_numpy()  # control column, never the factor itself
            ic = monthly_ic(base, factor, target)
            if ic.empty:
                continue
            ic_sn = monthly_ic(base, factor + "_sn", target)
            d = base.dropna(subset=[factor, target])
            spread = d.groupby("date").apply(lambda g: quintile_spread(g, factor, target))
            d = d.copy()
            d["bucket"] = d.groupby("date")["_size"].transform(
                lambda s: pd.qcut(s, 3, labels=False, duplicates="drop") if s.notna().sum() >= 30 else np.nan
            )
            by_size = {name: monthly_ic(d[d["bucket"] == b], factor, target).mean()
                       for name, b in (("small", 0), ("mid", 1), ("large", 2))}
            early = ic[ic.index <= pd.Timestamp("2021-12-31")]
            late = ic[ic.index >= pd.Timestamp("2022-01-01")]
            rows.append(
                {
                    "horizon": hlabel,
                    "factor": factor,
                    "label": FACTORS.get(factor, factor),
                    "months": int(ic.notna().sum()),
                    "mean_ic": float(ic.mean()),
                    "t_stat": newey_west_tstat(ic, NW_LAGS[hlabel]),
                    "hit_rate": float((ic > 0).mean()),
                    "q5_minus_q1": float(spread.mean()),
                    "coverage": float(d.groupby("date").size().mean()),
                    "ic_sector_neutral": float(ic_sn.mean()),
                    "ic_2019_2021": float(early.mean()) if len(early) else float("nan"),
                    "ic_2022_2026": float(late.mean()) if len(late) else float("nan"),
                    "ic_small": by_size["small"],
                    "ic_mid": by_size["mid"],
                    "ic_large": by_size["large"],
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["abs_t"] = out["t_stat"].abs()
    return out.sort_values(["horizon", "abs_t"], ascending=[True, False]).drop(columns="abs_t").reset_index(drop=True)


def fm_factor_list(panel: pd.DataFrame, horizon: str = "6m", min_names: int = 150) -> list[str]:
    """Factors for that horizon's joint model, best covered first.

    A complete-case regression over all factors leaves about 110 names a month, so
    sparse factors (insider 22%, promoter 65%) are reported univariately instead.
    log P/S and log P/E are inverse transforms of sales and earnings yield, and the
    P/E change is the P/S change net of earnings growth, so one of each pair enters:
    the change block is represented by the P/S windows. A factor stays only while the
    joint sample keeps 75% of that horizon's months and at least `min_names` names.
    """
    mirrors = {"ps_ratio", "pe_ratio", "pe_chg_3m", "pe_chg_6m", "pe_chg_12m"}
    target = f"excess_{HORIZONS[horizon]}"
    dated = panel[target].notna() if target in panel.columns else pd.Series(True, index=panel.index)
    min_months = max(12, int(0.75 * panel.loc[dated, "date"].nunique()))
    candidates = sorted(
        (f for f in FACTORS if f not in mirrors and f + "_z" in panel.columns),
        key=lambda f: panel[f + "_z"].notna().mean(),
        reverse=True,
    )
    chosen: list[str] = []
    for factor in candidates:
        trial = chosen + [factor]
        complete = panel.dropna(subset=[c + "_z" for c in trial])["date"].value_counts()
        complete = complete[complete.index.isin(panel.loc[dated, "date"])]
        if len(complete) >= min_months and float(complete.mean()) >= min_names:
            chosen = trial
    return chosen


def fama_macbeth(
    panel: pd.DataFrame, factors_by_horizon: dict[str, list[str]] | None = None, min_names: int = 100
) -> pd.DataFrame:
    """Monthly cross-sectional OLS of excess return on that horizon's z-scored factors."""
    rows = []
    factors_by_horizon = factors_by_horizon or {h: fm_factor_list(panel, h) for h in HORIZONS}
    for hlabel, h in HORIZONS.items():
        factors = factors_by_horizon.get(hlabel, [])
        if not factors:
            continue
        target = f"excess_{h}"
        zcols = [f + "_z" for f in factors]
        coefs, sizes, months = [], [], []
        for month, g in panel.dropna(subset=zcols + [target]).groupby("date"):
            if len(g) < min_names:
                continue
            X = np.column_stack([np.ones(len(g))] + [g[c].to_numpy(dtype=float) for c in zcols])
            beta, *_ = np.linalg.lstsq(X, g[target].to_numpy(dtype=float), rcond=None)
            coefs.append(beta[1:])
            sizes.append(len(g))
            months.append(month)
        if not coefs:
            continue
        coef = pd.DataFrame(coefs, columns=factors)
        for factor in factors:
            rows.append(
                {
                    "horizon": hlabel,
                    "factor": factor,
                    "label": FACTORS.get(factor, factor),
                    "mean_coef": float(coef[factor].mean()),
                    "t_stat": newey_west_tstat(coef[factor], NW_LAGS[hlabel]),
                    "months": int(coef[factor].notna().sum()),
                    "mean_names": float(np.mean(sizes)),
                    "first_month": str(min(months).date()),
                    "last_month": str(max(months).date()),
                }
            )
    return pd.DataFrame(rows)


def coverage_by_year(panel: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """Non-null share of each factor among universe rows, per calendar year."""
    d = panel.assign(year=panel["date"].dt.year)
    cov = d.groupby("year")[factors].apply(lambda g: g.notna().mean())
    cov.insert(0, "companies", d.groupby("year")["entity_id"].nunique())
    cov.insert(0, "rows", d.groupby("year").size())
    return cov.reset_index()


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_html(
    ic: pd.DataFrame, fm: pd.DataFrame, split: pd.DataFrame, path: Path, meta: dict,
    factor_sets: dict[str, list[str]],
) -> None:
    lines = [
        "<!doctype html><html><head><meta charset='utf-8'><title>T-118 factor weights</title>",
        "<style>body{font-family:-apple-system,Segoe UI,Arial;margin:24px;color:#222}"
        "table{border-collapse:collapse;margin:12px 0 28px;font-size:13px}"
        "th,td{border:1px solid #ccc;padding:4px 7px;text-align:right}"
        "th{background:#eee}td:first-child,th:first-child{text-align:left}"
        "h1{font-size:20px}h2{font-size:16px;margin-top:26px}</style></head><body>",
        "<h1>T-118: which held facts explain forward excess returns</h1>",
        f"<p>Monthly rebalances {meta['first_date']} to {meta['last_date']}, "
        f"{meta['rebalances']} dates, {meta['rows']:,} company-months, "
        f"{meta['companies']:,} companies. Benchmark {BENCHMARK} TRI; total return from tr_close. "
        "Point in time: a fact is used only from the first session at/after it was public "
        "(after 15:30 IST counts from the next session). Factors winsorised 1/99 and "
        "z-scored per date; the sector-neutral column is z within sector."
        + (f" <br><b>{meta['note']}</b>" if meta.get("note") else "") + "</p>",
    ]
    for hlabel in HORIZONS:
        table = ic[ic["horizon"] == hlabel].copy()
        if table.empty:
            continue
        table["abs_t"] = table["t_stat"].abs()
        table = table.sort_values("abs_t", ascending=False).head(15)
        lines.append(f"<h2>{hlabel} excess return</h2><table><tr><th>factor</th><th>mean IC</th>"
                     "<th>t (NW)</th><th>hit rate</th><th>Q5-Q1</th><th>names/month</th>"
                     "<th>IC sector-neutral</th><th>IC 2020-21</th><th>IC 2022-26</th></tr>")
        for _, r in table.iterrows():
            lines.append(
                f"<tr><td>{r['label']}</td><td>{r['mean_ic']:+.3f}</td><td>{r['t_stat']:+.2f}</td>"
                f"<td>{r['hit_rate']:.0%}</td><td>{r['q5_minus_q1']:+.2%}</td>"
                f"<td>{r['coverage']:,.0f}</td><td>{r['ic_sector_neutral']:+.3f}</td>"
                f"<td>{r['ic_2019_2021']:+.3f}</td><td>{r['ic_2022_2026']:+.3f}</td></tr>"
            )
        lines.append("</table>")
    lines.append("<h2>Fama-MacBeth, joint model</h2>")
    for hlabel, factors in factor_sets.items():
        lines.append(f"<p><b>{hlabel}:</b> {len(factors)} factors kept a cross-section of at least "
                     f"150 names over 75% of the horizon's months: {', '.join(factors)}</p>")
    lines.append("<table><tr><th>horizon</th><th>factor</th><th>mean coef</th><th>t (NW)</th>"
                 "<th>months</th><th>names/month</th><th>window</th></tr>")
    for _, r in fm.sort_values(["horizon", "t_stat"], key=lambda s: s.abs() if s.name == "t_stat" else s).iterrows():
        lines.append(
            f"<tr><td>{r['horizon']}</td><td>{r['label']}</td><td>{r['mean_coef']:+.4f}</td>"
            f"<td>{r['t_stat']:+.2f}</td><td>{r['months']}</td><td>{r['mean_names']:,.0f}</td>"
            f"<td>{r['first_month']}..{r['last_month']}</td></tr>"
        )
    lines.append("</table>")
    for window in ("pooled", str(meta["last_date"])):
        table = split[split["window"] == window]
        if table.empty:
            continue
        title = "12-month price move by sector, pooled" if window == "pooled" else f"by sector on {window}"
        lines.append(f"<h2>{title}</h2>")
        lines.append("<p>mean log changes per company-month in that sector; sales share + re-rating share "
                     "= 1 except for share issuance and dividends.</p>")
        lines.append("<table><tr><th>sector</th><th>names</th><th>price 12m</th><th>sales 12m</th>"
                     "<th>P/S 12m</th><th>sales share</th><th>re-rating share</th></tr>")
        for _, r in table.iterrows():
            lines.append(
                f"<tr><td>{r['sector']}</td><td>{r['names']:,}</td><td>{r['price_12m_log']:+.2%}</td>"
                f"<td>{r['sales_12m_log']:+.2%}</td><td>{r['ps_12m_log']:+.2%}</td>"
                f"<td>{r['sales_share']:+.2f}</td><td>{r['rerating_share']:+.2f}</td></tr>"
            )
        lines.append("</table>")
    lines.append("</body></html>")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-118 factor weight study")
    ap.add_argument("--out", default=".tmp/t118")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--start", default="2019-06-01")
    ap.add_argument("--end", default="2026-11-03")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = Path(args.snapshot) if args.snapshot else default_snapshot()
    t0 = time.time()
    con = connect(snapshot)
    try:
        panel, meta = build_panel(con, args.start, args.end)
    finally:
        con.close()
    print(f"panel: {meta['rows']:,} rows x {meta['companies']:,} companies, "
          f"{meta['rebalances']} rebalances {meta['first_date']}..{meta['last_date']} "
          f"({time.time() - t0:.0f}s)")
    print(f"results_key: {meta['filings']:,} filings, {meta['unmapped_isin']:,} unmapped to a traded company")
    print(f"P/E factor usable on {panel['pe_ratio'].notna().mean():.0%} of company-months "
          f"(needs positive TTM PAT); P/S on {panel['ps_ratio'].notna().mean():.0%}")

    cov = coverage_by_year(panel, list(FACTORS))
    cov.to_csv(out / "coverage_by_year.csv", index=False)
    print("\nuniverse and factor coverage by year (share of company-months with a value):")
    print(cov.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    # The growth factors need eight consecutive quarters of filings. The store holds
    # almost no 2017-2018 quarterly results (5 and 2,161 filing rows, 3 companies with
    # eight quarters by 2019-12-31), so no year before 2021 can measure them. Those
    # leading years are dropped from the statistics with a printed reason; a gap after
    # a good year means the panel is broken and the run stops.
    years = cov.set_index("year")
    good = {int(y): bool(all(float(row[g]) >= 0.40 for g in GROWTH_FACTORS)) for y, row in years.iterrows()}
    first_good = min(y for y, ok in good.items() if ok)
    late_bad = sorted(y for y, ok in good.items() if y > first_good and not ok)
    if late_bad:
        print(f"\nSTOP: growth-factor coverage under 40% of the universe in {late_bad}")
        return 2
    dropped = sorted(y for y in good if y < first_good)
    if dropped:
        print(f"\ngrowth factors unusable in {dropped} (needs 8 quarters of filings; the store's "
              f"quarterly coverage starts in 2019): statistics run from {first_good}")
        panel = panel[panel["date"].dt.year >= first_good].reset_index(drop=True)
        meta["first_date"] = str(panel["date"].min().date())
        meta["rows"] = int(len(panel))
        meta["rebalances"] = int(panel["date"].nunique())
        meta["note"] = (f"years {dropped} excluded: an 8-quarter TTM growth factor cannot exist "
                        f"there, the store holds almost no 2017-2018 quarterly filings")

    ic = ic_stats(panel)
    ic.to_csv(out / "factor_ic.csv", index=False)

    factor_sets = {h: fm_factor_list(panel, h) for h in HORIZONS}
    fm = fama_macbeth(panel, factor_sets)
    fm.to_csv(out / "fama_macbeth.csv", index=False)

    split = sector_split(panel)
    split.to_csv(out / "sector_split.csv", index=False)

    write_html(ic, fm, split, out / "T-118_factor_weights.html", meta, factor_sets)
    for hlabel, factors in factor_sets.items():
        sub = fm[fm["horizon"] == hlabel]
        if len(sub):
            print(f"fama-macbeth {hlabel}: {len(factors)} factors, {int(sub['months'].max())} months, "
                  f"{sub['mean_names'].max():,.0f} names/month")
    pooled = split[split["window"] == "pooled"].head(8)
    print("\nsector 12-month split, most compressed multiple first (pooled):")
    print(pooled.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    for hlabel in HORIZONS:
        table = ic[ic["horizon"] == hlabel].copy()
        table["abs_t"] = table["t_stat"].abs()
        print(f"\n{hlabel} top factors by |t|:")
        print(table.sort_values("abs_t", ascending=False)
              [["factor", "mean_ic", "t_stat", "hit_rate", "q5_minus_q1", "coverage"]]
              .head(10).to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    print(f"\nwrote {out}/factor_ic.csv, fama_macbeth.csv, sector_split.csv, coverage_by_year.csv, "
          f"T-118_factor_weights.html ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
