"""Unit tests for the frozen OCR gate scoring (no PDFs, no database, no engine)."""
from __future__ import annotations

import unittest

from reality_engine.scripts import hp_ocr_gate as gate


class NumberTokenTests(unittest.TestCase):
    def test_commas_are_stripped_and_duplicates_removed(self):
        self.assertEqual(gate.numbers("1,433 and 1,433 and 12.5%"), ["1433", "12.5"])

    def test_leading_dot_is_dropped(self):
        self.assertEqual(gate.numbers("value 42."), ["42"])

    def test_letters_do_not_create_tokens(self):
        self.assertEqual(gate.numbers("A1B 2024"), ["1", "2024"])


class ScoringTests(unittest.TestCase):
    TRUTH = "Revenue 1,433.50 and 20,000 in FY24. Total 21,433.50"

    def test_perfect_ocr(self):
        score = gate.score_page(self.TRUTH, self.TRUTH)
        self.assertEqual(score["accuracy"], 1.0)
        self.assertEqual(score["number_recall"], 1.0)
        self.assertEqual(score["number_precision"], 1.0)

    def test_missing_number_costs_recall_not_precision(self):
        score = gate.score_page(self.TRUTH, "Revenue 1,433.50 and 20,000 in FY24.")
        self.assertLess(score["number_recall"], 1.0)
        self.assertEqual(score["number_precision"], 1.0)

    def test_spurious_number_costs_precision(self):
        score = gate.score_page("Revenue 100", "Revenue 100 999")
        self.assertEqual(score["number_recall"], 1.0)
        self.assertEqual(score["number_precision"], 0.5)

    def test_empty_ocr_scores_zero_precision_when_truth_has_numbers(self):
        score = gate.score_page("Revenue 100", "")
        self.assertEqual(score["number_recall"], 0.0)
        self.assertEqual(score["number_precision"], 0.0)


class PageRuleTests(unittest.TestCase):
    def test_table_page_needs_numbers_and_digits(self):
        stats = {"chars": 400, "words": 100, "numbers": 20,
                 "numbers_3digits": 10, "number_share": 0.2}
        self.assertTrue(gate.is_table_page(stats))
        stats["numbers_3digits"] = 2
        self.assertFalse(gate.is_table_page(stats))

    def test_prose_page_rejects_dense_numbers(self):
        stats = {"chars": 800, "words": 150, "numbers": 3,
                 "numbers_3digits": 1, "number_share": 0.02}
        self.assertTrue(gate.is_prose_page(stats))
        stats["numbers"] = 20
        stats["number_share"] = 0.13
        self.assertFalse(gate.is_prose_page(stats))


class GateTests(unittest.TestCase):
    def summary(self, recall, precision):
        return {"table": {"number_recall": recall, "number_precision": precision}}

    def test_gate_passes_at_thresholds(self):
        self.assertTrue(gate.gate_verdict(self.summary(0.95, 0.98))["passed"])

    def test_gate_fails_below_either_threshold(self):
        self.assertFalse(gate.gate_verdict(self.summary(0.949, 0.99))["passed"])
        self.assertFalse(gate.gate_verdict(self.summary(0.99, 0.979))["passed"])

    def test_gate_fails_without_scores(self):
        self.assertFalse(gate.gate_verdict({})["passed"])


class CombinationTests(unittest.TestCase):
    def test_agreement_keeps_only_shared_numbers(self):
        manifest = {"pages": [{"id": "T1", "kind": "table", "doc_type": "results",
                               "pdf": "x.pdf", "page": 0,
                               "truth": "100 200 300"}]}
        rows_a = {"T1": {"text": "100 200 999"}}
        rows_b = {"T1": {"text": "100 200 300"}}
        rows = gate.combine_pair(rows_a, rows_b, manifest)
        agree = [r for r in rows if r["mode"] == "agree"][0]
        union = [r for r in rows if r["mode"] == "union"][0]
        self.assertEqual(agree["number_recall"], 0.6667)
        self.assertEqual(agree["number_precision"], 1.0)
        self.assertEqual(union["number_recall"], 1.0)
        self.assertLess(union["number_precision"], agree["number_precision"])
        self.assertTrue(agree["disagree"])


if __name__ == "__main__":
    unittest.main()
