"""Character-budget recall, span coverage and per-label slicing: bigger chunks
must pay for their size, and an arm that never covers a gold span must show a
zero coverage ceiling instead of a fake recall."""

import unittest
from types import SimpleNamespace

from reality_engine.scripts.eval_retrieval import (budget_rank, group_scores,
                                                  is_cross_document,
                                                  span_coverage)


GOLD = {"doc_id": 7, "span_start": 100, "span_end": 140}


def hit(start, end, char_len, doc_id=7):
    return {"doc_id": doc_id, "norm_start": start, "norm_end": end,
            "char_len": char_len}


class BudgetRankTests(unittest.TestCase):
    def test_hit_beyond_budget_is_a_miss(self):
        hits = [hit(0, 50, 4000), hit(90, 150, 4000)]
        self.assertEqual(budget_rank(hits, GOLD, 10000), 2)
        self.assertIsNone(budget_rank(hits, GOLD, 5000))

    def test_one_huge_chunk_gets_no_free_overlap(self):
        hits = [hit(50, 150, 8000)]
        self.assertIsNone(budget_rank(hits, GOLD, 5000))
        self.assertEqual(budget_rank(hits, GOLD, 10000), 1)

    def test_wrong_document_never_matches(self):
        hits = [hit(90, 150, 100, doc_id=8)]
        self.assertIsNone(budget_rank(hits, GOLD, 10000))


def store(*units):
    """Minimal Store stand-in: just the chunk map ``span_coverage`` reads."""
    by_chunk = {}
    for i, (doc_id, start, end) in enumerate(units):
        by_chunk[str(i)] = {"doc_id": doc_id, "norm_start": start, "norm_end": end}
    return SimpleNamespace(by_chunk=by_chunk)


class CoverageTests(unittest.TestCase):
    def test_unmapped_unit_cannot_cover(self):
        gold = [{"doc_id": 7, "span_start": 100, "span_end": 140}]
        got = span_coverage(store((7, -1, -1)), gold)
        self.assertEqual((got["covered"], got["coverage"]), (0, 0.0))

    def test_any_overlap_counts_and_wrong_doc_does_not(self):
        gold = [{"doc_id": 7, "span_start": 100, "span_end": 140},
                {"doc_id": 8, "span_start": 10, "span_end": 20}]
        got = span_coverage(store((7, 130, 200), (7, 0, 99), (9, 10, 20)), gold)
        self.assertEqual(got["covered"], 1)
        self.assertEqual(got["coverage"], 0.5)


class CrossDocumentFlagTests(unittest.TestCase):
    def test_boolean_field_and_legacy_why_prefix(self):
        self.assertTrue(is_cross_document({"cross_document": True}))
        self.assertTrue(is_cross_document({"why": "cross-document: growth bridge"}))
        self.assertFalse(is_cross_document({"cross_document": False, "why": "table row"}))
        self.assertFalse(is_cross_document({}))


class GroupScoreTests(unittest.TestCase):
    def test_slices_by_field_and_skips_blank_values(self):
        rows = [{"qid": "a", "sector": "Banks"}, {"qid": "b", "sector": "Banks"},
                {"qid": "c", "sector": ""}]
        ranks = {"a": 1, "b": None, "c": 3}
        budget = {5000: {"a": 1, "b": None, "c": None},
                  10000: {"a": 1, "b": None, "c": 3}}
        got = group_scores(rows, ["sector"], ranks, budget)
        self.assertEqual(sorted(got["sector"]), ["Banks"])
        self.assertEqual(got["sector"]["Banks"]["n"], 2)
        self.assertEqual(got["sector"]["Banks"]["recall@1"], 0.5)
        self.assertEqual(got["sector"]["Banks"]["budget_recall@10000"], 0.5)


if __name__ == "__main__":
    unittest.main()
