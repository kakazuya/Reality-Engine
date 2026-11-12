"""T-155: every pilot3 build keeps price history from ``price_start`` (2019-01-01 by default), whatever the
profile's ``window_start``: ``price_delivery``, ``index_price`` and ``valuation_daily`` keep a 2020 row while the
document stores still start at the window, and a valuation day whose PE/PB/EV inputs are not known keeps its close
and market cap with NULL ratios.  Fixtures only: in-memory sqlite built from the real DDL, no store, no network.

    python -m pytest reality_engine/tests/test_pilot3_price_window.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reality_engine.pilot3 import profile, ratios, schema, stores

SYM, ISIN = "MARUTI", "INE585B01010"
PRICE_COLUMNS = 21
INDEX_COLUMNS = 24


def _activate(window_start: str | None = "2023-10-01", price_start: str | None = None,
              compute_start: str | None = None) -> profile.Profile:
    """A one-company profile: documents from ``window_start``, prices from the default 2019-01-01 unless set."""
    active = profile.Profile(
        name="fixture", pages_db=Path("pages.db"), raw_root=Path("."), manifest=Path("manifest.csv"),
        out=Path("pilot.db"), window_start=window_start, price_start=price_start, compute_start=compute_start,
        companies=(profile.ProfileCompany(symbol=SYM, name="Maruti Suzuki India Ltd", bse_code="532500",
                                          isins=(ISIN,)),))
    profile.activate(active)
    return active


def _price(conn: sqlite3.Connection, day: str, close: float = 100.0) -> None:
    conn.execute("INSERT INTO price_delivery VALUES (" + ",".join("?" * PRICE_COLUMNS) + ")",
                 (SYM, ISIN, "NSE", day, close, close, close, close, close, 1.0, 1.0, 1.0, 1.0, 50.0,
                  1.0, close, day, "x", "d", "t", day))


def _index(conn: sqlite3.Connection, day: str, close: float = 10000.0) -> None:
    conn.execute("INSERT INTO index_price VALUES (" + ",".join("?" * INDEX_COLUMNS) + ")",
                 (SYM, ISIN, "Nifty 50", day, close, 100.0, 100.0, None, None, None, None, None, None, None, None,
                  None, None, None, None, day, "x", "d", "t", day))


def _quarter(conn: sqlite3.Connection, end: str, known: str) -> None:
    conn.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, audited, "
                 "statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, source_table, "
                 "source_rowid, known_at, known_at_source, is_reported) VALUES (" + ",".join("?" * 20) + ")",
                 (SYM, ISIN, end[:7] + "-01", end, "Q1FY21", "consolidated", "A", "P&L", "pat", "ProfitLossForPeriod",
                  1.0e9, "inr", 1.0, "q.xml", "results_xbrl.db", "quarterly", "q.xml", known, "x", 1))


def test_window_keeps_price_rows_from_2019_and_drops_older_document_rows():
    """window_start 2023-10-01: a 2020 price and index row stay (price_start 2019-01-01), a 2020 fin row goes."""
    _activate()
    try:
        conn = sqlite3.connect(":memory:")
        schema.create(conn, ("fin_quarter_xbrl", "price_delivery", "index_price"))
        _quarter(conn, "2020-06-30", "2020-08-01T10:00:00")
        _price(conn, "2018-12-31")
        _price(conn, "2020-03-02")
        _index(conn, "2018-12-31")
        _index(conn, "2020-03-02")
        deleted = stores.apply_window(conn)
        assert deleted["price_delivery"] == 1 and deleted["index_price"] == 1 and deleted["fin_quarter_xbrl"] == 1
        assert conn.execute("SELECT MIN(date) FROM price_delivery").fetchone()[0] == "2020-03-02"
        assert conn.execute("SELECT MIN(date) FROM index_price").fetchone()[0] == "2020-03-02"
        assert conn.execute("SELECT COUNT(*) FROM fin_quarter_xbrl").fetchone()[0] == 0
    finally:
        profile.activate(None)


def test_a_later_price_start_drops_the_earlier_prices():
    """A profile may keep prices later than 2019: 2021-01-01 drops the 2020 rows and keeps the 2021 ones."""
    _activate(price_start="2021-01-01")
    try:
        conn = sqlite3.connect(":memory:")
        schema.create(conn, ("price_delivery", "index_price"))
        _price(conn, "2020-03-02")
        _price(conn, "2021-02-01")
        _index(conn, "2020-03-02")
        _index(conn, "2021-02-01")
        stores.apply_window(conn)
        assert conn.execute("SELECT DISTINCT date FROM price_delivery").fetchall() == [("2021-02-01",)]
        assert conn.execute("SELECT DISTINCT date FROM index_price").fetchall() == [("2021-02-01",)]
    finally:
        profile.activate(None)


def test_price_input_copy_never_overlaps_the_main_price_table():
    """compute_start 2019-06 < price_start 2020: the 2019 rows move to price_delivery_input, main keeps 2020+,
    so the ratios TEMP view (main UNION ALL input) never lists one day twice."""
    _activate(compute_start="2019-06-01", price_start="2020-01-01")
    try:
        conn = sqlite3.connect(":memory:")
        schema.create(conn, ("price_delivery",))
        for day in ("2019-05-01", "2019-07-01", "2020-06-01"):
            _price(conn, day)
        stores.apply_window(conn)
        main = [r[0] for r in conn.execute("SELECT date FROM price_delivery ORDER BY date")]
        copied = [r[0] for r in conn.execute("SELECT date FROM price_delivery_input ORDER BY date")]
        assert main == ["2020-06-01"] and copied == ["2019-07-01"]
    finally:
        profile.activate(None)


def test_valuation_day_before_any_known_quarter_keeps_close_with_null_ratios():
    """A 2020 day values the close and market cap; PE/PB/EV stay NULL because no filed input is known on it."""
    _activate()
    try:
        conn = sqlite3.connect(":memory:")
        schema.create(conn, ("price_delivery", "share_capital", "fin_quarter_xbrl", "fin_annual_line",
                             "dividend_event", "valuation_daily"))
        _price(conn, "2020-06-01", close=100.0)
        conn.execute("INSERT INTO share_capital VALUES (" + ",".join("?" * 19) + ")",
                     (SYM, ISIN, "2019-12-31", "standalone", None, None, 10.0, 10.0, 1.0, "shares", 1.0,
                      "2020-01-01T10:00:00", "x", "d", "t", "1", None, None, "derived_from_capital"))
        assert ratios._valuation(conn, SYM, ISIN) == 1
        close, market_cap, pe, pb, ev = conn.execute(
            "SELECT close, market_cap, pe, pb, ev_ebitda FROM valuation_daily").fetchone()
        assert close == pytest.approx(100.0) and market_cap == pytest.approx(1000.0)
        assert pe is None and pb is None and ev is None
        assert conn.execute("SELECT MIN(date) FROM valuation_daily").fetchone()[0] == "2020-06-01"
    finally:
        profile.activate(None)


def test_index_prices_start_at_price_start(monkeypatch):
    """build_index_prices keeps the 2020 days and can compute their 1m returns: its floor is price_start."""
    _activate()
    try:
        conn = sqlite3.connect(":memory:")
        schema.create(conn, ("price_delivery",))
        for day in ("2020-04-01", "2020-05-01", "2020-06-01"):
            _price(conn, day)
        index_days = [("2020-04-01", 10000.0), ("2020-05-01", 10100.0), ("2020-06-01", 10200.0)]

        def fake_read(db, source, sql, params=()):
            return index_days, ["date", "close"]

        monkeypatch.setattr(stores.prepare, "_read_sqlite", fake_read)
        assert stores.build_index_prices(conn)[SYM] == 3
        assert conn.execute("SELECT MIN(date) FROM index_price").fetchone()[0] == "2020-04-01"
        stock_1m, index_1m = conn.execute(
            "SELECT stock_return_1m, index_return_1m FROM index_price WHERE date='2020-06-01'").fetchone()
        assert stock_1m == pytest.approx(0.0)
        assert index_1m == pytest.approx(100.0 * (10200.0 / 10100.0 - 1.0))
    finally:
        profile.activate(None)


def test_build_prices_reads_the_raw_market_rows_from_price_start(monkeypatch):
    """The raw price read is bounded by price_start (2019-01-01 here), not by window_start."""
    _activate(price_start="2019-01-01")
    try:
        conn = sqlite3.connect(":memory:")
        calls = []

        def fake_duck(sql, params=()):
            calls.append((sql, params))
            return [], []

        monkeypatch.setattr(stores, "_duck", fake_duck)
        stores.build_prices(conn)
        assert len(calls) == 2
        assert all("date >= ?" in sql and params[-1] == "2019-01-01" for sql, params in calls)
    finally:
        profile.activate(None)


def test_trim_derived_keeps_valuation_from_price_start():
    """trim_derived keeps a 2020 valuation day (price_start) while ratio_panel is still cut at window_start."""
    _activate()
    try:
        conn = sqlite3.connect(":memory:")
        schema.create(conn, ("valuation_daily", "ratio_panel"))
        for day in ("2018-12-31", "2020-06-01"):
            conn.execute("INSERT INTO valuation_daily VALUES (" + ",".join("?" * 19) + ")",
                         (SYM, ISIN, day, "consolidated", 100.0, 10.0, 1000.0, None, None, None, None, None,
                          None, None, None, None, day, "x", "{}"))
        conn.commit()
        assert stores.trim_derived(conn)["valuation_daily"] == 1
        assert conn.execute("SELECT DISTINCT date FROM valuation_daily").fetchall() == [("2020-06-01",)]
    finally:
        profile.activate(None)
