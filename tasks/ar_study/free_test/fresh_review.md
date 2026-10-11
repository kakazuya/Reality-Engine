# Fresh rows: parser vs LongCat+guards, with page context

## 0. SUNPHARMA p277 value 67.2
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / ₹ in Million / As at March 31, 2024
- around value: Delta effect of -1% change in discount rate | 5.1 | 66.3 | 482.3 | 5.7 | 67.2 | 396.4
- parser: label `Delta effect of -1% change in discount rate` | column `As at March 31, 2023 Pension Fund (Unfunded)` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Delta effect of -1% change in discount rate - Gratuity (Funded)` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Sensitivity analysis: Delta effect of -1% change in discount rate - Gratuity (Funded)` | unit million | period 2023-03-31 | keep True

## 1. SUNPHARMA p202 value 1,720.3
- page head: Notes to the Standalone Financial Statements / for the year ended March 31, 2024 / ₹ in Million / Type of Transaction
- around value: Subsidiaries | 111,125.6 | 54,929.6 | Interest income | 2,685.0 | 1,720.3 | Subsidiaries
- parser: label `Subsidiaries` | column `₹ in Million Year ended March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Subsidiaries - Interest income` | unit million | period 2023-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Interest income - Subsidiaries` | unit million | period 2023-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark

## 2. SUNPHARMA p245 value 4,326.4
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 12 INVESTMENTS (CURRENT) / As at March 31, 2024
- around value: 1,091.5 | Axis Liquid Fund – Direct Growth | 487,063 | 1,307.1 | 1,729,947 | 4,326.4 | Bandhan Liquid Fund – Growth – Direct Plan
- parser: label `Axis Liquid Fund – Direct Growth` | column `Financial Statements As at March 31, 2023 ₹ in Million` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Mutual funds – Unquoted – At fair value through Profit or Loss: Axis Liquid Fund – Direct Growth (carrying value)` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Mutual funds – Unquoted – At fair value through Profit or Loss – Axis Liquid Fund – Direct Growth – Quantity` | unit million | period 2023-03-31 | keep True | rejected: unit 'count' rejected: no evidence in label/header

## 3. SUNPHARMA p152 value 149
- page head: Notes to the Standalone Financial Statements / for the year ended March 31, 2024 / Impairment of financial assets
- around value: also includes derivative financial instruments that | are not designated as hedging instruments in hedge | relationships as defined by Ind AS 109. Gains or losses | on liabilities held for trading are recognised in the | statement of profit and loss. | Patient First. Always. | 149 | Statutory Reports | Corporate Overview
- parser: label `Corporate Overview Statutory Reports Financial Statements Standalone Notes to the Standalone Financial Statements for th` | column `Notes to the Standalone Financial Statements for the year ended March 31, 2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `Corporate Overview Statutory Reports Financial Statements Standalone Notes to the Standalone Financial Statements for th` | unit million | period 2024-03-31 | keep True | rejected: label 'Notes to the Standalone Financial Statements for the year ended 31 March 2024' rejected: shares 43% of the row's own words; unit 'other' rejected: unknown unit; drop ignored: row is verified
- v2+guards: label `Corporate Overview Statutory Reports Financial Statements Standalone Notes to the Standalone Financial Statements for th` | unit million | period 2024-03-31 | keep True | rejected: label 'Notes to the Standalone Financial Statements for the year ended March 31, 2024 (page 149)' rejected: shares 43% of the row's own words; unit 'other' rejected: unknown unit; drop ignored: row is verified

## 4. SUNPHARMA p252 value 1,720.0
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 34 EMPLOYEE BENEFITS EXPENSE / ₹ in Million
- around value: 1,138.3 | – | others (includes interest on income tax and lease liability) | 836.5 | 581.7 | 2,384.7 | 1,720.0 | NOTE: 36 OTHER EXPENSES | ₹ in Million
- parser: label `NOTE: 36 OTHER EXPENSES` | column `₹ in Million Year ended March 31, 2023 ₹ in Million Year ended March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `NOTE: 36 OTHER EXPENSES (total)` | unit million | period 2023-03-31 | keep True
- v2+guards: label `NOTE: 36 OTHER EXPENSES - Total other expenses` | unit million | period 2023-03-31 | keep True

## 5. SUNPHARMA p8 value 557,555
- page head: (₹ Million) / Particulars / FY15 / FY16
- around value: 2,399 | 2,399 | 2,399 | 2,399 | 2,399 | Reserve and surplus | 278,009 327,418 363,997 380,742 411,691 450,245 462,229 477,713 557,555 | 634,268 | Property, plant & equipment and other
- parser: label `Reserve and surplus` | column `FY23` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Financial position: Reserve and surplus` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Financial position - Reserve and surplus` | unit million | period 2023-03-31 | keep True

## 6. SUNPHARMA p250 value 433.3
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 26 OTHER FINANCIAL LIABILITIES (CURRENT) / ₹ in Million
- around value: As at | March 31, 2023 | Statutory remittances | 9,432.7 | 4,764.2 | Advance from customers (Refer note 53) | 433.3 | 410.2 | Deferred revenue (Refer note 53)
- parser: label `Advance from customers (Refer note` | column `As at March 31, 2024 As at March 31, 2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `Advance from customers (Refer note 53) - contingent charges, milestone obligations, trade and other commitments` | unit million | period 2024-03-31 | keep True | rejected: drop ignored: row is verified
- v2+guards: label `Advance from customers (Refer note 53) - footnote: claims, recall charges, milestone obligations, trade and other commit` | unit million | period 2024-03-31 | keep True | rejected: drop ignored: row is verified

## 7. SUNPHARMA p282 value 186.1
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 69 / (a)
- around value: 706.2 | 207.5 | 32,089.1 | 30,770.8 | Individually immaterial subsidiaries with non-controlling interests | (369.7) | 186.1 | 2,303.1 | 2,430.1
- parser: label `Individually immaterial subsidiaries with non-controlling interests` | column `Year ended March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Individually immaterial subsidiaries with non-controlling interests - Profit/(loss) allocated to non-controlling interes` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Individually immaterial subsidiaries with non-controlling interests - Profit/(loss) allocated to non-controlling interes` | unit million | period 2023-03-31 | keep True

## 8. SUNPHARMA p203 value 75,867.3
- page head: Notes to the Standalone Financial Statements / for the year ended March 31, 2024 / ₹ in Million / As at
- around value: Others | 106.4 | 107.1 | Loan taken | 110,360.1 | 75,867.3 | Subsidiaries
- parser: label `Loan taken` | column `Financial Statements (Annexure ‘A’) ₹ in Million As at March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Loan taken` | unit million | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']
- v2+guards: label `Loan taken` | unit million | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 9. SUNPHARMA p276 value -
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / ₹ in Million / Year ended March 31, 2024
- around value: Notes to the Consolidated Financial Statements | for the year ended March 31, 2024 | ₹ in Million | Year ended March 31, 2024 | Year ended March 31, 2023 | COVID-19 | Education | (Unfunded)
- parser: label `Current service cost` | column `Financial Statements Year ended March 31, 2023 Pension Fund (Unfunded) March 31,` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Current service cost - Gratuity (Funded)` | unit million | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']
- v2+guards: label `Current service cost - Gratuity (Funded)` | unit million | period 2023-03-31 | keep True

## 10. LT p653 value –
- page head: Salient Features of the Financial Statements of / Subsidiaries/Associate Companies/Joint Ventures / Integrated Annual Report 2023-24 / 650
- around value: INR | INR | INR | INR | Exchange rate on the last day of | financial year | – | – | –
- parser: label `3 Liabilities` | column `31-Mar-24 INR 01-May-23` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Liabilities - Date of Acquisition 01-May-23` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `3 Liabilities - L&T Capital Company Limited` | unit crore | period 2024-03-31 | keep True

## 11. LT p480 value 60762.23
- page head: Corporate / Overview / Statutory / Reports
- around value: Subsidiaries, including: | 129527.23 | 77408.90 | L&T Hydrocarbon Saudi Company | 60762.23 | 31895.83
- parser: label `L&T Hydrocarbon Saudi Company` | column `As at 31-3-2024 Amounts for major parties` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Subsidiaries - L&T Hydrocarbon Saudi Company` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `Guarantee given on behalf of Subsidiaries - L&T Hydrocarbon Saudi Company` | unit crore | period 2024-03-31 | keep True

## 12. LT p645 value 0.50
- page head: Integrated Annual Report 2023-24 / 642 / Notes forming part of the / Consolidated Financial Statements
- around value: 0.03 | 158 | Priyanka Managment Solution (India) | Private Limited | Accounts Payables | NA | 0.50 | 0.50 | 159
- parser: label `158 Priyanka Managment Solution (India) Accounts Payables NA Private Limited` | column `March 31, 2023 [1] [1] [1] [1] [1] [1] [1] [1] [1] [1] [1] Integrated Annual Rep` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `158 Priyanka Managment Solution (India) Private Limited Accounts Payables` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `158 Priyanka Managment Solution (India) Private Limited Accounts Payables NA - Balance outstanding as at March 31, 2023` | unit crore | period 2024-03-31 | keep True | rejected: period 2023-03-31 rejected: header supports ['2023', '2024']

## 13. LT p19 value 5466
- page head: v crore / Description / IndAS [12] / IGAAP [12]
- around value: items[3]) | 8856 | 7849 | 7612 | 5966 | 5414 | 5466 | 4861 | 4560
- parser: label `Profit after tax (excluding exceptional items[3])` | column `2018-19 0.24:1 (PBDIT) is excluding exceptional items wherever applicable and ot` | unit count | period 2019-03-31 | page unit None
- v1+guards: label `Profit after tax (excluding exceptional items[3])` | unit crore | period 2019-03-31 | keep True
- v2+guards: label `Profit after tax (excluding exceptional items[3])` | unit crore | period 2019-03-31 | keep True

## 14. LT p655 value (70.77)
- page head: Salient Features of the Financial Statements of / Subsidiaries/Associate Companies/Joint Ventures / Integrated Annual Report 2023-24 / 652
- around value: 2 | Other equity/Reserves and surplus (as | applicable) | (850.06) | (1191.76) | 217.17 | (70.77) | (170.24) | 3
- parser: label `2 Other equity/Reserves and surplus (as applicable)` | column `Limited 31-Mar-24 INR 18-Oct-13 Integrated Annual Report 2023-24` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `2 Other equity/Reserves and surplus (as applicable)` | unit crore | period 2024-03-31 | keep True | rejected: label 'Proposed dividend -equity' rejected: shares 25% of the row's own words
- v2+guards: label `2 Other equity/Reserves and surplus (as applicable)` | unit crore | period 2024-03-31 | keep True | rejected: label 'Proposed dividend - equity' rejected: shares 25% of the row's own words

## 15. LT p444 value 8.14
- page head: Corporate / Overview / Statutory / Reports
- around value: – | 7.48 | – | – | – | 0.66 | 8.14 | Total | 11434.06
- parser: label `Others` | column `v crore Total v crore As at 31-3-2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Trade payables ageing - Others - Total as at 31-3-2023 (disputed)` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Trade payables ageing - Disputed: Others - Total` | unit crore | period 2023-03-31 | keep True

## 16. LT p591 value 1161.72
- page head: Integrated Annual Report 2023-24 / 588 / Notes forming part of the / Consolidated Financial Statements
- around value: 3803.20 | – | 3.08 | Energy Projects | 1266.25 | 980.06 | 1161.72 | 1203.45 | Hi-Tech manufacturing
- parser: label `Energy Projects` | column `Investment in associates and joint ventures accounted applying equity method inc` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Energy Projects - Investment in associates and joint ventures accounted for using equity method` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `Energy Projects - Investment in associates and joint ventures accounted applying equity method included in segment asset` | unit crore | period 2024-03-31 | keep True

## 17. LT p571 value 42.20
- page head: Integrated Annual Report 2023-24 / 568 / Notes forming part of the / Consolidated Financial Statements
- around value: – | – | 143.51 | 143.51 | Term loans from banks | 14797.67 | 42.20 | 14839.87 | 11339.29
- parser: label `Term loans from banks` | column `As at 31-3-2024 Secured Unsecured` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Term loans from banks - Secured - As at 31-3-2024` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `Current maturities of long term borrowings - Term loans from banks - Unsecured` | unit crore | period 2024-03-31 | keep True

## 18. LT p451 value 447.99
- page head: Integrated Annual Report 2023-24 / 448 / Notes forming part of the / Standalone Financial Statements
- around value: (2405.83) | (2125.23) | Exceptional items (net of tax) [Note 59] | 447.99 | – | Profit before tax
- parser: label `Exceptional items (net of tax) [Note 59]` | column `For the year ended 31-3-2024 Total Segment Assets As at` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Exceptional items (net of tax) [Note 59] - Segment result [Profit/(loss) before interest and tax]` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `Exceptional items (net of tax) [Note 59] - Segment result [Profit/(loss) before interest and tax]` | unit crore | period 2024-03-31 | keep True

## 19. LT p558 value 382.25
- page head: Corporate / Overview / Statutory / Reports
- around value: 638.77 | Components [include goods-in-transit ¢ 12.48 crore (previous year: ¢ 10.67 crore)] | 466.95 | 425.62 | Construction materials [include goods-in-transit ¢ 119.58 crore (previous year: ¢ 275.00 crore)] | 409.75 | 382.25 | Manufacturing work-in-progress | 347.81
- parser: label `Construction materials [include goods-in-transit ¢ 119.58 crore (previous year: ¢ 275.00 crore)]` | column `v crore As at 31-3-2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Construction materials [include goods-in-transit ¢ 119.58 crore (previous year: ¢ 275.00 crore)]` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Construction materials [include goods-in-transit ¢ 119.58 crore (previous year: ¢ 275.00 crore)]` | unit crore | period 2023-03-31 | keep True

## 20. ICICIBANK p406 value 25.6
- page head: 332 | Annual Report 2023-24 / STATEMENT CONTAINING SALIENT FEATURES OF THE FINANCIAL STATEMENTS OF SUBSIDIARIES, / ASSOCIATE COMPANIES AND JOINT VENTURES / Part “A”: Subsidiaries
- around value: Nil | Profit/(loss) after | taxation | 4,361.7 | 16,942.2 | (0.9) | 25.6 | 5,723.2 | 1.1
- parser: label `ICICI Inc.1,2 2000` | column `100.00% 5,723.2 100.00% 0.9 Nil 100.00% # Nil (0.9) 16,942.2 6,866.0 74.73% 4,36` | unit % | period None | page unit million
- v1+guards: label `ICICI Inc.1,2 2000 - percentage distribution` | unit percent | period 2000-03-31 | keep True
- v2+guards: label `ICICI Securities Inc.1,2 - % of shareholding` | unit percent | period None | keep True | rejected: period 2024-03-31 rejected: year not in header

## 21. ICICIBANK p236 value 97,153,369
- page head: 162 | Annual Report 2023-24 / ` in ‘000s / At / 31.03.2024
- around value: of deposits) | 472,649,378 | 288,094,031 | v) | Subsidiaries and/or joint ventures | 97,153,369 | 68,914,088
- parser: label `v) Subsidiaries and/or joint ventures` | column `At 31.03.2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `I. Investments in India - v) Subsidiaries and/or joint ventures` | unit million | period 2024-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `I. Investments in India [net of provisions] - v) Subsidiaries and/or joint ventures` | unit thousand | period 2024-03-31 | keep True

## 22. ICICIBANK p204 value 2.24
- page head: MANAGEMENT DISCUSSION & ANALYSIS / 130 | Annual Report 2023-24 / The following table sets forth, for the periods indicated, the details of dividend received from subsidiaries/joint ventures/ / associa
- around value: 0.80 | 0.83 | ICICI Prudential Life Insurance Company Limited | 0.40 | 0.44 | ICICI Lombard General Insurance Company Limited | 2.24 | 2.48 | ICICI Prudential Asset Management company Limited
- parser: label `ICICI Lombard General Insurance Company Limited` | column `` 2023` | unit billion | period 2024-03-31* | page unit million
- v1+guards: label `ICICI Lombard General Insurance Company Limited - ` 2023` | unit billion | period 2024-03-31 | keep True
- v2+guards: label `Dividend received from ICICI Lombard General Insurance Company Limited` | unit billion | period 2024-03-31 | keep True

## 23. ICICIBANK p309 value 0.4
- page head: Annual Report 2023-24 | 235 / Integrated Report / Statutory Reports / Financial Statements
- around value: 191.3 | Key management personnel | 68.8 | 85.7 | Relatives of key management personnel | 0.8 | 0.4 | Receivables1 | 3,804.3
- parser: label `Relatives of key management personnel` | column `in million ` At March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Advances by the Bank - Relatives of key management personnel` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Advances by the Bank - Relatives of key management personnel` | unit million | period 2023-03-31 | keep True

## 24. ICICIBANK p385 value 186,455
- page head: Annual Report 2023-24 | 311 / Integrated Report / Statutory Reports / Financial Statements
- around value: 544.97 | 263,980 | 514.77 | Less : Exercised during the year | 489,029 | 349.77 | 186,455 | 305.89 | Outstanding at the end of the year
- parser: label `Less : Exercised during the year` | column `` except number of options Stock options outstanding Year ended March 31, 2023 N` | unit count | period 2023-03-31 | page unit million
- v1+guards: label `Less: Exercised during the year - Number of options` | unit count | period 2023-03-31 | keep True
- v2+guards: label `Less: Exercised during the year - Number of options, Year ended March 31, 2023` | unit count | period 2023-03-31 | keep True

## 25. ICICIBANK p235 value 34,150,501
- page head: Annual Report 2023-24 | 161 / Integrated Report / Statutory Reports / Financial Statements
- around value: 134,783,012 | II. | Inter-office adjustments (net) | 420,905 | 3,228,016 | III.	 Interest accrued | 34,150,501 | 30,423,631 | IV.	 Sundry creditors
- parser: label `III. Interest accrued` | column `At 31.03.2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `III. Interest accrued` | unit million | period 2024-03-31 | keep True | rejected: unit 'thousand' rejected: scale not stated in label/header
- v2+guards: label `III. Interest accrued` | unit million | period 2024-03-31 | keep True | rejected: unit 'thousand' rejected: scale not stated in label/header

## 26. ICICIBANK p207 value 2,355.89
- page head: MANAGEMENT DISCUSSION & ANALYSIS / Annual Report 2023-24 | 133 / Integrated Report / Statutory Reports
- around value: Equity share capital | 21.58 | 28.10 | 30.2 | Reserves | 1,985.58 | 2,355.89 | 18.6 | Deposits
- parser: label `Reserves` | column `in billion, except percentages ` At March 31, 2024` | unit billion | period 2024-03-31 | page unit million
- v1+guards: label `Reserves` | unit billion | period 2024-03-31 | keep True
- v2+guards: label `Reserves` | unit billion | period 2024-03-31 | keep True

## 27. ICICIBANK p300 value 104,040.7
- page head: 226 | Annual Report 2023-24 / FINANCIAL STATEMENTS OF ICICI BANK LIMITED / SCHEDULES / forming part of the Accounts (Contd.)
- around value: March 31, 2024 | At | March 31, 2023 | Deferred tax assets | Provision for bad and doubtful debts | 93,946.8 | 104,040.7 | Provision for operating expenses | 4,026.9
- parser: label `Provision for bad and doubtful debts` | column `in million ` At March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Provision for bad and doubtful debts` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Deferred tax assets: Provision for bad and doubtful debts` | unit million | period 2023-03-31 | keep True

## 28. ICICIBANK p349 value 38,985,508
- page head: Annual Report 2023-24 | 275 / Integrated Report / Statutory Reports / Financial Statements
- around value: 136,037,076 | II. | Inter-office adjustments (net) | 420,905 | 3,228,016 | III.	 Interest accrued | 38,985,508 | 33,390,137 | IV.	 Sundry creditors
- parser: label `III. Interest accrued` | column `At 31.03.2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `III. Interest accrued under Other liabilities and provisions` | unit million | period 2024-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `III. Interest accrued` | unit million | period 2024-03-31 | keep True | rejected: unit 'thousand' rejected: scale not stated in label/header

## 29. ICICIBANK p385 value 6,060,085
- page head: Annual Report 2023-24 | 311 / Integrated Report / Statutory Reports / Financial Statements
- around value: Less : Exercised during the year | 489,029 | 349.77 | 186,455 | 305.89 | Outstanding at the end of the year | 6,060,085 | 462.58 | 4,146,544
- parser: label `Outstanding at the end of the year` | column `Year ended March 31, 2024 Number of options` | unit count | period 2024-03-31 | page unit million
- v1+guards: label `Outstanding at the end of the year - Number of options` | unit count | period 2024-03-31 | keep True
- v2+guards: label `Outstanding at the end of the year - Number of options, Year ended March 31, 2024` | unit count | period 2024-03-31 | keep True

## 30. TITAGARH p88 value -
- page head: 172 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / 34 Exceptional Item / For the year ended / March 31, 2024
- around value: 172 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 | 34 Exceptional Item | For the year ended
- parser: label `Fair value of Plan Assets` | column `Gratuity (Unfunded) -For the Year Ended March 31, 2024` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Fair value of Plan Assets - Gratuity (Unfunded)` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Fair value of Plan Assets - Gratuity (Unfunded)` | unit lakh | period 2024-03-31 | keep True

## 31. TITAGARH p144 value 164.54
- page head: 284 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / (Rs. in Lacs) / Level 1 / Level 2
- around value: (Rs. In Lacs) | Particulars | Investment in unquoted equity shares | Closing Balance as on March 31, 2022 | 3,015.06 | Re-measurement recognised in Consolidated Statement of Proﬁ t and Loss | 164.54 | Closing Balance as on March 31, 2023 | 3,179.60
- parser: label `Re-measurement recognised in Consolidated Statement of Proﬁ t and Loss` | column `(Rs. In Lacs) shares` | unit count | period None | page unit lakh
- v1+guards: label `Re-measurement recognised in Consolidated Statement of Profit and Loss` | unit shares | period None | keep True
- v2+guards: label `Reconciliation of fair value measurement of financial instruments classified as FVTPL assets: Investment in unquoted equ` | unit lakh | period None | keep True | rejected: period 2023-03-31 rejected: year not in header

## 32. TITAGARH p97 value 625.28
- page head: 190 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Quantitative disclosures fair value / measurement hierarchy: / Date of Valuation
- around value: Financial Assets | Trade Receivables | 2,612.22 221.80 | 625.28 4,771.82 | - 2,249.51 221.80 | 616.60
- parser: label `Net exposure to Foreign Currency Risk (Assets)` | column `ﬁ nancial liabilities is to ﬁ nance the operations. The Company’s ﬁ nancial asse` | unit usd | period 2024-03-31 | page unit lakh
- v1+guards: label `Trade Receivables - Net exposure to Foreign Currency Risk (Assets)` | unit usd | period 2024-03-31 | keep True | rejected: unit 'lakh' rejected: scale not stated in label/header
- v2+guards: label `Net exposure to Foreign Currency Risk (Assets)` | unit usd | period 2024-03-31 | keep True | rejected: label 'Trade Receivables - USD - Financial Assets' rejected: shares 0% of the row's own words; unit 'lakh' rejected: scale not stated in label/header

## 33. TITAGARH p51 value 1744
- page head: 98 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / 2. Details of retirement beneﬁ ts, for Current FY and Previous FY / Beneﬁ ts / FY 2023-24
- around value: 35 | 24.8 | 69 | 48.94 | Workers | Male | 1744 | 921 | 52
- parser: label `Male` | column `(A)` | unit count | period None | page unit lakh
- v1+guards: label `Male employees (A)` | unit count | period None | keep True | rejected: period 2024-03-31 rejected: year not in header
- v2+guards: label `Employees - Male - Total (A), FY 2023-24` | unit count | period None | keep True | rejected: period 2024-03-31 rejected: year not in header

## 34. TITAGARH p24 value 301.84
- page head: 44 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / A.  CONSERVATION OF ENERGY / i) Steps taken or impact on conservation of energy:
- around value: 2022-23 | Capital | Nil | Nil | Recurring | 144.36 | 301.84 | Total | 144.36
- parser: label `Recurring` | column `(Rs. in Lakhs) 2022-23 Nil` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Recurring R & D Expenditure` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Expenditure on R & D: Recurring` | unit lakh | period 2023-03-31 | keep True

## 35. TITAGARH p44 value 723
- page head: 84 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / 17. Products/Services sold by the entity (accounting for 90% of the entity’s Turnover): / Sl. No. Product/Service / NIC Code
- around value: % (B / A) | No. (C) | % (C / A) | Employees | 1 | Permanent (D) | 723 | 680 | 94
- parser: label `1 Permanent (D)` | column `differently abled): Total (A) workers: Differently abled Employees` | unit count | period None | page unit lakh
- v1+guards: label `Permanent (D) employees: Total (A) differently abled` | unit count | period None | keep True | rejected: period 2024-03-31 rejected: year not in header
- v2+guards: label `Differently abled Employees: Permanent (D) - Total (A)` | unit count | period None | keep True | rejected: period 2024-03-31 rejected: year not in header

## 36. TITAGARH p138 value 2,77,655.71
- page head: 272 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Notes to Consolidated Financial Statements as at and for the year ended March 31, 2024 / Titagarh Rail Systems Limited (Formerly Titagarh 
- around value: Rs.in Lacs | For the year ended | March 31, 2023 | Rs.in Lacs | India | 3,85,084.89 | 2,77,655.71 | Rest of the World | 245.15
- parser: label `India` | column `For the year ended March 31, 2023 Rs.in Lacs` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `India - location of the customers` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Revenue from external customers located in India` | unit lakh | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 37. TITAGARH p119 value 2.41
- page head: 234 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Notes to Consolidated Financial Statements as at and for the year ended March 31, 2024 / Titagarh Rail Systems Limited (Formerly Titagarh 
- around value: Trade Payables | 773.59 | 52.32 | 11.04 | 46,811.76 | 25,476.48 | 2.41 | 2.41 | Other Financial
- parser: label `Trade Payables` | column `Titagarh Mermec Private Limited As at March 31, 2024` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Trade Payables - Titagarh Firema S.p.A` | unit lakh | period 2024-03-31 | keep True | rejected: period 2022-03-31 rejected: header supports ['2024']
- v2+guards: label `Trade Payables - Titagarh Firema S.p.A` | unit lakh | period 2024-03-31 | keep True

## 38. TITAGARH p79 value 97.88
- page head: 154 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Outstanding as at March 31, 2023 / Less than / 6 months
- around value: 31, 2024 | Rs. In Lacs | As at  March | 31, 2023 | Rs. In Lacs | Retention money held by customers | 97.88 | 87.38 | 535.98
- parser: label `Retention money held by customers` | column `Non-Current As at March 31, 2024 Rs. In Lacs Non-Current As at March 31, 2024 Rs` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Retention money held by customers - Non-Current` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Contract Assets - Retention money held by customers - Non-Current` | unit lakh | period 2024-03-31 | keep True

## 39. TITAGARH p54 value 474
- page head: 104 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Category / FY 2023-24 / FY 2022-23
- around value: Employees | Permanent | 723 | 680 | 94 | 593 | 474 | 80 | Other than Permanent
- parser: label `Permanent` | column `FY 2022-23 No. of Employees/ Workers covered (B)` | unit count | period 2023-03-31 | page unit lakh
- v1+guards: label `Permanent - FY 2022-23 No. of Employees/Workers covered (B)` | unit count | period 2023-03-31 | keep True
- v2+guards: label `Permanent Employees - FY 2022-23 No. of Employees/Workers covered (B)` | unit count | period 2023-03-31 | keep True

## 40. KPIGREEN p173 value 316.62
- page head: Notes to Standalone Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: KPIG Energia Pvt. Ltd. | 2,070.13 | - | Deemed Investments | KPIG Energia Private Limited | - | 316.62 | Sun Drops Energia Private Limited | 3,596.63
- parser: label `KPIG Energia Private Limited` | column `Year ended March 31, 2023` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `KPIG Energia Private Limited - Year ended March 31, 2023` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `KPIG Energia Private Limited - Deemed Investments` | unit lakh | period 2023-03-31 | keep True

## 41. KPIGREEN p175 value -
- page head: Notes to Standalone Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: Notes to Standalone Financial Statements | For the year ended March 31, 2024 | KPI Green Energy Limited | Annual Report 2023-24 | 196 | Particulars
- parser: label `KPARK Sunbeat Private Limited` | column `As at March 31, 2023` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `KPARK Sunbeat Private Limited - Investment in equity instruments` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `KPARK Sunbeat Private Limited - Purchase` | unit lakh | period 2023-03-31 | keep True

## 42. KPIGREEN p101 value -
- page head: KPI Green Energy Limited / Annual Report 2023-24 / 122 / 19. 	Markets served by the Company:
- around value: KPI Green Energy Limited | Annual Report 2023-24 | 122 | 19. 	Markets served by the Company:
- parser: label `Permanent Workers` | column `Total` | unit % | period None | page unit lakh
- v1+guards: label `Permanent Workers - Total workers` | unit percent | period None | keep True | rejected: period 2022-03-31 rejected: year not in header
- v2+guards: label `Permanent Workers Turnover Rate Total 2021-22` | unit percent | period None | keep True | rejected: period 2022-03-31 rejected: year not in header

## 43. KPIGREEN p217 value 4,079.83
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: Tax on Deferred Assets @ 25.17% | 300.87 | 550.14 | Deferred Tax Liabilities/Assets Transferred to Balance Sheet | Opening Balance of Deferred Tax (Liabilities) | 6,268.36 | 4,079.83 | Deferred Tax (Liabilities) Charged to P & L A/c | 1,974.94
- parser: label `Opening Balance of Deferred Tax (Liabilities)` | column `31-03-2023 (All the figures are in lakhs) 31-03-2023` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Deferred Tax (Liabilities) - Opening Balance` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Opening Balance of Deferred Tax (Liabilities)` | unit lakh | period 2023-03-31 | keep True

## 44. KPIGREEN p147 value 0.01
- page head: Notes to Standalone Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: KPARK SUNBEAT PRIVATE LIMITED | 1,391.65 | - | Investment in other than subsidiaries | 100 (100) Unquoted Equity Shares of `10 Each Fully Paid Up in | Evergreen Mahuva Windfarms Pvt. Ltd. (refer Note (ii) below) | 0.01 | 0.01 | 21,391.83
- parser: label `100 (100) Unquoted Equity Shares of `10 Each Fully Paid Up in Evergreen Mahuva Windfarms Pvt. Ltd. (refer Note (ii) belo` | column `(All the figures are in lakhs) 31-03-2023` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `100 (100) Unquoted Equity Shares of ₹10 Each Fully Paid Up in Evergreen Mahuva Windfarms Private Limited` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Investment in other than subsidiaries - 100 (100) Unquoted Equity Shares of `10 Each Fully Paid Up in Evergreen Mahuva W` | unit lakh | period 2023-03-31 | keep True

## 45. KPIGREEN p207 value 75.10
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: - | Bandhan bank OD | 80.79 | - | Axis bank - Escrow Account | 114.18 | 75.10 | State Bank of India - Dividend Account | 7.07
- parser: label `Axis bank -Escrow Account` | column `(All the figures are in lakhs) 31-03-2023 (All the figures are in lakhs) 31-03-2` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Axis bank -Escrow Account` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Balance with Banks - Other Account - Axis bank - Escrow Account` | unit lakh | period 2023-03-31 | keep True

## 46. KPIGREEN p163 value 11.60
- page head: Notes to Standalone Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: 734.77 | Contribution to Gratuity | 13.42 | (9.30) | Contribution to Provident Fund,ESIC and Labour fund | 31.01 | 11.60 | Staff Welfare Expenses | 55.73
- parser: label `Contribution to Provident Fund,ESIC and Labour fund` | column `(All the figures are in lakhs) 31-03-2023 (All the figures are in lakhs) 31-03-2` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Contribution to Provident Fund, ESIC and Labour fund` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Employee benefit expense - Contribution to Provident Fund, ESIC and Labour fund` | unit lakh | period 2023-03-31 | keep True

## 47. KPIGREEN p235 value -
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: Notes to Consolidated Financial Statements | For the year ended March 31, 2024 | KPI Green Energy Limited | Annual Report 2023-24 | 256 | Particulars
- parser: label `KP Human Development Foundation Managerial Remuneration` | column `Year ended March 31, 2024` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `KP Human Development Foundation - Managerial Remuneration` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Managerial Remuneration - KP Human Development Foundation` | unit lakh | period 2024-03-31 | keep True

## 48. KPIGREEN p211 value 34,779.96
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: (9.50) | 0.95 | Dividend Payment (Refer Note (iii) Below) | (180.67) | (545.72) | Retained Earnings Closing | 34,779.96 | 18,845.49 | 77,540.12
- parser: label `Retained Earnings Closing` | column `31-03-2024` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Retained Earnings Closing` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Retained Earnings Closing` | unit lakh | period 2024-03-31 | keep True

## 49. KPIGREEN p209 value 54.46
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24
- around value: Farukbhai Gulambhai Patel | 3,19,62,471 | 53.02 | 1,97,82,234 | 54.75 | 98,38,767 | 54.46 | Details of Shares for preceding Five years | Particulars
- parser: label `Farukbhai Gulambhai Patel Details of Shares for preceding Five years` | column `(All the figures are in lakhs) 31-03-2023 31-03-2022 % Held 31-03-2020 31-03-202` | unit % | period 2023-03-31 | page unit lakh
- v1+guards: label `Farukbhai Gulambhai Patel Details of Shares for preceding Five years` | unit percent | period 2023-03-31 | keep True | rejected: label 'Farukbhai Gulambhai Patel - % Held' rejected: shares 43% of the row's own words
- v2+guards: label `Farukbhai Gulambhai Patel Details of Shares for preceding Five years` | unit percent | period 2023-03-31 | keep True | rejected: label 'Farukbhai Gulambhai Patel - Holding more than 5% - % Held' rejected: shares 43% of the row's own words

## 50. NAVINFLUOR p100 value 5.38
- page head: Financial Section / Corporate Overview / 194 / 195
- around value: 28.00 | 33.60 | b. | Contract liabilities | 27C | 3.39 | 5.38 | c. | Provisions
- parser: label `b. Contract liabilities` | column `Amount ` in crores unless otherwise stated As at March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Current liabilities b. Contract liabilities` | unit crore | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']
- v2+guards: label `Current liabilities - Contract liabilities` | unit crore | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 51. NAVINFLUOR p55 value 19.02
- page head: Corporate Overview / Statutory Reports / Financial Section / 104
- around value: 0.37 | 0.37 | Negative | Negative | Interest Coverage Ratio# | 4.80 | 19.02 | 49.44 | 205.13
- parser: label `Interest Coverage Ratio#` | column `Consolidated FY 2022-23 0.37` | unit % | period 2023-03-31 | page unit crore
- v1+guards: label `Interest Coverage Ratio#` | unit ratio | period 2023-03-31 | keep True
- v2+guards: label `Interest Coverage Ratio (consolidated)` | unit percent | period 2023-03-31 | keep True | rejected: unit 'times' rejected: no evidence in label/header

## 52. NAVINFLUOR p150 value -
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: Amount ` in crores unless otherwise stated | Amount ` in crores unless otherwise stated | Financial Section | Corporate Overview | 294 | 295 | Annual Report 2023-24 | Statutory Reports | (ii)
- parser: label `Working Capital Loan from banks (refer note b)` | column `Amount ` in crores unless otherwise stated Non- Current As at March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Working Capital Loan from banks (refer note b) - Non-Current As at March 31, 2023` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Borrowings - Working Capital Loan from banks (refer note b) - Non-Current` | unit crore | period 2023-03-31 | keep True

## 53. NAVINFLUOR p100 value 1,250.90
- page head: Financial Section / Corporate Overview / 194 / 195
- around value: Other Expenses | 37 | 308.56 | 288.01 | Total Expenses | 1,247.86 | 1,250.90 | Profit before exceptional item and tax | 240.34
- parser: label `Total Expenses` | column `Amount ` in crores unless otherwise stated For the year ended March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Total Expenses` | unit crore | period 2023-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Total Expenses` | unit crore | period 2023-03-31 | keep True | rejected: label 'Total current assets' rejected: shares 50% of the row's own words; period 2024-03-31 rejected: header supports ['2023']

## 54. NAVINFLUOR p146 value 28,410
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: 865,252 | 23.20 | 32,125 | 1.06 | - HDFC Overnight Fund - Regular plan- Growth  Option | 28,410 | 10.01 | -
- parser: label `-HDFC Overnight Fund -Regular plan- Growth Option` | column `As at March 31, 2024 Quantity` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Investments in mutual funds - HDFC Overnight Fund -Regular plan- Growth Option - Quantity` | unit crore | period 2024-03-31 | keep True | rejected: unit 'count' rejected: no evidence in label/header
- v2+guards: label `Investments in mutual funds - HDFC Overnight Fund - Regular plan - Growth Option - Quantity` | unit crore | period 2024-03-31 | keep True | rejected: unit 'count' rejected: no evidence in label/header

## 55. NAVINFLUOR p73 value 0
- page head: Corporate Overview / Statutory Reports / Financial Section / Annual Report 2023-24
- around value: Corporate Overview | Statutory Reports | Financial Section | Annual Report 2023-24 | 140 | 141
- parser: label `Female` | column `measures for the well-being of workers:` | unit count | period None | page unit crore
- v1+guards: label `Female - No. (A) Total workers - measures for the well-being of workers` | unit count | period None | keep True | rejected: period 2024-03-31 rejected: year not in header
- v2+guards: label `Female` | unit count | period None | keep True | rejected: label 'Permanent Workers - Male - Total (A) - measures for the well-being of workers' rejected: shares 0% of the row's own words; period 2024-03-31 rejected: year not in header

## 56. NAVINFLUOR p126 value 0.28
- page head: Notes Forming Part of the Standalone Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Standalone Financial Statements / as at and for the year ended March
- around value: 6.67 | Mr. Radhesh R. Welling | 0.47 | 4.45 | Mr. Mohan M. Nambiar | 0.22 | 0.28 | Mr. Pradip N. Kapadia | 0.22
- parser: label `Mr. Mohan M. Nambiar` | column `in crores unless otherwise stated As at March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Mr. Mohan M. Nambiar - Amount due to Directors` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Mr. Mohan M. Nambiar` | unit crore | period 2023-03-31 | keep True | rejected: label 'Amount due to Directors - Mr. Vishad P. Mafatlal' rejected: shares 0% of the row's own words

## 57. NAVINFLUOR p154 value 0.27
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: 5.89 | Depreciation on investment properties (refer note 6) | 1.14 | 1.13 | Amortisation of intangible assets (refer note 7) | 0.53 | 0.27 | Total | 96.16
- parser: label `b) Other audit services` | column `For the year ended March 31, 2023 For the year ended March 31, 2023 Yet to be pa` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `b) Other audit services` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Payment to auditors - As auditors - b) Other audit services` | unit crore | period 2023-03-31 | keep True

## 58. NAVINFLUOR p135 value 486.03
- page head: Financial Section / Corporate Overview / 264 / 265
- around value: 468.12 | b. | Financial assets | i. | Investments | 15 | 486.03 | 32.17 | ii.
- parser: label `b. Financial assets i. Investments` | column `Amount ` in crores unless otherwise stated As at March 31, 2024` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Current assets b. Financial assets i. Investments` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `Current assets b. Financial assets i. Investments` | unit crore | period 2024-03-31 | keep True

## 59. NAVINFLUOR p163 value 10,710
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: 554.40 | 1,825 | 2,050 | March 19, 2018 | March 18, 2028 | 780.00 | 10,710 | 11,350 | May 09, 2018
- parser: label `March 19, 2018 March 18, 2028` | column `March 31, 2024` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Non-convertible debentures due March 19, 2018 March 18, 2028` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `Share options outstanding at end of year, grant March 19, 2018 expiry March 18, 2028, March 31, 2024` | unit crore | period 2024-03-31 | keep True | rejected: unit 'count' rejected: no evidence in label/header
