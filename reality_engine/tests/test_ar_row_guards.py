"""Row clean-up guards: cases taken from the 2026-10-11 LongCat test (tasks/ar_study/free_test/FINDINGS.md)."""
import unittest

from reality_engine.processing import ar_row_guards as g


class UnitGuard(unittest.TestCase):
    def test_crore_table_never_becomes_rupees(self):
        # CONCOR p353 / DABUR p474: model said "rupees" on a crore table
        self.assertEqual(g.guard_unit("crore", "rupees", "Profit / (Loss) for the year Company Limited March 2024 (₹ in crore)")[0], "crore")

    def test_absolute_rupees_accepted_when_header_has_no_scale(self):
        # JKCEMENT p78: remuneration in absolute rupees, parser said lakh
        self.assertEqual(g.guard_unit("lakh", "rupees", "Mr. Ajay Kumar Saraogi Remuneration Paid in ₹ 2022-23")[0], "rupees")

    def test_scale_change_needs_the_scale_in_the_header(self):
        self.assertEqual(g.guard_unit("thousand", "crore", "D Inventories ` cr Balance Sheet")[0], "crore")
        self.assertEqual(g.guard_unit("lakh", "crore", "Balance at the end of the year")[0], "lakh")

    def test_non_currency_unit_needs_evidence(self):
        self.assertEqual(g.guard_unit("lakh", "shares", "Equity Shares outstanding at the end of the year Number")[0], "shares")
        self.assertEqual(g.guard_unit("crore", "tonnes", "Captive fly ash Tonnes")[0], "tonnes")
        self.assertEqual(g.guard_unit("crore", "m3", "Specific water intensity m3/tonne of cement")[0], "m3")
        # ATUL p184: model said count for inventories in crore, nothing supports it
        unit, flag = g.guard_unit("thousand", "count", "D Inventories Balance Sheet (refer Note 9)")
        self.assertEqual(unit, "thousand"); self.assertIn("rejected", flag)

    def test_fresh_round_evidence(self):
        # NAVINFLUOR p146: mutual-fund units under a "Quantity" column; p55: interest coverage ratio in times
        self.assertEqual(g.guard_unit("crore", "count", "-HDFC Overnight Fund As at March 31, 2024 Quantity")[0], "count")
        self.assertEqual(g.guard_unit("%", "times", "Interest Coverage Ratio# Consolidated FY 2022-23")[0], "times")
        # ICICIBANK schedules: "` in ‘000s" with a curly quote
        self.assertEqual(g.guard_unit("million", "thousand", "III. Interest accrued At 31.03.2024 ` in ‘000s")[0], "thousand")


class PeriodGuard(unittest.TestCase):
    def test_year_change_against_header_is_rejected(self):
        # GESHIP p152: header "As at 31/03/2023", model said 2024
        self.assertEqual(g.guard_period("2023-03-31", "2024-03-31", "(K in crores) As at 31/03/2023")[0], "2023-03-31")
        # AXISBANK p416: header gives no year, keep the parser's
        self.assertEqual(g.guard_period("2023-03-31", "2024-03-31", "At cost as on 31st March of the preceding year")[0], "2023-03-31")

    def test_year_change_supported_by_header_is_accepted(self):
        # AXISBANK p409: header says year ended 31-03-2023, parser had 2024
        self.assertEqual(g.guard_period("2024-03-31", "2023-03-31", "crores) (` in Year ended 31-03-2023")[0], "2023-03-31")

    def test_fiscal_ranges(self):
        self.assertEqual(g.fiscal_years("FY 2023-24 Current Financial Year"), {"2024"})
        self.assertEqual(g.fiscal_years("Remuneration Paid in ₹ 2022-23"), {"2023"})


class LabelGuard(unittest.TestCase):
    def test_swapped_label_is_rejected(self):
        self.assertEqual(g.guard_label("Turnover", "Reserves & Surplus")[0], "Turnover")
        self.assertEqual(g.guard_label("Railway Siding", "Building - Details of capital expenditure on enabling assets")[0],
                         "Railway Siding")
        self.assertEqual(g.guard_label("4 Personal loans", "Sub-total (A) - 31 March, 2024 Gross NPAs")[0], "4 Personal loans")
        self.assertEqual(g.guard_label("Other non-financial assets", "Other intangible assets - within 12 months")[0],
                         "Other non-financial assets")

    def test_completed_or_contextualised_label_is_accepted(self):
        self.assertEqual(g.guard_label("rental income Fair valuation of", "Fair valuation of rental income recognised in profit or loss")[0],
                         "Fair valuation of rental income recognised in profit or loss")
        self.assertEqual(g.guard_label("Others", "Other expenses - Others")[0], "Other expenses - Others")
        self.assertEqual(g.guard_label("Balance at the end of the year Note 49: CONTINGENT LIABILITIES AND COMMITMENTS",
                                       "Hedge reserve - Balance at the end of the year")[0], "Hedge reserve - Balance at the end of the year")


class LabelTrim(unittest.TestCase):
    def test_trimmed_label_from_own_words_is_accepted(self):
        # fresh round: SUNPHARMA p215 footer merged into the label; ICICIBANK p286 "Gross NPAs" comes from the column
        self.assertEqual(g.guard_label("TOTAL ASSETS Sun Pharmaceutical Industries Limited | Annual Report 2023-24", "TOTAL ASSETS")[0],
                         "TOTAL ASSETS")
        self.assertEqual(g.guard_label("Total (A)+(B) 1. Represents loans and advances. 2. Excludes commercial business loans",
                                       "Total (A)+(B) Gross NPAs", column="in million, except percentages At March 31, 2023 Gross NPAs1")[0],
                         "Total (A)+(B) Gross NPAs")
        # a word from neither the label nor the column is not a trim
        self.assertEqual(g.guard_label("Turnover", "Turnover Reserves")[0], "Turnover Reserves")   # still passes on overlap
        self.assertEqual(g.guard_label("Railway Siding", "Building")[0], "Railway Siding")


class Apply(unittest.TestCase):
    def test_value_scope_untouched_and_verified_rows_not_dropped(self):
        row = {"label": "Power and fuel", "column": "2022-23", "unit": "crore", "period": "2023-03-31", "value": 312.5,
               "scope": "standalone"}
        out, flags = g.apply(row, {"label": "Other expenses - Power and fuel", "unit": "rupees", "period_end": "2023-03-31",
                                   "scope": "consolidated", "keep": False}, page_header="(₹ in crore)")
        self.assertEqual((out["value"], out["unit"], out["scope"], out["keep"]), (312.5, "crore", "standalone", True))
        self.assertEqual(out["label_clean"], "Other expenses - Power and fuel")
        self.assertTrue(any("drop ignored" in f for f in flags))


if __name__ == "__main__":
    unittest.main()
