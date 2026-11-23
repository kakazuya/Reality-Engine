"""T-229 stage A tests: point-in-time election and the panel arithmetic.

Synthetic only: a tiny SQLite store is written to ``tmp_path``; no store under
``D:/RealityEngine`` and no truth snapshot is opened.
"""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from reality_engine.research.factor_store91 import (
    elect_asof,
    excess_returns,
    financial_factors,
    guidance_factors,
    load_store,
    quarter_grid,
)

SESSIONS = pd.DatetimeIndex(pd.to_datetime([
    "2024-05-01", "2024-06-27", "2024-06-28", "2024-07-01", "2024-07-02",
]))
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def tmp_path():
    """A writable scratch folder: the sandbox's pytest basetemp root is ACL-locked
    by an earlier SYSTEM session (same workaround as ``test_row_checks.py``)."""
    base = ROOT / ".tmp" / f"t229_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _store(tmp_path, rows: list[tuple]) -> dict[str, Any]:
    """A store holding only fin_quarter_printed (and its company row)."""
    path = tmp_path / "c01" / "c01.db"
    path.parent.mkdir(parents=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE company(symbol TEXT, isin TEXT)")
    con.execute("INSERT INTO company VALUES ('TESTCO', 'INE000A01001')")
    con.execute("""
        CREATE TABLE fin_quarter_printed(
            symbol TEXT, fiscal_period TEXT, period_end TEXT, basis TEXT, line_item TEXT,
            value REAL, scale REAL, known_at TEXT, doc_key TEXT, page INTEGER,
            preferred_from TEXT, preferred_to TEXT)
    """)
    con.executemany(
        "INSERT INTO fin_quarter_printed VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    con.commit()
    con.close()
    return load_store(path, SESSIONS)


def _row(period: str, line: str, value: float, known_at: str,
         preferred_from: str | None, preferred_to: str | None,
         page: int = 7) -> tuple:
    return ("TESTCO", period, "2024-06-30", "consolidated", line, value, 1.0,
            known_at, "results.pdf", page, preferred_from, preferred_to)


def test_after_close_filing_is_not_used_on_that_month_end(tmp_path):
    """A filing at 16:30 IST on the month-end is usable from the next session only."""
    store = _store(tmp_path, [_row("Q1FY25", "revenue_from_operations", 100.0,
                                   "2024-06-28T16:30:00", "2024-06-28", None)])
    month_end = pd.Timestamp("2024-06-28")

    assert elect_asof(store["fin"], month_end).empty
    elected = elect_asof(store["fin"], pd.Timestamp("2024-07-01"))
    assert len(elected) == 1
    assert elected.iloc[0]["value_inr"] == 100.0


def test_preferred_window_elects_the_figure_of_the_day(tmp_path):
    """The later preferred window takes over on its availability session, and a
    row the store's election never typed (preferred_from NULL) is no candidate."""
    store = _store(tmp_path, [
        _row("Q1FY25", "revenue_from_operations", 100.0,
             "2024-05-01T10:00:00", "2024-05-01", "2024-07-01"),
        _row("Q1FY25", "revenue_from_operations", 110.0,
             "2024-07-01T10:00:00", "2024-07-01", None),
        _row("Q1FY25", "revenue_from_operations", 999.0,
             "2024-05-01T10:00:00", None, None),
    ])
    before = elect_asof(store["fin"], pd.Timestamp("2024-06-28"))
    after = elect_asof(store["fin"], pd.Timestamp("2024-07-01"))

    assert len(before) == 1 and before.iloc[0]["value_inr"] == 100.0
    assert len(after) == 1 and after.iloc[0]["value_inr"] == 110.0


def test_excess_return_is_the_raw_return_minus_that_month_mean():
    day = pd.Timestamp("2024-06-28")
    returns = pd.DataFrame({
        "store": ["a", "b", "c", "a", "b", "c"],
        "date": [day] * 6,
        "horizon": ["6m"] * 3 + ["12m"] * 3,
        "ret": [0.10, 0.00, -0.10, 0.20, np.nan, 0.00],
    })
    out = excess_returns(returns)

    six = out[out["horizon"] == "6m"]["excess"].to_numpy()
    twelve = out[out["horizon"] == "12m"].set_index("store")["excess"]
    assert np.allclose(six, [0.10, 0.00, -0.10])
    assert np.isclose(twelve["a"], 0.10) and np.isclose(twelve["c"], -0.10)
    assert pd.isna(twelve["b"])  # a NaN return is excluded from the mean, never zero


def test_guidance_rev_sign_reads_the_revision():
    guidance = pd.DataFrame({
        "id": [1, 2, 3],
        "metric": ["revenue_growth"] * 3,
        "low": [10.0, 15.0, 8.0],
        "high": [14.0, 19.0, 12.0],
        "unit": ["pct"] * 3,
        "revision_of": [None, 1, 2],
        "known_at": ["2024-05-01T10:00:00", "2024-08-01T10:00:00", "2024-11-01T10:00:00"],
        "avail": [pd.Timestamp("2024-05-01"), pd.Timestamp("2024-08-01"), pd.Timestamp("2024-11-01")],
        "target_period": ["FY25"] * 3,
        "doc_key": ["a.pdf", "b.pdf", "c.pdf"],
        "page": [1, 2, 3],
    })
    first = guidance_factors(guidance, pd.Timestamp("2024-06-01"), 0.05)
    raised = guidance_factors(guidance, pd.Timestamp("2024-09-01"), 0.05)
    cut = guidance_factors(guidance, pd.Timestamp("2024-12-01"), 0.05)

    assert first["guidance_rev"] == 0.0  # no revision yet
    assert raised["guidance_rev"] == 1.0
    assert np.isclose(raised["guidance_growth"], 0.17 - 0.05)
    assert cut["guidance_rev"] == -1.0


def test_quarter_yoy_matches_the_fiscal_quarter_not_the_row_position():
    """A missing quarter (Q4 prints only as an annual column) must not shift the base."""
    grid = pd.DataFrame({"rev": [100.0, 110.0, 120.0, 150.0]},
                        index=pd.to_datetime(["2023-06-30", "2023-09-30", "2023-12-31", "2024-06-30"]))
    factors = financial_factors(grid)

    assert np.isclose(factors["q_rev_yoy"], 150.0 / 100.0 - 1.0)  # Q1FY24, not Q3FY24
    assert np.isnan(factors.get("ttm_rev", np.nan))  # the four rows do not span four quarters


def test_quarter_grid_derives_q4_from_the_annual_and_9m_columns():
    elected = pd.DataFrame({
        "fiscal_period": ["Q1FY25", "H1FY25", "9MFY25", "FY25"],
        "line_item": ["revenue_from_operations"] * 4,
        "value_inr": [100.0, 250.0, 360.0, 500.0],
    })
    grid = quarter_grid(elected)

    assert list(grid.index) == [pd.Timestamp("2024-06-30"), pd.Timestamp("2024-09-30"),
                                pd.Timestamp("2024-12-31"), pd.Timestamp("2025-03-31")]
    assert np.allclose(grid["rev"].to_numpy(), [100.0, 150.0, 110.0, 140.0])
    factors = financial_factors(grid)
    assert factors["ttm_rev"] == 500.0
    assert np.isnan(factors.get("q_rev_yoy", np.nan))  # only four quarters are known
