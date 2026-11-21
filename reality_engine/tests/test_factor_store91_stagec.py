"""T-229 stage C tests: claim PIT, deck filters, unit scaling and residualisation arithmetic.

Synthetic only; no store, snapshot, T-228 or T-230 database is opened.
"""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from reality_engine.research.factor_store91_stagec import (
    claim_factors,
    deck_factors,
    load_claims,
    load_observations,
    rank_residual,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def tmp_path():
    """Writable scratch folder (the sandbox pytest basetemp is ACL-locked, as in stages A/B)."""
    base = ROOT / ".tmp" / f"t229c_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _panel() -> pd.DataFrame:
    return pd.DataFrame({
        "store": ["c01", "c01"],
        "symbol": ["TESTCO", "TESTCO"],
        "date": pd.to_datetime(["2024-06-28", "2024-07-01"]),
        "ttm_rev": [1.0e10, 1.0e10],   # rupees
        "mcap": [2.0e10, 2.0e10],
        "ttm_rev_yoy": [0.10, 0.10],
    })


def _claim(row_id, node, low, high, unit, avail, source_kind="announcement"):
    return {
        "row_id": row_id, "symbol": "TESTCO", "known_at": str(avail), "node": node,
        "sign": "0", "value_low": low, "value_high": high, "unit": unit,
        "source_kind": source_kind, "source_table": source_kind,
        "avail": pd.Timestamp(avail),
    }


def test_load_claims_applies_the_stage2_scope_and_duplicate_filters(tmp_path):
    db = tmp_path / "claims.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE claim(
        id INTEGER PRIMARY KEY, status TEXT, symbol TEXT, known_at TEXT, node TEXT, sign TEXT,
        value_low REAL, value_high REAL, unit TEXT, source_kind TEXT, speaker_scope TEXT,
        dup_of TEXT)""")
    con.executemany("INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, "verified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 10.0, None,
         "inr_cr", "announcement", "company", ""),
        (2, "verified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 99.0, None,
         "inr_cr", "announcement", "subsidiary", ""),
        (3, "verified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 77.0, None,
         "inr_cr", "announcement", "company", "1"),
        (4, "unverified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 55.0, None,
         "inr_cr", "announcement", "company", ""),
    ])
    con.commit()
    con.close()
    sessions = pd.DatetimeIndex(pd.to_datetime(["2024-06-25"]))
    frame, stats = load_claims(db, sessions)

    assert list(frame["row_id"]) == [1]
    assert stats["dropped_scope"] == 1 and stats["dropped_duplicate"] == 1


def test_claim_factors_apply_the_1530_rule_scopes_and_unit_scaling():
    claims = pd.DataFrame([
        _claim(1, "revenue.order_book", 200.0, None, "inr_cr", "2024-06-28"),
        _claim(2, "revenue.order_book", 1000.0, None, "inr_lakh", "2024-06-28"),
        # an order-book stock/target from a transcript is not an order win
        _claim(3, "revenue.order_book", 500.0, None, "inr_cr", "2024-06-28",
               source_kind="transcript"),
        _claim(4, "capex.amount", 100.0, None, "inr_cr", "2024-07-01"),
        # a currency the brief does not convert is skipped, never summed as rupees
        _claim(5, "capex.amount", 5.0, None, "usd_mn", "2024-06-28"),
        _claim(6, "equity.shares", 50.0, None, "inr_cr", "2024-06-28"),
        _claim(7, "revenue.total", 20.0, None, "pct", "2024-06-28",
               source_kind="transcript"),
    ])
    out, _ = claim_factors(_panel(), claims)
    out = out.set_index("date")

    at_month_end = out.loc[pd.Timestamp("2024-06-28")]
    assert np.isclose(at_month_end["claim_order_inflow_12m"], 210.0 * 1e7 / 1.0e10)
    assert np.isnan(at_month_end["claim_capex_12m"])  # 16:30 filing and usd_mn: nothing usable
    assert np.isclose(at_month_end["claim_dilution_12m"], 50.0 * 1e7 / 2.0e10)
    assert np.isclose(at_month_end["claim_rev_growth"], 0.20 - 0.10)
    assert at_month_end["claim_count_12m"] == 6

    later = out.loc[pd.Timestamp("2024-07-01")]
    assert np.isclose(later["claim_capex_12m"], 100.0 * 1e7 / 2.0e10)
    assert later["claim_count_12m"] == 7


def _observation_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE observation(
        observation_id INTEGER PRIMARY KEY, symbol TEXT, known_at TEXT, measure TEXT,
        value REAL, unit TEXT, unit_family TEXT, scale REAL, period TEXT, period_kind TEXT,
        segment TEXT, stage TEXT, series_kind TEXT, adjusted INTEGER, entity_scope TEXT,
        status TEXT)""")
    rows = [
        # the only order-book row that may count: company scope, verified, level, not adjusted
        (1, "TESTCO", "2024-06-28T09:00:00", "order.book", 1000.0, "INR Mn", "money", 1.0e6,
         "FY25", "actual", "", "", "level", 0, "company", "verified"),
        (2, "TESTCO", "2024-06-28T09:00:00", "order.book", 9999.0, "INR Mn", "money", 1.0e6,
         "FY25", "actual", "", "", "level", 0, "industry", "verified"),
        (3, "TESTCO", "2024-06-28T09:00:00", "order.book", 5000.0, "INR Mn", "money", 1.0e6,
         "FY25", "actual", "", "", "level", 1, "company", "verified"),
        (4, "TESTCO", "2024-06-28T09:00:00", "order.book", 7000.0, "INR Mn", "money", 1.0e6,
         "FY25", "actual", "", "", "bridge", 0, "company", "verified"),
        (5, "TESTCO", "2024-06-28T09:00:00", "order.book", 8000.0, "INR Mn", "money", 1.0e6,
         "FY25", "actual", "", "", "level", 0, "company", "unverified"),
        (6, "TESTCO", "2024-06-28T09:00:00", "capacity.add", 100.0, "MW", "capacity", 1.0,
         "FY27", "estimate", "", "under_construction", "level", 0, "company", "verified"),
        # the speculative pipeline is never a committed addition
        (7, "TESTCO", "2024-06-28T09:00:00", "capacity.add", 999.0, "MW", "capacity", 1.0,
         "FY30", "target", "", "under_review", "level", 0, "company", "verified"),
        (8, "TESTCO", "2024-06-28T09:00:00", "capacity.total", 400.0, "MW", "capacity", 1.0,
         "FY26", "actual", "", "", "level", 0, "company", "verified"),
        # a unit that has no same-unit total must be skipped, never divided by another unit
        (9, "TEST2", "2024-06-28T09:00:00", "capacity.add", 50.0, "MTPA", "capacity", 1.0,
         "FY27", "target", "", "approved", "level", 0, "company", "verified"),
        (10, "TEST2", "2024-06-28T09:00:00", "capacity.total", 500.0, "MW", "capacity", 1.0,
         "FY26", "actual", "", "", "level", 0, "company", "verified"),
    ]
    con.executemany("INSERT INTO observation VALUES (" + ",".join("?" * 16) + ")", rows)
    con.commit()
    con.close()


def test_deck_factors_keep_company_level_rows_and_skip_mismatched_units(tmp_path):
    db = tmp_path / "obs.db"
    _observation_db(db)
    sessions = pd.DatetimeIndex(pd.to_datetime(["2024-06-28"]))
    obs, _ = load_observations(db, sessions)
    # adjusted/bridge/industry-scope/unverified dropped; the under_review row loads but is
    # excluded by the capacity factor's stage rule below
    assert set(obs["observation_id"]) == {1, 6, 7, 8, 9, 10}

    panel = pd.DataFrame({"store": ["c01", "c02"], "symbol": ["TESTCO", "TEST2"],
                          "date": pd.to_datetime(["2024-06-28", "2024-06-28"]),
                          "ttm_rev": [1.0e10, 1.0e10]})
    out, stats = deck_factors(panel, obs)
    out = out.set_index("store")

    assert np.isclose(out.loc["c01", "deck_order_cover"], 1.0e9 / 1.0e10)
    assert np.isclose(out.loc["c01", "deck_capacity_growth"], 100.0 / 400.0)
    assert np.isnan(out.loc["c02", "deck_capacity_growth"])  # MTPA add, MW total
    assert stats["capacity_no_total"] == 1


def test_rank_residual_is_orthogonal_to_the_controls_on_every_date():
    rng = np.random.default_rng(11)
    rows = []
    for day in pd.to_datetime(["2024-06-28", "2024-07-31"]):
        for _ in range(40):
            rows.append({"date": day, "x1": rng.normal(), "x2": rng.normal(),
                         "y": rng.normal()})
    frame = pd.DataFrame(rows)
    residual = rank_residual(frame, "y", ["x1", "x2"])
    frame = frame.assign(residual=residual)
    assert bool(frame["residual"].notna().all())

    for _, group in frame.groupby("date"):
        for control in ("x1", "x2"):
            dot = float(np.dot(group["residual"].to_numpy(float),
                               (group[control].rank() - group[control].rank().mean()).to_numpy(float)))
            assert abs(dot) < 1e-8
