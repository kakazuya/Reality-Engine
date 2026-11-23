"""Entity / ask / period gate: the answer contract's three checks.

Fixture rows only, no database: the gate is pure, so a wrong-entity row, a
wrong-metric row and a wrong-period row are each shown to fail, both inside the
answerer's `gate_hop/gate_run` and in the strict grader's independent
recomputation from the same returned rows.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from reality_engine.query.gate import (asked_concepts, ask_coverage, entity_match, gate_hop,
                                       gate_run, period_match, unit_match)

REPO = Path(__file__).resolve().parents[2]
CASES = {
    "question": "AAA promoter holding Sep 2026",
    "as_of": "2026-10-19",
    "period": "Sep 2026",
    "entities": [{"isin": "INE000A01001", "symbol": "AAA"}],
    "answer_kind": "numeric",
}
SLOTS = {"isin": "INE000A01001", "symbol": "AAA", "symbols": ["INE000A01001", "AAA"],
         "question": CASES["question"], "period": "Sep 2026", "period_basis": "month",
         "date_from": "2026-09-01", "date_to": "2026-09-30"}


def _fact(item="Promoter holding %", day="2026-09-30", known="2026-10-02", unit="%",
          symbol="AAA", value=52.9) -> dict:
    return {"item": item, "value": value, "unit": unit, "period": day,
            "known_at": known, "symbol": symbol, "store": "shp_index",
            "ref": f"shp_index:{symbol}"}


def _hop(*rows, hop="FACTS") -> dict:
    return {"hop": hop, "ok": True, "na": False, "rows": list(rows),
            "detail": "; ".join(str(row.get("item")) for row in rows)}


class TestEntityGate(unittest.TestCase):
    def test_wrong_entity_row_fails(self):
        hop = _hop(_fact(symbol="BBB"))
        self.assertFalse(entity_match(hop, SLOTS))

    def test_asked_entity_row_passes(self):
        self.assertTrue(entity_match(_hop(_fact()), SLOTS))

    def test_row_without_identity_is_not_judged(self):
        row = _fact()
        row.pop("symbol")
        row.pop("ref")
        self.assertIsNone(entity_match(_hop(row), SLOTS))

    def test_a_none_doc_id_is_not_an_entity(self):
        row = _fact()
        row.pop("symbol")
        row["ref"] = "FACTS:None#None"
        self.assertIsNone(entity_match(_hop(row), SLOTS))

    def test_run_fails_on_a_wrong_entity_hop(self):
        hop = gate_hop(_hop(_fact(symbol="BBB")), SLOTS, ["promoter"], [])
        self.assertFalse(hop["entity_match"])
        self.assertIn("entity_match", gate_run([hop], {"text": "AAA promoter holding"},
                                               ["promoter"], []))


class TestAskGate(unittest.TestCase):
    def test_products_alias_is_not_promoter(self):
        self.assertEqual(asked_concepts("AEROFLEX products + close"), ["products", "return"])
        self.assertEqual(asked_concepts("public shareholding Sep 2026"), ["public_holding"])

    def test_price_cagr_drops_the_general_price_concept(self):
        self.assertEqual(asked_concepts("3-year price CAGR"), ["cagr"])

    def test_futures_premium_is_not_a_valuation_ask(self):
        self.assertEqual(asked_concepts("futures premium to spot, basis widening"),
                         ["futures"])

    def test_wrong_metric_row_is_not_covered(self):
        hop = gate_hop(_hop(_fact(item="Revenue from operations", unit="Rs crore")),
                       SLOTS, ["promoter"], [])
        self.assertFalse(hop["ask_match"])
        self.assertIn("ask_match", gate_run([hop], {"text": "AAA promoter holding"},
                                            ["promoter"], []))

    def test_two_part_ask_needs_both_parts(self):
        concepts = asked_concepts("AAA products and close")
        rtn = _hop({"ref": "SERIES:AAA", "known_at": "2026-10-19"}, hop="SERIES")
        rtn["detail"] = "AAA: close 12.6, return 2%"
        self.assertIn("ask_match", gate_run([rtn], {"text": "AAA products and close"},
                                           concepts, []))

    def test_absolute_ask_needs_a_money_row(self):
        hop = _hop(_fact(item="Chemicals segment revenue", unit="-", value=10.0))
        self.assertFalse(unit_match(hop, "absolute segment revenue in Rs crore"))

    def test_hidden_numeric_fields_are_not_answer_text(self):
        # The SERIES row carries the high as a number, but the answer prints a
        # close: the ask check must judge the answer, not the planner's dict.
        hop = {"hop": "SERIES", "ok": True, "na": False, "detail": "AAA: close 1,593",
               "rows": [{"ref": "SERIES:AAA", "known_at": "2026-06-30",
                         "high": 1710.0, "low": 1402.0}]}
        self.assertEqual(ask_coverage([hop], ["range"], [])[0], False)

    def test_one_generic_word_is_not_ask_evidence(self):
        hop = {"hop": "EVIDENCE", "ok": True, "na": False, "detail": "",
               "rows": [{"quote": "internal financial control system"}]}
        ok, why = ask_coverage([hop], [], ["control", "change"])
        self.assertFalse(ok)
        self.assertIn("ask_match", why[0])


class TestPeriodGate(unittest.TestCase):
    def test_wrong_quarter_row_fails(self):
        hop = _hop(_fact(day="2026-06-30", known="2026-07-21"))
        self.assertFalse(period_match(hop, dict(SLOTS, question="AAA promoter holding Sep 2026"),
                                      None))

    def test_wrong_quarter_label_fails(self):
        slots = dict(SLOTS, question="AAA net NPA Q1FY27",
                     period="Q1 FY2026-27", period_basis="quarter end",
                     date_from="2026-06-30", date_to="2026-06-30")
        hop = _hop({"item": "Net NPA", "value": 0.5, "unit": "%", "period": "Q4FY26",
                    "known_at": "2026-04-29", "ref": "deck_figures:x#6"})
        self.assertFalse(period_match(hop, slots, None))

    def test_row_in_the_asked_period_passes(self):
        slots = dict(SLOTS, question="AAA net NPA Q1FY27",
                     period="Q1 FY2026-27", period_basis="quarter end",
                     date_from="2026-06-30", date_to="2026-06-30")
        hop = _hop({"item": "Net NPA", "value": 0.39, "unit": "%", "period": "Q1FY27",
                    "known_at": "2026-07-30", "ref": "deck_figures:x#6"})
        self.assertTrue(period_match(hop, slots, None))


class TestStrictGraderRecomputes(unittest.TestCase):
    """grade_v1 must not trust the planner's flags: it rebuilds them from rows."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO / "tasks" / "answer_bench"))
        import grade_v1
        cls.g = grade_v1

    class _Index:
        ok = True

        def exists(self, symbol, doc_type, day, tol=3):
            return False

        def latest(self, symbol, doc_type, as_of):
            return None

    def _row(self, rows, stored_flags=None):
        hop = {"hop": "FACTS", "ok": True, "na": False, "rows": rows}
        if stored_flags:
            hop.update(stored_flags)
        return {"mid": "T1", "grade": "ANSWERED", "regression": False, "family": [11],
                "entity_level": "stock", "source_bank": "test",
                "question": CASES["question"], "as_of": CASES["as_of"],
                "period": CASES["period"], "answer": "Promoter holding % = 52.9 %",
                "evidence": [], "hops_ok": ["FACTS"], "v1": {"answer": "x"},
                "gate": [{"index": 0, "text": "AAA promoter holding", "gate": None,
                          "ask_concepts": ["promoter"], "slots": SLOTS,
                          "hops": [dict(hop, entity_match=True, ask_match=True,
                                        period_match=True)]}]}

    def test_correct_row_is_answered(self):
        graded = self.g.grade_row(CASES, self._row([_fact()]), self._Index())
        self.assertEqual(graded["strict_grade"], "ANSWERED")

    def test_wrong_entity_row_is_partial_even_if_the_flag_lied(self):
        graded = self.g.grade_row(CASES, self._row([_fact(symbol="BBB")]), self._Index())
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any("entity_match" in reason
                            for reason in graded["strict_reasons"]))
        self.assertGreaterEqual(graded["gate_flag_mismatches"], 1)

    def test_wrong_metric_row_is_partial(self):
        graded = self.g.grade_row(
            CASES, self._row([_fact(item="Revenue from operations", unit="Rs crore")]),
            self._Index())
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any("ask_match" in reason for reason in graded["strict_reasons"]))

    def test_wrong_period_row_is_partial(self):
        graded = self.g.grade_row(
            CASES, self._row([_fact(day="2025-09-30", known="2025-10-02")]), self._Index())
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any("period_match" in reason
                            for reason in graded["strict_reasons"]))


if __name__ == "__main__":
    unittest.main()
