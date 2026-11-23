"""Fixture tests for the pilot (b) store routes (commodity series, F&O OI, PIT membership).

The fixture is a temp data root under ``.tmp`` (the worker sandbox cannot open
``tempfile.mkdtemp``'s restrictive DACL with sqlite): the same table names and
columns ``build_b`` writes, one company that stayed in an index, one that left
and one that joined later.  No live database is touched.
"""
from __future__ import annotations

import shutil
import sqlite3
import unittest
from pathlib import Path

from reality_engine.query import load_planners, route
from reality_engine.query.ctx import Ctx, market_state_b_path

AS_OF = "2026-10-19"
ISIN = "INE000A01001"
LEFT = "INE000A01002"
JOINED = "INE000A01003"

B_DDL = [
    "CREATE TABLE series_meta(series_code TEXT PRIMARY KEY, display_name TEXT NOT NULL, "
    "kind TEXT NOT NULL, source TEXT NOT NULL, unit TEXT NOT NULL, cadence TEXT NOT NULL, "
    "fetched_to TEXT, pit_note TEXT)",
    "CREATE TABLE series_observation(series_code TEXT NOT NULL, dim_id TEXT NOT NULL, "
    "kind TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT, value REAL NOT NULL, "
    "unit TEXT NOT NULL, departure_pct REAL, source TEXT NOT NULL, known_at TEXT NOT NULL, "
    "pit_conf REAL NOT NULL DEFAULT 1.0, PRIMARY KEY (series_code, period_start)) WITHOUT ROWID",
    "CREATE TABLE index_list(index_code TEXT PRIMARY KEY, display_name TEXT NOT NULL, "
    "broad_or_sector TEXT NOT NULL, size INTEGER, history_from TEXT, coverage TEXT, "
    "snapshot_date TEXT, members_at_snapshot INTEGER, changes_parsed INTEGER, pit_conf REAL)",
    "CREATE TABLE company_membership_pit(isin TEXT NOT NULL, index_code TEXT NOT NULL, "
    "added_on TEXT NOT NULL, removed_on TEXT, source TEXT NOT NULL, "
    "pit_conf REAL NOT NULL DEFAULT 1.0, PRIMARY KEY (isin, index_code, added_on)) WITHOUT ROWID",
    "CREATE TABLE fno_oi_daily(date TEXT NOT NULL, underlying TEXT NOT NULL, "
    "expiry TEXT NOT NULL, strike REAL, option_type TEXT, oi REAL, oi_change REAL, "
    "volume REAL, settle REAL, isin TEXT, "
    "PRIMARY KEY (date, underlying, expiry, strike, option_type)) WITHOUT ROWID",
    "CREATE TABLE mkt_nse_full_daily(date TEXT NOT NULL, symbol TEXT NOT NULL, "
    "series TEXT NOT NULL, prev_close REAL, open REAL, high REAL, low REAL, last REAL, "
    "close REAL, avg_price REAL, volume INTEGER, turnover_lacs REAL, num_trades INTEGER, "
    "deliverable_qty INTEGER, delivery_pct REAL, PRIMARY KEY (date, symbol, series))",
]

EQ_DDL = [
    "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, bse_code TEXT, "
    "company_name TEXT, industry TEXT, sector TEXT, market_cap_tier TEXT, "
    "is_active INTEGER, is_nifty500 INTEGER)",
    "CREATE TABLE daily_price_delivery(date TEXT, symbol TEXT, isin TEXT, open REAL, "
    "high REAL, low REAL, close REAL, prev_close REAL, change_pct REAL, "
    "total_volume INTEGER, turnover_lacs REAL, num_trades INTEGER, "
    "deliverable_volume INTEGER, delivery_pct REAL, rsi_14 REAL)",
    "CREATE TABLE index_membership(index_name TEXT, symbol TEXT, isin TEXT)",
]


def _make(path: Path, ddl: list[str], rows: list[tuple[str, tuple]]) -> None:
    con = sqlite3.connect(path)
    for statement in ddl:
        con.execute(statement)
    for statement, params in rows:
        con.execute(statement, params)
    con.commit()
    con.close()


def build_root(root: Path) -> None:
    _make(root / "equity_intelligence.db", EQ_DDL, [
        ("INSERT INTO master_companies VALUES (?,?,?,?,?,?,?,?,?)",
         (ISIN, "AAA", "500001", "Alpha Ltd", "Capital Goods", "Industrials", "LARGE", 1, 1)),
        ("INSERT INTO master_companies VALUES (?,?,?,?,?,?,?,?,?)",
         (LEFT, "BBB", "500002", "Beta Ltd", "Capital Goods", "Industrials", "LARGE", 1, 1)),
        ("INSERT INTO master_companies VALUES (?,?,?,?,?,?,?,?,?)",
         (JOINED, "CCC", "500003", "Gamma Ltd", "Capital Goods", "Industrials", "LARGE", 1, 1)),
    ])
    con = sqlite3.connect(root / "equity_intelligence.db")
    for day, close in (("2026-06-01", 100.0), ("2026-06-02", 101.0), ("2026-06-05", 102.0)):
        for isin, symbol in ((ISIN, "AAA"), (LEFT, "BBB"), (JOINED, "CCC")):
            con.execute("INSERT INTO daily_price_delivery(date,symbol,isin,close,high,"
                        "delivery_pct,turnover_lacs) VALUES (?,?,?,?,?,?,?)",
                        (day, symbol, isin, close, close + 1.0, 40.0, 10.0))
    con.commit()
    con.close()

    pilot = root / "pilot" / "pilot60"
    pilot.mkdir(parents=True, exist_ok=True)
    _make(pilot / "market_state_b.db", B_DDL, [
        ("INSERT INTO series_meta VALUES (?,?,?,?,?,?,?,?)",
         ("wb_copper", "World Bank Copper", "commodity", "worldbank_pink_sheet", "($/mt)",
          "monthly", "2026-09-30", None)),
        ("INSERT INTO series_observation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
         ("wb_copper", "wb_copper", "commodity", "2026-01-31", None, 9000.0, "($/mt)", None,
          "worldbank_pink_sheet", "2026-10-02T23:59:59", 0.8)),
        ("INSERT INTO series_observation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
         ("wb_copper", "wb_copper", "commodity", "2026-03-31", None, 9900.0, "($/mt)", None,
          "worldbank_pink_sheet", "2026-10-02T23:59:59", 0.8)),
        ("INSERT INTO index_list VALUES (?,?,?,?,?,?,?,?,?,?)",
         ("nifty200", "NIFTY 200", "broad", 200, "2019-01-01", "snapshot", "2026-09-30",
          200, 10, 1.0)),
        ("INSERT INTO index_list VALUES (?,?,?,?,?,?,?,?,?,?)",
         ("nifty200alpha30", "NIFTY 200 ALPHA 30", "thematic", 30, "2019-01-01",
          "changes_only", None, None, 4, 0.6)),
        ("INSERT INTO company_membership_pit VALUES (?,?,?,?,?,?)",
         (ISIN, "nifty200", "2020-01-01", None, "snapshot_backcast", 0.9)),
        ("INSERT INTO company_membership_pit VALUES (?,?,?,?,?,?)",
         (LEFT, "nifty200", "2020-01-01", "2026-05-01", "nse_notice", 1.0)),
        ("INSERT INTO company_membership_pit VALUES (?,?,?,?,?,?)",
         (JOINED, "nifty200", "2026-07-01", None, "nse_notice", 1.0)),
        # 2026-06-26 session: CE 300, PE 500, FUT 200 -> PCR 1.667, front expiry 2026-07-30
        ("INSERT INTO fno_oi_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-26", "AAA", "2026-07-30", 100.0, "CE", 300.0, 30.0, 10.0, 4.0, ISIN)),
        ("INSERT INTO fno_oi_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-26", "AAA", "2026-07-30", 100.0, "PE", 500.0, -40.0, 8.0, 3.0, ISIN)),
        ("INSERT INTO fno_oi_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-26", "AAA", "2026-07-30", 0.0, "FUT", 200.0, 5.0, 2.0, 101.0, ISIN)),
        ("INSERT INTO fno_oi_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-26", "AAA", "2026-08-27", 100.0, "CE", 120.0, 10.0, 3.0, 5.0, ISIN)),
        # a session AFTER the PIT test's as_of: it must never be read
        ("INSERT INTO fno_oi_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-26", "AAA", "2026-08-27", 0.0, "FUT", 999.0, 0.0, 0.0, 99.0, ISIN)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-01", "AAA", "EQ", 99.0, 100.0, 101.0, 99.0, None, 100.0, 100.0, 1000,
          10.0, 5, 400, 40.0)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-02", "AAA", "EQ", 100.0, 100.0, 101.0, 99.0, None, 101.0, 100.5, 1000,
          10.0, 5, 500, 50.0)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-05", "AAA", "EQ", 101.0, 101.0, 103.0, 100.0, None, 102.0, 101.5, 1200,
          12.0, 6, 660, 55.0)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-01", "BBB", "EQ", 199.0, 200.0, 201.0, 199.0, None, 200.0, 200.0, 900,
          18.0, 4, 450, 50.0)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-06-05", "BBB", "EQ", 200.0, 200.0, 201.0, 197.0, None, 198.0, 199.0, 900,
          18.0, 4, 405, 45.0)),
        # A May window the live daily_price_delivery does not hold (it starts 2026-06-01):
        # the delivery screen must come from this bhavcopy instead.
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-04-28", "AAA", "EQ", 99.0, 100.0, 101.0, 99.0, None, 100.0, 100.0, 1000,
          10.0, 5, 400, 40.0)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-05-06", "AAA", "EQ", 100.0, 100.0, 101.0, 99.0, None, 101.0, 100.5, 1000,
          10.0, 5, 550, 55.0)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-04-28", "BBB", "EQ", 199.0, 200.0, 201.0, 199.0, None, 200.0, 200.0, 900,
          18.0, 4, 450, 50.0)),
        ("INSERT INTO mkt_nse_full_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ("2026-05-06", "BBB", "EQ", 200.0, 200.0, 201.0, 197.0, None, 198.0, 199.0, 900,
          18.0, 4, 405, 45.0)),
    ])


def case(**over):
    base = {
        "mid": "T9001", "source_bank": "test", "family": [2], "entity_level": "stock",
        "answer_kind": "number", "archetype": None, "question": "AAA close in June 2026",
        "entities": [{"isin": ISIN, "symbol": "AAA"}], "period": "June 2026",
        "as_of": AS_OF, "template": None,
        "rubric": {"required_evidence": ["px_nse_adj"]},
        "case_status": "answerable_now",
    }
    base.update(over)
    return base


class PilotBFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = (Path(".tmp") / "test_query_pilot_b").resolve()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.tmp.mkdir(parents=True, exist_ok=True)
        build_root(cls.tmp)
        cls.ctx = Ctx(root=cls.tmp)
        cls.planners = load_planners()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_plan(self, name, case_):
        plan = route(case_)
        hop = self.planners[name](plan["slots"], plan["as_of"], self.ctx)
        return plan, hop


class TestPilotBContext(PilotBFixtureTest):
    def test_alias_resolves_under_the_data_root_and_is_read_only(self):
        assert market_state_b_path(self.tmp) == \
            self.tmp / "pilot" / "pilot60" / "market_state_b.db"
        con = self.ctx.sqlite("market_state_b")
        assert con.execute("SELECT COUNT(*) FROM series_meta").fetchone()[0] == 1

    def test_alias_refuses_a_missing_store(self):
        from reality_engine.query.ctx import QueryUnavailable
        empty = (Path(".tmp") / "test_query_pilot_b_empty").resolve()
        empty.mkdir(parents=True, exist_ok=True)
        try:
            try:
                Ctx(root=empty).sqlite("market_state_b")
            except QueryUnavailable:
                return
            raise AssertionError("a missing pilot (b) store must raise QueryUnavailable")
        finally:
            shutil.rmtree(empty, ignore_errors=True)


class TestCommoditySeries(PilotBFixtureTest):
    def test_commodity_ask_reads_series_observation(self):
        _, hop = self.run_plan("SERIES", case(
            question="copper price in 2026: how far did it move",
            entities=[], period="Jan 2026-Mar 2026", as_of="2026-10-19"))
        assert hop["ok"] is True, hop
        assert hop["rows"], hop
        row = hop["rows"][0]
        assert "wb_copper" in row["ref"]
        assert row["period"].startswith("2026-01-31")
        assert row["known_at"] == "2026-10-19"
        assert "return" in hop["detail"] and "months" in hop["detail"]
        assert any("market_state_b.series_observation" in note for note in hop["degraded"])

    def test_series_rows_known_after_as_of_are_never_read(self):
        # The only rows are known_at 2026-10-02; a 2026-09-01 ask cannot see them.
        plan, hop = self.run_plan("SERIES", case(
            question="copper price in 2026: how far did it move",
            entities=[], period="Jan 2026-Mar 2026", as_of="2026-09-01"))
        assert plan["as_of"] == "2026-09-01"
        assert hop["ok"] is False
        assert hop["rows"] == []
        assert not any("2026-01-31" in str(row.get("period")) for row in hop["rows"])


class TestFnoOpenInterest(PilotBFixtureTest):
    def test_open_interest_ask_reads_fno_oi_daily(self):
        _, hop = self.run_plan("SERIES", case(
            question="AAA open interest and put-call ratio going into expiry",
            period="June 2026", as_of="2026-06-30"))
        assert hop["ok"] is True, hop
        row = hop["rows"][0]
        assert row["symbol"] == "AAA"
        assert "open interest" in row["item"] and "put-call ratio" in row["item"]
        assert row["period"] == "2026-06-26"
        assert abs(row["stats"]["pcr"] - 500 / 420) < 1e-9
        assert hop["pit"] == "fno_oi_daily.date <= 2026-06-30"

    def test_no_session_known_by_as_of_means_no_oi_rows(self):
        _, hop = self.run_plan("SERIES", case(
            question="AAA open interest and put-call ratio going into expiry",
            period="June 2026", as_of="2026-06-25"))
        assert not any("open interest" in str(row.get("item") or "")
                       for row in hop["rows"])
        assert not any(row.get("period") == "2026-06-26" for row in hop["rows"])


class TestMembershipUniverse(PilotBFixtureTest):
    def test_index_screen_uses_the_pit_intervals(self):
        _, hop = self.run_plan("SCREEN", case(
            question="For the Nifty 200 constituents, which companies rose most in June 2026?",
            entity_level="index", entities=[], period="June 2026", as_of="2026-06-30"))
        assert hop["ok"] is True, hop
        isins = {row.get("ref", "").split(":")[-1] for row in hop["rows"]}
        assert ISIN in isins
        assert LEFT not in isins    # removed 2026-05-01, before the as_of
        assert JOINED not in isins  # added 2026-07-01, after the as_of
        assert any("company_membership_pit" in note for note in hop["degraded"])

    def test_changes_only_index_is_not_a_universe(self):
        _, hop = self.run_plan("SCREEN", case(
            question="For the Nifty 200 Alpha 30 constituents, which companies rose most "
                     "in June 2026?", entity_level="index", entities=[], period="June 2026"))
        assert not any("company_membership_pit" in note for note in hop["degraded"])

    def test_new_high_ask_reports_the_level_and_its_date(self):
        _, hop = self.run_plan("SCREEN", case(
            question="For the Nifty 200 constituents, which companies made a new YTD high "
                     "in 2026, with the value and date?",
            entity_level="index", entities=[], period="June 2026", as_of="2026-06-30"))
        assert hop["ok"] is True, hop
        assert hop["rows"][0]["item"] == "high"
        assert hop["rows"][0]["period"] == "2026-06-05"
        assert hop["rows"][0]["value"] == 103.0  # AAA's June high
        assert "high" in hop["detail"]


class TestBhavcopyScreen(PilotBFixtureTest):
    def test_delivery_screen_falls_back_to_the_full_nse_bhavcopy(self):
        _, hop = self.run_plan("SCREEN", case(
            question="Which large caps saw delivery fall most in the week after 3 May 2026?",
            entity_level="market-wide", entities=[], period="3 May 2026"))
        assert hop["ok"] is True, hop
        assert "delivery % change" in hop["detail"]
        assert hop["rows"] and hop["rows"][0]["item"] == "delivery % change"
        assert any("full NSE bhavcopy" in note for note in hop["degraded"])
        # BBB 50% -> 45% is the fall; AAA 40% -> 55% is the rise.
        assert hop["rows"][0]["symbol"] == "BBB"
