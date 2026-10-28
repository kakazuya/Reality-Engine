"""Offline tests for ``reality_engine.processing.chunker_v3`` (no DB, no network, no D:)."""

import unittest

from reality_engine.processing import chunker_v3 as v3


RESOLVER = v3.EntityResolver(
    names={"Reliance Industries": "INE002A01018", "Titan Company": "INE280A01028"},
    symbols={"RELIANCE": "INE002A01018", "TITAN": "INE280A01028"},
)


def concall_text() -> str:
    return (
        "Anil Kumar: Good morning everyone. Revenue for the quarter was Rs 1,234 crore, up 18 percent. "
        "We expect margins to improve in the next quarter.\n"
        "Analyst 1: Could you comment on the order book and the capex plan?\n"
        "Anil Kumar: Yes, the order book stands at Rs 5,600 crore. Capex of Rs 400 crore is planned for "
        "the next year and we target a 12 percent margin. Demand in India remains strong.\n"
        "Sanjay Rao: Thank you. We will now take the next question.\n"
    )


CONCALL_DOC = {
    "doc_id": "sha:concall1", "doc_type": "concall", "isin": "INE280A01028",
    "symbol_at_time": "TITAN", "fiscal_period": "FY26Q3",
    "known_at": "2025-11-08T16:47:31", "quality_grade": "A", "pit_confidence": 1.0,
}


def ar_pages() -> list[str]:
    mdna = ("MANAGEMENT DISCUSSION AND ANALYSIS\n"
            "Demand remained strong across India and the company gained share in every region during the "
            "year. Revenue grew 12 percent and the order book stood at Rs 5,600 crore at the end of the "
            "year, giving visibility into the next twelve months of execution across both businesses.\n")
    related = ("RELATED PARTY TRANSACTIONS\n"
               "Note 34 Related party disclosures: transactions with key managerial personnel were "
               "Rs 12 crore during the year. No amounts are outstanding beyond the normal course, and the "
               "company confirms that all transactions were on arm\'s length terms approved by the audit "
               "committee at its meetings during the year under review.\n")
    note = ("Note 5 Segment Information\n"
            "The company operates in two segments. Segment revenue was Rs 4,500 crore for the year and "
            "geographic revenue was split India 82 percent and the rest of the world 18 percent. The "
            "segment assets and liabilities are reported to the chief operating decision maker on a "
            "consistent basis and there is no material change in the basis of measurement this year.\n")
    return ["Cover page\nAnnual Report 2026\n", mdna, related, note]


class HeaderAndCaseTest(unittest.TestCase):
    def test_header_carries_isin_period_and_known_at(self):
        chunks = v3.chunk_concall_v3(concall_text(), CONCALL_DOC)
        self.assertTrue(chunks)
        for c in chunks:
            self.assertIn("INE280A01028", c.header)
            self.assertIn("TITAN", c.header)
            self.assertIn("FY26Q3", c.header)
            self.assertIn("known 2025-11-08T16:47:31", c.header)
            self.assertEqual(c.isin, "INE280A01028")
            self.assertEqual(c.symbol_at_time, "TITAN")

    def test_original_case_is_preserved(self):
        chunks = v3.chunk_concall_v3(concall_text(), CONCALL_DOC)
        body = " ".join(c.body for c in chunks)
        self.assertIn("India", body)
        self.assertIn("Rs 1,234 crore", body)
        self.assertNotIn("india", body)


class ConcallTest(unittest.TestCase):
    def test_qa_pair_and_roles(self):
        chunks = v3.chunk_concall_v3(concall_text(), CONCALL_DOC)
        qa = [c for c in chunks if c.section == "Q&A"]
        self.assertTrue(qa, [c.section for c in chunks])
        # the Q&A pair is one chunk: the questioner asks, management answers, and
        # the answer carries most characters, so the chunk's role is management
        self.assertEqual(qa[0].speaker_role, "management")
        self.assertEqual(qa[0].speaker, "analyst 1")
        self.assertIn("Could you comment on the order book", qa[0].body)
        self.assertIn("Rs 5,600 crore", qa[0].body)
        opening = [c for c in chunks if c.section == "Opening remarks"]
        self.assertTrue(opening)
        self.assertEqual(opening[0].speaker_role, "management")
        self.assertIn("section:qa", qa[0].tags)

    def test_deterministic_tags(self):
        chunks = v3.chunk_concall_v3(concall_text(), CONCALL_DOC)
        tags = set().union(*(c.tags for c in chunks))
        for tag in ("order_book", "capex", "demand", "guidance", "forward_looking",
                    "has_number", "unit:inr_crore", "unit:percent",
                    "speaker_role:management"):
            self.assertIn(tag, tags)

    def test_entity_mentions_resolve_to_isin(self):
        text = concall_text() + "Reliance Industries remains our largest customer.\n"
        chunks = v3.chunk_concall_v3(text, CONCALL_DOC, RESOLVER)
        ents = dict(e for c in chunks for e in c.entities)
        self.assertEqual(ents.get("INE002A01018"), "RELIANCE")
        # the document's own ISIN is never reported as a mention
        self.assertNotIn("INE280A01028", ents)


class DeckTest(unittest.TestCase):
    def test_one_slide_per_chunk(self):
        pages = [
            "Financial highlights",
            "Revenue from operations for the quarter was Rs 4,500 crore, up 14 percent year on year. "
            "EBITDA margin expanded 120 basis points to 18 percent and PAT was Rs 620 crore, a "
            "growth of 21 percent over the same quarter last year, driven by the India business.",
            "Order book stood at Rs 11,200 crore as of 30 September 2026, up 22 percent year on year, "
            "with the new energy segment contributing 18 percent of the total order book and the "
            "company expecting execution to accelerate in the second half of the financial year.",
        ]
        chunks = v3.chunk_deck_v3(pages, dict(CONCALL_DOC, doc_type="deck", fiscal_period="Q2FY26"))
        self.assertEqual(len(chunks), 2)  # the "Financial highlights" divider merges forward
        self.assertEqual([c.page_from for c in chunks], [1, 3])  # merged chunk starts at the divider
        self.assertTrue(all(c.unit_kind == "slide" for c in chunks))
        self.assertIn("unit:inr_crore", chunks[0].tags)
        self.assertIn("order_book", chunks[1].tags)

    def test_short_slide_merges_forward(self):
        pages = [
            "India business",
            "x",
            "Revenue in India was Rs 9,000 crore for the year with 14 percent growth and healthy margins.",
        ]
        chunks = v3.chunk_deck_v3(pages, dict(CONCALL_DOC, doc_type="deck"))
        self.assertLess(len(chunks), 3)


class AnnualReportTest(unittest.TestCase):
    def test_sections_and_note(self):
        chunks = v3.chunk_annual_report_v3(ar_pages(), dict(CONCALL_DOC, doc_type="annual_report", fiscal_period="FY26"))
        sections = [c.section for c in chunks]
        self.assertTrue(any("MANAGEMENT DISCUSSION" in s for s in sections), sections)
        note = [c for c in chunks if "Note 5" in c.section]
        self.assertTrue(note, sections)
        self.assertIn("geographic revenue", note[0].body)
        self.assertIn("section:notes", note[0].tags)
        self.assertIn("section:mda", " ".join(t for c in chunks for t in c.tags))

    def test_spans_are_verbatim_slices(self):
        pages = ar_pages()
        text = "\n".join(pages)
        chunks = v3.chunk_annual_report_v3(pages, dict(CONCALL_DOC, doc_type="annual_report"))
        for c in chunks:
            self.assertEqual(text[c.span_start:c.span_end], c.body)


class ResultsNotesTest(unittest.TestCase):
    def test_only_notes_pages_and_note_blocks(self):
        pages = [
            "Statement of unaudited financial results\nRevenue 4,500 crore\nProfit 620 crore\n",
            "Notes to the Consolidated Financial Results\n"
            "Note 5 Segment Information\n"
            "Segment revenue was Rs 4,500 crore and geographic revenue was India 82 percent and "
            "rest of the world 18 percent for the quarter ended 30 September 2026. The company "
            "reports two segments and the segment assets and liabilities are reviewed by the chief "
            "operating decision maker on a consistent basis every quarter without any change.\n"
            "Note 6 Related Party Transactions\n"
            "Transactions with key managerial personnel were Rs 12 crore during the quarter. All "
            "transactions were on arm\'s length terms and approved by the audit committee, and no "
            "amounts are outstanding beyond the normal course of business at the end of the quarter.\n",
        ]
        chunks = v3.chunk_results_notes_v3(pages, dict(CONCALL_DOC, doc_type="results_notes", fiscal_period="Q2FY27"))
        self.assertTrue(chunks)
        self.assertFalse(any("Profit 620 crore" in c.body for c in chunks))
        self.assertTrue(all(c.page_from >= 2 for c in chunks), [c.page_from for c in chunks])
        note5 = [c for c in chunks if "Note 5" in c.section]
        self.assertTrue(note5, [c.section for c in chunks])
        self.assertIn("geographic revenue", note5[0].body)
        self.assertIn("section:segment", note5[0].tags)

    def test_missing_notes_marker_falls_back_and_grades_b(self):
        pages = ["Some filing\nRs 10 crore\n", "Other page\nDemand is strong in India.\n"]
        doc = dict(CONCALL_DOC, doc_type="results_notes", quality_grade="A")
        chunks = v3.chunk_results_notes_v3(pages, doc)
        self.assertTrue(chunks)
        self.assertEqual(chunks[0].quality_grade, "B")


class AnnouncementTest(unittest.TestCase):
    def test_short_announcement_is_one_chunk(self):
        pages = ["Outcome of Board Meeting\n"
                 "The Board approved an order win of Rs 1,250 crore from a state utility. "
                 "The order is to be executed over 24 months.\n"]
        chunks = v3.chunk_announcement_v3(pages, dict(CONCALL_DOC, doc_type="announcement",
                                                      known_at="2026-10-16T18:30:00", category="Order Win"))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].unit_kind, "announcement")
        self.assertIn("order_book", chunks[0].tags)
        self.assertIn("known 2026-10-16T18:30:00", chunks[0].header)

    def test_long_announcement_splits_on_headings(self):
        body = ("Paragraph of prose with enough words to be a body for the announcement test. " * 80).strip()
        pages = ["AWARD OF ORDER\n" + body + "\nDIVIDEND\n" + body + "\n"]
        chunks = v3.chunk_announcement_v3(pages, dict(CONCALL_DOC, doc_type="announcement"))
        self.assertGreater(len(chunks), 1)


class DocumentEntrypointTest(unittest.TestCase):
    def test_rejects_unknown_doc_type(self):
        with self.assertRaises(ValueError):
            v3.chunk_document({"doc_type": "mystery"}, ["text"])

    def test_pit_confidence_rules(self):
        self.assertEqual(v3.pit_confidence("bse_dissem"), 1.0)
        self.assertEqual(v3.pit_confidence("folder_name"), 0.6)
        self.assertEqual(v3.pit_confidence("drive_btime", edited_after_upload=True), 0.3)
        with self.assertRaises(ValueError):
            v3.pit_confidence("doc_date")
        with self.assertRaises(ValueError):
            v3.pit_confidence("upload")

    def test_quality_grades(self):
        good = ["A long and healthy page of text. " * 20]
        self.assertEqual(v3.grade_quality(good, "annual_report"), "A")
        self.assertEqual(v3.grade_quality(["tiny"], "annual_report"), "C")
        sparse = ["A long and healthy page of text. " * 20] + ["", ""]
        self.assertEqual(v3.grade_quality(sparse, "annual_report"), "C")

    def test_tag_vocabulary_is_closed(self):
        chunks = v3.chunk_document(CONCALL_DOC, [concall_text()], RESOLVER)
        for c in chunks:
            for tag in c.tags:
                self.assertIn(tag, v3.TAG_VOCAB, tag)


if __name__ == "__main__":
    unittest.main(verbosity=2)
