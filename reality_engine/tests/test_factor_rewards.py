"""T-207 factor-reward engine: point-in-time reward windows, shifts, walk-forward.

Every test runs on a synthetic panel or an explicit IC frame; no snapshot needed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from reality_engine.research import factor_rewards as fr


def _month_end(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="BME")


def _calendar(dates: pd.DatetimeIndex, extra_days: int = 500) -> pd.DatetimeIndex:
    return pd.bdate_range(dates.min() - pd.Timedelta(days=10), dates.max() + pd.Timedelta(days=extra_days))


def _flip_panel(dates: pd.DatetimeIndex, n_companies: int = 24, flip: int = 21) -> pd.DataFrame:
    """One planted factor: IC about +1 before `flip`, about -1 after.

    A small deterministic wobble keeps the IC series non-constant: a perfectly
    constant IC has zero Newey-West variance and no t-stat at all.
    """
    rows = []
    for i, date in enumerate(dates):
        values = np.arange(n_companies, dtype=float)
        noisy = values + 0.75 * np.sin(values * 3.7 + i)
        excess = noisy if i < flip else -noisy
        for entity, value, ret in zip(values, values, excess):
            rows.append(
                {
                    "date": date,
                    "entity_id": int(entity),
                    "planted": value,
                    "planted_z": (value - values.mean()) / values.std(),
                    "excess_126": ret,
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Date plumbing (pandas 3 is microsecond based: no unit-blind casts)
# --------------------------------------------------------------------------- #
def test_to_ns_does_not_stamp_1970():
    got = fr.to_ns(pd.Series(pd.to_datetime(["2021-01-31"])))[0]
    assert got == np.datetime64("2021-01-31", "ns")


def test_known_date_is_the_session_the_forward_window_ends():
    cal = pd.bdate_range("2024-01-01", periods=300)
    dates = pd.Series([cal[100], cal[290]])
    known = fr.known_dates_for(dates, cal, 126)
    assert known.iloc[0] == cal[226]
    assert pd.isna(known.iloc[1])


# --------------------------------------------------------------------------- #
# The rewarded set is only as old as its realised horizon
# --------------------------------------------------------------------------- #
def test_a_planted_reward_flips_only_after_its_horizon_has_passed():
    dates = _month_end("2020-01-31", 45)
    panel = _flip_panel(dates)
    ic = fr.realised_ic(panel, "planted", "6m", _calendar(dates))
    assert ic["ic"].iloc[:21].min() > 0.9 and ic["ic"].iloc[21:].max() < -0.9

    out = fr.rewarded_at(ic, dates, window_months=12, lags=5).set_index("date")
    # Before the flip: rewarded positive.
    assert bool(out.loc[dates[20], "rewarded"]) and int(out.loc[dates[20], "sign"]) == 1
    # A full horizon after the flip the newest IC is negative, but the trailing
    # window is still mostly positive: the reward has not flipped yet.
    assert int(out.loc[dates[27], "sign"]) == 1
    # As the old positives roll out, the window mixes signs: rated, not rewarded.
    assert bool(out.loc[dates[32], "rated"]) and not bool(out.loc[dates[32], "rewarded"])
    # Once the known window is all negative the other sign is rewarded.
    assert int(out.loc[dates[38], "sign"]) == -1


def test_an_ic_known_after_t_never_enters_the_window():
    dates = pd.date_range("2023-01-31", periods=24, freq="ME")
    ic = pd.DataFrame({"date": dates, "known_date": dates, "ic": 0.2})
    t = pd.DatetimeIndex([dates[-1]])
    base = fr.rewarded_at(ic, t, window_months=24, lags=5)

    future = pd.DataFrame(
        {"date": [dates[-1] + pd.Timedelta(days=1)],
         "known_date": [dates[-1] + pd.Timedelta(days=10)],
         "ic": [1e9]}
    )
    with_future = fr.rewarded_at(pd.concat([ic, future], ignore_index=True), t, window_months=24, lags=5)
    pd.testing.assert_frame_equal(base, with_future)


def test_fewer_than_twelve_known_months_is_not_rated():
    dates = pd.date_range("2023-01-31", periods=11, freq="ME")
    ic = pd.DataFrame({"date": dates, "known_date": dates, "ic": 0.2})
    short = fr.rewarded_at(ic, pd.DatetimeIndex([dates[-1]]), window_months=24, lags=5).iloc[0]
    assert short["months"] == 11
    assert not bool(short["rated"]) and not bool(short["rewarded"])

    twelve = pd.date_range("2023-01-31", periods=12, freq="ME")
    twelve_ic = pd.DataFrame({"date": twelve, "known_date": twelve, "ic": 0.2})
    full = fr.rewarded_at(twelve_ic, pd.DatetimeIndex([twelve[11]]), window_months=24, lags=5).iloc[0]
    assert bool(full["rated"]) and bool(full["rewarded"]) and int(full["sign"]) == 1


# --------------------------------------------------------------------------- #
# Walk-forward
# --------------------------------------------------------------------------- #
def _constant_panel(dates: pd.DatetimeIndex, n_companies: int = 30) -> pd.DataFrame:
    """f1 rises with the forward return (+1 IC), f2 falls (-1 IC), every month.

    The small monthly wobble keeps the IC series non-constant so Newey-West has
    a variance to work with; the rank order is preserved.
    """
    rows = []
    for i, date in enumerate(dates):
        f1 = np.arange(n_companies, dtype=float)
        f2 = f1[::-1]
        excess = f1 + 0.75 * np.sin(f1 * 3.7 + i)
        for entity in range(n_companies):
            rows.append(
                {
                    "date": date,
                    "entity_id": entity,
                    "f1": f1[entity],
                    "f2": f2[entity],
                    "f1_z": (f1[entity] - f1.mean()) / f1.std(),
                    "f2_z": (f2[entity] - f2.mean()) / f2.std(),
                    "excess_126": excess[entity],
                }
            )
    return pd.DataFrame(rows)


def test_dynamic_equals_static_when_nothing_changes():
    dates = _month_end("2020-01-31", 30)
    panel = _constant_panel(dates)
    cal = _calendar(dates)
    frames = []
    for factor, sign in (("f1", 1), ("f2", -1)):
        ic = fr.realised_ic(panel, factor, "6m", cal)
        r = fr.rewarded_at(ic, dates, window_months=24, lags=5)
        r["horizon"] = "6m"
        r["split"] = "all"
        r["group"] = "all"
        r["factor"] = factor
        r["window"] = fr.MAIN_WINDOW
        assert (r.loc[r["rated"], "sign"] == sign).all()
        frames.append(r)
    rewarded = pd.concat(frames, ignore_index=True)

    summary, monthly = fr.walk_forward(panel, rewarded, "6m", equal_signs={"f1": 1, "f2": -1})
    assert len(monthly) > 0
    dyn = monthly["DYNAMIC_ic"].dropna()
    stat = monthly["STATIC_ic"].dropna()
    np.testing.assert_allclose(dyn.to_numpy(), stat.to_numpy())
    diff = summary[summary["score"] == "DYNAMIC-STATIC"].iloc[0]
    assert diff["months"] == len(dyn) and abs(diff["mean_ic"]) < 1e-12


# --------------------------------------------------------------------------- #
# Splits and multiplicity
# --------------------------------------------------------------------------- #
def test_thin_sectors_merge_and_labels_are_normalised():
    dates = _month_end("2024-01-31", 2)
    rows = []
    for date in dates:
        for sector, n in (("BIG", 40), ("Tiny", 10), ("Tiny Two", 25)):
            for i in range(n):
                rows.append({"date": date, "entity_id": f"{sector}-{i}", "sector": sector})
    mapping, report = fr.sector_map(pd.DataFrame(rows), min_names=30, min_months=1)
    assert mapping["Tiny"] == mapping["Tiny Two"] == "Other (merged)"
    assert mapping["Big"] == "Big"
    assert report.attrs["group_min"]["Other (merged)"] >= 30


def test_benjamini_hochberg_keeps_the_ordered_rejections():
    assert fr.bh_survivors([0.001, 0.04, 0.2], 0.10).tolist() == [True, True, False]
    assert fr.binom_two_sided(12, 12) < 0.01


# --------------------------------------------------------------------------- #
# Round 2: block-balanced, persistent and placebo plumbing
# --------------------------------------------------------------------------- #
def test_block_score_equals_plain_when_each_block_has_one_factor():
    picks = [factors[0] for factors in fr.BLOCKS.values()]
    signed = {factor: (1 if i % 2 == 0 else -1) for i, factor in enumerate(picks)}
    columns = {}
    for i, factor in enumerate(signed):
        values = [1.0, -2.0, 3.0, 0.5]
        if i == 0:
            values[3] = np.nan
        columns[factor + "_z"] = values
    frame = pd.DataFrame(columns)
    np.testing.assert_allclose(
        fr.block_score(frame, signed).to_numpy(),
        fr.signed_score(frame, signed).to_numpy(),
        equal_nan=True,
    )


def test_persistent_uses_no_state_dated_after_t():
    dates = pd.date_range("2020-01-31", periods=24, freq="ME")
    rows = [
        {
            "date": date,
            "horizon": "6m",
            "split": "all",
            "group": "all",
            "window": fr.MAIN_WINDOW,
            "factor": "f",
            "rated": True,
            "rewarded": True,
            "sign": 1 if i < 12 else -1,
        }
        for i, date in enumerate(dates)
    ]
    rewarded = pd.DataFrame(rows)
    sets = fr.persistent_sets(rewarded, "6m")
    assert sets[dates[10]] == {}  # 11 rated months, below the 12-month floor
    assert sets[dates[11]] == {"f": 1}  # 12 positive states
    assert fr.persistent_sets(rewarded[rewarded["date"] <= dates[11]], "6m")[dates[11]] == {"f": 1}
    assert sets[dates[23]] == {}  # a 12/12 split has no 70% sign


def test_placebo_keeps_each_dates_value_distribution():
    dates = pd.to_datetime(["2024-01-31", "2024-02-29"])
    rows = [
        {"date": date, "entity_id": i, "f": float(i), "excess_126": float(i)}
        for date in dates
        for i in range(6)
    ]
    panel = pd.DataFrame(rows)
    panel.loc[0, "f"] = np.nan
    shuffled = fr.permute_panel(panel, 7, ["f"])
    for date in dates:
        before = panel.loc[panel["date"] == date, "f"].dropna().sort_values().to_numpy()
        after = shuffled.loc[shuffled["date"] == date, "f"].dropna().sort_values().to_numpy()
        np.testing.assert_allclose(after, before)
        assert shuffled.loc[shuffled["date"] == date, "f"].isna().sum() == panel.loc[
            panel["date"] == date, "f"
        ].isna().sum()
    np.testing.assert_allclose(shuffled["excess_126"], panel["excess_126"])
