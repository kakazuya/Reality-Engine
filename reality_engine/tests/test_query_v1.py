"""v1 query layer: decompose, strict grader rules, named-document preference.

Fixture data only (the shared temp data root from test_query_planners), no live
database is touched.  The strict-grader tests use a fake document index so the
rules are exercised deterministically.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.query import (
    METRIC_SYNONYMS, metric_matches, named_document, route)
from reality_engine.query.answer import evidence_matches, filter_hop
from reality_engine.query.decompose import decompose, sub_case
from reality_engine.tests.test_query_planners import AS_OF, ISIN, build_root, case


def _case(**over) -> dict:
    return case(**over)


class TestDecompose(unittest.TestCase):
    def test_conjunction_splits_the_two_asks(self):
        case_ = _case(
            question="Which large-cap had the biggest promoter stake sale in the last year, "
                     "and did the stock absorb it?",
            entity_level="market-cap bucket",
            entities=[{"symbol": "TITAN"}, {"symbol": "DMART"}],
            family=[14], period="last 1 year")
        subs = decompose(case_)
        self.assertEqual(len(subs), 2)
        self.assertIn("biggest promoter stake sale", subs[0]["text"])
        self.assertEqual(subs[0]["metric"], "promoter")
        self.assertIn("return", subs[1]["routing_text"])
        self.assertEqual(subs[1]["entity_from"], 0)
        self.assertTrue(subs[0]["universe"])

    def test_list_conjunction_is_not_split(self):
        subs = decompose(_case(question="do receivables and inventory growth run ahead of "
                                         "revenue, and what does the cash-conversion say?"))
        self.assertEqual(len(subs), 2)
        self.assertIn("receivables and inventory", subs[0]["text"])

    def test_rubric_steps_are_the_subs_for_a_single_clause(self):
        case_ = _case(question="HDFC Bank: is the quality of growth improving?",
                      rubric={"required_evidence": [], "required_steps":
                              "show NIM path -> compute credit cost -> compare with peers"})
        subs = decompose(case_)
        self.assertEqual(len(subs), 3)
        self.assertEqual(subs[0]["from"], "rubric")
        self.assertIn("NIM", subs[0]["text"])

    def test_rubric_steps_attach_to_a_multi_ask_question(self):
        case_ = _case(question="Which large-cap had the biggest promoter stake sale in the "
                               "last year, and did the stock absorb it?",
                      rubric={"required_steps": "compute promoter % change per name -> "
                                                "find the deal date -> show the price/volume "
                                                "response"})
        subs = decompose(case_)
        self.assertEqual(len(subs), 2)
        steps = [step for sub in subs for step in sub["steps"]]
        self.assertEqual(len(steps), 3)

    def test_named_document_is_detected(self):
        case_ = _case(question="How many manufacturing facilities does Ganesha Ecosphere have, "
                               "per its investor presentation of 5 August 2026?",
                      entities=[{"symbol": "GANECOS"}], period="Aug 2026")
        subs = decompose(case_)
        self.assertEqual(subs[0]["named_document"], {"doc_type": "deck", "date": "2026-08-05"})
        self.assertEqual(named_document({"question": case_["question"]}),
                         {"doc_type": "deck", "date": "2026-08-05"})

    def test_a_price_date_is_not_a_document(self):
        case_ = _case(question="AAA close on 16 Oct 2026")
        self.assertIsNone(named_document({"question": case_["question"]}))

    def test_dependent_sub_gets_the_picked_entity_and_no_family(self):
        subs = decompose(_case(
            question="Which large-cap had the biggest promoter stake sale, and did the stock "
                     "absorb it?", entity_level="market-cap bucket", family=[14]))
        variant = sub_case(_case(question="x", family=[14], entities=[{"symbol": "TITAN"}]),
                           subs[1], picked={"symbol": "IRFC"})
        self.assertEqual(variant["entities"], [{"symbol": "IRFC", "isin": None}])
        self.assertEqual(variant["family"], [])
        self.assertEqual(variant["entity_level"], "stock")
        self.assertIn("return", variant["question"])


class TestRelevanceFilter(unittest.TestCase):
    def test_net_promoter_score_is_not_promoter_holding(self):
        self.assertTrue(metric_matches("promoter", "Promoter holding %"))
        self.assertFalse(metric_matches("promoter", "Net Promoter Score (NPS)"))
        self.assertTrue(metric_matches("revenue", "Revenue from operations"))
        self.assertFalse(metric_matches("revenue", "sales volume drop"))

    def test_short_keys_are_whole_words(self):
        from reality_engine.query.router import metric_of
        self.assertEqual(metric_of("Himadri Speciality promoter holding")[0], "promoter")
        self.assertEqual(metric_of("shareholding pattern of the promoter")[0], "promoter")

    def test_hop_rows_and_detail_are_filtered(self):
        hop = {"hop": "FACTS", "ok": True, "na": False, "provenance": [], "checked": [],
               "degraded": [], "pit": None, "why": None, "gap": None, "empty": False,
               "nid_reason": None, "seconds": 0.0,
               "rows": [{"item": "Net Promoter Score (NPS)", "value": 89.0, "unit": "-",
                         "store": "deck_figures", "known_at": "2024-05-31", "ref": "d1"},
                        {"item": "Promoter holding %", "value": 52.9, "unit": "%",
                         "store": "shp_index", "known_at": "2026-09-30", "ref": "s1"}]}
        sub = decompose(_case(question="AAA promoter holding"))[0]
        filtered = filter_hop(hop, sub)
        self.assertEqual(len(filtered["rows"]), 1)
        self.assertIn("Promoter holding %", filtered["detail"])
        self.assertNotIn("Net Promoter", filtered["detail"])

    def test_a_hop_with_only_wrong_metric_rows_fails(self):
        hop = {"hop": "FACTS", "ok": True, "na": False, "provenance": [], "checked": [],
               "degraded": [], "pit": None, "why": None, "gap": None, "empty": False,
               "nid_reason": None, "seconds": 0.0,
               "rows": [{"item": "Net Promoter Score (NPS)", "value": 89.0, "unit": "-",
                         "store": "deck_figures", "known_at": "2024-05-31", "ref": "d1"}]}
        sub = decompose(_case(question="AAA promoter holding"))[0]
        self.assertFalse(filter_hop(hop, sub)["ok"])

    def test_evidence_metric_may_appear_before_a_lookalike(self):
        quote = ("Manufacturing Facilities | - | 6 | - ... Recycling & Washing Capacity 218,940")
        self.assertTrue(evidence_matches("facilities", quote))
        self.assertFalse(evidence_matches("promoter", "Net Promoter Score (NPS) | 89"))


class TestNamedDocumentPreference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # mkdtemp's restrictive DACL cannot be opened by sqlite under the
        # worker sandbox; a normal workspace subdirectory can.
        cls.tmp = (Path(".tmp") / "test_query_v1").resolve()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.tmp.mkdir(parents=True, exist_ok=True)
        build_root(cls.tmp)
        from reality_engine.query.ctx import Ctx
        cls.ctx = Ctx(root=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _facts(self, case_):
        from reality_engine.query.planners import load_planners
        plan = route(case_)
        return load_planners()["FACTS"](plan["slots"], plan["as_of"], self.ctx)

    def test_named_deck_is_read_instead_of_the_latest(self):
        hop = self._facts(_case(
            question="AAA capacity per its investor presentation of 1 June 2026",
            rubric={"required_evidence": ["deck_figures.pages"]}))
        self.assertTrue(hop["ok"])
        self.assertTrue(any(row["value"] == 10.0 for row in hop["rows"]))
        self.assertIn("named deck 2026-06-01", hop["detail"])

    def test_a_missing_named_document_never_falls_back_to_an_older_one(self):
        hop = self._facts(_case(
            question="AAA capacity per its investor presentation of 1 January 2026",
            rubric={"required_evidence": ["deck_figures.pages"]}))
        self.assertFalse(hop["ok"])
        self.assertTrue(hop["na"])
        self.assertFalse(hop["rows"])
        self.assertIn("carries no extracted capacity fact", hop["detail"])

    def test_evidence_stays_inside_the_named_document(self):
        def fake_doc_find(symbol, terms, doc_type=None, date=None, as_of=None):
            return {"found": True, "checked": ["fake"], "passages": [
                {"store": "document_chunks", "doc_type": "deck", "date": "2026-06-01",
                 "doc_id": 1, "page": 3, "quote": "capacity 10 MW installed"},
                {"store": "document_chunks", "doc_type": "deck", "date": "2025-12-01",
                 "doc_id": 2, "page": 4, "quote": "capacity 4 MW old deck"}]}

        self.ctx.overrides["doc_find"] = fake_doc_find
        try:
            from reality_engine.query.planners import load_planners
            case_ = _case(question="AAA capacity per its investor presentation of 1 June 2026",
                          answer_kind="text+quote")
            plan = route(case_)
            hop = load_planners()["EVIDENCE"](plan["slots"], plan["as_of"], self.ctx)
        finally:
            self.ctx.overrides.pop("doc_find", None)
        self.assertTrue(hop["ok"])
        self.assertTrue(all(row["known_at"] == "2026-06-01" for row in hop["rows"]))
        self.assertEqual(hop["rows"][0]["quote"], "capacity 10 MW installed")

    def test_rerank_prefers_quote_entity_and_metric_over_plain_overlap(self):
        passages = [
            {"store": "document_chunks", "doc_type": "deck", "date": "2026-06-01", "doc_id": 1,
             "page": 3, "quote": "AAA installed capacity of 10 MW across the site",
             "symbol": "AAA"},
            {"store": "document_chunks", "doc_type": "deck", "date": "2026-06-01", "doc_id": 2,
             "page": 4, "quote": "customer list and distribution details"}]
        from reality_engine.query import rerank
        ranked = rerank.rank(passages, terms=["capacity"], metric_terms=["capacity"],
                             entity="AAA", named_date="2026-06-01", as_of=AS_OF)
        self.assertEqual(ranked[0]["doc_id"], 1)


class _FakeIndex:
    ok = True

    def __init__(self, exists=True, latest="2026-09-30"):
        self._exists = exists
        self._latest = latest

    def exists(self, symbol, doc_type, day, tol=3):
        return self._exists

    def latest(self, symbol, doc_type, as_of):
        return self._latest


def _fact_hop(item, value, day, store="deck_figures", unit="%"):
    return {"hop": "FACTS", "ok": True, "na": False, "rows": [
        {"item": item, "value": value, "unit": unit, "store": store, "known_at": day,
         "ref": f"{store}:{day}"}], "provenance": [{"ref": "x", "known_at": day}],
        "evidence": [f"{day}:FACTS:x"], "checked": [], "degraded": [], "pit": None,
        "detail": f"{item} = {value} ({store}, known {day})", "why": None, "gap": None,
        "empty": False, "nid_reason": None, "seconds": 0.0}


def _v1_row(case_, runs, bench="ANSWERED", answer_text="", evidence=(), hops_ok=()):
    return {"mid": case_.get("mid", "T1"), "grade": bench, "regression": False,
            "family": case_.get("family"), "entity_level": case_.get("entity_level"),
            "source_bank": "test", "question": case_.get("question"),
            "as_of": case_.get("as_of"), "period": case_.get("period"),
            "answer": answer_text, "evidence": list(evidence), "hops_ok": list(hops_ok),
            "v1": {"answer": answer_text}, "subs": runs, "strict_reasons": [],
            "candidate": True}


def _run(index, text, ok=True, hops=(), entities=(), metric=None):
    if metric is None:
        from reality_engine.query.router import metric_of
        metric = metric_of(text)[0]
    return {"index": index, "text": text, "answered": ok, "hops": list(hops),
            "detail": "", "entities": list(entities), "chain": [], "steps": [],
            "metric": metric}


class TestStrictGrader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tasks" / "answer_bench"))
        import grade_v1
        cls.g = grade_v1

    def test_all_sub_questions_covered_is_answered(self):
        case_ = _case(mid="T1", question="AAA capacity, and how did the stock move after results?",
                      family=[1])
        row = _v1_row(case_, [
            _run(0, "AAA capacity", hops=[_fact_hop("capacity", 10.0, "2026-06-20")]),
            _run(1, "how did the stock move after results",
                 hops=[{"hop": "SERIES", "ok": True, "na": False,
                        "rows": [{"ref": "AAA", "known_at": "2026-06-30"}],
                        "evidence": ["2026-06-30:SERIES:AAA"], "detail": "AAA return 3%"}]),
        ], answer_text="capacity = 10 (deck_figures, known 2026-06-20); "
                       "AAA return 3% (SERIES)")
        graded = self.g.grade_row(case_, row, _FakeIndex(latest="2026-06-20"))
        self.assertEqual(graded["strict_grade"], "ANSWERED")

    def test_a_missing_sub_question_is_partial(self):
        case_ = _case(mid="T2", question="AAA capacity, and how did the stock move after results?",
                      family=[1])
        row = _v1_row(case_, [
            _run(0, "AAA capacity", hops=[_fact_hop("capacity", 10.0, "2026-06-20")]),
            _run(1, "how did the stock move after results", ok=False, hops=[]),
        ], answer_text="capacity = 10 (deck_figures, known 2026-06-20)")
        graded = self.g.grade_row(case_, row, _FakeIndex())
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any("sub-question 2" in reason
                            for reason in graded["strict_reasons"]))

    def test_follow_up_priced_on_the_wrong_entity_is_wrong(self):
        case_ = _case(
            mid="T3", question="Which large-cap had the biggest promoter stake sale, and did "
                               "the stock absorb it?", entity_level="market-cap bucket",
            entities=[{"symbol": "TITAN"}], family=[14], period="last 1 year")
        screen = {"hop": "SCREEN", "ok": True, "na": False, "evidence": ["2026-09-30:SCREEN:x"],
                  "rows": [{"symbol": "IRFC", "value": -3.46, "known_at": "2026-09-30",
                            "ref": "shp_index:IRFC"}], "detail": "promoter change IRFC -3.46pp"}
        row = _v1_row(case_, [
            _run(0, "Which large-cap had the biggest promoter stake sale", hops=[screen]),
            _run(1, "did the stock absorb it", entities=[{"symbol": "TITAN"}],
                 hops=[{"hop": "SERIES", "ok": True, "na": False,
                        "rows": [{"ref": "TITAN", "known_at": "2026-10-19"}],
                        "evidence": ["2026-10-19:SERIES:TITAN"], "detail": "TITAN return 18%"}],
                 ),
        ], answer_text="promoter holding change (pp), IRFC -3.46pp")
        graded = self.g.grade_row(case_, row, _FakeIndex())
        self.assertEqual(graded["strict_grade"], "WRONG")
        self.assertIn("IRFC", graded["strict_reasons"][0])

    def test_named_document_evidence_from_another_document_is_wrong(self):
        question = ("How many manufacturing facilities per its investor "
                    "presentation of 5 August 2026?")
        case_ = _case(mid="T4", question=question,
                      entities=[{"symbol": "GANECOS"}], family=[1], period="Aug 2026")
        row = _v1_row(case_, [_run(0, question, hops=[
            _fact_hop("Manufacturing Facilities", 3.0, "2021-01-26")])],
            answer_text="Manufacturing Facilities = 3 (deck_figures, known 2021-01-26)")
        graded = self.g.grade_row(case_, row, _FakeIndex(exists=True))
        self.assertEqual(graded["strict_grade"], "WRONG")
        self.assertIn("2026-08-05", graded["strict_reasons"][0])

    def test_named_document_without_the_document_does_not_penalise(self):
        question = ("How many facilities per its investor presentation of 5 August 2026?")
        case_ = _case(mid="T5", question=question,
                      entities=[{"symbol": "GANECOS"}], family=[1], period="Aug 2026")
        row = _v1_row(case_, [_run(0, question, hops=[
            _fact_hop("Manufacturing Facilities", 6.0, "2026-08-03")])],
            answer_text="Manufacturing Facilities = 6 (deck_figures, known 2026-08-03)")
        graded = self.g.grade_row(case_, row, _FakeIndex(exists=False))
        self.assertEqual(graded["strict_grade"], "ANSWERED")

    def test_stale_rows_are_partial(self):
        # A document-store row, so the freshness rule has a doc type to compare.
        case_ = _case(mid="T6", question="AAA promoter holding Sep 2026",
                      entities=[{"symbol": "AAA"}], period="Sep 2026", family=[11])
        row = _v1_row(case_, [_run(0, "AAA promoter holding", hops=[
            _fact_hop("Promoter holding %", 27.2, "2025-09-30")])],
            answer_text="Promoter holding % = 27.2 % (deck_figures, known 2025-09-30)")
        graded = self.g.grade_row(case_, row, _FakeIndex(latest="2026-06-30"))
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertTrue(any(reason.startswith("stale:") for reason in graded["strict_reasons"]))

    def test_unrelated_rows_reduce_an_answered_grade(self):
        case_ = _case(mid="T7", question="AAA promoter holding", entities=[{"symbol": "AAA"}],
                      family=[11])
        row = _v1_row(case_, [_run(0, "AAA promoter holding", hops=[
            _fact_hop("Promoter holding %", 52.9, "2026-09-30", store="shp_index")])],
            answer_text="Promoter holding % = 52.9 % (shp_index, known 2026-09-30); "
                        "Revenue from operations = 100 (deck_figures, known 2026-06-20); "
                        "Net Promoter Score (NPS) = 89 (deck_figures, known 2026-05-31)")
        graded = self.g.grade_row(case_, row, _FakeIndex())
        self.assertEqual(graded["strict_grade"], "PARTIAL")
        self.assertGreaterEqual(graded["unrelated_rows"], 2)

    def test_blocked_grades_are_never_upgraded(self):
        case_ = _case(mid="T8", question="AAA promoter holding")
        row = _v1_row(case_, [], bench="BLOCKED_SCHEMA")
        graded = self.g.grade_row(case_, row, _FakeIndex())
        self.assertEqual(graded["strict_grade"], "BLOCKED_SCHEMA")


if __name__ == "__main__":
    unittest.main()
