"""T-229 stage C tests: claim PIT, deck filters, unit scaling, restatement election, order repeats
and residualisation arithmetic.

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
    event_factors,
    load_claims,
    load_events,
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


def _claim(row_id, node, low, high, unit, avail, source_kind="announcement",
           segment="total", period="", statement="", quote="", context=""):
    return {
        "row_id": row_id, "symbol": "TESTCO", "known_at": str(avail), "node": node,
        "sign": "0", "value_low": low, "value_high": high, "unit": unit,
        "source_kind": source_kind, "source_table": source_kind,
        "segment": segment, "effective_period": period, "statement": statement,
        "quote_span": quote, "context": context,
        "avail": pd.Timestamp(avail),
    }


def test_load_claims_applies_the_stage2_scope_and_duplicate_filters(tmp_path):
    db = tmp_path / "claims.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE claim(
        id INTEGER PRIMARY KEY, status TEXT, symbol TEXT, known_at TEXT, node TEXT, sign TEXT,
        value_low REAL, value_high REAL, unit TEXT, segment TEXT, effective_period TEXT,
        statement TEXT, quote_span TEXT, context TEXT, source_kind TEXT, speaker_scope TEXT,
        dup_of TEXT)""")
    con.executemany("INSERT INTO claim VALUES (" + ",".join("?" * 17) + ")", [
        (1, "verified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 10.0, None,
         "inr_cr", "total", "FY26", "plan", "", "", "announcement", "company", ""),
        (2, "verified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 99.0, None,
         "inr_cr", "total", "FY26", "plan", "", "", "announcement", "subsidiary", ""),
        (3, "verified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 77.0, None,
         "inr_cr", "total", "FY26", "plan", "", "", "announcement", "company", "1"),
        (4, "unverified", "TESTCO", "2024-06-25T10:00:00", "capex.amount", "0", 55.0, None,
         "inr_cr", "total", "FY26", "plan", "", "", "announcement", "company", ""),
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


def test_capex_takes_the_latest_claim_per_segment_and_period():
    panel = pd.DataFrame({"store": ["c01"], "symbol": ["TESTCO"],
                          "date": pd.to_datetime(["2026-06-30"]),
                          "ttm_rev": [1.0e10], "mcap": [1.0e10], "ttm_rev_yoy": [0.10]})
    claims = pd.DataFrame([
        _claim(1, "capex.amount", 165.0, 170.0, "inr_cr", "2025-08-14", period="FY26"),
        _claim(2, "capex.amount", 125.0, 130.0, "inr_cr", "2025-11-12", period="FY26"),
        _claim(3, "capex.amount", 125.0, 130.0, "inr_cr", "2026-02-19", period="FY '26"),
        _claim(4, "capex.amount", 50.0, None, "inr_cr", "2025-12-01", period="FY27"),
    ])
    out, _ = claim_factors(panel, claims)
    row = out.set_index("date").loc[pd.Timestamp("2026-06-30")]

    # FY26 is one plan at its latest value (127.5), FY27 is a second plan (50): 177.5 crore
    assert np.isclose(row["claim_capex_12m"], 177.5 * 1e7 / 1.0e10)


def test_order_inflow_counts_one_announcement_per_order():
    panel = pd.DataFrame({"store": ["c01", "c01"], "symbol": ["TESTCO", "TESTCO"],
                          "date": pd.to_datetime(["2024-06-28", "2024-07-31"]),
                          "ttm_rev": [1.0e10, 1.0e10], "mcap": [2.0e10, 2.0e10],
                          "ttm_rev_yoy": [0.10, 0.10]})
    acme = "The company received an order from Acme Power Ltd for a 765 kV transmission line"
    claims = pd.DataFrame([
        _claim(1, "revenue.order_book", 100.0, None, "inr_cr", "2024-06-10", statement=acme),
        _claim(2, "revenue.order_book", 100.5, None, "inr_cr", "2024-06-20", statement=acme),
        _claim(3, "revenue.order_book", 100.0, None, "inr_cr", "2024-06-25",
               statement="The company received an order from Beta Steel Ltd for a steel plant"),
        _claim(4, "revenue.order_book", 100.0, None, "inr_cr", "2024-07-25", statement=acme),
    ])
    out, _ = claim_factors(panel, claims)
    out = out.set_index("date")

    at_june = out.loc[pd.Timestamp("2024-06-28")]
    # Acme's 10-day repeat counts once; Beta's equal value is a different order
    assert np.isclose(at_june["claim_order_inflow_12m"], 200.0 * 1e7 / 1.0e10)
    assert at_june["claim_count_12m"] == 3

    at_july = out.loc[pd.Timestamp("2024-07-31")]
    # the 45-day repeat is outside the 30-day window and counts as a new announcement
    assert np.isclose(at_july["claim_order_inflow_12m"], 300.0 * 1e7 / 1.0e10)
    assert at_july["claim_count_12m"] == 4


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


def _events_db(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE event(
        event_id INTEGER PRIMARY KEY, symbol TEXT, known_at TEXT, kind TEXT, order_kind TEXT,
        amount_inr_cr REAL, share_pct REAL, value_total REAL, raise_id TEXT, raise_primary INTEGER,
        detail TEXT, status TEXT, entity_scope TEXT)""")
    con.executemany("INSERT INTO event VALUES (" + ",".join("?" * 13) + ")", rows)
    con.commit()
    con.close()


def _event(event_id, kind, amount, known_at="2024-06-10T10:00:00", order_kind: str | None = "new_order",
           share_pct=None, value_total=None, raise_id=None, raise_primary=None, detail=""):
    return (event_id, "TESTCO", known_at, kind, order_kind, amount, share_pct, value_total,
            raise_id, raise_primary, detail, "verified", "company")


def test_events_are_point_in_time_at_1530_and_the_next_session(tmp_path):
    db = tmp_path / "events.db"
    _events_db(db, [_event(1, "order_win", 100.0, known_at="2024-06-28T16:00:00")])
    sessions = pd.DatetimeIndex(pd.to_datetime(["2024-06-28", "2024-07-01"]))
    events, _ = load_events(db, sessions)
    panel = pd.DataFrame({"store": ["c01", "c01"], "symbol": ["TESTCO", "TESTCO"],
                          "date": pd.to_datetime(["2024-06-28", "2024-07-01"]),
                          "ttm_rev": [1.0e10, 1.0e10], "mcap": [2.0e10, 2.0e10]})
    out, _ = event_factors(panel, events)
    out = out.set_index("date")
    # the 16:00 filing is not available at the June month-end: no row, so the merge leaves NaN
    assert pd.Timestamp("2024-06-28") not in out.index
    assert np.isclose(out.loc[pd.Timestamp("2024-07-01"), "ev_order_inflow_12m"],
                      100.0 * 1e7 / 1.0e10)


def test_events_raise_counts_once_per_raise_id_and_skips_non_primary(tmp_path):
    db = tmp_path / "events.db"
    _events_db(db, [
        _event(1, "fund_raise", 100.0, raise_id="r1", raise_primary=1),
        _event(2, "fund_raise", 100.0, raise_id="r1", raise_primary=1),
        _event(3, "fund_raise", 300.0, raise_id="r2", raise_primary=1),
        _event(4, "fund_raise", 999.0, raise_id="r3", raise_primary=0),
    ])
    sessions = pd.DatetimeIndex(pd.to_datetime(["2024-06-28"]))
    events, _ = load_events(db, sessions)
    panel = pd.DataFrame({"store": ["c01"], "symbol": ["TESTCO"],
                          "date": pd.to_datetime(["2024-06-28"]),
                          "ttm_rev": [1.0e10], "mcap": [2.0e10]})
    out, stats = event_factors(panel, events)
    assert np.isclose(out.loc[0, "ev_raise_12m"], 400.0 * 1e7 / 2.0e10)
    assert stats["raises_counted"] == 2      # r1 once, r2 once; r3 not a primary


def test_events_order_inflow_uses_the_share_and_amendment_increment_only(tmp_path):
    db = tmp_path / "events.db"
    _events_db(db, [
        # the stored amount is the company's 40% consortium share; value_total is the total
        _event(1, "order_win", 296.0, share_pct=40.0, value_total=740.0),
        # an amendment contributes its printed increment (20 of a new 120), never its total
        _event(2, "order_amendment", 20.0, order_kind=None, value_total=120.0,
               detail="amendment increment = new total - old total (computed)"),
        # an extension's full contract value is not an increment and must not be added
        _event(3, "order_amendment", 50.0, order_kind=None, value_total=50.0),
    ])
    sessions = pd.DatetimeIndex(pd.to_datetime(["2024-06-28"]))
    events, _ = load_events(db, sessions)
    panel = pd.DataFrame({"store": ["c01"], "symbol": ["TESTCO"],
                          "date": pd.to_datetime(["2024-06-28"]),
                          "ttm_rev": [1.0e10], "mcap": [2.0e10]})
    out, stats = event_factors(panel, events)
    assert np.isclose(out.loc[0, "ev_order_inflow_12m"], (296.0 + 20.0) * 1e7 / 1.0e10)
    assert stats["amendments_skipped"] == 1


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
