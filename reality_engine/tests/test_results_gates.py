"""T-242: results-page number gates (junk references, entity scope, holding/fragment values, unit line)."""
from reality_engine.v2 import observations as obs


def row(**kw):
    base = {"record_type": "number", "measure": "revenue_from_operations", "printed_label": "Revenue",
            "printed_axis": "", "series_title": "", "group_path": "", "value_text": "100.00", "value": 100.0,
            "unit": "lakhs", "unit_family": "money", "scale": 100000.0, "period": "Year ended March 31, 2026",
            "entity_scope": "company", "status": "verified", "status_reason": "", "segment": ""}
    base.update(kw)
    return base


# 1. junk numbers -> quarantined (not a figure)
def test_year_in_a_date_or_a_reference_is_quarantined():
    circular = row(measure="NEW:circular_date_year", printed_label="dated March 29, 2019 ('the Circular')",
                   value_text="2019", value=2019.0, unit="", unit_family="", scale=1.0,
                   period="March 29, 2019")
    act = row(measure="NEW:statutory_reference_year", printed_label="Companies Act,",
              value_text="2013", value=2013.0, unit="", unit_family="", scale=1.0, period="March31")
    term = row(measure="NEW:appointment_term_duration", printed_label="Term of appointment",
               value_text="2032", value=2032.0, unit="", unit_family="", scale=1.0,
               period="26th May, 2032")
    rows = [circular, act, term]
    obs.apply_results_row_gates(rows, "")
    assert [r["status"] for r in rows] == ["quarantined"] * 3
    assert all("results_not_a_figure" in r["status_reason"] for r in rows)


def test_section_rule_scrip_code_and_time_are_quarantined():
    section = row(measure="NEW:regulatory_section_reference", printed_label="Section 133 of the Companies Act",
                  value_text="133", value=133.0, unit="", unit_family="", scale=1.0)
    rule = row(measure="NEW:regulatory_rule_number",
               printed_label="read with rule 3 of the Companies (Indian Accounting Standards) Rules, 2015",
               value_text="3", value=3.0, unit="", unit_family="", scale=1.0)
    scrip = row(measure="NEW:regulatory_reference_number", printed_label="Scrip Code:",
                value_text="509675", value=509675.0, unit="", unit_family="", scale=1.0)
    time_row = row(measure="NEW:board_meeting_time", printed_label="The Board Meeting was commenced at",
                   value_text="12:45 P.M", value=12.0, unit="", unit_family="", scale=1.0)
    rows = [section, rule, scrip, time_row]
    obs.apply_results_row_gates(rows, "")
    assert [r["status"] for r in rows] == ["quarantined"] * 4


def test_a_date_used_as_the_value_is_quarantined_and_not_given_a_unit():
    dated = row(measure="NEW:report_quarter_end_date", printed_label="Report filed for quarter ended",
                value_text="30-Sep-2026", value=30.0, unit="", unit_family="", scale=1.0)
    obs.apply_results_row_gates([dated], "Figures in Crores")
    assert dated["status"] == "quarantined" and "is a date" in dated["status_reason"]
    assert dated["unit"] == "" and dated["scale"] == 1.0


def test_condition_percent_echo_is_quarantined_while_a_share_measure_is_kept():
    echo = row(measure="NEW:consideration_received_on_warrant_allotment",
               printed_label="upon receipt of 25% of the issue price", value_text="25%", value=25.0,
               unit="%", unit_family="percent", scale=1.0)
    rnd = row(measure="rnd.share", printed_label="at 5.0% of total revenue from operations",
              value_text="5.0%", value=5.0, unit="%", unit_family="percent", scale=1.0)
    rows = [echo, rnd]
    obs.apply_results_row_gates(rows, "")
    assert echo["status"] == "quarantined" and "results_not_a_figure" in echo["status_reason"]
    assert rnd["status"] == "verified" and not rnd["status_reason"]


def test_a_printed_growth_percent_is_kept():
    growth = row(measure="profit_before_exceptional_items_and_tax",
                 printed_label="significant increase of 40.7% in our profit before tax and exceptional items",
                 value_text="40.7%", value=40.7, unit="%", unit_family="percent", scale=1.0)
    obs.apply_results_row_gates([growth], "")
    assert growth["status"] == "verified"


def test_a_year_value_with_its_unit_is_a_real_figure():
    kept = row(measure="revenue_from_operations", printed_label="Revenue from operations", value_text="2019",
               value=2019.0, unit="lakhs", unit_family="money", scale=100000.0, period="Year ended March 31, 2025")
    obs.apply_results_row_gates([kept], "")
    assert kept["status"] == "verified"


# 2. entity scope: the company's own statement is company; an associate's figure needs its line
ARSSBL_HEAD = ("ANAND RATHI SHARE AND STOCK BROKERS UMITED\nCIN : L67120MH1991PLC064106\n"
               "CONSOUDATED CASH FLOW STATEMENT FOR THE YEAR ENDED MARCH 31, 2026\n")


def test_own_cash_flow_page_resets_a_wrong_subsidiary_tag():
    cash = row(measure="NEW:changes_in_loans_cash_flow", printed_label="(Increase)/Decrease in Loans",
               series_title="CONSOLIDATED CASH FLOW STATEMENT FOR THE YEAR ENDED MARCH 31, 2026",
               value_text="(4,164.17)", value=-4164.17, unit="₹ in Millions", scale=1000000.0,
               entity_scope="subsidiary", basis="consolidated")
    obs.apply_results_row_gates([cash], ARSSBL_HEAD, company="Anand Rathi Share and Stock Brokers Limited")
    assert cash["entity_scope"] == "company" and cash["status"] == "verified"


def test_a_page_that_does_not_name_the_company_keeps_its_scope():
    other = row(measure="total_comprehensive_income", printed_label="total comprehensive income/(loss)",
                series_title="7. The accompanying Statement includes the unaudited interim financial results",
                value_text="Rs. 0 million", value=0.0, unit="million", scale=1000000.0,
                entity_scope="subsidiary")
    obs.apply_results_row_gates([other], "S.R. BATLIBOI & ASSOCIATES LLP\nChartered Accountants\n2 subsidiaries ...",
                                company="Bosch Limited")
    assert other["entity_scope"] == "subsidiary" and other["status"] == "verified"


def test_associate_figure_is_unverified_unless_its_label_names_the_associate():
    associate = row(measure="pat", printed_label="net profit after tax", value_text="91.66", value=91.66,
                    unit="lacs", unit_family="money", scale=100000.0, entity_scope="subsidiary",
                    group_path="The Statement includes the interim financial information of one Associate")
    own_line = row(measure="share_of_profit_of_associates", printed_label="Share of profit of associates",
                   value_text="8.40", value=8.4, group_path="Associates' financial information")
    rows = [associate, own_line]
    obs.apply_results_row_gates(rows, "")
    assert associate["status"] == "unverified" and "results_associate_figure" in associate["status_reason"]
    assert own_line["status"] == "verified"


# 3. a holding count is not the company's share count; a fragment is not the printed figure
def test_holding_in_another_company_is_not_the_companys_share_count():
    holding = row(measure="count.shares", printed_label="equity shares", value_text="2,60,000", value=260000.0,
                  unit="equity shares", unit_family="", scale=1.0, entity_scope="subsidiary")
    page = ("The Company held a 19.87% equity stake in Ashika Capital Ltd (ACL), comprising "
            "2,60,000 equity shares as on March 31, 2026.")
    obs.apply_results_row_gates([holding], page)
    assert holding["status"] == "unverified" and "results_holding_count" in holding["status_reason"]


def test_value_that_is_the_start_of_the_printed_figure_is_unverified():
    fragment = row(measure="profit_before_exceptional_items_and_tax",
                   printed_label="Net Profit before tax and exceptional items", value_text="5", value=5.0,
                   unit="Crores", unit_family="money", scale=10000000.0, period="30th June, 26")
    page = ("Key Standalone financial information: Total Income 1,466.73 1,664.01 "
            "Net Profit before tax and exceptional items 55.43 163.92")
    obs.apply_results_row_gates([fragment], page)
    assert fragment["status"] == "unverified" and "results_value_fragment" in fragment["status_reason"]


def test_a_whole_printed_figure_is_not_a_fragment():
    whole = row(measure="revenue_from_operations", printed_label="Revenue from operations", value_text="10244",
                value=10244.0, unit="₹ in Crore", scale=10000000.0)
    obs.apply_results_row_gates([whole], "Revenue from operations 10,244 9,871")
    assert whole["status"] == "verified"


# 4. the printed unit/scale line is carried to rows without one
def test_page_scale_line_fills_an_empty_unit():
    unitless = row(measure="NEW:equity_attributable_to_owners", printed_label="Equity attributable to owners",
                   value_text="3,28,605.36", value=328605.36, unit="", unit_family="", scale=1.0,
                   series_title="Audited consolidated statement of Assets & Liabilities")
    obs.apply_results_row_gates([unitless], "Particulars (Rs. in lakhs, unless otherwise stated) 3,28,605.36")
    assert (unitless["unit"], unitless["scale"]) == ("Lakhs", 100000.0)
    assert unitless["status"] == "verified"
    assert "results_unit" in unitless["status_reason"]


def test_misspelled_and_previous_page_scale_lines_are_used():
    misspelled = row(measure="changes_in_payables", printed_label="Increase/(Decrease) In Payables",
                     value_text="(1,491.54)", value=-1491.54, unit="l akhs", unit_family="", scale=1.0)
    obs.apply_results_row_gates([misspelled], "BLACK ROSE INDUSTRIES LIMITED\nFigures~ ln l akhs\nCASH FLOW")
    assert (misspelled["unit"], misspelled["scale"]) == ("Lakhs", 100000.0)
    carried = row(measure="NEW:change_in_share_capital_share_premium_and_warrants",
                  printed_label="Increase/(Decrease) in Share Capital/Share Premium & Warrants(Net)",
                  value_text="(129.62)", value=-129.62, unit="", unit_family="", scale=1.0)
    obs.apply_results_row_gates([carried], "Particulars For the year ended March 31, 2026 (129.62)",
                                previous_text="(₹ in lacs)")
    assert (carried["unit"], carried["scale"]) == ("Lakhs", 100000.0)


def test_a_known_unit_is_never_replaced():
    known = row(unit="crore", unit_family="money", scale=10000000.0)
    obs.apply_results_row_gates([known], "Figures in lakhs")
    assert (known["unit"], known["scale"]) == ("crore", 10000000.0)
    assert known["status"] == "verified"


def test_apply_number_gates_dispatches_results_rows_only():
    results_row = row(measure="NEW:legal_reference_year", printed_label="Companies Act, 2013", value_text="2013",
                      value=2013.0, unit="", unit_family="", scale=1.0, period="2013")
    obs.apply_number_gates([results_row], "results", page_text="")
    assert results_row["status"] == "quarantined"
    deck_row = row(measure="capacity.total", printed_label="Capacity", value_text="30", value=30.0,
                   unit="mtpa", scale=1.0, period="FY25")
    obs.apply_number_gates([deck_row], "deck", page_text="Capacity 30 FY25")
    assert deck_row["status"] == "verified"


# T-242 r2 -- the results ckpt_0001 fix note (FAIL 40R/20P): cash-flow measure kind, basis, period duration,
# scale inheritance and JV/associate scope.
CASH_FLOW_PAGE = ("ANUPAM RASAYAN INDIA LIMITED\nUNAUDITED STANDALONE CASH FLOW STATEMENT FOR THE HALF YEAR "
                  "ENDED SEPTEMBER 30, 2026\nParticulars\n")


# 5. a cash-flow line never keeps the P&L / balance-sheet measure of the stock it moves
def test_cash_flow_lines_never_take_the_balance_sheet_measure():
    deposits = row(measure="deposits", printed_label="Increase/(Decrease) in Deposits", value_text="(0.47)",
                   value=-0.47, period="March 31, 2025", basis="consolidated")
    paid = row(measure="finance_cost", printed_label="Finance cost paid", value_text="(44,836.85)",
               value=-44836.85)
    taxes = row(measure="total_tax_expense", printed_label="Direct taxes paid", value_text="(16,810.89)",
                value=-16810.89)
    net_change = row(measure="cash_flow.net_change", printed_label="Net increase/(decrease) in cash and cash "
                                                                    "equivalents", value_text="131.40", value=131.4,
                     period="Half year ended September 30, 2026")
    rows = [deposits, paid, taxes, net_change]
    obs.apply_results_row_gates(rows, CASH_FLOW_PAGE)
    assert deposits["measure"] == "NEW:increase_decrease_in_deposits_cash_flow"
    assert deposits["status"] == "unverified" and "results_cash_flow_measure" in deposits["status_reason"]
    assert paid["measure"] == "NEW:finance_cost_paid_cash_flow" and paid["status"] == "unverified"
    assert taxes["measure"] == "direct_taxes_paid" and taxes["status"] == "verified"
    assert net_change["measure"] == "cash_flow.net_change" and net_change["status"] == "verified"


def test_a_panel_line_is_not_mapped_on_a_page_that_is_not_a_cash_flow_statement():
    stock = row(measure="deposits", printed_label="Increase/(Decrease) in Deposits", value_text="10.00",
                value=10.0, period="March 31, 2025")
    obs.apply_results_row_gates([stock], "Particulars (Rs. in lakhs) Deposits 10.00")
    assert stock["measure"] == "deposits" and stock["status"] == "verified"


# 6. basis: the page head wins, else the page before carries it; a dual filing that names neither is gated
def test_basis_comes_from_the_page_or_the_page_before_and_dual_unstated_is_gated():
    own_page = row(basis="")
    previous = row(basis="")
    unstated = row(basis="")
    obs.apply_results_row_gates(
        [own_page], "Statement of Consolidated Financial Results for the quarter ended June 30, 2026")
    obs.apply_results_row_gates(
        [previous], "Particulars 31.03.2026",
        previous_page_text="Statement of Standalone Financial Results (Rs. in Lakhs)")
    obs.apply_results_row_gates(
        [unstated], "Key Financial Highlights 10,252 mn", previous_page_text="Page 1 of 9",
        doc_dual_statement=True)
    assert own_page["basis"] == "consolidated" and own_page["basis_source"] == "page_heading"
    assert previous["basis"] == "standalone" and previous["basis_source"] == "previous_page_heading"
    assert unstated["basis"] == "" and unstated["status"] == "unverified"
    assert "basis_unstated" in unstated["status_reason"]
    assert own_page["status"] == "verified" and previous["status"] == "verified"


def test_a_dual_filing_whose_page_names_the_basis_is_not_gated():
    page_named = row(basis="")
    obs.apply_results_row_gates([page_named], "Standalone Statement of Profit and Loss March 31, 2026",
                                doc_dual_statement=True)
    assert page_named["basis"] == "standalone" and page_named["status"] == "verified"


# 7. period: a bare year or a release date is not a period; an end date under two durations needs its own
def test_period_duration_missing_for_two_columns_sharing_an_end_date():
    half = row(period="June 30, 2025")
    page = ("Statement of consolidated financial results\nQuarter ended June 30, 2026  Corresponding quarter "
            "ended June 30, 2025\nYear to date figures for the current period ended June 30, 2026\n"
            "Year to date figures for the previous period ended June 30, 2025")
    obs.apply_results_row_gates([half], page)
    assert half["status"] == "unverified" and "results_period_duration_missing" in half["status_reason"]


def test_bare_year_and_release_date_are_not_periods():
    year = row(period="2026")
    release = row(period="May 13, 2026")
    obs.apply_results_row_gates([year], "Consolidated Statement of Assets and Liabilities As At 31st March 2026")
    obs.apply_results_row_gates([release], "Bharti Airtel Limited - Media Release May 13, 2026\nPage 3 of 4")
    assert year["status"] == "unverified" and "results_period_not_a_period" in year["status_reason"]
    assert release["status"] == "unverified" and "release date" in release["status_reason"]


# 8. scale: a statement page without its scale line takes the document's one scale; share measures never do
def test_document_scale_line_completes_a_currency_only_unit():
    unitless = row(measure="investments", printed_label="Purchase / Sale of Investments (net)", unit="Rs.",
                   unit_family="", scale=1.0, value_text="(21.83)", value=-21.83, period="30.09.2025")
    obs.apply_results_row_gates([unitless], "30.09.2026 30.09.2025 (Unaudited) Rs. Rs.\nA. Cash Flow from "
                                            "Operating Activities",
                                doc_note=("Lakhs", "money", 100000.0))
    assert (unitless["unit"], unitless["scale"]) == ("Lakhs", 100000.0)
    assert "document prints Lakhs" in unitless["status_reason"]


def test_eps_takes_no_money_scale():
    eps = row(measure="eps", printed_label="Earnings/(loss) per share - Basic and Diluted", unit="\u20b9 Lakhs",
              unit_family="money", scale=1.0, period="Quarter ended 31st March 2025")
    obs.apply_results_row_gates([eps], "(Rs. in Lakhs) Particulars Quarter ended Year ended",
                                doc_note=("Lakhs", "money", 100000.0), doc_dual_statement=False)
    assert (eps["unit"], eps["unit_family"], eps["scale"]) == ("\u20b9", "money_per_unit", 1.0)
    assert "results_per_share_unit" in eps["status_reason"]
    assert eps["status"] == "verified"


# 9. a share of a JV/associate result is that entity's figure; a share of loss keeps its sign
def test_share_of_joint_venture_loss_is_scoped_and_negative():
    shared = row(measure="NEW:share_of_net_loss_of_joint_venture", printed_label="Group's share of net loss",
                 value_text="8,193.50", value=8193.5, unit="lakhs", scale=100000.0,
                 period="for the year ended March 31, 2026", entity_scope="subsidiary")
    obs.apply_results_row_gates([shared], "Statement on Impact of Audit Qualifications\n"
                                          "Group's share of net loss of INR 8,193.50 lakhs in respect of one "
                                          "joint venture")
    obs.gate_not_company([shared])
    assert shared["entity_scope"] == "jv"
    assert shared["value"] == -8193.5
    assert shared["status"] == "unverified" and "not_company" in shared["status_reason"]


def test_an_equity_accounted_business_is_the_associates_figure():
    aum = row(measure="aum.value", printed_label="Mutual fund quarterly average assets under management grew by "
                                                  "6% year-on year to 4,27,675 crore",
              value_text="4,27,675", value=427675.0, unit="crore", scale=10000000.0, basis="consolidated",
              entity_scope="subsidiary", period="Q1 FY27")
    page = ("1. Consolidated segment revenue; for Ind AS statutory reporting purpose Asset management, wellness "
            "business and health insurance are not consolidated and included under equity accounting.")
    obs.apply_results_row_gates([aum], page)
    obs.gate_not_company([aum])
    assert aum["entity_scope"] == "associate" and aum["basis"] == ""
    assert aum["status"] == "unverified" and "results_equity_accounted" in aum["status_reason"]


# T-242 r3 -- results_grade_r2 (28R/23P/8W/1J): scope backing, cash-flow "Adjustments for", current vs
# non-current, standalone-only basis, statute/clause junk references, and flow duration fill.
def test_scope_backing_resets_unbacked_scopes_and_keeps_named_subsidiary_table():
    arssbl = row(measure="revenue_from_operations", printed_label="Total Revenue from Operations",
                 series_title="STATEMENT OF UNAUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER ENDED JUNE 30, 2026",
                 entity_scope="subsidiary", basis="consolidated")
    arssbl_page = ("/-\\ N ,\\ Ni 1 Jt .-\\ 1 1-1 I\nANAND RATHI SHARE AND STOCK BROKERS LIMITED\n"
                   "STATEMENT OF UNAUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER ENDED JUNE 30, 2026\n")
    alfl = row(measure="deferred_tax_assets_net", printed_label="Deferred Tax Assets (net)",
               series_title="STATEMENT OF ASSETS AND LIABILITIES", entity_scope="subsidiary", period="As at 31st March 2026")
    abhifin = row(measure="property_plant_and_equipment", printed_label="Property,Plant and Equipment",
                  series_title="STATEMENT OF ASSET & LIABLITIES AS ON 31ST MARCH, 2026",
                  entity_scope="subsidiary", period="31.03.2025")
    parent_own = row(measure="profit_before_tax", printed_label="Profit before taxes",
                     series_title="STATEMENT OF CASH FLOWS", entity_scope="parent")
    named_sub = row(measure="revenue_from_operations", printed_label="Revenue from operations",
                    series_title="Acme Mobility Private Limited - Financial Results", entity_scope="subsidiary")
    obs.apply_results_row_gates([arssbl], arssbl_page, company="Anand Rathi Share and Stock Brokers Limited")
    obs.apply_results_row_gates([alfl], "STATEMENT OF ASSETS AND LIABILITIES\nDeferred Tax Assets (net) 3.57",
                                company="Abhinav Leasing & Finance Ltd",
                                previous_page_text="Abhinay Leasing and Finance Limited\nAUDITED FINANCIAL RESULTS")
    obs.apply_results_row_gates([abhifin], "ABHISHEK FINLEASE LIMITED\nSTATEMENT OF ASSET & LIABLITIES AS ON 31ST MARCH, 2026",
                                company="Abhishek Finlease Ltd")
    obs.apply_results_row_gates([parent_own], "ARISE INDUSTRIES LIMITED\nSTATEMENT OF CASH FLOWS",
                                company="Arise Industries Limited")
    obs.apply_results_row_gates([named_sub],
                                "Acme Mobility Private Limited\nStatement of Profit and Loss for the year ended March 31, 2026",
                                company="Acme India Limited")
    assert all(r["entity_scope"] == "company" and r["status"] == "verified"
               for r in (arssbl, alfl, abhifin, parent_own))
    assert named_sub["entity_scope"] == "subsidiary" and named_sub["status"] == "verified"


def test_cash_flow_adjustments_for_lines_map_to_cash_flow_while_pnl_keeps_measure():
    cf_interest = row(measure="interest_income", printed_label="Interest income", value_text="(3.39)", value=-3.39,
                      series_title="Statement of unaudited cash flows",
                      group_path="Cash flows from operating activities > Adjustments for :",
                      period="For the half year ended 30 September 2025")
    cf_rental = row(measure="NEW:rental_income", printed_label="Rental income", value_text="(184.02)", value=-184.02,
                    series_title="PART III - AUDITED CONSOLIDATED STATEMENT OF CASH FLOWS FOR THE YEAR ENDED 31 MARCH 2026",
                    group_path="Cash flow from operating activities > Adjustment for:",
                    period="For the year ended 31 March 2025")
    pnl_interest = row(measure="interest_income", printed_label="Interest income", value_text="42.50", value=42.5,
                       series_title="Statement of Standalone Financial Results",
                       period="Quarter ended June 30, 2026")
    obs.apply_results_row_gates([cf_interest], "Statement of unaudited cash flows\nAdjustments for :\nInterest income (3.39)")
    obs.apply_results_row_gates([cf_rental], "A. K. Capital Services Limited\n(184.02)")
    obs.apply_results_row_gates([pnl_interest], "Statement of Standalone Financial Results\nInterest income 42.50")
    assert cf_interest["measure"] == "NEW:interest_income_cash_flow" and cf_interest["status"] == "unverified"
    assert cf_rental["measure"] == "NEW:rental_income_cash_flow" and cf_rental["status"] == "unverified"
    assert pnl_interest["measure"] == "interest_income" and pnl_interest["status"] == "verified"


def test_current_vs_non_current_heading_selects_twin_or_marks_unverified():
    twin_fix = row(measure="other_current_assets", printed_label="Other non-current assets",
                   group_path="Assets > Non-current assets", period="As at March 31, 2026")
    no_twin = row(measure="current_tax_assets_net", printed_label="Non current tax asset (net)",
                  group_path="Assets > Non-current assets", period="March 31, 2026")
    page_sec = row(measure="non_current_investments", printed_label="Investments",
                   group_path="", period="As at March 31, 2026")
    obs.apply_results_row_gates([twin_fix, no_twin], "Statement of Assets and Liabilities")
    obs.apply_results_row_gates([page_sec], "Balance Sheet\nNon-current assets\nProperty 10\nCurrent assets\nInvestments 50")
    assert twin_fix["measure"] == "other_non_current_assets" and twin_fix["status"] == "verified"
    assert no_twin["status"] == "unverified" and "results_current_mismatch" in no_twin["status_reason"]
    assert page_sec["measure"] == "current_investments" and page_sec["status"] == "verified"


def test_standalone_only_filer_rewrites_consolidated_while_consolidated_filer_keeps_it():
    sa_filer = row(measure="pat", printed_label="Net Profit for the period", basis="consolidated",
                   period="Quarter ended Dec 31, 2025")
    cons_filer = row(measure="pat", printed_label="Net Profit for the period", basis="consolidated",
                     period="Quarter ended Dec 31, 2025")
    obs.apply_results_row_gates([sa_filer], "Apex Frozen Foods Ltd\nStatement of Audited Financial Results",
                                doc_standalone_only=True)
    obs.apply_results_row_gates([cons_filer], "Consolidated Financial Results for the Quarter ended Dec 31, 2025",
                                doc_standalone_only=False)
    assert sa_filer["basis"] == "standalone" and sa_filer["basis_source"] == "doc_standalone_only"
    assert sa_filer["status"] == "verified"
    assert cons_filer["basis"] == "consolidated" and cons_filer["status"] == "verified"


def test_statute_and_clause_references_are_dropped_while_financial_lines_stay():
    sec = row(measure="NEW:section_reference", printed_label="Section 143(10) of the Companies Act, 2013",
              value_text="143(10)", value=143.0, unit="Millions", scale=1000000.0)
    reg = row(measure="NEW:sebi_regulation", printed_label="Regulation 33 of SEBI (LODR) Regulations, 2015",
              value_text="33", value=33.0, unit="Lakhs", scale=100000.0)
    reg_unitless = row(measure="NEW:sebi_regulation", printed_label="Regulation 33 of SEBI (LODR) Regulations, 2015",
                       value_text="33", value=33.0, unit="", scale=1.0)
    sched = row(measure="NEW:schedule_ref", printed_label="Schedule III to the Companies Act",
                value_text="III", value=3.0, unit="", scale=1.0)
    rule = row(measure="NEW:rule_ref", printed_label="Rule 3(1) of Companies Rules",
               value_text="3(1)", value=3.0, unit="", scale=1.0)
    kept = row(measure="revenue_from_operations", printed_label="Revenue under Ind AS 115",
               value_text="1,234.50", value=1234.5, unit="Lakhs", scale=100000.0)
    rows = [sec, reg, sched, rule, kept]
    obs.apply_results_row_gates(rows, "Independent Auditor's Report")
    assert rows == [kept] and kept["status"] == "verified"
    assert obs.junk_ordinal_reason(reg_unitless).startswith("junk_statute_reference:")


def test_flow_duration_fill_populates_column_header_or_gates_while_stock_keeps_as_at():
    q_row = row(measure="pat", printed_label="Profit for the period", period="June 30, 2025")
    y_as_at = row(measure="finance_cost", printed_label="Finance Costs", period="As at 31-03-2026")
    yr_tail = row(measure="raw_material_cost", printed_label="Cost of Materials Consumed", period="31-Mar-26")
    ambig = row(measure="other_comprehensive_income", printed_label="OCI", period="Mar-26")
    mismatch_cf = row(measure="NEW:bad_debts_cash_flow", printed_label="Bad debts", period="31.03.2026")
    rel = row(measure="revenue_growth_qoq", printed_label="Airtel Business grew sequentially by", period="sequentially")
    stock = row(measure="trade_receivables", printed_label="Trade receivables", period="As at 31-03-2026")

    pnl_page = ("Statement of Financial Results\nQuarter ended\nYear ended\n"
                "June 30, 2026\nMarch 31, 2026\nJune 30, 2025\nMarch 31, 2026")
    anuras_page = ("Quarter Ended\nFinancial Year Ended\n"
                   "March 31, 2026\nDecember 31, 2025\nMarch 31, 2025\nAs at 31-03-2026\nAs at 31-03-2025")
    half_page = ("Statement of Financial Results\nQuarter ended\nHalf Year ended\nYear ended\n"
                 "30-Sep-26\n30-Jun-26\n30-Sep-25\n30-Sep-26\n30-Sep-25\n31-Mar-26")
    alpa_page = "Statement of Profit and Loss\nQuarter Ended\nYear Ended\nJun26\nMar-26\nJun-25\nMar-26"
    cf_half = "Standalone Statement of Cash Flow for the Half Year ended on 30th September, 2026\n30.09.2026 30.09.2025 31.03.2026"

    obs.apply_results_row_gates([q_row], pnl_page)
    obs.apply_results_row_gates([y_as_at, stock], anuras_page)
    obs.apply_results_row_gates([yr_tail], half_page)
    obs.apply_results_row_gates([ambig], alpa_page)
    obs.apply_results_row_gates([mismatch_cf], cf_half)
    obs.apply_results_row_gates([rel], "Media Release")

    assert q_row["period"] == "Quarter ended June 30, 2025" and q_row["status"] == "verified"
    assert y_as_at["period"] == "Year ended 31-03-2026" and y_as_at["status"] == "verified"
    assert yr_tail["period"] == "Year ended 31-Mar-26" and yr_tail["status"] == "verified"
    assert stock["period"] == "As at 31-03-2026" and stock["status"] == "verified"
    assert ambig["status"] == "unverified" and "results_period_duration_missing" in ambig["status_reason"]
    assert mismatch_cf["status"] == "unverified" and "results_period_duration_missing" in mismatch_cf["status_reason"]
    assert rel["status"] == "unverified" and "results_period_duration_missing" in rel["status_reason"]


# T-242 r3b -- the six graded-R rows r3 downgraded: a duration header the parser missed (misspelt, "ending on",
# carried from the page before, or garbled under an annual cash-flow title), and a cash-flow adjustment line whose
# NEW id already names its own line (never remapped, never unverified).
def test_duration_is_read_from_a_misspelt_half_year_header():
    half = row(measure="cash_generated_from_operations",
               printed_label="Cash (used in)/ generated from operations", value_text="221.36", value=221.36,
               unit="Rs in Crore", scale=10000000.0, period="30.09.2025")
    page = ("Unaudited Consolidated Statement of Cash Flow\n(Rs in Crore)\nParticulars\n"
            "for the Half Vear Ended\n30.09.2026\n30.09.2025\nA]\nCash Flow from Operating Activities\n"
            "Cash (used in)/ generated from operations 221.36 208.79")
    obs.apply_results_row_gates([half], page)
    assert half["status"] == "verified" and half["period"] == "Half year ended 30.09.2025"


def test_duration_is_read_from_a_year_ending_on_header():
    prior = row(measure="cash_flow.financing", printed_label="Net Cash flowsj(used in) Financing Activities",
                value_text="129.32", value=129.32, unit="Lakhs", scale=100000.0, period="31-March-2025")
    page = ("Continuation Sheet\nM/s ALUFLUORIDE LIMITED, VISAKHAPATNAM\n"
            "Consolidated Statement of Cash flows for the year ended 31st March, 2026\n"
            "Figures for the\nParticulars\ncurrent reporting\nyear ending on\n31-March-2026\n"
            "A) Cash Flow from Operating Activities:\nNet Cash flowsj(used in) Financing Activities 129.32 96.15\n"
            "Figures for the\nprevious reporting\nyear ending on\n31-March-2025\n")
    obs.apply_results_row_gates([prior], page)
    assert prior["status"] == "verified" and prior["period"] == "Year ended 31-March-2025"


def test_duration_carried_from_the_previous_page_resolves_a_flow_row():
    carried = row(measure="pat", printed_label="Profit for the year", value_text="1,234.00", value=1234.0,
                  period="31-Mar-26")
    obs.apply_results_row_gates(
        [carried], "Particulars 31-Mar-26 31-Mar-25\nProfit for the year 1,234.00 1,000.00",
        previous_page_text="Statement of Financial Results\nYear ended\nMarch 31, 2026\nMarch 31, 2025")
    assert carried["status"] == "verified" and carried["period"] == "Year ended 31-Mar-26"


def test_an_ambiguous_carried_header_resolves_nothing():
    stock = row(measure="total_current_assets", printed_label="Total current assets", period="31st March, 2026")
    obs.apply_results_row_gates([stock], "Balance Sheet\n31st March, 2026",
                                previous_page_text="Quarter ended 31 March 2026\nYear ended 31 March 2026")
    assert stock["status"] == "verified" and stock["period"] == "31st March, 2026"


def test_an_annual_cash_flow_statement_whose_title_garbles_the_duration_reads_year():
    annual = row(measure="cash_flow.operating", printed_label="Net cash flow from operating activities (A)",
                 value_text="22.04", value=22.04, unit="Rs. in Lakhs", scale=100000.0, period="31-Mar-26")
    page = ("AAKSH OPTIFIBRE LIMITED\nConsolidated Statement of Cash Flows for the izar ended March 31 2026\n"
            "Particulars\n31-Mar-26\n31-Mar-25\nCash flow from operating activities\n"
            "Net cash flow from operating activities (A) 22.04 14.84")
    obs.apply_results_row_gates([annual], page)
    assert annual["status"] == "verified" and annual["period"] == "Year ended 31-Mar-26"


def test_a_cash_flow_adjustment_line_that_names_its_own_line_is_not_remapped():
    rents = row(measure="NEW:rent_received_other_income_adjustment", printed_label="Rent Received/Other Income",
                value_text="(150.71)", value=-150.71, unit="Rs. In Lakhs", scale=100000.0, period="31-03-2025",
                group_path="CASH FLOW FROM OPERATING ACTIVITIES > Adjustments for :")
    interest = row(measure="NEW:interest_income_from_investing_activities",
                   printed_label="Interest income from investing activities", value_text="(329.80)",
                   value=-329.80, unit="\u20b9 in Lakhs", scale=100000.0, period="Year ended 31 March 2025",
                   group_path="A. CASH FLOW FROM OPERATING ACTIVITIES > Adjustments for:")
    derecognition = row(measure="NEW:net_gain_on_derecognition_of_financial_instruments_under_amortised_cost_category",
                        printed_label="Net gain on derecognition of finanical instruments under amortised cost "
                                      "category", value_text="(97.79)", value=-97.79, unit="Rs. in Lakhs",
                        scale=100000.0, period="For the year ended 31 March 2025 (Audited)",
                        group_path="Cash flow from operating activities > Adjustment for:")
    rows = [rents, interest, derecognition]
    obs.apply_results_row_gates(rows, "Consolidated Statement of Cash Flows\n31-03-2026 31-03-2025\n"
                                      "Adjustments for:")
    assert [r["measure"] for r in rows] == [
        "NEW:rent_received_other_income_adjustment",
        "NEW:interest_income_from_investing_activities",
        "NEW:net_gain_on_derecognition_of_financial_instruments_under_amortised_cost_category",
    ]
    assert [r["status"] for r in rows] == ["verified"] * 3


def test_a_plain_income_line_under_adjustments_is_still_remapped():
    rental = row(measure="NEW:rental_income", printed_label="Rental income", value_text="(184.02)",
                 value=-184.02, unit="Rs. in Lakhs", scale=100000.0, period="For the year ended 31 March 2025",
                 group_path="Cash flow from operating activities > Adjustment for:")
    obs.apply_results_row_gates([rental], "Consolidated Statement of Cash Flows\nAdjustment for:")
    assert rental["measure"] == "NEW:rental_income_cash_flow" and rental["status"] == "unverified"
    assert "results_cash_flow_measure" in rental["status_reason"]


# T-242 r3c -- ambiguous dates (printed in >1 column) are never carried or filled by key, and 'Year ended'
# never lands on a non-31-March date unless the header binds the word to that exact single column.
def test_apolloin_p6_to_p7_never_fills_year_on_half_year_date():
    p6 = ("(Rs. In Lakhs except per share data)\nParticulars\n"
          "Year to Date figures\nfor current period\nended\n"
          "Year to Date figures\nfor previous year\nended\nYear Ended\n"
          "30.09.2026\n30.06.2026\n30.9.2025\n30.09.2026\n30.09.2025\n31.03.2026\n"
          "Statement of Standalone Unudited Financial Results For The Quarter Ended as on 30th September, 2026")
    p7 = ("30.09.2026\n30.09.2025\n(Unaudited)\n(Unaudited)\nRs.\nRs.\n"
          "A.\nCash Flow from Operating Activities\n"
          "(Increase) / Decrease in Trade Receivable\n-204.86\n0.00\n"
          "Statement of Cash Flow for the year ended September 30,2026\nParticulars\nYEAR ENDED")
    recv_25 = row(measure="changes_in_receivables", printed_label="(Increase) / Decrease in Trade Receivable",
                  value_text="0.00", value=0.0, unit="Lakhs", scale=100000.0, period="30.09.2025")
    recv_26 = row(measure="changes_in_receivables", printed_label="(Increase) / Decrease in Trade Receivable",
                  value_text="-204.86", value=-204.86, unit="Lakhs", scale=100000.0, period="30.09.2026")
    p6_rev = row(measure="revenue_from_operations", printed_label="1. Income from Operations",
                 value_text="505.07", value=505.07, unit="Lakhs", scale=100000.0, period="30.09.2026")

    obs.apply_results_row_gates([recv_25, recv_26], p7, previous_text=p6, previous_page_text=p6)
    obs.apply_results_row_gates([p6_rev], p6)

    for r, expected_p in ((recv_25, "30.09.2025"), (recv_26, "30.09.2026"), (p6_rev, "30.09.2026")):
        assert r["period"] == expected_p
        assert "year" not in r["period"].lower()
        assert r["status"] == "unverified" and "results_period_duration_missing" in r["status_reason"]


def test_agl_p3_never_fills_quarter_on_year_column_or_year_on_june():
    p2 = ("Independent Auditor's Review Report\n"
          "for the quarter ended June 30, 2026 and year to date from April 01, 2026 to June 30, 2026.\n"
          "The comparative financial information of the Company for the corresponding quarter ended June 30, 2025 "
          "and preceding quarter ended March 31, 2026, included in these Unaudited Standalone Financial Results")
    p3 = ("Rs in crores\nYear ended\n30 Jun 2026\n31 Mar 2026\n30 Jun 2025\n31 Mar 2026\n"
          "(Unaudited)\n(Unaudited)\n(Unaudited)\n(Audited)\n"
          "1\nIncome\n(a) Income from operations\n521\n442\n513\n2,034\n"
          "10 Paid-up equity share capital\n197\n197\n197\n197\n"
          "STATEMENT OF UNAUDITED STANDALONE FINANCIAL RESULTS FOR THE QUARTER ENDED JUNE 30, 2026\n"
          "Particulars\nQuarter ended")
    q4_442 = row(measure="revenue_from_operations", printed_label="Income from operations",
                 value_text="442", value=442.0, unit="crores", scale=10000000.0, period="Quarter ended 31 Mar 2026")
    fy_2034 = row(measure="revenue_from_operations", printed_label="Income from operations",
                  value_text="2,034", value=2034.0, unit="crores", scale=10000000.0, period="31 Mar 2026")
    jun_521 = row(measure="revenue_from_operations", printed_label="Income from operations",
                  value_text="521", value=521.0, unit="crores", scale=10000000.0, period="30 Jun 2026")
    cap_197 = row(measure="equity_share_capital", printed_label="Paid-up equity share capital",
                  value_text="197", value=197.0, unit="crores", scale=10000000.0, period="31 Mar 2026")

    obs.apply_results_row_gates([q4_442, fy_2034, jun_521, cap_197], p3, previous_text=p2, previous_page_text=p2)

    assert q4_442["period"] == "Quarter ended 31 Mar 2026" and q4_442["status"] == "verified"
    assert fy_2034["period"] == "31 Mar 2026"
    assert "quarter" not in fy_2034["period"].lower()
    assert fy_2034["status"] == "unverified" and "results_period_duration_missing" in fy_2034["status_reason"]
    assert jun_521["period"] == "Quarter ended 30 Jun 2026" and jun_521["status"] == "verified"
    assert "year" not in jun_521["period"].lower()
    assert cap_197["period"] == "31 Mar 2026" and cap_197["status"] == "verified"


def test_asitcfin_p14_never_fills_quarter_on_year_column():
    p13 = ("The Statement includes the results for the quarter ended 31st March, 2026 being the balancing "
           "figures between the audited figures in respect of the full financial year ended 31 st March, 2026 "
           "and the published unaudited year-to-date figures")
    p14 = ("Asit C. Mehta Financial Services Limited\n"
           "Statement of Audited Consolidated Financial Results for the Quarter and Year ended March 31 , 2026\n"
           "in Lakhs\nQuarter ended\nYear ended\nParticulars\n"
           "31 .03.2026\n31 .12.2025\n31 .03.2025\n31 .03.2026\n31 .03.2025\n"
           "Audited\nUnaudited\nAudited\nAudited\nAudited\n"
           "a. Revenue from operations 1,473.43 1,358.34 2,953.33 6,123.00 7,264.08")
    fy_6123 = row(measure="revenue_from_operations", printed_label="Revenue from operations",
                  value_text="6,123.00", value=6123.0, unit="Lakhs", scale=100000.0, period="31.03.2026")
    q3_1358 = row(measure="revenue_from_operations", printed_label="Revenue from operations",
                  value_text="1,358.34", value=1358.34, unit="Lakhs", scale=100000.0, period="31.12.2025")

    obs.apply_results_row_gates([fy_6123, q3_1358], p14, previous_text=p13, previous_page_text=p13)

    assert fy_6123["period"] == "31.03.2026"
    assert "quarter" not in fy_6123["period"].lower()
    assert fy_6123["status"] == "unverified" and "results_period_duration_missing" in fy_6123["status_reason"]
    assert q3_1358["period"] == "Quarter ended 31.12.2025" and q3_1358["status"] == "verified"


def test_year_only_fills_on_year_end_unless_exact_single_column_header():
    ytd_row = row(measure="revenue_from_operations", printed_label="Revenue from operations",
                  value_text="100.00", value=100.0, period="30.09.2026")
    exact_col = row(measure="revenue_from_operations", printed_label="Revenue from operations",
                    value_text="500.00", value=500.0, period="31 Dec 2025")

    obs.apply_results_row_gates(
        [ytd_row], "Statement of Results\nYear to date figures for the period ended 30.09.2026\nRevenue 100.00")
    obs.apply_results_row_gates([exact_col], "Statement of Results\nYear ended\n31 Dec 2025\nRevenue 500.00")

    assert ytd_row["period"] == "30.09.2026"
    assert ytd_row["status"] == "unverified" and "results_period_duration_missing" in ytd_row["status_reason"]
    assert exact_col["period"] == "Year ended 31 Dec 2025" and exact_col["status"] == "verified"


# T-242 r3d -- one label, two values, one date: resolve duration by column position or strip to bare date.
def test_r3d_agarwaleye_p9_q_plus_h1_resolves_by_column_position():
    page = ("Dr. Agarwal's Eye Hospital Limited\n"
            "Statement of Unaudited Financial Results for the Quarter and Half Year ended 30 September 2026\n"
            "(Rs. in Crores, except per share data)\n"
            "Quarter Ended Half Year Ended Year Ended\n"
            "Particulars\n"
            "30-Sep-26 30-Jun-26 30-Sep-25 30-Sep-26 30-Sep-25 31-Mar-26\n"
            "(Unaudited) (Unaudited) (Unaudited) (Unaudited) (Unaudited) (Audited)\n"
            "Earnings per equity share (of Rs. 10/- each)\n"
            "(a) Basic 1.65 1.10 1.07 3.2 2.11 5.40\n"
            "(b) Diluted 1.62 1.08 1.05 3.15 2.08 5.31")
    q2_26 = row(measure="eps_basic", printed_label="(a) Basic", value_text="1.65", value=1.65,
                unit="Rs.", scale=1.0, period="Quarter ended 30-Sep-26")
    h1_26 = row(measure="eps_basic", printed_label="(a) Basic", value_text="3.2", value=3.2,
                unit="Rs.", scale=1.0, period="Quarter ended 30-Sep-26")
    q2_25 = row(measure="eps_basic", printed_label="(a) Basic", value_text="1.07", value=1.07,
                unit="Rs.", scale=1.0, period="Quarter ended 30-Sep-25")
    h1_25 = row(measure="eps_basic", printed_label="(a) Basic", value_text="2.11", value=2.11,
                unit="Rs.", scale=1.0, period="Quarter ended 30-Sep-25")
    obs.apply_results_row_gates([q2_26, h1_26, q2_25, h1_25], page)
    assert q2_26["period"] == "Quarter ended 30-Sep-26" and q2_26["period_source"] == "column_position"
    assert h1_26["period"] == "Half year ended 30-Sep-26" and h1_26["period_source"] == "column_position"
    assert q2_25["period"] == "Quarter ended 30-Sep-25" and q2_25["period_source"] == "column_position"
    assert h1_25["period"] == "Half year ended 30-Sep-25" and h1_25["period_source"] == "column_position"
    assert all(r["status"] == "verified" for r in (q2_26, h1_26, q2_25, h1_25))


def test_r3d_q_plus_year_corrects_reader_quarter_on_year_with_dashes_and_wraps():
    page_agarwal_p11 = (
        "Dr. Agarwal's Eye Hospital Limited\n"
        "Quarter ended Year ended\n"
        "Particulars\n"
        "31-Mar-26 31-Dec-25 31-Mar-25 31-Mar-26 31-Mar-25\n"
        "(a) Basic\n1.25\n1.02\n0.98\n4.21\n3.76\n"
        "(b) Diluted 1.24 1.01 0.97 4.18 3.74"
    )
    q_eps = row(measure="eps_basic", printed_label="(a) Basic", value_text="1.25", value=1.25,
                unit="Rs.", scale=1.0, period="Quarter ended 31-Mar-26")
    y_eps = row(measure="eps_basic", printed_label="(a) Basic", value_text="4.21", value=4.21,
                unit="Rs.", scale=1.0, period="Quarter ended 31-Mar-26")
    page_aanchalisp_p9 = (
        "Aanchal Ispat Limited\n"
        "Quarter ended Year ended\n"
        "Particulars\n"
        "31.03.2026 31.12.2025 31.03.2025 31.03.2026 31.03.2025\n"
        "f) Depreciation and amortization 15.22 - 12.00 61.54 -\n"
        "g) Other expenses 100.00 90.00 80.00 350.00 300.00"
    )
    q_dep = row(measure="depreciation_and_amortization", printed_label="f) Depreciation and amortization",
                value_text="15.22", value=15.22, unit="Lakhs", scale=100000.0, period="Quarter ended 31.03.2026")
    y_dep = row(measure="depreciation_and_amortization", printed_label="f) Depreciation and amortization",
                value_text="61.54", value=61.54, unit="Lakhs", scale=100000.0, period="Quarter ended 31.03.2026")
    obs.apply_results_row_gates([q_eps, y_eps], page_agarwal_p11)
    obs.apply_results_row_gates([q_dep, y_dep], page_aanchalisp_p9)
    assert q_eps["period"] == "Quarter ended 31-Mar-26" and y_eps["period"] == "Year ended 31-Mar-26"
    assert y_eps["period_source"] == "column_position" and y_eps["status"] == "verified"
    assert q_dep["period"] == "Quarter ended 31.03.2026" and y_dep["period"] == "Year ended 31.03.2026"
    assert y_dep["period_source"] == "column_position" and y_dep["status"] == "verified"


def test_r3d_ambiguous_or_unpaired_strips_duration_to_bare_date_unverified():
    # Equal values printed in two columns or unpaired / mismatched OCR tokens cannot resolve column position.
    page_mismatch = (
        "Statement of Results\n"
        "Quarter ended Year ended\n"
        "31.03.2026 31.12.2025 31.03.2025 31.03.2026 31.03.2025\n"
        "f) Depreciation and amortization 15.22 2 69 12.00 61.54 -"
    )
    m1 = row(measure="depreciation_and_amortization", printed_label="f) Depreciation and amortization",
             value_text="15.22", value=15.22, period="Quarter ended 31.03.2026")
    m2 = row(measure="depreciation_and_amortization", printed_label="f) Depreciation and amortization",
             value_text="61.54", value=61.54, period="Quarter ended 31.03.2026")
    page_dup = (
        "Statement of Results\n"
        "Quarter ended Half year ended\n"
        "30-Sep-26 30-Sep-25 30-Sep-26 30-Sep-25\n"
        "(a) Basic 10.00 8.00 10.00 12.00"
    )
    d1 = row(measure="eps_basic", printed_label="(a) Basic", value_text="10.00", value=10.0,
             period="Quarter ended 30-Sep-26", period_source="reader")
    d2 = row(measure="eps_basic", printed_label="(a) Basic", value_text="11.00", value=11.0,
             period="Quarter ended 30-Sep-26", period_source="reader")
    obs.apply_results_row_gates([m1, m2], page_mismatch)
    obs.apply_results_row_gates([d1, d2], page_dup)
    for r, bare in ((m1, "31.03.2026"), (m2, "31.03.2026"), (d1, "30-Sep-26"), (d2, "30-Sep-26")):
        assert r["period"] == bare
        assert r["period_source"] == ""
        assert r["status"] == "unverified"
        assert "results_period_duration_ambiguous" in r["status_reason"]


def test_r3d_single_value_per_date_page_is_untouched():
    page = (
        "Quarter ended Year ended\n"
        "31.03.2026 31.12.2025 31.03.2025 31.03.2026 31.03.2025\n"
        "a. Revenue from operations 1,473.43 1,358.34 2,953.33 6,123.00 7,264.08"
    )
    q = row(measure="revenue_from_operations", printed_label="a. Revenue from operations",
            value_text="1,473.43", value=1473.43, period="Quarter ended 31.03.2026")
    y = row(measure="revenue_from_operations", printed_label="a. Revenue from operations",
            value_text="6,123.00", value=6123.0, period="Year ended 31.03.2026")
    q3 = row(measure="revenue_from_operations", printed_label="a. Revenue from operations",
             value_text="1,358.34", value=1358.34, period="31.12.2025")
    obs.apply_results_row_gates([q, y, q3], page)
    assert q["period"] == "Quarter ended 31.03.2026" and q["status"] == "verified"
    assert y["period"] == "Year ended 31.03.2026" and y["status"] == "verified"
    assert q3["period"] == "Quarter ended 31.12.2025" and q3["status"] == "verified"


def test_r3d_bare_date_ocr_bracket_and_residue_counter(tmp_path):
    from reality_engine.scripts.results_r3d_residue import collect_r3d_residue
    import sqlite3

    page = (
        "Statement of Unaudited Financial Results\n"
        "Quarter ended Nine months ended Year ended\n"
        "31-Dec-25 30-Sep-25 31-Dec-24 31-Dec-25 31-Dec-24 31-Mar-25\n"
        "b) Other expenses {57.62) 40.00 - (175.40) - 210.00"
    )
    q_exp = row(measure="other_expenses", printed_label="b) Other expenses", value_text="{57.62)", value=-57.62,
                period="31-Dec-25")
    m9_exp = row(measure="other_expenses", printed_label="b) Other expenses", value_text="(175.40)", value=-175.40,
                 period="31-Dec-25")
    obs.apply_results_row_gates([q_exp, m9_exp], page)
    assert q_exp["period"] == "Quarter ended 31-Dec-25" and q_exp["period_source"] == "column_position"
    assert m9_exp["period"] == "Nine months ended 31-Dec-25" and m9_exp["period_source"] == "column_position"
    assert q_exp["status"] == "verified" and m9_exp["status"] == "verified"

    db_path = tmp_path / "sample.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE observation (doc_key TEXT, page INTEGER, symbol TEXT, printed_label TEXT, "
                "basis TEXT, segment TEXT, period TEXT, value REAL, value_text TEXT, period_source TEXT, "
                "status TEXT, record_type TEXT)")
    con.executemany(
        "INSERT INTO observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("d1", 9, "AGARWALEYE", "(a) Basic", "standalone", "", "Quarter ended 30-Sep-26", 1.65, "1.65", "", "unverified", "number"),
            ("d1", 9, "AGARWALEYE", "(a) Basic", "standalone", "", "Quarter ended 30-Sep-26", 3.2, "3.2", "", "unverified", "number"),
            ("d2", 3, "AGL", "Equity", "standalone", "", "Quarter ended 31 Mar 2026", 442.0, "442", "", "verified", "number"),
            ("d2", 3, "AGL", "Equity", "standalone", "", "31 Mar 2026", 2034.0, "2,034", "", "unverified", "number"),
        ],
    )
    con.commit()
    con.close()
    res = collect_r3d_residue(db_path)
    assert res["group_count"] == 1 and res["row_count"] == 2
    assert res["sample"][0][1][0]["symbol"] == "AGARWALEYE"
