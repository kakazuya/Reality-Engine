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

## results gates r3b (26 Nov 2026, T-242, obs_results_fy27.db copy)

Wolf's check of the r3 recheck copy `C:/RealityEngine/t242/results_recheck/results_r3.db` found 6 rows graded R in
the two packs downgraded: a flow period whose duration is printed but not matched (ALOKINDS p7 "for the Half Vear
Ended", ALUFLUOR p18 "year ending on 31-March-2025", AKSHOPTFBR p11 "for the izar ended March 31 2026") and three
cash-flow adjustment lines stored under a `NEW:` id that already names the line (AMFORG, AKCAPIT, ABDL).
`reality_engine/v2/observations.py` now reads those headers (and a single-duration header carried from the page
before; an ambiguous one carries nothing), reads an annual cash-flow statement's bare 31 March columns as years
when its title names no duration, and remaps a cash-flow line only when its measure is a dictionary P&L/BS measure
or a `NEW:` id that is a plain line name. The rules are in `docs/DEVELOPER_GUIDE.md` (r3b bullet).

### results gates r3c (26 Nov 2026, T-242)

Eagle's non-author review of r3b (`D:/RealityEngine/t242/grades/results_r3b_review_eagle.md`) failed on two structural
defects: `D1` `'Year ended'` on non-year-end dates (`APOLLOIN` p6->p7 `30.09`, `AGL` p3 `30 Jun`, `ARVINDFASN`, `AMBIT`)
and `D2` `'Quarter ended'` on annual columns sharing the same end date (`AGL` p3 `31 Mar 2026`, `ASITCFIN` p14
`31.03.2026`). `_results_duration_dates_scan`, `_results_duration_dates`, and `_results_period_reason` in
`reality_engine/v2/observations.py` now: (1) mark any end date printed in >1 column on the current or carrying page
ambiguous so it is never carried and never filled by key; (2) require complete header-prefix matching and uniform
`(day, month)` for single-group headers (rejecting `Year to Date` / `"Quarter and Year ended"` collapses); (3) allow
`'Year ended'` only on 31 March unless the header block binds `'year'` 1-to-1 to an exact single unique column; (4)
parse spaced dot/ordinal/comma dates (`31 .03.2026`, `31 st March, 2026`, `September 30,2026`); and (5) leave refused
flow rows without a duration (`unverified`, `results_period_duration_missing`) while sparing non-flow stock rows.

```
$env:REALITY_RAW_FETCH="0"
python -m reality_engine.v2.observations --recheck --baseline .tmp/r3b/base.db --out .tmp/r3b/after.db `
    --stores-root C:/RealityEngine/tg_build/universe_fy27 --doc-types results
```

(The run wrapped `observations.main` in a scratch script that retries a transient `unable to open database file`
race on a store another working process held open; the pipeline code is untouched. Rule hits: `results_period`
8,788, `results_duration_filled` 8,269, `results_cash_flow` 1,842, `results_scope_reset` 2,961,
`results_dropped` 760, `results_junk` 1,435, `results_unit` 415, `results_doc_units` 1,330,
`results_basis_unstated` 387, `results_current_mismatch` 58, `results_jv` 21, `results_equity_accounted` 24,
`results_per_share` 291, `repeats_dropped` 542; r3 had `results_period` 9,669, `results_duration_filled` 7,419,
`results_cash_flow` 2,420. `downgraded` 2,630 (r3 3,189), `upgraded` 37, `unproven_upgrades` 533 — the run stops
with the same rc 2 "would verify without a new printed source", as r3 did.)

recheck of a fresh copy (`REALITY_RAW_FETCH=0`, the 681 stores under
`C:/RealityEngine/tg_build/universe_fy27`, `--doc-types results`): 1,858 pages, 49,993 rows read;
49,071 rows written (542 exact repeats + 760 junk rows dropped); verified 14,171 -> 11,399
(r3: 10,848).


### The 68 graded-R rows

0 status changes; 14 attribute changes (all verified -> verified).

- ckpt1 #1 ALOKINDS obs 34701: period '30.09.2025' -> 'Half year ended 30.09.2025'
- ckpt1 #3 ALUFLUOR obs 35953: period '31-March-2025' -> 'Year ended 31-March-2025'
- ckpt1 #7 AMFORG obs 37167: period '31-03-2025' -> 'Year ended 31-03-2025'; basis '' -> 'standalone'
- ckpt1 #38 ACC obs 19164: period 'March 31, 2026' -> 'Year ended March 31, 2026'
- ckpt1 #41 AMNPLST obs 38424: period '31-Mar-26' -> 'Year ended 31-Mar-26'
- ckpt1 #42 ADHBHUTIN obs 23295: basis '' -> 'standalone'
- ckpt1 #54 ARSSINFRA obs 2197: period 'March 31, 2026' -> 'Year ended March 31, 2026'
- ckpt1 #55 AKSHOPTFBR obs 32434: period '31-Mar-26' -> 'Year ended 31-Mar-26'
- ckpt1 #57 ACCEDERE obs 19266: period 'As at March 31, 2026' -> 'Year ended March 31, 2026'
- r2 #1 AJANTPHARM obs 31246: basis '' -> 'consolidated'
- r2 #34 APOLLOTYRE obs 43783: basis '' -> 'standalone'
- r2 #36 ADVENZYMES obs 24454: basis '' -> 'consolidated'
- r2 #53 ADTECH obs 24988: basis '' -> 'standalone'
- r2 #60 ANSALBU obs 42382: basis '' -> 'standalone'

The six r3 downgrades (verified -> verified):

- ckpt1 #1 ALOKINDS: `cash_generated_from_operations` period 'Half year ended 30.09.2025', status verified
- ckpt1 #3 ALUFLUOR: `cash_flow.financing` period 'Year ended 31-March-2025', status verified
- ckpt1 #7 AMFORG: `NEW:rent_received_other_income_adjustment` period 'Year ended 31-03-2025', status verified
- ckpt1 #22 AKCAPIT: `NEW:net_gain_on_derecognition_of_financial_instruments_under_amortised_cost_category` period 'For the year ended 31 March 2025 (Audited)', status verified
- ckpt1 #32 ABDL: `NEW:interest_income_from_investing_activities` period 'Year ended 31 March 2025', status verified
- ckpt1 #55 AKSHOPTFBR: `cash_flow.operating` period 'Year ended 31-Mar-26', status verified

### Downgrades by rule (verified -> not verified, 2809 rows)

- `results_period_duration_missing`: 967
- `results_cash_flow_measure`: 747
- `other`: 522
- `removed`: 262
- `results_period_not_a_period`: 228
- `results_unit`: 53
- `results_equity_accounted`: 17
- `results_current_mismatch`: 13

#### results_period_duration_missing: 967 downgraded, 20 random (seed 7)

- `17764` ABB p4: `verified` -> `unverified`, revenue_from_operations, period 'June 30, 2025', value_text '2,940.47'; results_period_duration_missing: no column duration header found for flow period 'June 30, 2025'
- `9322` ANURAS p8: `verified` -> `unverified`, NEW:defined_benefit_plan_remeasurement_gain_loss, period 'March 31, 2026', value_text '9.50'; results_period_duration_missing: 'March 31, 2026' is printed under more than one duration (quarter, year), the row does not say which
- `20770` ACESOFT p13: `verified` -> `unverified`, revenue.value, period '31st March 2026', value_text '95.00'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `35504` ALPINEHOU p5: `verified` -> `unverified`, NEW:changes_in_trade_payables_and_current_liabilities, period '30-09-2026', value_text '-763.08'; results_period_duration_missing: no column duration header found for flow period '30-09-2026'
- `4512` ASTRAL p11: `verified` -> `unverified`, total_comprehensive_income, period 'the period ended on that date', value_text 'Rs. 369 million'; results_period_duration_missing: 'the period ended on that date' has no resolved date/duration
- `5538` AADHARHFC p7: `verified` -> `unverified`, NEW:ipo_proceeds_amount_utilised_upto, period 'March 31, 2026', value_text '75,000'; printed_label is not in the page text layer: 'To meet the future capital requirements towards onward lending'
- `44999` ARAVALIS p2: `verified` -> `unverified`, finance_cost, period '31/03/2026', value_text '29.56'; results_period_duration_missing: no column duration header found for flow period '31/03/2026'
- `29942` AIHL p11: `verified` -> `unverified`, purchase_of_finished_goods, period '31.12.2025', value_text '169.80'; results_period_duration_missing: no column duration header found for flow period '31.12.2025'
- `6673` AGRIBIO p13: `verified` -> `unverified`, NEW:group_share_of_total_net_profit_loss_after_tax, period 'for the quarter', value_text '34.48'; results_period_duration_missing: 'for the quarter' has no resolved date/duration
- `19165` ACC p7: `verified` -> `unverified`, NEW:changes_in_other_liabilities, period 'March 31, 2025', value_text '(42.13)'; results_period_duration_missing: no column duration header found for flow period 'March 31, 2025'
- `32109` AKSHAR p5: `verified` -> `unverified`, operating_profit_before_working_capital_changes, period 'March 31, 2026', value_text '(256.49)'; results_period_duration_missing: no column duration header found for flow period 'March 31, 2026'
- `4895` ALFL p3: `verified` -> `unverified`, investments, period '30.09.2026', value_text '637.46'; results_period_duration_missing: '30.09.2026' is printed under more than one duration (half_year, quarter), the row does not say which
- `48403` ARVINDFASN p4: `verified` -> `unverified`, profit_before_tax, period '30.06.2026', value_text '(20.63)'; results_period_duration_missing: no column duration header found for flow period '30.06.2026'
- `25912` AEIM p6: `verified` -> `unverified`, equity_share_capital, period '30-06-2026', value_text '2,766.96'; results_period_duration_missing: '30-06-2026' is printed under more than one duration (quarter, year), the row does not say which
- `11168` AKSHOPTFBR p4: `verified` -> `unverified`, total_assets, period 'Mar-26', value_text '24,402.82'; results_period_duration_missing: 'Mar-26' is printed under more than one duration (quarter, year), the row does not say which
- `4099` BHARTIARTL p26: `verified` -> `unverified`, revenue_growth_qoq, period 'sequentially', value_text '9.5%'; results_period_duration_missing: 'sequentially' has no resolved date/duration
- `6012` ASTEC p3: `verified` -> `unverified`, profit_before_tax, period '30-Jun-25', value_text '(3,305.64)'; results_period_duration_missing: no column duration header found for flow period '30-Jun-25'
- `23957` ADL p3: `verified` -> `unverified`, NEW:taxes_for_earlier_years, period '31.03.2026', value_text '0.69'; results_period_duration_missing: '31.03.2026' is printed under more than one duration (three_months, year), the row does not say which
- `22814` ADFFOODS p10: `verified` -> `unverified`, total_comprehensive_income, period 'for the year ended on that date', value_text '59.72'; results_period_duration_missing: 'for the year ended on that date' has no resolved date/duration
- `5531` AADHARHFC p7: `verified` -> `unverified`, NEW:fresh_issue_amount, period 'May 13, 2024', value_text 'Rs 100,000 lakhs'; results_period_duration_missing: no column duration header found for flow period 'May 13, 2024'

#### results_cash_flow_measure: 747 downgraded, 20 random (seed 7)

- `21529` ACI p5: `verified` -> `unverified`, NEW:profit_loss_on_sale_of_asset, period 'For the year ended March 31, 2025', value_text '42.42'; results_cash_flow_measure: '(Profit)/Loss on sale of asset' is a cash-flow line, not the P&L/balance-sheet 'NEW:profit_loss_on_sale_of_asset'
- `6410` AIRFLOA p16: `verified` -> `unverified`, interest_income, period 'As at March 31, 2026', value_text '-26.53'; results_cash_flow_measure: 'Interest Income' is a cash-flow line, not the P&L/balance-sheet 'interest_income'
- `35480` ALPINEHOU p5: `verified` -> `unverified`, NEW:provision_for_gratuity_and_earned_leave_payable, period '31-03-2026', value_text '11.37'; results_cash_flow_measure: 'Provision For Gratuity & Earned Leave Payable' is a cash-flow line, not the P&L/balance-sheet 'NEW:provision_for_gratuity_and_earned_leave_payable'
- `31023` AIRFLOA p12: `verified` -> `unverified`, trade_receivables, period 'As at March 31, 2026', value_text '-8,641.54'; results_cash_flow_measure: 'Trade Receivables' is a cash-flow line, not the P&L/balance-sheet 'trade_receivables'
- `3911` BBTCL p16: `verified` -> `unverified`, borrowings, period 'For the year ended March 31, 2026', value_text '2,433.40'; results_cash_flow_measure: 'Increase (Decrease) in Working Capital Borrowings' is a cash-flow line, not the P&L/balance-sheet 'borrowings'
- `38166` AMJLAND p8: `verified` -> `unverified`, depreciation_and_amortisation_expense, period 'Period ended 30 September 2026', value_text '93.13'; results_cash_flow_measure: 'Depredation and amortisation expense' is a cash-flow line, not the P&L/balance-sheet 'depreciation_and_amortisation_expense'
- `7799` ALSL p9: `verified` -> `unverified`, other_current_liabilities, period '31-03-2026', value_text '493.56'; results_cash_flow_measure: 'Increase/(Decrease) in Other Current Liabilities' is a cash-flow line, not the P&L/balance-sheet 'other_current_liabilities'
- `21480` ACHYUT p4: `verified` -> `unverified`, other_financial_assets, period 'For the year ended 31 March 2026', value_text '(0.02)'; results_cash_flow_measure: 'Other Current Financial Assets' is a cash-flow line, not the P&L/balance-sheet 'other_financial_assets'
- `43269` APCL p17: `verified` -> `unverified`, lease_liabilities, period '31-Mar-26', value_text '(1)'; results_cash_flow_measure: 'Payment of lease liabilities' is a cash-flow line, not the P&L/balance-sheet 'lease_liabilities'
- `43234` APCL p17: `verified` -> `unverified`, NEW:loss_on_sale_of_investment, period '31-Mar-26', value_text '7,996'; results_cash_flow_measure: 'Loss of Sale of Investement' is a cash-flow line, not the P&L/balance-sheet 'NEW:loss_on_sale_of_investment'
- `40094` ANDREWYU p20: `verified` -> `unverified`, interest_income, period 'Year ended 31st March, 2026', value_text '(208.54)'; results_cash_flow_measure: 'Interest Income' is a cash-flow line, not the P&L/balance-sheet 'interest_income'
- `3915` BBTCL p16: `verified` -> `unverified`, lease_liabilities, period 'For the year ended March 31, 2025', value_text '(191.03)'; results_cash_flow_measure: 'Principle payment of lease liabilities' is a cash-flow line, not the P&L/balance-sheet 'lease_liabilities'
- `40085` ANDREWYU p20: `verified` -> `unverified`, depreciation_and_amortisation_expense, period 'Year ended 31st March, 2026', value_text '689.99'; results_cash_flow_measure: 'Depreciation/Impairment of PPE' is a cash-flow line, not the P&L/balance-sheet 'depreciation_and_amortisation_expense'
- `40101` ANDREWYU p20: `verified` -> `unverified`, NEW:gain_on_remeasurement_of_investments, period 'Year ended 31st March, 2026', value_text '(24.67)'; results_cash_flow_measure: 'Gain on Remeasurement of Investments' is a cash-flow line, not the P&L/balance-sheet 'NEW:gain_on_remeasurement_of_investments'
- `29369` AGRIBIO p12: `verified` -> `unverified`, finance_cost, period '31.03.2023', value_text '10.70'; results_cash_flow_measure: 'Interest and Bank Charges' is a cash-flow line, not the P&L/balance-sheet 'finance_cost'
- `3837` ATIL p21: `verified` -> `unverified`, finance_cost, period '31/03/2026', value_text '(233.29)'; results_cash_flow_measure: 'Interest and other finance charges paid' is a cash-flow line, not the P&L/balance-sheet 'finance_cost'
- `21478` ACHYUT p4: `verified` -> `unverified`, trade_receivables, period 'For the period ended 30 September 2026', value_text '28.25'; results_cash_flow_measure: 'Trade Receivables' is a cash-flow line, not the P&L/balance-sheet 'trade_receivables'
- `2746` AVALON p9: `verified` -> `unverified`, borrowings, period "30 Sep'25", value_text '(80.13)'; results_cash_flow_measure: 'Proceeds from / (Repayment) of Current borrowings' is a cash-flow line, not the P&L/balance-sheet 'borrowings'
- `37161` AMFORG p11: `verified` -> `unverified`, depreciation_and_amortisation_expense, period '31-03-2026', value_text '28.04'; results_cash_flow_measure: 'Depreciation' is a cash-flow line, not the P&L/balance-sheet 'depreciation_and_amortisation_expense'
- `9784` BHARATROHAN p19: `verified` -> `unverified`, interest_income, period '31st March, 2026', value_text '(38.20)'; results_cash_flow_measure: 'Interest income' is a cash-flow line, not the P&L/balance-sheet 'interest_income'

#### other: 522 downgraded, 20 random (seed 7)

- `20739` ACESOFT p10: `verified` -> `unverified`, count.shares, period 'June 30', value_text '361'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `31211` AJANTPHARM p2: `verified` -> `unverified`, revenue_growth_yoy, period 'H1 FY 2027', value_text '49%'; parts sum to 213 but the printed total is 29%
- `11589` ALKEM p23: `verified` -> `unverified`, revenue_growth_yoy, period 'Q2FY27', value_text '13.8%'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `9952` AMBUJACEM p16: `verified` -> `unverified`, NEW:segment_results, period '30/06/2025', value_text '1,228'; printed_axis is not in the page text layer: 'Corresponding 3 months ended 30/06/2025 Unaudited (Refer Note 3)'
- `22718` ADANIGREEN p50: `verified` -> `unverified`, capacity.growth_multiple, period 'FY26', value_text '1.5 times'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `13681` 360ONE p3: `verified` -> `unverified`, other_income, period 'Q2 FY27', value_text '(44)'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `6728` ABATEAS p11: `verified` -> `unverified`, share_of_profit_of_jv_and_associates, period 'half year ended September 30, 2026', value_text '4.71'; not_company: a jv figure is served labelled, never verified
- `13688` 360ONE p3: `verified` -> `unverified`, revenue_growth_yoy, period 'Q2 FY27', value_text '4.8%'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `27120` AEONXDIGI p6: `verified` -> `unverified`, other_current_assets, period '31st March, 2026', value_text '256.13'; basis_conflict: same measure/label/period with different values and no distinct basis
- `4779` BOSCHLTD p9: `verified` -> `unverified`, share_of_profit_of_jv_and_associates, period 'year to date from April 01, 2026 to September 30, 2026', value_text 'Rs. 23 million'; not_company: a jv figure is served labelled, never verified
- `1026` BHARTIARTL p74: `verified` -> `unverified`, ebitda_margin, period 'Jun-25', value_text '50.9%'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `1023` BHARTIARTL p74: `verified` -> `unverified`, ebitda_margin, period 'Mar-26', value_text '44.2%'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `18052` ABFRL p9: `verified` -> `unverified`, share_of_profit_of_jv_and_associates, period 'quarter ended June 30, 2026', value_text 'Rs.(6.39 crores)'; not_company: a jv figure is served labelled, never verified
- `47637` ARVINDFASN p33: `verified` -> `unverified`, revenue.value, period 'Q4 FY26', value_text '1,365'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `31360` AJRINFRA p7: `verified` -> `unverified`, ownership_stake_pct, period 'year ended March 31, 2025', value_text '16.29%'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `22935` ADANIGREEN p19: `verified` -> `unverified`, profit_before_exceptional_items_and_tax, period '3 Months ended 30.06.2025', value_text '956'; not_company: a jv figure is served labelled, never verified
- `41969` ANTHEM p14: `verified` -> `unverified`, total_comprehensive_income, period 'the year ended 31st March 2026', value_text '(788.10)'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `40070` ANANTRAJ p5: `verified` -> `unverified`, share_of_profit_of_jv_and_associates, period 'Quarter ended 31.03.2025', value_text '0.65'; not_company: a jv figure is served labelled, never verified
- `27091` AEONXDIGI p6: `verified` -> `unverified`, total_non_current_assets, period '31st March, 2026', value_text '803.49'; basis_conflict: same measure/label/period with different values and no distinct basis
- `20762` ACESOFT p13: `verified` -> `unverified`, equity_share_capital, period '31st March 2026', value_text '111.00'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from

#### removed: 262 downgraded, 20 random (seed 7)

- `25636` AEIM p10: `verified` -> `removed`, NEW:legal_reference, period 'March 31, 2026', value_text '143(10)'; 
- `19264` ACCEDERE p4: `verified` -> `removed`, equity_share_capital, period '31-03-2026', value_text '457.09'; 
- `25574` AEGISLOG p3: `verified` -> `removed`, NEW:statutory_section_reference, period 'March 31, 2026', value_text '143(10)'; 
- `13907` 3PLAND p5: `verified` -> `removed`, property_plant_and_equipment, period '31.03.2026', value_text '11'; 
- `29654` AHMDSTE p4: `verified` -> `removed`, NEW:secretarial_auditor_appointment_term_end, period '2030-31', value_text '2030-31'; 
- `49940` ASAHIINDIA p10: `verified` -> `removed`, total_assets, period '31.03.2026', value_text '777225'; 
- `31477` AKSHAR p6: `verified` -> `removed`, NEW:regulatory_reference_number, period '31.03.2026', value_text '33 (3) (d)'; 
- `45979` ARENTERP p8: `verified` -> `removed`, NEW:biological_assets_other_than_bearer_plants, period '31-03-2026', value_text '0.00'; 
- `28201` AGI p5: `verified` -> `removed`, NEW:increase_decrease_in_acceptances, period 'Half year ended 30th September 2026', value_text '20.07'; 
- `13883` 3PLAND p5: `verified` -> `removed`, cash_and_cash_equivalents, period '31.03.2026', value_text '20'; 
- `15241` A1L p9: `verified` -> `removed`, total_liabilities, period '31.03.2025', value_text '2,394.52'; 
- `44338` APOLLOTYRE p10: `verified` -> `removed`, debt_equity, period '31.03.2026', value_text '0.20'; 
- `18808` ACCORDTS p1: `verified` -> `removed`, NEW:regulations_30_and_33_reference, period 'September 30, 2026', value_text '30 & 33'; 
- `15962` AAREYDRUGS p5: `verified` -> `removed`, count.shares, period 'June 30, 2026', value_text '28,454,303'; 
- `49928` ASAHIINDIA p10: `verified` -> `removed`, NEW:segment_assets, period '31.03.2026', value_text '383854'; 
- `44342` APOLLOTYRE p10: `verified` -> `removed`, long_term_debt_equity, period '31.03.2026', value_text '1.12'; 
- `11167` AKSHOPTFBR p4: `verified` -> `removed`, NEW:unallocated_assets, period 'Mar-25', value_text '4,387.56'; 
- `13899` 3PLAND p5: `verified` -> `removed`, current_tax_assets_net, period '31.03.2026', value_text '2'; 
- `30969` AIIL p11: `verified` -> `removed`, NEW:segment_assets, period '30.09.2026', value_text '3,719.76'; 
- `31476` AKSHAR p6: `verified` -> `removed`, NEW:regulatory_reference_number, period '31.03.2026', value_text '33(2)'; 

#### results_period_not_a_period: 228 downgraded, 20 random (seed 7)

- `36557` AMARJOTHI p16: `verified` -> `unverified`, cash_and_cash_equivalents, period '2025', value_text '417.74'; results_period_not_a_period: '2025' is a year, not a period
- `12554` ALEMBICLTD p15: `verified` -> `unverified`, other_equity, period '2026', value_text '77,010'; results_period_not_a_period: '2026' is a year, not a period
- `25825` AEONXDIGI p1: `verified` -> `unverified`, NEW:resignation_effective_date, period '26.05.2026', value_text '26th May, 2026'; results_period_not_a_period: '26.05.2026' is the release date, not the row's period
- `12666` BHARTIARTL p32: `verified` -> `unverified`, cash_profit, period '2024', value_text '720,012'; results_period_not_a_period: '2024' is a year, not a period
- `23354` ADMANUM p1: `verified` -> `unverified`, NEW:board_meeting_resolution_number, period '27/10-04', value_text '2026-27/10-04'; results_period_not_a_period: '27/10-04' is the release date, not the row's period
- `36591` AMARJOTHI p16: `verified` -> `unverified`, deferred_tax_liabilities_net, period '2025', value_text '0.00'; results_period_not_a_period: '2025' is a year, not a period
- `12619` BHARTIARTL p32: `verified` -> `unverified`, count.countries, period '2025', value_text '17'; results_period_not_a_period: '2025' is a year, not a period
- `6684` ACCEDERE p13: `verified` -> `unverified`, deferred_tax_assets_net, period '2026', value_text '6.77'; results_period_not_a_period: '2026' is a year, not a period
- `39651` ANANDRATHI p3: `verified` -> `unverified`, count.shares, period 'November 11, 2024', value_text '8,30,20,634'; basis_unstated: the filing prints a standalone and a consolidated statement and neither this page nor the page before names which one this row comes from
- `6690` ACCEDERE p13: `verified` -> `unverified`, cash_and_cash_equivalents, period '2025', value_text '31.11'; results_period_not_a_period: '2025' is a year, not a period
- `12534` ALEMBICLTD p15: `verified` -> `unverified`, inventories, period '2026', value_text '5,224'; results_period_not_a_period: '2026' is a year, not a period
- `12642` BHARTIARTL p32: `verified` -> `unverified`, ebitda, period '2024', value_text '889,064'; results_period_not_a_period: '2024' is a year, not a period
- `36559` AMARJOTHI p16: `verified` -> `unverified`, other_bank_balances, period '2025', value_text '23.19'; results_period_not_a_period: '2025' is a year, not a period
- `36543` AMARJOTHI p16: `verified` -> `unverified`, NEW:other_non_current_financial_assets, period '2025', value_text '0.00'; results_period_not_a_period: '2025' is a year, not a period
- `6682` ACCEDERE p13: `verified` -> `unverified`, long_term_loans_and_advances, period '2025', value_text '83.24'; results_period_not_a_period: '2025' is a year, not a period
- `6681` ACCEDERE p13: `verified` -> `unverified`, long_term_loans_and_advances, period '2026', value_text '91.49'; results_period_not_a_period: '2026' is a year, not a period
- `36568` AMARJOTHI p16: `verified` -> `unverified`, total_current_assets, period '2026', value_text '18359.16'; results_period_not_a_period: '2026' is a year, not a period
- `36560` AMARJOTHI p16: `verified` -> `unverified`, loans, period '2026', value_text '0.00'; results_period_not_a_period: '2026' is a year, not a period
- `12544` ALEMBICLTD p15: `verified` -> `unverified`, other_financial_assets, period '2026', value_text '353'; results_period_not_a_period: '2026' is a year, not a period
- `36535` AMARJOTHI p16: `verified` -> `unverified`, NEW:biological_assets_other_than_bearer_plants, period '2025', value_text '0.00'; results_period_not_a_period: '2025' is a year, not a period

#### results_unit: 53 downgraded, 20 random (seed 7)

- `44886` ARCHIDPLY p16: `verified` -> `unverified`, finance_cost, period 'FOR YEAR ENDED 31 MARCH, 2026', value_text '1,734.42'; results_unit: previous page prints Lakhs
- `44956` ARCHIDPLY p7: `verified` -> `unverified`, borrowings, period 'FOR YEAR ENDED 31 MARCH, 2025', value_text '1,500.00'; results_unit: document prints Lakhs
- `44827` ARCHIDPLY p16: `verified` -> `unverified`, finance_cost, period 'FOR YEAR ENDED 31 MARCH, 2026', value_text '1,768.90'; results_unit: previous page prints Lakhs
- `43690` APOLLOIN p7: `verified` -> `unverified`, other_current_liabilities, period '30.09.2026', value_text '-1.62'; results_unit: previous page prints Lakhs
- `44958` ARCHIDPLY p7: `verified` -> `unverified`, borrowings, period 'FOR YEAR ENDED 31 MARCH, 2025', value_text '7.40'; results_unit: document prints Lakhs
- `43710` APOLLOIN p7: `verified` -> `unverified`, equity_share_capital, period '30.09.2026', value_text '0.00'; results_unit: previous page prints Lakhs
- `44955` ARCHIDPLY p7: `verified` -> `unverified`, borrowings, period 'FOR YEAR ENDED 31 MARCH, 2026', value_text '1,650.00'; results_unit: document prints Lakhs
- `43708` APOLLOIN p7: `verified` -> `unverified`, borrowings, period '30.09.2026', value_text '-2.83'; results_unit: previous page prints Lakhs
- `5646` APPL p7: `verified` -> `unverified`, NEW:share_issue_premium, period 'half year under review', value_text '270'; results_unit: previous page prints Lakhs
- `44828` ARCHIDPLY p16: `verified` -> `unverified`, finance_cost, period 'FOR YEAR ENDED 31 MARCH, 2025', value_text '1,774.11'; results_unit: previous page prints Lakhs
- `44961` ARCHIDPLY p7: `verified` -> `unverified`, lease_liabilities, period 'FOR YEAR ENDED 31 MARCH, 2026', value_text '122.88'; results_unit: document prints Lakhs
- `43674` APOLLOIN p7: `verified` -> `unverified`, depreciation_and_amortisation_expense, period '30.09.2026', value_text '15.00'; results_unit: previous page prints Lakhs
- `44901` ARCHIDPLY p7: `verified` -> `unverified`, finance_cost, period 'FOR YEAR ENDED 31 MARCH, 2025', value_text '809.66'; results_unit: document prints Lakhs
- `39649` ANANDRATHI p3: `verified` -> `unverified`, NEW:amount_securities_proposed_to_be_issued, period 'November 11, 2024', value_text 'Rs. 41,51,03,170'; results_unit: document prints Lakhs
- `44855` ARCHIDPLY p16: `verified` -> `unverified`, provisions, period 'FOR YEAR ENDED 31 MARCH, 2025', value_text '336.36'; results_unit: previous page prints Lakhs
- `22323` ADANIGREEN p26: `verified` -> `unverified`, NEW:acquisition_consideration, period 'April 2026', value_text 'USD 1,515,000'; results_unit: document prints Crores
- `43683` APOLLOIN p7: `verified` -> `unverified`, other_current_assets, period '30.09.2025', value_text '0.00'; results_unit: previous page prints Lakhs
- `44962` ARCHIDPLY p7: `verified` -> `unverified`, lease_liabilities, period 'FOR YEAR ENDED 31 MARCH, 2025', value_text '109.25'; results_unit: document prints Lakhs
- `39650` ANANDRATHI p3: `verified` -> `unverified`, NEW:bonus_ratio, period 'November 11, 2024', value_text '1:1'; results_unit: document prints Lakhs
- `43685` APOLLOIN p7: `verified` -> `unverified`, other_financial_assets, period '30.09.2025', value_text '-48.38'; results_unit: previous page prints Lakhs

#### results_equity_accounted: 17 downgraded, 20 random (seed 7)

- `17731` ABCAPITAL p22: `verified` -> `unverified`, NEW:gross_stage_3_ratio, period 'Q1 FY27', value_text '1.30%'; results_equity_accounted: 'Gross stage 3 ratio improved by 97 bps year-on-year and 3 bps sequentially to 1.30%' is the equity-accounted business (business), not a consolidated figu
- `17749` ABCAPITAL p22: `verified` -> `unverified`, aum.value, period 'Q1 FY27', value_text '1,98,722'; results_equity_accounted: 'Equity QAAUM grew by 10% year-on-year to ₹ 1,98,722 crore' is the equity-accounted business (business), not a consolidated figure
- `17747` ABCAPITAL p22: `verified` -> `unverified`, aum.value, period 'Q1 FY27', value_text '4,27,675'; results_equity_accounted: 'Mutual fund quarterly average assets under management grew by 6% year-on year to 4,27,675 crore' is the equity-accounted business (asset management), not
- `17746` ABCAPITAL p22: `verified` -> `unverified`, aum.growth_yoy, period 'Q1 FY27', value_text '6%'; results_equity_accounted: 'Mutual fund quarterly average assets under management grew by 6% year-on year to 4,27,675 crore' is the equity-accounted business (asset management), not
- `17725` ABCAPITAL p22: `verified` -> `unverified`, profit_before_tax, period 'Q1 FY27', value_text '1,222'; results_equity_accounted: 'Profit before tax grew by 32% year-on-year and 10% sequentially to ₹ 1,222 crore' is the equity-accounted business (business), not a consolidated figure
- `17719` ABCAPITAL p22: `verified` -> `unverified`, loans.disbursement, period 'Q1 FY27', value_text '21,201'; results_equity_accounted: 'Disbursements grew by 34% year-on-year to ₹ 21,201 crore' is the equity-accounted business (business), not a consolidated figure
- `17720` ABCAPITAL p22: `verified` -> `unverified`, aum.growth_yoy, period 'Q1 FY27', value_text '28%'; results_equity_accounted: 'AUM grew by 28% year-on-year and 5% sequentially to ₹ 1,67,456 crore' is the equity-accounted business (business), not a consolidated figure
- `17748` ABCAPITAL p22: `verified` -> `unverified`, aum.growth_yoy, period 'Q1 FY27', value_text '10%'; results_equity_accounted: 'Equity QAAUM grew by 10% year-on-year to ₹ 1,98,722 crore' is the equity-accounted business (business), not a consolidated figure
- `17724` ABCAPITAL p22: `verified` -> `unverified`, profit_before_tax_growth_qoq, period 'Q1 FY27', value_text '10%'; results_equity_accounted: 'Profit before tax grew by 32% year-on-year and 10% sequentially to ₹ 1,222 crore' is the equity-accounted business (business), not a consolidated figure
- `17722` ABCAPITAL p22: `verified` -> `unverified`, aum.value, period 'Q1 FY27', value_text '1,67,456'; results_equity_accounted: 'AUM grew by 28% year-on-year and 5% sequentially to ₹ 1,67,456 crore' is the equity-accounted business (business), not a consolidated figure
- `17729` ABCAPITAL p22: `verified` -> `unverified`, NEW:gross_stage_3_ratio_change_yoy_bps, period 'Q1 FY27', value_text '97'; results_equity_accounted: 'Gross stage 3 ratio improved by 97 bps year-on-year and 3 bps sequentially to 1.30%' is the equity-accounted business (business), not a consolidated figu
- `17721` ABCAPITAL p22: `verified` -> `unverified`, NEW:aum_growth_sequential, period 'Q1 FY27', value_text '5%'; results_equity_accounted: 'AUM grew by 28% year-on-year and 5% sequentially to ₹ 1,67,456 crore' is the equity-accounted business (business), not a consolidated figure
- `17727` ABCAPITAL p22: `verified` -> `unverified`, NEW:return_on_assets_change_sequential_bps, period 'Q1 FY27', value_text '8'; results_equity_accounted: 'Return on assets increased by 14 bps year-on-year and 8 bps sequentially to 2.39%' is the equity-accounted business (business), not a consolidated figure
- `17728` ABCAPITAL p22: `verified` -> `unverified`, roa, period 'Q1 FY27', value_text '2.39%'; results_equity_accounted: 'Return on assets increased by 14 bps year-on-year and 8 bps sequentially to 2.39%' is the equity-accounted business (business), not a consolidated figure
- `17723` ABCAPITAL p22: `verified` -> `unverified`, profit_before_tax_growth_yoy, period 'Q1 FY27', value_text '32%'; results_equity_accounted: 'Profit before tax grew by 32% year-on-year and 10% sequentially to ₹ 1,222 crore' is the equity-accounted business (business), not a consolidated figure
- `17726` ABCAPITAL p22: `verified` -> `unverified`, NEW:return_on_assets_change_yoy_bps, period 'Q1 FY27', value_text '14'; results_equity_accounted: 'Return on assets increased by 14 bps year-on-year and 8 bps sequentially to 2.39%' is the equity-accounted business (business), not a consolidated figure
- `17718` ABCAPITAL p22: `verified` -> `unverified`, loans.disbursement_share, period 'Q1 FY27', value_text '34%'; results_equity_accounted: 'Disbursements grew by 34% year-on-year to ₹ 21,201 crore' is the equity-accounted business (business), not a consolidated figure

#### results_current_mismatch: 13 downgraded, 20 random (seed 7)

- `48807` ASAL p5: `verified` -> `unverified`, current_tax_assets_net, period 'September 30, 2026', value_text '100.78'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `40444` ANDREWYU p12: `verified` -> `unverified`, current_tax_assets_net, period 'As at March 31 , 2026', value_text '1657.07'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `10174` ACEVECTOR p14: `verified` -> `unverified`, current_tax_assets_net, period 'March 31, 2026', value_text '45.80'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `5668` ACC p19: `verified` -> `unverified`, current_tax_assets_net, period 'March 31, 2025', value_text '714.51'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `5667` ACC p19: `verified` -> `unverified`, current_tax_assets_net, period 'March 31, 2026', value_text '117.39'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `40589` ANDREWYU p19: `verified` -> `unverified`, current_tax_assets_net, period 'As at March 31, 2026', value_text '1,657.07'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `40588` ANDREWYU p19: `verified` -> `unverified`, current_tax_assets_net, period 'As at September 30, 2026', value_text '1711.23'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `48808` ASAL p5: `verified` -> `unverified`, current_tax_assets_net, period 'March 31, 2026', value_text '279.28'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `38111` AMPVOLTS p7: `verified` -> `unverified`, current_tax_assets_net, period '31-Mar-25', value_text '9.91'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `727` AVALON p11: `verified` -> `unverified`, current_tax_assets_net, period 'March 31, 2025', value_text '28.52'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `24764` ADROITINFO p11: `verified` -> `unverified`, current_tax_assets_net, period '31-Mar-26', value_text '65.86'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `49671` ASHIMASYN p18: `verified` -> `unverified`, current_tax_assets_net, period 'As at 31/03/2026', value_text '372'; results_current_mismatch: section is non_current under 'current_tax_assets_net'
- `40445` ANDREWYU p12: `verified` -> `unverified`, current_tax_assets_net, period 'As at March 31, 2025', value_text '1,199.05'; results_current_mismatch: section is non_current under 'current_tax_assets_net'

## results gates r3e (27 Nov 2026, T-242, r3d baseline copy)

Five structural fixes from results ckpt_0002 (Eagle's fix note `D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_0002.fix.md`),
each a rule in `apply_results_row_gates` (`reality_engine/v2/observations.py`): a comprise/consist-of/include component keeps
the heading's measure and a component repeating the block's printed total is unverified; a P&L flow measure under a
cash-flow statement title (on the page or carried from the page before) is the statement's line; a balance-sheet stock
takes the printed `As at` date, never a filled flow duration; a note line naming another entity as a subsidiary/associate
scopes the row and unverifies it; an ordinal `value_text` is quarantined.

Measurement: a scratch pass over the r3d baseline copy `.tmp/r3e_base.db` (copy of `C:/RealityEngine/t242/results_r3d/base.db`)
re-applying `apply_results_row_gates` + `gate_not_company` to every page with rows, no model and no fetch: 5,176 pages,
141,936 rows, 31,749 verified before. The 46 pilot60 stores (`c04`..`c60`) another process held write-locked were read
through an immutable connection, and the doc-level scale/basis scan (`_results_doc_context`, ~1,700 docs) was left out of
this pass because no r3e rule reads it.

| rule | rows hit | of which verified -> not verified |
|---|---:|---:|
| `results_component_family` (component keeps the heading's measure) | 14 | 0 |
| `results_component_is_total` (component repeats the block total) | 2 | 1 |
| `results_cash_flow_measure` (P&L flow line under a cash-flow title) | 1,103 | 267 |
| `results_stock_duration` (stock row takes `As at`, no duration fill) | 36 | 3 (33 period rewrites, status kept) |
| `results_note_entity` (note names a subsidiary/associate) | 53 | 14 |
| `results_not_a_figure` ordinal (`33rd` is not 33) | 29 | 4 -> quarantined |

r3e-attributable verified downgrades: 289 of 31,749 (0.91%); no single rule over the 3% stop bar (largest: cash-flow 0.84%).

The six ckpt_0002 cases now: APMIN p5 obs 43952 `verified` -> `unverified` (`results_component_is_total`);
ASTRONMULT p4 obs 4987 `other_bank_balances` -> `cash_and_cash_equivalents` (status kept); ARCHIDPLY p7 obs 44943
`finance_income` -> `NEW:interest_received_cash_flow` unverified; AMIC p14 obs 37433 period `Half year ended 31.03.2026`
-> `As at 31.03.2026` (status kept); ALANKIT p7 obs 32092 `subsidiary` + unverified (`results_note_entity`); BLUECOAST p1
obs 11486 `33rd` -> `quarantined`.

### Graded-R rows (results_ckpt1 / results_grade_r2 / results_grade_r3c / results_ckpt2)

0 r3e-attributable status changes. All eight R-row downgrades in this pass come from the already-merged r3d residue rule
(`results_period_duration_ambiguous`), which the r3d base copy predates: ckpt1 ASARFI (48901), AAVAS (8962); r2 BBTCL
(3906); r3c AKSHOPTFBR (11178), AMITSEC (37761); ckpt2 AEONXDIGI (26019), AVONMORE (94458), AKSHOPTFBR (11185). That
was r3d's own defect, fixed in r3d2 (`## results gates r3d2` below): each now keeps its base period and `verified`,
and r3e keeps 0 of its own graded-R changes. The ckpt_0002 W/J rows change as
intended: 43952 unverified, 44943 unverified, 32092 unverified, 11486 quarantined, 4987 and 37433 attributes only.

### Seeded 20-row samples per new rule (seed 7, page text read for each)

- `results_component_family` (14 rows, all sampled): 14/14 right - every row is a cash component printed under a
  "Cash and Cash Equivalents Comprise(s)/include(s)" heading (ASTRONMULT `Current Account`, APMIN `Balances with Banks`,
  AROGRANITE `In Other Fixed Deposit Accounts`, BHAGCHEM `In current accounts`).
- `results_component_is_total` (2 rows): 2/2 right - APMIN's component line carries the end-of-period total (10) and the
  current-period total (5), never the 8 it prints as the component.
- `results_cash_flow_measure` (20 of 1,103): 17/20 = 85% right - `Interest received`, `Finance costs`, `Depreciation` on
  a printed cash-flow statement (ARTSON, ACC, APOLLOTYRE, ATGL, ACCURACY) become `NEW:*_cash_flow`. 3 wrong: ACLD p5
  (P&L "EXPENSES" page whose previous page ends with a cash-flow title) remapped its P&L cost lines; all three were
  already unverified.
- `results_stock_duration` (20 of 36): 20/20 are stock rows (`non_controlling_interest` on a balance sheet); 17 take the
  printed `As at` date (AMIC, ABFRL, ANURAS, BIKAJI, BERGEPAINT), 3 strip a duration the page's OCR garbles ("Aaat")
  and stay unverified.
- `results_note_entity` (20 of 53): 18/20 = 90% right - the note line names the entity and calls it a subsidiary/associate
  (ALANKIT `Share premium`, AGARWALEYE 12.25% of `Aditya Jyot Eye Hospital`, ADANIGREEN exceptional items of
  `Adani Solar Energy Jaisalmer Two`, AGRIBIO associate's total assets). 2 wrong: an investment *in* a subsidiary
  (ANSALBU `Invested Rs. 34.01 Crores ... to Ansal Crown Infrabuild`) and a step-down holding percentage read as the
  entity's own figure.
- ordinal (`results_not_a_figure`, 20 of 29): 20/20 right - board-meeting dates (`28th`), AGM numbers (`11th`), filing
  quarters (`01st`, `04th`), `1st to market`, a `5th Floor` address line and BLUECOAST's `33rd Board's Report`.

## results gates r3d2 (27 Nov 2026, T-242, r3d/r3e baseline)

r3d's `results_period_duration_ambiguous` residue rule grouped rows on one page by
`(printed_label, basis, segment, date_key)` only. Distinct measures that print the same label for the same date -- `Total`
on a balance sheet, `b. Services` in a segment table, `(a) Investments activities` twice -- therefore looked like one
label holding two values, and every row of that label was stripped to the bare date and `unverified`. r3d2 adds
`measure` to the group key in `_results_resolve_residue_periods`: the rule abstains (the row keeps its own period,
`period_source` and status) unless one measure carries >= 2 distinct values for one date key under one label; inside
such a group the r3d behaviour is unchanged (duration by column position, else the bare printed date). `measure` also
joins the group key of `reality_engine/scripts/results_r3d_residue.py`, so its residue count means the same thing.

The eight graded-R rows keep their base period and `verified` against the r3d copy `C:/RealityEngine/t242/results_r3d/base.db`
page text (stores `C:/RealityEngine/tg_build/universe_fy27`, read-only): ASARFI 48901 (`30-Jun-26`), AAVAS 8962
(`September 2026`), BBTCL 3906 (`For the year ended March 31, 2025`), AKSHOPTFBR 11178/11185 (`Mar-26`/`Mar-25`),
AMITSEC 37761 (`Corresponding 3 months ended in the previous year 30.06.2025`), AEONXDIGI 26019 (`Half Year Ended
September 30, 2026`), AVONMORE 94458 (`Sept 30, 2026`). Each is a parametrised case of
`test_r3d2_graded_r_row_keeps_its_period_and_status` in `reality_engine/tests/test_results_gates.py`, built from the real
page text and every row that printed that label for that date. r3d's AGARWALEYE, AANCHALISP and residue-counter evidence
tests still pass unchanged.

Accept (`pytest -q <file>` each separately): test_results_gates.py 64 passed, test_observations.py 177 passed,
test_ar_sections.py 42 passed, test_deck_guards.py 37 passed.

## results gates r3f (27 Nov 2026, T-242, r3d baseline copy)

Two fix notes name the kinds r3d/r3e do not cover (`D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_0003.fix.md`,
`ckpt_0004.fix.md`) and the pack pages are `C:/RealityEngine/t242/results_ckpt3|4/pack.jsonl`. Seven script-only rules in
`apply_results_row_gates` (`reality_engine/v2/observations.py`), no model and no fetch:

| kind | rule | ckpt3/4 case |
|---|---|---|
| OCR bracket / split digits | `_results_ocr_value_reason` + `_results_join_digits` | ALOKINDS `{171.56)` -> -171.56; ATGL `(2 69)` -> -2.69; AEQUS `3, 221 59` -> 3221.59 |
| garbled OCR value | `_results_garbled_value_reason` -> quarantined | ARSSINFRA `-2,1::!.J.:?.9` |
| measure from the section | `_results_in_cf_section` (BS measure/exceptional only), `RESULTS_GENERIC_TWINS`, `_results_pnl_charge_reason` | APTUS `Issue of equity shares`; AZADIND `Extraordinary items`; AAYUSH `(b) Provisions` -> `long_term_provisions`; BANDHANBNK P&L provisions charge |
| change, not balance | `_results_change_not_balance_reason` (`value_kind='change'`) | HDFCAMC DTL `had increased by` 69.75 crore |
| share-count table | `_results_share_count_reason` (Number column, page scale 1e5) | ATMAIND preference shares 2.50 lakh |
| segment column / geography | `_results_column_period_reason` (+ `_results_ordered_columns`, `_results_ocr_dates`), `_results_geography_row_reason` | AEQUS `Aerospace` -> `Quarter ended March 31, 2026`; BHARATROHAN -> `Half year ended 30th September, 2025`; ARTEMISMED `India` segment + unverified |
| own statement scope | `_results_own_statement_heading` | ASTRONMULT p2 `subsidiary` -> `company` |

Guards that keep the rules safe: a comma group that is not 3 digits (`22, 2025`) or a 4-digit tail (`31, 2026`) never
joins; opening/closing cash balances and `capex` keep their measure; a printed `Components of Cash & Cash Equivalents`
note stops the cash-flow section; a partial header (`March 2026`, `September 30`), a date printed under two columns and a
mixed-duration table all make the column rule abstain.

**Measurement (per-row gate pass; the full `--recheck` did not finish inside the sandbox's 10-minute call cap).** A copy of
`C:/RealityEngine/t242/results_r3d/base.db` was taken with the sqlite backup API into `.tmp/t242_r3f/base.db`; the gates
were re-applied to each row of the six graded packs with that pack's own `page_text` and `previous_page_text`, exactly the
function the recheck calls.

| pack | changed rows | graded-R changes |
|---|---:|---:|
| results_ckpt1 | 2 | 0 |
| results_grade_r2 | 0 | 0 |
| results_grade_r3c | 0 | 0 |
| results_ckpt2 | 4 | 0 |
| results_ckpt3 | 6 | 0 |
| results_ckpt4 | 6 | 0 |
| **all** | **18** | **0** |

All 18 changed rows are named in their fix note (16 ckpt3/ckpt4 W rows + the ckpt1/ckpt2 rows their own note names). The
14 named ckpt3/ckpt4 W rows: AEQUS 124746 period, ATGL 88210 value, ARSSINFRA 3944 quarantined, ALOKINDS 35145 value,
APTUS 44528 measure+period, ADHBHUTIN 23312 measure (r3e), AZADIND 160543 measure, AAYUSH 192254 measure, HDFCAMC
187965 unverified+`change`, BANDHANBNK 10787 unverified, BHARATROHAN 109749 period, ATMAIND 89866 measure+scale,
ARTEMISMED 47404 segment+unverified, ASTRONMULT 86910 scope.

**Seed-7 sample (200 pages, all with store page text).** 5,176 observation pages sampled; for each page the gates ran over
its rows with the store's `doc_page` text and the page before it:

| rule | triggers on 200 pages | judged |
|---|---:|---|
| OCR bracket / split | 13 | 13/13 right (BLUESTONE, ABFRL, ANIRIT, BALLARPUR x5, AMBUJACEM x2, ARKADE x2, AEIM) |
| garbled OCR | 0 | pack row + counter test right |
| measure from the section | 112 | 20/20 judged right (AIAENG, ACCURACY, ALPINEHOU, ACI, ANSALAPI) |
| change, not balance | 1 | 1/1 right (AHLEAST hypothetical reduction) |
| share-count table | 0 | pack row + counter test right |
| segment column / geography | 0 after the guards | pack rows AEQUS/BHARATROHAN/ARTEMISMED + 3MINDIA/ABLBL/AURUS abstain |
| own statement scope | 0 | pack row + counter test right |

The AURUS `Total Tax Expense` case (a value printed under two date-ambiguous columns) was the reason for the duplicate-date
abstain; the ABLBL page (`September 30` split from its year) for the partial-header abstain.

The full recheck of the baseline copy did start (`--recheck --baseline .tmp/t242_r3f/base.db --out .tmp/t242_r3f/out.db
--stores-root C:/RealityEngine/tg_build/universe_fy27 --doc-types results`) but was still on its first pass when the
10-minute call cap ended it; a scoped `--only` selector over the six packs' 264 documents / 35 page numbers also exceeded
20 minutes. The full recheck remains owed.

Accept (`pytest -q <file>` each separately): test_results_gates.py 72 passed (7 new r3f tests), test_observations.py 177
passed, test_ar_sections.py 42 passed, test_deck_guards.py 37 passed.
