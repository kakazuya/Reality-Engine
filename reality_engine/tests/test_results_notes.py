import unittest

from reality_engine.scripts.results_notes import (NOTE_NO, NOTE_ONE, NOTES_HEAD, STATEMENT, detect_quarter, fy_q,
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


if __name__ == "__main__":
    unittest.main()
