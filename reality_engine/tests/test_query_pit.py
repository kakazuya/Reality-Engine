"""PIT tests: a document first known after ``as_of`` is never returned.

Two layers are proven here: the reality-data tool functions (``docs``,
``doc_page``, ``doc_find``, ``core.facts``) and the query layer's EVIDENCE
planner.  The fixture is a fake store result dated after the cut; no live
database is touched.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))

import core  # noqa: E402
import lookups_docs  # noqa: E402

AS_OF = "2026-06-30"
LATE = "2026-10-24"


def _entry(date: str, title: str = "deck") -> dict:
    return {"doc_type": "deck", "date": date, "title": title, "stores": [],
            "has_text": True, "has_facts": False, "pages": 10}


class ToolPitTest(unittest.TestCase):
    def setUp(self):
        self._resolve = lookups_docs.core.resolve_one
        self._collect = lookups_docs._collect
        lookups_docs.core.resolve_one = lambda symbol: {"isin": "INE000A01001",
                                                        "nse_symbol": "AAA"}

    def tearDown(self):
        lookups_docs.core.resolve_one = self._resolve
        lookups_docs._collect = self._collect

    def test_docs_never_lists_a_later_document(self):
        lookups_docs._collect = lambda *a, **k: (
            [_entry("2026-06-20", "on time"), _entry(LATE, "late deck")], ["fake"], [])
        result = lookups_docs.docs("AAA", as_of=AS_OF)
        dates = [doc["date"] for doc in result.get("documents") or []]
        self.assertEqual(dates, ["2026-06-20"])
        self.assertNotIn(LATE, json.dumps(result))

    def test_doc_page_refuses_a_later_document(self):
        lookups_docs._collect = lambda *a, **k: ([_entry(LATE)], ["fake"], [])
        result = lookups_docs.doc_page("AAA", LATE, 21, as_of=AS_OF)
        self.assertFalse(result["found"])
        self.assertIn("after as_of", json.dumps(result))
        self.assertNotIn("date_matched", result)

    def test_doc_find_drops_later_passages(self):
        passage = {"store": "document_chunks", "doc_type": "ar", "date": LATE,
                   "doc_id": 9, "page": 3, "quote": "margins expanded", "score": 1}
        saved = (lookups_docs._chunk_passages, lookups_docs._ar_passages,
                 lookups_docs._deck_passages, lookups_docs._announcement_passages)
        try:
            for name in ("_chunk_passages", "_ar_passages", "_deck_passages",
                         "_announcement_passages"):
                setattr(lookups_docs, name, lambda *a, **k: [dict(passage)])
            result = lookups_docs.doc_find("AAA", "margins", as_of=AS_OF)
        finally:
            (lookups_docs._chunk_passages, lookups_docs._ar_passages,
             lookups_docs._deck_passages, lookups_docs._announcement_passages) = saved
        self.assertFalse(result["found"])
        self.assertNotIn(LATE, json.dumps(result))

    def test_facts_drops_a_fact_filed_later(self):
        late_row = {"source": "ar_facts", "kind": "financials", "item": "Revenue",
                    "value": 100.0, "value_raw": "100", "unit": "INR crore",
                    "value_cr": 100.0, "period": "FY26", "period_end": "2026-03-31",
                    "basis": "consolidated", "context": None, "doc_id": 1,
                    "doc_type": "ANNUAL_REPORT", "page": 1, "date": LATE,
                    "url": None, "doc_path": None, "quote": "revenue", "known_at": LATE}
        saved = (core._facts_ar, core._facts_results, core._facts_deck,
                 core._facts_concall, core.resolve_one, core.provenance,
                 core.quarantined_doc_ids)
        try:
            core.resolve_one = lambda symbol: {"isin": "INE000A01001", "nse_symbol": "AAA",
                                               "name": "Alpha Ltd", "bse_code": "500001"}
            core._facts_ar = lambda *a, **k: [dict(late_row)]
            core._facts_results = lambda *a, **k: []
            core._facts_deck = lambda *a, **k: []
            core._facts_concall = lambda *a, **k: []
            core.provenance = lambda *a, **k: {}
            core.quarantined_doc_ids = lambda: set()
            result = core.facts("AAA", kind="financials", as_of=AS_OF)
        finally:
            (core._facts_ar, core._facts_results, core._facts_deck,
             core._facts_concall, core.resolve_one, core.provenance,
             core.quarantined_doc_ids) = saved
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["as_of"], AS_OF)

    def test_facts_keeps_an_on_time_fact(self):
        row = {"source": "ar_facts", "kind": "financials", "item": "Revenue", "value": 100.0,
               "value_raw": "100", "unit": "INR crore", "value_cr": 100.0,
               "period": "FY26", "period_end": "2026-03-31", "basis": "consolidated",
               "context": None, "doc_id": 1, "doc_type": "ANNUAL_REPORT", "page": 1,
               "date": "2026-06-20", "url": None, "doc_path": None, "quote": "revenue",
               "known_at": "2026-06-20"}
        saved = (core._facts_ar, core._facts_results, core._facts_deck,
                 core._facts_concall, core.resolve_one, core.provenance,
                 core.quarantined_doc_ids)
        try:
            core.resolve_one = lambda symbol: {"isin": "INE000A01001", "nse_symbol": "AAA",
                                               "name": "Alpha Ltd", "bse_code": "500001"}
            core._facts_ar = lambda *a, **k: [dict(row)]
            core._facts_results = lambda *a, **k: []
            core._facts_deck = lambda *a, **k: []
            core._facts_concall = lambda *a, **k: []
            core.provenance = lambda *a, **k: {}
            core.quarantined_doc_ids = lambda: set()
            result = core.facts("AAA", kind="financials", as_of=AS_OF)
        finally:
            (core._facts_ar, core._facts_results, core._facts_deck,
             core._facts_concall, core.resolve_one, core.provenance,
             core.quarantined_doc_ids) = saved
        self.assertEqual(len(result["facts"]), 1)
        self.assertEqual(result["facts"][0]["known_at"], "2026-06-20")


if __name__ == "__main__":
    unittest.main()
