"""Router tests: deterministic chains, slot parsing, canonical order."""
from __future__ import annotations

import unittest

from reality_engine.query import CANONICAL_ORDER, route
from reality_engine.query import router


def case(**over):
    base = {"mid": "T0001", "source_bank": "shivam30", "family": [2], "entity_level": "stock",
            "answer_kind": "number", "question": "AAA revenue FY26",
            "entities": [{"symbol": "AAA"}], "period": "FY26", "as_of": "2026-10-19",
            "template": None, "archetype": None,
            "rubric": {"required_evidence": ["results_xbrl.filings", "px_nse_adj"]}}
    base.update(over)
    return base


class TestChain(unittest.TestCase):
    def test_resolve_is_always_first(self):
        plan = route(case())
        self.assertEqual(plan["chain"][0], "resolve")

    def test_canonical_order_holds(self):
        plan = route(case(entity_level="market-cap bucket",
                          question="Which large caps rank highest on revenue growth",
                          family=[8], answer_kind="ranking",
                          rubric={"required_evidence": ["results_xbrl.filings",
                                                        "document_chunks", "policy_events"]}))
        order = [CANONICAL_ORDER.index(name) for name in plan["chain"]]
        self.assertEqual(order, sorted(order))
        self.assertIn("SCREEN", plan["chain"])
        self.assertIn("EVIDENCE", plan["chain"])

    def test_ripple_bank_routes_ripple_without_answer_kind(self):
        plan = route(case(source_bank="ripple200", family=[], answer_kind=None,
                          question="copper price move transmission to cable makers"))
        self.assertIn("RIPPLE", plan["chain"])

    def test_text_answer_forces_evidence(self):
        plan = route(case(question="What did management say about margins?",
                          answer_kind="text+quote", rubric={"required_evidence": []}))
        self.assertIn("EVIDENCE", plan["chain"])

    def test_deterministic(self):
        first = route(case())
        second = route(case())
        self.assertEqual(first["chain"], second["chain"])
        self.assertEqual(first["slots"], second["slots"])


class TestPeriods(unittest.TestCase):
    def test_quarter_end(self):
        self.assertEqual(router.period_bounds(case(period="Q2FY27"))[:2],
                         ("2026-09-30", "2026-09-30"))

    def test_fiscal_year(self):
        self.assertEqual(router.period_bounds(case(period="FY25"))[:2],
                         ("2025-03-31", "2025-03-31"))

    def test_month_span(self):
        self.assertEqual(router.period_bounds(case(period="Oct 2023-Oct 2026"))[:2],
                         ("2023-10-01", "2026-10-31"))

    def test_named_date(self):
        self.assertEqual(router.period_bounds(case(period="16 Oct 2026"))[:2],
                         ("2026-10-16", "2026-10-16"))

    def test_ytd_and_52_week(self):
        self.assertEqual(router.period_bounds(case(period="2026", question="YTD high"))[:2],
                         ("2026-01-01", "2026-10-19"))
        start, end, _ = router.period_bounds(case(period="2026", question="52-week high"))
        self.assertEqual(end, "2026-10-19")
        self.assertEqual(start, "2025-10-19")

    def test_lookback(self):
        start, end, basis = router.period_bounds(case(period="", question="3-yr price CAGR"))
        self.assertEqual(end, "2026-10-19")
        self.assertEqual(start, "2023-10-19")
        self.assertIn("lookback", basis)


class TestSlots(unittest.TestCase):
    def test_symbol_and_isin(self):
        plan = route(case(entities=[{"isin": "INE000A01001"}]))
        self.assertEqual(plan["slots"]["isin"], "INE000A01001")
        self.assertIsNone(plan["slots"]["symbol"])

    def test_metric_and_terms(self):
        plan = route(case(question="What was AAA net NPA in Q1FY27?"))
        self.assertEqual(plan["slots"]["metric"], "net_npa")
        self.assertNotIn("what", plan["slots"]["terms"])
        self.assertNotIn("large", router.key_terms("which large caps fell"))

    def test_doc_type_and_page(self):
        plan = route(case(question="What did page 21 of the investor presentation show?",
                          entities=[{"symbol": "AAA"}]))
        self.assertEqual(plan["slots"]["page"], 21)
        self.assertEqual(plan["slots"]["doc_type"], "deck")

    def test_status_from_case_map(self):
        plan = route(case(case_status="needs_new_table:company_segment_pnl"))
        self.assertEqual(plan["status"], "needs_new_table:company_segment_pnl")
        self.assertIn("FACTS", plan["pit_keys"])


if __name__ == "__main__":
    unittest.main()
