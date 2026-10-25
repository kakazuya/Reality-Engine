"""Acceptance tests for the structure-aware chunker (C1)."""

import unittest

from reality_engine.processing import chunker_v2 as cv


META = {
    "doc_id": "42",
    "symbol": "ACME",
    "isin": "INE000A01001",
    "doc_type": "concall",
    "published_date": "2024-11-05",
    "fiscal_period": "Q2 FY25",
}

CONCALL = (
    "q2 and h1 fy25 post earnings conference call october 30, 2024 management team "
    "mr. ravi shah, managing director and ms. neha desai, chief financial officer\n"
    "ravi shah : Good afternoon everyone. Revenue for the quarter grew 18 percent to 1,240 crore "
    "and profit after tax was 96 crore, with an ebitda margin of 15.2 percent on the back of "
    "steady volume growth across both the packaging and agrochemical segments.\n"
    "analyst : Could you explain why the packaging segment margin fell this quarter and when you "
    "expect it to recover?\n"
    "ravi shah : Yes. pvc resin prices rose 22 percent and we could not pass the full increase on "
    "to customers, so the segment margin fell 310 basis points. We expect a full recovery by q4 as "
    "the new contracts reset and the price clause starts biting.\n"
)

SHORT_QA = (
    "ravi shah : welcome to the call.\n"
    "analyst : any update on capacity?\n"
    "ravi shah : yes, we added 400 tonnes in march.\n"
    "analyst : thank you. and the capex number?\n"
    "ravi shah : capex was 82 crore for the year and debt to equity stayed at 0.4 times.\n"
)

LONG_PARA = (
    "Revenue from operations for the year was 1,284 crore, up 18 percent, and the operating "
    "margin improved to 14.6 percent on better realisations and a stable input cost "
    "environment, with the new line commissioned in the second half contributing for the "
    "full year for the first time and the order book staying above two years of revenue. "
)

AR_SMALL = (
    "Notes to the Financial Statements\n"
    "Note 1 Borrowings\n" + LONG_PARA + "\n"
    "Note 2 Cash and bank\nA short note with a single number, 42 crore.\n"
    "Note 3 Segment information\n" + LONG_PARA + "\n"
    "Note 4 Subsequent events\n"
)

DECK_DIVIDED = [
    "Financials",
    "Revenue and margins\n" + LONG_PARA * 2,
    "Thank you.",
    "Outlook and guidance\n" + LONG_PARA * 2,
]

DECK = [
    "Investor presentation q2 fy25\n" + "Revenue growth of 18 percent year on year was led by the "
    "packaging division, which added three new customers in the quarter and expanded the existing "
    "contract with the largest north india converter." * 2,
    "Capital expenditure plan\n" + "We plan 420 crore of capex over three years, of which 180 crore "
    "is for the new plant at gujarat and the balance for debottlenecking existing lines, funded "
    "through internal accruals and a term loan." * 2,
    "Outlook and guidance\n" + "Management guides to 14 to 16 percent revenue growth for fy26 with "
    "ebitda margins at 15 percent or better, supported by the price reset clause and a stable raw "
    "material environment, with no large one-off expected." * 2,
]

ARNOTE = (
    "Notes to the Financial Statements\n"
    "Note 12 Related Party Transactions\n"
    "The following table sets out transactions with related parties for the year ended March 31, 2026.\n"
    "Name | Relationship | Amount (crore) | Outstanding\n"
    "Sanofi Pharma AG | Holding company | 1,240.5 | 310.2\n"
    "Soframed India | Associate | 486.1 | 92.4\n"
    "Avio Pharma | Joint venture | 212.8 | 0.0\n"
    "Total | | 1,939.4 | 402.6\n"
    "The amounts are stated at arm's length and were approved by the audit committee each quarter.\n"
    "Note 13 Borrowings\n"
    "Long term borrowings at the year end were 1,200 crore against 980 crore a year earlier, and the "
    "current maturities of long term debt were 140 crore, with a weighted average cost of 8.6 percent.\n"
)

CIRCULAR = (
    "Ministry of Steel\nProduction Linked Incentive Scheme for Specialty Steel\n"
    "1. The scheme shall be known as the Production Linked Incentive Scheme for Specialty Steel.\n"
    "2. The total outlay of the scheme is 6,322 crore and it will be disbursed over five years.\n"
    "3. Incentive of 4 percent to 6 percent of incremental sales shall be provided to eligible makers.\n"
    "4. An applicant must file its claim within 12 months of the close of the financial year.\n"
)

LONG_NOTE = (
    "Note 20 Segment Information\n"
    + "\n".join(
        f"Paragraph {i}. Revenue from the segment grew steadily and margins improved across the year, "
        "helped by a better product mix, stable input costs and the operating leverage of the newer "
        "lines that were commissioned in the second half of the previous financial year.\n"
        for i in range(30)
    )
)


class ConcallTests(unittest.TestCase):
    def test_three_turn_call_pairs_question_with_answer(self):
        chunks = cv.chunk_document(META, [CONCALL])
        qa = [c for c in chunks if c.unit_kind == "qa_pair"]
        self.assertEqual(len(qa), 1, [c.unit_kind for c in chunks])
        answer = qa[0].body
        self.assertIn("analyst :", answer)
        self.assertIn("margin fell this quarter", answer)
        self.assertIn("pvc resin prices rose 22 percent", answer)
        self.assertIn("full recovery by q4", answer)
        self.assertEqual(qa[0].section, "Q&A")
        self.assertEqual(
            qa[0].header,
            "ACME · Concall transcript · Q2 FY25 · Q&A · filed 2024-11-05",
        )

    def test_opening_remarks_split_by_speaker(self):
        chunks = cv.chunk_document(META, [CONCALL])
        opening = [c for c in chunks if c.unit_kind == "opening_remark"]
        self.assertEqual(len(opening), 1)
        self.assertEqual(opening[0].speaker, "ravi shah")
        self.assertIn("Revenue for the quarter grew 18 percent", opening[0].body)

    def test_bodies_are_verbatim_slices(self):
        chunks = cv.chunk_document(META, [CONCALL])
        for chunk in chunks:
            self.assertEqual(CONCALL[chunk.span_start:chunk.span_end], chunk.body)
            self.assertEqual(len(chunk.body), chunk.char_len)

    def test_short_qa_pairs_merge_inside_the_same_section(self):
        chunks = cv.chunk_document(dict(META, published_date="2025-01-10"), [SHORT_QA])
        qa = [c for c in chunks if c.unit_kind == "qa_pair"]
        self.assertEqual(len(qa), 1, [c.body for c in chunks])
        self.assertIn("capacity", qa[0].body)
        self.assertIn("capex", qa[0].body)
        self.assertLess(len(chunks), 3)


class DeckTests(unittest.TestCase):
    def test_one_slide_per_chunk(self):
        chunks = cv.chunk_document(dict(META, doc_type="deck", symbol="ZYDUS"), DECK)
        self.assertEqual(len(chunks), 3)
        self.assertEqual([c.unit_kind for c in chunks], ["slide"] * 3)
        self.assertEqual([c.page_from for c in chunks], [1, 2, 3])
        self.assertEqual([c.page_to for c in chunks], [1, 2, 3])
        for chunk, page in zip(chunks, DECK):
            self.assertEqual(chunk.body, page)
        self.assertTrue(chunks[1].section.startswith("Capital expenditure plan"))
        self.assertIn("Investor deck", chunks[0].header)

    def test_short_slide_merges_and_header_carries_deck_title_and_section(self):
        chunks = cv.chunk_document(
            dict(META, doc_type="deck", symbol="ZYDUS",
                 title="Q2 FY25 investor presentation"),
            DECK_DIVIDED)
        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertGreaterEqual(chunk.char_len, cv.DECK_MIN_CHARS, chunk.body[:80])
        self.assertIn("Q2 FY25 investor presentation", chunks[0].header)
        self.assertIn("Financials", chunks[0].header)
        self.assertTrue(any("Thank you." in c.body for c in chunks),
                        [c.body[:60] for c in chunks])
        self.assertEqual((chunks[0].page_from, chunks[0].page_to), (1, 2))


class AnnualReportTests(unittest.TestCase):
    def test_note_table_stays_whole(self):
        chunks = cv.chunk_document(
            dict(META, doc_type="annual_report"), [ARNOTE])
        note12 = [c for c in chunks if "Note 12" in c.section]
        self.assertEqual(len(note12), 1, [c.section for c in chunks])
        body = note12[0].body
        self.assertIn("Name | Relationship | Amount (crore) | Outstanding", body)
        self.assertIn("Total | | 1,939.4 | 402.6", body)
        self.assertIn("arm's length", body)

        blocks, tables = cv.blocks_from_text(ARNOTE)
        self.assertTrue(tables, "table detector found no rows")
        for chunk in chunks:
            for start, end in tables:
                self.assertFalse(
                    start < chunk.span_start < end,
                    f"chunk starts inside a table: {chunk.body[:60]!r}",
                )

    def test_oversize_note_splits_at_paragraph_boundaries(self):
        chunks = cv.chunk_document(
            dict(META, doc_type="annual_report", symbol="HEXT"), [LONG_NOTE])
        self.assertGreaterEqual(len(chunks), 2, [c.char_len for c in chunks])
        self.assertGreater(len(LONG_NOTE), cv.MAX_CHARS)
        for chunk in chunks:
            self.assertLessEqual(chunk.char_len, cv.MAX_CHARS)
            self.assertEqual(LONG_NOTE[chunk.span_start:chunk.span_end], chunk.body)
        for chunk in chunks[1:]:
            self.assertEqual(LONG_NOTE[chunk.span_start - 1], "\n",
                             "split did not land on a paragraph boundary")

    def test_undersized_note_merges_and_heading_alone_is_never_a_chunk(self):
        chunks = cv.chunk_document(
            dict(META, doc_type="annual_report", symbol="ACME"), [AR_SMALL])
        self.assertGreaterEqual(len(chunks), 2, [c.body[:60] for c in chunks])
        for chunk in chunks:
            self.assertGreaterEqual(chunk.char_len, cv.MIN_CHARS, chunk.body[:80])
        self.assertTrue(any("single number" in c.body for c in chunks))
        for chunk in chunks:
            self.assertFalse(chunk.body.strip().lower().startswith("note 4")
                             and len(chunk.body.strip()) < cv.MIN_CHARS)

    def test_oversize_split_has_no_tiny_tail(self):
        body = "Note 20 Borrowings\n" + "\n".join(
            "The company repaid 120 crore of borrowings during the year and the weighted "
            "average cost of debt fell to 8.1 percent, with no covenant breach and adequate "
            "headroom under the working capital limits, and the maturity profile stayed "
            "comfortable through the year."
            for _ in range(40))
        chunks = cv.chunk_document(
            dict(META, doc_type="annual_report", symbol="HEXT"), [body])
        self.assertGreaterEqual(len(chunks), 2)
        self.assertLessEqual(max(c.char_len for c in chunks), cv.MAX_CHARS)
        self.assertGreaterEqual(min(c.char_len for c in chunks), 300,
                                [c.char_len for c in chunks])


class CircularTests(unittest.TestCase):
    def test_numbered_clauses_stay_together(self):
        chunks = cv.chunk_document(dict(META, doc_type="circular", symbol=""), [CIRCULAR])
        clauses = [c for c in chunks if c.unit_kind == "clause"]
        self.assertEqual(len(clauses), 4, [c.section for c in chunks])
        self.assertEqual([c.section.split()[1] for c in clauses], ["1", "2", "3", "4"])
        self.assertIn("6,322 crore", clauses[1].body)
        self.assertIn("Production Linked Incentive Scheme", clauses[0].body)
        self.assertIn("PIB/RBI circular", clauses[0].header)
        self.assertEqual(CIRCULAR[clauses[1].span_start:clauses[1].span_end], clauses[1].body)


if __name__ == "__main__":
    unittest.main()



