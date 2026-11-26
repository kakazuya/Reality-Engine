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
