"""T-235 flow signals and after-signal study: rules, timing and placebo.

Every test runs on synthetic frames or an in-memory DuckDB; no snapshot is read.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

from reality_engine.research import flow_events as ev
from reality_engine.research import flow_signals as fs
from reality_engine.research.factor_weights import pit_sessions


# --------------------------------------------------------------------------- #
# Named-party classification (bulk/block deals)
# --------------------------------------------------------------------------- #
def test_client_classification_uses_insurance_then_fund_then_foreign():
    assert fs.classify_client("ICICI PRUDENTIAL LIFE INSURANCE COMPANY LIMITED") == "insurance"
    assert fs.classify_client("SBI MUTUAL FUND") == "mf"
    assert fs.classify_client("Kotak Mahindra Asset Management Company") == "mf"
    assert fs.classify_client("ISHARES CORE MSCI EMERGING MARKETS ETF") == "fii"
    assert fs.classify_client("NORGES BANK ON ACCOUNT OF THE GOVERNMENT PENSION FUND GLOBAL") == "fii"
    assert fs.classify_client("GRAVITON RESEARCH CAPITAL LLP") == "other"
    assert fs.classify_client("") == "other"


# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #
def test_delivery_spike_needs_ratio_level_and_a_usable_median():
    assert fs.delivery_spike(2.0, 55.0, 25.0, 0.01) == "delivery_spike_up"
    assert fs.delivery_spike(2.5, 55.0, 25.0, -0.01) == "delivery_spike_down"
    assert fs.delivery_spike(1.99, 55.0, 25.0, 0.01) is None
    assert fs.delivery_spike(2.5, 39.9, 25.0, 0.01) is None  # absolute level floor
    assert fs.delivery_spike(2.5, 55.0, 19.9, 0.01) is None  # thin median
    assert fs.delivery_spike(2.5, 55.0, 25.0, float("nan")) is None


def test_delivery_trend_is_a_ratio_and_needs_a_base():
    assert fs.delivery_trend(1.5, 30.0) == "delivery_trend_up"
    assert fs.delivery_trend(1 / 1.5, 30.0) == "delivery_trend_down"
    assert fs.delivery_trend(1.49, 30.0) is None
    assert fs.delivery_trend(1.9, 29.9) is None


def test_volume_spike_needs_ratio_liquidity_and_a_price_sign():
    floor = fs.VALUE_MEDIAN_FLOOR_INR
    assert fs.volume_spike(3.0, floor, floor, -0.02) == "volume_spike_down"
    assert fs.volume_spike(2.99, floor, floor, 0.02) is None
    assert fs.volume_spike(4.0, floor, floor / 2, 0.02) is None
    assert fs.volume_spike(4.0, floor / 2, floor, 0.02) is None
    assert fs.volume_spike(4.0, floor, floor, float("nan")) is None


# --------------------------------------------------------------------------- #
# Clusters and cooldowns
# --------------------------------------------------------------------------- #
def test_trailing_window_is_inclusive_and_resets_per_company():
    frame = pd.DataFrame({
        "company": ["A", "A", "A", "B"],
        "date": pd.to_datetime(["2024-01-01", "2024-01-15", "2024-01-31", "2024-01-31"]),
        "value": [10.0, 20.0, 30.0, 7.0],
        "n": [1, 1, 1, 1],
    })
    got = fs.trailing_window(frame, "value", days=30, count="n")
    got = got[got["company"].eq("A")].set_index("date")
    assert got.loc["2024-01-15", "window_value"] == 30.0
    assert got.loc["2024-01-31", "window_value"] == 60.0  # Jan 1 == Jan 31 - 30 days
    assert got.loc["2024-01-31", "window_count"] == 3.0
    other = fs.trailing_window(frame, "value", days=30, count="n")
    assert other[other["company"].eq("B")]["window_value"].iloc[0] == 7.0


def test_cooldown_keeps_the_first_firing_per_company_and_signal():
    events = pd.DataFrame({
        "company": ["A", "A", "A", "B", "B"],
        "signal": ["s"] * 5,
        "i": [10, 20, 45, 10, 45],
        "row": [0, 1, 2, 3, 4],
    })
    kept = fs.apply_cooldown(events, ("company", "signal"))
    assert list(kept["row"]) == [0, 2, 3, 4]


# --------------------------------------------------------------------------- #
# Point-in-time: a filing is usable only from the session its inputs were public
# --------------------------------------------------------------------------- #
def test_filing_after_close_is_known_only_next_session():
    cal = pd.bdate_range("2024-01-01", "2024-01-10")
    stamps = pd.Series(pd.to_datetime([
        "2024-01-02 10:00:00+05:30",
        "2024-01-02 15:31:00+05:30",
        "2024-01-06 10:00:00+05:30",  # Saturday
    ], utc=True))
    got = pit_sessions(stamps, cal)
    assert got.iloc[0] == pd.Timestamp("2024-01-02")
    assert got.iloc[1] == pd.Timestamp("2024-01-03")
    assert got.iloc[2] == pd.Timestamp("2024-01-08")


def test_event_returns_uses_the_entry_session_and_never_maps_an_earlier_filing_forward():
    con = duckdb.connect()
    con.execute(
        """CREATE TABLE t235_ret(entity_id VARCHAR, date DATE, i BIGINT, close DOUBLE,
                                 tr_close DOUBLE, exc_60_lag DOUBLE, exc_5 DOUBLE,
                                 exc_20 DOUBLE, exc_60 DOUBLE, exc_120 DOUBLE, exc_250 DOUBLE)"""
    )
    con.execute(
        """INSERT INTO t235_ret VALUES
           ('A','2024-01-02',1,100,100,0,0.10,0.1,0.1,0.1,0.1),
           ('A','2024-01-03',2,101,101,0,0.05,0.1,0.1,0.1,0.1)"""
    )
    signals = pd.DataFrame({
        "company": ["A", "A", "A"],
        "date_known": pd.to_datetime(["2024-01-02", "2024-01-03", "2023-12-01"]),
        "signal": ["s", "s", "s"],
        "direction": ["down", "up", "up"],
        "strength": [1.0, 1.0, 1.0],
    })
    joined, dropped = ev.event_returns(con, signals)
    around = joined.set_index("date_known")
    assert joined["i"].tolist() == [1, 2]
    assert around.loc["2024-01-02", "sign"] == -1.0
    assert around.loc["2024-01-02", "sign_5"] == -0.10
    assert around.loc["2024-01-03", "sign_5"] == 0.05
    assert dropped == 1  # a date before the price panel is dropped, not collapsed onto day 1
    con.close()


# --------------------------------------------------------------------------- #
# Statistics: Newey-West cell, BH, placebo
# --------------------------------------------------------------------------- #
def test_cell_stats_applies_the_direction_sign():
    rows = []
    for k in range(40):
        rows.append({"company": f"C{k}", "date_known": pd.Timestamp("2024-01-02") + pd.Timedelta(days=k),
                     "signal": "s", "direction": "up", "sign": 1.0,
                     "exc_5": 0.05 if k < 30 else -0.01,
                     "exc_20": 0.0, "exc_60": 0.0, "exc_120": 0.0, "exc_250": 0.0})
    cells = ev.cell_stats(pd.DataFrame(rows), ["signal"]).set_index("horizon")
    assert cells.loc[5, "n"] == 40
    assert cells.loc[5, "hit"] == 0.75
    assert cells.loc[5, "mean"] == pytest.approx(0.035)
    rows_down = pd.DataFrame(rows).assign(direction="down", sign=-1.0)
    cells_down = ev.cell_stats(rows_down, ["signal"]).set_index("horizon")
    assert cells_down.loc[5, "mean"] == pytest.approx(-0.035)


def test_bh_adjust_is_monotone_and_not_below_the_raw_p():
    p = np.array([0.001, 0.01, 0.02, 0.5, np.nan])
    q = ev.bh_adjust(p)
    assert np.isnan(q[-1])
    assert np.all(q[:-1] >= p[:-1] - 1e-15)
    assert q[0] == 0.004
    assert q[3] == 0.5
    order = np.argsort(p[:-1])
    assert np.all(np.diff(q[:-1][order]) >= -1e-15)


def test_placebo_draws_same_stock_dates_for_every_seed():
    rng = np.random.default_rng(7)
    con = duckdb.connect()
    con.execute("CREATE TABLE t235_cal(date DATE, i BIGINT)")
    con.execute("CREATE TABLE t235_ret(entity_id VARCHAR, date DATE, i BIGINT, exc_5 DOUBLE)")
    dates = pd.bdate_range("2024-01-01", periods=200)
    con.executemany("INSERT INTO t235_cal VALUES (?, ?)", [(d.date(), i) for i, d in enumerate(dates)])
    con.executemany(
        "INSERT INTO t235_ret VALUES (?, ?, ?, ?)",
        [("A", d.date(), i, float(rng.normal(0, 0.02))) for i, d in enumerate(dates)],
    )
    events = pd.DataFrame({
        "company": ["A"] * 50,
        "signal": ["s"] * 50,
        "direction": ["up"] * 50,
        "date_known": dates[:50],
    })
    out = ev.placebo_frame(con, events, 5, seeds=20)
    con.close()
    assert len(out) == 20
    assert set(out["seed"]) == set(range(20))
    assert out["n"].min() == 50
    assert abs(out["placebo_mean"].mean()) < 0.01  # random dates: no forward drift
    assert out["placebo_mean"].nunique() > 1


# --------------------------------------------------------------------------- #
# Look-back and pairs
# --------------------------------------------------------------------------- #
def _synthetic_lookback():
    dates = pd.bdate_range("2023-01-02", periods=300)
    sessions = {("A", 2023): np.arange(300)}
    moves = pd.DataFrame({
        "company": ["A", "A"],
        "date": [dates[200], dates[240]],
        "direction": ["up", "up"],
        "i": [200, 240],
        "year": [2023, 2023],
    })
    events = pd.DataFrame({
        "company": ["A", "A"],
        "date_known": [dates[150], dates[230]],
        "signal": ["planted", "planted"],
        "direction": ["up", "up"],
        "i": [150, 230],
        "year": [2023, 2023],
    })
    return events, moves, sessions


def test_lookback_finds_a_planted_lead_and_hit():
    events, moves, sessions = _synthetic_lookback()
    out = ev.lookback_study(events, moves, sessions, seeds=5).iloc[0]
    assert out["recall"] == 1.0  # both moves had a firing in the prior 90 sessions
    assert out["precision"] == 1.0  # both firings were followed by a move within 60
    assert out["n_moves"] == 2 and out["n_firings"] == 2


def test_pair_study_pairs_firings_within_thirty_sessions():
    events = pd.DataFrame({
        "company": ["A", "A", "B"],
        "signal": ["a", "b", "a"],
        "direction": ["up", "up", "up"],
        "i": [10, 20, 100],
        "date_known": pd.to_datetime(["2024-01-01", "2024-01-10", "2024-06-03"]),
        "sign": [1.0, 1.0, 1.0],
        **{f"exc_{h}": [0.0, 0.0, 0.0] for h in ev.HORIZONS},
    })
    pairs = ev.pair_study(events)
    assert len(pairs) == 1
    assert pairs.iloc[0]["pair"] == "a+b"
    assert pairs.iloc[0]["company"] == "A"
