"""Fixture tests for reality_engine/pilot3/answer_check.py (T-049 F, guide O5).

A tiny pilot3.db and a tiny sandbox (one company, eight questions, one answers row each) are built under
``.tmp/``: one question for every result class, plus the three shapes T-049 F added -- a growth answer whose
oracle cites two revenues while the lookup returns the growth %, a share answer over two cited amounts, and a
"4 sessions after results" question whose results date comes from pilot3_docs.  No production database, network
or model.

    python -m pytest reality_engine/tests/test_pilot3_answer_check.py -q
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from reality_engine.pilot3 import answer_check as ac
from reality_engine.pilot3 import kpi, schema, transcripts

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / ".tmp" / "answer_check"
DB = FIXTURE / "pilot3.db"
SANDBOX = FIXTURE / "sandbox"
QUESTIONS = [
    ("KEC001", "lookup", "What was KEC's consolidated revenue from operations for FY26?"),
    ("KEC002", "lookup", "What was KEC's consolidated EBITDA and EBITDA margin for FY26?"),
    ("KEC003", "lookup", "What was KEC's capital expenditure for FY26?"),
    ("KEC004", "lookup", "What is KEC's registered office address?"),
    ("KEC005", "lookup", "What was KEC's net worth for FY26?"),
    ("KEC006", "lookup", "By what percentage did KEC's revenue from operations grow in FY26 over FY25?"),
    ("KEC007", "lookup", "What was the international share of KEC's order book at the end of FY26?"),
    ("KEC008", "lookup", "How did KEC's share price move over the 4 trading sessions after its Q1 FY27 results?"),
]
ANSWERS = {
    "KEC001": [{"measure": "revenue from operations", "value": 23506.0, "unit": "inr_cr", "period": "FY26",
                "table": "ar_facts", "rowid": 1, "known_at": "2026-07-29"}],
    "KEC002": [{"measure": "EBITDA", "value": 1659.0, "unit": "inr_cr", "period": "FY26", "table": "ar_facts"},
               {"measure": "EBITDA margin", "value": 7.1, "unit": "pct", "period": "FY26", "table": "ar_facts"}],
    "KEC003": [{"measure": "capital expenditure", "value": 999.0, "unit": "inr_cr", "period": "FY26",
                "table": "ar_facts"}],
    "KEC004": [],
    "KEC005": [{"measure": "net worth", "value": 4600.0, "unit": "inr_cr", "period": "FY26", "table": "ar_facts"}],
    # the loop cites the two revenues; pilot3 holds the growth ratio
    "KEC006": [{"measure": "revenue from operations", "value": 23506.0, "unit": "inr_cr", "period": "FY26",
                "table": "ar_facts"},
               {"measure": "revenue from operations", "value": 21847.0, "unit": "inr_cr", "period": "FY25",
                "table": "ar_facts"}],
    # the loop cites the two order books; pilot3 holds the share
    "KEC007": [{"measure": "order book", "value": 36267.0, "unit": "inr_cr", "period": "FY26",
                "table": "deck_figures"},
               {"measure": "international order book", "value": 15000.0, "unit": "inr_cr", "period": "FY26",
                "table": "deck_figures"}],
    # the results day is the Q1 FY27 results filing (2026-08-07), then four trading sessions
    "KEC008": [{"measure": "closing price, results day", "value": 1059.6, "unit": "inr", "period": "2026-08-07",
                "table": "px_nse"},
               {"measure": "closing price, fourth session after results", "value": 1046.25, "unit": "inr",
                "period": "2026-08-13", "table": "px_nse"}],
}
FIN_COLUMNS = 23


def build_fixture() -> None:
    """The pilot3 db: revenue, EBITDA and capex, the growth ratio, the international share, the results doc, prices."""
    FIXTURE.mkdir(parents=True, exist_ok=True)
    for path in (DB, SANDBOX / "kec_loop" / "kec.db"):
        for suffix in ("", "-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
    conn = sqlite3.connect(DB)
    schema.create(conn, list(schema.TABLES))
    conn.executescript(kpi.SCHEMA + transcripts.SCHEMA)
    conn.execute(schema.FTS)
    conn.execute("INSERT INTO company VALUES ('KEC','INE389H01022',NULL,NULL,'t','532714','KEC International Ltd')")
    row = ("KEC", "INE389H01022", "FY26", "2026-03-31", "consolidated", "PL", "{item}", "{item}",
           "{value}", "inr_crore", 1e7, None, None, None, "ar_facts.db", "ar_facts", "1", "2026-07-29T10:00:00",
           "docs.known_at", 1, 0, "reported", "FY")
    assert len(row) == FIN_COLUMNS, len(row)
    for item, value, year in (("revenue_from_operations", 23506.0, "FY26"), ("ebitda", 1659.0, "FY26"),
                              ("capex", 100.0, "FY26"), ("revenue_from_operations", 21847.0, "FY25")):
        conn.execute(f"INSERT INTO fin_annual_line VALUES ({','.join('?' * FIN_COLUMNS)})",
                     tuple(value if v == "{value}" else year if v == "FY26" else
                           item if v == "{item}" else v for v in row))
    # ratio_panel: the growth the reply returns (100 * (23506 / 21847 - 1) = 7.59%)
    conn.execute("INSERT INTO ratio_panel VALUES ('KEC','INE389H01022','FY26','FY','2025-04-01','2026-03-31',"
                 "'consolidated','revenue_growth_yoy_pct',7.5931,'pct',1.0,'F_GROWTH',NULL,'2026-07-29T10:00:00',"
                 "'ratio_panel',1)")
    # kpi_series: the international share the reply returns (15000 / 36267 = 41.36%)
    conn.execute("INSERT INTO kpi_series (symbol, metric, dimension, value, unit, period_type, fiscal_period, basis,"
                 " doc_key, page, quote, known_at, known_at_source, extractor_rule, confidence, conf_rank) VALUES "
                 "('KEC','order_book_international_share','total',41.36,'pct','FY','FY26','consolidated','deck',3,"
                 "'International share of order book 41%','2026-08-10T18:00:00','docs.known_at','table_v1',"
                 "'table_row',4)")
    # the Q1 FY27 results filing whose known_at dates the sessions in KEC008, and the prices around it
    conn.execute("INSERT INTO doc VALUES ('results_q1fy27','KEC','INE389H01022','results','results','Outcome of "
                 "Board Meeting','2026-08-07','2026-08-07T14:39:01','9',NULL,'sandbox','kec/results.pdf')")
    for day, close, prev_close in (("2026-08-07", 1059.6, 1027.0), ("2026-08-10", 1054.05, 1059.6),
                                   ("2026-08-11", 1049.1, 1054.05), ("2026-08-12", 1078.5, 1049.1),
                                   ("2026-08-13", 1046.25, 1078.5)):
        conn.execute("INSERT INTO price_delivery (symbol, isin, exchange, date, close, prev_close, known_at) "
                     "VALUES ('KEC','INE389H01022','NSE',?,?,?,'2026-08-14T00:00:00')", (day, close, prev_close))
    conn.commit()
    conn.close()


def build_sandbox() -> None:
    """Five questions and one newest answers row each, as the gap loop writes them."""
    loop_dir = SANDBOX / "kec_loop"
    (loop_dir / "questions").mkdir(parents=True, exist_ok=True)
    (loop_dir / "questions" / "KEC_QUESTIONS.jsonl").write_text(
        "\n".join(json.dumps({"id": qid, "kind": kind, "question": text, "as_of": "2026-10-19"})
                  for qid, kind, text in QUESTIONS), encoding="utf-8")
    conn = sqlite3.connect(loop_dir / "kec.db")
    conn.execute("CREATE TABLE answers (round INTEGER, qid TEXT, status TEXT, answer_json TEXT, "
                 "gap_type TEXT, tier INTEGER)")
    for qid in ANSWERS:
        payload = {"qid": qid, "status": "answered", "answer": "KEC answered it.",
                   "numbers": ANSWERS[qid], "sources": [], "gap_type": None, "tier": 1}
        conn.execute("INSERT INTO answers VALUES (1,?,?,?,NULL,1)",
                     (qid, "answered", json.dumps(payload)))
    conn.commit()
    conn.close()


class AnswerCheckFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_fixture()
        build_sandbox()
        cls.result = ac.evaluate(DB, SANDBOX, symbols=("KEC",))
        cls.records = {record["qid"]: record for record in cls.result["records"]}

    def test_one_row_per_question_and_every_class(self):
        self.assertEqual(len(self.records), 8)
        self.assertEqual({qid: record["class"] for qid, record in self.records.items()},
                         {"KEC001": "match", "KEC002": "partial", "KEC003": "mismatch",
                          "KEC004": "no_tool", "KEC005": "empty", "KEC006": "match", "KEC007": "match",
                          "KEC008": "match"})
        self.assertEqual(self.result["summary"]["by_company"]["KEC"]["match"], 4)
        self.assertEqual(self.result["summary"]["passed_oracle"], 8)

    def test_match_carries_arguments_and_provenance(self):
        record = self.records["KEC001"]
        self.assertEqual(record["tool"], "pilot3_fin")
        self.assertIn("revenue_from_operations", record["arguments"])
        self.assertIn("fin_annual_line", record["provenance"])
        self.assertIn("known_at=2026-07-29", record["provenance"])
        self.assertIn("23506", record["returned_numbers"])

    def test_partial_names_the_missing_number(self):
        record = self.records["KEC002"]
        self.assertEqual(record["class"], "partial")
        self.assertIn("EBITDA margin", record["oracle_numbers"])
        self.assertEqual(record["tool"], "pilot3_fin")

    def test_growth_is_graded_on_the_derived_value(self):
        """The oracle cites two revenues, the lookup returns the growth %: the answer, not the inputs, is graded."""
        record = self.records["KEC006"]
        self.assertEqual(record["tool"], "pilot3_ratio")
        self.assertIn("revenue_growth_yoy_pct", record["arguments"])
        self.assertEqual(record["compared_on"], "derived")
        self.assertEqual(record["class"], "match")
        self.assertEqual(record["cited_class"], "mismatch")   # no cited revenue occurs in the ratio reply
        self.assertIn("growth of revenue", record["derived_numbers"])

    def test_share_is_graded_on_the_derived_value(self):
        """The oracle cites the two order books, the lookup returns the share: 15000 / 36267 = 41.36%."""
        record = self.records["KEC007"]
        self.assertEqual(record["tool"], "pilot3_kpi")
        self.assertEqual(record["compared_on"], "derived")
        self.assertEqual(record["class"], "match")
        self.assertEqual(record["cited_class"], "mismatch")
        self.assertIn("international order book", record["derived_numbers"])

    def test_results_date_comes_from_pilot3_docs(self):
        """No date in the question: the results filing's known_at anchors the four sessions."""
        record = self.records["KEC008"]
        self.assertEqual(record["tool"], "pilot3_sql")
        self.assertIn("date >= (SELECT MAX(date)", record["arguments"])
        self.assertIn("2026-08-07", record["arguments"])
        self.assertEqual(record["class"], "match")

    def test_reports_are_written(self):
        out = ac.write_xlsx(FIXTURE / "ANSWERABILITY.xlsx", self.result["records"], self.result["summary"])
        page = ac.write_html(FIXTURE / "ANSWERABILITY.html", self.result["records"], self.result["summary"])
        self.assertTrue(out.is_file() and out.stat().st_size > 5000)
        self.assertIn("match", page.read_text(encoding="utf-8"))
        import openpyxl

        book = openpyxl.load_workbook(out, read_only=True)
        self.assertEqual(book.sheetnames, ["answers", "summary"])
        rows = list(book["answers"].iter_rows(values_only=True))
        self.assertEqual(rows[0][0], "qid")
        self.assertIn("compared on", rows[0])
        self.assertIn("cited class", rows[0])
        self.assertEqual(len(rows), 9)


class NumberAndPeriodTests(unittest.TestCase):
    def test_units_and_scales(self):
        # 23,506 crore is 235.05 billion rupees: a crore row, a rupee row and a store scale all match.
        self.assertTrue(ac.same_number(23505.54, "inr_cr", 23506.0, "inr_crore", 1e7))
        self.assertTrue(ac.same_number(23505.54, "inr_cr", 235055400000.0, "inr", 1.0))
        self.assertFalse(ac.same_number(23505.54, "inr_cr", 23506.0, "inr_crore", 1e6))
        self.assertTrue(ac.same_number(7.1, "pct", 7.1, "pct", 1.0))
        self.assertFalse(ac.same_number(7.1, "pct", 7.1, "inr_cr", 1.0))
        self.assertTrue(ac.number_in_text(23505.54, "inr_cr", "Revenue grew to ₹23,506 crore in FY26"))

    def test_periods(self):
        self.assertTrue(ac.periods_match("FY26", "FY26"))
        self.assertFalse(ac.periods_match("FY26", "FY25"))
        self.assertTrue(ac.periods_match("as on 31 March 2026", "FY26"))  # a March date closes the year
        self.assertTrue(ac.periods_match("Q1 FY27", "Q1FY27"))
        self.assertFalse(ac.periods_match("Q1FY27", "FY27"))   # stored values stay strict
        self.assertTrue(ac.periods_within("Q1FY27", "FY27"))   # a quoted sentence may name the quarter
        self.assertFalse(ac.periods_within("Q1FY26", "FY27"))
        self.assertEqual(ac.periods_in("from FY25 to FY26"), [("FY", "FY25"), ("FY", "FY26")])


class PlanRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_fixture()
        cls.vocab = ac.vocabulary(DB)

    def _plan(self, question, numbers=(), symbol="KEC", kind="lookup"):
        return ac.plan({"question": question, "symbol": symbol, "kind": kind}, list(numbers), self.vocab)

    def test_one_measure_one_period(self):
        mapping = self._plan("What was KEC's consolidated revenue from operations for FY26?")
        self.assertEqual((mapping["tool"], mapping["args"]["measure"], mapping["args"]["period"]),
                         ("pilot3_fin", "revenue_from_operations", "FY26"))
        self.assertEqual(mapping["args"]["basis"], "consolidated")

    def test_two_periods_ask_for_all_periods(self):
        mapping = self._plan("By how much did KEC's revenue change from FY25 to FY26?")
        self.assertIsNone(mapping["args"]["period"])

    def test_holding_uses_the_quarter_asked(self):
        mapping = self._plan("What was KEC's promoter holding at the end of June 2026?")
        self.assertEqual(mapping["tool"], "pilot3_holding")
        self.assertEqual(mapping["args"]["quarter_end"], "2026-06-30")
        self.assertEqual(mapping["args"]["as_of"], "2026-10-19")  # the filing cut-off stays the question's

    def test_price_question_is_a_sql_query(self):
        mapping = self._plan("What was KEC's closing price on 16 October 2026?")
        self.assertEqual(mapping["tool"], "pilot3_sql")
        self.assertIn("price_delivery", mapping["args"]["query"])
        self.assertIn("2026-10-16", mapping["args"]["query"])

    def test_unmapped_question_is_no_tool(self):
        self.assertIsNone(self._plan("What is KEC's registered office address?"))

    def test_ratio_question_with_cited_inputs_asks_for_the_inputs(self):
        numbers = [{"measure": "finance costs Q1 FY26", "value": 1.5e9, "unit": "inr", "period": "Q1FY26"}]
        mapping = self._plan("What was KEC's interest coverage in FY26?", numbers)
        self.assertEqual((mapping["tool"], mapping["args"]["measure"]), ("pilot3_fin", "finance_cost"))

    def test_topic_the_tagger_emits_is_asked_as_a_topic(self):
        mapping = self._plan("What did KEC's management say about margins in its latest earnings call?",
                             kind="guidance")
        self.assertEqual(mapping["tool"], "pilot3_statements")
        self.assertEqual(mapping["args"].get("topic"), "margin")
        self.assertNotIn("terms", mapping["args"])

    def test_topic_the_tagger_never_emits_is_asked_as_terms(self):
        """pilot3_statements(topic="price") returns nothing: no tag contains "price", so the word goes in terms."""
        mapping = self._plan("What did KEC's management say about price increases in its latest earnings call?",
                             kind="guidance")
        self.assertEqual(mapping["tool"], "pilot3_statements")
        self.assertEqual(mapping["args"].get("terms"), "price")
        self.assertNotIn("topic", mapping["args"])

    def test_sessions_after_results_use_the_resolved_results_date(self):
        mapping = ac.plan({"question": "How did KEC's share price move over the 4 trading sessions after its "
                                      "Q1 FY27 results?", "symbol": "KEC", "kind": "lookup"},
                          [], self.vocab, results_day="2026-08-07")
        self.assertEqual(mapping["tool"], "pilot3_sql")
        self.assertIn("date >= (SELECT MAX(date)", mapping["args"]["query"])
        self.assertIn("2026-08-07", mapping["args"]["query"])

    def test_price_on_a_market_holiday_reads_the_last_session(self):
        """31 March 2025 and 31 March 2026 were not trading days: the query resolves each to the last session."""
        mapping = self._plan("What was KEC's closing price on 31 March 2025 and 31 March 2026?")
        query = mapping["args"]["query"]
        self.assertEqual(mapping["tool"], "pilot3_sql")
        self.assertIn("date IN (", query)
        self.assertIn("2025-03-31", query) and self.assertIn("2026-03-31", query)
        self.assertIn("as_traded_on", query)

    def test_search_args_carry_the_period_the_window_and_the_document_type(self):
        mapping = self._plan("List the new orders KEC announced between July and October 2026.")
        self.assertEqual(mapping["tool"], "pilot3_search")
        self.assertEqual((mapping["args"]["date_from"], mapping["args"]["date_to"]), ("2026-07-01", "2026-10-31"))
        statements = self._plan("What did KEC say about margins in its latest earnings call?", kind="guidance")
        self.assertEqual(statements["args"]["topic"], "margin")
        self.assertIn("rank_terms", statements["args"])

    def test_keywords_drop_the_company_and_keep_the_period(self):
        words = ac._keywords("What did Bajaj Finance say about its two-wheeler stress in Q1 FY27?", "BAJFINANCE")
        self.assertNotIn("bajaj", words) and self.assertNotIn("finance", words)
        self.assertIn("two-wheeler", words) and self.assertIn("q1fy27", words)
        self.assertEqual(ac.date_window("between July and October 2026"), ("2026-07-01", "2026-10-31"))
        self.assertEqual(ac.date_window("in July 2026"), ("2026-07-01", "2026-07-31"))


class DerivedAnswerTests(unittest.TestCase):
    def _verdict(self, question, numbers, rows):
        operands = [o for o in (ac.operand(n) for n in numbers) if o]
        op, _why = ac.derived_op(question, numbers)
        return ac.derived_values(op, operands, question)

    def test_growth_is_computed_from_two_cited_revenues(self):
        values = self._verdict("By what percentage did revenue grow in FY26 over FY25?",
                               [{"measure": "revenue", "value": 23506.0, "unit": "inr_cr", "period": "FY26"},
                                {"measure": "revenue", "value": 21847.0, "unit": "inr_cr", "period": "FY25"}], [])
        self.assertEqual(len(values), 1)
        self.assertAlmostEqual(values[0]["value"], 100 * (23506 / 21847 - 1), places=6)
        self.assertEqual((values[0]["family"], values[0]["period"]), ("pct", "FY26"))

    def test_share_is_computed_from_a_part_and_a_whole(self):
        question = "What was the international share of KEC's order book at the end of FY26?"
        values = self._verdict(question,
                               [{"measure": "order book", "value": 36267.0, "unit": "inr_cr", "period": "FY26"},
                                {"measure": "international order book", "value": 15000.0, "unit": "inr_cr",
                                 "period": "FY26"}], [])
        self.assertEqual(len(values), 1)
        self.assertAlmostEqual(values[0]["value"], 41.36, places=2)
        self.assertEqual(values[0]["family"], "pct")

    def test_the_cited_comparison_stays_beside_the_answer_grade(self):
        """A derived answer grades on the derived value and never drops the cited class."""
        numbers = [{"measure": "revenue", "value": 23506.0, "unit": "inr_cr", "period": "FY26"},
                   {"measure": "revenue", "value": 21847.0, "unit": "inr_cr", "period": "FY25"}]
        reply = {"rows": [{"metric": "revenue_growth_yoy_pct", "value": 7.5931, "unit": "pct", "period": "FY26",
                           "provenance": {}}]}
        verdict = ac.classify("pilot3_ratio", reply, numbers, True,
                              "By what percentage did revenue grow in FY26 over FY25?", "revenue_growth_yoy_pct")
        self.assertEqual((verdict["class"], verdict["compared_on"], verdict["cited_class"]),
                         ("match", "derived", "mismatch"))
        wrong = {"rows": [{"metric": "revenue_growth_yoy_pct", "value": 12.5, "unit": "pct", "period": "FY26",
                           "provenance": {}}]}
        verdict = ac.classify("pilot3_ratio", wrong, numbers, True,
                              "By what percentage did revenue grow in FY26 over FY25?", "revenue_growth_yoy_pct")
        self.assertEqual((verdict["class"], verdict["compared_on"]), ("mismatch", "derived"))

    def test_no_derived_value_in_the_reply_keeps_the_cited_comparison(self):
        """Nothing to grade (the reply holds neither the ratio nor its inputs): the old comparison decides."""
        numbers = [{"measure": "revenue", "value": 23506.0, "unit": "inr_cr", "period": "FY26"},
                   {"measure": "revenue", "value": 21847.0, "unit": "inr_cr", "period": "FY25"}]
        reply = {"rows": [{"metric": "capex", "value": 100.0, "unit": "inr_crore", "period": "FY26",
                           "provenance": {}}]}
        verdict = ac.classify("pilot3_fin", reply, numbers, True,
                              "By what percentage did revenue grow in FY26 over FY25?", "capex")
        self.assertEqual((verdict["compared_on"], verdict["class"]), ("cited", "mismatch"))


if __name__ == "__main__":
    unittest.main()
