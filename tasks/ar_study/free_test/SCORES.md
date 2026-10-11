# Free-reader AR test: scores

## dots

| report | part | rows | numbers checked | not in text | pages outside | notes |
|---|---|---|---|---|---|---|
| GESHIP | S1_agm_notice | 545 | 233 | 0 | 0 | 37 malformed rows; output cut at max_tokens |
| GESHIP | S2_chairman_esg_highlights | 657 | 311 | 0 | 0 | 63 malformed rows; output cut at max_tokens |
| GESHIP | S3_boards_report_annexures_secretarial | 650 | 528 | 3 | 0 | 1 malformed rows; output cut at max_tokens |
| GESHIP | S4_corp_governance | 132 | 126 | 0 | 0 |  |
| GESHIP | S5_brsr | 93 | 86 | 0 | 0 |  |
| GESHIP | S6_fleet_auditor_caro | 72 | 53 | 0 | 0 |  |
| GESHIP | S7_standalone_fs_notes | 706 | 644 | 3 | 0 | 10 malformed rows; output cut at max_tokens |
| GESHIP | S8a_consolidated_p135-150 | 367 | 349 | 1 | 0 |  |
| GESHIP | S8b_consolidated_p151-171 | 644 | 637 | 2 | 0 |  |
| CONCOR | p1-50 | 417 | 280 | 4 | 0 | 118 malformed rows |
| CONCOR | p101-150 | 112 | 105 | 1 | 0 | 10 malformed rows |
| CONCOR | p151-200 | 369 | 166 | 0 | 0 |  |
| CONCOR | p201-250 | 653 | 587 | 0 | 0 | 1 malformed rows; output cut at max_tokens |
| CONCOR | p251-300 | 406 | 401 | 0 | 0 | 1 malformed rows |
| CONCOR | p301-350 | 384 | 327 | 0 | 0 | 20 malformed rows |
| CONCOR | p351-400 | 627 | 596 | 2 | 0 | 1 malformed rows; output cut at max_tokens |
| CONCOR | p401-432 | 75 | 52 | 1 | 0 | 1 malformed rows |
| CONCOR | p51-100 | 0 | 0 | 0 | 0 | no CSV header |
| COCHINSHIP | p1-50 | 91 | 70 | 1 | 0 |  |
| COCHINSHIP | p101-150 | 495 | 460 | 1 | 0 | 91 malformed rows |
| COCHINSHIP | p151-200 | 126 | 122 | 3 | 0 |  |
| COCHINSHIP | p201-250 | 628 | 626 | 2 | 0 | 40 malformed rows; output cut at max_tokens |
| COCHINSHIP | p251-300 | 227 | 217 | 0 | 0 | 1 malformed rows |
| COCHINSHIP | p301-350 | 614 | 614 | 0 | 0 | 1 malformed rows |
| COCHINSHIP | p351-362 | 55 | 26 | 1 | 0 | 38 malformed rows |
| COCHINSHIP | p51-100 | 157 | 153 | 0 | 0 | 13 malformed rows |

**Must-find recall: 23/25**; numbers not found in the text: 25/7769 (0.3%); rows 9302

- OK  CSL-ocf-standalone p151-200 p156
- OK  CSL-ocf-fy23 p151-200 p156
- MISS CSL-ocf-consolidated 
- OK  CSL-contract-liab p151-200 p197
- OK  CSL-1200-pax-vessels p1-50 p24
- OK  CSL-sbfa-reversal p1-50 p37
- MISS CSL-sap-edit-log 
- OK  CON-kam-tughlakabad p401-432 p413
- OK  CON-kam-phillaur p401-432 p413
- OK  CON-kam-moradabad p401-432 p413
- OK  CON-land-lease-rou p201-250 p206
- OK  CON-seis-861 p201-250 p237
- OK  CON-receivables p1-50 p7
- OK  CON-brsr-rpt-purchases p151-200 p161
- OK  GES-audit-trail S6_fleet_auditor_caro p102
- OK  GES-capcom-standalone S7_standalone_fs_notes p127
- OK  GES-capcom-consolidated S8b_consolidated_p151-171 p162
- OK  GES-care-aaa S4_corp_governance p75
- OK  GES-tc-receivables S8b_consolidated_p151-171 p167
- OK  GES-brsr-loans-rp S5_brsr p83
- OK  GES-brsr-invest-rp S5_brsr p83
- OK  GES-csr-obligation S3_boards_report_annexures_secretarial p47
- OK  GES-csr-spent S3_boards_report_annexures_secretarial p47
- OK  GES-csr-unspent S7_standalone_fs_notes p116
- OK  GES-eu-ets S1_agm_notice p14

## gemma

| report | part | rows | numbers checked | not in text | pages outside | notes |
|---|---|---|---|---|---|---|
| GESHIP | S1_agm_notice#1 | 7 | 0 | 0 | 0 |  |
| GESHIP | S1_agm_notice#2 | 7 | 6 | 0 | 0 |  |
| GESHIP | S2_chairman_esg_highlights#1 | 29 | 28 | 0 | 0 |  |
| GESHIP | S2_chairman_esg_highlights#2 | 22 | 17 | 0 | 0 |  |
| GESHIP | S3_boards_report_annexures_secretarial#1 | 64 | 64 | 0 | 10 |  |
| GESHIP | S3_boards_report_annexures_secretarial#2 | 15 | 14 | 0 | 4 |  |
| GESHIP | S3_boards_report_annexures_secretarial#3 | 22 | 21 | 0 | 0 | 11 malformed rows |
| GESHIP | S3_boards_report_annexures_secretarial#4 | 49 | 46 | 0 | 0 | 3 malformed rows |
| GESHIP | S4_corp_governance#1 | 13 | 12 | 0 | 0 | 1 malformed rows |
| GESHIP | S4_corp_governance#2 | 9 | 9 | 0 | 0 | 7 malformed rows |
| GESHIP | S4_corp_governance#3 | 21 | 15 | 0 | 0 |  |
| GESHIP | S5_brsr#1 | 52 | 51 | 0 | 0 | 1 malformed rows |
| GESHIP | S5_brsr#2 | 38 | 38 | 0 | 0 |  |
| GESHIP | S5_brsr#3 | 16 | 16 | 0 | 0 |  |
| GESHIP | S6_fleet_auditor_caro#1 | 22 | 18 | 0 | 0 |  |
| GESHIP | S6_fleet_auditor_caro#2 | 19 | 18 | 0 | 0 |  |
| GESHIP | S7_standalone_fs_notes#1 | 13 | 13 | 0 | 0 |  |
| GESHIP | S7_standalone_fs_notes#2 | 12 | 12 | 0 | 0 |  |
| GESHIP | S7_standalone_fs_notes#3 | 37 | 34 | 0 | 0 |  |
| GESHIP | S7_standalone_fs_notes#4 | 51 | 51 | 0 | 0 |  |
| GESHIP | S7_standalone_fs_notes#5 | 65 | 64 | 0 | 0 |  |
| GESHIP | S8a_consolidated_p135-150#1 | 75 | 68 | 0 | 0 |  |
| GESHIP | S8a_consolidated_p135-150#2 | 19 | 19 | 0 | 0 |  |
| GESHIP | S8a_consolidated_p135-150#3 | 20 | 20 | 0 | 0 |  |
| GESHIP | S8a_consolidated_p135-150#4 | 22 | 22 | 0 | 0 |  |
| GESHIP | S8b_consolidated_p151-171#1 | 36 | 36 | 0 | 0 |  |
| GESHIP | S8b_consolidated_p151-171#2 | 45 | 45 | 1 | 0 |  |
| GESHIP | S8b_consolidated_p151-171#3 | 54 | 53 | 0 | 0 |  |
| CONCOR | p1-50#1 | 20 | 20 | 0 | 0 |  |
| CONCOR | p1-50#2 | 20 | 17 | 1 | 0 | 2 malformed rows |
| CONCOR | p1-50#3 | 14 | 10 | 0 | 0 |  |
| CONCOR | p1-50#4 | 33 | 33 | 0 | 0 | 33 malformed rows |
| CONCOR | p1-50#5 | 26 | 26 | 0 | 0 |  |
| CONCOR | p101-150#1 | 16 | 15 | 0 | 0 |  |
| CONCOR | p101-150#2 | 24 | 21 | 0 | 0 |  |
| CONCOR | p101-150#3 | 26 | 24 | 0 | 0 |  |
| CONCOR | p101-150#4 | 50 | 50 | 0 | 0 |  |
| CONCOR | p151-200#1 | 22 | 22 | 0 | 0 |  |
| CONCOR | p151-200#2 | 36 | 36 | 0 | 0 |  |
| CONCOR | p151-200#3 | 27 | 19 | 0 | 0 |  |
| CONCOR | p151-200#4 | 0 | 0 | 0 | 0 |  |
| CONCOR | p201-250#1 | 13 | 13 | 0 | 0 |  |
| CONCOR | p201-250#2 | 27 | 26 | 0 | 0 |  |
| CONCOR | p201-250#3 | 39 | 39 | 0 | 0 |  |
| CONCOR | p201-250#4 | 29 | 29 | 0 | 0 |  |
| CONCOR | p251-300#1 | 34 | 33 | 1 | 0 |  |
| CONCOR | p251-300#2 | 123 | 123 | 0 | 0 |  |
| CONCOR | p251-300#3 | 26 | 25 | 0 | 0 |  |
| CONCOR | p251-300#4 | 10 | 8 | 0 | 0 |  |
| CONCOR | p301-350#1 | 26 | 15 | 0 | 0 |  |
| CONCOR | p301-350#2 | 7 | 7 | 0 | 0 |  |
| CONCOR | p301-350#3 | 23 | 23 | 3 | 0 |  |
| CONCOR | p301-350#4 | 63 | 63 | 0 | 0 |  |
| CONCOR | p351-400#1 | 33 | 33 | 0 | 0 |  |
| CONCOR | p351-400#2 | 40 | 40 | 0 | 0 |  |
| CONCOR | p351-400#3 | 35 | 35 | 0 | 0 | 2 malformed rows |
| CONCOR | p351-400#4 | 21 | 21 | 0 | 0 |  |
| CONCOR | p401-432#1 | 31 | 31 | 0 | 0 |  |
| CONCOR | p401-432#2 | 18 | 8 | 0 | 0 | 18 malformed rows |
| CONCOR | p401-432#3 | 14 | 0 | 0 | 0 | 1 malformed rows |
| CONCOR | p51-100#1 | 22 | 21 | 0 | 0 |  |
| CONCOR | p51-100#2 | 19 | 13 | 1 | 0 |  |
| CONCOR | p51-100#3 | 26 | 23 | 2 | 0 |  |
| CONCOR | p51-100#4 | 12 | 12 | 0 | 0 |  |
| CONCOR | p51-100#5 | 4 | 3 | 0 | 0 |  |
| COCHINSHIP | p1-50#1 | 25 | 24 | 0 | 5 |  |
| COCHINSHIP | p1-50#2 | 31 | 29 | 0 | 0 |  |
| COCHINSHIP | p1-50#3 | 37 | 37 | 0 | 0 |  |
| COCHINSHIP | p1-50#4 | 13 | 13 | 0 | 2 |  |
| COCHINSHIP | p1-50#5 | 32 | 26 | 0 | 0 | 2 malformed rows |
| COCHINSHIP | p1-50#6 | 39 | 39 | 0 | 0 |  |
| COCHINSHIP | p101-150#1 | 38 | 38 | 0 | 0 | 1 malformed rows |
| COCHINSHIP | p101-150#2 | 29 | 29 | 0 | 0 |  |
| COCHINSHIP | p101-150#3 | 15 | 11 | 0 | 0 |  |
| COCHINSHIP | p101-150#4 | 13 | 11 | 0 | 0 |  |
| COCHINSHIP | p151-200#1 | 41 | 40 | 0 | 0 |  |
| COCHINSHIP | p151-200#2 | 6 | 5 | 0 | 0 |  |
| COCHINSHIP | p151-200#3 | 15 | 12 | 0 | 15 |  |
| COCHINSHIP | p151-200#4 | 51 | 51 | 0 | 2 |  |
| COCHINSHIP | p151-200#5 | 25 | 24 | 0 | 0 |  |
| COCHINSHIP | p201-250#1 | 34 | 34 | 0 | 0 |  |
| COCHINSHIP | p201-250#2 | 70 | 70 | 0 | 0 |  |
| COCHINSHIP | p201-250#3 | 30 | 26 | 0 | 0 |  |
| COCHINSHIP | p201-250#4 | 18 | 15 | 0 | 0 |  |
| COCHINSHIP | p251-300#1 | 9 | 7 | 0 | 0 | 1 malformed rows |
| COCHINSHIP | p251-300#2 | 2 | 1 | 0 | 0 |  |
| COCHINSHIP | p251-300#3 | 28 | 24 | 0 | 28 |  |
| COCHINSHIP | p251-300#4 | 46 | 46 | 1 | 0 |  |
| COCHINSHIP | p251-300#5 | 33 | 33 | 0 | 0 |  |
| COCHINSHIP | p301-350#1 | 50 | 50 | 0 | 0 |  |
| COCHINSHIP | p301-350#2 | 35 | 35 | 0 | 0 |  |
| COCHINSHIP | p301-350#3 | 32 | 32 | 0 | 0 |  |
| COCHINSHIP | p301-350#4 | 17 | 17 | 0 | 0 |  |
| COCHINSHIP | p351-362#1 | 4 | 3 | 0 | 0 |  |
| COCHINSHIP | p51-100#1 | 7 | 6 | 0 | 0 |  |
| COCHINSHIP | p51-100#2 | 21 | 21 | 0 | 0 |  |
| COCHINSHIP | p51-100#3 | 20 | 14 | 0 | 0 | 4 malformed rows |
| COCHINSHIP | p51-100#4 | 29 | 27 | 0 | 0 |  |
| COCHINSHIP | p51-100#5 | 41 | 41 | 0 | 0 |  |

**Must-find recall: 25/25**; numbers not found in the text: 10/2638 (0.4%); rows 2799

- OK  CSL-ocf-standalone p151-200#1 p156
- OK  CSL-ocf-fy23 p151-200#1 p156
- OK  CSL-ocf-consolidated p201-250#4 p248
- OK  CSL-contract-liab p151-200#5 p197
- OK  CSL-1200-pax-vessels p1-50#3 p24
- OK  CSL-sbfa-reversal p1-50#5 p37
- OK  CSL-sap-edit-log p101-150#3 p143
- OK  CON-kam-tughlakabad p251-300#3 p293
- OK  CON-kam-phillaur p251-300#3 p293
- OK  CON-kam-moradabad p251-300#3 p293
- OK  CON-land-lease-rou p251-300#1 p262
- OK  CON-seis-861 p201-250#3 p237
- OK  CON-receivables p1-50#1 p7
- OK  CON-brsr-rpt-purchases p151-200#1 p161
- OK  GES-audit-trail S6_fleet_auditor_caro#1 p102
- OK  GES-capcom-standalone S7_standalone_fs_notes#4 p128
- OK  GES-capcom-consolidated S8b_consolidated_p151-171#2 p162
- OK  GES-care-aaa S4_corp_governance#3 p75
- OK  GES-tc-receivables S8b_consolidated_p151-171#3 p167
- OK  GES-brsr-loans-rp S5_brsr#1 p79
- OK  GES-brsr-invest-rp S5_brsr#1 p83
- OK  GES-csr-obligation S3_boards_report_annexures_secretarial#1 p47
- OK  GES-csr-spent S3_boards_report_annexures_secretarial#1 p47
- OK  GES-csr-unspent S7_standalone_fs_notes#3 p116
- OK  GES-eu-ets S2_chairman_esg_highlights#1 p34

## glyph

| report | part | rows | numbers checked | not in text | pages outside | notes |
|---|---|---|---|---|---|---|
| GESHIP | S1_agm_notice | 21 | 12 | 1 | 0 |  |
| GESHIP | S2_chairman_esg_highlights | 67 | 49 | 1 | 0 |  |
| GESHIP | S3_boards_report_annexures_secretarial | 128 | 121 | 10 | 2 |  |
| GESHIP | S4_corp_governance | - | - | - | - | ERROR HTTP 408: {"error":"The upstream provider was unable to process the request","er |
| GESHIP | S5_brsr | - | - | - | - | ERROR HTTP 408: {"error":"The upstream provider was unable to process the request","er |
| GESHIP | S6_fleet_auditor_caro | 110 | 100 | 3 | 0 |  |
| GESHIP | S7_standalone_fs_notes | 108 | 106 | 1 | 0 |  |
| GESHIP | S8a_consolidated_p135-150 | - | - | - | - | ERROR HTTP 408: {"error":"The upstream provider was unable to process the request","er |
| GESHIP | S8b_consolidated_p151-171 | 82 | 75 | 3 | 0 | 3 malformed rows |
| CONCOR | p1-50 | 30 | 23 | 0 | 0 |  |
| CONCOR | p101-150 | 134 | 118 | 17 | 0 | 9 malformed rows |
| CONCOR | p151-200 | 115 | 111 | 0 | 0 |  |
| CONCOR | p201-250 | 86 | 72 | 1 | 0 |  |
| CONCOR | p251-300 | 68 | 64 | 12 | 14 |  |
| CONCOR | p301-350 | 89 | 69 | 0 | 0 | 1 malformed rows |
| CONCOR | p351-400 | - | - | - | - | ERROR HTTP 408: {"error":"The upstream provider was unable to process the request","er |
| CONCOR | p401-432 | 86 | 71 | 20 | 0 |  |
| CONCOR | p51-100 | 73 | 47 | 1 | 0 |  |
| COCHINSHIP | p1-50 | 141 | 98 | 5 | 6 | 4 malformed rows |
| COCHINSHIP | p101-150 | - | - | - | - | ERROR HTTP 408: {"error":"The upstream provider was unable to process the request","er |
| COCHINSHIP | p151-200 | - | - | - | - | ERROR HTTP 408: {"error":"The upstream provider was unable to process the request","er |
| COCHINSHIP | p201-250 | - | - | - | - | ERROR HTTP 408: {"error":"The upstream provider was unable to process the request","er |
| COCHINSHIP | p251-300 | 79 | 47 | 1 | 0 |  |
| COCHINSHIP | p301-350 | 61 | 58 | 8 | 15 |  |
| COCHINSHIP | p351-362 | 0 | 0 | 0 | 0 |  |
| COCHINSHIP | p51-100 | 121 | 91 | 2 | 0 |  |

**Must-find recall: 18/25**; numbers not found in the text: 86/1332 (6.5%); rows 1599

- MISS CSL-ocf-standalone 
- MISS CSL-ocf-fy23 
- MISS CSL-ocf-consolidated 
- MISS CSL-contract-liab 
- OK  CSL-1200-pax-vessels p1-50 p24
- OK  CSL-sbfa-reversal p1-50 p37
- OK  CSL-sap-edit-log p301-350 p341
- OK  CON-kam-tughlakabad p251-300 p292
- OK  CON-kam-phillaur p251-300 p292
- OK  CON-kam-moradabad p251-300 p292
- OK  CON-land-lease-rou p251-300 p291
- OK  CON-seis-861 p201-250 p235
- OK  CON-receivables p251-300 p230
- OK  CON-brsr-rpt-purchases p151-200 p159
- OK  GES-audit-trail S6_fleet_auditor_caro p102
- OK  GES-capcom-standalone S7_standalone_fs_notes p128
- OK  GES-capcom-consolidated S8b_consolidated_p151-171 p162
- MISS GES-care-aaa 
- OK  GES-tc-receivables S8b_consolidated_p151-171 p167
- MISS GES-brsr-loans-rp 
- MISS GES-brsr-invest-rp 
- OK  GES-csr-obligation S3_boards_report_annexures_secretarial p47
- OK  GES-csr-spent S3_boards_report_annexures_secretarial p47
- OK  GES-csr-unspent S3_boards_report_annexures_secretarial p67
- OK  GES-eu-ets S2_chairman_esg_highlights p28

## longcat

| report | part | rows | numbers checked | not in text | pages outside | notes |
|---|---|---|---|---|---|---|
| GESHIP | S1_agm_notice | 18 | 13 | 3 | 0 |  |
| GESHIP | S2_chairman_esg_highlights | 109 | 102 | 0 | 0 |  |
| GESHIP | S3_boards_report_annexures_secretarial | 119 | 103 | 0 | 0 |  |
| GESHIP | S4_corp_governance | 55 | 36 | 0 | 0 | 19 malformed rows |
| GESHIP | S5_brsr | 436 | 148 | 1 | 0 | 23 malformed rows |
| GESHIP | S6_fleet_auditor_caro | 38 | 19 | 0 | 0 | 13 malformed rows |
| GESHIP | S7_standalone_fs_notes | 141 | 129 | 0 | 0 |  |
| GESHIP | S8a_consolidated_p135-150 | 99 | 91 | 0 | 0 | 8 malformed rows |
| GESHIP | S8b_consolidated_p151-171 | 87 | 84 | 0 | 0 |  |
| CONCOR | p1-50 | 103 | 102 | 0 | 0 |  |
| CONCOR | p101-150 | 155 | 143 | 0 | 0 | 1 malformed rows |
| CONCOR | p151-200 | 51 | 45 | 0 | 0 | 7 malformed rows |
| CONCOR | p201-250 | 202 | 200 | 0 | 0 |  |
| CONCOR | p251-300 | 146 | 136 | 0 | 0 | 10 malformed rows |
| CONCOR | p301-350 | 86 | 84 | 1 | 0 |  |
| CONCOR | p351-400 | 160 | 17 | 0 | 0 | 144 malformed rows |
| CONCOR | p401-432 | 66 | 57 | 0 | 0 |  |
| CONCOR | p51-100 | 120 | 113 | 0 | 0 |  |
| COCHINSHIP | p1-50 | 719 | 595 | 1 | 0 | 2 malformed rows |
| COCHINSHIP | p101-150 | 84 | 76 | 0 | 0 | 6 malformed rows |
| COCHINSHIP | p151-200 | 685 | 636 | 10 | 0 | 50 malformed rows; output cut at max_tokens |
| COCHINSHIP | p201-250 | 266 | 257 | 2 | 0 |  |
| COCHINSHIP | p251-300 | 88 | 80 | 3 | 0 |  |
| COCHINSHIP | p301-350 | 357 | 350 | 0 | 0 | 5 malformed rows |
| COCHINSHIP | p351-362 | 15 | 6 | 1 | 0 | 1 malformed rows |
| COCHINSHIP | p51-100 | 317 | 124 | 0 | 0 | 76 malformed rows |

**Must-find recall: 25/25**; numbers not found in the text: 22/3746 (0.6%); rows 4722

- OK  CSL-ocf-standalone p151-200 p156
- OK  CSL-ocf-fy23 p151-200 p156
- OK  CSL-ocf-consolidated p201-250 p248
- OK  CSL-contract-liab p151-200 p197
- OK  CSL-1200-pax-vessels p1-50 p24
- OK  CSL-sbfa-reversal p1-50 p37
- OK  CSL-sap-edit-log p101-150 precording audit trail (edit log) facility of the accounting software was enabled on March, 2024
- OK  CON-kam-tughlakabad p251-300 p293
- OK  CON-kam-phillaur p251-300 p293
- OK  CON-kam-moradabad p251-300 p293
- OK  CON-land-lease-rou p251-300 pRefer Note no. 30, 39 and 51... no Right of Use (ROU) has been assessed
- OK  CON-seis-861 p201-250 p237
- OK  CON-receivables p1-50 p7
- OK  CON-brsr-rpt-purchases p151-200 p161
- OK  GES-audit-trail S6_fleet_auditor_caro p102
- OK  GES-capcom-standalone S7_standalone_fs_notes p128
- OK  GES-capcom-consolidated S8b_consolidated_p151-171 p151
- OK  GES-care-aaa S4_corp_governance pCARE AA+; Stable ... CARE AAA; Stable
- OK  GES-tc-receivables S8b_consolidated_p151-171 p167
- OK  GES-brsr-loans-rp S2_chairman_esg_highlights p40
- OK  GES-brsr-invest-rp S5_brsr p83
- OK  GES-csr-obligation S3_boards_report_annexures_secretarial p47
- OK  GES-csr-spent S3_boards_report_annexures_secretarial p47
- OK  GES-csr-unspent S7_standalone_fs_notes p116
- OK  GES-eu-ets S2_chairman_esg_highlights p35

## nemotron-ultra

| report | part | rows | numbers checked | not in text | pages outside | notes |
|---|---|---|---|---|---|---|
| GESHIP | S1_agm_notice | 55 | 35 | 15 | 0 |  |
| GESHIP | S2_chairman_esg_highlights | 84 | 69 | 1 | 1 |  |
| GESHIP | S3_boards_report_annexures_secretarial | - | - | - | - | ERROR ('Connection aborted.', RemoteDisconnected('Remote end closed connection without |
| GESHIP | S4_corp_governance | - | - | - | - | ERROR HTTP 200: {"id":"gen-1791727606-2qDEhCsj3ylpaJAeDMsV","error":{"message":"Upstre |
| GESHIP | S5_brsr | - | - | - | - | ERROR ('Connection aborted.', RemoteDisconnected('Remote end closed connection without |
| GESHIP | S6_fleet_auditor_caro | 51 | 41 | 2 | 0 |  |
| GESHIP | S7_standalone_fs_notes | - | - | - | - | ERROR ('Connection aborted.', RemoteDisconnected('Remote end closed connection without |
| GESHIP | S8a_consolidated_p135-150 | - | - | - | - | ERROR ('Connection aborted.', RemoteDisconnected('Remote end closed connection without |
| GESHIP | S8b_consolidated_p151-171 | - | - | - | - | ERROR ('Connection aborted.', RemoteDisconnected('Remote end closed connection without |
| CONCOR | p1-50 | - | - | - | - | ERROR ('Connection aborted.', RemoteDisconnected('Remote end closed connection without |
| CONCOR | p101-150 | - | - | - | - | ERROR ('Connection aborted.', RemoteDisconnected('Remote end closed connection without |
| CONCOR | p151-200 | 135 | 124 | 0 | 0 |  |

**Must-find recall: 4/25**; numbers not found in the text: 18/269 (6.7%); rows 325

- MISS CSL-ocf-standalone 
- MISS CSL-ocf-fy23 
- MISS CSL-ocf-consolidated 
- MISS CSL-contract-liab 
- MISS CSL-1200-pax-vessels 
- MISS CSL-sbfa-reversal 
- MISS CSL-sap-edit-log 
- MISS CON-kam-tughlakabad 
- MISS CON-kam-phillaur 
- MISS CON-kam-moradabad 
- MISS CON-land-lease-rou 
- MISS CON-seis-861 
- MISS CON-receivables 
- OK  CON-brsr-rpt-purchases p151-200 p160
- OK  GES-audit-trail S6_fleet_auditor_caro p102
- MISS GES-capcom-standalone 
- MISS GES-capcom-consolidated 
- MISS GES-care-aaa 
- MISS GES-tc-receivables 
- OK  GES-brsr-loans-rp S2_chairman_esg_highlights p40
- MISS GES-brsr-invest-rp 
- MISS GES-csr-obligation 
- MISS GES-csr-spent 
- MISS GES-csr-unspent 
- OK  GES-eu-ets S2_chairman_esg_highlights p35

## nim-super

| report | part | rows | numbers checked | not in text | pages outside | notes |
|---|---|---|---|---|---|---|
| GESHIP | S1_agm_notice | 755 | 9 | 6 | 6 | 1 malformed rows; output cut at max_tokens |
| GESHIP | S2_chairman_esg_highlights | 32 | 18 | 0 | 0 | 1 malformed rows |
| GESHIP | S3_boards_report_annexures_secretarial | 106 | 74 | 8 | 0 | 18 malformed rows |
| GESHIP | S4_corp_governance | 42 | 27 | 0 | 8 | 10 malformed rows |
| GESHIP | S5_brsr | 278 | 157 | 0 | 75 | 32 malformed rows |
| GESHIP | S6_fleet_auditor_caro | 45 | 43 | 12 | 14 | 36 malformed rows |
| GESHIP | S7_standalone_fs_notes | 122 | 110 | 0 | 31 | 14 malformed rows |
| GESHIP | S8a_consolidated_p135-150 | 434 | 138 | 2 | 0 | 263 malformed rows; output cut at max_tokens |
| GESHIP | S8b_consolidated_p151-171 | 567 | 459 | 1 | 2 | 48 malformed rows; output cut at max_tokens |
| CONCOR | p1-50 | 0 | 0 | 0 | 0 | no CSV header |
| CONCOR | p101-150 | 122 | 110 | 3 | 0 | 22 malformed rows |
| CONCOR | p151-200 | 0 | 0 | 0 | 0 | no CSV header |
| CONCOR | p201-250 | 50 | 37 | 0 | 0 | 3 malformed rows |
| CONCOR | p251-300 | 118 | 26 | 6 | 2 | 115 malformed rows |
| CONCOR | p301-350 | 177 | 156 | 2 | 6 | 162 malformed rows |
| CONCOR | p351-400 | 568 | 502 | 6 | 0 | 1 malformed rows; output cut at max_tokens |
| CONCOR | p401-432 | 0 | 0 | 0 | 0 |  |
| CONCOR | p51-100 | 26 | 14 | 6 | 0 |  |
| COCHINSHIP | p1-50 | 0 | 0 | 0 | 0 |  |
| COCHINSHIP | p101-150 | 72 | 13 | 0 | 2 | 57 malformed rows |
| COCHINSHIP | p151-200 | 110 | 109 | 1 | 4 |  |
| COCHINSHIP | p201-250 | 0 | 0 | 0 | 0 | no CSV header |
| COCHINSHIP | p251-300 | 53 | 30 | 0 | 22 | 40 malformed rows |
| COCHINSHIP | p301-350 | 111 | 101 | 0 | 0 | 15 malformed rows |
| COCHINSHIP | p351-362 | 0 | 0 | 0 | 0 | no CSV header |
| COCHINSHIP | p51-100 | 28 | 21 | 0 | 5 | 5 malformed rows |

**Must-find recall: 14/25**; numbers not found in the text: 53/2154 (2.5%); rows 3816

- OK  CSL-ocf-standalone p151-200 p156
- OK  CSL-ocf-fy23 p151-200 p156
- MISS CSL-ocf-consolidated 
- OK  CSL-contract-liab p151-200 p196
- MISS CSL-1200-pax-vessels 
- OK  CSL-sbfa-reversal p251-300 p310
- OK  CSL-sap-edit-log p101-150 p any direct data change to SAP database tables are not being carried out
- MISS CON-kam-tughlakabad 
- MISS CON-kam-phillaur 
- MISS CON-kam-moradabad 
- OK  CON-land-lease-rou p301-350 pconsolidated
- MISS CON-seis-861 
- MISS CON-receivables 
- MISS CON-brsr-rpt-purchases 
- OK  GES-audit-trail S6_fleet_auditor_caro pin respect of other accounting software(s), audit trail was not enabled at the database level to log any direct data changes.
- MISS GES-capcom-standalone 
- MISS GES-capcom-consolidated 
- OK  GES-care-aaa S4_corp_governance p75
- MISS GES-tc-receivables 
- OK  GES-brsr-loans-rp S5_brsr p82
- OK  GES-brsr-invest-rp S5_brsr p82
- OK  GES-csr-obligation S3_boards_report_annexures_secretarial p60
- OK  GES-csr-spent S3_boards_report_annexures_secretarial p52
- OK  GES-csr-unspent S3_boards_report_annexures_secretarial p53
- OK  GES-eu-ets S5_brsr p91

## nim-ultra

| report | part | rows | numbers checked | not in text | pages outside | notes |
|---|---|---|---|---|---|---|
| GESHIP | S1_agm_notice | 29 | 7 | 0 | 0 | 7 malformed rows |
| GESHIP | S2_chairman_esg_highlights | 127 | 124 | 0 | 0 |  |
| GESHIP | S4_corp_governance | 138 | 95 | 16 | 0 |  |
| GESHIP | S5_brsr | 151 | 137 | 0 | 0 |  |
| GESHIP | S6_fleet_auditor_caro | 49 | 39 | 3 | 0 |  |
| GESHIP | S7_standalone_fs_notes | 231 | 219 | 0 | 0 | 2 malformed rows |
| GESHIP | S8a_consolidated_p135-150 | 135 | 119 | 12 | 0 |  |
| GESHIP | S8b_consolidated_p151-171 | 99 | 92 | 0 | 0 |  |
| CONCOR | p1-50 | 108 | 98 | 0 | 0 |  |

**Must-find recall: 12/25**; numbers not found in the text: 31/930 (3.3%); rows 1067

- MISS CSL-ocf-standalone 
- MISS CSL-ocf-fy23 
- MISS CSL-ocf-consolidated 
- MISS CSL-contract-liab 
- MISS CSL-1200-pax-vessels 
- MISS CSL-sbfa-reversal 
- MISS CSL-sap-edit-log 
- MISS CON-kam-tughlakabad 
- MISS CON-kam-phillaur 
- MISS CON-kam-moradabad 
- MISS CON-land-lease-rou 
- MISS CON-seis-861 
- OK  CON-receivables p1-50 p7
- MISS CON-brsr-rpt-purchases 
- OK  GES-audit-trail S6_fleet_auditor_caro p102
- OK  GES-capcom-standalone S7_standalone_fs_notes p128
- OK  GES-capcom-consolidated S8b_consolidated_p151-171 p162
- OK  GES-care-aaa S4_corp_governance p75
- OK  GES-tc-receivables S8b_consolidated_p151-171 p167
- OK  GES-brsr-loans-rp S2_chairman_esg_highlights p40
- OK  GES-brsr-invest-rp S5_brsr p83
- OK  GES-csr-obligation S5_brsr p81
- OK  GES-csr-spent S8b_consolidated_p151-171 p155
- OK  GES-csr-unspent S7_standalone_fs_notes p116
- OK  GES-eu-ets S2_chairman_esg_highlights p35
