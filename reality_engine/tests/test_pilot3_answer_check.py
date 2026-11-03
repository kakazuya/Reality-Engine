"""Fixture tests for reality_engine/pilot3/answer_check.py (T-049 F, guide O5).

A tiny pilot3.db and a tiny sandbox (one company, five questions, one answers row each) are built under
``.tmp/``: one question for every result class.  No production database, network or model.

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
}
FIN_COLUMNS = 23


def build_fixture() -> None:
    """The pilot3 db: revenue, EBITDA and capex for FY26, and no net-worth row (the empty case)."""
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
    for item, value in (("revenue_from_operations", 23506.0), ("ebitda", 1659.0), ("capex", 100.0)):
        conn.execute(f"INSERT INTO fin_annual_line VALUES ({','.join('?' * FIN_COLUMNS)})",
                     tuple(value if v == "{value}" else item if v == "{item}" else v for v in row))
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
        self.assertEqual(len(self.records), 5)
        self.assertEqual({qid: record["class"] for qid, record in self.records.items()},
                         {"KEC001": "match", "KEC002": "partial", "KEC003": "mismatch",
                          "KEC004": "no_tool", "KEC005": "empty"})
        self.assertEqual(self.result["summary"]["by_company"]["KEC"]["match"], 1)
        self.assertEqual(self.result["summary"]["passed_oracle"], 5)

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
        self.assertEqual(len(rows), 6)


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


if __name__ == "__main__":
    unittest.main()
