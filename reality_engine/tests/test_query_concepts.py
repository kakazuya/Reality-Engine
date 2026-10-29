"""Ask-concept routing: the gate's alias table, the row that must carry it, and the
computations the bank asks for by name (sessions near the high, drawdown recovery,
RSI divergence, volume/delivery).

The rule the task fixes: a row carries a concept only when the ask really names it,
and a row of the right concept passes while a row of another concept still fails.
"""
import unittest

from reality_engine.query import compute, gate
from reality_engine.query.planners import facts


def _hop(rows, hop="SERIES", detail=""):
    return {"hop": hop, "rows": rows, "detail": detail}


class TestAskConceptsAreTheAsk(unittest.TestCase):
    def test_short_alias_does_not_match_inside_a_word(self):
        # "pe" inside "complete"/"per", "pat" inside "Data Patterns", "rsi"
        # inside "diversification", "eps" inside "steps" are not asks.
        for question in ("what does the file complete say",
                         "Data Patterns capacity and licence",
                         "diversification of the portfolio"):
            self.assertNotIn("valuation", gate.asked_concepts(question), question)
            self.assertNotIn("pat", gate.asked_concepts(question), question)
        self.assertNotIn("rsi", gate.asked_concepts("diversification"))

    def test_real_synonyms_still_name_the_concept(self):
        self.assertIn("valuation", gate.asked_concepts("MSUMI P/B versus the stored ratio"))
        self.assertIn("valuation", gate.asked_concepts("what is its P/E now"))
        self.assertIn("range", gate.asked_concepts("the 52-week high and the higher highs"))
        self.assertIn("cagr", gate.asked_concepts("3-year adjusted price CAGR"))
        self.assertIn("capex", gate.asked_concepts("capex per store"))
        self.assertIn("segment", gate.asked_concepts("segment revenue for Q1FY27"))

    def test_adjustment_basis_is_not_the_ask(self):
        # "split- and dividend-adjusted closes" asks for the CAGR.
        self.assertEqual(gate.asked_concepts(
            "3-year price CAGR using split- and dividend-adjusted closes"), ["cagr"])

    def test_entity_reference_is_not_an_identity_ask(self):
        self.assertNotIn("isin_identity", gate.asked_concepts(
            "What did ISIN INE864I01014 say about capacity?"))
        self.assertIn("isin_identity", gate.asked_concepts("the name change after the demerger"))


class TestRowMustCarryTheConcept(unittest.TestCase):
    def test_right_concept_row_passes(self):
        concepts = gate.asked_concepts("HAL 52-week high")
        hop = _hop([{"ref": "HAL", "item": "close, return, high, low"}])
        ok, missing = gate.ask_coverage([hop], concepts, [])
        self.assertTrue(ok, missing)

    def test_wrong_concept_row_still_fails(self):
        concepts = gate.asked_concepts("HAL 52-week high")
        hop = _hop([{"ref": "HAL", "item": "close"}])
        ok, missing = gate.ask_coverage([hop], concepts, [])
        self.assertFalse(ok)
        self.assertTrue(missing and "range" in missing[0])

    def test_two_part_ask_needs_both_parts(self):
        concepts = gate.asked_concepts("capacity expansion timeline with capex and quote")
        only_capacity = _hop([{"ref": "X", "item": "bed capacity 73%"}], hop="FACTS")
        self.assertFalse(gate.ask_coverage([only_capacity], concepts, [])[0])
        both = _hop([{"ref": "X", "item": "bed capacity 73%"}, {"ref": "X", "item": "capex 1,200"}],
                    hop="FACTS")
        self.assertTrue(gate.ask_coverage([both], concepts, [])[0])


class TestConceptWordsReachTheStores(unittest.TestCase):
    def test_asked_words_unions_every_named_concept(self):
        words = facts.asked_words("capacity expansion and capex", "capacity")
        self.assertIn("capacity", words)
        self.assertIn("capex", words)

    def test_segment_rows_name_the_segment(self):
        class Ctx:
            def rows(self, name, sql, params=()):
                return [{"segment": "Aerospace", "period_end": "2026-06-30", "metric": "revenue",
                         "basis": "consolidated", "value_cr": 1234.5,
                         "share_of_total_pct": 61.2, "doc_id": "d1", "page": 7,
                         "known_at": "2026-08-01T10:00:00"}]

        rows, _ = facts._segment_pnl(Ctx(), "INE000000000", "2026-10-19", (None, None))
        self.assertEqual(len(rows), 1)
        self.assertIn("segment", rows[0]["item"])
        self.assertIn("revenue", rows[0]["item"])
        self.assertEqual(rows[0]["unit"], "Rs crore")


class TestNamedStudies(unittest.TestCase):
    points = [("2026-01-01", 100.0), ("2026-01-02", 99.0), ("2026-01-03", 101.0),
              ("2026-01-04", 100.5), ("2026-01-05", 101.0)]

    def test_days_within_counts_sessions_near_the_high(self):
        near = compute.days_within(self.points, 2.0)
        self.assertEqual(near["sessions"], 5)
        self.assertEqual(near["near"], 5)  # 99 is within 2% of 101 (>= 98.98)
        tight = compute.days_within(self.points, 0.6)
        self.assertEqual(tight["near"], 3)  # 101, 100.5, 101
        self.assertAlmostEqual(near["share_pct"], 100.0)

    def test_drawdown_recovery_reports_sessions_to_regain_the_peak(self):
        points = [("2026-01-01", 100.0), ("2026-01-02", 80.0), ("2026-01-03", 90.0),
                  ("2026-01-04", 100.0), ("2026-01-05", 70.0), ("2026-01-06", 100.0),
                  ("2026-01-07", 100.0), ("2026-01-08", 100.0)] * 3
        falls = compute.drawdown_recoveries(points, 15.0)
        self.assertTrue(falls)
        self.assertLessEqual(falls[-1]["fall_pct"], -15.0)
        self.assertIsNotNone(falls[-1]["recovered"])

    def test_rsi_divergence_is_price_low_with_rsi_high(self):
        prices = [90.0 + i * 0.1 for i in range(20)] + [
            95.0, 90.0, 93.0, 96.0, 94.0, 92.0, 88.0, 85.0, 88.0, 92.0]
        rsis = [50.0] * 20 + [50.0, 40.0, 42.0, 46.0, 45.0, 44.0, 44.0, 45.0, 46.0, 48.0]
        dated = [(f"2026-01-{i + 1:02d}", p, r) for i, (p, r) in enumerate(zip(prices, rsis))]
        found = compute.rsi_divergence(dated)
        self.assertIsNotNone(found)
        self.assertTrue(found["price_lower_low"])
        self.assertTrue(found["rsi_higher_low"])
        self.assertTrue(found["divergence"])

    def test_flow_stats_reports_volume_and_delivery(self):
        stats = compute.flow_stats([{"volume": 10, "delivery_pct": 40.0},
                                    {"volume": 30, "delivery_pct": 60.0}])
        self.assertEqual(stats["volume_last"], 30)
        self.assertEqual(stats["volume_avg"], 20)
        self.assertEqual(stats["delivery_avg"], 50.0)


if __name__ == "__main__":
    unittest.main()
