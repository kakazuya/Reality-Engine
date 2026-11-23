"""T-134: exact periods and stored derivations (quarters, halves, TTM, YoY, QoQ).

Values below are comparable to SBI Life APE, in INR billions rendered at 1e9 (base rupees).
"""
import json
import sqlite3

import pytest

from reality_engine.v2 import schema
from reality_engine.v2.periods import derive, fiscal_label, period_row

BILLION = 1_000_000_000


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema.create(conn)
    conn.execute("INSERT INTO entity (entity_id, isin, name, kind) "
                 "VALUES (1, 'INE123A01016', 'SBI Life', 'company')")
    return conn


def _period(conn, start, end):
    row = period_row(start, end)
    conn.execute("INSERT OR IGNORE INTO period VALUES (?,?,?,?,?)",
                 (row["period_id"], row["start_date"], row["end_date"], row["kind"],
                  row["fiscal_label"]))
    return row["period_id"]


def _fact(conn, period_id, value, *, unit="inr", known_at="2026-01-01T00:00:00",
          kind="reported", definition="reported", metric="ape"):
    cursor = conn.execute(
        "INSERT INTO fact (entity_id, metric, dimension, period_id, basis, definition, kind, "
        "value, unit, known_at) VALUES (1,?,?,?,'na',?,?,?,?,?)",
        (metric, "", period_id, definition, kind, value, unit, known_at))
    return int(cursor.lastrowid)


def _billions(value):
    return value * BILLION


def _derived(conn, label, metric="ape"):
    """Every fact stored for one fiscal label, with its derivation row when derived."""
    return conn.execute(
        "SELECT f.fact_id, f.value, f.unit, f.kind, f.known_at, f.superseded_at, "
        "f.check_detail, p.fiscal_label, p.kind AS period_kind, d.formula_id, d.input_ids "
        "FROM fact f JOIN period p ON p.period_id = f.period_id "
        "LEFT JOIN derivation d ON d.fact_id = f.fact_id "
        "WHERE f.metric=? AND p.fiscal_label=? ORDER BY f.fact_id",
        (metric, label)).fetchall()


def _rows_with(conn, label, formula_id, metric="ape"):
    return [r for r in _derived(conn, label, metric) if r["formula_id"] == formula_id]


def _one_row(conn, label, formula_id, metric="ape"):
    rows = _rows_with(conn, label, formula_id, metric)
    assert len(rows) == 1, [(r["formula_id"], r["value"]) for r in rows]
    return rows[0]


def _one(conn, label, metric="ape"):
    rows = [r for r in _derived(conn, label, metric) if r["formula_id"] is not None]
    assert len(rows) == 1, [(r["formula_id"], r["value"]) for r in rows]
    return rows[0]


def _period_with_label(conn, label):
    return next(p for p in conn.execute("SELECT * FROM period")
                if p["fiscal_label"] == label)


def test_quarters_halves_and_input_order():
    conn = _conn()
    h1 = _period(conn, "2025-04-01", "2025-09-30")
    nine = _period(conn, "2025-04-01", "2025-12-31")
    fy = _period(conn, "2025-04-01", "2026-03-31")
    q1 = _period(conn, "2025-04-01", "2025-06-30")
    h1_id = _fact(conn, h1, _billions(99.2), known_at="2025-10-25T16:00:00")
    nine_id = _fact(conn, nine, _billions(168.8), known_at="2026-01-25T16:00:00")
    fy_id = _fact(conn, fy, _billions(221.1), known_at="2026-04-28T20:41:01")
    q1_id = _fact(conn, q1, _billions(39.7), known_at="2025-07-24T14:55:31")

    result = derive(conn, 1, "ape")

    q3 = _one(conn, "Q3FY26")
    assert q3["formula_id"] == "Q_FROM_9M_LESS_H1"
    assert json.loads(q3["input_ids"]) == [nine_id, h1_id]
    assert q3["value"] == pytest.approx(_billions(69.6), rel=1e-12)
    assert q3["known_at"] == "2026-01-25T16:00:00"

    q4 = _one(conn, "Q4FY26")
    assert q4["formula_id"] == "Q_FROM_FY_LESS_9M"
    assert json.loads(q4["input_ids"]) == [fy_id, nine_id]
    assert q4["value"] == pytest.approx(_billions(52.3), rel=1e-12)
    assert q4["known_at"] == "2026-04-28T20:41:01"

    q2 = _one(conn, "Q2FY26")
    assert q2["formula_id"] == "Q_FROM_H1_LESS_Q1"
    assert json.loads(q2["input_ids"]) == [h1_id, q1_id]
    assert q2["value"] == pytest.approx(_billions(59.5), rel=1e-12)

    for row in (q2, q3, q4):
        assert row["kind"] == "derived"
        assert row["unit"] == "inr"
        assert row["period_kind"] == "Q"
    # H2FY26 = FY26 - H1FY26 is a half year, not one of the quarter tests
    h2 = _one(conn, "H2FY26")
    assert h2["formula_id"] == "H2_FROM_FY_LESS_H1"
    assert h2["value"] == pytest.approx(_billions(221.1 - 99.2), rel=1e-12)
    # Q1..Q4 is exactly FY26: a full year is not relabelled TTM
    assert _derived(conn, "TTM to Q4FY26") == []
    assert result["written"] == 4


def test_conflicting_period_blocks_fy_derivations():
    conn = _conn()
    h1 = _period(conn, "2025-04-01", "2025-09-30")
    nine = _period(conn, "2025-04-01", "2025-12-31")
    fy = _period(conn, "2025-04-01", "2026-03-31")
    _fact(conn, h1, _billions(99.2))
    _fact(conn, nine, _billions(168.8))
    first = _fact(conn, fy, _billions(242.7), known_at="2026-04-28T20:41:01")
    second = _fact(conn, fy, _billions(221.1), known_at="2026-04-28T20:41:01")

    result = derive(conn, 1, "ape")

    conflict = [c for c in result["conflicts"] if c["period_id"] == fy]
    assert len(conflict) == 1
    assert conflict[0]["fiscal_label"] == "FY26"
    assert conflict[0]["values"] == sorted([_billions(242.7), _billions(221.1)])
    assert sorted(conflict[0]["fact_ids"]) == sorted([first, second])
    assert _one(conn, "Q3FY26")["value"] == pytest.approx(_billions(69.6), rel=1e-12)
    assert [r for r in _derived(conn, "Q4FY26") if r["formula_id"] is not None] == []          # FY26 is an unreliable input
    assert _derived(conn, "H2FY26") == []


def test_ttm_from_four_quarters_and_from_fy_plus_ytd():
    quarters_and_fy = [
        ("Q3FY26", "2025-10-01", "2025-12-31", 69.6),
        ("Q4FY26", "2026-01-01", "2026-03-31", 52.3),
        ("Q1FY27", "2026-04-01", "2026-06-30", 59.5),
        ("Q2FY27", "2026-07-01", "2026-09-30", 60.0),
        ("FY26", "2025-04-01", "2026-03-31", 221.1),
        ("H1FY26", "2025-04-01", "2025-09-30", 99.2),
        ("H1FY27", "2026-04-01", "2026-09-30", 119.5),
    ]
    conn = _conn()
    ids = {}
    for label, start, end, value in quarters_and_fy:
        ids[label] = _fact(conn, _period(conn, start, end), _billions(value))
    expected_ttm = _billions(69.6 + 52.3 + 59.5 + 60.0)   # = 221.1 + 119.5 - 99.2

    result = derive(conn, 1, "ape")

    ttm = _one(conn, "TTM to Q2FY27")
    assert ttm["period_kind"] == "TTM"
    assert ttm["formula_id"] == "TTM_SUM4Q"
    assert ttm["value"] == pytest.approx(expected_ttm, rel=1e-12)
    assert json.loads(ttm["input_ids"]) == [
        ids["Q3FY26"], ids["Q4FY26"], ids["Q1FY27"], ids["Q2FY27"]]
    # the second route agrees instead of writing a duplicate row for the same period
    assert any(s["formula_id"] == "TTM_FY_PLUS_YTD_LESS_PRIOR_YTD"
               and s["reason"] == "agrees_with_derivation" for s in result["skipped"])
    # no YoY for the TTM period, and no check_detail comparing FY26 with a TTM
    assert conn.execute(
        "SELECT count(*) FROM fact f JOIN period p ON p.period_id=f.period_id "
        "JOIN derivation d ON d.fact_id=f.fact_id "
        "WHERE p.kind='TTM' AND d.formula_id='YOY_PCT'").fetchone()[0] == 0
    fy26 = conn.execute("SELECT check_detail FROM fact WHERE fact_id=?", (ids["FY26"],)).fetchone()
    assert fy26["check_detail"] is None

    # the FY + YTD - prior YTD route on its own
    conn2 = _conn()
    fy_id = _fact(conn2, _period(conn2, "2025-04-01", "2026-03-31"), _billions(221.1))
    h1_26 = _fact(conn2, _period(conn2, "2025-04-01", "2025-09-30"), _billions(99.2))
    h1_27 = _fact(conn2, _period(conn2, "2026-04-01", "2026-09-30"), _billions(119.5))
    derive(conn2, 1, "ape")
    ttm2 = _one(conn2, "TTM to Q2FY27")
    assert ttm2["formula_id"] == "TTM_FY_PLUS_YTD_LESS_PRIOR_YTD"
    assert json.loads(ttm2["input_ids"]) == [fy_id, h1_27, h1_26]
    assert ttm2["value"] == pytest.approx(expected_ttm, rel=1e-12)


def test_reported_quarter_is_compared_not_overwritten():
    conn = _conn()
    q1 = _period(conn, "2025-04-01", "2025-06-30")
    h1 = _period(conn, "2025-04-01", "2025-09-30")
    nine = _period(conn, "2025-04-01", "2025-12-31")
    fy = _period(conn, "2025-04-01", "2026-03-31")
    q4 = _period(conn, "2026-01-01", "2026-03-31")
    _fact(conn, q1, _billions(39.7))
    _fact(conn, h1, _billions(99.2))
    _fact(conn, nine, _billions(168.8))
    _fact(conn, fy, _billions(221.1))
    reported_q4 = _fact(conn, q4, _billions(53.0))     # FY - 9M would be 52.3

    result = derive(conn, 1, "ape")

    assert [r for r in _derived(conn, "Q4FY26") if r["formula_id"] is not None] == []
    row = conn.execute("SELECT value, kind, check_status, check_detail FROM fact "
                       "WHERE fact_id=?", (reported_q4,)).fetchone()
    assert row["kind"] == "reported"
    assert row["value"] == _billions(53.0)
    assert row["check_status"] == "unverified"
    assert row["check_detail"] == "derived 52300000000 vs reported 53000000000"
    assert any(s["reason"] == "reported_differs" for s in result["skipped"])
    # the other cumulative derivations are unaffected
    assert _one(conn, "Q3FY26")["value"] == pytest.approx(_billions(69.6), rel=1e-12)


def test_non_additive_metric_gets_only_growth():
    conn = _conn()
    values = {
        ("Q1FY26", "2025-04-01", "2025-06-30"): 18.0,
        ("Q2FY26", "2025-07-01", "2025-09-30"): 20.0,
        ("Q1FY27", "2026-04-01", "2026-06-30"): 20.0,
        ("Q2FY27", "2026-07-01", "2026-09-30"): 25.0,
    }
    ids = {label: _fact(conn, _period(conn, start, end), value, unit="pct",
                        metric="vnb_margin")
           for (label, start, end), value in values.items()}

    result = derive(conn, 1, "vnb_margin", additive=False)

    assert result["written"] == 4      # YoY Q1FY27, YoY Q2FY27, QoQ Q2FY26, QoQ Q2FY27
    formulas = {r["formula_id"] for r in conn.execute(
        "SELECT d.formula_id FROM fact f JOIN derivation d ON d.fact_id=f.fact_id "
        "WHERE f.metric='vnb_margin'").fetchall()}
    assert formulas == {"YOY_PCT", "QOQ_PCT"}
    yoy_q1 = _one_row(conn, "Q1FY27", "YOY_PCT", "vnb_margin")
    assert json.loads(yoy_q1["input_ids"]) == [ids["Q1FY26"], ids["Q1FY27"]]
    assert yoy_q1["value"] == pytest.approx((20.0 / 18.0 - 1.0) * 100.0, rel=1e-12)
    qoq = _one_row(conn, "Q2FY27", "QOQ_PCT", "vnb_margin")
    assert qoq["value"] == pytest.approx(25.0, rel=1e-12)
    # no quarter/half/year sum was written for a ratio
    assert conn.execute(
        "SELECT count(*) FROM fact f JOIN derivation d ON d.fact_id=f.fact_id "
        "WHERE d.formula_id LIKE 'Q_FROM%'").fetchone()[0] == 0


def test_yoy_uses_the_fact_known_at_the_as_of_date():
    conn = _conn()
    fy25 = _period(conn, "2024-04-01", "2025-03-31")
    fy26 = _period(conn, "2025-04-01", "2026-03-31")
    old = _fact(conn, fy25, _billions(200.0), known_at="2026-01-15T16:00:00")
    conn.execute("UPDATE fact SET superseded_at='2026-05-01T10:00:00' WHERE fact_id=?", (old,))
    _fact(conn, fy25, _billions(210.0), known_at="2026-05-01T10:00:00")
    _fact(conn, fy26, _billions(250.0), known_at="2026-04-28T20:41:01")

    derive(conn, 1, "ape", as_of="2026-04-30")
    rows = [r for r in _derived(conn, "FY26") if r["formula_id"] == "YOY_PCT"]
    assert len(rows) == 1
    assert rows[0]["value"] == pytest.approx(25.0, rel=1e-12)
    assert rows[0]["known_at"] == "2026-04-28T20:41:01"

    derive(conn, 1, "ape")                       # now the restatement is in force
    rows = conn.execute(
        "SELECT f.value, f.known_at, f.superseded_at FROM fact f "
        "JOIN period p ON p.period_id=f.period_id "
        "JOIN derivation d ON d.fact_id=f.fact_id "
        "WHERE f.metric='ape' AND d.formula_id='YOY_PCT' AND p.fiscal_label='FY26' "
        "ORDER BY f.fact_id").fetchall()
    assert len(rows) == 2
    assert rows[0]["superseded_at"] == "2026-05-01T10:00:00"
    current = [r for r in rows if r["superseded_at"] is None]
    assert len(current) == 1
    assert current[0]["value"] == pytest.approx((250.0 / 210.0 - 1.0) * 100.0, rel=1e-12)
    assert current[0]["known_at"] == "2026-05-01T10:00:00"


def test_fiscal_labels_and_period_rows():
    assert fiscal_label("2026-07-01", "2026-09-30") == "Q2FY27"
    assert fiscal_label("2026-04-01", "2026-09-30") == "H1FY27"
    assert fiscal_label("2026-04-01", "2026-12-31") == "9MFY27"
    assert fiscal_label("2025-04-01", "2026-03-31") == "FY26"
    assert fiscal_label("2025-10-01", "2026-03-31") == "H2FY26"
    assert fiscal_label("2025-10-01", "2026-09-30") == "TTM to Q2FY27"
    assert fiscal_label(None, "2026-09-30") == "30 Sep 2026"
    assert fiscal_label("2026-01-01", "2026-03-31", fy_end_month=12) == "Q1FY26"

    row = period_row(None, "2026-09-30")
    assert row["kind"] == "POINT" and row["start_date"] is None
    assert row["period_id"] == "/2026-09-30" and row["fiscal_label"] == "30 Sep 2026"
    assert period_row("2025-04-01", "2026-03-31")["kind"] == "FY"
    assert period_row("2026-02-01", "2026-02-28")["kind"] == "M"

    with pytest.raises(ValueError):
        period_row("2026-05-01", "2026-06-15")
    assert period_row("2026-05-01", "2026-06-15", allow_other=True)["kind"] == "OTHER"
    with pytest.raises(ValueError):
        period_row("2026-04-02", "2026-04-01")


def test_rerun_writes_nothing():
    conn = _conn()
    _fact(conn, _period(conn, "2025-04-01", "2025-06-30"), _billions(39.7))
    _fact(conn, _period(conn, "2025-04-01", "2025-09-30"), _billions(99.2))
    _fact(conn, _period(conn, "2025-04-01", "2025-12-31"), _billions(168.8))
    _fact(conn, _period(conn, "2025-04-01", "2026-03-31"), _billions(221.1))
    first = derive(conn, 1, "ape")
    second = derive(conn, 1, "ape")
    assert first["written"] == 4
    assert second["written"] == 0
    assert conn.execute("SELECT count(*) FROM derivation").fetchone()[0] == 4
