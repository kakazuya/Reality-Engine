"""T-235 stage 1: dated per-stock capital-flow signals from the held market data.

One table, ``flow_signal(company, date_known, signal, direction, strength, detail)``:
each row is one observation a decision could have used at ``date_known`` (a
trading session). ``company`` is the issuer entity code (the permanent ISIN
issuer anchor used by T-118/T-207); ``detail`` carries the measure.

Signals (all thresholds are fixed here, before any outcome is seen):

* delivery spike: NSE delivery % on a session >= 2x its own prior-60-session
  median and >= 40%, direction by the session's adjusted-close return
  (up = accumulation, down = distribution);
* delivery trend: mean delivery % of the last 20 sessions vs the 60 sessions
  before them, ratio >= 1.5 (up) or <= 1/1.5 (down), base >= 30%;
* volume spike: volume >= 3x the prior-200-session mean, prior-60-session median
  traded value >= Rs 1 crore, direction by the session return;
* insider cluster: trailing-30-day net insider value (NSE PIT disclosures)
  >= Rs 5 crore over >= 2 disclosures, buy or sell;
* pledge cluster: trailing-30-day promoter pledge value >= Rs 5 crore
  (Pledge / Pledge Invoke) or pledge release >= Rs 5 crore (Pledge Revoke);
* bulk/block institutional flow: one session's net FII + MF + insurance
  bulk/block value >= Rs 5 crore, by the named-party name rule below;
* promoter change: promoter % change q/q >= 0.5pp at the filing's own
  availability date (never the quarter end);
* bad quarter: TTM PAT YoY <= -25% or TTM operating margin down >= 3pp YoY,
  at the date the four quarterly filings were public (15:30 IST rule);
* peak quarter: TTM PAT (or margin) at its own 20-quarter high, at the same
  availability date (peak-earnings trap, T-207);
* FPI / MF / insurance change: category % change q/q >= 0.5pp at the filing's
  broadcast date, from the T-209 structured universe store (2024-04 onwards).

Every signal is emitted at the first session on which its inputs were usable:
market data after the close of the observation day (next session), filings by
the 15:30 IST rule, shareholding on its filing/broadcast date. A company/signal
fires at most once per 30 sessions, so a delivery-% state that lasts for weeks is
one event, not one event per session. A shareholding filing is used only when it
was published within 120 days of its own quarter end: the snapshot's known_at for
old quarters is the 2022 backfill crawl date, and without this filter thousands of
2015-2021 filings would fire on a handful of 2022 sessions.

Run (read-only snapshot; writes only under --out):

    python -m reality_engine.research.flow_signals --out .tmp/t235

A 2010-2018 price/results backfill only needs ``--start 2010-01-01``; the
availability rule and the output schema do not change.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from reality_engine.research.factor_weights import (
    IST,
    connect,
    default_snapshot,
    ist_date,
    pick_basis,
    pit_sessions,
    quarter_facts,
    utc_ns,
)

# --------------------------------------------------------------------------- #
# Thresholds, fixed before any outcome was seen (the doc repeats this table)
# --------------------------------------------------------------------------- #
DELIVERY_SPIKE_X = 2.0
DELIVERY_FLOOR_PCT = 40.0
DELIVERY_MEDIAN_FLOOR_PCT = 20.0
DELIVERY_MEDIAN_SESSIONS = 60
DELIVERY_TREND_X = 1.5
DELIVERY_TREND_BASE_MIN_PCT = 30.0
DELIVERY_TREND_MEAN = 20
DELIVERY_TREND_BASE = 60
VOLUME_SPIKE_X = 3.0
VALUE_MEDIAN_FLOOR_INR = 1e7  # Rs 1 crore
VOLUME_MEAN_SESSIONS = 200
VALUE_MEDIAN_SESSIONS = 60
INSIDER_CLUSTER_INR = 5e7  # Rs 5 crore
INSIDER_CLUSTER_COUNT = 2
PLEDGE_CLUSTER_INR = 5e7
DEAL_INSTITUTION_INR = 5e7
PROMOTER_CHANGE_PP = 0.5
CATEGORY_CHANGE_PP = 0.5
BAD_PAT_YOY = -0.25
BAD_MARGIN_PP = -0.03
PEAK_WINDOW_QUARTERS = 20
PEAK_MIN_QUARTERS = 12
CLUSTER_WINDOW_DAYS = 30
COOLDOWN_SESSIONS = 30
# A shareholding filing is usable only when it was published for its own quarter: the
# snapshot's known_at for older quarters is the 2022 backfill crawl date, so thousands
# of 2015-2021 filings would otherwise fire on a handful of 2022 sessions.
MAX_FILING_LAG_DAYS = 120
STRUCTURED_DEFAULT = r"D:/RealityEngine/structured/structured_universe.db"

SIGNAL_LABELS = {
    "delivery_spike_up": "delivery % >=2x own 60-session median, up day",
    "delivery_spike_down": "delivery % >=2x own 60-session median, down day",
    "delivery_trend_up": "20-session delivery mean >=1.5x the 60 before it",
    "delivery_trend_down": "20-session delivery mean <=0.67x the 60 before it",
    "volume_spike_up": "volume >=3x own 200-session mean, up day",
    "volume_spike_down": "volume >=3x own 200-session mean, down day",
    "insider_buy_cluster": "insider net buy >=Rs 5cr over 30 days",
    "insider_sell_cluster": "insider net sell >=Rs 5cr over 30 days",
    "pledge_increase": "promoter pledge >=Rs 5cr over 30 days",
    "pledge_release": "promoter pledge release >=Rs 5cr over 30 days",
    "bulk_inst_buy": "institutional bulk/block net buy >=Rs 5cr",
    "bulk_inst_sell": "institutional bulk/block net sell >=Rs 5cr",
    "promoter_up": "promoter % up >=0.5pp q/q at filing date",
    "promoter_down": "promoter % down >=0.5pp q/q at filing date",
    "bad_quarter": "TTM PAT <=-25% YoY or TTM margin -3pp YoY",
    "peak_quarter": "TTM PAT or margin at its own 20-quarter high",
    "fpi_up": "FPI % up >=0.5pp q/q at filing date",
    "fpi_down": "FPI % down >=0.5pp q/q at filing date",
    "mf_up": "MF % up >=0.5pp q/q at filing date",
    "mf_down": "MF % down >=0.5pp q/q at filing date",
    "insurance_up": "insurance % up >=0.5pp q/q at filing date",
    "insurance_down": "insurance % down >=0.5pp q/q at filing date",
}

_COLUMNS = ["company", "date_known", "signal", "direction", "strength", "detail"]

# --------------------------------------------------------------------------- #
# Pure rules (unit-tested without a database)
# --------------------------------------------------------------------------- #
_INSURANCE = ("INSURANCE", "LIFE INSUR", "GENERAL INSUR", "LIC OF INDIA", "INSURANCE CO")
_MUTUAL_FUND = (
    "MUTUAL FUND", "MUTUALFUND", "ASSET MANAGEMENT", "ASSET MANAGERS", "AMC ",
    " MF ", "MF LTD", "MUTUAL FUNDS",
)
_FOREIGN = (
    "FII", "FPI", "FOREIGN", "MAURITIUS", "SINGAPORE", "LUXEMBOURG", "CAYMAN",
    "BERMUDA", "GLOBAL FUND", "MASTER FUND", "EMERGING MARKET", "ETF", "ISHARES",
    "NORGES", "GOLDMAN", "MORGAN STANLEY", "CITIGROUP", "CITADEL", "UBS",
    "NOMURA", "BNP PARIBAS", "JPMORGAN", "HSBC", "ABERDEEN", "WELLINGTON",
    "VANGUARD", "BLACKROCK", "SOCIETE GENERALE", "MACQUARIE",
)


def classify_client(name: object) -> str:
    """Named bulk/block party -> fii | mf | insurance | other.

    Insurance is tested first (``ICICI PRUDENTIAL LIFE INSURANCE``), then mutual
    fund, then foreign/institutional patterns. Everything else (proprietary
    desks, brokers, individuals, LLPs) is ``other`` and never counts as an
    institutional flow.
    """
    text = " ".join(str(name or "").upper().split())
    if not text:
        return "other"
    if any(word in text for word in _INSURANCE):
        return "insurance"
    if any(word in text for word in _MUTUAL_FUND):
        return "mf"
    if any(word in text for word in _FOREIGN):
        return "fii"
    return "other"


def delivery_spike(ratio: float, level: float, median: float, day_ret: float) -> str | None:
    """Delivery spike rule: signal name or None (direction from the price sign)."""
    if not np.isfinite(median) or median < DELIVERY_MEDIAN_FLOOR_PCT:
        return None
    if not np.isfinite(level) or level < DELIVERY_FLOOR_PCT:
        return None
    if not np.isfinite(ratio) or ratio < DELIVERY_SPIKE_X:
        return None
    if not np.isfinite(day_ret):
        return None
    return "delivery_spike_up" if day_ret >= 0 else "delivery_spike_down"


def delivery_trend(ratio: float, base: float) -> str | None:
    """Delivery-share trend rule."""
    if not np.isfinite(base) or base < DELIVERY_TREND_BASE_MIN_PCT:
        return None
    if not np.isfinite(ratio):
        return None
    if ratio >= DELIVERY_TREND_X:
        return "delivery_trend_up"
    if ratio <= 1.0 / DELIVERY_TREND_X:
        return "delivery_trend_down"
    return None


def volume_spike(ratio: float, value_inr: float, value_median: float, day_ret: float) -> str | None:
    """Volume spike rule (a liquid name is required so one small trade cannot fire it)."""
    if not np.isfinite(value_median) or value_median < VALUE_MEDIAN_FLOOR_INR:
        return None
    if not np.isfinite(value_inr) or value_inr < VALUE_MEDIAN_FLOOR_INR:
        return None
    if not np.isfinite(ratio) or ratio < VOLUME_SPIKE_X:
        return None
    if not np.isfinite(day_ret):
        return None
    return "volume_spike_up" if day_ret >= 0 else "volume_spike_down"


def trailing_window(frame: pd.DataFrame, value: str, days: int = CLUSTER_WINDOW_DAYS,
                    count: str | None = None) -> pd.DataFrame:
    """Per-``company`` trailing calendar-day sum and count, both endpoints inclusive.

    ``frame`` must carry ``company`` and ``date`` columns. Returns ``window_value``
    and ``window_count`` in the frame's sorted order (company, date).
    """
    work = frame.sort_values(["company", "date"]).reset_index(drop=True)
    value_arr = work[value].to_numpy(dtype=float)
    count_arr = work[count].to_numpy(dtype=float) if count else np.ones(len(work))
    dates = work["date"].to_numpy(dtype="datetime64[D]")
    entities = work["company"].to_numpy()
    out_v = np.empty(len(work))
    out_c = np.empty(len(work))
    starts = np.r_[0, np.flatnonzero(entities[1:] != entities[:-1]) + 1, len(work)]
    for pos in range(len(starts) - 1):
        lo, hi = starts[pos], starts[pos + 1]
        d = dates[lo:hi]
        cs_v = np.cumsum(value_arr[lo:hi])
        cs_c = np.cumsum(count_arr[lo:hi])
        left = np.searchsorted(d, d - np.timedelta64(days, "D"), side="left")
        prev_v = np.where(left > 0, cs_v[np.maximum(left - 1, 0)], 0.0)
        prev_c = np.where(left > 0, cs_c[np.maximum(left - 1, 0)], 0.0)
        out_v[lo:hi] = cs_v - prev_v
        out_c[lo:hi] = cs_c - prev_c
    work["window_value"] = out_v
    work["window_count"] = out_c
    return work


def apply_cooldown(frame: pd.DataFrame, by: tuple[str, ...], cooldown: int = COOLDOWN_SESSIONS) -> pd.DataFrame:
    """Keep the first firing and drop any repeat within ``cooldown`` sessions."""
    if frame.empty:
        return frame
    frame = frame.sort_values([*by, "i"]).reset_index(drop=True)
    keep = np.ones(len(frame), dtype=bool)
    keys = frame.loc[:, list(by)].astype(str).agg("|".join, axis=1).to_numpy()
    i_values = frame["i"].to_numpy()
    last = -10 ** 9
    for pos in range(len(frame)):
        if pos == 0 or keys[pos] != keys[pos - 1]:
            last = -10 ** 9
        if pos > 0 and i_values[pos] - last < cooldown:
            keep[pos] = False
        else:
            last = i_values[pos]
    return frame[keep].drop(columns=["i"], errors="ignore").reset_index(drop=True)


def _detail(**values) -> str:
    clean = {}
    for key, value in values.items():
        if isinstance(value, (float, np.floating)):
            clean[key] = round(float(value), 4) if np.isfinite(value) else None
        elif isinstance(value, (np.integer, np.bool_)):
            clean[key] = int(value) if not isinstance(value, np.bool_) else bool(value)
        else:
            clean[key] = value
    return json.dumps(clean, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Snapshot plumbing (shared with flow_events.py)
# --------------------------------------------------------------------------- #
def trading_calendar(con: duckdb.DuckDBPyConnection, start: str, end: str) -> pd.DataFrame:
    """NSE sessions up to ``end`` with their 0-based row number ``i``.

    The lower bound is the snapshot's first session, never the request's start:
    a filing older than the window must not collapse onto the window's first
    session (that would build one giant cluster on day one).
    """
    return con.execute(
        """SELECT date, CAST(row_number() OVER (ORDER BY date) - 1 AS BIGINT) AS i
           FROM (SELECT DISTINCT date FROM px_daily
                 WHERE exch = 'NSE' AND date <= CAST(? AS DATE))""",
        [end],
    ).df()


def isin_entity_map(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        "SELECT isin, any_value(entity_id) AS entity_id FROM px_daily WHERE isin IS NOT NULL GROUP BY isin"
    ).df()


def load_shares(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame) -> pd.DataFrame:
    """Shares outstanding with the session each filing was usable on."""
    raw = con.execute(
        """SELECT trading_isin, known_at_utc,
                  PaidUpValueOfEquityShareCapital AS pu, FaceValueOfEquityShareCapital AS fv
           FROM results_key
           WHERE known_at_utc IS NOT NULL AND PaidUpValueOfEquityShareCapital > 0
             AND FaceValueOfEquityShareCapital > 0"""
    ).df()
    raw = raw.merge(isin_entity_map(con), left_on="trading_isin", right_on="isin", how="inner")
    raw["avail_date"] = pit_sessions(raw["known_at_utc"], pd.DatetimeIndex(cal["date"])).to_numpy()
    raw["shares"] = raw["pu"] / raw["fv"]
    raw = raw.dropna(subset=["entity_id", "avail_date", "shares"])
    raw["avail_date"] = pd.to_datetime(raw["avail_date"])
    return raw.sort_values(["entity_id", "avail_date"]).drop_duplicates(
        ["entity_id", "avail_date"], keep="last"
    )[["entity_id", "avail_date", "shares"]].reset_index(drop=True)


def load_sectors(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    ind = con.execute("SELECT isin, sector FROM company_industry WHERE sector IS NOT NULL").df()
    out = ind.merge(isin_entity_map(con), on="isin", how="inner").drop_duplicates("entity_id")
    return out[["entity_id", "sector"]].rename(columns={"entity_id": "company"}).reset_index(drop=True)


def load_symbols(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT entity_id AS company, latest_symbol AS symbol FROM entity").df()


# --------------------------------------------------------------------------- #
# Market-data signals (computed in DuckDB over the daily panel)
# --------------------------------------------------------------------------- #
def market_events(con: duckdb.DuckDBPyConnection, start: str, end: str) -> tuple[pd.DataFrame, int]:
    """Delivery / volume signals; ``date_known`` = the next NSE session."""
    con.execute(
        """CREATE OR REPLACE TEMP TABLE t235_cal AS
           SELECT date, CAST(row_number() OVER (ORDER BY date) - 1 AS BIGINT) AS i
           FROM (SELECT DISTINCT date FROM px_daily
                 WHERE exch = 'NSE' AND date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE))""",
        [start, end],
    )
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE t235_daily AS
            WITH j AS (
              SELECT p.entity_id, p.date, c.i, p.close, p.adj_close, p.volume, p.value_inr,
                     n.delivery_pct AS dp
              FROM px_daily p
              JOIN t235_cal c ON c.date = p.date
              LEFT JOIN (SELECT entity_id, date, max(delivery_pct) AS delivery_pct
                         FROM px_nse WHERE delivery_pct IS NOT NULL GROUP BY 1, 2) n
                ON n.entity_id = p.entity_id AND n.date = p.date
              WHERE p.date BETWEEN DATE '{start}' AND DATE '{end}'
            )
            SELECT *,
              adj_close / lag(adj_close) OVER w - 1 AS day_ret,
              quantile_cont(dp, 0.5) OVER (PARTITION BY entity_id ORDER BY i
                  ROWS BETWEEN {DELIVERY_MEDIAN_SESSIONS} PRECEDING AND 1 PRECEDING) AS dp_med60,
              count(dp) OVER (PARTITION BY entity_id ORDER BY i
                  ROWS BETWEEN {DELIVERY_MEDIAN_SESSIONS} PRECEDING AND 1 PRECEDING) AS dp_n60,
              avg(dp) OVER (PARTITION BY entity_id ORDER BY i
                  ROWS BETWEEN {DELIVERY_TREND_MEAN} PRECEDING AND 1 PRECEDING) AS dp_mean20,
              avg(dp) OVER (PARTITION BY entity_id ORDER BY i
                  ROWS BETWEEN {DELIVERY_TREND_MEAN + DELIVERY_TREND_BASE} PRECEDING
                  AND {DELIVERY_TREND_MEAN + 1} PRECEDING) AS dp_base60,
              avg(volume) OVER (PARTITION BY entity_id ORDER BY i
                  ROWS BETWEEN {VOLUME_MEAN_SESSIONS} PRECEDING AND 1 PRECEDING) AS vol_mean200,
              count(volume) OVER (PARTITION BY entity_id ORDER BY i
                  ROWS BETWEEN {VOLUME_MEAN_SESSIONS} PRECEDING AND 1 PRECEDING) AS vol_n200,
              quantile_cont(value_inr, 0.5) OVER (PARTITION BY entity_id ORDER BY i
                  ROWS BETWEEN {VALUE_MEDIAN_SESSIONS} PRECEDING AND 1 PRECEDING) AS value_med60
            FROM j WINDOW w AS (PARTITION BY entity_id ORDER BY i)"""
    )
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE t235_mkt AS
            WITH spike AS (
              SELECT d.entity_id AS company, d.i,
                CASE WHEN d.day_ret >= 0 THEN 'delivery_spike_up' ELSE 'delivery_spike_down' END AS signal,
                CASE WHEN d.day_ret >= 0 THEN 'up' ELSE 'down' END AS direction,
                round(d.dp / nullif(d.dp_med60, 0), 4) AS strength,
                json_object('dp', round(d.dp, 2), 'dp_med60', round(d.dp_med60, 2),
                            'ret', round(d.day_ret, 4)) AS detail
              FROM t235_daily d
              WHERE d.dp IS NOT NULL AND d.dp_n60 >= 40 AND d.dp >= {DELIVERY_FLOOR_PCT}
                AND d.dp_med60 >= {DELIVERY_MEDIAN_FLOOR_PCT}
                AND d.dp >= {DELIVERY_SPIKE_X} * d.dp_med60 AND d.day_ret IS NOT NULL
            ), trend AS (
              SELECT d.entity_id AS company, d.i,
                CASE WHEN d.dp_mean20 >= {DELIVERY_TREND_X} * d.dp_base60
                     THEN 'delivery_trend_up' ELSE 'delivery_trend_down' END AS signal,
                CASE WHEN d.dp_mean20 >= {DELIVERY_TREND_X} * d.dp_base60
                     THEN 'up' ELSE 'down' END AS direction,
                round(d.dp_mean20 / nullif(d.dp_base60, 0), 4) AS strength,
                json_object('dp_mean20', round(d.dp_mean20, 2),
                            'dp_base60', round(d.dp_base60, 2)) AS detail
              FROM t235_daily d
              WHERE d.dp_mean20 IS NOT NULL AND d.dp_base60 >= {DELIVERY_TREND_BASE_MIN_PCT}
                AND d.dp_mean20 <= d.dp_base60 / {DELIVERY_TREND_X}
            ), trend_up AS (
              SELECT d.entity_id AS company, d.i, 'delivery_trend_up' AS signal, 'up' AS direction,
                round(d.dp_mean20 / nullif(d.dp_base60, 0), 4) AS strength,
                json_object('dp_mean20', round(d.dp_mean20, 2),
                            'dp_base60', round(d.dp_base60, 2)) AS detail
              FROM t235_daily d
              WHERE d.dp_mean20 IS NOT NULL AND d.dp_base60 >= {DELIVERY_TREND_BASE_MIN_PCT}
                AND d.dp_mean20 >= {DELIVERY_TREND_X} * d.dp_base60
            ), vol AS (
              SELECT d.entity_id AS company, d.i,
                CASE WHEN d.day_ret >= 0 THEN 'volume_spike_up' ELSE 'volume_spike_down' END AS signal,
                CASE WHEN d.day_ret >= 0 THEN 'up' ELSE 'down' END AS direction,
                round(d.volume / nullif(d.vol_mean200, 0), 4) AS strength,
                json_object('volume', d.volume, 'vol_mean200', round(d.vol_mean200, 1),
                            'value_inr', d.value_inr, 'ret', round(d.day_ret, 4)) AS detail
              FROM t235_daily d
              WHERE d.vol_n200 >= 150 AND d.vol_mean200 > 0
                AND d.value_med60 >= {VALUE_MEDIAN_FLOOR_INR}
                AND d.value_inr >= {VALUE_MEDIAN_FLOOR_INR}
                AND d.volume >= {VOLUME_SPIKE_X} * d.vol_mean200 AND d.day_ret IS NOT NULL
            )
            SELECT s.company, c.date AS date_known, s.i, s.signal, s.direction, s.strength, s.detail
            FROM (SELECT * FROM spike UNION ALL SELECT * FROM trend_up UNION ALL SELECT * FROM trend
                  UNION ALL SELECT * FROM vol) s
            JOIN t235_cal c ON c.i = s.i + 1"""
    )
    rows = con.execute("SELECT * FROM t235_mkt").df()
    observed = int(con.execute("SELECT count(*) FROM t235_daily").fetchone()[0])
    con.execute("DROP TABLE IF EXISTS t235_mkt")
    con.execute("DROP TABLE IF EXISTS t235_daily")
    con.execute("DROP TABLE IF EXISTS t235_cal")
    rows = apply_cooldown(rows, ("company", "signal"))
    rows["date_known"] = pd.to_datetime(rows["date_known"])
    return rows, observed


# --------------------------------------------------------------------------- #
# Insider / pledge disclosures
# --------------------------------------------------------------------------- #
def insider_events(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame) -> pd.DataFrame:
    """Insider 30-day clusters and promoter pledge clusters from NSE PIT rows."""
    ins = con.execute(
        """SELECT symbol, known_at_utc, transaction_type, securities_value, person_category
           FROM nse_insider
           WHERE known_at_utc IS NOT NULL AND securities_value > 0
             AND transaction_type IN ('Buy', 'Sell', 'Pledge', 'Pledge Revoke', 'Pledge Invoke')"""
    ).df()
    if ins.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    # Promoter / director / KMP / their relatives only: designated-employee ESOP
    # sales are thousands of rows a month at a large company and are not the
    # informed money the signal is about.
    category = ins["person_category"].astype(str).str.upper()
    ins = ins[category.str.contains(
        "PROMOTER|DIRECTOR|KEY MANAGERIAL|IMMEDIATE RELATIVE", regex=True, na=False)].copy()
    ins["promoter_only"] = ins["person_category"].astype(str).str.upper().str.contains(
        "PROMOTER", na=False)
    if ins.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    ins = ins.merge(
        con.execute(
            """SELECT symbol, isin, TRY_CAST(first_date AS DATE) AS first_date,
                      TRY_CAST(last_date AS DATE) AS last_date, n_days
               FROM symbol_isin_history WHERE exchange = 'NSE'"""
        ).df(),
        on="symbol",
        how="inner",
    )
    ins["_date"] = ist_date(ins["known_at_utc"])
    ins = ins[(ins["_date"] >= ins["first_date"]) & (ins["_date"] <= ins["last_date"])]
    ins = ins.sort_values(
        ["n_days", "symbol", "known_at_utc", "transaction_type", "securities_value"],
        ascending=[False, True, True, True, True],
    ).drop_duplicates(["symbol", "known_at_utc", "securities_value"])
    ins = ins.merge(isin_entity_map(con), on="isin", how="inner")
    if ins.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    ins["avail"] = pit_sessions(ins["known_at_utc"], pd.DatetimeIndex(cal["date"])).to_numpy()
    ins = ins.dropna(subset=["avail"]).copy()
    ins["avail"] = pd.to_datetime(ins["avail"])
    i_map = cal.set_index("date")["i"].to_dict()
    ins["i"] = ins["avail"].map(i_map).astype("Int64")
    ins = ins.dropna(subset=["i"]).copy()
    ins["i"] = ins["i"].astype(int)

    frames: list[pd.DataFrame] = []

    # Buys and sells: trailing 30-day net value, fired on the disclosure session.
    trade = ins[ins["transaction_type"].isin(["Buy", "Sell"])].copy()
    if not trade.empty:
        trade["signed"] = np.where(trade["transaction_type"].eq("Buy"), trade["securities_value"],
                                   -trade["securities_value"])
        daily = trade.groupby(["entity_id", "avail"], as_index=False).agg(
            value=("signed", "sum"), n=("signed", "size"), i=("i", "max"))
        daily = trailing_window(daily.rename(columns={"entity_id": "company"}).assign(date=lambda d: d["avail"]),
                                "value", count="n")
        for sign, signal in ((1, "insider_buy_cluster"), (-1, "insider_sell_cluster")):
            hit = daily[(daily["window_value"] * sign >= INSIDER_CLUSTER_INR)
                        & (daily["window_count"] >= INSIDER_CLUSTER_COUNT)].copy()
            if hit.empty:
                continue
            hit = hit.rename(columns={"company": "company"})
            hit["signal"] = signal
            hit["direction"] = "up" if sign > 0 else "down"
            hit["strength"] = hit["window_value"].abs() / 1e7
            hit["detail"] = [_detail(crore=abs(v) / 1e7, n=int(n))
                             for v, n in zip(hit["window_value"], hit["window_count"])]
            hit["company"] = hit["company"]
            hit = hit.rename(columns={"date": "date_known"})
            frames.append(apply_cooldown(hit[["company", "date_known", "signal", "direction",
                                              "strength", "detail", "i"]], ("company", "signal")))

    # Pledge creation/invocation and release: promoter rows only, one disclosure enough.
    for kinds, signal, direction in (
        (("Pledge", "Pledge Invoke"), "pledge_increase", "down"),
        (("Pledge Revoke",), "pledge_release", "up"),
    ):
        part = ins[ins["transaction_type"].isin(kinds) & ins["promoter_only"]]
        if part.empty:
            continue
        daily = part.groupby(["entity_id", "avail"], as_index=False).agg(
            value=("securities_value", "sum"), n=("securities_value", "size"), i=("i", "max"))
        daily = trailing_window(daily.rename(columns={"entity_id": "company"}).assign(date=lambda d: d["avail"]),
                                "value", count="n")
        hit = daily[daily["window_value"] >= PLEDGE_CLUSTER_INR].copy()
        if hit.empty:
            continue
        hit["signal"] = signal
        hit["direction"] = direction
        hit["strength"] = hit["window_value"] / 1e7
        hit["detail"] = [_detail(crore=v / 1e7, n=int(n))
                         for v, n in zip(hit["window_value"], hit["window_count"])]
        hit = hit.rename(columns={"date": "date_known"})
        frames.append(apply_cooldown(hit[["company", "date_known", "signal", "direction",
                                          "strength", "detail", "i"]], ("company", "signal")))

    if not frames:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Bulk / block institutional flow
# --------------------------------------------------------------------------- #
def deal_events(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame) -> pd.DataFrame:
    """One row per entity/session of net institutional bulk/block flow >= Rs 5cr."""
    empty = pd.DataFrame(columns=[*_COLUMNS, "i"])
    hist = con.execute(
        """SELECT symbol, isin, TRY_CAST(first_date AS DATE) AS first_date,
                  TRY_CAST(last_date AS DATE) AS last_date, n_days
           FROM symbol_isin_history WHERE exchange = 'NSE'"""
    ).df()
    nse = con.execute(
        """SELECT TRY_CAST(date AS DATE) AS deal_date, symbol, client_name, buy_sell,
                  quantity, price, known_at_utc
           FROM nse_deals WHERE known_at_utc IS NOT NULL"""
    ).df()
    nse = nse.merge(hist, on="symbol", how="inner")
    nse = nse[(nse["deal_date"] >= nse["first_date"]) & (nse["deal_date"] <= nse["last_date"])]
    nse = nse.sort_values(["n_days", "symbol", "known_at_utc"], ascending=[False, True, True])
    nse = nse.drop_duplicates(["symbol", "deal_date", "client_name", "buy_sell"]).merge(
        isin_entity_map(con), on="isin", how="inner")

    bse = con.execute(
        """SELECT TRY_CAST(d.date AS DATE) AS deal_date, d.sc_code, d.client_name, d.buy_sell,
                  d.quantity, d.price, d.known_at_utc, b.isin
           FROM bse_deals d
           JOIN bse_code_isin b ON b.sc_code = d.sc_code
                              AND TRY_CAST(d.date AS DATE) >= TRY_CAST(b.first_date AS DATE)
                              AND TRY_CAST(d.date AS DATE) <= TRY_CAST(b.last_date AS DATE)
           WHERE d.known_at_utc IS NOT NULL"""
    ).df()
    bse = bse.drop_duplicates(["sc_code", "deal_date", "client_name", "buy_sell"]).merge(
        isin_entity_map(con), on="isin", how="inner")

    frames = [part for part in (nse, bse) if not part.empty]
    if not frames:
        return empty
    deals = pd.concat(frames, ignore_index=True)
    deals["value_inr"] = (pd.to_numeric(deals["quantity"], errors="coerce")
                          * pd.to_numeric(deals["price"], errors="coerce"))
    deals["side"] = deals["buy_sell"].astype(str).str.upper().str[0]
    deals["cls"] = deals["client_name"].map(classify_client)
    deals = deals[deals["value_inr"].notna() & (deals["value_inr"] > 0)
                  & deals["side"].isin(["B", "S"])].copy()
    inst = deals[deals["cls"].isin(["fii", "mf", "insurance"])].copy()
    if inst.empty:
        return empty
    inst["signed"] = np.where(inst["side"].eq("B"), inst["value_inr"], -inst["value_inr"])
    split = inst.pivot_table(index=["entity_id", "deal_date"], columns="cls",
                             values="signed", aggfunc="sum", fill_value=0.0).reset_index()
    for cls in ("fii", "mf", "insurance"):
        if cls not in split.columns:
            split[cls] = 0.0
    split["net"] = split["fii"] + split["mf"] + split["insurance"]
    split["n"] = inst.groupby(["entity_id", "deal_date"]).size().to_numpy()
    split = split[split["net"].abs() >= DEAL_INSTITUTION_INR].copy()
    if split.empty:
        return empty
    known = inst.groupby(["entity_id", "deal_date"], as_index=False)["known_at_utc"].max()
    split = split.merge(known, on=["entity_id", "deal_date"], how="left")
    split["avail"] = pit_sessions(split["known_at_utc"], pd.DatetimeIndex(cal["date"])).to_numpy()
    split = split.dropna(subset=["avail"]).copy()
    split["date_known"] = pd.to_datetime(split["avail"])
    i_map = cal.set_index("date")["i"].to_dict()
    split["i"] = split["date_known"].map(i_map)
    split = split.dropna(subset=["i"])
    split["company"] = split["entity_id"]
    split["signal"] = np.where(split["net"] > 0, "bulk_inst_buy", "bulk_inst_sell")
    split["direction"] = np.where(split["net"] > 0, "up", "down")
    split["strength"] = split["net"].abs() / 1e7
    split["detail"] = [
        _detail(crore=net / 1e7, fii_crore=fii / 1e7, mf_crore=mf / 1e7,
                ins_crore=ins / 1e7, deals=int(n))
        for net, fii, mf, ins, n in zip(split["net"], split["fii"], split["mf"],
                                        split["insurance"], split["n"])
    ]
    return split[["company", "date_known", "signal", "direction", "strength", "detail", "i"]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Ownership: promoter % (snapshot) and FPI/MF/insurance (structured store)
# --------------------------------------------------------------------------- #
def _quarterly_changes(frame: pd.DataFrame, value: str, isin: str, known: str,
                       min_days: int = 60, max_days: int = 120,
                       max_known_lag_days: int = MAX_FILING_LAG_DAYS) -> pd.DataFrame:
    frame = frame.dropna(subset=[isin, "quarter_end", value, known]).copy()
    frame = frame.sort_values([isin, "quarter_end", known]).drop_duplicates(
        [isin, "quarter_end"], keep="last")
    frame = frame.sort_values([isin, "quarter_end"])
    frame["prev"] = frame.groupby(isin)[value].shift(1)
    frame["prev_q"] = frame.groupby(isin)["quarter_end"].shift(1)
    frame["chg"] = frame[value] - frame["prev"]
    frame["gap"] = (frame["quarter_end"] - frame["prev_q"]).dt.days
    known_ist = (pd.to_datetime(frame[known], utc=True).dt.tz_convert(IST)
                 .dt.tz_localize(None).dt.normalize())
    frame["known_lag_days"] = (known_ist - frame["quarter_end"]).dt.days
    timely = frame["known_lag_days"].between(0, max_known_lag_days)
    return frame[(frame["gap"].between(min_days, max_days)) & frame["chg"].notna() & timely]


def promoter_events(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame) -> pd.DataFrame:
    """Promoter % q/q change at the filing's own availability time."""
    shp = con.execute(
        """SELECT isin, TRY_CAST(quarter_end AS DATE) AS quarter_end, promoter_pct, known_at_utc
           FROM shp_index WHERE promoter_pct IS NOT NULL AND known_at_utc IS NOT NULL"""
    ).df()
    if shp.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    shp = _quarterly_changes(shp, "promoter_pct", "isin", "known_at_utc")
    shp = shp[shp["chg"].abs() >= PROMOTER_CHANGE_PP].merge(isin_entity_map(con), on="isin", how="inner")
    if shp.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    shp["avail"] = pit_sessions(shp["known_at_utc"], pd.DatetimeIndex(cal["date"])).to_numpy()
    shp = shp.dropna(subset=["avail"]).copy()
    shp["date_known"] = pd.to_datetime(shp["avail"])
    i_map = cal.set_index("date")["i"].to_dict()
    shp["i"] = shp["date_known"].map(i_map)
    shp = shp.dropna(subset=["i"])
    shp["company"] = shp["entity_id"]
    shp["signal"] = np.where(shp["chg"] > 0, "promoter_up", "promoter_down")
    shp["direction"] = np.where(shp["chg"] > 0, "up", "down")
    shp["strength"] = shp["chg"].abs()
    shp["detail"] = [
        _detail(promoter_pct=now, prev=prev, chg_pp=chg, quarter_end=str(q)[:10])
        for now, prev, chg, q in zip(shp["promoter_pct"], shp["prev"], shp["chg"], shp["quarter_end"])
    ]
    return shp[["company", "date_known", "signal", "direction", "strength", "detail", "i"]].reset_index(drop=True)


def category_events(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame,
                    structured_db: Path | None) -> tuple[pd.DataFrame, str]:
    """FPI / MF / insurance % q/q change from the T-209 structured universe store."""
    empty = pd.DataFrame(columns=[*_COLUMNS, "i"])
    if structured_db is None or not Path(structured_db).exists():
        return empty, f"structured store not found: {structured_db}"
    try:
        ro = sqlite3.connect(f"file:{Path(structured_db).as_posix()}?mode=ro", uri=True)
        frame = pd.read_sql_query(
            """SELECT isin, category, quarter_end, pct, pct_basis, known_at
               FROM shp_category
               WHERE category IN ('fpi_total', 'mf', 'insurance') AND pct IS NOT NULL
                 AND known_at IS NOT NULL""",
            ro,
        )
        ro.close()
    except sqlite3.Error as exc:  # a store on an unavailable drive must not stop the run
        return empty, f"structured store unreadable: {exc}"
    if frame.empty:
        return empty, "structured store has no category rows"
    frame["quarter_end"] = pd.to_datetime(frame["quarter_end"], errors="coerce")
    # The T-209 store's known_at is a naive IST broadcast timestamp.
    frame["known_at"] = (pd.to_datetime(frame["known_at"], errors="coerce")
                         .dt.tz_localize(IST).dt.tz_convert("UTC"))
    if "pct_basis" in frame.columns:
        frame = frame[frame["pct_basis"].fillna("total_shares").eq("total_shares")]
    frames = []
    for category, label in (("fpi_total", "fpi"), ("mf", "mf"), ("insurance", "insurance")):
        part = _quarterly_changes(frame[frame["category"].eq(category)],
                                  "pct", "isin", "known_at")
        part = part[part["chg"].abs() >= CATEGORY_CHANGE_PP]
        if part.empty:
            continue
        part = part.merge(isin_entity_map(con), on="isin", how="inner")
        if part.empty:
            continue
        part["avail"] = pit_sessions(part["known_at"], pd.DatetimeIndex(cal["date"])).to_numpy()
        part = part.dropna(subset=["avail"]).copy()
        part["date_known"] = pd.to_datetime(part["avail"])
        i_map = cal.set_index("date")["i"].to_dict()
        part["i"] = part["date_known"].map(i_map)
        part = part.dropna(subset=["i"])
        part["company"] = part["entity_id"]
        part["signal"] = np.where(part["chg"] > 0, f"{label}_up", f"{label}_down")
        part["direction"] = np.where(part["chg"] > 0, "up", "down")
        part["strength"] = part["chg"].abs()
        part["detail"] = [
            _detail(category=category, pct=now, prev=prev, chg_pp=chg, quarter_end=str(q)[:10])
            for now, prev, chg, q in zip(part["pct"], part["prev"], part["chg"], part["quarter_end"])
        ]
        frames.append(part[["company", "date_known", "signal", "direction", "strength", "detail", "i"]])
    if not frames:
        return empty, "structured store has no category change rows"
    return pd.concat(frames, ignore_index=True), f"{len(pd.concat(frames, ignore_index=True))} rows"


# --------------------------------------------------------------------------- #
# Earnings: bad quarter and peak quarter
# --------------------------------------------------------------------------- #
def results_events(con: duckdb.DuckDBPyConnection, cal: pd.DataFrame, start: str) -> pd.DataFrame:
    """Bad-quarter and peak-quarter signals at the TTM availability date."""
    floor = f"{max(2005, int(str(start)[:4]) - 6)}-01-01"
    raw = con.execute(
        """SELECT r.trading_isin, r.consolidated, r.period_end, r.fy_start, r.known_at_utc,
                  r.RevenueFromOperations AS rev, r.ProfitLossForPeriod AS pat,
                  r.InterestEarned AS interest, r.Expenses AS expense, r.FinanceCosts AS fin_cost,
                  r.DepreciationDepletionAndAmortisationExpense AS dep,
                  r.ytd_RevenueFromOperations AS ytd_rev, r.ytd_ProfitLossForPeriod AS ytd_pat,
                  r.PaidUpValueOfEquityShareCapital AS pu, r.FaceValueOfEquityShareCapital AS fv
           FROM results_key r WHERE TRY_CAST(r.period_end AS DATE) >= CAST(? AS DATE)""",
        [floor],
    ).df()
    raw = raw.merge(isin_entity_map(con), left_on="trading_isin", right_on="isin", how="left")
    raw = raw.dropna(subset=["entity_id", "period_end", "known_at_utc"]).copy()
    raw["rev"] = raw["rev"].fillna(raw["interest"])
    raw["avail_date"] = pit_sessions(raw["known_at_utc"], pd.DatetimeIndex(cal["date"])).to_numpy()
    raw["fy_start"] = raw["fy_start"].astype(str)
    # Availability of the 4-quarter TTM level itself (the level does not need the
    # YoY window that quarter_facts' avail_date covers).
    per_q = raw.dropna(subset=["entity_id", "period_end", "known_at_utc"]).copy()
    per_q["period_end"] = pd.to_datetime(per_q["period_end"])
    per_q["known_ns"] = utc_ns(per_q["known_at_utc"])
    per_q = per_q.sort_values(["entity_id", "period_end", "known_at_utc"]).drop_duplicates(
        ["entity_id", "period_end"], keep="last").sort_values(["entity_id", "period_end"])
    per_q["avail4_ns"] = per_q.groupby("entity_id", sort=False)["known_ns"].transform(
        lambda s: s.rolling(4, min_periods=4).max())
    facts = quarter_facts(pick_basis(raw))
    if facts.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    facts["period_end"] = pd.to_datetime(facts["period_end"])
    facts = facts.merge(per_q[["entity_id", "period_end", "avail4_ns"]],
                        on=["entity_id", "period_end"], how="left")
    facts["avail4"] = pit_sessions(pd.to_datetime(facts["avail4_ns"], unit="ns", utc=True),
                                   pd.DatetimeIndex(cal["date"])).to_numpy()
    facts = facts.sort_values(["entity_id", "period_end"]).reset_index(drop=True)
    facts["margin"] = facts["ttm_op"] / facts["ttm_rev"]
    facts["margin_prev"] = facts["ttm_op_prev"] / facts["ttm_rev_prev"]
    grouped = facts.groupby("entity_id", sort=False)
    facts["q_count"] = grouped.cumcount() + 1
    facts["pat_peak"] = grouped["ttm_pat"].transform(
        lambda s: s.rolling(PEAK_WINDOW_QUARTERS, min_periods=PEAK_MIN_QUARTERS).max())
    facts["margin_peak"] = grouped["margin"].transform(
        lambda s: s.rolling(PEAK_WINDOW_QUARTERS, min_periods=PEAK_MIN_QUARTERS).max())

    margin_chg = facts["margin"] - facts["margin_prev"]
    bad = facts[
        (facts["ttm_pat_yoy"] <= BAD_PAT_YOY) | (margin_chg <= BAD_MARGIN_PP)
    ].copy()
    peak = facts[
        (facts["q_count"] >= PEAK_MIN_QUARTERS)
        & (((facts["ttm_pat"] >= facts["pat_peak"]) & (facts["ttm_pat"] > 0))
           | ((facts["margin"] >= facts["margin_peak"]) & (facts["margin"] > 0)))
    ].copy()
    if bad.empty and peak.empty:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])

    i_map = cal.set_index("date")["i"].to_dict()
    frames: list[pd.DataFrame] = []
    for part, signal, avail_col in ((bad, "bad_quarter", "avail_date"),
                                    (peak, "peak_quarter", "avail4")):
        if part.empty:
            continue
        part = part.dropna(subset=[avail_col]).copy()
        part["date_known"] = pd.to_datetime(part[avail_col])
        part["i"] = part["date_known"].map(i_map)
        part = part.dropna(subset=["i"])
        part["company"] = part["entity_id"]
        part["signal"] = signal
        part["direction"] = "down"
        if signal == "bad_quarter":
            part["strength"] = np.maximum(
                part["ttm_pat_yoy"].fillna(0).abs(),
                (part["margin"] - part["margin_prev"]).fillna(0).abs())
            part["detail"] = [
                _detail(ttm_pat_yoy=yoy, margin=now_m, margin_prev=prev_m, margin_chg_pp=(now_m - prev_m) * 100)
                for yoy, now_m, prev_m in zip(part["ttm_pat_yoy"], part["margin"], part["margin_prev"])
            ]
        else:
            part["strength"] = 1.0
            part["detail"] = [
                _detail(ttm_pat=pat, pat_peak=pk, margin=mgn, margin_peak=mpk)
                for pat, pk, mgn, mpk in zip(part["ttm_pat"], part["pat_peak"],
                                            part["margin"], part["margin_peak"])
            ]
        frames.append(part[["company", "date_known", "signal", "direction", "strength", "detail", "i"]]
                      .drop_duplicates(["company", "date_known", "signal"]))
    if not frames:
        return pd.DataFrame(columns=[*_COLUMNS, "i"])
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_signals(snapshot: Path, start: str, end: str, structured_db: Path | None,
                  out: Path) -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con = connect(Path(snapshot))
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    notes: list[str] = []
    try:
        cal = trading_calendar(con, start, end)
        if cal.empty:
            raise SystemExit(f"no NSE sessions between {start} and {end}")
        market, observed = market_events(con, start, end)
        notes.append(f"daily panel rows: {observed:,}; market signals: {len(market):,}")
        insider = insider_events(con, cal)
        notes.append(f"insider/pledge signals: {len(insider):,}")
        deals = deal_events(con, cal)
        notes.append(f"bulk/block institutional signals: {len(deals):,}")
        promoter = promoter_events(con, cal)
        notes.append(f"promoter q/q signals: {len(promoter):,}")
        structured_path = Path(structured_db) if structured_db else None
        category, category_note = category_events(con, cal, structured_path)
        notes.append(f"FPI/MF/insurance q/q signals: {len(category):,} ({category_note})")
        earnings = results_events(con, cal, start)
        notes.append(f"earnings signals: {len(earnings):,}")
    finally:
        con.close()

    frames = [frame for frame in (market, insider, deals, promoter, category, earnings) if not frame.empty]
    if not frames:
        raise SystemExit("no signals were built")
    signals = pd.concat(frames, ignore_index=True)
    signals["date_known"] = pd.to_datetime(signals["date_known"]).dt.normalize()
    signals = signals.drop_duplicates(["company", "date_known", "signal"]).sort_values(
        ["date_known", "company", "signal"]).reset_index(drop=True)
    signals["detail"] = signals["detail"].fillna("")
    signals = signals[signals["date_known"].between(pd.Timestamp(start), pd.Timestamp(end))]
    signals[["company", "date_known", "signal", "direction", "strength", "detail"]].to_csv(
        out / "flow_signal.csv", index=False)
    counts = signals.groupby(["signal", "direction"]).size().rename("firings").reset_index()
    counts.to_csv(out / "signal_firings.csv", index=False)
    for note in notes:
        print(f"  {note}")
    print(f"  wrote {len(signals):,} signals to {out / 'flow_signal.csv'}")
    return signals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-235 capital-flow signals")
    parser.add_argument("--out", default=".tmp/t235", help="output directory")
    parser.add_argument("--snapshot", default=None, help="truth snapshot path")
    parser.add_argument("--start", default="2019-01-01", help="first price session")
    parser.add_argument("--end", default=None, help="last price session (default: snapshot end)")
    parser.add_argument("--structured", default=os.environ.get("REALITY_STRUCTURED_DB", STRUCTURED_DEFAULT),
                        help="T-209 structured_universe.db (FPI/MF/insurance categories)")
    args = parser.parse_args(argv)
    snapshot = Path(args.snapshot) if args.snapshot else default_snapshot()
    if args.end:
        end = args.end
    else:
        con = connect(snapshot)
        end = str(con.execute("SELECT max(date) FROM px_daily").fetchone()[0])
        con.close()
    structured = Path(args.structured) if args.structured else None
    build_signals(snapshot, args.start, end, structured, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
