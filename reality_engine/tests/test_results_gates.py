"""T-242: results-page number gates (junk references, entity scope, holding/fragment values, unit line)."""
import shutil
import uuid
from pathlib import Path

import pytest

from reality_engine.v2 import observations as obs


@pytest.fixture()
def tmp_path():
    """A writable scratch folder: the sandbox's pytest basetemp root can be ACL-locked (test_observations)."""
    base = Path(".tmp") / f"t242_results_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)



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
                "measure TEXT, basis TEXT, segment TEXT, period TEXT, value REAL, value_text TEXT, "
                "period_source TEXT, status TEXT, record_type TEXT)")
    con.executemany(
        "INSERT INTO observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("d1", 9, "AGARWALEYE", "(a) Basic", "eps_basic", "standalone", "", "Quarter ended 30-Sep-26", 1.65, "1.65", "", "unverified", "number"),
            ("d1", 9, "AGARWALEYE", "(a) Basic", "eps_basic", "standalone", "", "Quarter ended 30-Sep-26", 3.2, "3.2", "", "unverified", "number"),
            ("d2", 3, "AGL", "Equity", "equity_share_capital", "standalone", "", "Quarter ended 31 Mar 2026", 442.0, "442", "", "verified", "number"),
            ("d2", 3, "AGL", "Equity", "borrowings", "standalone", "", "31 Mar 2026", 2034.0, "2,034", "", "unverified", "number"),
        ],
    )
    con.commit()
    con.close()
    res = collect_r3d_residue(db_path)
    assert res["group_count"] == 1 and res["row_count"] == 2
    assert res["sample"][0][1][0]["symbol"] == "AGARWALEYE"


# T-242 r3e -- the five structural fixes from results ckpt_0002 (Eagle's fix note, pack results_ckpt2).
def test_r3e_component_under_a_comprise_heading_keeps_the_heading_family():
    page = (
        "Cash And Cash Equivalents Comprise :\n"
        "Cash\n16.99\n10.49\n"
        "Bank Balance :\nCurrent Account\n0.37\n39.50\n"
        "Total\n17.36\n49.99"
    )
    component = row(measure="other_bank_balances", printed_label="Current Account", value_text="0.37",
                    value=0.37, period="Half Year Ended September 30, 2026")
    plain = row(measure="other_bank_balances", printed_label="Current Account", value_text="0.37",
                value=0.37, period="Year ended March 31, 2026")
    obs.apply_results_row_gates([component], page)
    obs.apply_results_row_gates([plain], "Bank Balance :\nCurrent Account\n0.37")
    assert component["measure"] == "cash_and_cash_equivalents"
    assert "results_component_family" in component["status_reason"]
    assert plain["measure"] == "other_bank_balances"


def test_r3e_component_that_repeats_the_block_total_is_unverified():
    page = (
        "Cash and cash equivalents at the end of the period\n5\n10\n"
        "Cash and Cash Equivalents include:\n"
        "Cash in hand\n2\n2\n"
        "Balances with Banks\n-\n-\n"
        "- on Current/Cash Credit Accounts\n8\n10"
    )
    total_misread = row(measure="cash_and_cash_equivalents", printed_label="- on Current/Cash Credit Accounts",
                        value_text="10", value=10.0, period="30.09.2025")
    component = row(measure="cash_and_cash_equivalents", printed_label="- on Current/Cash Credit Accounts",
                    value_text="8", value=8.0, period="30.09.2026")
    obs.apply_results_row_gates([total_misread], page)
    obs.apply_results_row_gates([component], page)
    assert total_misread["status"] == "unverified"
    assert "results_component_is_total" in total_misread["status_reason"]
    assert component["status"] == "verified"


def test_r3e_cf_line_under_a_title_carried_from_the_previous_page_is_remapped():
    previous = "ARCHIDPLY INDUSTRIES LIMITED\nStatement Of Cash Flow\nAmount in Rs.\nFOR YEAR ENDED 31 MARCH, 2026"
    page = "Amount in Rs.\nPARTICULARS\nInterest Received\n9.92\n10.16"
    income = row(measure="finance_income", printed_label="Interest Received", value_text="10.16", value=10.16,
                 period="FOR YEAR ENDED 31 MARCH, 2025")
    obs.apply_results_row_gates([income], page, previous_page_text=previous)
    assert income["measure"] == "NEW:interest_received_cash_flow"
    assert income["status"] == "unverified"
    assert "results_cash_flow_measure" in income["status_reason"]


def test_r3e_interest_received_on_a_profit_and_loss_page_keeps_its_measure():
    page = "Statement of Profit and Loss\nRevenue from operations\n100.00\nInterest Received\n9.92"
    previous = "Statement of Profit and Loss\nRevenue from operations\n90.00"
    income = row(measure="finance_income", printed_label="Interest Received", value_text="9.92", value=9.92,
                 period="Year ended March 31, 2026")
    obs.apply_results_row_gates([income], page, previous_page_text=previous)
    assert income["measure"] == "finance_income"


def test_r3e_a_cash_flow_line_already_carrying_a_cash_flow_measure_is_kept():
    page = "Statement of Cash Flow\nNet cash flow from investing activities\n(1,742)"
    flow = row(measure="cash_flow.investing", printed_label="Net cash flow from investing activities",
               value_text="(1,742)", value=-1742.0, period="Half year ended September 30, 2026")
    obs.apply_results_row_gates([flow], page)
    assert flow["measure"] == "cash_flow.investing" and flow["status"] == "verified"


def test_r3e_a_stock_measure_takes_no_flow_duration_fill():
    page = (
        "CONSOLIDATED AUDITED STATEMENT OF ASSETS AND LIABILITIES AS AT MARCH 31, 2026\n"
        "As at 31.03.2026\nAs at 31.03.2025\n"
        "EQUITY AND LIABILITIES\nShareholders' Funds\nMinority Interest\n29.76\n216.15"
    )
    filled = row(measure="non_controlling_interest", printed_label="Minority Interest", value_text="29.76",
                 value=29.76, period="Half year ended 31.03.2026", period_source="column_header")
    already = row(measure="non_controlling_interest", printed_label="Minority Interest", value_text="29.76",
                  value=29.76, period="As at 31.03.2026")
    flow = row(measure="revenue_from_operations", printed_label="Revenue from operations", value_text="100.00",
               value=100.0, period="Half year ended 31.03.2026", period_source="column_header")
    obs.apply_results_row_gates([filled], page)
    obs.apply_results_row_gates([already], page)
    obs.apply_results_row_gates([flow], page)
    assert filled["period"] == "As at 31.03.2026" and filled["status"] == "verified"
    assert "results_stock_duration" in filled["status_reason"]
    assert already["period"] == "As at 31.03.2026"
    assert flow["period"] == "Half year ended 31.03.2026"


def test_r3e_a_note_naming_a_subsidiary_sets_the_entity_scope():
    page = (
        "Notes:\n"
        "4. During the quarter ended March 31, 2026, Alankit Imaginations Limited, Wholly owned subsidiary has "
        "issued 3,50,000 fully paid up equity shares at Rs 750 per share ( Face value Rs. 10 Per equity Shares and "
        "Share premium of Rs. 740 per equity share) by way of right Issue fully subscribed by the Holding company\n"
        "5. Figures have been re-grouped to make them comparable"
    )
    subsidiary = row(measure="face_value_per_share", printed_label="Face value", value_text="Rs. 10", value=10.0,
                     unit="Rs.", scale=1.0, period="quarter ended March 31, 2026")
    own_page = ("Notes:\n4. Alankit Limited has issued 3,50,000 fully paid up equity shares at Rs 750 per share "
                "( Face value Re. 1 Per equity Share)")
    own = row(measure="face_value_per_share", printed_label="Face value", value_text="Re. 1", value=1.0,
              unit="Rs.", scale=1.0, period="quarter ended March 31, 2026")
    obs.apply_results_row_gates([subsidiary], page, "Alankit Limited")
    obs.apply_results_row_gates([own], own_page, "Alankit Limited")
    assert subsidiary["entity_scope"] == "subsidiary" and subsidiary["status"] == "unverified"
    assert "results_note_entity" in subsidiary["status_reason"]
    assert own["entity_scope"] == "company" and own["status"] == "verified"


def test_r3e_an_ordinal_is_not_a_figure():
    ordinal = row(measure="NEW:board_report_number", printed_label="Board's Report", value_text="33rd",
                  value=33.0, unit="Lakhs", scale=100000.0, period="financial year ended March 31, 2026")
    quarters = row(measure="NEW:quarters_reported", printed_label="Quarters reported", value_text="3",
                   value=3.0, unit="", unit_family="", scale=1.0, period="Year ended March 31, 2026")
    obs.apply_results_row_gates([ordinal, quarters], "approved the 33rd Board's Report for the 3rd quarter")
    assert ordinal["status"] == "quarantined" and "ordinal" in ordinal["status_reason"]
    assert quarters["status"] == "verified" and quarters["value"] == 3.0

# T-242 r3d2 -- the ambiguous-duration rule abstains outside one measure's two-values-one-date group.
# Each case is the real page (stores under C:/RealityEngine/tg_build/universe_fy27, read-only at build time) and
# every row that printed the graded-R row's label for its date under ANY measure; base copy
# C:/RealityEngine/t242/results_r3d/base.db. Only a second value of the SAME measure is a two-values group.
R3D2_GRADED_R_PAGES = [
    ('BBTCL', "Particulars\n For the year ended \nMarch 31, 2026 \n For the year ended \nMarch 31, 2025 \nCash Flow from operating activities\nProfit/(Loss) before tax\n2,646.34\n \n(783.06)\n \nAdjustments for non-cash items:\nDepreciation / Amortization\n4,261.60\n \n3,113.26\n \n(Profit)/Loss on sale of Fixed Assets\n2.92\n \n(14.79)\n \nFinance cost\n2,272.10\n \n1,766.36\n \nRental Income\n(70.88)\n \n(67.60)\n \nInterest Income\n(46.60)\n \n(8.67)\n \nOther Comprehensive Income\n3.92\n \n0.17\n \nOperating Profit before working capital changes\n9,069.40\n \n4,005.67\n \n(Decrease) / Increase in Trade Payables\n(1,253.51)\n \n1,243.68\n \n(Decrease) / Increase in other current liabilities \n(473.30)\n \n605.42\n \n(Decrease) / Increase in Current provision\n0.01\n \n0.01\n \n(Decrease) / Increase in other non current financial liabilities \n2.38\n \n2.23\n \n(Decrease) / Increase in Non Current Provisions\n32.69\n \n13.47\n \n(Decrease) / Increase in Other Non current liabilities\n6.63\n \n(1.93)\n \nDecrease / (Increase) in inventories\n(2,091.71)\n \n(2,204.83)\n \nDecrease / (Increase) in trade receivables\n(1,192.04)\n \n(842.46)\n \nDecrease / (Increase) in Other Bank balances\n(41.58)\n \n(33.28)\n \nDecrease / (Increase) in Other Current Financial assets\n(11.19)\n \n(3.75)\n \nDecrease / (Increase) in Other current assets\n(708.79)\n \n(610.02)\n \nDecrease / (Increase) in Other non current financial assets\n(222.97)\n \n(46.21)\n \nDecrease / (Increase) in Other non current assets\n180.08\n \n449.75\n \nCash generated from / (used in) Operations\n3,296.10\n \n2,577.76\n \nDirect Taxes Paid (Net of Refunds)\n303.50\n \n286.19\n \nNet cash flow from / (used in) operating activities(A)\n2,992.61\n \n2,291.58\n \nCash Flow from investing activities\nPurchase of Property, Plant & Equipment\n(775.91)\n \n(3,880.94)\n \nPurchase of Intangible assets\n(4.18)\n \n(20.10)\n \nSale of Fixed Assets\n8.00\n \n40.64\n \nInvestment in Debt type instruments\n(56.03)\n \n-\n \nInterest Income\n46.60\n \n8.67\n \nRental Income\n70.88\n \n67.60\n \nNet cash flow from / (used in) investing activities (B)\n(710.63)\n \n(3,784.13)\n \nCash Flows from financing activities\nIncrease (Decrease) in Long Term Borrowings\n(1,993.16)\n \n(338.65)\n \nIncrease (Decrease) in Working Capital Borrowings\n2,433.40\n \n4,025.41\n \nDividend paid\n-\n \n(205.11)\n \nPrinciple payment of lease liabilities\n(438.57)\n \n(191.03)\n \nInterest payment of lease liabilities\n(142.01)\n \n(45.92)\n \nFinance cost paid\n(2,130.09)\n \n(1,720.44)\n \nNet cash flow from / (used in) financing activities (C )\n(2,270.43)\n \n1,524.26\n \nNet Increase / (Decrease) in cash and cash equivalents (A+B+C)\n11.54\n \n31.70\n \nCash and cash equivalents at the beginning of the year\n47.62\n \n15.92\n \nCash and Cash Equivalents at the end of the year\n59.17\n \n47.62\n \nComponents of Cash and Cash Equivalents\nCash on Hand\n13.94\n \n10.65\n \nWith Banks\n45.23\n \n36.97\n \nTotal Cash and Cash Equivalents\n59.17\n \n47.62\n \nfor and on behalf of the Board\nB&B Triplewall Containers Limited\nMANISH KUMAR GUPTA RAVI AGARWAL \n Managing Director WTD & CFO \nDIN: 03568502 DIN: 00636684\nPlace : Bangalore\nDate : 30 May 2026\nB&B Triplewall Containers Limited\nREGD. OFFICE :- Sy.No. 263/2/3, Marsur Madiwal Village, Kasaba Hobli, Anekal Taluk, Bengaluru - 562106 IN\nCIN: L21015KA2011PLC060106\nAUDITED CONSOLIDATED STATEMENT OF CASH FLOWS FOR THE YEAR ENDED 31ST MARCH, 2026\n (Rs In Lakhs)\nMANISH \nKUMAR \nGUPTA\nDigitally signed by \nMANISH KUMAR \nGUPTA \nDate: 2026.05.30 \n17:14:07 +05'30'\nRAVI \nAGARWAL\nDigitally signed by \nRAVI AGARWAL \nDate: 2026.05.30 \n17:18:05 +05'30'",
     [
        {'measure': 'NEW:rental_income_cash_flow', 'printed_label': 'Rental Income', 'printed_axis': 'For the year ended March 31, 2025', 'value_text': '67.60', 'value': 67.6, 'unit': 'Rs In Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'For the year ended March 31, 2025', 'basis': 'consolidated', 'segment': '', 'series_title': 'AUDITED CONSOLIDATED STATEMENT OF CASH FLOWS FOR THE YEAR ENDED 31ST MARCH, 2026', 'group_path': 'Cash Flow from investing activities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:rental_income_cash_flow_adjustment', 'printed_label': 'Rental Income', 'printed_axis': 'For the year ended March 31, 2025', 'value_text': '(67.60)', 'value': -67.6, 'unit': 'Rs In Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'For the year ended March 31, 2025', 'basis': 'consolidated', 'segment': '', 'series_title': 'AUDITED CONSOLIDATED STATEMENT OF CASH FLOWS FOR THE YEAR ENDED 31ST MARCH, 2026', 'group_path': 'Cash Flow from operating activities > Adjustments for non-cash items:', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
     ], 'For the year ended March 31, 2025'),
    ('AAVAS', "Column A\nColumn B\nColumn C [i]\nColumn D[ii]\nColumn E[iii]\nColumn F[iv]\nColumn G[v]\nColumn H(vi]\nColumn H I\nColumn l[vii]\nColumn J\nColumn K\nColumn L\nColumn M\nColumn N\nColumn O\nParticulars\nDescription \nof asset for \nwhich this \ncertificate \nrelate\nExclusive Charge\nPari-Passu Charge\nAssets not \noffered as \nSecurity\nElimination \n(amount in \nnegative)\nRelated to only those items covered by this certificate\nDebt for which \nthis certificate \nbeing issued\nOther Secured \nDebt\nDebt for \nwhich this \ncertificate \nbeing issued\nAssets shared \nby Pari- passu \ndebt holder \n(includes debt \nfor which this \ncertificate is \nissued & other \ndebt with pari- \npassu charge)\nOther \nassets on \nwhich there \nis pari \nPassu \ncharge \n(excluding \nitems\ncovered in \ncolumn F)\nDebt not \nbacked by any \nassets offered \nas\nsecurity(Clause \n1.9 of SEBI DT \nmaster Circular \ndated August \n13, 2025.\ndebt amount \nconsidered \nmore than \nonce (due to \nexclusive plus \npari-passu \ncharge)\n(Total C to H)\nMarket \nValue for \nAssets \ncharged on \nExclusive \nBasis\nCarrying /book value \nfor exclusive charge \nassets where market \nvalue is not \nascertainable or \napplicable (For Eg. \nBank Balance, DSRA \nmarket value is not \napplicable)\nMarket \nValue for \nPari passu \ncharge \nAssets viii\nCarrying value/book \nvalue for pari passu \ncharge assets where \nmarket value is not \nascertainable or \napplicable(For Eg. \nBank Balance, DSRA \nmarket value is not \napplicable)\nTotal Value \n(=K+L+M+N)\nRelating to Column F\nBook Value\nBook Value\nYes/No\nBook Value\nBook Value\nLIABILITIES\nDebt securities to \nwhich this \ncertificate pertains\n1,69,330.13\n1,69,330.13\n#1,69,330.13\n1,69,330.13\nOther debt sharing \npari-passu charge \nwith above debt\n-\nOther Debt\n66,724.07\n66,724.07\nSubordinated debt\n-\nBorrowings\n2,23,857.90\n2,23,857.90\nBanks\n11,45,566.45\n11,45,566.45\nDebt Securities\n10,229.58\n22,554.39\n32,783.97\nOthers\n-\nTrade payables\n691.48\n691.48\nLease Liabilities\n10,279.27\n10,279.27\nProvisions\n1,449.04\n1,449.04\nOthers\n43,588.06\n43,588.06\nTotal\n1,69,330.13\n14,46,378.00\n-\n56,007.85\n22,554.39\n-\n16,94,270.37\n1,69,330.13\n1,69,330.13\nCover on Book \nValue\n112.39%\nCover on Market \nValueIX\nExclusive \nSecurity \nCover Ratio\n112.39%\nPari-Passu \nSecurity Cover \nRatio\nN/A\nNote:\n1. The enclosed figures are based on IND AS Results for the period ended September 2026\n2. Loan(Advances) amount disclosed In column C & O as secured represent principal outstanding and includes accrued interest, if any\n* Loan(Advances) by its existing nature is not tradable instrument and hence are valued as per carrying value/book value.\n# Listed NCD's are valued at cost method not at market value, hence are valued as per carring value/book value.\n•♦This amount Excludes interest Accrued. It represents deposits under lien towards the first loss gurantee provided by the company under the securitization agreements.",
     [
        {'measure': 'NEW:debt_securities_for_which_certificate_issued', 'printed_label': 'Total', 'printed_axis': 'Carrying /book value for exclusive charge assets where market value is not ascertainable or applicable (For Eg. Bank Balance, DSRA market value is not applicable)', 'value_text': '1,69,330.13', 'value': 169330.13, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'September 2026', 'basis': '', 'segment': '', 'series_title': '', 'group_path': 'LIABILITIES', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:debt_securities_for_which_certificate_issued', 'printed_label': 'Total', 'printed_axis': 'Book Value', 'value_text': '1,69,330.13', 'value': 169330.13, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'September 2026', 'basis': '', 'segment': '', 'series_title': '', 'group_path': 'LIABILITIES', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:total_other_secured_debt', 'printed_label': 'Total', 'printed_axis': 'Book Value', 'value_text': '14,46,378.00', 'value': 1446378.0, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'September 2026', 'basis': '', 'segment': '', 'series_title': '', 'group_path': 'LIABILITIES', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:total_pari_passu_assets', 'printed_label': 'Total', 'printed_axis': 'Book Value', 'value_text': '56,007.85', 'value': 56007.85, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'September 2026', 'basis': '', 'segment': '', 'series_title': '', 'group_path': 'LIABILITIES', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:total_other_assets_offered_as_security', 'printed_label': 'Total', 'printed_axis': 'Book Value', 'value_text': '22,554.39', 'value': 22554.39, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'September 2026', 'basis': '', 'segment': '', 'series_title': '', 'group_path': 'LIABILITIES', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:total_liabilities_covered_by_certificate', 'printed_label': 'Total', 'printed_axis': '(Total C to H)', 'value_text': '16,94,270.37', 'value': 1694270.37, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'September 2026', 'basis': '', 'segment': '', 'series_title': '', 'group_path': 'LIABILITIES', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:debt_securities_for_which_certificate_issued', 'printed_label': 'Total', 'printed_axis': 'Total Value (=K+L+M+N)', 'value_text': '1,69,330.13', 'value': 169330.13, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'September 2026', 'basis': '', 'segment': '', 'series_title': '', 'group_path': 'LIABILITIES', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
     ], 'September 2026'),
    ('AKSHOPTFBR', 'AKSH OPTIFIBRE LIMITED \nCorporate Identification No. (CIN) : L24305RJ1986PLC016132 \nSTANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES \nRa tn dakhs \nQuarter Ended \nYear Ended \nSl. No. |(Particulars \nMar-26 \nDec-25 \nMar-25 \nMar-26 \nMar-25 \n(Audited)# \n(Unaudited) \n(Audited)# \n(Audited) \n(Audited) \n1 \nSegment Revenue \na. Manufacturing \n1,334.41 \n1,372.38 \n1,967.33 \n6,248.38 \n7,511.38 \nb. Services \n2,684.82 \n1,292.38 \n1,211.33 \n6,322.28 \n5,201.10 \nTotal \n4,019.23 \n2,664.76 \n3,178.66 \n12,570.66 \n12,712.48 \n2 \nSegment Results ( Profit / (Loss)) \n(before tax and finance costs) \na. Manufacturing \n(276.77), \n(300.86)! \n(369.73) \n(770.93)| \n(1,505.14), \nb. Services \n272.10 \n69.31 \n90.22 \n437.69 \n392.14 \nTotal \n(4.67) \n(231.55) \n(279.51)| \n(333.24) \n(1,113.00) \n(Add)/Less - Finance Costs \n155.62 \n169.05 \n436.05 \n667.79 \n856.92 \n- \nInterest (Income) \n(109.79) \n(22.86) \n(54.30) \n(201.36), \n(147.56), \n- \n_Unallocated Expenses / (Income) \n77.85 \n92.52 \n101.63 \n363.86 \n417.55 \nProfit \n/ (Loss) after finance costs but before Exceptional Items \n(128.35) \n(470.26) \n(762.89) \n(1,163.53) \n(2,239.91) \nExceptional Income/(Expense) \n187.85 \n(35.54) \n(1,208.84)| \n57.13 \n38.73 \nProfit / (Loss) from Ordinary Activities before tax \n59.50 \n(505.80) \n(1,971.73)| \n_(1,106.40) \n(2,201.18) \n3 \nSegment Assets \n* \n|a. Manufacturing \n12,458.49 \n12,379.20 \n13,209.31 \n12,458.49 \n13,209.31 \nb. Services \n6,995.58 \n5,742.92 \n5,421.26 \n6,995.58 \n5,421.26 \nc. Unallocated \n4,948.75 \n4,727.33 \n4,387.56 \n4,948.75 \n4,387.56 \nTotal \n24,402.82 \n22,849.45 \n23,018.13 \n24,402.82 \n23,018.13 \n4 \nSegment Liabilities \na. Manufacturing \n12,034.21 \n11,341.01 \n10,723.18 \n12,034.21 \n10,723.18 \nb. Services \n3,867.67 \n3,194.62 \n2,925.98 \n3,867.67 \n2,925.98 \nc. Unallocated \n415.03 \n266.22 \n439.29 \n415.03 \n439.29 \nTotal \n16,316.91 \n14,801.85 \n14,088.45 \n16,316.91 \n14,088.45 \n# Refer Note no. 11',
     [
        {'measure': 'NEW:segment_liabilities', 'printed_label': 'b. Services', 'printed_axis': 'Mar-26', 'value_text': '3,867.67', 'value': 3867.67, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-26', 'basis': 'standalone', 'segment': 'Services', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Liabilities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'revenue.mix', 'printed_label': 'b. Services', 'printed_axis': 'Mar-26', 'value_text': '2,684.82', 'value': 2684.82, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-26', 'basis': 'standalone', 'segment': 'Services', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Revenue', 'record_type': 'number', 'status': 'unverified', 'status_reason': "basis_conflict: same measure/label/period with different values and no distinct basis; results_period_duration_missing: no column duration header found for flow period 'Mar-26'"},
        {'measure': 'revenue.mix', 'printed_label': 'b. Services', 'printed_axis': 'Mar-26', 'value_text': '6,322.28', 'value': 6322.28, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-26', 'basis': 'standalone', 'segment': 'Services', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Revenue', 'record_type': 'number', 'status': 'unverified', 'status_reason': "basis_conflict: same measure/label/period with different values and no distinct basis; results_period_duration_missing: no column duration header found for flow period 'Mar-26'"},
        {'measure': 'NEW:segment_result_before_tax_and_finance_costs', 'printed_label': 'b. Services', 'printed_axis': 'Mar-26', 'value_text': '272.10', 'value': 272.1, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-26', 'basis': 'standalone', 'segment': 'Services', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Results ( Profit / (Loss)) > (before tax and finance costs)', 'record_type': 'number', 'status': 'unverified', 'status_reason': 'basis_conflict: same measure/label/period with different values and no distinct basis'},
        {'measure': 'NEW:segment_result_before_tax_and_finance_costs', 'printed_label': 'b. Services', 'printed_axis': 'Mar-26', 'value_text': '437.69', 'value': 437.69, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-26', 'basis': 'standalone', 'segment': 'Services', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Results ( Profit / (Loss)) > (before tax and finance costs)', 'record_type': 'number', 'status': 'unverified', 'status_reason': 'basis_conflict: same measure/label/period with different values and no distinct basis'},
        {'measure': 'NEW:segment_assets', 'printed_label': 'b. Services', 'printed_axis': 'Mar-26', 'value_text': '6,995.58', 'value': 6995.58, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-26', 'basis': 'standalone', 'segment': 'Services', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Assets', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
     ], 'Mar-26'),
    ('AKSHOPTFBR', 'AKSH OPTIFIBRE LIMITED \nCorporate Identification No. (CIN) : L24305RJ1986PLC016132 \nSTANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES \nRa tn dakhs \nQuarter Ended \nYear Ended \nSl. No. |(Particulars \nMar-26 \nDec-25 \nMar-25 \nMar-26 \nMar-25 \n(Audited)# \n(Unaudited) \n(Audited)# \n(Audited) \n(Audited) \n1 \nSegment Revenue \na. Manufacturing \n1,334.41 \n1,372.38 \n1,967.33 \n6,248.38 \n7,511.38 \nb. Services \n2,684.82 \n1,292.38 \n1,211.33 \n6,322.28 \n5,201.10 \nTotal \n4,019.23 \n2,664.76 \n3,178.66 \n12,570.66 \n12,712.48 \n2 \nSegment Results ( Profit / (Loss)) \n(before tax and finance costs) \na. Manufacturing \n(276.77), \n(300.86)! \n(369.73) \n(770.93)| \n(1,505.14), \nb. Services \n272.10 \n69.31 \n90.22 \n437.69 \n392.14 \nTotal \n(4.67) \n(231.55) \n(279.51)| \n(333.24) \n(1,113.00) \n(Add)/Less - Finance Costs \n155.62 \n169.05 \n436.05 \n667.79 \n856.92 \n- \nInterest (Income) \n(109.79) \n(22.86) \n(54.30) \n(201.36), \n(147.56), \n- \n_Unallocated Expenses / (Income) \n77.85 \n92.52 \n101.63 \n363.86 \n417.55 \nProfit \n/ (Loss) after finance costs but before Exceptional Items \n(128.35) \n(470.26) \n(762.89) \n(1,163.53) \n(2,239.91) \nExceptional Income/(Expense) \n187.85 \n(35.54) \n(1,208.84)| \n57.13 \n38.73 \nProfit / (Loss) from Ordinary Activities before tax \n59.50 \n(505.80) \n(1,971.73)| \n_(1,106.40) \n(2,201.18) \n3 \nSegment Assets \n* \n|a. Manufacturing \n12,458.49 \n12,379.20 \n13,209.31 \n12,458.49 \n13,209.31 \nb. Services \n6,995.58 \n5,742.92 \n5,421.26 \n6,995.58 \n5,421.26 \nc. Unallocated \n4,948.75 \n4,727.33 \n4,387.56 \n4,948.75 \n4,387.56 \nTotal \n24,402.82 \n22,849.45 \n23,018.13 \n24,402.82 \n23,018.13 \n4 \nSegment Liabilities \na. Manufacturing \n12,034.21 \n11,341.01 \n10,723.18 \n12,034.21 \n10,723.18 \nb. Services \n3,867.67 \n3,194.62 \n2,925.98 \n3,867.67 \n2,925.98 \nc. Unallocated \n415.03 \n266.22 \n439.29 \n415.03 \n439.29 \nTotal \n16,316.91 \n14,801.85 \n14,088.45 \n16,316.91 \n14,088.45 \n# Refer Note no. 11',
     [
        {'measure': 'NEW:unallocated_liabilities', 'printed_label': 'c. Unallocated', 'printed_axis': 'Mar-25', 'value_text': '439.29', 'value': 439.29, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-25', 'basis': 'standalone', 'segment': 'Unallocated', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Liabilities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:unallocated_assets', 'printed_label': 'c. Unallocated', 'printed_axis': 'Mar-25', 'value_text': '4,387.56', 'value': 4387.56, 'unit': 'Rs in lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Mar-25', 'basis': 'standalone', 'segment': 'Unallocated', 'series_title': 'STANDALONE SEGMENT WISE REVENUE, RESULTS, ASSETS & LIABILITIES', 'group_path': 'Segment Assets', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
     ], 'Mar-25'),
    ('AEONXDIGI', '(₹ In Lakhs)\nSr. \nNo.\nA\nCASH FLOW FROM OPERATING ACTIVITIES\nNet (Loss)/Profit before Tax\n40.62\n \n(109.35)\n \nAdjustments for:\nDepreciation and Amortization Expenses\n71.38\n \n171.45\n \nForeign Exchange (Gain) / Loss\n(4.74)\n \n(6.20)\n \nImpairment on receivables \n3.43\n \n(13.54)\n \n(Profit)/Loss on sale of Investments\n-\n \n(13.18)\n \nLoss / (profit) on Asset Discarded\n-\n \n2.03\n \nInterest & Finance Charges\n12.91\n \n18.47\n \nInterest Received\n(218.03)\n \n(135.05)\n \n(402.77)\n \n(243.73)\n \nOperating Profit Before Working Capital Changes\n(94.43)\n \n(353.08)\n \nAdjustments for changes in working capital\nDecrease/(Increase) in Receivables\n(254.01)\n \n(503.41)\n \nDecrease/(Increase) Other Current Financial assets\n-\n \n-\n \nDecrease/(Increase) Other Non Current Financial Assets\n(8.52)\n \n0.99\n \nDecrease/(Increase) Other Current Assets\n(32.72)\n \n(44.61)\n \nIncrease/(Decrease) in Payables\n(96.75)\n \n539.36\n \nIncrease/(Decrease) in Other Current Liabilities\n89.29\n \n176.76\n \nIncrease/(Decrease) in Other Financial Liabilities\n(18.74)\n \n60.35\n \nIncrease/(Decrease) in Short Term Provision & Lease Liability\n(83.29)\n \n84.19\n \nIncrease/(Decrease) in Long term Provision & Lease Liability\n9.98\n \n85.95\n \nForeign Exchange (Gain) / Loss\n4.74\n \n6.20\n \nImpairment on receivables \n(3.43)\n \n(393.47)\n \n13.54\n \n419.32\n \nCash generated from operations\n(487.90)\n \n66.24\n \nIncome Tax Paid\n(152.16)\n \n(188.19)\n \nNET CASH FLOW FROM OPERATING ACTIVITIES (A)\n(640.06)\n \n(121.95)\n \nB\nCASH FLOW FROM INVESTING ACTIVITIES\nPurchase of Property, Plant and Equipment\n(4.53)\n \n(41.28)\n \nPurchase of Intangible Assets\n(137.23)\n \n(427.75)\n \nProceeds / (Deposit) from Term deposit and margin money \nwith bank\n(4.30)\n \n(4.97)\n \nRealised and Unrealised Gain on Investment\n-\n \n13.18\n \nDecrease/(Increase) in Investments\n-\n \n(146.06)\n \n594.30\n \n133.48\n \nNET CASH FLOW FROM INVESTING ACTIVITIES (B)\n(146.06)\n \n133.48\n \nC\nCASH FLOW FROM FINANCING ACTIVITIES\nChanges in Working Capital Loan (Net)\n295.01\n \n-\n \nDecrease/(Increase) in Loans given\n201.28\n \n(298.58)\n \nShare Application Money Received for Share Allotment\n3.45\n \n-\n \nDividend Paid \n-\n \n(46.00)\n \nInterest Received\n218.03\n \n402.77\n \nInterest paid\n(12.91)\n \n704.86\n \n(18.47)\n \n39.71\n \nNET CASH FLOW FROM FINANCING ACTIVITIES (C)\n704.86\n \n39.71\n \n(81.26)\n \n51.24\n \nCash and Cash equivalents as at 01.04.2026\n528.15\n \n476.91\n \nCash and Cash equivalents as at 30.09.2026\n446.89\n \n528.15\n \nCash & Cash Equivalents\nAs at 30/09/2026\nAs at 31/03/2026\nCash in Hand\n0.78\n \n1.93\n \nCash at Bank\n446.11\n \n526.22\n \nCash & Cash Equivalents as Stated\n446.89\n \n528.15\n \nAEONX DIGITAL TECHNOLOGY LIMITED\nSTANDALONE CASH FLOW STATEMENT FOR THE HALF YEAR ENDED SEPTEMBER 30, 2026\nParticulars\nHalf Year Ended September 30, \n2026\nYear Ended March 31, 2026\nNET INCREASE/(DECREASE) IN CASH & CASH EQUIVALENTS\n(A+B+C)',
     [
        {'measure': 'changes_in_working_capital', 'printed_label': 'Impairment on receivables', 'printed_axis': 'Half Year Ended September 30, 2026', 'value_text': '(393.47)', 'value': -393.47, 'unit': '₹ In Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Half Year Ended September 30, 2026', 'basis': 'standalone', 'segment': '', 'series_title': 'STANDALONE CASH FLOW STATEMENT FOR THE HALF YEAR ENDED SEPTEMBER 30, 2026', 'group_path': 'A > CASH FLOW FROM OPERATING ACTIVITIES > Adjustments for changes in working capital', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:impairment_on_receivables_adjustment', 'printed_label': 'Impairment on receivables', 'printed_axis': 'Half Year Ended September 30, 2026', 'value_text': '3.43', 'value': 3.43, 'unit': '₹ In Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Half Year Ended September 30, 2026', 'basis': 'standalone', 'segment': '', 'series_title': 'STANDALONE CASH FLOW STATEMENT FOR THE HALF YEAR ENDED SEPTEMBER 30, 2026', 'group_path': 'A > CASH FLOW FROM OPERATING ACTIVITIES > Adjustments for:', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:impairment_on_receivables_working_capital_adjustment', 'printed_label': 'Impairment on receivables', 'printed_axis': 'Half Year Ended September 30, 2026', 'value_text': '(3.43)', 'value': -3.43, 'unit': '₹ In Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Half Year Ended September 30, 2026', 'basis': 'standalone', 'segment': '', 'series_title': 'STANDALONE CASH FLOW STATEMENT FOR THE HALF YEAR ENDED SEPTEMBER 30, 2026', 'group_path': 'A > CASH FLOW FROM OPERATING ACTIVITIES > Adjustments for changes in working capital', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
     ], 'Half Year Ended September 30, 2026'),
    ('AMITSEC', '! \nI I \nI I I I \n! \nI I I \nI I \nI \nI i \n! i \ni \nI \nI \nI \nI ! I I \nS1\' No. \nI \nI \nI \nI \nI \n1 \n2 \n3 \n-\n-\nReporting of Segment wise Revenue, Results and Capital Employed along with the Segment results \nFor the Quarter Ended 30th June, 2026 \nParticulars \n3 months ended \n30.06.2026 \nUnaudited \nQuarter Ended \nPreceding \n3 months ended \n31.03.2026 \nUnaudited \n; Corresponding \n3 \nmonths ended in the \nprevious year \n30.06.2025 \nUnaudited \n(Amount Rs in Lacs) \nYear to date figures for \nYear Ended \n31.03.2026 \nAudited \n---------\x01----------+-------- - -, - - - -\n-\n- -\n- -1-----------1 \n~egm_ent Revenue \n-\n1- ----------1-- ----- - -\n~--\n-- -\n-- ---------------1 \njl ~ egment - Trading Division \nB - Segment - Investment Division \n~~ ·=--~==~__=\'-\'--\' _____ \n1------2-\'5-\n. 7-7-+------69~~ i_ _ \n_1----------l~.~\n67_\'+---------- -\'2-~\n.2~- _ _ _ \n2.08 \n33.92 \n264.02 \n- --- --- - ------\n8.81 \n- ----1-----------1 \nTotal \n27.44 \n71.58 i \n36.00 \n272.83 \n--\n--\n- -------- ---------\nL e s ~ : Inter Segment Revenue \nI-------,~f___-----\n-\n-\n~ \nNet Sales/Income From Operations \n27.44 I \n36.00 \n272.83 \n71.58 i \nI \n- ---\nSegm~nt Results \nA - Segment - Trading Division \nB - Segment - Investment Division \n! \n--t-\n, --\n2.95 1 __ \n-- -\n2.28 I \n2.BO I \n2.08 \n-\n-\n- ------- ---------\n2.73 \n14.14 \n8.81 \n1.67 , \nTotal Segment Profit before Interest & \nTax \nI \n5.23 , \n22.94 \n4.47 \n4.81 \nLess: \n! \nI \n--\n~-\n(i) Interest Expenses \n+-\n-\n(ii) Other Unallocable Income net of \nExpenditure \n0.56 I \n2.80 \n8.34 \nProfit before Tax \n1.46 I \n4.67 I \n2.01 \n14.61 \nLess: T".x Expenses \nI \n0.50 \n3.76 \n-\n- --- --- - --------\n0.37 f------ ! .17 I \nTotal Profit after Tax \n1.09 I \n3.50 \n1.51 \n10.85 \n-\nCapital Employed \n--+ \nI \n-\n---------+---\n-\n-\n--- --\n~ \nSegment Assets - Segment Laibilities \nA - S_egment - Trading Division \n32.43 \n76.08 \n--- -\n------- -\n41.35 \n~----~------- I--------_+-------- -\nI \nB - Segment - Investment Division \nC - Unallocated \n\'1,310.51 \n1,270.14 \n0.00 \n13.83 \n_________ -"-\'1,\'-=-3""-18"-\'.4-=-5"-+ ________ 127 o.} ± c \n1.34 \n13.83 \nTotal \n1,361.14 \n1,360.05 \n1,342.94 \n1,360.05 \nPLACE: NDORE \nDATE: 13 August 2026',
     [
        {'measure': 'NEW:segment_assets_less_segment_liabilities', 'printed_label': 'A - Segment - Trading Division', 'printed_axis': 'Corresponding 3 months ended in the previous year 30.06.2025', 'value_text': '32.43', 'value': 32.43, 'unit': 'Rs in Lacs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Corresponding 3 months ended in the previous year 30.06.2025', 'basis': '', 'segment': 'A - Segment - Trading Division', 'series_title': 'Reporting of Segment wise Revenue, Results and Capital Employed along with the Segment results', 'group_path': 'Capital Employed > Segment Assets - Segment Laibilities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'revenue.mix', 'printed_label': 'A - Segment - Trading Division', 'printed_axis': 'Corresponding 3 months ended in the previous year 30.06.2025', 'value_text': '33.92', 'value': 33.92, 'unit': 'Rs in Lacs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Corresponding 3 months ended in the previous year 30.06.2025', 'basis': '', 'segment': 'A - Segment - Trading Division', 'series_title': 'Reporting of Segment wise Revenue, Results and Capital Employed along with the Segment results', 'group_path': 'Segment Revenue', 'record_type': 'number', 'status': 'verified', 'status_reason': 'parts sum to the printed total 36.00'},
        {'measure': 'NEW:segment_result', 'printed_label': 'A - Segment - Trading Division', 'printed_axis': 'Corresponding 3 months ended in the previous year 30.06.2025', 'value_text': '2.73', 'value': 2.73, 'unit': 'Rs in Lacs', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Corresponding 3 months ended in the previous year 30.06.2025', 'basis': '', 'segment': 'A - Segment - Trading Division', 'series_title': 'Reporting of Segment wise Revenue, Results and Capital Employed along with the Segment results', 'group_path': 'Segment Results', 'record_type': 'number', 'status': 'unverified', 'status_reason': "group_path is not in the page text layer: 'Segment Results'"},
     ], 'Corresponding 3 months ended in the previous year 30.06.2025'),
    ('ASARFI', 'Standalone Unaudited Balance Sheet as at 30 June 2026\n(` in Lakhs)\n30-Jun-26\n31-Mar-26\nUnaudited\n Audited \nI. EQUITY AND LIABILITIES\n \n(1) Shareholders’ funds\n \n(a) Share Capital\n1,967.73\n \n1,967.73\n \n(b) Reserves and Surplus\n8,310.50\n \n7,883.66\n \nTotal\n10,278.23\n \n9,851.39\n \n(2) Non-current liabilities\n(a) Long-term Borrowings\n3,492.01\n \n3,500.88\n \n(b) Deferred Tax Liabilities (net)\n290.10\n \n302.33\n \n(c) Other Long-term Liabilities\n720.11\n \n724.35\n \n(d) Long-term Provisions\n189.75\n \n109.34\n \nTotal\n4,691.97\n \n4,636.90\n \n(3) Current liabilities\n(a) Short-term Borrowings\n1,987.62\n \n2,254.85\n \n(b) Trade Payables\n - Due to Micro and Small Enterprises\n1,752.43\n \n1,463.32\n \n - Due to Others\n199.18\n \n193.04\n \n(c) Other Current Liabilities\n1,060.94\n \n928.17\n \n(d) Short-term Provisions\n147.74\n \n61.60\n \nTotal\n5,147.91\n \n4,900.98\n \nTotal Equity and Liabilities\n20,118.11\n \n19,389.27\n \nII. ASSETS\n(1) Non-current assets\n(a) Property, Plant and Equipment and Intangible Assets\n (i) Property, Plant and Equipment\n10,545.33\n \n10,814.13\n \n (ii) Capital Work-in-progress\n396.70\n \n175.91\n \n(b) Non-current Investments\n1.00\n \n1.00\n \n(c) Long term Loans and Advances\n359.36\n \n280.45\n \n(d) Other Non-current Assets\n1,143.30\n \n1,011.99\n \nTotal\n12,445.69\n \n12,283.48\n \n(2) Current assets\n(a) Inventories\n310.68\n \n321.87\n \n(b) Trade Receivables\n6,464.56\n \n5,406.67\n \n(c) Cash and cash equivalents\n804.39\n \n1,293.71\n \n(d) Short-term Loans and Advances\n73.08\n \n53.84\n \n(e) Other Current Assets\n19.71\n \n29.70\n \nTotal\n7,672.42\n \n7,105.79\n \nTotal Assets\n20,118.11\n \n19,389.27\n \n-\n \n-\n \nFor and on behalf of the Board of\nPlace: Dhanbad\nAsarfi Hospital Limited\nDate: 07.08.2026\nUdai Pratap Singh\nMadhuri Singh\nHarendra Singh\nCS Sudipa Singh\nManaging Director\nDirector\nCFO\nCompany Secretary\n \n08453794\n6562038\nBANPS9243R\nACS No. 56989\nAsarfi Hospital Limited\n(CIN: L85110JH2005PLC011673)\n(Address: Baramuri, Bishunpur Polytechnic, Dhanbad)\nAs at\nParticulars',
     [
        {'measure': 'total_non_current_assets', 'printed_label': 'Total', 'printed_axis': '30-Jun-26', 'value_text': '12,445.69', 'value': 12445.69, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': '30-Jun-26', 'basis': 'standalone', 'segment': '', 'series_title': 'Standalone Unaudited Balance Sheet as at 30 June 2026', 'group_path': 'II. ASSETS > (1) Non-current assets', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'total_equity', 'printed_label': 'Total', 'printed_axis': '30-Jun-26', 'value_text': '10,278.23', 'value': 10278.23, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': '30-Jun-26', 'basis': 'standalone', 'segment': '', 'series_title': 'Standalone Unaudited Balance Sheet as at 30 June 2026', 'group_path': 'I. EQUITY AND LIABILITIES > (1) Shareholders’ funds', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'total_non_current_liabilities', 'printed_label': 'Total', 'printed_axis': '30-Jun-26', 'value_text': '4,691.97', 'value': 4691.97, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': '30-Jun-26', 'basis': 'standalone', 'segment': '', 'series_title': 'Standalone Unaudited Balance Sheet as at 30 June 2026', 'group_path': 'I. EQUITY AND LIABILITIES > (2) Non-current liabilities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'total_current_liabilities', 'printed_label': 'Total', 'printed_axis': '30-Jun-26', 'value_text': '5,147.91', 'value': 5147.91, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': '30-Jun-26', 'basis': 'standalone', 'segment': '', 'series_title': 'Standalone Unaudited Balance Sheet as at 30 June 2026', 'group_path': 'I. EQUITY AND LIABILITIES > (3) Current liabilities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'total_current_assets', 'printed_label': 'Total', 'printed_axis': '30-Jun-26', 'value_text': '7,672.42', 'value': 7672.42, 'unit': 'Lakhs', 'unit_family': 'money', 'scale': 100000.0, 'period': '30-Jun-26', 'basis': 'standalone', 'segment': '', 'series_title': 'Standalone Unaudited Balance Sheet as at 30 June 2026', 'group_path': 'II. ASSETS > (2) Current assets', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
     ], '30-Jun-26'),
    ('AVONMORE', 'Avonmore Capital & Management Services Limited \nRegistered Office: Level 5, Grande Palladium, 175 CST Road, Off BKC Kalina, Santacruz (E) Mumbai - 400098 \nStandalone un-audited Segment wise revenue, resuits , Segment assets and Segment liabilities for the Quarter/Half year ended \n30 Sept 2026 \n(Rs. In Lakh ) \nQuarter ended \nHalf year ended \nYear \nended \n30, \n30, \n30, \nt 30, \nv \ne e Sept30. \n| sept 30, 2028 \nSoptat: \n| mars1, 2028 \nUnaudited | Unaudited | Unaudited | Unaudited | Unaudited \nAudited \nSegment Revenue \n(a) Investments activities \n- \n. \no \n" \n- \n\\ \n(b) Debt and equity market operations \n59 \n43 \n76 \n102 \n163 \n236 \n(c) Advisory fees \n- \n- \n- \n- \n- \n100 \n(d) Finance activities \n162 \n190 \n189 \n352 \n409 \n735 \nIncome from Operations \n221 \n233 \n265 \n454 \n572 \n1,071 \nSegment results \nProfit before tax and interest from each \nsegment \n(a) Investments aclivities \n= \no \n- \n- \n- \n2 \n(b) Debt and equity market operations \n14 \n8 \n76 \n22 \n163 \n214 \n(c) Advisory fees \n- \n- \n- \n- \n3 \n84 \n(d) Finance activities \n5 \n17 \n21 \n22 \n38 \n(184) \nTotal \n19 \n25 \n97 \n44 \n201 \n114 \nLess. \n- \n1) Unallocable interest \nol \no \n= \n= \n£y \n= \n2) Other unallocable expenditure (net off \n- \n- \n- \n- \n% \n- \nunallocable income) \n3) Exceptional Income \n= \n" \n= \n- \n= \n7 \nProfit before tax \n19 \n25 \n97 \n44 \n201 \n114 \nSegment Assots \n(a) Investments activities \n19,070 \n16,529 \n16,417 \n19,070 \n16,417 \n16,417 \n(b) Debt and equity market operations \n1511 \n590 \n774 \n1511 \n774 \n878 \n(c) Advisory fees \n& \ni \nx \n2 \n2 \n- \n(d) Finance activities \n5,793 \n9,940 \n7929 \n5,793 \n7,929 \n8,183 \n(e) Unallocated \n1,162 \n749 \n955 \n1,162 \n955 \n1,151 \nTotal Segment Assets \n27,536 \n27,808 \n26,075 \n27,536 \n26,075 \n26,629 \nSegment Liabilities \n(a) Investments activities \n9,249 \n9,557 \n8,094 \n9,249 \n8,004 \n8,342 \n(b) Debt and equity market operations \n5 \n5 \n5 \n5 \n85 \n5 \n(c) Advisory fees \n- \nE \ny \n- \n- \n- \n(d) Finance activities \n96 \n79 \n387 \n96 \n307 \n185 \n(e) Unallocated \n& \n- \n- \n- \n- \n- \n9,350 \n9,641 \n8,486 \n9,350 \n8,486 \n8,502 \nFor and on behalf of the B \nAvonmore Capital & \nices Limited \nAshok Kum \nPlace: New Delhi \nManaging Di \nDate: 2nd Nov - 2026 \nDIN : 02590928',
     [
        {'measure': 'NEW:segment_liabilities', 'printed_label': '(a) Investments activities', 'printed_axis': 'Unaudited', 'value_text': '9,249', 'value': 9249.0, 'unit': 'Rs. In Lakh', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Sept 30, 2026', 'basis': 'standalone', 'segment': 'Investments activities', 'series_title': 'Standalone un-audited Segment wise revenue, resuits , Segment assets and Segment liabilities for the Quarter/Half year ended 30 Sept 2026', 'group_path': 'Segment Liabilities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:segment_assets', 'printed_label': '(a) Investments activities', 'printed_axis': 'Unaudited', 'value_text': '19,070', 'value': 19070.0, 'unit': 'Rs. In Lakh', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Sept 30, 2026', 'basis': 'standalone', 'segment': 'Investments activities', 'series_title': 'Standalone un-audited Segment wise revenue, resuits , Segment assets and Segment liabilities for the Quarter/Half year ended 30 Sept 2026', 'group_path': 'Segment Assets', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:segment_assets', 'printed_label': '(a) Investments activities', 'printed_axis': 'Unaudited', 'value_text': '19,070', 'value': 19070.0, 'unit': 'Rs. In Lakh', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Sept 30, 2026', 'basis': 'standalone', 'segment': 'Investments activities', 'series_title': 'Standalone un-audited Segment wise revenue, resuits , Segment assets and Segment liabilities for the Quarter/Half year ended 30 Sept 2026', 'group_path': 'Segment Assets', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
        {'measure': 'NEW:segment_liabilities', 'printed_label': '(a) Investments activities', 'printed_axis': 'Unaudited', 'value_text': '9,249', 'value': 9249.0, 'unit': 'Rs. In Lakh', 'unit_family': 'money', 'scale': 100000.0, 'period': 'Sept 30, 2026', 'basis': 'standalone', 'segment': 'Investments activities', 'series_title': 'Standalone un-audited Segment wise revenue, resuits , Segment assets and Segment liabilities for the Quarter/Half year ended 30 Sept 2026', 'group_path': 'Segment Liabilities', 'record_type': 'number', 'status': 'verified', 'status_reason': ''},
     ], 'Sept 30, 2026'),
]


@pytest.mark.parametrize("symbol,page,specs,expected_period", R3D2_GRADED_R_PAGES,
                         ids=[f"{case[0]}-{case[2][0]['measure']}" for case in R3D2_GRADED_R_PAGES])
def test_r3d2_graded_r_row_keeps_its_period_and_status(symbol, page, specs, expected_period):
    rows = [row(**spec) for spec in specs]
    obs.apply_results_row_gates(rows, page, symbol)
    target = rows[0]
    assert target["period"] == expected_period
    assert target["status"] == "verified"
    assert "results_period_duration_ambiguous" not in target["status_reason"]


# T-242 r3f -- results ckpt_0003/0004 fix notes.  Each case is a graded row's own printed value and the pack page
# (C:/RealityEngine/t242/results_ckpt3|4) that printed it.
def test_r3f_ocr_bracket_pair_is_negative_and_split_digits_rejoin():
    alokinds = row(measure="NEW:net_loss_for_the_period", printed_label="Net Loss for the period {7-8)",
                   value_text="{171.56)", value=171.56, unit="Rs. in Crore", scale=10000000.0,
                   period="Quarter ended 30.06.2025")
    atgl = row(measure="NEW:effective_portion_of_loss_gain_on_cash_flow_hedge",
               printed_label="-Effective portion of (loss)/gain on cash flow hedge", value_text="(2 69)",
               value=-2.0, unit="Rs. crore", scale=10000000.0, period="Quarter ended June 30, 2025")
    split = row(measure="revenue.mix", printed_label="Aerospace", value_text="3, 221 59", value=3221.59,
                unit="Rs. in Millions", scale=1000000.0)
    plain = row(value_text="171.56", value=171.56)
    bracketed = row(value_text="(171.56)", value=-171.56)
    rows = [alokinds, atgl, split, plain, bracketed]
    obs.apply_results_row_gates(rows, "")
    assert alokinds["value"] == -171.56 and "results_ocr_value" in alokinds["status_reason"]
    assert atgl["value"] == -2.69 and "results_ocr_value" in atgl["status_reason"]
    assert split["value"] == 3221.59
    assert plain["value"] == 171.56 and bracketed["value"] == -171.56
    assert "results_ocr_value" not in plain["status_reason"]
    assert "results_ocr_value" not in bracketed["status_reason"]


def test_r3f_garbled_ocr_value_is_quarantined():
    garbled = row(measure="changes_in_payables", printed_label="Adjustments for trade payables",
                  value_text="-2,1::!.J.:?.9", value=-2.1, unit="Lakhs", scale=100000.0)
    clean = row(measure="changes_in_payables", printed_label="Adjustments for trade payables",
                value_text="2,100.90", value=2100.9, unit="Lakhs", scale=100000.0)
    money = row(measure="revenue_from_operations", printed_label="Revenue", value_text="Rs. 1,234.56",
                value=1234.56, unit="Lakhs", scale=100000.0)
    rows = [garbled, clean, money]
    obs.apply_results_row_gates(rows, "")
    assert garbled["status"] == "quarantined" and "results_garbled_value" in garbled["status_reason"]
    assert clean["status"] == "verified" and money["status"] == "verified"


AZADIND_CF_PAGE = (
    "AZAD INDUSTRIES LIMITED\nStatement of Cash Flow for the year ended March 31, 2026\n"
    "B. Cash flow from investing activities\n"
    "Interest received 123.48 89.13\nExtraordinary items (0.09)\nLong term investments (1,279.00)"
)
APTUS_CF_PAGE = (
    "APTUS VALUE HOUSING FINANCE LIMITED\nStatement of Cash Flows for the year ended March 31, 2025\n"
    "(INR in lakhs)\nCash flows from financing activities\n"
    "Issue of equity shares (including securities premium) 1,735.82 1,532.16\n"
    "Dividend paid (22,508.10) (22,467.96)"
)
AAYUSH_BS_PAGE = (
    "AAYUSH WELLNESS LIMITED\nSTATEMENT OF ASSETS AND LIABILITIES FOR THE HALF YEAR ENDED 30TH SEPTEMBER, 2026\n"
    "(Rs. in lakhs}\nCONSOLIDATED\nParticulars\nAs at 30-Sep-2026\nAs at 31-Mar-2026\n"
    "Non-current Liabilities\n(a) Financial liabilities\n(i) Borrowings\n460.53\n473.53\n"
    "(b) Provisions\n0.00\n0.00\n( c) Deferred tax liabilities (Net)\n0.00\n0.00\n"
    "Total Non-current Liabilities\n460.53\n473.53"
)


def test_r3f_measure_from_the_section_cash_flow_generic_twin_and_pnl_charge():
    extraordinary = row(measure="exceptional_items", printed_label="Extraordinary items", value_text="(0.09)",
                        value=-0.09, unit="Lakhs", scale=100000.0, period="For the Year ended 31 March, 2025")
    equity_issue = row(measure="equity_share_capital",
                       printed_label="Issue of equity shares (including securities premium)",
                       value_text="1,532.16", value=1532.16, unit="INR in lakhs", scale=100000.0,
                       period="31.03.2025")
    provisions = row(measure="provisions", printed_label="(b) Provisions", value_text="0.00", value=0.0,
                     unit="Rs. in lakhs", scale=100000.0, period="As at 30-Sep-2026")
    charge = row(measure="provisions", printed_label="The provisions (other than tax) & contingencies charged to "
                                                      "the Profit and Loss for FY26 were at",
                 value_text="Rs.4,131 crore", value=4131.0, unit="Rs crore", scale=10000000.0, period="FY26")
    pnl_provisions = row(measure="provisions", printed_label="Provisions", value_text="12.00", value=12.0,
                         unit="Lakhs", scale=100000.0)
    obs.apply_results_row_gates([extraordinary], AZADIND_CF_PAGE)
    obs.apply_results_row_gates([equity_issue], APTUS_CF_PAGE)
    obs.apply_results_row_gates([provisions], AAYUSH_BS_PAGE)
    obs.apply_results_row_gates([charge], "Bandhan Bank Limited\nMedia Release Q4 FY26\n"
                                          "The provisions (other than tax) & contingencies charged to the Profit "
                                          "and Loss for FY26 were at\nRs.4,131 crore")
    obs.apply_results_row_gates([pnl_provisions], "Statement of Profit and Loss\nProvisions 12.00")
    assert extraordinary["measure"] == "NEW:extraordinary_items_cash_flow" and extraordinary["status"] == "unverified"
    assert equity_issue["measure"].startswith("NEW:issue_of_equity_shares")
    assert equity_issue["status"] == "unverified"
    assert provisions["measure"] == "long_term_provisions" and provisions["status"] == "verified"
    assert charge["status"] == "unverified" and "results_measure_section" in charge["status_reason"]
    assert pnl_provisions["measure"] == "provisions" and pnl_provisions["status"] == "verified"


def test_r3f_printed_movement_is_never_the_balance():
    movement = row(measure="deferred_tax_liabilities_net",
                   printed_label="the Deferred Tax Liability recognised by the Company on fair value gains on its "
                                 "investments as on June 30, 2024 had increased by",
                   value_text="\u20b9 69.75 Crore", value=69.75, unit="Crore", scale=10000000.0,
                   period="June 30, 2024")
    balance = row(measure="deferred_tax_liabilities_net", printed_label="Deferred tax liabilities (net)",
                  value_text="69.75", value=69.75, unit="Crore", scale=10000000.0, period="As at March 31, 2026")
    obs.apply_results_row_gates([movement], "")
    obs.apply_results_row_gates([balance], "")
    assert movement["status"] == "unverified" and movement["value_kind"] == "change"
    assert "results_change_not_balance" in movement["status_reason"]
    assert balance["status"] == "verified" and not balance.get("value_kind")


ATMAIND_SHARE_PAGE = (
    "ATMA INDUSTRIES LIMITED\nAmount in Lacs(\u201800000)\nNote : 11 Share Capital\n"
    "Particulars\nNumber\nAmount (Rs.)\nNumber\nAmount (Rs.)}\n1\n|AUTHORIZED CAPITAL\n"
    "Equity Shares of Rs. 10/- each with voting Rights\n25.50\n255.00\n25.50\n255.00\n"
    "Preference Shares of Rs. 10/- each\n2.50\n25.00\n2.50\n25.00\n"
    "11.1 Reconciliation of Number of Shares:-\nParticulars\nAs on March 31, 2026\nAs on March 31, 2025\n"
    "Number\nAmount (Rs.)\nNumber\nAmount (Rs.)\nAuthorised\n"
    "Equity Shares of 10/- each with voting Rights\nShare Outstanding at the beginning of the year\n"
    "25.50\n255.00\n25.50\n255.00\nShare Outstanding at the end of the year\n25.50\n255.00\n25.50\n255.00\n"
    "Preference Shares of 10/- each\nShare Outstanding at the beginning of the year\n2.50\n25.00\n2.50\n25.00\n"
    "Add: Increase during the year\n0.00\n0.00\n60.00\n0.00\nLess: Decrease during the year\n0.00\n0.00\n"
    "0.00\n0.00\nShare Outstanding at the end of the year\n2.50\n25.00\n2.50\n25.00\n"
    "Issued, Subscribed & Paid up\nEquity Shares of 10/- each with voting Rights\n"
    "Share Outstanding at the end of the year\n23.00\n230.00\n23.00\n230.00"
)


def test_r3f_share_count_table_keeps_a_count_measure_in_the_page_scale():
    count = row(measure="NEW:authorized_preference_share_capital",
                printed_label="Share Outstanding at the end of the year", value_text="2.50", value=2.5,
                unit="Number", unit_family="", scale=1.0, period="As on March 31, 2025")
    amount = row(measure="NEW:authorized_preference_share_capital",
                 printed_label="Share Outstanding at the end of the year", value_text="25.00", value=25.0,
                 unit="Number", unit_family="", scale=1.0, period="As on March 31, 2025")
    obs.apply_results_row_gates([count], ATMAIND_SHARE_PAGE)
    obs.apply_results_row_gates([amount], ATMAIND_SHARE_PAGE)
    assert count["measure"] == "NEW:preference_shares_outstanding"
    assert (count["unit"], count["unit_family"], count["scale"]) == ("Number", "count", 100000.0)
    assert "results_share_count" in count["status_reason"]
    assert amount["measure"] == "NEW:authorized_preference_share_capital" and amount["scale"] == 1.0


AEQUS_SEGMENT_PAGE = (
    "Aequs Limited\nUnaudited consolidated segment information for the quarter ended June 30, 2026\n"
    "(\u20b9 in Millions, except per share data)\nQuarter ended\nParticulars\n"
    "June 30, 2026\nMarch 31, 2026\nJune 30, 2025\nUnaudited\nUnaudited\nUnaudited\n"
    "Segment revenue\nAerospace\n3, 221 59\n3,039.54\n2,302 9B\n"
    "Consumer\n733.86\n631.49\n252.72\n"
    "Total external revenue\n3,955.45\n3,671.03\n2,555.70"
)
BHARATROHAN_HALF_PAGE = (
    "BHARATROHAN AIRBORNE INNOVATIONS LIMITED\n"
    "Unaudited Standalone Financial Results for the half year ended September 30, 2026\n"
    "(INR in lakhs, unless otherwise stated)\n"
    "Half Year ended\nYear ended\nSt No.\nParticulars\n"
    "30th September, 2026\n31t March, 2026\n_30th September, 2025\n315t March, 2026\n"
    "Un-Audited\nUn-Audited\nUn-Audited\nAudited\nI\nRevenue From Operations\n"
    "Net Sales or Revenue from Operations\n4,234.49\n5,248.62\n3,292.44\n8,541.07"
)
MINDIA_INTERLEAVED_PAGE = (
    "3M INDIA LIMITED\nSEGMENT-WISE REVENUE, RESULTS, ASSETS AND LIABILITIES FOR THE QUARTER AND YEAR ENDED "
    "31 MARCH 2026\n(Rs. in lakhs)\nParticulars\n3 months ended\n31 March 2026\n(Unaudited)\n"
    "3 months ended\n31 December 2025\n(Unaudited)\n3 months ended\n31 March 2025\n(Unaudited)\n"
    "12 months ended\n31 March 2026\n(Audited)\n12 months ended\n31 March 2025\n(Audited)\n"
    "(e) Others\n5.94\n20.56\n5.67\n50.36\n25.06"
)


def test_r3f_segment_table_value_takes_its_own_printed_column():
    aeqlike = row(measure="revenue.mix", printed_label="Aerospace", value_text="3,039.54", value=3039.54,
                  unit="\u20b9 in Millions", scale=1000000.0, period="Year ended March 31, 2026", segment="Aerospace")
    half = row(measure="revenue_from_operations", printed_label="Net Sales or Revenue from Operations",
               value_text="3,292.44", value=3292.44, unit="INR in lakhs", scale=100000.0,
               period="Year ended 30th September, 2025")
    interleaved = row(measure="revenue.mix", printed_label="(e) Others", value_text="25.06", value=25.06,
                      unit="Rs. in lakhs", scale=100000.0, period="12 months ended 31 March 2025")
    obs.apply_results_row_gates([aeqlike], AEQUS_SEGMENT_PAGE)
    obs.apply_results_row_gates([half], BHARATROHAN_HALF_PAGE)
    obs.apply_results_row_gates([interleaved], MINDIA_INTERLEAVED_PAGE)
    assert aeqlike["period"] == "Quarter ended March 31, 2026"
    assert aeqlike["period_source"] == "column_position" and aeqlike["status"] == "verified"
    assert half["period"] == "Half year ended 30th September, 2025"
    assert half["period_source"] == "column_position"
    assert interleaved["period"] == "12 months ended 31 March 2025"
    assert not interleaved.get("period_source")


ARTEMISMED_GEO_PAGE = (
    "ARTEMIS MEDICARE SERVICES LIMITED\nNotes:-\n1. The above unaudited standalone financial results for the "
    "quarter ended June 30, 2026\n4. Segment Reporting:\nGeographical information\n"
    "Geographical information analyses the Company's revenue by the country of domicile (i.e. India) and other "
    "countries.\nRegion\nCarrying amount of Non-Current Assets\nQuarter ended\nYear ended\n"
    "30-Jun-26\n31-Mar-26\n30-Jun-25\n31-Mar-26\nIndia\n1,02,038.47\n98,241.62\n79,690.69\n98,241.62\n"
    "Outside India\nTotal\n1,02,038.47\n98,241.62\n79,690.69\n98,241.62"
)


def test_r3f_geography_row_is_a_subset_and_carries_its_segment():
    india = row(measure="NEW:carrying_amount_of_non_current_assets", printed_label="India",
                value_text="1,02,038.47", value=102038.47, unit="Lakhs", scale=100000.0, period="30-Jun-26")
    no_head = row(measure="NEW:carrying_amount_of_non_current_assets", printed_label="India",
                  value_text="1,02,038.47", value=102038.47, unit="Lakhs", scale=100000.0, period="30-Jun-26")
    obs.apply_results_row_gates([india], ARTEMISMED_GEO_PAGE)
    obs.apply_results_row_gates([no_head], "Statement of Assets and Liabilities\nIndia 1,02,038.47")
    assert india["segment"] == "India" and india["status"] == "unverified"
    assert "results_geography_subset" in india["status_reason"]
    assert no_head["segment"] == "" and no_head["status"] == "verified"


ASTRONMULT_PAGE = (
    "ASTRON MULTIGRAIN LIMITED\n(FORMERLY KNOWN AS ASTRON MULTIGRAIN PRIVATE LIMITED)\n"
    "CIN: U15549GJ2018PLC103488\nSTATEMENT OF FINANCIAL RESULTS FOR THE HALF YEAR ENDED 30th SEPTEMBER, 2026\n"
    "(Rs in Lakhs)\n6 Months Ended\nYear Ended\n30th September\n2026\n(Unaudited)\n31st March\n2026\n(Audited)\n"
    "30th September\n2025\n(Unaudited)\n31st March\n2026\n(Audited)\n"
    "Other expenses\n89.04\n266.03\n35.59\n301.62"
)
ASTRONMULT_PREVIOUS = (
    "Subject: Outcome of the Board Meeting held on Wednesday, 4th November, 2026 and submission of\n"
    "Un-Audited Standalone Financial Results along with Limited Review Report for the Half Year Ended\n"
    "on 30th September, 2026."
)


def test_r3f_own_statement_heading_wins_over_a_previous_page_mention():
    own = row(measure="other_expenses", printed_label="Other expenses", value_text="35.59", value=35.59,
              unit="Rs in Lakhs", scale=100000.0, period="Half year ended 30th September 2025",
              entity_scope="subsidiary")
    note = row(measure="total_comprehensive_income", printed_label="total comprehensive income",
               value_text="621", value=621.0, unit="Crores", scale=10000000.0,
               period="quarter ended June 30, 2026", entity_scope="subsidiary")
    audit_note = ("S JR lB C & CO LLP\nChartered Accountants\nThe accompanying statement includes unaudited interim "
                  "financial results in respect of 39 subsidiaries, whose unaudited interim financial results "
                  "reflect total comprehensive income of Rs 621 Crores for the quarter ended June 30, 2026.")
    obs.apply_results_row_gates([own], ASTRONMULT_PAGE, company="Astron Multigrain Limited",
                                previous_page_text=ASTRONMULT_PREVIOUS)
    obs.apply_results_row_gates([note], audit_note, company="Adani Green Energy Limited")
    assert own["entity_scope"] == "company" and own["status"] == "verified"
    assert obs._results_own_statement_heading(ASTRONMULT_PAGE, "Astron Multigrain Limited")
    assert not obs._results_own_statement_heading(audit_note, "Adani Green Energy Limited")
    assert note["entity_scope"] == "subsidiary"
