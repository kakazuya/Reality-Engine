"""T-229 stage B tests: BH, within-date placebo, matched draws and claim PIT.

Synthetic only; no store, snapshot or T-228 database is opened.
"""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from reality_engine.research.factor_store91_stageb import (
    _bh,
    _draw_one,
    placebo_check,
    text_factors,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def tmp_path():
    """Writable scratch folder (the sandbox pytest basetemp is ACL-locked, as in stage A)."""
    base = ROOT / ".tmp" / f"t229b_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_bh_step_up_rejects_the_expected_prefix():
    mask = _bh(np.array([0.001, 0.008, 0.039, 0.5, 0.9]), 0.10)
    assert list(mask) == [True, True, True, False, False]
    assert not _bh(np.array([0.5, 0.6]), 0.10).any()


def test_placebo_finds_a_planted_relation_and_not_noise():
    rng = np.random.default_rng(7)
    rows = []
    for day in pd.date_range("2024-06-28", periods=24, freq="ME"):
        signal = rng.normal(size=40)
        target = 0.08 * signal + rng.normal(size=40) * 0.05
        for i in range(40):
            rows.append({"date": day, "sig": signal[i], "noise": rng.normal(),
                         "texcess_6m": target[i]})
    frame = pd.DataFrame(rows)
    out = placebo_check(frame, ["sig", "noise"], n_perm=100, seed=229).set_index(["factor", "horizon"])

    assert out.loc[("sig", "6m"), "months"] == 24
    assert out.loc[("sig", "6m"), "p_value"] <= 0.02
    assert out.loc[("noise", "6m"), "p_value"] > 0.05


def test_matched_draw_keeps_the_cell_counts():
    cells = {("A", "small"): ["a1", "a2", "a3", "a4"], ("B", "large"): ["b1", "b2", "b3"]}
    by_bucket = {"small": ["a1", "a2", "a3", "a4"], "large": ["b1", "b2", "b3"]}
    wanted = {("A", "small"): 3, ("B", "large"): 2}
    chosen = _draw_one(cells, by_bucket, ["a1", "b1"], wanted, np.random.default_rng(229))

    assert len(chosen) == 5
    assert sum(name.startswith("a") for name in chosen) == 3
    assert sum(name.startswith("b") for name in chosen) == 2
    # a cell the pool cannot fill falls back to the same size bucket, never to silence
    fallback = _draw_one({}, by_bucket, [], {("Z", "small"): 2}, np.random.default_rng(1))
    assert len(fallback) == 2 and all(name.startswith("a") for name in fallback)


def test_text_factors_use_verified_claims_after_the_1530_rule(tmp_path):
    db = tmp_path / "claims.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE claim(status TEXT, symbol TEXT, known_at TEXT, node TEXT, sign TEXT,
                                      value_low REAL, value_high REAL, unit TEXT, judge_forward INTEGER)""")
    con.executemany("INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?)", [
        ("verified", "TESTCO", "2024-06-28T16:30:00", "revenue.total", "+", 15.0, 19.0, "pct", 1),
        ("verified", "TESTCO", "2024-06-25T10:00:00", "margin.ebitda", "-", None, None, "pct", 1),
        ("verified", "TESTCO", "2024-06-26T10:00:00", "debt.level", "+", None, None, "pct", 1),
        ("unverified", "TESTCO", "2024-06-25T10:00:00", "revenue.total", "+", 99.0, 99.0, "pct", 1),
    ])
    con.commit()
    con.close()
    sessions = pd.DatetimeIndex(pd.to_datetime(["2024-06-27", "2024-06-28", "2024-07-01"]))
    panel = pd.DataFrame({
        "store": ["c01", "c01"], "symbol": ["TESTCO", "TESTCO"],
        "date": [pd.Timestamp("2024-06-28"), pd.Timestamp("2024-07-01")],
        "ttm_rev_yoy": [0.10, 0.10],
    })
    out = text_factors(panel, db, sessions).set_index("date")

    at_month_end = out.loc[pd.Timestamp("2024-06-28")]
    at_next = out.loc[pd.Timestamp("2024-07-01")]
    assert np.isnan(at_month_end["claim_rev_growth"])  # 16:30 filing is next session
    assert np.isclose(at_next["claim_rev_growth"], 0.17 - 0.10)
    assert at_next["claim_margin_dir"] == -1.0
    assert at_next["claim_debt_dir"] == 1.0
    assert at_month_end["claim_count_12m"] == 2
    assert at_next["claim_count_12m"] == 3
