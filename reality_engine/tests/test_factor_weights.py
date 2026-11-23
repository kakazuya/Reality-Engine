"""T-118 factor weight study: point-in-time, TTM and IC checks on tiny fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reality_engine.research import factor_weights as fw

SESSIONS = pd.DatetimeIndex(pd.bdate_range("2024-01-08", periods=3))


# --------------------------------------------------------------------------- #
# Point in time
# --------------------------------------------------------------------------- #
def test_same_day_before_close_is_usable_that_session():
    known = pd.Series([pd.Timestamp("2024-01-09 10:00", tz="UTC")])  # 15:30 IST exactly
    assert fw.pit_sessions(known, SESSIONS).iloc[0] == pd.Timestamp("2024-01-09")


def test_after_close_counts_from_the_next_session():
    known = pd.Series([pd.Timestamp("2024-01-09 10:00:01", tz="UTC")])  # 15:30:01 IST
    assert fw.pit_sessions(known, SESSIONS).iloc[0] == pd.Timestamp("2024-01-10")


def test_weekend_filing_uses_the_next_session():
    known = pd.Series([pd.Timestamp("2024-01-06 12:00", tz="UTC")])  # Saturday evening IST
    assert fw.pit_sessions(known, SESSIONS).iloc[0] == pd.Timestamp("2024-01-08")


def test_filing_past_the_last_session_is_nat():
    known = pd.Series([pd.Timestamp("2024-01-10 11:00", tz="UTC")])
    assert pd.isna(fw.pit_sessions(known, SESSIONS).iloc[0])


def test_fact_known_after_the_rebalance_is_not_used():
    panel = pd.DataFrame(
        {"date": pd.to_datetime(["2024-02-29", "2024-03-28"]), "entity_id": ["e1", "e1"]}
    )
    facts = pd.DataFrame(
        {"entity_id": ["e1"], "avail_date": pd.to_datetime(["2024-03-05"]), "ttm_pat_yoy": [0.25]}
    )
    out = fw.attach_asof(panel, facts, ["ttm_pat_yoy"])
    assert pd.isna(out.loc[out["date"] == pd.Timestamp("2024-02-29"), "ttm_pat_yoy"]).all()
    assert out.loc[out["date"] == pd.Timestamp("2024-03-28"), "ttm_pat_yoy"].iloc[0] == 0.25


# --------------------------------------------------------------------------- #
# TTM and basis
# --------------------------------------------------------------------------- #
def _quarters(entity: str, basis: str) -> pd.DataFrame:
    ends = ["2022-06-30", "2022-09-30", "2022-12-31", "2023-03-31",
            "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"]
    fys = ["2022-04-01"] * 4 + ["2023-04-01"] * 4
    rev = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
    rows = []
    for end, fy, value in zip(ends, fys, rev):
        rows.append(
            {
                "entity_id": entity,
                "consolidated": basis,
                "period_end": end,
                "fy_start": fy,
                "known_at_utc": pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=30),
                "rev": value,
                "pat": value / 10,
                "ytd_rev": float("nan"),
                "ytd_pat": float("nan"),
                "expense": value * 0.8,
                "fin_cost": 0.5,
                "dep": 0.5,
                "pu": 100.0,
                "fv": 10.0,
            }
        )
    return pd.DataFrame(rows)


def test_ttm_from_four_quarters():
    facts = fw.quarter_facts(_quarters("e1", "Consolidated"))
    last = facts[facts["period_end"] == pd.Timestamp("2024-03-31")].iloc[0]
    assert last["ttm_rev"] == pytest.approx(14 + 15 + 16 + 17)
    assert last["ttm_rev_yoy"] == pytest.approx((14 + 15 + 16 + 17) / (10 + 11 + 12 + 13) - 1)


def test_ttm_uses_ytd_delta_when_a_quarter_value_is_missing():
    fin = _quarters("e1", "Consolidated")
    # 2022-09-30 quarter revenue missing from the filing; YTD (Q1+Q2) is there.
    mask = fin["period_end"] == "2022-09-30"
    fin.loc[mask, "rev"] = np.nan
    fin.loc[mask, "ytd_rev"] = 21.0
    fin.loc[mask, "ytd_pat"] = 2.1
    fin.loc[fin["period_end"] == "2022-06-30", "ytd_rev"] = 10.0  # Q1 YTD = Q1
    fin.loc[fin["period_end"] == "2022-06-30", "ytd_pat"] = 1.0
    facts = fw.quarter_facts(fin)
    ttm_2023 = facts[facts["period_end"] == pd.Timestamp("2023-03-31")].iloc[0]
    assert ttm_2023["ttm_rev"] == pytest.approx(10 + 11 + 12 + 13)  # derived Q2 = 21 - 10
    last = facts[facts["period_end"] == pd.Timestamp("2024-03-31")].iloc[0]
    assert last["ttm_rev_yoy"] == pytest.approx(62.0 / 46.0 - 1)


def test_ttm_needs_four_consecutive_quarters():
    fin = _quarters("e1", "Consolidated").iloc[1:]  # drop the oldest quarter -> 7 left
    facts = fw.quarter_facts(fin)
    assert facts[facts["period_end"] == pd.Timestamp("2023-03-31")]["ttm_rev"].isna().all()


def test_ttm_available_only_from_its_filing_date():
    # regression: pandas 3 datetimes are microsecond based; a nanosecond cast that
    # forgets this stamps every fact in 1970 and the panel never updates
    facts = fw.quarter_facts(_quarters("e1", "Consolidated"))
    last = facts.iloc[-1]
    assert last["avail_date"] == pd.Timestamp("2024-04-30")


def test_promoter_availability_is_the_filing_date():
    shp = pd.DataFrame(
        {
            "entity_id": ["e1"] * 5,
            "quarter_end": pd.date_range("2024-03-31", periods=5, freq="QE"),
            "promoter_pct": [55.0, 55.0, 54.0, 54.0, 53.0],
            "known_at_utc": [
                pd.Timestamp("2024-04-20 10:00", tz="UTC"),
                pd.Timestamp("2024-07-20 10:00", tz="UTC"),
                pd.Timestamp("2024-10-20 10:00", tz="UTC"),
                pd.Timestamp("2025-01-20 10:00", tz="UTC"),
                pd.Timestamp("2025-04-20 10:00", tz="UTC"),
            ],
        }
    )
    out = fw.promoter_history(shp)
    assert out["avail_date"].min() == pd.Timestamp("2024-04-20")
    assert out["promoter_chg_4q"].iloc[4] == pytest.approx(-2.0)


def test_basis_is_never_mixed():
    cons = _quarters("e1", "Consolidated").iloc[:5]
    stand = _quarters("e1", "Non-Consolidated").iloc[5:]
    mixed = pd.concat([cons, stand], ignore_index=True)
    chosen = fw.pick_basis(mixed)
    assert set(chosen["consolidated"].unique()) == {"Consolidated"}
    assert len(chosen) == 5


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def test_newey_west_tstat_matches_hand_calculation():
    # mean 3, Bartlett kernel with 4 lags -> variance 2.08, t = 3 / sqrt(2.08 / 5)
    assert fw.newey_west_tstat(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 5) == pytest.approx(4.6513, abs=0.001)


def test_ic_sign_on_a_planted_factor():
    rng = np.random.default_rng(7)
    panels = []
    for month in range(24):
        n = 40
        factor = rng.normal(size=n)
        target = 0.02 * factor + rng.normal(scale=0.01, size=n)
        panels.append(
            pd.DataFrame({"date": pd.Timestamp("2022-01-31") + pd.offsets.MonthEnd(month),
                          "factor": factor, "target": target})
        )
    frame = pd.concat(panels, ignore_index=True)
    ic = fw.monthly_ic(frame, "factor", "target")
    assert ic.mean() > 0.5
    assert fw.newey_west_tstat(ic, 5) > 3.0
    assert (ic > 0).mean() == 1.0


# --------------------------------------------------------------------------- #
# Re-rating / discovery factors
# --------------------------------------------------------------------------- #
def _rerating_panel() -> pd.DataFrame:
    """13 monthly rows: price doubles and TTM sales grow 25% over the 12 months."""
    dates = pd.date_range("2024-01-31", periods=13, freq="ME")
    price = 100 * (2.0 ** (np.arange(13) / 12))
    sales = 100 * (1.25 ** (np.arange(13) / 12))
    return pd.DataFrame(
        {
            "date": dates,
            "entity_id": "e1",
            "close": price,
            "adj_close": price,
            "adj_close_252": price[0],
            "shares": 10.0,
            "ttm_rev": sales,
            "ttm_pat": np.r_[np.full(12, -5.0), 5.0],  # negative PAT except the last row
        }
    )


def test_rerating_share_of_the_price_move():
    out = fw.rerating_factors(_rerating_panel())
    last = out.iloc[-1]
    assert last["ps_chg_12m"] == pytest.approx(np.log(16 / 10), abs=1e-9)
    assert last["rerating_share_12m"] == pytest.approx(np.log(16 / 10) / np.log(2.0))
    assert last["rerating_share_12m"] + last["sales_share_12m"] == pytest.approx(1.0)
    assert out["ps_chg_3m"].notna().sum() == 10
    assert out["ps_chg_6m"].notna().sum() == 7
    assert out["ps_chg_12m"].notna().sum() == 1


def test_pe_factors_need_positive_ttm_pat():
    out = fw.rerating_factors(_rerating_panel())
    assert out["pe_ratio"].notna().sum() == 1  # only the profitable row
    assert out["pe_chg_12m"].isna().all()  # no positive-PAT row 12 months earlier
    assert out["ps_ratio"].notna().all()


def test_ic_table_lists_size_as_a_factor_and_a_control():
    rng = np.random.default_rng(3)
    rows = []
    for month in range(8):
        n = 30
        size = rng.normal(size=n)
        rows.append(
            pd.DataFrame(
                {
                    "date": pd.Timestamp("2023-01-31") + pd.offsets.MonthEnd(month),
                    "entity_id": [f"e{i}" for i in range(n)],
                    "size": size,
                    "size_sn": size,
                    "excess_126": -0.01 * size + rng.normal(scale=0.01, size=n),
                    "excess_252": -0.01 * size + rng.normal(scale=0.01, size=n),
                    "excess_504": -0.01 * size + rng.normal(scale=0.01, size=n),
                }
            )
        )
    out = fw.ic_stats(pd.concat(rows, ignore_index=True), ["size"])
    assert len(out) == 3
    assert out["mean_ic"].lt(0).all()


def test_joint_model_drops_a_factor_that_would_empty_the_cross_section():
    rng = np.random.default_rng(11)
    n = 300
    frame = pd.DataFrame(
        {
            "date": np.repeat(pd.date_range("2022-01-31", periods=30, freq="ME"), n),
            "ttm_rev_yoy_z": rng.normal(size=30 * n),
            "reversal_1m_z": rng.normal(size=30 * n),
            "insider_net_to_mcap_z": np.r_[rng.normal(size=30 * 40), np.full(30 * (n - 40), np.nan)],
        }
    )
    chosen = fw.fm_factor_list(frame, min_names=150)
    assert "insider_net_to_mcap" not in chosen
    assert set(chosen) >= {"ttm_rev_yoy", "reversal_1m"}


# --------------------------------------------------------------------------- #
# Sector re-rating and the cyclical-peak factors
# --------------------------------------------------------------------------- #
def _sector_panel(n_entities: int = 30, n_dates: int = 25) -> pd.DataFrame:
    dates = pd.date_range("2022-01-31", periods=n_dates, freq="ME")
    rows = []
    for e in range(n_entities):
        for i, day in enumerate(dates):
            rows.append(
                {
                    "date": day,
                    "entity_id": f"e{e}",
                    "sector": "s1" if e < n_entities // 2 else "s2",
                    "ps_ratio": -3.0 + 0.01 * e + (0.1 if e < n_entities // 2 else -0.05) * i,
                    "pe_ratio": 2.0 + 0.01 * e - 0.05 * i,
                    "op_margin": 0.05 + 0.01 * i + 0.001 * e,
                    "ttm_pat": 100.0 + i,
                    "q_pat_yoy": float(e),
                }
            )
    return pd.DataFrame(rows)


def test_sector_re_rating_and_relative_multiple():
    out = fw.sector_factors(_sector_panel())
    last = out["date"].max()
    tail = out[out["date"] == last].set_index("entity_id")
    changes = tail.groupby("sector")["sector_ps_chg_12m"].first()
    assert changes["s1"] == pytest.approx(1.2)  # 12 rows of +0.1
    assert changes["s2"] == pytest.approx(-0.6)  # 12 rows of -0.05
    assert tail.loc["e0", "ps_vs_sector"] == pytest.approx(-0.07)  # -3+2.4 vs median -3+0.07+2.4
    assert out["sector_ps_chg_36m"].isna().all()  # only 25 months of history


def test_peak_percentiles_and_growth_trap():
    out = fw.sector_factors(_sector_panel())
    ordered = out.sort_values(["entity_id", "date"])
    e0 = ordered[ordered["entity_id"] == "e0"]
    assert pd.isna(e0["op_margin_pctile"].iloc[0])  # needs 24 months of history
    assert e0["op_margin_pctile"].iloc[-1] == pytest.approx(1.0)  # it rose every month
    last = out[out["date"] == out["date"].max()].set_index("entity_id")
    assert last.loc["e29", "peak_growth_trap"] == 1.0  # top growth tercile at a peak margin
    assert last.loc["e10", "peak_growth_trap"] == 0.0  # solid growth, ordinary margin


def test_quintile_spread_reads_a_binary_factor_as_two_groups():
    frame = pd.DataFrame({"flag": [0.0] * 90 + [1.0] * 10, "ret": [0.01] * 90 + [0.05] * 10})
    assert fw.quintile_spread(frame, "flag", "ret") == pytest.approx(0.04)


def test_sector_split_reports_the_price_move_components():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-31"] * 4),
            "sector": ["IT", "IT", "Banks", "Banks"],
            "px_log_chg_12m": [0.2, 0.4, -0.1, 0.1],
            "sales_log_chg_12m": [0.3, 0.5, 0.2, 0.0],
            "ps_chg_12m": [-0.1, -0.1, -0.3, 0.1],
            "sales_share_12m": [1.5, 1.25, 2.0, 0.0],
            "rerating_share_12m": [-0.5, -0.25, -1.0, 1.0],
        }
    )
    out = fw.sector_split(frame)
    it = out[(out["window"] == "pooled") & (out["sector"] == "IT")].iloc[0]
    assert it["names"] == 2
    assert it["sales_share"] == pytest.approx(1.375)


# --------------------------------------------------------------------------- #
# Universe / forward return from the snapshot schema (in-memory DuckDB)
# --------------------------------------------------------------------------- #
def _price_fixture():
    """450 sessions, one liquid NSE company and one illiquid BSE company."""
    sessions = pd.DatetimeIndex(pd.bdate_range("2024-01-01", periods=450))
    idx = np.arange(len(sessions))
    a = pd.DataFrame(
        {
            "exch": "NSE",
            "entity_id": "e1",
            "date": sessions,
            "isin": "INE000000001",
            "symbol": "AAA",
            "close": 100 * 1.001 ** idx,
            "adj_close": 100 * 1.001 ** idx,
            "tr_close": 100 * 1.002 ** idx,
            "value_inr": 2e7,
            "delivery_pct": 50.0,
        }
    )
    b = pd.DataFrame(
        {
            "exch": "BSE",
            "entity_id": "e2",
            "date": sessions,
            "isin": "INE000000002",
            "symbol": "BBB",
            "close": 50.0,
            "adj_close": 50.0,
            "tr_close": 50.0,
            "value_inr": 5e6,  # below the Rs 1 crore floor
            "delivery_pct": 10.0,
        }
    )
    tri = pd.DataFrame(
        {
            "index_name": "NIFTY 500",
            "date": sessions.strftime("%Y-%m-%d"),
            "tri": 1000 * 1.0005 ** idx,
        }
    )
    return pd.concat([a, b], ignore_index=True), tri, sessions


def test_universe_liquidity_filter_and_forward_return_from_tr_close():
    import duckdb

    px, tri, sessions = _price_fixture()
    con = duckdb.connect(":memory:")
    con.register("px_df", px)
    con.register("tri_df", tri)
    con.execute("CREATE TABLE px_daily AS SELECT * FROM px_df")
    con.execute("CREATE TABLE index_tri AS SELECT * FROM tri_df")
    univ, cal = fw.build_price_panel(con, str(sessions[240].date()), str(sessions[-1].date()))
    con.close()

    assert set(univ["entity_id"]) == {"e1"}  # illiquid BSE name filtered out
    assert univ["excess_126"].notna().any()

    # last rebalance cannot have a 126-session forward window: dropped, never padded
    last_date = univ["date"].max()
    assert pd.isna(univ.loc[univ["date"] == last_date, "excess_126"]).all()

    row = univ.dropna(subset=["excess_126"]).iloc[0]
    i = int(cal.loc[cal["date"] == row["date"], "i"].iloc[0])
    tr = px.loc[px["entity_id"] == "e1", "tr_close"].to_numpy()
    bench = tri["tri"].to_numpy()
    expected = (tr[i + 126 - 1] / tr[i - 1] - 1) - (bench[i + 126 - 1] / bench[i - 1] - 1)
    assert row["excess_126"] == pytest.approx(expected, abs=1e-9)
