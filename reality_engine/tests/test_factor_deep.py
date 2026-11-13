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
