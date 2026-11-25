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
