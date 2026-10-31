"""Small fixtures for the v4 executor, answer contract, renderer and grader (§H.4).

No database is opened from the repo: ``fixture`` builds an in-memory SQLite store
with the §B.1 fact columns plus the small stored objects the executor reads.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tasks" / "answer_bench"))

from reality_engine.query.v4 import execute, render  # noqa: E402
import grade_v2  # noqa: E402

WINDOW = {"from": "2026-04-01", "to": "2026-09-30"}


def as_of(day: str = "2026-10-31") -> str:
    return day


@pytest.fixture()
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE fact(entity_id TEXT, atom_id TEXT, dims TEXT, period_start TEXT,
                          period_end TEXT, value REAL, unit TEXT, known_at TEXT,
                          source_ref TEXT);
        CREATE TABLE own_estimate(isin TEXT, est_atom TEXT, period_end TEXT, value REAL,
                                  unit TEXT, method TEXT, inputs_json TEXT, n_obs INT,
                                  confidence REAL, known_at TEXT, as_of TEXT);
        CREATE TABLE claim(entity_id TEXT, topic TEXT, direction TEXT, magnitude REAL,
                           unit TEXT, horizon TEXT, certainty TEXT,
                           guidance_vs_fact TEXT, quote TEXT, page_no INT, doc_id TEXT,
                           doctype TEXT, surface_id INT, known_at TEXT, pit_conf REAL);
        CREATE TABLE edge(driver TEXT, target TEXT, origin TEXT, strength REAL, lag INT,
                          n INT, fdr_q REAL, stability_by_window TEXT, label TEXT,
                          known_at TEXT, last_tested TEXT, mechanism TEXT,
                          evidence_ref TEXT);
        CREATE TABLE membership(entity_id TEXT, set_kind TEXT, set_value TEXT,
                                valid_from TEXT, valid_to TEXT, weight REAL,
                                source TEXT, known_at TEXT);
        """
    )
    facts = [
        ("INE001", "fin.revenue", "exchange=NSE;basis=raw", "2026-06-30", "2026-06-30",
         100.0, "INR", "2026-07-30", "results_xbrl"),
        ("INE001", "fin.revenue", "exchange=NSE;basis=raw", "2026-09-30", "2026-09-30",
         110.0, "INR", "2026-10-30", "results_xbrl"),
        ("INE001", "fin.revenue", "exchange=BSE;basis=raw", "2026-09-30", "2026-09-30",
         112.0, "INR", "2026-10-30", "results_xbrl"),
        ("INE001", "fin.ebitda", "exchange=NSE;basis=raw", "2026-09-30", "2026-09-30",
         30.0, "INR", "2026-10-30", "results_xbrl"),
        ("INE001", "price.close", "basis=raw", "2026-01-01", "2026-01-01", 100.0,
         "INR", "2026-01-02", "px_nse"),
        ("INE001", "price.close", "basis=raw", "2026-01-02", "2026-01-02", 120.0,
         "INR", "2026-01-02", "px_nse"),
        ("INE001", "price.close", "basis=raw", "2026-01-03", "2026-01-03", 90.0,
         "INR", "2026-01-03", "px_nse"),
        ("INE001", "price.open", "basis=raw", "2026-01-03", "2026-01-03", 95.0,
         "INR", "2026-01-03", "px_nse"),
        ("INE001", "price.high", "exchange=NSE", "2026-01-02", "2026-01-02", 130.0,
         "INR", "2026-01-02T23:59:59", "bhavcopy"),
        ("INE001", "price.high", "exchange=NSE", "2026-01-03", "2026-01-03", 91.0,
         "INR", "2026-01-03T23:59:59", "bhavcopy"),
        ("INE001", "price.close", "basis=raw", "2023-01-03", "2023-01-03", 100.0,
         "INR", "2023-01-03", "px_nse"),
        ("INE001", "hold.pct", "holder_class=promoter", "2026-06-30", "2026-06-30",
         55.0, "%", "2026-07-30", "shp_index"),
        ("INE001", "hold.pct", "holder_class=promoter", "2026-09-30", "2026-09-30",
         49.0, "%", "2026-10-30", "shp_index"),
        ("INE001", "hold.pct", "holder_class=public", "2026-06-30", "2026-06-30",
         30.0, "%", "2026-07-30", "shp_index"),
        ("INE001", "hold.pct", "holder_class=public", "2026-09-30", "2026-09-30",
         36.0, "%", "2026-10-30", "shp_index"),
        ("INE001", "hold.pledge_pct", "holder_class=promoter", "2026-06-30", "2026-06-30",
         1.5, "%", "2026-07-14", "shp_index"),
        ("INE001", "hold.pledge_pct", "holder_class=promoter", "2026-09-30", "2026-09-30",
         2.0, "%", "2026-10-15", "shp_index"),
        ("INE002", "price.close", "basis=raw", "2026-10-01", "2026-10-01", 50.0,
         "INR", "2026-10-02", "px_nse"),
        ("INE003", "price.close", "basis=raw", "2026-10-01", "2026-10-01", 70.0,
         "INR", "2026-10-02", "px_nse"),
        ("INE001", "price.close", "basis=adjusted", "2026-01-03", "2026-01-03", 80.0,
         "INR", "2026-01-03", "px_nse_adj"),
    ]
    conn.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", facts)
    conn.execute(
        "INSERT INTO own_estimate VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("INE001", "fin.revenue", "2026-09-30", 105.0, "INR", "trend",
         json.dumps({"series": "fin.revenue", "n": 8}), 8, 0.55, "2026-10-30",
         "2026-10-30"))
    conn.execute(
        "INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("INE001", "demand", "up", None, None, "FY27", "stated", "fact",
         "Demand remained strong through the quarter", 4, "doc1", "concall", None,
         "2026-10-15", 0.9))
    conn.executemany(
        "INSERT INTO edge VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("DRIVER", "A", "measured", 0.8, 5, 100, 0.01, None, "verified",
          "2026-10-01", None, "input cost", "e1"),
         ("A", "B", "measured", 0.6, 10, 80, 0.02, None, "verified",
          "2026-10-01", None, "pass-through", "e2")])
    conn.execute(
        "INSERT INTO membership VALUES (?,?,?,?,?,?,?,?)",
        ("INE001", "index", "NIFTY50", "2026-01-01", None, 1.0, "nse", "2026-01-01"))
    conn.commit()
    return conn


def part(**kw) -> dict:
    base = {"atom": None, "formula": None, "dims": {}, "window": 0,
            "operator": "value_at", "shape": "scalar", "judgement": False}
    base.update(kw)
    return base


def run(db, p, **kw):
    window = kw.pop("window", WINDOW)
    return execute.execute(p, kw.pop("as_of", as_of()), db, windows=[window], **kw)


# --- the measured contract -------------------------------------------------
def test_measured_scalar_contract(db):
    result = run(db, part(atom="fin.revenue", dims={"exchange": "NSE"}))
    assert result.answer_type == "measured"
    assert result.value == 110.0
    assert (result.unit, result.period, result.isin) == ("INR", "2026-09-30", "INE001")
    assert result.source_ref == "results_xbrl" and result.known_at == "2026-10-30"
    status = grade_v2.part_status(part(atom="fin.revenue", dims={"exchange": "NSE"}),
                                  result)
    assert status["covered"] and status["counts_as"] == "real_answered"


def test_pit_cut_hides_later_rows(db):
    early = run(db, part(atom="fin.revenue", dims={"exchange": "NSE"}),
                as_of="2026-09-30")
    assert early.value == 100.0 and early.period == "2026-06-30"


# --- latest readings: the most recent period KNOWN by as_of (§D.2) ----------
def test_latest_quarter_reads_the_most_recent_period_known_by_as_of(db):
    """"the latest quarter" as of 2026-10-07 is 2026-06-30 (filed 2026-07-14), not the
    2026-09-30 row known 2026-10-15 and not an empty 91-day period_end window."""
    latest = {"from": None, "to": "2026-10-07", "basis": "latest quarter"}
    result = run(db, part(atom="hold.pledge_pct", dims={"holder_class": "promoter"}),
                 as_of="2026-10-07", window=latest)
    assert result.answer_type == "measured"
    assert (result.value, result.period, result.known_at) == (1.5, "2026-06-30",
                                                             "2026-07-14")
    assert "period 2026-06-30, 99 days before 2026-10-07, filed 2026-07-14" in \
        (result.assumption or "")
    assert "staleness limit 200 days" in (result.assumption or "")


def test_a_latest_reading_older_than_its_limit_is_not_offered(db):
    """A years-old row is never "latest": the limit is stated, the part stays NID."""
    latest = {"from": None, "to": "2027-06-01", "basis": "latest"}
    result = run(db, part(atom="hold.pledge_pct", dims={"holder_class": "promoter"}),
                 as_of="2027-06-01", window=latest)
    assert result.answer_type == "not_in_data"
    assert "staleness limit" in (result.nid_reason or "")
    assert "2026-09-30" in (result.nid_reason or "")


def test_a_named_period_with_no_row_stays_typed_nid(db):
    window = {"from": "2026-10-01", "to": "2026-12-31", "basis": "quarter end"}
    result = run(db, part(atom="fin.revenue", dims={"exchange": "NSE"}),
                 as_of="2026-10-31", window=window)
    assert result.answer_type == "not_in_data"
    assert "2026-10-01..2026-12-31" in (result.nid_reason or "")


def test_dims_filter_sum_and_each_readings(db):
    bse = run(db, part(atom="fin.revenue", dims={"exchange": "BSE"}))
    assert bse.value == 112.0
    summed = run(db, part(atom="fin.revenue", dims={"exchange": "sum"}))
    assert summed.values[-1]["value"] == 222.0 and summed.answer_type == "measured"
    each = run(db, part(atom="fin.revenue", dims={"exchange": "each"},
                        operator="series", shape="series"))
    assert len({row["dims"].get("exchange") for row in each.values}) == 2


def test_each_is_never_silently_one_reading(db):
    result = run(db, part(atom="fin.revenue", dims={"exchange": "each"}))
    assert result.shape == "series" and result.numbers.get("each_readings")
    assert len({row["dims"].get("exchange") for row in result.values}) == 2


def test_series_renderer_prints_period_value_source_and_known_at(db):
    result = run(db, part(atom="price.close", operator="series", shape="series",
                          dims={"basis": "raw"}),
                 window={"from": "2026-01-01", "to": "2026-01-31"})
    text = render.render(result)
    assert "points" in text and "2026-01-01=100" in text
    assert "source px_nse" in text and "known_at 2026-01-03" in text
    assert render.answer_contract([result])["real_answered"] == 1


# --- dims the atom does not carry, YTD, sessions, CAGR ----------------------
def test_dim_the_atom_does_not_carry_is_ignored(db):
    """An exchange label ("its NSE close") does not reject a close with no exchange dim."""
    result = run(db, part(atom="price.close", dims={"exchange": "NSE"}),
                 window={"from": "2026-01-03", "to": "2026-01-03"})
    assert result.answer_type == "measured" and result.value == 90.0
    assert result.period == "2026-01-03"


def test_explicit_bse_on_an_unserved_atom_stays_nid(db):
    """The store's close is NSE-first: a real "on BSE" ask must not answer it."""
    result = run(db, part(atom="price.close", dims={"exchange": "BSE"}),
                 window={"from": "2026-01-03", "to": "2026-01-03"})
    assert result.answer_type == "not_in_data"
    assert "exchange=BSE" in (result.nid_reason or "")


def test_ytd_high_is_a_max_with_date_over_the_year(db):
    result = run(db, part(atom="price.high", dims={"lag": "ytd"}),
                 window={"from": "2026-01-03", "to": "2026-01-03"})
    assert result.operator == "max_with_date"
    assert (result.value, result.period) == (130.0, "2026-01-02")
    assert "YTD window 2026-01-01..2026-01-03" in (result.assumption or "")


def test_named_date_with_no_session_snaps_and_says_so(db):
    result = run(db, part(atom="price.close"),
                 window={"from": "2026-01-04", "to": "2026-01-04"})
    assert (result.value, result.period) == (90.0, "2026-01-03")
    assert "not a trading session" in (result.assumption or "")


def test_cagr_reads_price_closes_over_the_named_years(db):
    result = run(db, part(formula="f.cagr", dims={"basis": "raw"}),
                 window={"from": "2023-01-03", "to": "2026-01-03"})
    years = max(1096 / 365.25, 1.0 / 365.0)      # 2023-01-03 -> 2026-01-03 (2024 is leap)
    assert result.answer_type == "measured"
    assert result.value == pytest.approx(100.0 * ((90.0 / 100.0) ** (1.0 / years) - 1.0),
                                        rel=1e-6)
    assert "basis: raw close" in (result.assumption or "")


def _insert(db, rows):
    db.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", rows)
    db.commit()


def _bonus_rows(close_before=1000.0, close_after=500.0, adjusted=False):
    """A 1:1 bonus on 2024-01-03: 100 shares -> 200, 1000 -> 500 per share."""
    closes = [close_before, close_before, close_after, close_after, close_after]
    if adjusted:
        closes = [1000.0] * 5
    rows = [("INE001", "price.close", "", f"2024-01-0{day}", f"2024-01-0{day}", value,
             "INR", f"2024-01-0{day}", "px_nse")
            for day, value in zip(range(1, 6), closes)]
    rows += [("INE001", "price.shares_out", "", f"2024-01-0{day}", f"2024-01-0{day}",
              shares, "shares", f"2024-01-0{day}", "market_state.company_state_daily")
             for day, shares in zip(range(1, 6), (100.0, 100.0, 200.0, 200.0, 200.0))]
    return rows


def test_held_bonus_is_adjusted_and_named(db):
    """A raw 1:1 bonus is a 0% return after adjustment, never a -50% return."""
    _insert(db, _bonus_rows())
    result = run(db, part(formula="f.cagr", dims={"basis": "adjusted"}),
                 window={"from": "2023-12-01", "to": "2024-12-31"})
    assert result.answer_type == "measured"
    assert result.value == pytest.approx(0.0, abs=1e-9)
    note = result.assumption or ""
    assert "adjusted for split/bonus on 2024-01-03" in note
    assert "ratio 2" in note
    assert result.numbers.get("price_actions")


def test_adjusted_series_with_a_continuous_action_is_not_double_adjusted(db):
    """A build-adjusted close already carries the bonus: it must not be halved again."""
    _insert(db, _bonus_rows(adjusted=True))
    result = run(db, part(formula="f.cagr", dims={"basis": "adjusted"}),
                 window={"from": "2023-12-01", "to": "2024-12-31"})
    assert result.answer_type == "measured"
    assert result.value == pytest.approx(0.0, abs=1e-9)
    assert "adjusted for split/bonus on 2024-01-03" in (result.assumption or "")


def test_unexplained_jump_is_a_typed_nid(db):
    """A -50% close with no held ratio may be a bonus: never report it as a return."""
    _insert(db, [("INE001", "price.close", "", f"2024-01-0{day}", f"2024-01-0{day}",
                  value, "INR", f"2024-01-0{day}", "px_nse")
                 for day, value in zip(range(1, 5), (1000.0, 1000.0, 500.0, 500.0))])
    result = run(db, part(formula="f.cagr", dims={}),
                 window={"from": "2023-12-01", "to": "2024-12-31"})
    assert result.answer_type == "not_in_data"
    reason = result.nid_reason or ""
    assert "2024-01-03" in reason and "no held split/bonus ratio" in reason
    assert "ratio" in (result.to_close or "")


def test_change_over_a_price_window_states_its_basis(db):
    result = run(db, part(atom="price.close", operator="pct_change"),
                 window={"from": "2026-01-01", "to": "2026-01-03"})
    assert result.answer_type == "measured"
    assert result.value == pytest.approx(-10.0, rel=1e-6)
    assert "basis: raw close" in (result.assumption or "")


def test_total_return_says_dividends_are_not_adjusted(db):
    result = run(db, part(formula="f.cagr",
                          dims={"basis": "adjusted", "total_return": "yes"}),
                 window={"from": "2023-01-03", "to": "2026-01-02"})
    assert "not a total return" in (result.assumption or "")
    assert "dividends are not adjusted" in (result.assumption or "")


# --- estimate / proxy / NID ------------------------------------------------
def test_estimate_block_carries_method_and_inputs(db):
    result = run(db, part(atom="own.estimate", dims={"est_atom": "fin.revenue"}))
    assert result.answer_type == "estimate"
    assert (result.method, result.confidence) == ("trend", 0.55)
    assert result.inputs and result.inputs["n"] == 8
    text = render.render(result)
    assert "estimate" in text and "method trend" in text and "inputs:" in text
    assert grade_v2.part_status(part(atom="own.estimate", dims={"est_atom": "fin.revenue"}),
                                result)["covered"]


PROXY = {"value": 4.5, "unit": "%", "period": "2026-09-30",
         "assumption": "the institution total bounds the name-level position, "
                       "arithmetic: 9.0% of the 50% institution total",
         "confidence": 0.4, "sources": ["shp_index"], "search_log":
         "tasks/arch_v4/nid_search_logs/nim.json",
         "approved_by": "opus"}


def test_approved_proxy_counts_unapproved_does_not(db):
    approved = run(db, part(atom="fin.nim", dims={}), proxy=PROXY)
    assert approved.answer_type == "proxy"
    assert execute.counts_as_answered(approved)
    assert "approved_by opus" in render.render(approved)
    unapproved = run(db, part(atom="fin.nim", dims={}), proxy={**PROXY, "approved_by": None})
    assert unapproved.answer_type == "proxy"
    assert not execute.counts_as_answered(unapproved)
    assert "NOT APPROVED" in render.render(unapproved)


def test_nid_is_typed_and_never_answered(db):
    result = run(db, part(atom="fin.nim", dims={}))
    assert result.answer_type == "not_in_data"
    text = render.render(result)
    for phrase in ("NOT IN DATA:", "Tried:", "Checked:", "Why:", "To close:"):
        assert phrase in text
    assert not execute.counts_as_answered(result)
    assert grade_v2.part_status(part(atom="fin.nim", dims={}), result)["covered"] is False


def test_estimate_without_method_is_not_covered(db):
    result = run(db, part(atom="own.estimate", dims={"est_atom": "fin.revenue"}))
    broken = execute.as_result({**result.to_dict(), "method": None})
    status = grade_v2.part_status(part(atom="own.estimate", dims={"est_atom": "fin.revenue"}),
                                  broken)
    assert status["covered"] is False and "method" in status["reason"]


# --- the near-high study operator (§D.1, one operator for a distribution) ---
STUDY_WINDOW = {"from": "2026-01-01", "to": "2026-01-10"}
STUDY_AS_OF = "2026-01-10"
#: Ten sessions whose high rises to a spike on the last day.  A then-current high for an
#: early session is <= 103; today's high (210) would reject every early session, so the
#: count alone tells the two apart.
STUDY_SERIES = [
    ("2026-01-01", 100.0, 100.0),
    ("2026-01-02", 102.0, 101.0),
    ("2026-01-03", 101.0, 95.0),
    ("2026-01-04", 100.0, 99.0),
    ("2026-01-05", 103.0, 102.0),
    ("2026-01-06", 104.0, 101.0),
    ("2026-01-07", 105.0, 104.5),
    ("2026-01-08", 106.0, 105.0),
    ("2026-01-09", 107.0, 106.0),
    ("2026-01-10", 210.0, 200.0),
]
#: A low tail before the window so every session has the full 5-day trail (then-current
#: high); it never wins a max because it is far below the window's prices.
STUDY_WARMUP = [(f"2025-12-{day:02d}", 50.0, 49.0) for day in range(27, 32)]


def study_db(extra_rows=(), shares=()) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE fact(entity_id TEXT, atom TEXT, dims TEXT, period_start TEXT,
                          period_end TEXT, value REAL, unit TEXT, known_at TEXT,
                          source_ref TEXT);
        """)
    rows = []
    for day, high, close in STUDY_WARMUP + STUDY_SERIES:
        rows.append(("INE9", "price.high", "exchange=NSE", day, day, high, "INR",
                     day + "T23:59:59", "bhavcopy"))
        rows.append(("INE9", "price.close", "basis=raw", day, day, close, "INR", day,
                     "px_nse"))
    rows.extend(shares)
    rows.extend(extra_rows)
    conn.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def study_part(**kw) -> dict:
    dims = {"threshold": 3.0, "lookback_days": 5, "measure": "count"}
    dims.update(kw.pop("dims", {}))
    base = {"atom": "price.high", "dims": dims, "window": 0,
            "operator": "near_high", "shape": "scalar"}
    base.update(kw)
    return base


def study(conn, **kw):
    window = kw.pop("window", STUDY_WINDOW)
    return execute.execute(study_part(**kw), STUDY_AS_OF, conn,
                           windows=[window], entity="INE9")


def test_near_high_is_then_current_not_todays_high_and_counts_losers():
    conn = study_db()
    result = study(conn, dims={"forward": 1})
    assert result.answer_type == "measured" and result.value == 8
    assert [row["period"] for row in result.values] == [
        "2026-01-01", "2026-01-02", "2026-01-04", "2026-01-05", "2026-01-06",
        "2026-01-07", "2026-01-08", "2026-01-09"]
    # today's high (210) for every session would leave nobody within 3% of it
    assert result.numbers["n_sessions"] == 10
    assert result.numbers["winners"] == 6 and result.numbers["losers"] == 2
    losers = [row for row in result.values if row["forward_pct"] < 0]
    assert [row["period"] for row in losers] == ["2026-01-02", "2026-01-05"]
    assert "losers 2" in render.render(result)
    # the high behind each row is the max of its own trail, never the full series
    assert result.values[0]["high_52w"] == 100.0
    assert result.values[2]["high_52w"] == 102.0


def test_near_high_never_sees_a_row_after_as_of():
    clean = study(study_db(), dims={"forward": 1})
    later = study(study_db(extra_rows=[
        # a high inside the trail but published after as_of: the known_at cut hides it
        ("INE9", "price.high", "exchange=NSE", "2026-01-02", "2026-01-02", 1000.0,
         "INR", "2027-01-01", "bhavcopy"),
        # a row dated after as_of: the window cut hides it even with an early known_at
        ("INE9", "price.high", "exchange=NSE", "2026-01-11", "2026-01-11", 1000.0,
         "INR", "2026-01-11", "bhavcopy"),
        # a later revision of the last session: not visible at as_of, so cannot move it
        ("INE9", "price.close", "basis=raw", "2026-01-10", "2026-01-10", 1.0,
         "INR", "2026-12-31", "px_nse"),
    ]), dims={"forward": 1})
    assert later.value == clean.value == 8
    assert later.values == clean.values
    assert max(row["period"] for row in later.values) <= STUDY_AS_OF
    assert all(row["forward_end"] <= STUDY_AS_OF for row in later.values)


def test_near_high_incomplete_forward_window_is_counted_and_named():
    conn = study_db()
    result = study(conn, dims={"threshold": 5.0, "forward": 1})
    assert result.value == 9
    assert result.numbers["forward_incomplete"] == 1
    assert result.numbers["incomplete_sessions"] == ["2026-01-10"]
    assert result.values[-1]["forward_status"].startswith("incomplete")
    assert "incomplete 1" in render.render(result)


def test_near_high_without_a_full_trail_is_a_typed_nid():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE fact(entity_id TEXT, atom TEXT, dims TEXT, period_start TEXT,
                          period_end TEXT, value REAL, unit TEXT, known_at TEXT,
                          source_ref TEXT);
        """)
    rows = []
    for day, high, close in STUDY_SERIES[:3]:
        rows.append(("INE9", "price.high", "exchange=NSE", day, day, high, "INR", day,
                     "bhavcopy"))
        rows.append(("INE9", "price.close", "basis=raw", day, day, close, "INR", day,
                     "px_nse"))
    conn.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", rows)
    result = execute.execute(
        study_part(), STUDY_AS_OF, conn,
        windows=[{"from": "2026-01-01", "to": "2026-01-03"}], entity="INE9")
    assert result.answer_type == "not_in_data"
    reason = result.nid_reason or ""
    assert "no 5 days of daily prices" in reason
    assert "starts 2026-01-01" in reason


def test_near_high_names_a_corporate_action_in_its_trail():
    shares = [("INE9", "price.shares_out", "", "2026-01-01", "2026-01-01", 100.0,
               "shares", "2026-01-01", "px_nse"),
              ("INE9", "price.shares_out", "", "2026-01-03", "2026-01-03", 200.0,
               "shares", "2026-01-03", "px_nse")]
    result = study(study_db(shares=shares))
    assumption = result.assumption or ""
    assert result.numbers["corporate_actions"]
    assert "2026-01-03" in assumption and "shares 100 -> 200" in assumption
    assert "raw prices across it are not adjusted" in assumption


# --- rank, claim, walk, formula, rule --------------------------------------
def test_ranked_list_orders_entities(db):
    result = run(db, part(atom="price.close", operator="rank",
                          shape="top-n list with values", dims={"basis": "raw",
                                                               "limit": 2}),
                 window={"from": "2026-10-01", "to": "2026-10-31"})
    assert [row["entity_id"] for row in result.entities][:2] == ["INE003", "INE002"]
    assert result.answer_type == "measured"
    assert "INE003 70" in render.render(result)


def test_claim_passage(db):
    result = run(db, part(atom="claim.claim", dims={"topic": "demand"},
                          shape="passage"))
    assert result.answer_type == "measured" and result.values[0]["quote"].startswith(
        "Demand remained strong")
    assert "Demand remained strong" in render.render(result)


def test_walk_is_bounded_and_pit_filtered(db):
    result = run(db, part(operator="walk", dims={"driver": "DRIVER", "max_hops": 5}))
    assert result.shape == "path" and len(result.values) == 2
    assert result.values[0]["target"] == "A" and result.values[1]["target"] == "B"
    later = run(db, part(operator="walk", dims={"driver": "DRIVER"}), as_of="2026-09-30")
    assert later.answer_type == "not_in_data"  # the edges are known only from 2026-10-01


def test_formula_margin_over_the_fact_view(db):
    result = run(db, part(formula="f.margin",
                          dims={"margin_kind": "ebitda", "exchange": "NSE"}))
    assert result.answer_type == "measured"
    assert result.value == pytest.approx(30.0 / 110.0 * 100.0, rel=1e-6)
    assert result.unit == "%" and result.inputs


def test_rule_control_change_reads_holder_classes(db):
    result = run(db, part(operator="rule", judgement=True,
                          dims={"rule": "control_change"}))
    assert result.answer_type == "measured" and result.verdict == "control change"
    assert result.rule_used and "5pp" in result.rule_used


def test_measured_without_known_at_is_not_covered(db):
    result = run(db, part(atom="fin.revenue", dims={"exchange": "NSE"}))
    broken = execute.as_result({**result.to_dict(), "known_at": None})
    status = grade_v2.part_status(part(atom="fin.revenue", dims={"exchange": "NSE"}),
                                  broken)
    assert status["covered"] is False and "known_at" in status["reason"]


def test_unknown_operator_and_atom_stay_typed(db):
    for p in (part(atom="fin.revenue", operator="not_an_operator"),
              part(atom="zzz.unknown")):
        result = run(db, p)
        assert result.answer_type in execute.ANSWER_TYPES
        assert result.part_index == 0


# --- what a result really is (false-label classes, 2026-10-31) --------------
def _fact_store(rows) -> sqlite3.Connection:
    """A fact store with the WP2a shape (``atom``, not ``atom_id``)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE fact(entity_id TEXT, atom TEXT, dims TEXT, period_start TEXT,
                          period_end TEXT, value REAL, unit TEXT, known_at TEXT,
                          source_ref TEXT);
        """)
    conn.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def test_a_change_is_printed_as_a_change_with_its_start_and_end():
    """MB1033#L: the +359.1 close change was printed as "price.close: 359.1"."""
    conn = _fact_store([
        ("INE047A01021", "price.close", "basis=raw", "2025-09-24", "2025-09-24", 2807.4,
         "INR", "2025-09-24", "market_state.company_state_daily"),
        ("INE047A01021", "price.close", "basis=raw", "2026-09-24", "2026-09-24", 3166.5,
         "INR", "2026-09-24", "market_state.company_state_daily"),
        ("INE345A01011", "price.delivery_pct", "exchange=NSE", "2019-01-01", "2019-01-01",
         32.9, "%", "2019-01-01", "market_state_b.mkt_nse_full_daily"),
        ("INE345A01011", "price.delivery_pct", "exchange=NSE", "2026-09-24", "2026-09-24",
         40.57, "%", "2026-09-24", "market_state_b.mkt_nse_full_daily"),
    ])
    window = {"from": "2025-09-24", "to": "2026-09-24"}
    close = execute.execute(part(atom="price.close", operator="change"), "2026-09-24",
                            conn, windows=[window], entity="INE047A01021")
    weight = {"from": "2019-01-01", "to": "2026-09-24"}
    delivery = execute.execute(part(atom="price.delivery_pct", operator="change"),
                               "2026-09-24", conn, windows=[weight],
                               entity="INE345A01011")
    assert close.value == pytest.approx(359.1)
    assert delivery.value == pytest.approx(7.67)
    text = render.render(close)
    assert "price.close change" in text
    assert "from 2,807.40 on 2025-09-24 to 3,166.50 on 2026-09-24" in text
    assert "price.close: 359.1" not in text
    text = render.render(delivery)
    assert "price.delivery_pct change" in text
    assert "from 32.9 on 2019-01-01 to 40.57 on 2026-09-24" in text
    assert "price.delivery_pct: 7.67" not in text


def test_a_ratio_names_its_kind_and_only_the_inputs_it_used():
    """MB0064#L / MB0004#L: a P/B cited the source of a debt ratio."""
    conn = _fact_store([
        ("INE752E01010", "price.mcap", "", "2026-10-19", "2026-10-19", 232840.521,
         "INR_CRORE", "2026-10-19", "market_state.company_state_daily"),
        ("INE752E01010", "fin.book_equity",
         "basis=consolidated;period_kind=fy", "2026-03-31", "2026-03-31", 100494.02,
         "INR_CRORE", "2026-05-15", "facts_pilot.company_metric_series"),
        ("INE752E01010", "fin.total_debt",
         "basis=consolidated;period_kind=fy", "2026-03-31", "2026-03-31", 148009.01,
         "INR_CRORE", "2026-05-15",
         "derived:facts_pilot.company_metric_series:borrowings_current+"
         "borrowings_noncurrent"),
    ])
    result = execute.execute(
        part(formula="f.ratio", dims={"ratio_kind": "pb"}), "2026-10-19", conn,
        windows=[{"from": None, "to": "2026-10-19", "basis": "as_of"}],
        entity="INE752E01010")
    assert result.answer_type == "measured"
    assert result.value == pytest.approx(232840.521 / 100494.02, rel=1e-6)
    assert result.source_ref == "derived:f.ratio(pb):price.mcap+fin.book_equity"
    assert [row["atom"] for row in result.inputs] == ["price.mcap", "fin.book_equity"]
    assert result.numbers["ratio_kind"] == "pb"
    assert result.period == "2026-03-31"      # the last input the arithmetic reads
    text = render.render(result)
    assert "f.ratio (pb)" in text and "price.mcap+fin.book_equity" in text
    assert "borrowings" not in text


def test_a_years_old_latest_is_a_typed_failure_not_a_current_value():
    """MB0997#MS: FY21 capex was offered as the current capex on 2026-10-19."""
    conn = _fact_store([
        ("INE589A01014", "fin.capex", "basis=consolidated;period_kind=quarter",
         "2021-03-31", "2021-03-31", 2318.79, "INR_CRORE", "2021-06-30",
         "quarters.company_quarter_series#capex"),
    ])
    result = execute.execute(
        part(atom="fin.capex"), "2026-10-19", conn,
        windows=[{"from": None, "to": "2026-10-19", "basis": "as_of"}],
        entity="INE589A01014")
    assert result.answer_type == "not_in_data"
    reason = result.nid_reason or ""
    assert "2021-03-31" in reason and "2028 days" in reason and "400-day" in reason
    text = render.render(result)
    assert "NOT IN DATA" in text and "2,318.79" not in text


def test_an_impossible_share_and_an_unstatable_list_are_typed_failures():
    """MB0974#MI: f.share_of 4,357.91%; MB0525: "—" on a 4,357-value series."""
    conn = _fact_store([
        ("INE278R01034", "fin.segment_value",
         "basis=consolidated;metric=revenue;segment=Food", "2025-03-31", "2025-03-31",
         157.2899, "INR_CRORE", "2025-12-06", "facts_pilot.company_segment_pnl"),
        ("INE278R01034", "fin.revenue", "basis=consolidated;period_kind=quarter",
         "2025-09-30", "2025-09-30", 3.6093, "INR_CRORE", "2026-04-10",
         "facts_pilot.company_metric_series"),
    ])
    share = execute.execute(
        part(formula="f.share_of"), "2026-10-19", conn,
        windows=[{"from": None, "to": "2026-10-19", "basis": "as_of"}],
        entity="INE278R01034")
    assert share.answer_type == "not_in_data"
    assert "4,357.91%" in (share.nid_reason or "")
    assert "cannot exceed 100%" in (share.nid_reason or "")
    assert "P1 not_in_data" in render.render(share)

    series = _fact_store([
        ("wb_zinc", "macro.commodity_close", "commodity=wb_zinc", "2026-09-30",
         "2026-09-30", 1000.0 + index, "USD", "2026-10-02",
         "market_state_b.series_observation") for index in range(4357)])
    distinct = execute.execute(
        part(atom="macro.commodity_close", operator="list_distinct",
             dims={"distinct": "value"}), "2026-10-07", series,
        windows=[{"from": None, "to": "2026-10-07"}])
    assert distinct.answer_type == "not_in_data"
    assert "4,357 distinct value values" in (distinct.nid_reason or "")
    text = render.render(distinct)
    assert "NOT IN DATA" in text and "measured" not in text

    small = _fact_store([
        ("wb_zinc", "macro.commodity_close", "commodity=wb_zinc", "2026-09-30",
         "2026-09-30", float(index + 1), "USD", "2026-10-02",
         "market_state_b.series_observation") for index in range(3)])
    stated = execute.execute(
        part(atom="macro.commodity_close", operator="list_distinct",
             dims={"distinct": "value"}), "2026-10-07", small,
        windows=[{"from": None, "to": "2026-10-07"}])
    assert stated.answer_type == "measured"
    assert "3 distinct value" in render.render(stated)


def _close_store(raw: bool) -> sqlite3.Connection:
    """A 1:1 bonus on 2024-01-03 (1000 -> 500): raw closes or a build-adjusted panel."""
    dims = "basis=raw" if raw else ""
    rows = [("INE001", "price.close", dims, f"2024-01-0{day}", f"2024-01-0{day}", value,
             "INR", f"2024-01-0{day}", "market_state.company_state_daily")
            for day, value in zip(range(1, 6), (1000.0, 1000.0, 500.0, 500.0, 500.0))]
    rows += [("INE001", "price.shares_out", "", f"2024-01-0{day}", f"2024-01-0{day}",
              shares, "shares", f"2024-01-0{day}", "market_state.company_state_daily")
             for day, shares in zip(range(1, 6), (100.0, 100.0, 200.0, 200.0, 200.0))]
    rows += [("INE001", "price.mcap", "", f"2024-01-0{day}", f"2024-01-0{day}",
              mcap, "INR_CRORE", f"2024-01-0{day}", "market_state.company_state_daily")
             for day, mcap in zip(range(1, 6), (10.0, 10.0, 10.0, 10.0, 10.0))]
    return _fact_store(rows)


def test_a_level_is_the_traded_close_and_a_return_is_the_adjusted_series():
    """POWERGRID 2023-09-11: a stated close before an action is not a traded price."""
    raw = _close_store(raw=True)
    level = execute.execute(part(atom="price.close"), "2024-01-05", raw,
                            windows=[{"from": "2024-01-03", "to": "2024-01-03"}],
                            entity="INE001")
    assert level.answer_type == "measured" and level.value == 500.0
    assert "raw close" in (level.assumption or "")
    assert level.numbers.get("close_basis") == "raw"
    assert "traded close" in render.render(level)

    ret = execute.execute(part(atom="price.close", operator="pct_change"), "2024-01-05",
                          raw, windows=[{"from": "2024-01-01", "to": "2024-01-05"}],
                          entity="INE001")
    assert ret.answer_type == "measured" and ret.value == pytest.approx(0.0, abs=1e-9)
    assert "adjusted for split/bonus on 2024-01-03" in (ret.assumption or "")
    assert ret.numbers.get("price_basis") == "adjusted"

    old = _close_store(raw=False)       # a store built before fact_view.sql's raw_close
    old_level = execute.execute(part(atom="price.close"), "2024-01-05", old,
                                windows=[{"from": "2024-01-03", "to": "2024-01-03"}],
                                entity="INE001")
    note = old_level.assumption or ""
    assert old_level.answer_type == "measured"
    assert "adjusted close" in note and "not a traded price" in note
    assert "raw close" not in note
# --- the grader ------------------------------------------------------------
ASK = {"as_of": "2026-10-31", "windows": [WINDOW],
       "entities": [{"isin": "INE001", "level": "stock"}],
       "parts": [{"atom": "fin.revenue", "dims": {"exchange": "NSE"}, "window": 0,
                  "operator": "value_at", "shape": "scalar", "judgement": False},
                 {"atom": "fin.nim", "dims": {}, "window": 0,
                  "operator": "value_at", "shape": "scalar", "judgement": False}]}


def test_multi_part_ask_needs_every_part(db):
    results = execute.execute_ask(ASK, db)
    status = grade_v2.case_status(ASK, results)
    assert status["parts"] == 2 and status["real_answered"] == 1
    assert status["covered"] is False
    dropped = grade_v2.case_status(ASK, results[:1])
    assert dropped["covered"] is False and dropped["not_answered"] == 1
    proxied = execute.execute_ask(ASK, db, proxies={1: PROXY})
    status = grade_v2.case_status(ASK, proxied)
    assert status["covered"] is True
    assert status["real_answered"] == 1 and status["proxy_answered"] == 1


def test_unrelated_result_fails_the_case(db):
    results = execute.execute_ask(ASK, db)
    stray = execute.Result(part_index=9, atom="price.close", answer_type="measured",
                           value=1.0, unit="INR", period="2026-09-30", isin="INE001",
                           source_ref="px_nse", known_at="2026-10-31")
    status = grade_v2.case_status(ASK, results + [stray])
    assert status["covered"] is False and status["unrelated"]


def test_grade_run_counts_real_and_proxy_separately(db):
    cases = [{"mid": "C1", "ask": ASK},
             {"mid": "C2", "ask": {**ASK, "parts": ASK["parts"][:1]}}]
    results = {"C1": execute.execute_ask(ASK, db, proxies={1: PROXY}),
               "C2": execute.execute_ask({**ASK, "parts": ASK["parts"][:1]}, db)}
    summary = grade_v2.grade_run(cases, results)["summary"]
    assert summary["rows"] == 2 and summary["answered"] == 2
    assert summary["real_answered_parts"] == 2
    assert summary["proxy_answered_parts"] == 1
