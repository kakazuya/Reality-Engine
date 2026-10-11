# Step 4: CPU pipeline on 13 FY24 reports (no LLM)

| Report | s | XBRL figures found in AR (sa/cons) | tables: cpu_ok / unchecked / to LLM | cells stored by CPU | LLM slice: new prose | + LLM tables | diff baseline |
|---|---|---|---|---|---|---|---|
| COCHINSHIP | 16 | 85/109 · 70/110 | 28% / 8% / 64% of 839 | 44% | 41.3% (~117 pp) | ~34 pp | FY23 AR |
| CONCOR | 13 | 60/114 · 79/120 | 21% / 4% / 75% of 870 | 31% | 13.5% (~39 pp) | ~44 pp | FY23 AR |
| GESHIP | 9 | 78/98 · 91/112 | 21% / 5% / 73% of 589 | 38% | 29.7% (~64 pp) | ~32 pp | FY23 AR |
| AXISBANK | 13 | 38/84 · 50/85 | 21% / 7% / 72% of 780 | 44% | 18.1% (~73 pp) | ~38 pp | FY23 AR |
| BAJFINANCE | 14 | 95/113 · 93/114 | 21% / 8% / 71% of 825 | 28% | 18.3% (~64 pp) | ~76 pp | FY23 AR |
| INFY | 14 | 76/96 · 85/105 | 12% / 6% / 82% of 936 | 25% | 36.5% (~110 pp) | ~73 pp | FY23 AR |
| DABUR | 17 | 100/119 · 110/130 | 18% / 7% / 75% of 949 | 52% | 27.2% (~107 pp) | ~40 pp | FY23 AR |
| CIPLA | 16 | 95/117 · 113/130 | 18% / 7% / 75% of 971 | 34% | 40.1% (~164 pp) | ~62 pp | FY23 AR |
| CUMMINSIND | 11 | 75/110 · 75/118 | 39% / 12% / 48% of 431 | 44% | 10.8% (~24 pp) | ~20 pp | FY23 AR |
| ATUL | 13 | 105/116 · 117/130 | 35% / 6% / 59% of 483 | 40% | 24.6% (~46 pp) | ~35 pp | FY23 AR |
| EXIDEIND | 10 | 76/100 · 84/114 | 19% / 10% / 70% of 611 | 40% | 34.8% (~102 pp) | ~27 pp | FY23 AR |
| SOBHA | 14 | 92/110 · 96/114 | 23% / 5% / 72% of 793 | 41% | 32.3% (~96 pp) | ~32 pp | FY23 AR |
| JKCEMENT | 17 | 87/108 · 88/115 | 10% / 10% / 80% of 734 | 33% | 38.9% (~124 pp) | ~53 pp | FY23 AR |

**All 13:** cells in cpu_ok tables 33%, stored unchecked 4%, to LLM 63%. LLM slice: new prose 28.5% of characters (flagged-only tier 21.3%) (~87 page-equivalents per report) + failed tables ~44 pp per report.


## Must-find signals (study reports)

| id | report | item | where it ends up |
|---|---|---|---|
| C1 | COCHINSHIP | Operating cash flow negative (standalone, lakh) | cpu_ok table |
| C2 | COCHINSHIP | Operating cash flow negative (consolidated, lakh) | cpu_ok table |
| C3 | COCHINSHIP | Contract liability for other works (lakh) | cpu_ok table |
| C4 | COCHINSHIP | Two 1,200-pax vessels past delivery date, customer asks reallocation | LLM slice |
| C5 | COCHINSHIP | C&AG comment: SBFA not reported by auditor | LLM slice |
| C6 | COCHINSHIP | Audit trail / edit log enabled only from Mar-2024 | LLM slice |
| K1 | CONCOR | KAM: Tughlakabad land licence fee demand | LLM slice |
| K2 | CONCOR | EoM: railway land leases not recognised as ROU/lease liability | MISSED |
| K3 | CONCOR | SEIS claim disallowed, fully provided | cpu_ok table |
| K4 | CONCOR | Trade receivables FY24 (213.10 FY23) | cpu_ok table |
| K5 | CONCOR | BRSR related-party purchases share | table to LLM/unchecked |
| G1 | GESHIP | Auditor modification: audit trail not verifiable | LLM slice |
| G2 | GESHIP | Capital commitments standalone | table to LLM/unchecked |
| G3 | GESHIP | Credit rating upgraded AA+ to AAA | LLM slice |
| G4 | GESHIP | Time-charter receivables < 1 year | table to LLM/unchecked |
| G5 | GESHIP | BRSR loans to related parties share | MISSED |
| G6 | GESHIP | EU ETS: broker for EUAs, registry account expected | LLM slice |

## Random cpu_ok rows (check against the page)

| report | page | label | column | period | unit | value | on page? |
|---|---|---|---|---|---|---|---|
| COCHINSHIP | 319 | Balance at the end of the year Note 49: CONTINGENT LIABILITI | (H in lakhs) For the year ended March 31 | 2023-03-31 | lakh | (3578.40) | yes |
| COCHINSHIP | 192 | Equity Shares outstanding at the end of the year | As at March 31,2023 Number | 2023-03-31 | lakh | 131540390 | yes |
| COCHINSHIP | 224 | Interest accrued but not due on NCD | Hooghly Cochin Shipyard Ltd As at March  | 2023-03-31 | lakh | 263.27 | yes |
| CONCOR | 365 | rental income Fair valuation of | For the year ended March 31, 2023 Recogn | 2023-03-31 | crore | (0.03) | yes |
| CONCOR | 353 | Profit / (Loss) for the year | Company Limited March 2024 | 2024-03-31 | crore | 5.51 | yes |
| CONCOR | 375 | Segment Assets Unallocated | 2024 | 2024-03-31 | crore | 3,828.25 | yes |
| GESHIP | 160 | Fair value of plan assets at the end of the year | Provident Fund Funded 31/03/2024 | 2024-03-31 | crore | 284.41 | yes |
| GESHIP | 152 | Co. Ltd. [Refer Notes (ii) and (iii) below] | (K in crores) As at 31/03/2023 | 2023-03-31 | crore | 356.60 | yes |
| GESHIP | 141 | Loss on principal settlement of derivative contracts related | Current Year | 2024-03-31 | crore | (59.69) | yes |
| AXISBANK | 213 | Other interest income | 2022-23 | 2023-03-31 | crore | 2,431 | yes |
| AXISBANK | 409 | Net cash generated from financing activities 406 Integrated  | crores) (` in Year ended 31-03-2023 | 2024-03-31 | crore | 6,640.54 | yes |
| AXISBANK | 348 | Provision held | 2023 | 2023-03-31 | crore | 0.02 | yes |
| BAJFINANCE | 443 | Other non-financial assets | As at 31 March 2024 months | 2024-03-31 | crore | 38.95 | yes |
| BAJFINANCE | 53 | Profit after tax (PAT) | (C in crore) Change | None | % | 26% | yes |
| BAJFINANCE | 248 | Finance costs | For the year ended 31 March 2024 | 2024-03-31 | crore | 13,843.44 | yes |
| INFY | 207 | Communication | Segment As at March 31, 2024 Energy, Uti | 2024-03-31 | crore | 28 | yes |
| INFY | 292 | other comprehensive income |  | 2023-03-31* | crore | 7,632 | yes |
| INFY | 323 | Interest expense | Gratuity As at March 31, 2024 | 2024-03-31 | crore | 121 | yes |
| DABUR | 411 | Total non-current liabilities | (All amounts in ` crores, unless otherwi | 2024-03-31 | crore | 889.17 | yes |
| DABUR | 457 | Re-measurement loss on the defined benefit plans through OCI | March 2023 | 2023-03-31 | crore | 3.24 | yes |
| DABUR | 349 | ` Units of face value of 100 each BY 8.05% Tamil Nadu State  | No. of units 31 March 2023 | 2023-03-31 | count | 20,00,000 | yes |
| CIPLA | 387 | Samina Hamied | As at 31st March, 2024 % to total shares | 2024-03-31 | % | 2.22% | yes |
| CIPLA | 289 | M K Hamied | As at 31st March, 2022 % of holdings | 2022-03-31 | % | 3.45% | yes |
| CIPLA | 90 | Associates / Non-Management | Female % Female Nos. | None | % | 29.66 | yes |
| CUMMINSIND | 314 | Other timing differences | March 31, 2023 ` Crore | 2023-03-31 | crore | 4.98 | yes |
| CUMMINSIND | 187 | Intangible assets under development | Cummins India Limited | 2024-03-31* | crore | (2.16) | yes |
| CUMMINSIND | 240 | i) Current service cost March 31, 2024 | ൠCrore PF Annual Report 2023-2024 l | 2024-03-31 | crore | 16.79 | yes |
| ATUL | 184 | D Inventories ` cr Balance Sheet (refer Note | year As at March 31, 2024 | 2024-03-31 | thousand | 563.20 | yes |
| ATUL | 156 | Osia Infrastructure Ltd | 2023-24 | 2024-03-31 | crore | 0.10 | yes |
| ATUL | 219 | Indian Oil Corporation Ltd | (` cr) March 31, 2023 Amount (` cr) As a | 2023-03-31 | crore | 0.28 | yes |
| EXIDEIND | 145 | Permanent | FY 2022-23 No. of employees / workers co | 2023-03-31 | count | 1,532 | yes |
| EXIDEIND | 309 | Profit on sale of property, | (H in Crores) 2022-23 (H in Crores) 2022 | 2023-03-31 | crore | 6.48 | yes |
| EXIDEIND | 310 | Clearing and forwarding expenses | Particulars 2023-24 assembly expenses Re | 2024-03-31 | crore | 49.82 | yes |
| SOBHA | 184 | (iii) Loans | As at 31 March 2024 | 2024-03-31 | million | 230.02 | yes |
| SOBHA | 209 | (v) Sobha Assets Private Limited (^) | 31 March 2024 stated otherwise) (#) (ref | 2024-03-31 | million | 10,000 | yes |
| SOBHA | 349 | Unbilled Revenue | probability of default | None | % | 0.00% | yes |
| JKCEMENT | 143 | b. Term loans from banks in local currency | Crores, unless otherwise stated) As at M | 2024-03-31 | crore | 4,246.83 | yes |
| JKCEMENT | 126 | (v) Other financial assets | (All amounts are in Rupees Crores, unles | 2023-03-31 | crore | 792.16 | yes |
| JKCEMENT | 65 | Specific water intensity m3/tonne of cement | FY 2020-21 _ _ | 2021-03-31 | crore | 0.16 | yes |