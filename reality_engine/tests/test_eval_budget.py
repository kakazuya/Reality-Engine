"""Character-budget recall: bigger chunks must pay for their size."""

import unittest

from reality_engine.scripts.eval_retrieval import budget_rank


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


if __name__ == "__main__":
    unittest.main()
