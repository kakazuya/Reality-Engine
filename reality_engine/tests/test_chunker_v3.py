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

    def test_unknown_opener_is_management_not_analyst(self):
        text = ("Richa Chhabra: Thank you all for joining. I would like to request that "
                "participants limit themselves to two questions.\n"
                "Analyst 1: Could you comment on the order book?\n"
                "Anil Kumar: The order book stands at Rs 5,600 crore.\n")
        chunks = v3.chunk_concall_v3(text, CONCALL_DOC)
        opening = [c for c in chunks if c.section == "Opening remarks"]
        self.assertTrue(opening)
        self.assertEqual(opening[0].speaker_role, "management")

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
        for chunk in chunks:
            self.assertIn(chunk.unit_kind, ("announcement", "announcement_cont"))


class SplitLongTest(unittest.TestCase):
    def test_oversize_note_extends_to_sentence_end(self):
        # One paragraph longer than MAX_CHARS with no sentence end before the
        # hard limit: the split must reach the next sentence end within +15%.
        body = ("word " * 1400)[:6000] + " Sentence ends here. " + ("tail text follows. " * 60)
        pages = ["Note 5 Segment Information\n" + body + "\n"]
        chunks = v3.chunk_annual_report_v3(pages, dict(CONCALL_DOC, doc_type="annual_report"))
        self.assertGreater(len(chunks), 1)
        first = chunks[0]
        self.assertTrue(first.body.rstrip().endswith("."), first.body[-80:])
        self.assertLessEqual(first.char_len, int(v3.MAX_CHARS * 1.15) + 2)
        rest = chunks[1:]
        self.assertTrue(rest[0].unit_kind.endswith("_cont"), rest[0].unit_kind)
        self.assertIn("(cont.)", rest[0].section)
        self.assertIn("(cont.)", rest[0].header)


class ForwardLookingTest(unittest.TestCase):
    def test_needs_verb_and_anchor(self):
        self.assertTrue(v3.is_forward_looking(
            "We expect margins to improve in the next quarter."))
        self.assertTrue(v3.is_forward_looking("We target a 12 percent margin."))
        self.assertTrue(v3.is_forward_looking(
            "The company expects execution to accelerate in the second half."))
        self.assertFalse(v3.is_forward_looking("We will now take the next question."))
        self.assertFalse(v3.is_forward_looking("The transcript will also be available."))
        self.assertFalse(v3.is_forward_looking("We will deliver growth in FY24."))
        self.assertFalse(v3.is_forward_looking(
            "Thank you for your guidance over the years; this will be my last call."))
        self.assertFalse(v3.is_forward_looking(
            "Revenue for the quarter was Rs 1,234 crore."))

    def test_table_row_is_not_forward_looking(self):
        row = " ".join(f"{i} {i * 2} {i * 3}" for i in range(8)) + " will next year"
        self.assertFalse(v3.is_forward_looking(row))

    def test_ordinary_concall_turns_are_not_forward_looking(self):
        neutral = (
            "Moderator: Good morning. This call is being recorded.\n"
            "Analyst 1: Can you comment on the quarter please?\n"
            "Anil Kumar: Revenue for the quarter was Rs 1,234 crore, up 18 percent. "
            "Demand in India remains strong across every region.\n"
        )
        chunks = v3.chunk_concall_v3(neutral, CONCALL_DOC)
        self.assertTrue(chunks)
        for c in chunks:
            self.assertNotIn("forward_looking", c.tags)


class BoundaryRuleTest(unittest.TestCase):
    def test_bare_date_and_table_cell_are_not_headings(self):
        from reality_engine.processing import chunker_v2 as v2
        self.assertFalse(v2._is_heading("31 March 2025"))
        self.assertFalse(v2._is_heading("31 December 2033"))
        self.assertFalse(v2._is_heading("ESOPs)"))
        self.assertTrue(v2._is_heading("MANAGEMENT DISCUSSION AND ANALYSIS"))

    def test_wrapped_line_is_not_a_sentence_end(self):
        from reality_engine.processing import chunker_v2 as v2
        self.assertFalse(v2._is_clean_end("abc\ndef", 4, 7))
        self.assertTrue(v2._is_clean_end("abc.def", 4, 7))
        self.assertTrue(v2._is_clean_end("ab\n\ncd", 4, 6))


class TagPrecisionRulesTest(unittest.TestCase):
    def tags(self, text, section="", doc_type="annual_report"):
        return set(v3.deterministic_tags(text, doc_type, section))

    def test_lodr_boilerplate_is_not_regulatory(self):
        text = ("In terms of the SEBI (Listing Obligations and Disclosure Requirements) "
                "Regulations, 2015, the company has submitted the disclosure to the exchanges.")
        self.assertNotIn("regulatory", self.tags(text))

    def test_retirement_benefits_are_not_management_change(self):
        text = ("The company contributed Rs 12 crore towards retirement benefits and "
                "gratuity for employees during the year under review.")
        self.assertNotIn("management_change", self.tags(text))
        self.assertIn("management_change", self.tags(
            "The Board appointed a new managing director with effect from 1 October."))

    def test_land_acquired_is_not_ma(self):
        self.assertNotIn("m_and_a", self.tags(
            "The company acquired land at Pune for a new plant during the year."))
        self.assertNotIn("m_and_a", self.tags(
            "There are some delays on the land acquisition front this year."))
        self.assertIn("m_and_a", self.tags(
            "The acquisition of a controlling stake in the subsidiary was completed."))

    def test_pricing_power_is_not_pricing(self):
        self.assertNotIn("pricing", self.tags(
            "The business has demonstrated pricing power across cycles."))
        self.assertIn("pricing", self.tags("The company took a price hike of 5 percent."))

    def test_exchange_rate_is_not_a_usd_amount(self):
        self.assertNotIn("unit:usd", self.tags("INR to USD 86.61 and EUR/USD 1.16"))
        self.assertNotIn("unit:usd", self.tags("Argentine Peso / USD 1,073 (all figures in crore)"))
        self.assertIn("unit:usd", self.tags("The order is worth US$ 100 million."))
        self.assertIn("unit:usd", self.tags("Revenue was USD 5 billion."))

    def test_award_ceremony_is_not_an_order(self):
        self.assertNotIn("order_book", self.tags(
            "Awarded the Safety King of the Year 2025 for excellence in safety."))
        self.assertIn("order_book", self.tags(
            "The company has been awarded a contract worth Rs 1,250 crore."))

    def test_contract_resignation_clause_is_not_a_management_change(self):
        self.assertNotIn("management_change", self.tags(
            "In case of resignation with good reason, the notice period is one month."))
        self.assertNotIn("management_change", self.tags(
            "As per the scheme, the Appointed Date is April 1, 2022."))
        self.assertIn("management_change", self.tags(
            "The Chief Financial Officer resigned from the company on 30 September."))
        self.assertIn("management_change", self.tags(
            "Diane Enberg Jurgens has been appointed as an Additional Director."))

    def test_note_cross_reference_is_not_an_accounting_note(self):
        self.assertNotIn("accounting_note", self.tags(
            "Total income as per Segment (Refer note 19) was 80,489.74."))
        self.assertIn("accounting_note", self.tags(
            "Note 4\nProperty, plant and equipment\nParticulars\nLand"))

    def test_ocr_address_is_not_a_percent(self):
        self.assertNotIn("unit:percent", self.tags(
            "Corporate Office : 1%t Floor Srivari Shrimat, Coimbatore - 641018"))
        self.assertIn("unit:percent", self.tags("The EBITDA margin was 18.5%."))

    def test_risk_management_is_not_a_stated_risk(self):
        self.assertNotIn("risk", self.tags(
            "ESG, risk management and cybersecurity and other domains."))
        self.assertIn("risk", self.tags("Contingent liabilities and litigation are disclosed."))

    def test_safe_harbour_is_not_a_stated_risk(self):
        self.assertNotIn("risk", self.tags(
            "These statements are subject to risks and uncertainties, and actual "
            "results may differ materially."))
        self.assertIn("risk", self.tags("Key risks relating to the business are set out below."))

    def test_mda_prose_mentioning_notes_is_not_a_note(self):
        text = ("The management notes that demand was strong across every region this year.")
        self.assertNotIn("section:notes", self.tags(text, "MD&A > Demand"))

    def test_notes_cross_reference_late_in_body_is_not_a_note(self):
        body = ("The Board is responsible for the assurance of the report. " * 6
                + "See notes to the consolidated financial statements.")
        self.assertNotIn("section:notes", self.tags(body, "ASSURE"))


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
