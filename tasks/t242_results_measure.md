# T-242: results-page number gates - measurement

Copy of `D:/RealityEngine/hy4_out/obs_results_pilot.db` rechecked with the merged results row gates
(`apply_results_row_gates`), 2026-11-25.

```
$env:REALITY_RAW_FETCH="0"
python -m reality_engine.v2.observations --recheck \
    --baseline .tmp/results_pilot.db --out .tmp/results_recheck5.db \
    --stores <the 145 cNN.db that hold the pilot documents> --doc-types results
```

The recheck read 188 pages / 5,430 rows; verified rows 1,477 -> 1,421.

| rule | changed rows | of which were verified | share of 1,477 verified |
|---|---:|---:|---:|
| `results_not_a_figure` (junk number -> quarantined) | 175 | 55 | 3.72% |
| `results_unit` (printed unit/scale filled) | 715 | 119 | 8.06% |
| `results_scope_reset` (entity scope reset to company) | 200 | 99 | 6.70% |
| `results_associate_figure` (associate/JV figure -> unverified) | 1 | 1 | 0.07% |
| `results_holding_count` (holding count -> unverified) | 2 | 2 | 0.14% |
| `results_value_fragment` (fragment of a printed figure -> unverified) | 1 | 1 | 0.07% |

Every rule is under the 10%-of-verified stop bar. Status transitions:

- `unverified` -> `quarantined`: 120
- `verified` -> `quarantined`: 55
- `verified` -> `unverified`: 6
- `unverified` -> `verified`: 5

The five `unverified` -> `verified` rows are BRIGADE p12 revenue totals restored by the existing parts-sum
check, not by these gates.

## The 60 graded rows

0 of the 33 R rows changed. Changed rows:

- #1 5PAISA: `verified` -> `verified`, unit ``/1 -> `Lakhs`/100000, scope `company` -> `company` (results_unit)
- #3 BLACKROSE: `verified` -> `verified`, unit `l akhs`/1 -> `Lakhs`/100000, scope `company` -> `company` (results_unit)
- #5 ARSSBL: `verified` -> `verified`, unit `₹ in Millions`/1e+06 -> `₹ in Millions`/1e+06, scope `subsidiary` -> `company`
- #6 ARSSBL: `verified` -> `verified`, unit `₹ in Millions`/1e+06 -> `₹ in Millions`/1e+06, scope `subsidiary` -> `company`
- #10 5PAISA: `verified` -> `verified`, unit ``/1 -> `Lakhs`/100000, scope `company` -> `company` (results_unit)
- #16 BLACKROSE: `verified` -> `verified`, unit `l akhs`/1 -> `Lakhs`/100000, scope `company` -> `company` (results_unit)
- #25 AVANTIFEED: `verified` -> `verified`, unit ``/1 -> `Lakhs`/100000, scope `company` -> `company` (results_unit)
- #27 ASTRONMULT: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`
- #31 APOORVA: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company` (results_not_a_figure)
- #33 AGRIBIO: `verified` -> `unverified`, unit `lacs`/100000 -> `lacs`/100000, scope `subsidiary` -> `subsidiary` (results_associate_figure)
- #35 AXITA: `verified` -> `verified`, unit ``/100000 -> `Lakhs`/100000, scope `company` -> `company` (results_unit)
- #36 AIML: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company` (results_not_a_figure)
- #41 BERVINL: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company` (results_not_a_figure)
- #42 BIRLANU: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary` (results_not_a_figure)
- #43 ARSSINFRA: `verified` -> `verified`, unit `(Rupees in Lakll )`/1 -> `Lakhs`/100000, scope `company` -> `company` (results_unit)
- #44 BRIGHTBR: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary` (results_not_a_figure)
- #47 COALINDIA: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company` (results_not_a_figure)
- #50 ACMERAIL: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company` (results_not_a_figure)
- #51 ASHIKAG: `verified` -> `unverified`, unit `equity shares`/1 -> `equity shares`/1, scope `subsidiary` -> `subsidiary` (results_holding_count)
- #53 AUTOIND: `verified` -> `quarantined`, unit `%`/1 -> `%`/1, scope `company` -> `company` (results_not_a_figure)
- #54 AEPL: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company` (results_not_a_figure)
- #60 BIRLACORPN: `verified` -> `unverified`, unit `Crores`/1e+07 -> `Crores`/1e+07, scope `company` -> `company` (results_value_fragment)

The 9 J rows (31, 36, 41, 42, 44, 47, 50, 53, 54) are quarantined; 33/51/60 are unverified; 5/6/27 are
`company`; 1/3/10/16/25/35/43 carry `Lakhs`/1e5.

## results_not_a_figure: 175 changed, 20 random (seed 7)

- `3041` ATAM p2: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:regulatory_reference_year; vt='2015'; label='Regulations, 2015'; reason='results_not_a_figure: 2015 is a year in a date/reference, not a figure'
- `1069` AASTAFIN p6: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:companies_act_section_reference; vt='133'; label='Section 133 of the Companies Act, 2013'; reason='results_not_a_figure: 133 is a section/rule/serial reference, not a figure'
- `3995` ALKOSIGN p7: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:regulatory_reference_number; vt='1/80/2019'; label='Circular No.CIR/CFD/CMD 1/80/2019'; reason="results_not_a_figure: '1/80/2019' is a date, not a figure"
- `5328` AIML p1: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:board_meeting_time; vt='12:45 P.M'; label='The Board Meeting was commenced at'; reason="results_not_a_figure: '12:45 P.M' is a time, not a figure"
- `123` ACESOFT p12: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:incorporation_date; vt='17.2.1999'; label='Ace Infoway Private Limited or “Transferor Company 1” is a private limited compa'; reason="results_not_a_figure: '17.2.1999' is a date, not a figure"
- `129` ACESOFT p12: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:incorporation_date; vt='04.5.2025'; label='QeApps Private Limited or “Transferor Company 7” is a private limited company in'; reason="results_not_a_figure: '04.5.2025' is a date, not a figure"
- `4794` APTPACK p5: `unverified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:legal_reference_rule_11; vt='11'; label='Rule 11 of the Companies (Audit and Auditors) Rules, 2014'; reason='no_period: no period printed for this row; results_not_a_figure: 11 is a section/rule/serial reference, not a figure'
- `394` BIRLANU p1: `unverified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:regulatory_reference_number; vt='33'; label='Pursuant to Regulation 30, 33 and other applicable Regulations, if any, of SEBI '; reason='basis_conflict: same measure/label/period with different values and no distinct basis; results_not_a_figure: 33 is a section/rule/serial reference, not a figure'
- `3667` APOORVA p8: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:circular_reference_number; vt='44'; label="SEBI Circular No. CIR/CFD/CMD1/44/2019 dated March 29, 2019 ('the Circular')"; reason='results_not_a_figure: 44 is a section/rule/serial reference, not a figure'
- `4837` BELLACASA p4: `unverified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:legal_reference_year; vt='2013'; label='Companies Act, 2013 as amended'; reason='no_period: no period printed for this row; results_not_a_figure: 2013 is a year in a date/reference, not a figure'
- `125` ACESOFT p12: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:incorporation_date; vt='18.8.2025'; label='QeCAD Studio Private Limited or “Transferor Company 3” is a private limited comp'; reason="results_not_a_figure: '18.8.2025' is a date, not a figure"
- `4767` AVL p6: `unverified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:legal_act_year; vt='2013'; label='Companies Act'; reason='no_period: no period printed for this row; results_not_a_figure: 2013 is a year in a date/reference, not a figure'
- `1092` BDI p12: `unverified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:regulatory_reference; vt='33'; label='Regulation 33 of the LODR Regulations'; reason=' from colour/legend, not a printed heading; no_period: no period printed for this row; results_not_a_figure: 33 is a section/rule/serial reference, not a figure'
- `30` AAYUSHBULL p2: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:statutory_reference_year; vt='2013'; label='Companies Act,'; reason='results_not_a_figure: 2013 is a year in a date/reference, not a figure'
- `392` BIRLANU p1: `unverified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:regulatory_reference_number; vt='2015'; label='Ref: Disclosure under Regulation 30 read with Regulation 33 of SEBI (Listing Obl'; reason='w; basis_conflict: same measure/label/period with different values and no distinct basis; results_not_a_figure: 2015 is a year in a date/reference, not a figure'
- `4304` AUTOIND p12: `verified` -> `quarantined`, unit `%`/1 -> `%`/1, scope `company` -> `company`; NEW:consideration_received_on_warrant_allotment; vt='25%'; label='upon receipt of 25% of the issue price'; reason="results_not_a_figure: '25%' repeats the condition in its own label ('upon receipt of 25% of the issue price')"
- `4262` BERVINL p2: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:regulatory_reference_year; vt='2015'; label='Regulations,'; reason='results_not_a_figure: 2015 is a year in a date/reference, not a figure'
- `128` ACESOFT p12: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:incorporation_date; vt='25.5.2023'; label='QeLearn Private Limited Transferor Company 6” is a private limited company incor'; reason="results_not_a_figure: '25.5.2023' is a date, not a figure"
- `2191` ASSOCIATED p2: `verified` -> `quarantined`, unit ``/1 -> ``/1, scope `company` -> `company`; NEW:sebi_regulations_year; vt='2015'; label='SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015'; reason='results_not_a_figure: 2015 is a year in a date/reference, not a figure'
- `393` BIRLANU p1: `unverified` -> `quarantined`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; NEW:regulatory_reference_number; vt='30'; label='Pursuant to Regulation 30, 33 and other applicable Regulations, if any, of SEBI '; reason='basis_conflict: same measure/label/period with different values and no distinct basis; results_not_a_figure: 30 is a section/rule/serial reference, not a figure'

## results_unit: 715 changed, 20 random (seed 7)

- `4360` AVANTIFEED p12: `unverified` -> `unverified`, unit ``/1 -> `Lakhs`/100000, scope `company` -> `company`; NEW:equity_attributable_to_owners; vt='2,80,096.29'; label='Equity attrtbutable to owners'; reason="printed_axis is not in the page text layer: 'As at March 31, 2025 Audited'; results_unit: page prints Lakhs"
- `3960` ARSSINFRA p14: `unverified` -> `unverified`, unit `(Rupees in Lakll )`/1 -> `Lakhs`/100000, scope `company` -> `company`; cash_flow.operating; vt='-2,876.77'; label='NET CASH INFLOW FROM OPERATING ACTIVITIES (A)'; reason="printed_axis is not in the page text layer: 'Year Ended March 31, 2026 (Audited)'; results_unit: page prints Lakhs"
- `192` AXITA p6: `unverified` -> `unverified`, unit ``/100000 -> `Lakhs`/100000, scope `company` -> `company`; cash_flow.investing; vt='10.08'; label='Net Cash Flow from Investing Activities (B)'; reason='no_unit: no unit printed for this money/quantity row; results_unit: page prints Lakhs'
- `4375` AIIL p14: `unverified` -> `unverified`, unit ``/1 -> `Crores`/1e+07, scope `company` -> `company`; revenue_from_operations; vt='595.19'; label='Revenue from operations'; reason='nit printed for this money/quantity row; basis_conflict: same measure/label/period with different values and no distinct basis; results_unit: page prints Crores'
- `1205` AUREATE p6: `unverified` -> `unverified`, unit ``/1 -> `Lakhs`/100000, scope `company` -> `company`; cash_and_cash_equivalents; vt='42.59'; label='(d) Cash and Cash Equivalents'; reason='no_unit: no unit printed for this money/quantity row; results_unit: page prints Lakhs'
- `1904` BLACKROSE p11: `verified` -> `verified`, unit `l akhs`/1 -> `Lakhs`/100000, scope `company` -> `company`; cash_generated_from_operations; vt='4,136.81'; label='Cash Generated From Operating Activities'; reason='results_unit: page prints Lakhs'
- `4441` AIIL p14: `unverified` -> `unverified`, unit ``/1 -> `Crores`/1e+07, scope `company` -> `company`; profit_before_tax; vt='535.07'; label='Profit/(Loss) before tax (3-4)'; reason='nit printed for this money/quantity row; basis_conflict: same measure/label/period with different values and no distinct basis; results_unit: page prints Crores'
- `4438` AIIL p14: `unverified` -> `unverified`, unit ``/1 -> `Crores`/1e+07, scope `company` -> `company`; profit_before_exceptional_items_and_tax; vt='2,094.68'; label='Profit/ (Loss) before exceptional items and tax (1-2)'; reason='no_unit: no unit printed for this money/quantity row; results_unit: page prints Crores'
- `4392` AIIL p14: `unverified` -> `unverified`, unit ``/1 -> `Crores`/1e+07, scope `company` -> `company`; finance_cost; vt='58.16'; label='(i) Finance Costs'; reason="printed_axis is not in the page text layer: '30.06.2026 (Unaudited)'; no_unit: no unit printed for this money/quantity row; results_unit: page prints Crores"
- `195` AXITA p6: `unverified` -> `unverified`, unit ``/100000 -> `Lakhs`/100000, scope `company` -> `company`; NEW:movement_in_short_term_borrowings; vt='2,134.99'; label='Movement in Short term borrowing'; reason="new_driver_node_missing: 'debt.level' is not one of revenue/cost/margin/capex/capacity/debt/equity/working_capital/none; results_unit: page prints Lakhs"
- `4386` AIIL p14: `unverified` -> `unverified`, unit ``/1 -> `Crores`/1e+07, scope `company` -> `company`; total_income; vt='1,452.95'; label='Total Income'; reason="printed_axis is not in the page text layer: '30.06.2026 (Unaudited)'; no_unit: no unit printed for this money/quantity row; results_unit: page prints Crores"
- `4395` AIIL p14: `unverified` -> `unverified`, unit ``/1 -> `Crores`/1e+07, scope `company` -> `company`; finance_cost; vt='60.78'; label='(i) Finance Costs'; reason='nit printed for this money/quantity row; basis_conflict: same measure/label/period with different values and no distinct basis; results_unit: page prints Crores'
- `3932` ARSSINFRA p14: `unverified` -> `unverified`, unit `(Rupees in Lakll )`/1 -> `Lakhs`/100000, scope `company` -> `company`; depreciation_and_amortisation_expense; vt='111.79'; label='Adjustments for depreciation and amortisation expense'; reason="printed_axis is not in the page text layer: 'Year Ended March 31, 2026 (Audited)'; results_unit: page prints Lakhs"
- `182` AXITA p6: `unverified` -> `unverified`, unit ``/100000 -> `Lakhs`/100000, scope `company` -> `company`; interest_income; vt='(9.71)'; label='Interest Received'; reason='no_unit: no unit printed for this money/quantity row; results_unit: page prints Lakhs'
- `1902` BLACKROSE p11: `verified` -> `verified`, unit `l akhs`/1 -> `Lakhs`/100000, scope `company` -> `company`; changes_in_payables; vt='2,624.80'; label='lncrease/(Dccrcase) In Payables, Provisions And Other liabilities'; reason='results_unit: page prints Lakhs'
- `179` AXITA p6: `unverified` -> `unverified`, unit ``/100000 -> `Lakhs`/100000, scope `company` -> `company`; cash_flow.operating; vt='1,571.28'; label='Net Cash Flow from Operating Activities (A)'; reason='no_unit: no unit printed for this money/quantity row; results_unit: page prints Lakhs'
- `4366` AVANTIFEED p12: `unverified` -> `unverified`, unit ``/1 -> `Lakhs`/100000, scope `company` -> `company`; borrowings; vt='1,046.03'; label='Borrowings'; reason="rinted_axis is not in the page text layer: 'As at March 31, 2025 Audited'; no_unit: no unit printed for this money/quantity row; results_unit: page prints Lakhs"
- `1284` ALKALI p4: `unverified` -> `unverified`, unit ``/100000 -> `Lakhs`/100000, scope `company` -> `company`; depreciation_and_amortisation_expense; vt='154.49'; label='Depreciation'; reason=" in the page text layer: 'For the Half Year Ended 30.09.2025 (Unaudited)'; no_unit: no unit printed for this money/quantity row; results_unit: page prints Lakhs"
- `2085` 5PAISA p13: `unverified` -> `unverified`, unit ``/1 -> `Lakhs`/100000, scope `company` -> `company`; capex; vt='(803.20)'; label='Purchase of PPE & Intangible Assets'; reason='no_unit: no unit printed for this money/quantity row; results_unit: page prints Lakhs'
- `3955` ARSSINFRA p14: `verified` -> `verified`, unit `(Rupees in Lakll )`/1 -> `Lakhs`/100000, scope `company` -> `company`; other_bank_balances; vt='204.44'; label='Adjustments for other bank balances'; reason='results_unit: page prints Lakhs'

## results_scope_reset: 200 changed, 20 random (seed 7)

- `827` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; NEW:profit_before_extraordinary_items_and_tax; vt='(112.25)'; label='Profit before extraordinary items and tax'; reason="printed_axis is not in the page text layer: '30.06.2026 Unaudited'"
- `4929` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; profit_before_tax; vt='173.51'; label='Net Profit Before tax as per Statement of Profit & Loss'; reason=''
- `821` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; profit_before_exceptional_items_and_tax; vt='(112.25)'; label='Profit/(Loss) before exceptional items and tax'; reason="printed_axis is not in the page text layer: '30.06.2026 Unaudited'"
- `4937` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; NEW:gain_on_disposal_of_fixed_assets_net_cash_flow_adjustment; vt='(8.33)'; label='Gain on disposal of fixed assets (net)'; reason=''
- `2113` ARSSBL p21: `verified` -> `verified`, unit `₹ in Millions`/1e+06 -> `₹ in Millions`/1e+06, scope `subsidiary` -> `company`; NEW:gain_loss_on_sale_of_property_plant_and_equipment; vt='(0.49)'; label='(Gain)/Loss on Sale of Property, Plant and Equipment (Net)'; reason=''
- `4934` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; depreciation_and_amortisation_expense; vt='61.87'; label='Depreciation and amortisation expense'; reason=''
- `4965` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; NEW:proceeds_from_sale_disposal_of_fixed_assets; vt='84.75'; label='Proceeds from sale/disposal of fixed assets'; reason=''
- `837` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; profit_before_tax; vt='(130.02)'; label='Profit/(Loss) before tax'; reason="printed_axis is not in the page text layer: '31.03.2026 Audited'"
- `817` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; total_expenses; vt='112.25'; label='Total expenses (IV)'; reason="printed_axis is not in the page text layer: '30.09.2026 Unaudited'"
- `4939` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; operating_profit_before_working_capital_changes; vt='213.21'; label='Operating Profit before working capital changes'; reason=''
- `4954` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; NEW:changes_in_other_liabilities; vt='(43.85)'; label='(Decrease)/ Increase in other liabilites'; reason=''
- `839` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; current_tax; vt='55.87'; label='(1) Current Tax'; reason="printed_axis is not in the page text layer: '30.09.2025 Unaudited'; basis_conflict: same measure/label/period with different values and no distinct basis"
- `2132` ARSSBL p21: `verified` -> `verified`, unit `₹ in Millions`/1e+06 -> `₹ in Millions`/1e+06, scope `subsidiary` -> `company`; NEW:changes_in_loans_cash_flow; vt='(682.20)'; label='(Increase)/Decrease in Loans'; reason=''
- `815` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; total_expenses; vt='112.25'; label='Total expenses (IV)'; reason="printed_axis is not in the page text layer: '30.06.2026 Unaudited'"
- `4931` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; finance_cost; vt='2.89'; label='Interest Paid'; reason=''
- `4973` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; borrowings; vt='14.08'; label='Proceeds from short-term borrowings (net)'; reason=''
- `807` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; depreciation_and_amortisation_expense; vt='2.96'; label='Depreciation and amortization expenses'; reason="printed_axis is not in the page text layer: '30.06.2026 Unaudited'"
- `4935` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; interest_income; vt='(5.21)'; label='Interest income'; reason=''
- `806` BGDL p3: `unverified` -> `unverified`, unit `Lakhs`/100000 -> `Lakhs`/100000, scope `subsidiary` -> `company`; changes_in_inventories; vt='(0.28)'; label='Change in inventory of finished goods, work-in-progress and Stock-in-Trade'; reason="printed_axis is not in the page text layer: '30.09.2025 Unaudited'"
- `4949` ASTRONMULT p4: `verified` -> `verified`, unit `Rs in Lakhs`/100000 -> `Rs in Lakhs`/100000, scope `subsidiary` -> `company`; NEW:changes_in_other_current_assets; vt='(3.97)'; label='Decrease/(Increase) in other current assets'; reason=''

## results_associate_figure: 1 changed, 20 random (seed 7)

- `544` AGRIBIO p7: `verified` -> `unverified`, unit `lacs`/100000 -> `lacs`/100000, scope `subsidiary` -> `subsidiary`; pat; vt='91.66'; label='net profit after tax'; reason="ate_figure: 'net profit after tax' is the associate/JV's figure ('The Statement includes the interim financial information of one Associate'), not the company's"

## results_holding_count: 2 changed, 20 random (seed 7)

- `5363` ASHIKAG p10: `verified` -> `unverified`, unit `equity shares`/1 -> `equity shares`/1, scope `subsidiary` -> `subsidiary`; count.shares; vt='2,60,000'; label='equity shares'; reason="results_holding_count: '2,60,000' is a holding in another company, not the company's own share count"
- `4307` AUTOIND p12: `verified` -> `unverified`, unit ``/1 -> ``/1, scope `subsidiary` -> `subsidiary`; count.shares; vt='3,42,56,089'; label='equity shares'; reason="results_holding_count: '3,42,56,089' is a holding in another company, not the company's own share count"

## results_value_fragment: 1 changed, 20 random (seed 7)

- `4534` BIRLACORPN p6: `verified` -> `unverified`, unit `Crores`/1e+07 -> `Crores`/1e+07, scope `company` -> `company`; profit_before_exceptional_items_and_tax; vt='5'; label='Net Profit before tax and exceptional items'; reason="results_value_fragment: '5' is the start of the printed figure '55.43'"


## results gates r2 (26 Nov 2026, T-242, obs_results_fy27.db copy)

Measured by a scratch script calling the same `apply_results_row_gates` over the baseline rows and the stores' `doc_page` texts (1,858 pages; no model, no fetch): 49,993 rows, 14,171 verified. 1,201 verified rows become unverified across the five r2 rules (no rule over the 3% stop): `basis_unstated` 380 (2.68%), `results_period_duration_missing` 281 (1.98%), `results_period_not_a_period` 239 (1.69%), cash-flow line 277 (1.95%), `results_equity_accounted` 24. 625 cash-flow lines remapped in all (348 already unverified); 291 per-share rows lose the money scale, status unchanged. Graded-R rows of results_ckpt1 (40): 0 status changes; row 42 only gains `basis='standalone'`.
P rows: 2/16/25 basis_unstated; 30/36/37/43 -> NEW:<line>_cash_flow + unverified; 31 bare year; 33 basis + release date; 35 associate + basis cleared; 46 EPS unit '₹'; 59 duration; 60 entity_scope jv + value -8193.50; 8/48/51/52 basis carried (52 also Lakhs); 11 Lakhs; 24 (misaligned OCR) and 26 (no duration word on its page) unchanged.
A full `--recheck` of a copy was started but spent >25 min loading page words/PDFs and was abandoned; the gate path is the same function.
