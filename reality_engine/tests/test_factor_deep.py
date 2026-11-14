"""T-210 factor-deep study: planted sectors/pairs/companies, permutation gates.

Every test runs on a synthetic panel; no snapshot and no pilot store is touched.
The planted effects are the four the brief names: an interaction, an opposite
pair, a redundant factor and a company-specific factor. A pure-noise panel must
yield no claim beyond what its own permutation runs yield.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from reality_engine.research import factor_deep as fd

FACTOR_NAMES = ["f1", "opp", "f5", "cond", "sig", "noise"]


def _month_end(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="BME")


def _calendar(dates: pd.DatetimeIndex, extra_days: int = 900) -> pd.DatetimeIndex:
    return pd.bdate_range(dates.min() - pd.Timedelta(days=10), dates.max() + pd.Timedelta(days=extra_days))


def _panel(
    periods: int = 40,
    n_companies: int = 160,
    n_sectors: int = 2,
    seed: int = 11,
    noise_target: bool = False,
    company_specific: bool = True,
) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """Planted panel: f1 earns, opp = -f1, f5 proxies f1, sig pays only when cond is high."""
    dates = _month_end("2020-01-31", periods)
    rng = np.random.default_rng(seed)
    rows = []
    per_sector = n_companies // n_sectors
    for date in dates:
        for sector_i in range(n_sectors):
            sector = f"S{sector_i}"
            for c in range(per_sector):
                entity = f"{sector}-{c}"
                f1 = float(rng.normal())
                opp = -f1 + 0.05 * float(rng.normal())
                f5 = 0.60 * f1 + 0.80 * float(rng.normal())
                sig = float(rng.normal())
                cond = float(rng.normal())
                bump = 1.5 * sig if cond > 0 else -1.5 * sig
                if noise_target:
                    excess = 1.0 * float(rng.normal())
                else:
                    excess = 0.8 * f1 + bump + 0.7 * float(rng.normal())
                if company_specific and sector_i == 0 and c == 0 and not noise_target:
                    excess = -0.8 * f1 - 1.5 * sig * (cond > 0) + 0.7 * float(rng.normal())
                rows.append({
                    "date": date, "entity_id": entity, "symbol": entity,
                    "sector": sector, "sector_group": sector,
                    "f1": f1, "opp": opp, "f5": f5, "sig": sig, "cond": cond,
                    "noise": float(rng.normal()),
                    "excess_126": excess, "excess_252": excess, "excess_504": excess,
                })
    panel = pd.DataFrame(rows).reset_index(drop=True)
    for factor in FACTOR_NAMES:
        mean = panel.groupby("date", observed=True)[factor].transform("mean")
        sd = panel.groupby("date", observed=True)[factor].transform("std").replace(0.0, np.nan)
        panel[factor + "_z"] = (panel[factor] - mean) / sd
    return panel, dates


# --------------------------------------------------------------------------- #
# Rank plumbing
# --------------------------------------------------------------------------- #
def test_rank_ic_is_one_for_a_planted_order_and_nan_for_a_thin_sample():
    y = np.arange(30, dtype=float)
    assert abs(fd.rank_ic(y, y) - 1.0) < 1e-12
    assert abs(fd.rank_ic(y, -y) + 1.0) < 1e-12
    assert np.isnan(fd.rank_ic(y[:10], y[:10]))


def test_avg_ranks_average_ties():
    got = fd.avg_ranks(np.array([1.0, 2.0, 2.0, 4.0]))
    np.testing.assert_allclose(got, [1.0, 2.5, 2.5, 4.0])


# --------------------------------------------------------------------------- #
# Correlations: an opposite pair moves together in exposures, oppositely in ICs
# --------------------------------------------------------------------------- #
def test_opposite_pair_is_labelled_opposite_and_the_proxy_rides_its_cluster():
    panel, _ = _panel()
    exposure = fd.exposure_corr(panel, factors=FACTOR_NAMES)
    labels = fd.pair_relations(exposure)
    row = labels[(labels["factor_a"] == "f1") & (labels["factor_b"] == "opp")].iloc[0]
    assert row["rho"] <= -fd.CORR_MOVE
    assert row["relation"] == "opposite"
    clusters = fd._clusters(exposure[exposure["group"] == "S0"])
    assert clusters["f1"] == clusters["opp"]
    assert clusters["f1"] != clusters.get("sig", "sig")


# --------------------------------------------------------------------------- #
# Redundancy: a proxy factor earns alone but not beside the factor it proxies
# --------------------------------------------------------------------------- #
def test_proxy_is_rewarded_univariately_but_redundant_in_the_joint_model():
    panel, dates = _panel()
    cal = _calendar(dates)
    ic_table = fd._sector_ic_table(panel, dates, cal, FACTOR_NAMES)
    uni = fd.univariate_sector(ic_table, "12m")
    exposure = fd.exposure_corr(panel, factors=FACTOR_NAMES)
    model = {"S0": ["f1", "f5"], "S1": ["f1", "f5"]}
    fm = fd.fama_macbeth_sector(panel, "12m", model)
    table = fd.redundancy_table(uni, fm, model, exposure)
    f5 = table[(table["group"] == "S0") & (table["factor"] == "f5")].iloc[0]
    f1 = table[(table["group"] == "S0") & (table["factor"] == "f1")].iloc[0]
    assert bool(f5["univariate_significant"])
    assert abs(f5["multivariate_nw_t"]) < fd.REDUNDANT_T
    assert bool(f5["redundant"])
    assert abs(f1["multivariate_nw_t"]) >= fd.REDUNDANT_T


# --------------------------------------------------------------------------- #
# Company estimates: one planted company differs from its sector after shrinkage
# --------------------------------------------------------------------------- #
def test_company_specific_sign_survives_shrinkage_towards_the_sector_prior():
    panel, dates = _panel(company_specific=True)
    cal = _calendar(dates)
    own = fd.company_estimates(panel, cal, "12m", as_of=cal[-1], factors=["f1"], min_months=24)
    assert len(own) > 100
    shrunk = fd.shrink_estimates(own, min_months=24)
    special = shrunk[shrunk["entity_id"] == "S0-0"].iloc[0]
    peer = shrunk[shrunk["entity_id"] == "S0-1"].iloc[0]
    assert special["own_ic"] < -0.3
    assert special["sector_prior_ic"] > 0.3
    assert special["shrink_weight"] > 0.0
    assert special["shrunk_ic"] - special["sector_prior_ic"] < -fd.COMPANY_DIFF
    assert special["shrunk_ic"] < peer["shrunk_ic"]
    assert abs(peer["shrunk_ic"] - peer["sector_prior_ic"]) < fd.COMPANY_DIFF
    gaps = fd.company_gaps(shrunk)
    assert (gaps["entity_id"] == "S0-0").any()


def test_company_estimates_drop_months_not_realised_by_as_of():
    panel, dates = _panel(periods=30)
    cal = _calendar(dates)
    cut = pd.Timestamp(dates[15])
    own = fd.company_estimates(panel, cal, "12m", as_of=cut, factors=["f1"], min_months=12)
    # 12m windows from the first 12 month-ends are realised by month 24; the cut
    # at month 16 leaves only the first ~4, below the floor.
    assert own.empty


# --------------------------------------------------------------------------- #
# Interactions: the planted pair is claimed, noise is not
# --------------------------------------------------------------------------- #
def test_planted_interaction_is_claimed_and_its_terciles_have_the_planted_sign():
    panel, _ = _panel()
    observed, null = fd.interaction_study(panel, ["12m"], FACTOR_NAMES, runs=20)
    claims = fd.interaction_claims(observed, null)
    got = claims[claims["claimed"]]
    assert len(got) >= 1
    hit = got[(got["factor_a"] == "sig") & (got["factor_b"] == "cond")]
    assert len(hit) >= 1
    assert hit.iloc[0]["mean_diff"] > 0.3
    assert abs(hit.iloc[0]["nw_t"]) >= fd.INTERACTION_T


def test_a_pure_noise_panel_yields_no_interaction_claim_beyond_its_placebo():
    panel, _ = _panel(seed=5, noise_target=True)
    observed, null = fd.interaction_study(panel, ["12m"], FACTOR_NAMES, runs=20)
    claims = fd.interaction_claims(observed, null)
    placebo = fd.interaction_placebo_counts(null)
    assert len(placebo) == 20
    assert int(claims["claimed"].sum()) <= max(placebo)


def test_stepwise_picks_the_planted_factors_and_ignores_noise():
    panel, _ = _panel(periods=30)
    rng = np.random.default_rng(3)
    frames = []
    for date in sorted(panel["date"].unique()):
        sub = panel[panel["date"] == date].reset_index(drop=True).copy()
        sub["excess_252"] = (0.7 * sub["f1"] - 0.6 * sub["sig"] + 0.5 * sub["cond"]
                             + 0.8 * rng.normal(size=len(sub)))
        frames.append(sub)
    pools = {"f1": 0.5, "sig": -0.5, "cond": 0.4, "noise": 0.0}
    selected, ic = fd.forward_stepwise(frames, "excess_252", pools)
    assert selected.get("f1") == 1
    assert selected.get("sig") == -1
    assert "noise" not in selected
    assert ic >= fd.STEP_MIN_GAIN


def test_candidate_pool_caps_and_keeps_the_strongest():
    pool = fd.candidate_pool({f"f{i}": 0.01 * i for i in range(30)})
    assert len(pool) == fd.STEP_POOL
    assert max(pool, key=lambda f: abs(pool[f])) == "f29"


def test_sparse_scores_the_next_month_only_with_information_known_at_t():
    panel, dates = _panel(periods=30)
    cal = _calendar(dates)
    rewarded = pd.DataFrame(columns=["horizon", "split", "group", "factor", "window", "date",
                                     "rated", "rewarded", "sign", "mean_ic", "nw_t", "months",
                                     "sign_share"])
    equal = {"f1": 1, "opp": -1, "noise": 1}
    monthly, _summary = fd.sparse_walk_forward(panel, rewarded, cal, "12m", equal_signs=equal,
                                               factors=FACTOR_NAMES)
    assert not monthly.empty
    changed = panel.copy()
    late = changed["date"] > dates[20]
    changed.loc[late, "excess_252"] = -changed.loc[late, "excess_252"]
    changed.loc[late, "excess_126"] = -changed.loc[late, "excess_126"]
    changed.loc[late, "excess_504"] = -changed.loc[late, "excess_504"]
    monthly2, _ = fd.sparse_walk_forward(changed, rewarded, cal, "12m", equal_signs=equal,
                                         factors=FACTOR_NAMES)
    early = monthly[monthly["date"] <= dates[20]][["group", "date", "selected", "test_month"]]
    early2 = monthly2[monthly2["date"] <= dates[20]][["group", "date", "selected", "test_month"]]
    pd.testing.assert_frame_equal(early.reset_index(drop=True), early2.reset_index(drop=True))


# --------------------------------------------------------------------------- #
# KPI arm plumbing (method pilot, no store needed)
# --------------------------------------------------------------------------- #
def test_fiscal_index_reads_quarter_labels():
    assert fd.fiscal_index("Q2FY26") == 2026 * 4 + 2
    assert fd.fiscal_index("H1 FY25") == 2025 * 4 + 2
    assert fd.fiscal_index("9M FY25") == 2025 * 4 + 3
    assert fd.fiscal_index("FY24") == 2024 * 4 + 4
    assert np.isnan(fd.fiscal_index("unknown"))


def test_kpi_panel_builds_yoy_and_change_in_yoy():
    raw = pd.DataFrame({
        "symbol": ["A"] * 9,
        "metric": ["order_book"] * 9,
        "dimension": ["total"] * 9,
        "value": [100.0, 110, 120, 130, 200, 220, 240, 260, 300],
        "unit": ["mn"] * 9,
        "fiscal_period": [f"Q{i}FY26" for i in range(1, 5)] + [f"Q{i}FY27" for i in range(1, 5)] + ["Q1FY28"],
        "known_at": pd.date_range("2025-06-30", periods=9, freq="QE"),
        "store": ["s"] * 9,
    })
    kpi = fd.kpi_factor_panel(raw)
    q5 = kpi[kpi["quarter"] == fd.fiscal_index("Q1FY27")].iloc[0]
    q9 = kpi[kpi["quarter"] == fd.fiscal_index("Q1FY28")].iloc[0]
    assert abs(q5["yoy"] - 1.0) < 1e-12   # 200 / 100 - 1
    assert abs(q9["yoy"] - 0.5) < 1e-12   # 300 / 200 - 1
    assert abs(q9["yoy_chg"] + 0.5) < 1e-12  # 0.5 - 1.0
    assert np.isnan(kpi.iloc[0]["yoy"])


# --------------------------------------------------------------------------- #
# Chunked panel builder and column-pruned loader
# --------------------------------------------------------------------------- #
def test_build_panel_parquet_matches_build_panel_and_prunes_columns(tmp_path):
    import duckdb
    from reality_engine.research import factor_weights as fw

    sessions = pd.DatetimeIndex(pd.bdate_range("2023-01-02", periods=600))
    idx = np.arange(len(sessions))
    px_frames = []
    for k in range(4):
        px_frames.append(pd.DataFrame({
            "exch": "NSE",
            "entity_id": f"E{k}",
            "date": sessions,
            "isin": f"INE00000000{k}",
            "symbol": f"SYM{k}",
            "close": (100.0 + 10 * k) * (1.0005 + 0.0001 * k) ** idx,
            "adj_close": (100.0 + 10 * k) * (1.0005 + 0.0001 * k) ** idx,
            "tr_close": (100.0 + 10 * k) * (1.0008 + 0.0001 * k) ** idx,
            "value_inr": 2e7,
            "delivery_pct": 45.0 + k,
        }))
    px = pd.concat(px_frames, ignore_index=True)
    tri = pd.DataFrame({
        "index_name": "NIFTY 500",
        "date": sessions.strftime("%Y-%m-%d"),
        "tri": 1000.0 * 1.0004 ** idx,
    })
    q_ends = pd.date_range("2022-03-31", "2025-03-31", freq="QE")
    res_rows = []
    shp_rows = []
    for k in range(4):
        for qi, qe in enumerate(q_ends):
            res_rows.append({
                "trading_isin": f"INE00000000{k}",
                "consolidated": "Consolidated",
                "period_end": qe.strftime("%Y-%m-%d"),
                "fy_start": f"FY{qe.year if qe.month >= 4 else qe.year - 1}",
                "known_at_utc": (qe + pd.Timedelta(days=30)).strftime("%Y-%m-%dT10:00:00Z"),
                "RevenueFromOperations": 1000.0 + 20 * qi + 50 * k,
                "ProfitLossForPeriod": 100.0 + 2 * qi + 10 * k,
                "InterestEarned": np.nan,
                "Expenses": 850.0 + 15 * qi,
                "FinanceCosts": 20.0,
                "DepreciationDepletionAndAmortisationExpense": 30.0,
                "ytd_RevenueFromOperations": np.nan,
                "ytd_ProfitLossForPeriod": np.nan,
                "PaidUpValueOfEquityShareCapital": 100.0,
                "FaceValueOfEquityShareCapital": 10.0,
            })
            shp_rows.append({
                "isin": f"INE00000000{k}",
                "quarter_end": qe.strftime("%Y-%m-%d"),
                "promoter_pct": 50.0 + 0.1 * qi + k,
                "known_at_utc": (qe + pd.Timedelta(days=20)).strftime("%Y-%m-%dT10:00:00Z"),
            })
    ins = pd.DataFrame({
        "symbol": ["SYM0", "SYM1"],
        "known_at_utc": ["2024-05-10T09:00:00Z", "2024-06-12T09:00:00Z"],
        "transaction_type": ["Buy", "Sell"],
        "securities_value": [5e6, 3e6],
        "intimation_date": ["2024-05-10", "2024-06-12"],
    })
    hist = pd.DataFrame({
        "symbol": [f"SYM{k}" for k in range(4)],
        "isin": [f"INE00000000{k}" for k in range(4)],
        "first_date": ["2020-01-01"] * 4,
        "last_date": ["2026-12-31"] * 4,
        "n_days": [1500] * 4,
    })
    ind = pd.DataFrame({
        "isin": [f"INE00000000{k}" for k in range(4)],
        "sector": ["Chemicals", "Chemicals", "Healthcare", "Healthcare"],
    })

    snap = tmp_path / "snap.duckdb"
    con = duckdb.connect(str(snap))
    for name, df in (
        ("px_daily", px), ("index_tri", tri), ("results_key", pd.DataFrame(res_rows)),
        ("shp_index", pd.DataFrame(shp_rows)), ("nse_insider", ins),
        ("symbol_isin_history", hist), ("company_industry", ind),
    ):
        con.register(f"_{name}", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _{name}")
    con.close()

    start, end = str(sessions[260].date()), str(sessions[-1].date())
    parquet_path = tmp_path / "panel.parquet"
    meta = fw.build_panel_parquet(snap, start, end, parquet_path, entity_batch_size=2, memory_limit="512MB", threads=1)
    assert parquet_path.exists()

    con = fw.connect(snap, memory_limit="512MB", threads=1)
    try:
        ref, ref_meta = fw.build_panel(con, start, end)
    finally:
        con.close()

    assert meta["rows"] == ref_meta["rows"]
    assert meta["companies"] == ref_meta["companies"]
    got = pd.read_parquet(parquet_path).sort_values(["date", "entity_id"]).reset_index(drop=True)
    ref = ref.sort_values(["date", "entity_id"]).reset_index(drop=True)
    assert set(got.columns) == set(ref.columns)
    got = got[ref.columns]
    for col in ref.columns:
        if pd.api.types.is_numeric_dtype(ref[col]):
            a = ref[col].to_numpy(dtype=float)
            b = got[col].to_numpy(dtype=float)
            assert np.array_equal(np.isnan(a), np.isnan(b))
            ok = ~np.isnan(a)
            if ok.any():
                np.testing.assert_allclose(a[ok], b[ok], atol=1e-12, rtol=1e-12)

    sliced = fd._load_panel_slice(parquet_path)
    assert not any(c.endswith("_sn") for c in sliced.columns)
    assert all(f in sliced.columns and f + "_z" in sliced.columns for f in fw.FACTORS)
    assert sliced["earnings_yield_z"].dtype == np.float32
    assert sliced["earnings_yield"].dtype == np.float64


def test_kpi_ic_and_interactions_handle_mixed_datetime_resolution():
    panel, dates = _panel(periods=12, n_companies=16, n_sectors=1)
    panel["date"] = pd.to_datetime(panel["date"]).astype("datetime64[ns]")
    syms = sorted(panel["symbol"].unique())
    rows = []
    for d in dates[:8]:
        for i, sym in enumerate(syms):
            rows.append({
                "symbol": sym, "metric": "m_a", "dimension": "", "quarter": 20241,
                "known_at": (d - pd.Timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "level": float(i), "yoy": float(i) * 0.1, "yoy_chg": 0.01, "unit": "x", "store": "s",
            })
            rows.append({
                "symbol": sym, "metric": "m_b", "dimension": "", "quarter": 20241,
                "known_at": (d - pd.Timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "level": float(len(syms) - i), "yoy": float(len(syms) - i) * 0.1, "yoy_chg": 0.02, "unit": "x", "store": "s",
            })
    kpi = pd.DataFrame(rows)
    kpi["known_at"] = pd.to_datetime(kpi["known_at"]).astype("datetime64[us]")
    ics, cov = fd.kpi_ic(kpi, panel, ["6m", "12m"], min_companies=8, min_names=6)
    assert not ics.empty
    assert not cov.empty
    pairs = fd.kpi_interactions(kpi, panel, "12m", min_companies=8)
    assert not pairs.empty
