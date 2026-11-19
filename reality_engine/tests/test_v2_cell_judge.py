"""T-225 XBRL line-item judge (reality_engine/v2/cell_judge.py)."""
from reality_engine.v2 import cell_judge as cj

LAKH = 1e5
ROWS = [
    # period_end, basis, line_item, value (rupees), scale
    ("2025-12-31", "standalone", "revenue_from_operations", 908_292_000.0, 1.0),
    ("2025-12-31", "standalone", "other_income", 30_796_000.0, 1.0),
    ("2025-12-31", "standalone", "pat", 30_796_000.0, 1.0),          # same figure as other income
    ("2025-12-31", "standalone", "eps_basic", -0.11, 1.0),
    ("2025-12-31", "standalone", "changes_in_inventories", 20_983_000.0, 1.0),
    ("2025-12-31", "consolidated", "revenue_from_operations", 950_000_000.0, 1.0),
]
X = cj.XbrlIndex(ROWS)
TITLE = "STATEMENT OF UN-AUDITED STANDALONE FINANCIAL RESULTS FOR THE QUARTER ENDED 31.12.2025"


def cell(label, value, col="Quarter Ended > 31.12.2025 > Unaudited", unit="₹ in Lakhs", title=TITLE):
    return {"row_label": label, "col_header": col, "value_text": value, "unit_text": unit, "table_title": title}


def test_agree_on_line_quarter_basis():
    v = cj.judge(cell("1 > Revenue from operations", "9,082.92"), X)
    assert (v.verdict, v.line_item, v.period_end, v.basis) == ("agree", "revenue_from_operations", "2025-12-31",
                                                               "standalone")


def test_value_coincidence_on_other_line_is_not_agreement():
    # 307.96 lakh equals both other_income and pat; under the PAT label it agrees only because pat holds it,
    # and under the revenue label it disagrees and names where the value sits
    assert cj.judge(cell("Profit for the period", "307.96"), X).verdict == "agree"
    v = cj.judge(cell("Revenue from operations", "307.96"), X)
    assert v.verdict == "disagree" and v.reason == "value_differs"
    assert v.elsewhere == ["standalone:other_income", "standalone:pat"]


def test_basis_from_title_keeps_consolidated_apart():
    v = cj.judge(cell("Revenue from operations", "9,500.00", title="CONSOLIDATED RESULTS"), X)
    assert v.verdict == "agree" and v.basis == "consolidated"
    assert cj.judge(cell("Revenue from operations", "9,082.92", title="CONSOLIDATED RESULTS"), X).verdict == "disagree"


def test_longer_and_unprinted_period_columns_are_not_judged():
    assert cj.judge(cell("Revenue from operations", "31,278.84", col="Nine-months Ended > 31.12.2025"), X).reason \
        == "nine_month_column"
    # a header that dropped its "Half year ended" level: a mismatch is not called a disagreement
    v = cj.judge(cell("Revenue from operations", "14,971.00", col="31.12.2025 (Unaudited)"), X)
    assert (v.verdict, v.reason) == ("no_xbrl_line", "period_type_unprinted")
    # but an unprinted type that matches the quarter agrees
    assert cj.judge(cell("Revenue from operations", "9,082.92", col="31.12.2025 (Unaudited)"), X).verdict == "agree"
    # "corresponding quarter of the previous year" names a year but is a quarter
    assert cj.column_kind("Corresponding quarter of previous year > 31.12.2024") == "quarter"
    assert cj.column_kind("31.03.2025", "Statement of Financial Results for the Quarter and Year ended") == "unprinted"
    assert cj.column_kind("31.03.2025", "Balance Sheet as at 31 March 2025") == "as_at"


def test_per_share_lines_ignore_money_unit_and_sign_flip_agrees():
    assert cj.judge(cell("Earnings per share > Basic", "(0.11)"), X).verdict == "agree"
    v = cj.judge(cell("b. Changes in Inventories of Work in Progress", "(209.83)"), X)
    assert v.verdict == "agree" and v.sign_flip


def test_no_xbrl_line_reasons():
    assert cj.judge(cell("Segment Revenue > Construction", "9,082.92"), X).reason == "segment_table"
    assert cj.judge(cell("Ratio of something", "1.2"), X).reason == "label_unmapped"
    assert cj.judge(cell("Revenue from operations", "-"), X).reason == "not_a_number"
    assert cj.judge(cell("Revenue from operations", "1.0", col="Quarter Ended > 30.06.2020"), X).reason \
        == "no_xbrl_row"


def test_near_miss_and_column_alarms():
    v = cj.judge(cell("Revenue from operations", "9,100.00"), X)   # 0.19% off
    assert (v.verdict, v.reason) == ("disagree", "near_miss")
    col_ok = "Quarter Ended > 31.12.2025"
    recs = [{"doc_key": "d", "page": 1, "table_title": "t", "col_header": col_ok, "verdict": v, "reason": ""}
            for v in ("agree", "agree", "disagree")]
    recs += [{"doc_key": "d", "page": 1, "table_title": "t", "col_header": "other", "verdict": "disagree",
              "reason": "value_differs"} for _ in range(3)]
    out = cj.mark_alarms(recs)
    assert [r["alarm"] for r in out] == ["", "", "cell", "column", "column", "column"]


def test_period_end_formats():
    assert cj.period_end("Quarter ended > 31-Dec-25 > Unaudited") == "2025-12-31"
    assert cj.period_end("31st December, 2025") == "2025-12-31"
    assert cj.period_end("Dec 31, 2025") == "2025-12-31"
    assert cj.period_end("Quarter Ended (Unaudited) > 30 June 2024") == "2024-06-30"
    assert cj.period_end("Quarter Ended") is None


ANNUAL = [
    # statement, period_type, period_end, basis, line_item, value (rupees), scale
    ("P&L", "FY", "2025-03-31", "standalone", "revenue_from_operations", 3_500_000_000.0, 1.0),
    ("P&L", "H1", "2025-09-30", "standalone", "revenue_from_operations", 1_800_000_000.0, 1.0),
    ("BS", "FY", "2025-03-31", "standalone", "inventories", 120_000_000.0, 1.0),
    ("BS", "FY", "2025-03-31", "standalone", "borrowings_current", 50_000_000.0, 1.0),
    ("BS", "FY", "2025-03-31", "standalone", "borrowings_noncurrent", 80_000_000.0, 1.0),
    ("BS", "FY", "2025-03-31", "standalone", "total_assets", 900_000_000.0, 1.0),
    ("CF", "FY", "2025-03-31", "standalone", "cash_flow_from_operations", 70_000_000.0, 1.0),
    ("CF", "FY", "2025-03-31", "standalone", "cash_generated_from_operations", 90_000_000.0, 1.0),
    ("CF", "FY", "2025-03-31", "standalone", "dividends_paid", 10_000_000.0, 1.0),
]
XA = cj.XbrlIndex(ROWS, ANNUAL)
AR_PL = "STANDALONE STATEMENT OF PROFIT AND LOSS FOR THE YEAR ENDED 31 MARCH 2025"
BS_T = "Standalone Statement of Assets & Liabilities"
CF_T = "Standalone Cash Flow Statement for the year ended 31 March 2025"


def test_year_and_half_columns_use_annual_facts():
    v = cj.judge(cell("Revenue from operations", "35,000.00", col="Year Ended > 31.03.2025 > Audited"), XA)
    assert (v.verdict, v.period_key) == ("agree", "FY")
    v = cj.judge(cell("Revenue from operations", "18,000.00", col="Half Year ended > 30.09.2025"), XA)
    assert (v.verdict, v.period_key) == ("agree", "H1")
    assert cj.judge(cell("Revenue from operations", "18,000.00", col="Year Ended > 31.03.2025"), XA).verdict         == "disagree"
    # an AR P&L column prints only the date; the title names the year
    assert cj.judge(cell("Revenue from operations", "35,000.00", col="31 March 2025", title=AR_PL), XA).verdict         == "agree"


def test_balance_sheet_lines_and_blocks():
    assert cj.bs_lines("2. Current Assets > (a) Inventories") == ("inventories",)
    assert cj.bs_lines("Non-Current Liabilities > (a) Financial Liabilities > (i) Borrowings") ==         ("borrowings_noncurrent",)
    assert cj.bs_lines("(a) Financial Liabilities > (i) Borrowings") == ("borrowings_current", "borrowings_noncurrent")
    assert cj.bs_lines("TOTAL EQUITY AND LIABILITIES") == ("total_assets",)
    assert cj.bs_lines("Other Current Assets") == ()
    v = cj.judge(cell("2. Current Assets > (a) Inventories", "1,200.00", col="As at 31.03.2025 > Audited", title=BS_T),
                 XA)
    assert (v.verdict, v.period_key) == ("agree", "BS")
    # block unprinted: either borrowing line may hold the figure
    assert cj.judge(cell("(a) Financial Liabilities > (i) Borrowings", "800.00", col="As at 31.03.2025", title=BS_T),
                    XA).verdict == "agree"
    v = cj.judge(cell("Current Liabilities > Borrowings", "800.00", col="As at 31.03.2025", title=BS_T), XA)
    assert v.verdict == "disagree" and v.elsewhere == ["standalone:borrowings_noncurrent"]


def test_cash_flow_lines():
    assert cj.cf_line("Cash generated from Operations") == "cash_generated_from_operations"
    assert cj.cf_line("Net Cash Flow from /(used in) Operating Activities (A)") == "cash_flow_from_operations"
    assert cj.cf_line("Repayment of Long Term Borrowings") == "repayment_of_borrowings"
    assert cj.cf_line("Cash flow from operating activities > Dividend Paid") is None   # a financing-only line
    v = cj.judge(cell("Net cash from operating activities", "700.00", col="For the Year ended > 31st March, 2025",
                      title=CF_T), XA)
    assert (v.verdict, v.line_item) == ("agree", "cash_flow_from_operations")
    v = cj.judge(cell("Dividend Paid", "(100.00)", col="31.03.2025", title=CF_T), XA)
    assert v.verdict == "agree" and v.sign_flip
    # a working-capital "Inventories" row of a cash-flow table is never the balance-sheet stock
    assert cj.judge(cell("Inventories", "1,200.00", col="31.03.2025", title=CF_T), XA).reason == "label_unmapped"


def test_adjustments_and_other_entity_tables_are_not_judged():
    assert cj.cf_line("(Profit)/loss on sale of Property, Plant and Equipment") is None
    assert cj.cf_line("Impairment/Write off of Asset held for sale") is None
    assert cj.cf_line("Proceeds from sale of property, plant and equipment") == "sale_of_ppe"
    assert cj.judge(cell("Total Revenue", "254.59", col="Flames Facilities Private Limited > Year ended 31.03.2025",
                         title="A. Subsidiaries"), XA).reason == "other_entity_table"


def test_decimal_point_lost_is_named():
    v = cj.judge(cell("Revenue from operations", "908292"), X)      # 9,082.92 read without its point and comma
    assert (v.verdict, v.reason) == ("disagree", "decimal_lost")
    v = cj.judge(cell("Earnings per share > Basic", "011"), X)        # -0.11 read as "011" (sign lost as well)
    assert (v.verdict, v.reason) == ("disagree", "decimal_lost")


def test_value_of_another_period_names_the_misplaced_column():
    xi = cj.XbrlIndex(ROWS + [("2024-12-31", "standalone", "revenue_from_operations", 802_000_000.0, 1.0)],
                      [("P&L", "FY", "2025-03-31", "standalone", "revenue_from_operations", 3_500_000_000.0, 1.0)])
    # the Q 31.12.2024 figure verified under the 31.12.2025 header (unit unprinted: every scale is tried)
    v = cj.judge(cell("Revenue from operations", "8,020.00", unit=""), xi)
    assert (v.verdict, v.reason) == ("disagree", "other_period")
    assert v.elsewhere[0] == "Q:2024-12-31:standalone:revenue_from_operations"
    assert v.printed == 802_000_000.0                         # shown at the scale that matched
    # a full-year figure under a quarter header
    v = cj.judge(cell("Revenue from operations", "35,000.00"), xi)
    assert v.reason == "other_period" and v.elsewhere == ["FY:2025-03-31:standalone:revenue_from_operations"]
