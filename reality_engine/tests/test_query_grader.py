"""Strict grader: every part of the ask, and nothing but the ask.

The 10-row hand check of the 2026-10-29 gate run found 3 of 10 strict-ANSWERED
rows wrong and 3 partial.  These tests pin the three rules that closed that gap:

1. a multi-part ask ("share count AND promoter holding", "promoter AND public",
   "business AND segments", "raw AND adjusted") is PARTIAL when a part is
   missing, even though the bench hop returned rows;
2. rows that carry no part of the ask are counted, and one that carries a number
   makes the case PARTIAL;
3. a judgement ask ("has the debt fallen") needs a row carrying that metric, not
   a price return.

Fixtures only, no database: the grader is pure once the doc index is stubbed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from reality_engine.query import gate

REPO = Path(__file__).resolve().parents[2]


def _case(question: str, period: str = "Sep 2026") -> dict:
    return {"question": question, "as_of": "2026-10-19", "period": period,
            "entities": [{"isin": "INE000A01001", "symbol": "AAA"}],
            "answer_kind": "numeric", "family": [11]}


def _slots(question: str, period: str = "Sep 2026") -> dict:
    return {"isin": "INE000A01001", "symbol": "AAA", "symbols": ["INE000A01001", "AAA"],
            "question": question, "period": period, "period_basis": "month",
            "date_from": "2026-09-01", "date_to": "2026-09-30"}


def _holding_row(item: str, value: float) -> dict:
    return {"isin": "INE000A01001", "symbol": "AAA", "item": item, "period": "2026-09-30",
            "known_at": "2026-10-02T10:00:00", "ref": "shp_index:2026-09-30",
            "value": value, "unit": "%", "store": "shp_index"}


def _series_row(item: str, detail: str, day: str = "2026-09-30") -> dict:
    return {"hop": "SERIES", "ok": True, "na": False,
            "rows": [{"isin": "INE000A01001", "symbol": "AAA", "item": item,
                      "known_at": day, "ref": "AAA"}],
            "detail": detail}


def _evidence_row(quote: str) -> dict:
    return {"hop": "EVIDENCE", "ok": True, "na": False,
            "rows": [{"isin": "INE000A01001", "symbol": "AAA", "quote": quote,
                      "known_at": "2026-09-30", "ref": "deck_figures:x#7"}],
            "detail": quote}


def _facts_hop(*rows, detail: str = "") -> dict:
    return {"hop": "FACTS", "ok": True, "na": False, "rows": list(rows),
            "detail": detail or "; ".join(str(row.get("item")) for row in rows)}


def _result(question: str, hops: list[dict], answer: str, period: str = "Sep 2026") -> dict:
    return {"mid": "T1", "grade": "ANSWERED", "regression": False, "family": [11],
            "entity_level": "stock", "source_bank": "test", "question": question,
            "as_of": "2026-10-19", "period": period, "answer": answer, "evidence": [],
            "hops_ok": [hop["hop"] for hop in hops],
            "gate": [{"index": 0, "text": question, "gate": None, "ask_concepts": [],
                      "slots": _slots(question, period), "hops": hops}]}


class _Index:
    """Doc index stub: no snapshot, no staleness or named-document rule."""

    ok = True

    def exists(self, symbol, doc_type, day, tol=3):
        return False

    def latest(self, symbol, doc_type, as_of):
        return None


class TestGraderRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO / "tasks" / "answer_bench"))
        import grade_v1
        cls.g = grade_v1

    def grade(self, case, row):
        return self.g.grade_row(case, row, _Index())

    def test_one_part_of_a_two_part_ask_is_partial(self):
        # "promoter and public holding": only the public number is returned.
        question = "AAA promoter and public holding Sep 2026"
        row = _result(question,
                      [_facts_hop(_holding_row("Public holding %", 47.1))],
                      "Public holding % 2026-09-30 = 47.1 %")
        graded = self.grade(_case(question), row)
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any("promoter" in reason for reason in graded["strict_reasons"]),
                        graded["strict_reasons"])

    def test_both_parts_is_answered(self):
        question = "AAA promoter and public holding Sep 2026"
        row = _result(question,
                      [_facts_hop(_holding_row("Promoter holding %", 52.9),
                                  _holding_row("Public holding %", 47.1))],
                      "Promoter holding % = 52.9 %; Public holding % = 47.1 %")
        graded = self.grade(_case(question), row)
        self.assertEqual(graded["strict_grade"], "ANSWERED", graded["strict_reasons"])

    def test_raw_and_adjusted_are_two_parts(self):
        question = "AAA YTD high for 2026, raw and adjusted for its corporate action"
        only_adjusted = _series_row("high",
                                    "AAA: adjusted high 1,150 (2026-05-27)")
        graded = self.grade(_case(question, "2026"),
                            _result(question, [only_adjusted],
                                    "adjusted high 1,150 (2026-05-27)"))
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any("raw" in reason for reason in graded["strict_reasons"]),
                        graded["strict_reasons"])
        both = _series_row("high", "AAA: adjusted high 1,150; raw close high 1,150")
        graded = self.grade(_case(question, "2026"),
                            _result(question, [both],
                                    "adjusted high 1,150; raw close high 1,150"))
        self.assertEqual(graded["strict_grade"], "ANSWERED", graded["strict_reasons"])

    def test_unrelated_numeric_row_is_partial(self):
        # A YTD-high answer with a Novelis EBITDA bridge appended.
        question = "AAA YTD high for 2026"
        series = _series_row("close, high, low",
                             "AAA: YTD high 1,150 (2026-05-27), low 840.2 (2026-03-23)")
        bridge = _evidence_row("Q2 Adjusted EBITDA Bridge vs. prior year $ millions 484 14 "
                               "(7) (38) (7) 16 462 Q2FY24 Volume Price/Mix")
        graded = self.grade(_case(question, "2026"),
                            _result(question, [series, bridge],
                                    "YTD high 1,150; Q2 Adjusted EBITDA Bridge $ millions 484"))
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertGreaterEqual(graded["unrelated_rows"], 1)
        self.assertTrue(any("unrelated" in reason for reason in graded["strict_reasons"]),
                        graded["strict_reasons"])

    def test_unrelated_row_without_a_number_alone_is_reported_not_penalised(self):
        question = "AAA YTD high for 2026"
        series = _series_row("high", "AAA: YTD high 1,150 (2026-05-27)")
        note = _evidence_row("the management commentary is upbeat")
        graded = self.grade(_case(question, "2026"),
                            _result(question, [series, note], "YTD high 1,150"))
        self.assertEqual(graded["unrelated_rows"], 1)
        self.assertEqual(graded["strict_grade"], "ANSWERED", graded["strict_reasons"])

    def test_judgement_ask_is_not_answered_by_a_price_return(self):
        # "has the debt fallen, or has it moved into CWIP and JVs" -> a 4-year
        # price return is not the debt metric.
        question = ("Jaiprakash Power: has the debt actually fallen, or has it been "
                    "moved into CWIP and JVs")
        price = _series_row("close, return",
                            "AAA: 2022-03-31 close 62.5 -> 2026-03-30 close 268.6, "
                            "return 329.4% (988 sessions)")
        graded = self.grade(_case(question, "FY22-FY26"),
                            _result(question, [price],
                                    "AAA: return 329.4% (988 sessions)", "FY22-FY26"))
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any("ask_match" in reason or "concept_substance" in reason
                            for reason in graded["strict_reasons"]),
                        graded["strict_reasons"])


class TestAskParts(unittest.TestCase):
    def test_promoter_and_public_are_two_concepts(self):
        self.assertEqual(gate.asked_concepts("public shareholding Sep 2026"),
                         ["public_holding"])
        self.assertEqual(gate.asked_concepts("promoter and public shareholding"),
                         ["public_holding", "promoter"])

    def test_share_count_and_holding_are_two_concepts(self):
        concepts = gate.asked_concepts(
            "the exact share count and promoter holding now, after its corporate action")
        self.assertIn("share_count", concepts)
        self.assertIn("promoter", concepts)

    def test_a_public_row_does_not_answer_a_promoter_ask(self):
        hop = _facts_hop(_holding_row("Public holding %", 68.5))
        ok, why = gate.ask_coverage([hop], ["promoter"], [])
        self.assertFalse(ok, why)

    def test_judgement_subject_is_the_metric_not_the_company(self):
        subjects = gate.judgement_subject(
            "Jaiprakash Power: has the debt actually fallen, or has it been moved "
            "into CWIP and JVs")
        self.assertIn("debt", subjects)
        self.assertNotIn("jaiprakash", subjects)
        # A judgement about the stock's price is a price ask.
        self.assertEqual(gate.judgement_subject("has the stock recovered since the fall"), [])

    def test_substance_missing_names_the_metric_no_row_carries(self):
        hop = _series_row("close", "AAA: close 268.6, return 329.4%")
        self.assertEqual(gate.substance_missing([hop], ["debt"]), ["debt"])
        debt_hop = _facts_hop({"item": "Total debt", "value": 3234.0, "unit": "Rs crore"},
                              detail="Total debt FY26 = 3,234 Rs crore")
        self.assertEqual(gate.substance_missing([debt_hop], ["debt"]), [])

    def test_carries_number_ignores_dates(self):
        self.assertTrue(gate.carries_number("1,150 (2026-05-27)"))
        self.assertFalse(gate.carries_number("close 2026-05-27 only"))


if __name__ == "__main__":
    unittest.main()
