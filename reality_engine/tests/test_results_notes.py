import unittest

from reality_engine.scripts.results_notes import (NOTE_NO, NOTE_ONE, NOTES_HEAD, STATEMENT, STOP, _heading_stop, block_basis, clean_block,
                      detect_quarter, fy_q, is_note, trim_tail,
                                                  is_prose, quarter_end_before, split_notes)


class QuarterTests(unittest.TestCase):
    def test_quarter_end_before_filing(self):
        self.assertEqual(quarter_end_before("2026-08-12T14:07:34"), "2026-06-30")
        self.assertEqual(quarter_end_before("2026-05-20"), "2026-03-31")
        self.assertEqual(quarter_end_before("2026-01-05"), "2025-12-31")
        self.assertEqual(quarter_end_before("2026-07-01"), "2026-06-30")

    def test_fy_label(self):
        self.assertEqual(fy_q("2026-06-30"), "Q1FY27")
        self.assertEqual(fy_q("2026-03-31"), "Q4FY26")
        self.assertEqual(fy_q("2025-12-31"), "Q3FY26")

    def test_latest_quarter_wins_over_comparatives(self):
        text = ("Statement for the quarter ended June 30, 2026. Quarter ended March 31, 2026 ... "
                "Year ended March 31, 2026 ... year ended 31.03.2026 ... year ended 31st March 2026")
        self.assertEqual(detect_quarter(text, "2026-06-30"), "2026-06-30")

    def test_never_after_filing(self):
        self.assertEqual(detect_quarter("quarter ended 30.09.2026", "2026-06-30"), None)

    def test_annual_results_use_year_ended(self):
        self.assertEqual(detect_quarter("for the year ended 31st March, 2026", "2026-03-31"), "2026-03-31")


class NotesTests(unittest.TestCase):
    def test_headings(self):
        for t in ["Notes:", "NOTES", "Notes to the Statement of Standalone Unaudited Financial Results for the quarter",
                  "Notes forming part of financial results for the quarter ended"]:
            self.assertTrue(NOTES_HEAD.match(t), t)
        self.assertFalse(NOTES_HEAD.match("Notes payable to banks 1,234"))

    def test_note_one_without_heading(self):
        self.assertTrue(NOTE_ONE.match("Note 1: The above"))
        self.assertTrue(NOTE_ONE.match("1. The above results were reviewed"))
        self.assertFalse(NOTE_ONE.match("1. Revenue from operations 1,234"))

    def test_statement_title_not_sentence(self):
        self.assertTrue(STATEMENT.search("Statement of Unaudited Standalone Financial Results for the quarter"))
        self.assertFalse(STATEMENT.search("The above financial results were reviewed by the Audit Committee"))

    def test_split_styles(self):
        self.assertEqual([n for n, _ in split_notes("1. A text\n2. B text\n3 C text")], [1, 2, 3])
        self.assertEqual([n for n, _ in split_notes("1 \nA text\n2 \nB text")], [1, 2])
        self.assertEqual([n for n, _ in split_notes("(i) A text\n(ii) B text\n(iii) C")], [1, 2, 3])
        self.assertEqual([n for n, _ in split_notes("Note 1: A\nNote 2: B")], [1, 2])

    def test_numbering_must_increase(self):
        self.assertEqual([n for n, _ in split_notes("1. A\n12 months ended\n2. B")], [1, 2])

    def test_prose_filter_drops_table_cells(self):
        self.assertFalse(is_prose("(3) \n1.91 \n- \n3.28 \n49.88 \n55.07 \n0.19"))
        self.assertTrue(is_prose("2. Figures of the previous quarter have been regrouped and reclassified to "
                                 "conform to the classification of the current period, wherever necessary."))

    def test_note_number_regex(self):
        self.assertEqual(NOTE_NO.match("12. The Board").group(1), "12")
        self.assertIsNone(NOTE_NO.match("2026 revenue"))






class CleaningTests(unittest.TestCase):
    def test_signature_block_dropped_sentence_end_kept(self):
        block = ("3 The above results were reviewed by the Audit Committee and approved at the meeting held on\n"
                 "February 04, 2026.\n"
                 "For and on behalf of the Board of Directors\n"
                 "Raajhendhran M\n"
                 "Managing Director\n"
                 "DIN: 00123456\n"
                 "Place: Chennai\n"
                 "Digitally signed by RAAJHENDHRAN M\n"
                 "Date: 2026.02.04 18:41:11 +05'30'")
        out = clean_block(block)
        self.assertIn("February 04, 2026.", out)
        for junk in ("behalf", "Raajhendhran", "Managing Director", "DIN", "Place", "Digitally"):
            self.assertNotIn(junk, out)

    def test_table_region_removed_prose_kept(self):
        block = ("4 Other income includes the following items for the periods presented:\n"
                 "Particulars\nQuarter ended\n30.06.2026\n31.03.2026\n"
                 "Dividend income\n1,590.66\n(1,137.81)\n698.90\n"
                 "Interest income\n12.40\n11.02\n9.87\n"
                 "5 Figures of the previous period have been regrouped wherever necessary.")
        out = clean_block(block)
        self.assertNotIn("1,590.66", out)
        self.assertNotIn("Dividend income", out)
        self.assertIn("Other income includes", out)
        self.assertIn("regrouped wherever necessary", out)

    def test_letterhead_line_dropped_however_long(self):
        out = clean_block("6 The results are available on the Company's website and the stock exchanges.\n"
                          "Regd. Office: 39 Kali Krishna Tagore Street, Kolkata 700007, Tel: +91 33 2259 8155, "
                          "E-mail: info@example.com")
        self.assertNotIn("Regd", out)

    def test_auditor_firm_in_a_sentence_is_kept(self):
        line = ("The same has been subjected to limited review by the Joint Statutory Auditors of the Bank M/s Ravi "
                "Rajan & Co LLP, Chartered Accountants, in line with the guidelines issued by the RBI.")
        self.assertIn("Chartered Accountants", clean_block(line))


class SplitTests(unittest.TestCase):
    def test_number_beside_middle_of_paragraph(self):
        block = ("1 The results have been prepared in accordance with Ind AS.\n"
                 "The unaudited consolidated financial results for the quarter have been reviewed by the Audit\n"
                 "2\n"
                 "Committee and subsequently approved by the Board of Directors on February 12, 2026.")
        notes = split_notes(block)
        self.assertEqual([n for n, _ in notes], [1, 2])
        self.assertTrue(notes[1][1].split("\n", 2)[1].startswith("The unaudited consolidated"))

    def test_opening_paragraph_belongs_to_first_number(self):
        block = ("The above unaudited financial results were reviewed by the Audit Committee at the meeting held on\n"
                 "1\n2026. The limited review has been carried out by the Statutory Auditors.\n"
                 "2\nThe results are prepared under Ind AS.")
        notes = split_notes(block)
        self.assertEqual([n for n, _ in notes], [1, 2])
        self.assertIn("The above unaudited", notes[0][1])

    def test_continued_page_starts_mid_numbering(self):
        self.assertEqual([n for n, _ in split_notes("7. A text\n8. B text\n9. C text")], [7, 8, 9])

    def test_ocr_capital_i_as_one(self):
        self.assertEqual([n for n, _ in split_notes("I\nThe above results.\n2\nB text.")], [1, 2])

    def test_roman_subitems_inside_numbered_notes(self):
        block = "12. (i) The award was confirmed.\n(i) Further, the decree is pending.\n13. The branch in Libya."
        self.assertEqual([n for n, _ in split_notes(block)], [12, 13])


class FilterTests(unittest.TestCase):
    def test_narrow_column_note_is_prose(self):
        body = "1\nThe above results\nhave been reviewed\nby the Audit Committee\nand subsequently\napproved\n" \
               "by the Board of Directors\nof the company\nat their respective\nmeetings\nheld on\nFebruary\n5, 2026."
        self.assertTrue(is_note(body))

    def test_auditor_text_and_cover_letter_are_not_notes(self):
        self.assertFalse(is_note("3. We conducted our review of the Statement in accordance with the Standard on "
                                 "Review Engagements (SRE) 2410 issued by the Institute."))
        self.assertFalse(is_note("1. The Audited Financial Results for the quarter and year ended 31st March, 2026 "
                                 "along with the Auditors' Report thereon are enclosed herewith."))

    def test_cash_flow_rows_removed_before_split(self):
        self.assertEqual(clean_block("Purchase of investments measured under amortised cost\n(41,766.89)\n"
                                     "Proceeds from liquidation of investments measured under amortised cost\n"
                                     "41,766.89\n"
                                     "Purchase of other intangible assets and intangible assets under development\n"
                                     "(8.89)"), "")

    def test_trim_tail(self):
        self.assertEqual(trim_tail("5 Figures have been regrouped wherever necessary.\nRaajhendhran M\n1.:."),
                         "5 Figures have been regrouped wherever necessary.")


class BoundaryTests(unittest.TestCase):
    def test_stop_only_at_heading(self):
        body = ("1. The results for the quarter ended on 30th June, 2026 along with the\n"
                "Limited Review Report of the auditors were taken on record by the Board.\n"
                "2. Figures have been regrouped.\n\nLimited Review Report\nTo the Board of Directors")
        cut = _heading_stop(STOP, body)
        self.assertGreater(cut, body.index("2. Figures"))

    def test_basis_single_basis_company(self):
        res = {"has_standalone": 0, "has_consolidated": 0}
        self.assertEqual(block_basis("Notes:", "1. The results were reviewed.", "", res), "standalone")


if __name__ == "__main__":
    unittest.main()
