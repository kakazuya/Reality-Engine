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


# ------------------------------------------------- T-242 AR gates r5 (ckpt_0003: 12 W rows + 3 R counters + unit P)


def _ar_r5_row(**kw):
    base = {
        "record_type": "number", "status": "verified", "status_reason": "", "unit": "", "scale": 1.0,
        "entity_scope": "company", "segment": "", "product": "", "customer": "", "series_title": "",
        "group_path": "", "printed_axis": "", "printed_label": "", "period": "March 31, 2026",
        "basis": "", "new_definition": "", "new_driver_node": "",
    }
    return {**base, **kw}


def test_w3_ambujacem_rpt_other_related_party_and_category_mismatch():
    from reality_engine.v2 import observations as obs
    prev = (
        "Notes to Consolidated Financial Statements as at and for the year ended March 31, 2026\n"
        "Transactions with related party\n"
        "A) Details of transactions relating to other related parties\n"
        "2\nSale of Finished goods and Work-in-progress inventories\n"
        "Adani Cement Industries Limited\n64.99\n211.55\n"
    )
    page = (
        "Notes to Consolidated Financial Statements as at and for the year ended March 31, 2026\n"
        "Ordefence Systems Limited\n0.02\n-\n"
        "3\nSale of Power\nPowerpulse Trading Solutions Limited\n180.77\n12.70\n"
    )
    row_sub = _ar_r5_row(
        measure="NEW:related_party_sale_of_services",
        printed_label="Ordefence Systems Limited",
        value=0.02, value_text="0.02", unit="₹ in crore", scale=1e7,
        period="For the year ended March 31, 2026", basis="consolidated",
        series_title="Notes to Consolidated Financial Statements", entity_scope="subsidiary",
    )
    row_comp = _ar_r5_row(
        measure="NEW:related_party_sale_of_services",
        printed_label="Ordefence Systems Limited",
        value=0.02, value_text="0.02", unit="₹ in crore", scale=1e7,
        period="For the year ended March 31, 2026", basis="consolidated",
        series_title="Notes to Consolidated Financial Statements", entity_scope="company",
    )
    obs.apply_ar_row_gates([row_sub, row_comp], page, "Ambuja Cements Limited", previous_text=prev)
    assert row_sub["entity_scope"] == "company" and row_sub["status"] == "unverified"
    assert row_sub["scope_source"] == "rpt_not_subsidiary" and row_sub["customer"] == "Ordefence Systems Limited"
    assert "ar_rpt_category_mismatch" in row_sub["status_reason"]
    assert row_comp["status"] == "unverified" and "ar_rpt_category_mismatch" in row_comp["status_reason"]


def test_w5_anuras_own_ncd_issuance_is_not_subsidiary():
    from reality_engine.v2 import observations as obs
    page = (
        "Anupam Rasayan India Limited Integrated Report 2025-2026\n"
        "32.4 Material changes and commitments after the closure of the year\n"
        "Issue and Allotment of Non-Convertible Debentures\n"
        "Pursuant to the aforesaid approval, the Company issued and allotted 16,000 (sixteen thousand) NCDs "
        "on May 26, 2026, aggregating to ₹ 160 Crores on a private placement basis to Aditya Birla Capital Limited.\n"
    )
    row = _ar_r5_row(
        measure="NEW:aggregate_value_of_non_convertible_debentures_issued_and_allotted",
        printed_label="aggregating to ₹ 160 Crores", value=160.0, value_text="₹ 160 Crores",
        unit="Crores", scale=1e7, period="May 26, 2026",
        series_title="Issue and Allotment of Non-Convertible Debentures",
        group_path="32.4 Material changes and commitments after the closure of the year",
        customer="Aditya Birla Capital Limited", entity_scope="subsidiary",
    )
    obs.apply_ar_row_gates([row], page, "Anupam Rasayan India Limited")
    assert row["entity_scope"] == "company" and row["status"] == "verified"


def test_w7_abansent_rpt_non_subsidiary_category_not_subsidiary():
    from reality_engine.v2 import observations as obs
    page_code = (
        "Notes forming part of Consolidated Financial Statements for the period ended March 31, 2026\n"
        "Nature of transactions\nRelationship Category\nMarch 31, 2026\nMarch 31, 2025\n"
        "Debt securities issued during the period (as per BENPOS)\n"
        "Abans Investment Managers Limited (Formerly known as Abans\nInvestment Managers Private Limited)\n"
        "5\n4,144.00\n4,403.00\n"
        "Total\n4,735.00\n5,349.00\n"
    )
    row_code = _ar_r5_row(
        measure="NEW:debt_securities_issued",
        printed_label="Abans Investment Managers Limited (Formerly known as Abans Investment Managers Private Limited)",
        value=4403.0, value_text="4,403.00", period="March 31, 2025", basis="consolidated",
        group_path="Debt securities issued during the period (as per BENPOS)", entity_scope="subsidiary",
    )
    page_text_cat = page_code.replace("\n5\n", "\nEnterprises where key management personnel have significant influence\n")
    row_text_cat = dict(row_code)
    obs.apply_ar_row_gates([row_code], page_code, "Abans Enterprises Limited")
    obs.apply_ar_row_gates([row_text_cat], page_text_cat, "Abans Enterprises Limited")
    for r in (row_code, row_text_cat):
        assert r["entity_scope"] == "company" and r["scope_source"] == "rpt_not_subsidiary"
        assert "Abans Investment Managers" in r["customer"] and r["status"] == "verified"


def test_w10_accelya_currency_slice_under_canonical_measure():
    from reality_engine.v2 import observations as obs
    page = (
        "Accelya Solutions India Limited 40th Annual Report 2025-26\n"
        "In INR lakhs:\nEURO\nGBP\nUSD\nSGD\nCAD\n"
        "As at 30 June 2025\nEEFC accounts\n0.01\n0.01\n0.01\n-\n-\n"
    )
    row = _ar_r5_row(
        measure="NEW:eefc_accounts", printed_label="EEFC accounts",
        printed_axis="USD", group_path="As at 30 June 2025",
        value=0.01, value_text="0.01", unit="INR lakhs", scale=1e5,
        period="As at 30 June 2025", basis="standalone",
    )
    obs.apply_ar_row_gates([row], page, "Accelya Solutions India Limited")
    assert row["status"] == "unverified" and "ar_subset_as_total" in row["status_reason"]


def test_w21_archidply_raw_material_item_subset_as_total():
    from reality_engine.v2 import observations as obs
    page = (
        "Notes to Consolidated Financial Statement for the year ended 31st March 2026\n"
        "Break up of Raw Materials Consumed\nYear Ended 31.03.2026\nYear Ended 31.03.2025\n"
        "Paper in Kgs\n93,34,823\n5,555.21\n81,37,311\n4,652.09\n"
        "Chemicals in Kgs\n1,99,42,687\n6,729.57\n1,64,62,376\n5,499.65\n"
        "Others\n314.40\n875.06\n3,15,97,413\n21,087.18\n2,68,35,524\n19,070.11\n"
    )
    row = _ar_r5_row(
        measure="raw_material_cost", printed_label="Chemicals in Kgs",
        value=5499.65, value_text="5,499.65", unit="Lakhs", scale=1e5,
        period="Year Ended 31.03.2025", basis="consolidated",
    )
    obs.apply_ar_row_gates([row], page, "Archidply Industries Limited")
    assert row["status"] == "unverified" and "ar_subset_as_total" in row["status_reason"]


def test_w25_abdl_subsidiary_loan_subset_as_total():
    from reality_engine.v2 import observations as obs
    page = (
        "Allied Blenders and Distillers Limited\n"
        "for the year ended 31 March 2026 (` in lakhs, except for share data and, if otherwise stated)\n"
        "Particulars\nSubsidiaries\n31 March 2026\n31 March 2025\n"
        "Unsecured loan / advances granted\n"
        "Deccan Star Distilleries India Private Limited\n1.09\n2.00\n"
        "Sub-total\n130.85\n32.36\n"
    )
    row = _ar_r5_row(
        measure="loans", printed_label="Deccan Star Distilleries India Private Limited",
        value=1.09, value_text="1.09", unit="₹ in lakhs", scale=1e5,
        period="31 March 2026", basis="standalone", entity_scope="subsidiary",
    )
    obs.apply_ar_row_gates([row], page, "Allied Blenders and Distillers Limited")
    assert row["status"] == "unverified" and "ar_subset_as_total" in row["status_reason"]


def test_w39_arssinfra_other_equity_grand_total_never_maps_to_one_reserve():
    from reality_engine.v2 import observations as obs
    page = (
        "Notes to the Standalone Financial Statements for the year ended 31st March, 2026\n"
        "ARSS Infrastructure Projects Limited\n(` in lakhs)\n"
        "Particulars\nAs at March 31, 2026\nAs at March 31, 2025\n"
        "c. Retained Earnings\nSub Total\n(3,94,824.39)\n(39,326.35)\n"
        "d. Capital Reserve\nSub Total\n1,061.95\n-\n"
        "Grand Total\n86,956.30\n(18,652.35)\n"
    )
    row = _ar_r5_row(
        measure="NEW:retained_earnings_and_capital_reserve_grand_total",
        printed_label="Grand Total", value=-18652.35, value_text="(18,652.35)",
        unit="` in lakhs", scale=1e5, period="As at March 31, 2025", basis="standalone",
        new_definition="Retained earnings and capital reserve grand total", new_driver_node="equity",
    )
    obs.apply_ar_row_gates([row], page, "ARSSINFRA")
    assert row["status"] == "unverified" and "ar_subset_as_total" in row["status_reason"]


def test_w42_abb_cwip_project_subset_as_total():
    from reality_engine.v2 import observations as obs
    page = (
        "ABB India Limited | Integrated Annual Report 2025\n(₹ in Crores)\n"
        "To be completed in\nTotal\nLess than 1 year\n"
        "Peenya\n4.65\n4.65\n"
        "Nelamangala\n17.07\n17.07\n"
        "As at December 31, 2024\n21.72\n21.72\n"
    )
    row = _ar_r5_row(
        measure="capital_work_in_progress", printed_label="Nelamangala",
        printed_axis="Less than 1 year", value=17.07, value_text="17.07",
        unit="Crores", scale=1e7, period="As at December 31, 2024",
    )
    obs.apply_ar_row_gates([row], page, "ABB India Limited")
    assert row["status"] == "unverified" and "ar_subset_as_total" in row["status_reason"]


def test_w43_aci_period_from_non_period_text_column_is_unverified():
    from reality_engine.v2 import observations as obs
    page = (
        "Notes Forming Part of Consolidated Financial Statements For the Year Ended March 31, 2026\n"
        "Note 37.1 (a) Details of disputed statutory dues\n"
        "Name of Statute\nPeriod to which amounts relates\nForum where dispute is pending\n"
        "As at March 31, 2026\nAs at March 31, 2025\n"
        "Income tax matters in respect of which Group is in appeal#\n"
        "FY 2021-22\nITAT\n5,005.30\n5,005.30\n"
    )
    row = _ar_r5_row(
        measure="NEW:disputed_statutory_dues",
        printed_label="Income tax matters in respect of which Group is in appeal#",
        printed_axis="As at March 31, 2026", value=5005.3, value_text="5,005.30",
        unit="Rupees in Lakhs", scale=1e5, period="FY 2021-22", basis="consolidated",
    )
    obs.apply_ar_row_gates([row], page, "Archean Chemical Industries Limited")
    assert row["status"] == "unverified" and "ar_period_from_text_column" in row["status_reason"]


def test_w47_ahleast_other_entity_bound_statements():
    from reality_engine.v2 import observations as obs
    prev = (
        "127\nNotes to the Financial Statements for the year ended March 31, 2026\n"
        "Financial Statements\nStatutory Reports\nGJS Hotels Limited\n5. INVESTMENTS\n"
    )
    page = (
        "128\nNotes to the Financial Statements for the year ended March 31, 2026\n19th Annual Report 2025-26\n"
        "Amount in Thousands\nParticulars\nAs at 31.03.2026\nAs at 31.03.2025\n"
        "Asian Hotels (East) Limited, the Holding Company and its Nominees\n4,918,116\n49,181.16\n"
    )
    row_with_prev = _ar_r5_row(
        measure="count.shares", printed_label="Asian Hotels (East) Limited",
        value=4918116.0, value_text="4,918,116", period="As at 31.03.2026",
    )
    row_no_prev = dict(row_with_prev)
    obs.apply_ar_row_gates([row_with_prev], page, "Asian Hotels (East) Limited", previous_text=prev)
    obs.apply_ar_row_gates([row_no_prev], page, "Asian Hotels (East) Limited")
    assert row_with_prev["entity_scope"] == "subsidiary" and row_with_prev["segment"] == "GJS Hotels Limited"
    assert row_with_prev["status"] == "unverified" and "ar_other_entity" in row_with_prev["status_reason"]
    assert row_no_prev["entity_scope"] == "subsidiary" and row_no_prev["status"] == "unverified"
    assert "ar_other_entity" in row_no_prev["status_reason"]


def test_w48_abfrl_authorised_shares_rewritten_from_count_shares():
    from reality_engine.v2 import observations as obs
    page = (
        "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS FOR THE YEAR ENDED MARCH 31, 2026\n"
        "NOTE 21 : EQUITY SHARE CAPITAL\nAuthorised share capital\nEquity share capital\n"
        "As at the end of the year\n2,03,60,00,000\n2,036.00\n"
    )
    row = _ar_r5_row(
        measure="count.shares", printed_label="As at the end of the year",
        series_title="NOTE 21 : EQUITY SHARE CAPITAL > Authorised share capital > Equity share capital",
        group_path="Authorised share capital > Equity share capital",
        value=2036000000.0, value_text="2,03,60,00,000", unit="No. of shares",
        period="As at March 31, 2025", basis="consolidated",
    )
    obs.apply_ar_row_gates([row], page, "Aditya Birla Fashion and Retail Limited")
    assert row["measure"] == "NEW:authorised_shares" and row["new_driver_node"] == "equity"


def test_w59_bmwentltd_wide_table_misaligned_is_unverified():
    from reality_engine.v2 import observations as obs
    page = (
        "BMW VENTURES LIMITED\nNotes to the financial statements (continued)\n(Rs in lakhs)\n"
        "4 Property, plant and equipment\n"
        "Balance as at 01 April 2025\n"
        "210.00\n1,145.63\n7,596.60\n2,753.75\n176.76\n206.22\n534.90\n395.71\n199.14\n143.05\n894.71\n14,256.46\n66.62\n"
        "Add : Additions\n"
        "103.15\n189.65\n785.65\n-\n5.70\n202.99\n45.58\n16.12\n2.76\n-\n1,351.61\n3.50\n"
        "Less : Disposals/Transfer\n"
        "(1,248.78)\n(43.00)\n(25.71)\n(1,317.49)\n"
    )
    row = _ar_r5_row(
        measure="NEW:gross_block_equipments_for_rental", printed_label="Balance as at 01 April 2025",
        printed_axis="Equipments for Rental", group_path="Gross block",
        value=894.71, value_text="894.71", unit="Rs in lakhs", scale=1e5, period="01 April 2025",
    )
    obs.apply_ar_row_gates([row], page, "BMW Ventures Limited")
    assert row["status"] == "unverified" and "ar_wide_table_misaligned" in row["status_reason"]


def test_r_counter_13_18_55_related_party_subsidiaries_stay_verified():
    from reality_engine.v2 import observations as obs
    # R #13 360ONE: printed Nature of relationship = Subsidiary
    p13 = (
        "NOTES forming part of Standalone Financial Statements for the year ended March 31, 2026\n"
        "(B) Disclosure of Related Party transactions (` in crore)\n"
        "Sr no\nNature of transations\nNature of relationship\nFor the year ended March 31, 2026\nFor the year ended March 31, 2025\n"
        "6\nInter corporate deposit (ICD) taken repaid\n"
        "360 ONE Distribution Services Limited\nSubsidiary\n-\n25.00\n"
    )
    r13 = _ar_r5_row(
        measure="NEW:inter_corporate_deposit_taken_repaid",
        printed_label="360 ONE Distribution Services Limited", value=25.0, value_text="25.00",
        unit="crore", scale=1e7, period="March 31, 2025", basis="standalone",
        series_title="(B) Disclosure of Related Party transactions",
        group_path="Inter corporate deposit (ICD) taken repaid", entity_scope="subsidiary",
    )
    # R #18 ATLANTAA: printed Relationship = Stepdown Subsidiary Company
    p18 = (
        "Atlantaa Limited Notes to the Consolidated financial statements as of and for the period ended March 31, 2026\n"
        "(` in Lakhs)\nName of the Related Party / Entity\nRelationship\n31-Mar-26\n31-Mar-25\nNature of Transaction\n"
        "MORA Tollways Limited\nStepdown Subsidiary Company\nMisc advances/reimbursements paid by the company\n12.22\n"
    )
    r18 = _ar_r5_row(
        measure="NEW:miscellaneous_advances_reimbursements_paid_by_company",
        printed_label="MORA Tollways Limited", value=12.22, value_text="12.22",
        unit="₹ in Lakhs", scale=1e5, period="31-Mar-25", basis="consolidated",
        customer="MORA Tollways Limited", entity_scope="subsidiary",
    )
    # R #55 AMAGI: previous page names Step-down subsidiaries directory
    prev55 = (
        "Notes to Standalone Financial Statements for the year ended March 31, 2026\n"
        "33. Related party disclosures (a) Names of related parties and related party relationship\n"
        "Step-down subsidiaries : Amagi Media UK Private Limited, UK*\n"
        "Amagi Eastern Europe d.o.o. za usluge, Croatia*\n"
    )
    p55 = (
        "Notes to Standalone Financial Statements for the year ended March 31, 2026\n"
        "(All amounts in Indian Rupees million, unless otherwise stated)\n"
        "For the year ended March 31, 2026\nFor the year ended March 31, 2025\n"
        "Employee stock compensation and SARs expense cross charged to\n"
        "Amagi Eastern Europe d.o.o. za usluge, Croatia\n13.16\n13.00\n"
    )
    r55 = _ar_r5_row(
        measure="NEW:employee_stock_compensation_and_sars_expense_cross_charged_to",
        printed_label="Amagi Eastern Europe d.o.o. za usluge, Croatia",
        value=13.16, value_text="13.16", unit="Indian Rupees million", scale=1e6,
        period="For the year ended March 31, 2026", basis="standalone",
        series_title="(b) The transactions that have been entered into with the related parties during the year are as follows:",
        group_path="Employee stock compensation and SARs expense cross charged to",
        customer="Amagi Eastern Europe d.o.o. za usluge", entity_scope="subsidiary",
    )
    obs.apply_ar_row_gates([r13], p13, "360 ONE WAM LIMITED")
    obs.apply_ar_row_gates([r18], p18, "ATLANTAA LIMITED")
    obs.apply_ar_row_gates([r55], p55, "Amagi Media Labs Limited", previous_text=prev55)
    for r in (r13, r18, r55):
        assert (r["entity_scope"], r["status"]) == ("subsidiary", "verified"), (r["printed_label"], r["status_reason"])


def test_p_units_hundreds_thousands_and_facing_page_carried():
    from reality_engine.v2 import observations as obs
    r19 = _ar_r5_row(
        measure="NEW:securities_premium_reserve_balance", printed_label="Balance as at 31st March, 2024",
        value=1270622.0, value_text="1270622.00", unit="Rs in Hundreds", scale=1.0, period="31st March, 2024",
    )
    obs.apply_ar_row_gates([r19], "Rs in Hundreds\nBalance as at 31st March, 2024 1270622.00", "Aravali Securities & Finance Ltd")
    assert r19["scale"] == 100.0 and r19["status"] == "verified"

    r46 = _ar_r5_row(
        measure="NEW:allowance_for_doubtful_debts", printed_label="Less: Allowance for doubtful debts",
        value=0.0, value_text="0.00", period="2025-2026",
    )
    obs.apply_ar_row_gates(
        [r46],
        "Notes forming part of the financial statements as at and for the year ended March 31, 2026\n"
        "(All amounts are in thousands, except share and per share data, unless otherwise stated)\n2025-2026",
        "Ad-Manum Finance Ltd",
    )
    assert (r46["unit"], r46["scale"], r46["status"]) == ("Thousands", 1e3, "verified")

    r14 = _ar_r5_row(
        measure="NEW:total_foreign_currency_earnings", printed_label="TOTAL",
        series_title="Note No 28: The Details of Foreign Currency Earnings and Expenditure incurred by the Company are as under:",
        group_path="Earnings in Foreign Currency",
        value=229.86, value_text="229.86", period="31 March 2025",
    )
    obs.apply_ar_row_gates(
        [r14], "Note No 28: Earnings in Foreign Currency TOTAL 229.86 31 March 2025", "Aegeus Technologies Ltd",
        previous_text="(All Amounts in Indian Rupees (₹) (in Lakhs) unless otherwise stated)",
    )
    assert (r14["unit"], r14["scale"], r14["status"]) == ("Lakhs", 1e5, "verified")


# ------------------------------------------------- T-242 AR gates r6 (narrow ar_rpt_not_subsidiary & ar_other_entity)


def test_r6_rpt_company_associate_jv_transactions_and_lt_subsidiaries_including_stay_verified():
    from reality_engine.v2 import observations as obs
    # ACC: company RPT with Adani Enterprises under "other related parties" (both pre-company & counterparty-sub)
    p_acc = (
        "Notes to Consolidated financial statements for the year ended March 31, 2026\n"
        "Related Party Disclosures\n(I) Details of Transactions relating to other related parties\n"
        "Receipt of services\nAdani Enterprises Limited (Corporate cost allocation)\n91.02\n53.19\n"
    )
    for sc in ("company", "subsidiary"):
        r_acc = _ar_r5_row(
            measure="NEW:related_party_receipt_of_services",
            printed_label="Adani Enterprises Limited (Corporate cost allocation)",
            value=91.02, value_text="91.02", unit="Crores", scale=1e7,
            customer="Adani Enterprises Limited", entity_scope=sc, basis="consolidated",
        )
        obs.apply_ar_row_gates([r_acc], p_acc, "ACC Limited")
        assert (r_acc["entity_scope"], r_acc["status"]) == ("company", "verified")

    # AGL (Contech 12), A2ZINFRA (Mansi 12.91), ADVENTHTL (Bamboo loans 10,176.47), AFSL (Abans Metals (1,753.90))
    p_agl = (
        "Notes to Financial Statements for the year ended March 31, 2026\n27. Related party disclosures\n"
        "Joint Venture\nContech Logistics Solutions Private Limited\nBusiness support income\n12\n-\n"
    )
    r_agl = _ar_r5_row(
        measure="NEW:business_support_income", printed_label="Contech Logistics Solutions Private Limited",
        value=12.0, value_text="12", unit="Lakhs", scale=1e5, entity_scope="subsidiary",
    )
    obs.apply_ar_row_gates([r_agl], p_agl, "Allcargo Global Limited")
    assert (r_agl["entity_scope"], r_agl["status"]) == ("company", "verified")

    p_a2z = (
        "Notes to Standalone Financial Statements for the year ended March 31, 2026\n"
        "B. Transactions with related parties\nAssociates\n"
        "- Mansi Bijlee & Rice Mills Limited\n14.77\n12.91\n"
    )
    r_a2z = _ar_r5_row(
        measure="NEW:fund_transferred_expenses_incurred_on_behalf_of_related_party",
        printed_label="- Mansi Bijlee & Rice Mills Limited", value=12.91, value_text="12.91",
        unit="Lakhs", scale=1e5, entity_scope="subsidiary", basis="standalone",
    )
    obs.apply_ar_row_gates([r_a2z], p_a2z, "A2Z Infra Engineering Limited")
    assert (r_a2z["entity_scope"], r_a2z["status"]) == ("company", "verified")

    p_adv = (
        "Notes to Consolidated Financial Statements for the year ended March 31, 2026\n"
        "Disclosure in Respect of Major Related Party Balances\nJoint Venture\n"
        "Bamboo Hotel and Global Centre (Delhi) Private Limited\n10,176.47\n"
    )
    r_adv = _ar_r5_row(
        measure="NEW:loans_granted_net_related_party",
        printed_label="Bamboo Hotel and Global Centre (Delhi) Private Limited",
        value=10176.47, value_text="10,176.47", unit="Lakhs", scale=1e5,
        customer="Bamboo Hotel and Global Centre (Delhi) Private Limited", entity_scope="subsidiary",
    )
    obs.apply_ar_row_gates([r_adv], p_adv, "Advent Hotels International Limited")
    assert (r_adv["entity_scope"], r_adv["status"]) == ("company", "verified")

    p_afsl = (
        "Notes to the Consolidated Financial Statements for the year ended March 31, 2026\n"
        "Related party transactions\nRelationship\nMarch 31, 2026\nMarch 31, 2025\n"
        "Abans Metals Private Limited\n4\n(1,753.90)\n(1,726.79)\n"
    )
    r_afsl = _ar_r5_row(
        measure="NEW:net_loans_given_or_received_back", printed_label="Abans Metals Private Limited",
        value=-1753.90, value_text="(1,753.90)", unit="Lakhs", scale=1e5,
        entity_scope="subsidiary", basis="consolidated",
    )
    obs.apply_ar_row_gates([r_afsl], p_afsl, "Abans Financial Services Limited")
    assert (r_afsl["entity_scope"], r_afsl["customer"], r_afsl["status"]) == (
        "company", "Abans Metals Private Limited", "verified"
    )

    # LT p574: "Subsidiaries, including:" below "Joint venture:" decides nearest heading -> stays subsidiary + verified
    p_lt = (
        "Disclosure of related parties/related party transactions pursuant to Ind AS 24\n"
        "As at 31-3-2026\nAs at 31-3-2025\n"
        "₹ crore\nvi.\nImpairment loss on loans & advances recoverable\nJoint venture:\n"
        "Raykal Aluminium Company Private Limited\n0.89\n0.88\n"
        "vii.\nUnsecured loans taken (including lease finance)\nSubsidiaries, including:\n825.05\n456.70\n"
        "L&T Construction Equipment Limited\n77.75\n70.50\n"
    )
    r_lt = _ar_r5_row(
        measure="NEW:unsecured_loans_taken_including_lease_finance",
        printed_label="L&T Construction Equipment Limited", value=70.50, value_text="70.50",
        unit="crore", scale=1e7, period="31-3-2025", entity_scope="subsidiary",
    )
    obs.apply_ar_row_gates([r_lt], p_lt, "Larsen & Toubro Limited")
    assert (r_lt["entity_scope"], r_lt["status"]) == ("subsidiary", "verified")


def test_r6_other_entity_narrowed_to_statement_headings_and_keeps_own_capital_governance_and_7nr():
    from reality_engine.v2 import observations as obs
    # AMBALALSA share capital / capital management with earlier RPT/subsidiary page
    prev_rpt = (
        "Ambalal Sarabhai Enterprises Limited\nNotes to the Standalone Financial Statements for the year ended March 31, 2026\n"
        "Related Party Disclosures\nSystronics India Limited\n"
    )
    p_amb = (
        "CIN : L52100GJ1978PLC003159\nNotes to the Standalone Financial Statements for the year ended March 31, 2026\n"
        "(` in Lakhs)\nNote 37 : Capital management\nEquity share capital\n7,663.33\n7,663.33\n"
    )
    r_amb = _ar_r5_row(
        measure="equity_share_capital", printed_label="Equity share capital",
        value=7663.33, value_text="7,663.33", unit="Lakhs", scale=1e5, basis="standalone",
    )
    obs.apply_ar_row_gates([r_amb], p_amb, "Ambalal Sarabhai Enterprises Limited", previous_text=prev_rpt)
    assert (r_amb["entity_scope"], r_amb["segment"], r_amb["status"]) == ("company", "", "verified")

    # PERSISTENT investments page naming Altizon
    p_per = (
        "Notes to the Financial Statements for the year ended March 31, 2026\n"
        "Note 6: Investments\nParticulars\nAltizon Systems Private Limited\n10.50\n"
    )
    r_per = _ar_r5_row(measure="NEW:non_current_investments_other", printed_label="Altizon Systems Private Limited",
                       value=10.50, value_text="10.50", unit="Millions", scale=1e6)
    obs.apply_ar_row_gates([r_per], p_per, "Persistent Systems Limited")
    assert (r_per["entity_scope"], r_per["status"]) == ("company", "verified")

    # AIAENG CSR page with Form AOC-1 (VEGA MPS PTY LIMITED) before it
    p_aoc = "Annual Report 2025-26\nFORM NO. AOC-1\nPart - A : Subsidiaries\nVEGA MPS PTY LIMITED\n"
    p_csr = (
        "Corporate Governance Report\nFor the year ended March 31, 2026\nCSR Committee Meetings Held\n"
        "Notes to Financial Statements reference\n* Mr. Rajan R. Harivallabhdas\n2\n2\n"
    )
    r_aia = _ar_r5_row(measure="NEW:csr_committee_meetings_held", printed_label="* Mr. Rajan R. Harivallabhdas",
                       value=2.0, value_text="2")
    obs.apply_ar_row_gates([r_aia], p_csr, "AIA Engineering Limited", previous_text=p_aoc)
    assert (r_aia["entity_scope"], r_aia["status"]) == ("company", "verified"), r_aia["status_reason"]

    # ASIANTILES board attendance page & (v) KMP enterprise page with nav tabs
    p_asi = (
        "Annual Report 2025-26 253\nMarch 31, 2026\nStatutory Reports\nFinancial Statements\nCorporate Overview\n"
        "(v) Enterprises over which KMP and/or their relatives having significant influence\n"
        "Affil Vitrified Private Limited\nAmaxo Granite\n(c) Compensation of key management personnel\n(` in Lakhs)\n"
        "Board meetings held during tenure\n6\n"
    )
    r_asi = _ar_r5_row(measure="NEW:board_meetings_attended_during_tenure", printed_label="Mr. Bhaveshkumar Patel",
                       value=6.0, value_text="6")
    obs.apply_ar_row_gates([r_asi], p_asi, "Asian Granito India Limited")
    assert (r_asi["entity_scope"], r_asi["status"]) == ("company", "verified"), r_asi["status_reason"]

    # 7NR 'Limited' vs 'Ltd' and Annexure to Auditors' Report 'to the members of 7NR Retail Limited'
    p_7nr = (
        "Annexure A to Auditors' Report\nReferred to in paragraph 1\n"
        "to the members of 7NR Retail Limited on the standalone financial statements for the year ended March 31, 2026\n"
        "(Rupees in Lakhs)\nAggregate amount of Loans repayable on demand\n1,121.84\n"
    )
    r_7nr = _ar_r5_row(measure="NEW:aggregate_loans_repayable_on_demand", printed_label="Aggregate amount of Loans",
                       value=1121.84, value_text="1,121.84", unit="Rupees in Lakhs", scale=1e5, basis="standalone")
    obs.apply_ar_row_gates([r_7nr], p_7nr, "7NR Retail Ltd")
    assert (r_7nr["entity_scope"], r_7nr["segment"], r_7nr["status"]) == ("company", "", "verified")

    # Explicit other-entity statement heading still flags ar_other_entity
    p_sub_stmt = (
        "Financial Statements of GJS Hotels Limited\nBalance Sheet as at March 31, 2026\n"
        "(Rupees in Lakhs)\nTotal Assets\n4,500.00\n"
    )
    r_sub_stmt = _ar_r5_row(measure="total_assets", printed_label="Total Assets", value=4500.0, value_text="4,500.00",
                            unit="Lakhs", scale=1e5, period="As at March 31, 2026")
    obs.apply_ar_row_gates([r_sub_stmt], p_sub_stmt, "Asian Hotels (East) Limited")
    assert r_sub_stmt["entity_scope"] == "subsidiary" and r_sub_stmt["segment"] == "GJS Hotels Limited"
    assert r_sub_stmt["status"] == "unverified" and "ar_other_entity" in r_sub_stmt["status_reason"]


