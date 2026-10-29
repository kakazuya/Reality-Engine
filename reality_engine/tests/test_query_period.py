"""Period/entity wiring of the router and the planners (2026-10-29 gate run).

Every period form the router resolves is pinned here, plus the rows-level contract
the entity/period gate enforces: a SERIES row states the window it is about and
names the asked entity (the GOLD leak), a FACTS row carries the ISIN and only the
asked fiscal year, and EVIDENCE keeps the passages dated inside the asked month.

Fixture only: a temp data root under ``.tmp`` (the worker sandbox cannot open
``tempfile.mkdtemp``'s restrictive DACL with sqlite).  No live database.
"""
from __future__ import annotations

import shutil
import sqlite3
import unittest
from pathlib import Path

from reality_engine.query import route
from reality_engine.query.gate import period_match
from reality_engine.query.planners import load_planners
from reality_engine.query.router import period_bounds

AS_OF = "2026-10-19"
ISIN = "INE000A01001"


def _make(path: Path, ddl: list[str], rows: list[tuple[str, tuple]]) -> None:
    con = sqlite3.connect(path)
    for statement in ddl:
        con.execute(statement)
    for statement, params in rows:
        con.execute(statement, params)
    con.commit()
    con.close()


def build_root(root: Path) -> None:
    eq = root / "equity_intelligence.db"
    _make(eq, [
        "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, bse_code TEXT, "
        "company_name TEXT, industry TEXT, sector TEXT, market_cap_tier TEXT, "
        "is_active INTEGER, is_nifty500 INTEGER)",
        "CREATE TABLE daily_price_delivery(date TEXT, symbol TEXT, isin TEXT, open REAL, "
        "high REAL, low REAL, close REAL, prev_close REAL, change_pct REAL, "
        "total_volume INTEGER, turnover_lacs REAL, num_trades INTEGER, "
        "deliverable_volume INTEGER, delivery_pct REAL, rsi_14 REAL)",
        "CREATE TABLE mkt_commodity_daily(date TEXT, commodity TEXT, ticker TEXT, "
        "close REAL, adj_close REAL)",
    ], [
        ("INSERT INTO master_companies VALUES (?,?,?,?,?,?,?,?,?)",
         (ISIN, "AAA", "500001", "Alpha Ltd", "Capital Goods", "Industrials", "LARGE", 1, 1)),
    ])
    con = sqlite3.connect(eq)
    for i, day in enumerate(("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04")):
        con.execute("INSERT INTO daily_price_delivery(date,symbol,isin,open,high,low,close,"
                    "prev_close,change_pct,total_volume,delivery_pct,rsi_14) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (day, "AAA", ISIN, 100 + i, 101 + i, 99 + i, 100 + i, 99 + i,
                     1.0, 1000, 40.0, 55.0))
    # The commodity the question mentions; a SERIES answer for a stock ask must
    # never return this row instead of the asked company.
    con.execute("INSERT INTO mkt_commodity_daily VALUES (?,?,?,?,?)",
                ("2026-06-04", "gold", "gold", 70000.0, 70000.0))
    con.commit()
    con.close()

    ar = root / "ar_facts.db"
    _make(ar, [
        "CREATE TABLE ar_facts(doc_id INTEGER, piece INTEGER, isin TEXT, symbol TEXT, "
        "fiscal_year TEXT, filed_at TEXT, page INTEGER, category TEXT, item TEXT, "
        "value REAL, unit TEXT, period TEXT, basis TEXT, quote TEXT)",
    ], [
        ("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (11, 1, ISIN, "AAA", "FY26", "2026-06-20", 5, "operations",
          "Manufacturing capacity", 10.0, "MW", "FY26", "consolidated",
          "manufacturing capacity of 10 MW")),
        ("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (12, 1, ISIN, "AAA", "FY25", "2025-06-20", 9, "operations",
          "Manufacturing capacity", 4.0, "MW", "FY25", "consolidated",
          "manufacturing capacity of 4 MW")),
    ])


def case(**over):
    base = {"mid": "T9001", "source_bank": "test", "family": [2], "entity_level": "stock",
            "answer_kind": "number", "archetype": None,
            "question": "AAA close on 4 June 2026", "period": "4 June 2026",
            "entities": [{"isin": ISIN, "symbol": "AAA"}], "as_of": AS_OF,
            "template": None, "rubric": {"required_evidence": ["px_nse_adj"]},
            "case_status": "answerable_now"}
    base.update(over)
    return base


class TestPeriodForms(unittest.TestCase):
    """Every period form the gate checks is resolved to one window, once."""

    def bounds(self, period, question="", as_of=AS_OF):
        return period_bounds({"period": period, "question": question, "as_of": as_of})

    def test_hyphenated_fiscal_year(self):
        self.assertEqual(self.bounds("FY 2025-26"), ("2026-03-31", "2026-03-31",
                                                     "fiscal year end"))
        self.assertEqual(self.bounds("Q1 FY2026-27"), ("2026-06-30", "2026-06-30",
                                                       "quarter end"))

    def test_fiscal_year_span(self):
        self.assertEqual(self.bounds("FY26-FY28"),
                         ("2026-03-31", "2028-03-31", "fiscal year span"))

    def test_quarter_span(self):
        self.assertEqual(self.bounds("Q4FY26-Q1FY27"),
                         ("2026-03-31", "2026-06-30", "quarter span"))

    def test_month_span_sharing_one_year(self):
        self.assertEqual(self.bounds("Jun-Jul 2026"), ("2026-06-01", "2026-07-31",
                                                       "month span"))
        self.assertEqual(self.bounds("April-June 2026 (Q1 FY2026-27)"),
                         ("2026-06-30", "2026-06-30", "quarter end"))

    def test_since_is_an_open_window_to_as_of(self):
        self.assertEqual(self.bounds("since Jan 2026"), ("2026-01-01", AS_OF, "since"))

    def test_shared_month_day_range(self):
        self.assertEqual(self.bounds("10-18 Sep 2026 and 18-28 Sep 2026"),
                         ("2026-09-10", "2026-09-28", "named dates"))

    def test_last_two_quarters_is_a_six_month_lookback(self):
        start, end, basis = self.bounds("last 2 quarters")
        self.assertEqual(end, AS_OF)
        self.assertEqual(start, "2026-04-19")
        self.assertIn("lookback", basis)

    def test_route_publishes_the_gate_label(self):
        plan = route(case(question="AAA net NPA Q1 FY2026-27", period="Q1 FY2026-27"))
        self.assertEqual(plan["slots"]["period_label"], "Q1FY27")
        self.assertEqual(plan["slots"]["date_from"], "2026-06-30")


class PlannerFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = (Path(".tmp") / "test_query_period").resolve()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.tmp.mkdir(parents=True, exist_ok=True)
        build_root(cls.tmp)
        from reality_engine.query.ctx import Ctx
        cls.ctx = Ctx(root=cls.tmp)
        cls.planners = load_planners()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_plan(self, name, case_):
        plan = route(case_)
        return plan, self.planners[name](plan["slots"], plan["as_of"], self.ctx)


class TestSeriesPeriodAndEntity(PlannerFixture):
    def test_prices_the_asked_stock_when_the_question_names_gold(self):
        # The GOLD leak: "gold" in a question about a stock must not replace the
        # entity with the commodity series.
        _, hop = self.run_plan("SERIES", case(
            question="AAA gold-jewellery stocks moved in June 2026",
            period="June 2026"))
        self.assertTrue(hop["ok"])
        self.assertTrue(hop["rows"])
        self.assertFalse(any(row.get("ref") == "gold" for row in hop["rows"]))
        self.assertTrue(all(row.get("isin") == ISIN for row in hop["rows"]))

    def test_row_period_is_the_window_not_the_as_of_day(self):
        plan, hop = self.run_plan("SERIES", case())
        period = next(row["period"] for row in hop["rows"])
        self.assertEqual(period, "2026-06-04")
        self.assertIsNot(period_match(hop, plan["slots"], None), False)

    def test_rows_outside_the_asked_month_are_not_returned(self):
        plan, hop = self.run_plan("SERIES", case(period="Sep 2026",
                                                 question="AAA close in Sep 2026"))
        self.assertFalse(hop["ok"])
        self.assertEqual(hop["rows"], [])


class TestFactsPeriodAndEntity(PlannerFixture):
    def test_rows_name_the_entity_and_only_the_asked_fiscal_year(self):
        plan, hop = self.run_plan("FACTS", case(
            question="AAA manufacturing capacity FY26", period="FY26",
            rubric={"required_evidence": ["ar_facts"]}))
        self.assertTrue(hop["ok"])
        self.assertTrue(all(row.get("isin") == ISIN for row in hop["rows"]))
        self.assertNotIn("FY25", [row.get("period") for row in hop["rows"]])
        self.assertIsNot(period_match(hop, plan["slots"], None), False)

    def test_a_fact_from_another_year_is_not_used(self):
        _, hop = self.run_plan("FACTS", case(
            question="AAA manufacturing capacity FY27", period="FY27",
            rubric={"required_evidence": ["ar_facts"]}))
        self.assertFalse(hop["ok"])
        self.assertEqual(hop["rows"], [])


class TestEvidencePeriod(PlannerFixture):
    def test_only_passages_dated_inside_the_month(self):
        def fake_doc_find(symbol, terms, doc_type=None, date=None, as_of=None):
            return {"found": True, "checked": ["fake"], "passages": [
                {"store": "document_chunks", "doc_type": "ar", "date": "2026-06-02",
                 "doc_id": 1, "page": 3, "quote": "our products serve steel plants"},
                {"store": "document_chunks", "doc_type": "ar", "date": "2026-09-15",
                 "doc_id": 2, "page": 4, "quote": "products paragraph from September"}]}

        self.ctx.overrides["doc_find"] = fake_doc_find
        try:
            plan, hop = self.run_plan("EVIDENCE", case(
                question="What products does AAA make in June 2026?",
                period="June 2026", answer_kind="text+quote"))
        finally:
            self.ctx.overrides.pop("doc_find", None)
        self.assertTrue(hop["ok"])
        self.assertTrue(hop["rows"])
        self.assertTrue(all(str(row.get("known_at"))[:10].startswith("2026-06")
                            for row in hop["rows"]))
        self.assertTrue(all(row.get("isin") == ISIN for row in hop["rows"]))
        self.assertIsNot(period_match(hop, plan["slots"], None), False)


if __name__ == "__main__":
    unittest.main()
