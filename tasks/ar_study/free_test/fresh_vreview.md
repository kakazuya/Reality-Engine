# Fresh rows: parser vs LongCat+guards, with page context

## 0. SUNPHARMA p276 value 6.2
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / ₹ in Million / Year ended March 31, 2024 / Year ended March 31, 2023 / COVID-19 / Education / (Unfunded) / Pension 
- around value: 639.0 | - | - | 571.6 | Interest cost | 6.2 | 76.0 | 465.0
- parser: label `Interest cost` | column `Statements Financial Statements Year ended March 31, 2024 COVID-19 Education (Un` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `Interest cost - Pension Fund` | unit million | period 2024-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Interest cost - COVID-19 Education (Unfunded)` | unit million | period 2024-03-31 | keep True

## 1. SUNPHARMA p215 value 854,628.8
- page head: Consolidated Balance Sheet / as at March 31, 2024 / ₹ in Million / Particulars / Notes / As at / March 31, 2024 / As at / March 31, 2023 / ASSETS / (1)	 Non-current assets / (a)	 Property, plant and 
- around value: 398,619.4 | Assets classified as held for sale | 3C | 418.7 | 214.0 | TOTAL ASSETS | 854,628.8 | 807,435.9 | Sun Pharmaceutical Industries Limited   |   Annual Report 2023-24
- parser: label `TOTAL ASSETS Sun Pharmaceutical Industries Limited | Annual Report 2023-24` | column `Statutory Reports Consolidated As at March 31, 2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `TOTAL ASSETS` | unit million | period 2024-03-31 | keep True
- v2+guards: label `TOTAL ASSETS` | unit million | period 2024-03-31 | keep True

## 2. SUNPHARMA p244 value 9,202.1
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 7 LOANS (NON-CURRENT) / ₹ in Million / As at / March 31, 2024 / As at / March 31, 2023 / Loans to employees /
- around value: Finished goods | 37,345.0 | 34,510.9 | Stock-in-trade | 8,003.0 | 9,202.1 | 
- parser: label `Stock-in-trade` | column `₹ in Million As at March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Stock-in-trade - Goods-in-transit` | unit million | period 2023-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Stock-in-trade - Goods-in-transit` | unit million | period 2023-03-31 | keep True

## 3. SUNPHARMA p163 value 10,000
- page head: Notes to the Standalone Financial Statements / for the year ended March 31, 2024 / NOTE: 4 (b) INTANGIBLE ASSETS UNDER DEVELOPMENT / ₹ in Million / Year ended / March 31, 2024 / Year ended / March 31,
- around value: 1.5 | Faststone Mercantile Company Private Limited |  | Shares of ₹ 10 each fully paid | 10,000 | 0.1 | 10,000
- parser: label `Softdeal Pharmaceuticals Private Limited Shares of ₹ 10 each fully paid` | column `As at March 31, 2024 Quantity` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `Softdeal Pharmaceuticals Private Limited Shares of ₹ 10 each fully paid - Quantity` | unit shares | period 2024-03-31 | keep True
- v2+guards: label `Softdeal Pharmaceuticals Private Limited Shares of ₹ 10 each fully paid - Quantity` | unit shares | period 2024-03-31 | keep True

## 4. SUNPHARMA p252 value 7,607.8
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 34 EMPLOYEE BENEFITS EXPENSE / ₹ in Million / Year ended / March 31, 2024 / Year ended / March 31, 2023 / Sal
- around value: 7,767.9 | 7,189.4 | Conversion and other manufacturing charges | 6,302.6 | 5,613.2 | Power and fuel | 7,607.8 | 8,300.5 | Rent
- parser: label `Power and fuel` | column `Year ended March 31, 2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `Power and fuel` | unit million | period 2024-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Power and fuel (under Other expenses, Note 36)` | unit million | period 2024-03-31 | keep True

## 5. SUNPHARMA p8 value 718
- page head: (₹ Million) / Particulars / FY15 / FY16 / FY17 / FY18 / FY19 / FY20 / FY21 / FY22 / FY23 / FY24 / Operating performance / Revenue from operations / 273,920 284,870 315,784 264,895 290,659 328,375 334,
- around value: 31,776 | (a)	 Capital | 1,178 | 783 | 1,679 | 1,819 | 718 | 484 | 471
- parser: label `(a) Capital` | column `FY19` | unit million | period 2019-03-31 | page unit million
- v1+guards: label `R&D expenditure (a) Capital` | unit million | period 2019-03-31 | keep True
- v2+guards: label `R&D expenditure (a) Capital` | unit million | period 2019-03-31 | keep True

## 6. SUNPHARMA p250 value 432,788.7
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 26 OTHER FINANCIAL LIABILITIES (CURRENT) / ₹ in Million / As at / March 31, 2024 / As at / March 31, 2023 / I
- around value: Year ended | March 31, 2024 | Year ended | March 31, 2023 | Revenue from contracts with customers (Refer note 53) | 477,584.5 | 432,788.7 | Other operating revenues* | 7,384.0
- parser: label `Revenue from contracts with customers (Refer note` | column `₹ in Million Year ended March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Revenue from contracts with customers (Refer note)` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Revenue from contracts with customers (Refer note 53)` | unit million | period 2023-03-31 | keep True

## 7. SUNPHARMA p276 value 5,537.3
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / ₹ in Million / Year ended March 31, 2024 / Year ended March 31, 2023 / COVID-19 / Education / (Unfunded) / Pension 
- around value: Obligations as at the beginning of the year | 83.4 | 1,017.8 | 6,224.9 | 92.5 | 1,072.2 | 5,537.3 | Current service cost
- parser: label `Reconciliation of defined benefit obligations Obligations as at the beginning of the year` | column `₹ in Million Year ended March 31, 2023 Gratuity (Funded) ₹ in Million As at Marc` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Reconciliation of defined benefit obligations - Obligations as at the beginning of the year - Gratuity (Funded)` | unit million | period 2023-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Reconciliation of defined benefit obligations - Obligations as at the beginning of the year - Gratuity (Funded)` | unit million | period 2023-03-31 | keep True

## 8. SUNPHARMA p216 value 5,828.2
- page head: Consolidated Balance Sheet / as at March 31, 2024 / ₹ in Million / Particulars / Notes / As at / March 31, 2024 / As at / March 31, 2023 / EQUITY AND LIABILITIES / Equity / (a)	 Equity share capital 
- around value: 1,550.6 | 316.9 | (d)	 Other non-current liabilities | 24 | 4,999.4 | 5,828.2 | Total non-current liabilities | 13,725.1
- parser: label `(d) Other non-current liabilities` | column `₹ in Million As at March 31, 2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Other non-current liabilities` | unit million | period 2023-03-31 | keep True
- v2+guards: label `Non-current liabilities - (d) Other non-current liabilities` | unit million | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 9. SUNPHARMA p270 value 8,475.9
- page head: Notes to the Consolidated Financial Statements / for the year ended March 31, 2024 / NOTE: 48 Disclosures mandated by the Companies Act, 2013 Schedule III Part II by way of additional information is 
- around value: - | Others | 289.3 | (543.9) | Income tax expense recognised in consolidated statement of profit and loss | 14,394.5 | 8,475.9 | NOTE: 50 DEFERRED TAX | (i)
- parser: label `Income tax expense recognised in consolidated statement of profit and loss NOTE: 50 DEFERRED TAX (i) Deferred tax assets` | column `₹ in Million Year ended March 31, 2023 ₹ in Million Closing balance March 31, 20` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Income tax expense recognised in consolidated statement of profit and loss` | unit million | period 2023-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Income tax expense recognised in consolidated statement of profit and loss - Tax reconciliation` | unit million | period 2023-03-31 | keep True

## 10. LT p484 value 7848.97
- page head: Corporate / Overview / Statutory / Reports / Integrated / Report / Management / Discussion and Analysis / Financial / Statements / 481 / NOTE [49] / Basic and diluted Earnings per Share [EPS] computed
- around value: 2022-23 | Basic earnings per share | Net profit after tax (¢ crore) | A | 9304.33 | 7848.97 | Weighted average number of equity shares outstanding
- parser: label `Net profit after tax (¢ crore) A` | column `2022-23` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Net profit after tax (₹ crore) A` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Net profit after tax (₹ crore) A - Basic earnings per share` | unit crore | period 2023-03-31 | keep True

## 11. LT p627 value 1144.31
- page head: Integrated Annual Report 2023-24 / 624 / Notes forming part of the / Consolidated Financial Statements / (f) 	 Fair value hierarchy of financial assets and financial liabilities at fair value: / v cro
- around value: 0.09 | 0.09 | (iv) 	 Derivative instruments designated as cash flow | hedges | 9,18 | – | 1144.31 | – | 1144.31
- parser: label `hedges` | column `and financial liabilities at fair value: As at 31-3-2024 Level 2` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `hedges` | unit crore | period 2024-03-31 | keep True | rejected: label '(ix) Loans (Financial Services) Financial assets at FVTOCI - As at 31-3-2024 Level 2' rejected: shares 0% of the row's own words
- v2+guards: label `Financial assets at FVTOCI: (iv) Derivative instruments designated as cash flow hedges - As at 31-3-2024 Level 2` | unit crore | period 2024-03-31 | keep True

## 12. LT p19 value 49,107
- page head: v crore / Description / IndAS [12] / IGAAP [12] / 2023-24 / 2022-23 / 2021-22 / 2020-21 / 2019-20 / 2018-19 / 2017-18 / 2016-17 / 2015-16 / 2014-15 / [9]
- around value: 10,28,541 | 8,53,824 | No. of employees | 59,344 | 55,202 | 50,267 | 49,107 | 45,467 | 45,205
- parser: label `No. of employees [1] [2] June 30, 2017)]. [6] [7] [8] [9] [10] [12]` | column `FINANCIALS- 2020-21 0.40:1 (PBDIT) is excluding exceptional items wherever appli` | unit count | period 2021-03-31 | page unit None
- v1+guards: label `No. of employees` | unit count | period 2021-03-31 | keep True
- v2+guards: label `No. of employees` | unit count | period 2021-03-31 | keep True

## 13. LT p451 value 1413.59
- page head: Integrated Annual Report 2023-24 / 448 / Notes forming part of the / Standalone Financial Statements / NOTE [40] / Disclosure pursuant to Ind AS 108 “Operating Segment” / (a) / Information about repor
- around value: 4895.44 | Sub-total | 126235.85 | 1762.18 | 127998.03 | 110500.98 | 1413.59 | 111914.57 | Inter-segment revenue
- parser: label `Sub-total` | column `For the year ended 31-3-2023 Inter- segment Segment Liabilities As at 31-3-2024` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Segment assets - Sub-total - Inter-segment` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Sub-total - Inter-segment revenue` | unit crore | period 2023-03-31 | keep True

## 14. LT p587 value (50.43)
- page head: Integrated Annual Report 2023-24 / 584 / Notes forming part of the / Consolidated Financial Statements / NOTE [43] / Disclosures pursuant to Ind AS 112 “Disclosure of interest in other entities” : Joi
- around value: 1.86 | 0.60 | 1.23 | 2.37 | Depreciation and amortisation | (37.95) | (50.43) | (68.64) | (66.16)
- parser: label `Depreciation and amortisation` | column `2022-23` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Depreciation and amortisation` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Depreciation and amortisation - L&T - MHI Power Boilers Private Limited` | unit crore | period 2023-03-31 | keep True

## 15. LT p566 value 3,256
- page head: Corporate / Overview / Statutory / Reports / Integrated / Report / Management / Discussion and Analysis / Financial / Statements / 563 / the rate of 25% each over a period of four years from the date 
- around value: Options granted during the year | – | – | vi. | Options exercised during the year | 5,014 | 3,256 | vii. | Options lapsed/cancelled during the year
- parser: label `vi. Options exercised during the year` | column `2022-23 9-8-2021 onwards 9-8-2022 onwards` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `vi. Options exercised during the year - share price Series B 2023-24 9-8-2021 onwards 9-8-2022 onwards` | unit count | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2021', '2022', '2023']
- v2+guards: label `Series B - Options exercised during the year` | unit count | period 2023-03-31 | keep True

## 16. LT p456 value 277.16
- page head: Corporate / Overview / Statutory / Reports / Integrated / Report / Management / Discussion and Analysis / Financial / Statements / 453 / NOTE [42] / Disclosure pursuant to Ind AS 1 “Presentation of fi
- around value: Provisions | 28 | 1428.87 | 222.71 | 1651.57 | 1555.21 | 277.16 | 1832.37 | Total
- parser: label `Provisions` | column `As at 31-3-2023 After twelve months` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Provisions - As at 31-3-2023 After twelve months` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Provisions - As at 31-3-2023 After twelve months` | unit crore | period 2023-03-31 | keep True

## 17. LT p558 value 16.14
- page head: Corporate / Overview / Statutory / Reports / Integrated / Report / Management / Discussion and Analysis / Financial / Statements / 555 / NOTE [11] / Current assets: Inventories / v crore / Particulars
- around value: Current assets: Financial assets - Investments | v crore | Particulars | As at 31-3-2024 | As at 31-3-2023 | Equity shares | 16.14 | 40.31 | Government and trust securities
- parser: label `Equity shares` | column `31-3-2024` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Equity shares` | unit crore | period 2024-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `NOTE [12] Current assets: Financial assets - Investments: Equity shares` | unit crore | period 2024-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark

## 18. LT p475 value (70.24)
- page head: Integrated Annual Report 2023-24 / 472 / Notes forming part of the / Standalone Financial Statements / v crore / Sr. / No. / Nature of transaction/relationship/major parties / 2023-24 / 2022-23 / Amou
- around value: 15.68 | xxv | Amount recognised in Profit or Loss on account of impairment/(reversal of | impairment) loss on investment and inter corporate deposit | Subsidiaries, including: | (70.24) | (891.86)
- parser: label `impairment) loss on investment and inter corporate deposit xxv Amount recognised in Profit or Loss on account of impairm` | column `2023-24 Amount` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Impairment loss on investment and inter corporate deposit (xxv) - Amount recognised in Profit` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `xxv Amount recognised in Profit or Loss on account of impairment/(reversal of impairment) loss on investment and inter c` | unit crore | period 2024-03-31 | keep True

## 19. LT p404 value 1676.96
- page head: Corporate / Overview / Statutory / Reports / Integrated / Report / Management / Discussion and Analysis / Financial / Statements / 401 / Standalone Statement of Cash Flows for the year ended March 31,
- around value: 7450.00 | 2450.00 | Repayment of non-current borrowings | (4845.00) | (5549.00) | (Repayments)/proceeds from other borrowings (net) | 1676.96 | 1078.98 | Settlement of derivative contracts related to borrowings
- parser: label `(Repayments)/proceeds from other borrowings (net)` | column `2023-24` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `(Repayments)/proceeds from other borrowings (net)` | unit crore | period 2024-03-31 | keep True
- v2+guards: label `C. Cash flow from financing activities - (Repayments)/proceeds from other borrowings (net)` | unit crore | period 2024-03-31 | keep True

## 20. ICICIBANK p297 value 39,349.2
- page head: Annual Report 2023-24 | 223 / Integrated Report / Statutory Reports / Financial Statements / FINANCIAL STATEMENTS OF ICICI BANK LIMITED / SCHEDULES / forming part of the Accounts (Contd.) / ` in milli
- around value: March 31, | 2020 | Plan assets | 59,385.6 | 49,805.1 | 44,339.6 | 39,349.2 | 33,424.3 | Defined benefit obligations
- parser: label `Plan assets` | column `Year ended March 31, 2021` | unit million | period 2021-03-31 | page unit million
- v1+guards: label `Plan assets` | unit million | period 2021-03-31 | keep True
- v2+guards: label `Plan assets` | unit million | period 2021-03-31 | keep True

## 21. ICICIBANK p355 value 879,292,351
- page head: Annual Report 2023-24 | 281 / Integrated Report / Statutory Reports / Financial Statements / ` in ‘000s / Year ended / 31.03.2024 / Year ended / 31.03.2023 / SCHEDULE 13 - INTEREST EARNED / I. / Inter
- around value: Year ended | 31.03.2023 | SCHEDULE 13 - INTEREST EARNED | I. | Interest/discount on advances/bills | 1,165,897,763 | 879,292,351 | II. | Income on investments (including dividend)
- parser: label `Interest/discount on advances/bills` | column `in ‘000s ` Year ended 31.03.2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Interest/discount on advances/bills` | unit thousand | period 2023-03-31 | keep True
- v2+guards: label `Interest/discount on advances/bills` | unit thousand | period 2023-03-31 | keep True

## 22. ICICIBANK p235 value 271,391,562
- page head: Annual Report 2023-24 | 161 / Integrated Report / Statutory Reports / Financial Statements / ` in ‘000s / At / 31.03.2024 / At / 31.03.2023 / SCHEDULE 5 - OTHER LIABILITIES AND PROVISIONS / I. / Bills
- around value: 47,022,362 | VI.	 Unrealised loss on foreign exchange and derivative contracts1 | 173,575,855 | 178,698,973 | VII.	 Others (including provisions)2 | 362,466,486 | 271,391,562 | TOTAL OTHER LIABILITIES AND PROVISIONS | 953,227,258
- parser: label `VII. Others (including provisions)2` | column `in ‘000s ` At 31.03.2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `VII. Others (including provisions) - TOTAL OTHER LIABILITIES AND PROVISIONS` | unit thousand | period 2023-03-31 | keep True
- v2+guards: label `VII. Others (including provisions) - Other liabilities and provisions` | unit thousand | period 2023-03-31 | keep True

## 23. ICICIBANK p216 value 154.71
- page head: MANAGEMENT DISCUSSION & ANALYSIS / 142 | Annual Report 2023-24 / ICICI Lombard General Insurance Company (ICICI / General) / The Gross Domestic Premium Income of ICICI General / increased by 17.8% yea
- around value: 18.15 | 24.89 | 29.18 | ICICI Securities Limited (consolidated) | 11.40 | 17.33 | 154.71 | 253.65 | ICICI Securities Primary Dealership Limited
- parser: label `ICICI Securities Limited (consolidated)` | column `Total assets1 At March 31, 2023` | unit billion | period 2023-03-31 | page unit million
- v1+guards: label `ICICI Securities Limited (consolidated) Total assets At March 31, 2023` | unit billion | period 2023-03-31 | keep True
- v2+guards: label `ICICI Securities Limited (consolidated) - Total assets at March 31, 2023` | unit billion | period 2023-03-31 | keep True

## 24. ICICIBANK p286 value 299,860.7
- page head: 212 | Annual Report 2023-24 / FINANCIAL STATEMENTS OF ICICI BANK LIMITED / SCHEDULES / forming part of the Accounts (Contd.) / (II)	 Sector-wise advances / ` in million, except percentages / S / No. /
- around value: Sub-total (B) | 7,603,933.5 | 245,159.1 | 3.22% | Total (A)+(B) | 10,446,527.0 | 299,860.7 | 2.87%
- parser: label `Total (A)+(B) 1. Represents loans and advances. 2. Excludes commercial business loans and dealer funding.` | column `` in million, except percentages At March 31, 2023 Gross NPAs1` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Total (A)+(B) 1. Represents loans and advances. 2. Excludes commercial business loans and dealer funding.` | unit million | period 2023-03-31 | keep True | rejected: label 'Total (A)+(B) Gross NPA' rejected: shares 0% of the row's own words
- v2+guards: label `Total (A)+(B) Gross NPAs` | unit million | period 2023-03-31 | keep True

## 25. ICICIBANK p347 value 9,927,900
- page head: Annual Report 2023-24 | 273 / Integrated Report / Statutory Reports / Financial Statements / SCHEDULES / forming part of the Consolidated Balance Sheet (Contd.) / ` in ‘000s / At / 31.03.2024 / At / 3
- around value: Opening balance | 21,758,809 | 20,714,999 | Additions during the year | 9,927,900 | 1,043,810
- parser: label `Additions during the year` | column `At 31.03.2024` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `V. Investment fluctuation reserve - Additions during the year` | unit thousand | period 2024-03-31 | keep True
- v2+guards: label `V. Investment fluctuation reserve - Additions during the year` | unit thousand | period 2024-03-31 | keep True

## 26. ICICIBANK p355 value 279,050,297
- page head: Annual Report 2023-24 | 281 / Integrated Report / Statutory Reports / Financial Statements / ` in ‘000s / Year ended / 31.03.2024 / Year ended / 31.03.2023 / SCHEDULE 13 - INTEREST EARNED / I. / Inter
- around value: Interest/discount on advances/bills | 1,165,897,763 | 879,292,351 | II. | Income on investments (including dividend) | 381,070,710 | 279,050,297 | III. | Interest on balances with Reserve Bank of India and other inter-bank funds
- parser: label `Income on investments (including dividend)` | column `in ‘000s ` Year ended 31.03.2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Income on investments (including dividend)` | unit thousand | period 2023-03-31 | keep True
- v2+guards: label `Income on investments (including dividend)` | unit thousand | period 2023-03-31 | keep True

## 27. ICICIBANK p257 value 5,084,697.5
- page head: Annual Report 2023-24 | 183 / Integrated Report / Statutory Reports / Financial Statements / FINANCIAL STATEMENTS OF ICICI BANK LIMITED / SCHEDULES / forming part of the Accounts (Contd.) / 'RBI’s Mas
- around value: Net profit/(loss) (6)-(7) | 318,965.0 | 9. | Segment assets | 6,039,593.7 | 4,328,743.5 | 5,084,697.5 | 297,915.4 | 15,750,950.1
- parser: label `9. Segment assets` | column `For the year ended March 31, 2023 Treasury` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `9. Segment assets - Treasury` | unit million | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']
- v2+guards: label `9. Segment assets - For the year ended March 31, 2023 Treasury` | unit million | period 2023-03-31 | keep True

## 28. ICICIBANK p346 value 26,254,000
- page head: 272 | Annual Report 2023-24 / ` in ‘000s / At / 31.03.2024 / At / 31.03.2023 / SCHEDULE 1 - CAPITAL / Authorised capital / 12,500,000,000 equity shares of ` 2 each (March 31, 2023: 12,500,000,000 / eq
- around value: 160,232,000 | 133,978,000 | Additions during the year | 31,353,000 | 26,254,000
- parser: label `Additions during the year` | column `` in ‘000s At 31.03.2023` | unit million | period 2023-03-31 | page unit million
- v1+guards: label `Additions during the year - Securities premium` | unit thousand | period 2023-03-31 | keep True
- v2+guards: label `II. Special Reserve - Additions during the year` | unit thousand | period 2023-03-31 | keep True

## 29. ICICIBANK p273 value 15,946.4
- page head: Annual Report 2023-24 | 199 / Integrated Report / Statutory Reports / Financial Statements / FINANCIAL STATEMENTS OF ICICI BANK LIMITED / SCHEDULES / forming part of the Accounts (Contd.) / Trading /
- around value: 16,141.2 | 10 | 5,396.9 | 7 | JPYTONAR | Fixed receivable v/s Floating payable | 15,946.4 | 10 | 5,852.0
- parser: label `JPYTONAR Fixed receivable v/s Floating payable` | column `LIMITED At March 31, 2024 Notional principal` | unit million | period 2024-03-31 | page unit million
- v1+guards: label `JPYTONAR Fixed receivable v/s Floating payable Notional principal` | unit million | period 2024-03-31 | keep True
- v2+guards: label `JPYTONAR Fixed receivable v/s Floating payable - Notional principal` | unit million | period 2024-03-31 | keep True

## 30. TITAGARH p67 value 10,780.38
- page head: 130 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Standalone Balance Sheet as at March 31, 2024 / Titagarh Rail Systems Limited (Formerly Titagarh Wagons Limited) / Notes / As at / March 3
- around value: b) Right-of-Use Assets | 6.6 | 9,069.72 | 10,191.97 | c) Capital Work-in-progress | 6.4 | 10,780.38 | 1,227.91 | d) Investment Properties
- parser: label `c) Capital Work-in-progress` | column `As at March 31, 2024 Rs. In Lacs` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `c) Capital Work-in-progress (Non-current Assets)` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `c) Capital Work-in-progress` | unit lakh | period 2024-03-31 | keep True

## 31. TITAGARH p16 value 5,546.37
- page head: 28 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / BOARD’S REPORT / Dear Shareholders, / Your Directors present their Twenty-Seventh Annual Report on the business and operations of Titagarh 
- around value: - | Proﬁ t/(Loss) before tax | 39,704.68 | 15,877.21    38,857.38 | 19,009.70 | Tax Expenses/(Beneﬁ ts) | 10,014.00       5,540.57     10,014.00       5,546.37 | Proﬁ t/(Loss) for the year after tax from continuing | operations
- parser: label `Tax Expenses/(Beneﬁ ts)` | column `(Rs. in lakhs) Consolidated 2022-23` | unit lakh | period 2023-03-31 | page unit None
- v1+guards: label `Tax Expenses/(Beneﬁ ts)` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Tax Expenses/(Benefits) - Consolidated 2022-23` | unit lakh | period 2023-03-31 | keep True

## 32. TITAGARH p54 value 723
- page head: 104 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Category / FY 2023-24 / FY 2022-23 / Total (A) / No. of / Employees/ / Workers / covered (B) / % (B/A) / Total (A) / No. of / Employees/ /
- around value: Employees/ | Workers | covered (B) | % (B/A) | Employees | Permanent | 723 | 680 | 94
- parser: label `Permanent` | column `Total (A)` | unit count | period None | page unit lakh
- v1+guards: label `Permanent employees - Total (A)` | unit count | period None | keep True
- v2+guards: label `Employees - Permanent - FY 2023-24 No. of Employees/Workers covered (B)` | unit count | period None | keep True | rejected: period 2024-03-31 rejected: year not in header

## 33. TITAGARH p145 value 3,804.22
- page head: 286 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / The Group’s foreign currency exposure at the end of the reporting period are as follows: / (Rs. in Lacs) / March 31, 2024 / PARTICULARS / 
- around value: (3,187.62) | 1,852.20 | 989.85 | Net exposure to Foreign Currency Risk | (Assets less Liabilities) | 467.89 | 3,804.22 | (1,753.50) | (1,076.38)
- parser: label `Net exposure to Foreign Currency Risk (Assets less Liabilities) Foreign Currency Sensitivity` | column `March 31, 2023 USD EURO` | unit usd | period 2023-03-31 | page unit lakh
- v1+guards: label `Net exposure to Foreign Currency Risk (Assets less Liabilities) - Foreign Currency Sensitivity - March 31, 2023 USD EURO` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Net exposure to Foreign Currency Risk (Assets less Liabilities) - Foreign Currency Sensitivity - March 31, 2023 - EURO` | unit lakh | period 2023-03-31 | keep True

## 34. TITAGARH p125 value 164.86
- page head: 246 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Notes to Consolidated Financial Statements as at and for the year ended March 31, 2024 / Titagarh Rail Systems Limited (Formerly Titagarh 
- around value: March 31, 2023 | Rs. In Lacs | Security Deposits* | 437.90 | 363.37 | 190.90 | 164.86 | Bank Deposits with Remaining Maturity of | More than Twelve Months @
- parser: label `Security Deposits*` | column `As at March 31, 2023 Rs. In Lacs` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Security Deposits* - Current` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Security Deposits* - Current` | unit lakh | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 35. TITAGARH p81 value 1.42%
- page head: 158 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / @ During the year following new equity shares were issued: / 1) Pursuant to approval by the Board of Directors and the / Shareholders of t
- around value: 0.00% | -0.01% | Titagarh Logistics | Infrastructures Pvt. Ltd. | 19,08,487 | 1.42% | -0.18% | 19,08,487
- parser: label `Titagarh Logistics` | column `As at March 31, 2024 % of total shares` | unit % | period 2024-03-31 | page unit lakh
- v1+guards: label `Titagarh Logistics Infrastructures Pvt. Ltd. - As at March 31, 2024 % of total shares` | unit percent | period 2024-03-31 | keep True
- v2+guards: label `Titagarh Logistics Infrastructures Pvt. Ltd. - As at March 31, 224 % of total shares` | unit percent | period 2024-03-31 | keep True

## 36. TITAGARH p67 value 4,452.93
- page head: 130 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Standalone Balance Sheet as at March 31, 2024 / Titagarh Rail Systems Limited (Formerly Titagarh Wagons Limited) / Notes / As at / March 3
- around value: 6,690.58 | - | g) Financial Assets | i) Investments | 7 | 21,293.27 | 4,452.93 | ii) Other Financial Assets | 9
- parser: label `g) Financial Assets i) Investments` | column `As at March 31, 2023 Rs. In Lacs` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `g) Financial Assets i) Investments (Non-current Assets)` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `g) Financial Assets i) Investments` | unit lakh | period 2023-03-31 | keep True

## 37. TITAGARH p108 value 2,61,935.01
- page head: 212 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Notes / As at / March 31, 2024 / Rs. In Lacs / As at / March 31, 2023 / Rs. In Lacs / I. ASSETS / Non-current Assets / Property, Plant and
- around value: Other Expenses | 29 | 34,699.88 | 30,963.52 | Total Expenses | 3,50,192.53 | 2,61,935.01 | Proﬁ t before Share of Net Loss of Joint Ventures and Associate Accounted for Using the | Equity Method, Exceptional Items and Tax
- parser: label `Total Expenses` | column `For the year ended March 31, 2023 Rs. In Lacs` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Total Expenses` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Total Expenses` | unit lakh | period 2023-03-31 | keep True

## 38. TITAGARH p108 value 12,020.67
- page head: 212 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Notes / As at / March 31, 2024 / Rs. In Lacs / As at / March 31, 2023 / Rs. In Lacs / I. ASSETS / Non-current Assets / Property, Plant and
- around value: Total Comprehensive Income for the Year | 28,646.23 | 11,571.93 | Attributable to: | Owners of Titagarh Rail Systems Limited (Formerly Titagarh Wagons Limited) | 28,646.23 | 12,020.67 | Non-controlling Interests | -
- parser: label `Attributable to: Owners of Titagarh Rail Systems Limited (Formerly Titagarh Wagons Limited)` | column `For the year ended March 31, 2023 Rs. In Lacs` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Attributable to: Owners of Titagarh Rail Systems Limited (Formerly Titagarh Wagons Limited) - Total Comprehensive Income` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Attributable to: Owners of Titagarh Rail Systems Limited (Formerly Titagarh Wagons Limited) - Total Comprehensive Income` | unit lakh | period 2023-03-31 | keep True

## 39. TITAGARH p67 value 26,803.47
- page head: 130 | TITAGARH RAIL SYSTEMS LIMITED | Annual Report 2023-24 / Standalone Balance Sheet as at March 31, 2024 / Titagarh Rail Systems Limited (Formerly Titagarh Wagons Limited) / Notes / As at / March 3
- around value: 343.64 | d) Deferred Tax Liabilities (Net) | 20 | 1,064.46 | 1,346.36 | Total Non-current Liabilities | 26,803.47 | 19,425.14 | Current Liabilities
- parser: label `Total Non-current Liabilities` | column `As at March 31, 2024 Rs. In Lacs` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Total Non-current Liabilities` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Total Non-current Liabilities` | unit lakh | period 2024-03-31 | keep True

## 40. KPIGREEN p221 value 4.14
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24 / 242 / (All the figures are in lakhs) / Particulars / 31-03-2024 / 31
- around value: 31-03-2024 | 31-03-2023 | Employee Benefits | Gratuity | Provision for Gratuity | 6.84 | 4.14 | 6.84 | 4.14
- parser: label `28. Current Tax Liabilities (net) Tax Provision Current Tax` | column `(All the figures are in lakhs) 31-03-2023 (All the figures are in lakhs) 31-03-2` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Current Tax Liabilities (net) - Tax Provision - Current Tax` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Current Tax Liabilities (net) - Tax Provision - Current Tax - Provision For Income Tax` | unit lakh | period 2023-03-31 | keep True

## 41. KPIGREEN p57 value 16,165.68
- page head: KPI Green Energy Limited / Annual Report 2023-24 / 78 / Directors' Report / Dear Shareholders, / The Board of Directors are pleased to present the 16th Annual Report along with Audited Financial State
- around value: 2,218.98 | 5,536.06 | 3,224.18 | Profit for the period | 10,371.60 | 7,839.36 | 16,165.68 | 10,962.79 | 1.	 Previous period/ year figures have been re-grouped/ re-classified wherever required.
- parser: label `Profit for the period` | column `Consolidated 2023-24` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Profit for the period` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Profit for the period` | unit lakh | period 2024-03-31 | keep True | rejected: period 2023-03-31 rejected: header supports ['2024']

## 42. KPIGREEN p237 value 44,454.51
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24 / 258 / The Company, KPI Green Energy Limited has given gurrantee of `
- around value: ratio is less than 25%, | reasons for change is not | given. | Current Assets (a) | in lakhs | 1,33,387.70 | 44,454.51 | 24.07% | Current Liabilities (b)
- parser: label `Current Assets (a) in lakhs` | column `March 31, 2023` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Current Assets (a)` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Current Assets (a) in lakhs` | unit lakh | period 2023-03-31 | keep True

## 43. KPIGREEN p167 value 6,711.05
- page head: Notes to Standalone Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24 / 188 / (iii) Fair value of instruments measured at amortised cost / Par
- around value: 306.94 | 306.94 | Investments | Level 3 | 21,391.83 | 21,391.83 | 6,711.05 | 6711.05 | Trade receivables
- parser: label `Investments Level` | column `March 31, 2023 Carrying value` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Investments Level - March 31, 2023 Carrying value` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Investments - Level 3 - Fair value` | unit lakh | period 2023-03-31 | keep True

## 44. KPIGREEN p151 value 23.02
- page head: Notes to Standalone Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24 / 172 / (All the figures are in lakhs) / Particulars / 31-03-2024 / 31-0
- around value: TCS Receivable | 0.72 | 0.72 | Deposits | - | 32.46 | 23.02 | 182.44 | 15. Other current assets
- parser: label `15. Other current assets Capital advances` | column `(All the figures are in lakhs) 31-03-2024 (All the figures are in lakhs) 31-03-2` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Other current assets - Capital advances` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `15. Other current assets - Capital advances` | unit lakh | period 2024-03-31 | keep True

## 45. KPIGREEN p57 value 3,680.59
- page head: KPI Green Energy Limited / Annual Report 2023-24 / 78 / Directors' Report / Dear Shareholders, / The Board of Directors are pleased to present the 16th Annual Report along with Audited Financial State
- around value: 25,274.82 | 15,695.31 | 34,375.90 | 21,173.77 | Finance Cost | 7,638.59 | 3,680.59 | 8,606.21 | 4,676.45
- parser: label `Finance Cost` | column `Standalone 2022-23` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Finance Cost` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Finance Cost` | unit lakh | period 2023-03-31 | keep True

## 46. KPIGREEN p151 value 21,002.66
- page head: Notes to Standalone Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24 / 172 / (All the figures are in lakhs) / Particulars / 31-03-2024 / 31-0
- around value: (All the figures are in lakhs) | Particulars | 31-03-2024 | 31-03-2023 | Capital advances | Advance Given to Suppliers | 21,002.66 | - | Advances other than capital advances
- parser: label `Advance Given to Suppliers Advances other than capital advances` | column `31-03-2024 31-03-2024` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Advances other than capital advances - Advance Given to Suppliers` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Other current assets - Advances other than capital advances - Advance Given to Suppliers` | unit lakh | period 2024-03-31 | keep True

## 47. KPIGREEN p231 value 23,189.32
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24 / 252 / 46. Segment Reporting / Information reported to the CODM for t
- around value: 2,12,596.91 | 1,08,659.22 | Sale of Plot | 7,807.20 | 8,110.25 | Unallocable Assets | 23,189.32 | 8,728.03 | Total Segment Assets
- parser: label `Unallocable Assets` | column `Year ended March 31, 2024` | unit lakh | period 2024-03-31 | page unit lakh
- v1+guards: label `Segment Assets - Unallocable Assets` | unit lakh | period 2024-03-31 | keep True
- v2+guards: label `Segment Assets - Unallocable Assets` | unit lakh | period 2024-03-31 | keep True

## 48. KPIGREEN p57 value 46.13
- page head: KPI Green Energy Limited / Annual Report 2023-24 / 78 / Directors' Report / Dear Shareholders, / The Board of Directors are pleased to present the 16th Annual Report along with Audited Financial State
- around value: 3,546.99 | 1,910.25 | 4,037.41 | 2,261.76 | Extraordinary items/ Prior Period Items | 30.54 | 46.13 | 30.54 | 48.59
- parser: label `Extraordinary items/ Prior Period Items` | column `Standalone 2022-23` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Extraordinary items/ Prior Period Items` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `Extraordinary items/ Prior Period Items` | unit lakh | period 2023-03-31 | keep True

## 49. KPIGREEN p221 value 875.77
- page head: Notes to Consolidated Financial Statements / For the year ended March 31, 2024 / KPI Green Energy Limited / Annual Report 2023-24 / 242 / (All the figures are in lakhs) / Particulars / 31-03-2024 / 31
- around value: 250.00 | - | Unclaimed Dividend | 7.07 | - | 2,678.98 | 875.77 | 26. Other Current liabilities | (All the figures are in lakhs)
- parser: label `26. Other Current liabilities Revenue Received in Advance` | column `(All the figures are in lakhs) 31-03-2023 (All the figures are in lakhs) 31-03-2` | unit lakh | period 2023-03-31 | page unit lakh
- v1+guards: label `Other Current Liabilities - Revenue Received in Advance` | unit lakh | period 2023-03-31 | keep True
- v2+guards: label `26. Other Current liabilities - Revenue Received in Advance` | unit lakh | period 2023-03-31 | keep True

## 50. NAVINFLUOR p157 value 5.80%
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: 19.36% | Public Sector Units | 31.08% | 28.14% | Others | 5.97% | 5.80% | 46.	 EMPLOYEE BENEFIT PLANS  (contd.)
- parser: label `Others` | column `As at March 31, 2023` | unit % | period 2023-03-31 | page unit crore
- v1+guards: label `Others - Investments` | unit percent | period 2023-03-31 | keep True
- v2+guards: label `Others - Category wise plan assets` | unit percent | period 2023-03-31 | keep True

## 51. NAVINFLUOR p136 value (9.04)
- page head: Financial Section / Corporate Overview / 266 / 267 / Annual Report 2023-24 / Statutory Reports / Consolidated Statement of Cash Flows / for the year ended March 31, 2024 / Amount ` in crores unless ot
- around value: - | (Gain) / Loss on sale / disposal of property, plant and equipment (Net) | 0.89 | (1.97) | (Gain) on sale of investments (Net) | (5.34) | (9.04) | Changes in fair value of financial assets at fair value through profit or loss | (10.95)
- parser: label `(Gain) on sale of investments (Net)` | column `` in crores unless otherwise stated For the year ended March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `(Gain) on sale of investments (Net)` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Adjustments for: (Gain) on sale of investments (Net)` | unit crore | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 52. NAVINFLUOR p156 value 30.22
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: March  31, 2023 | Present value of funded defined benefit obligation | (38.33) | (33.54) | Fair value of plan assets | 31.54 | 30.22 | Net (liability)/asset arising from gratuity | (6.79)
- parser: label `Closing fair value of plan assets (D) (c) Principal assumptions` | column `crores unless otherwise stated For the year ended March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Closing fair value of plan assets (D)` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `D. Movements in the fair value of the plan assets - Closing fair value of plan assets (D)` | unit crore | period 2023-03-31 | keep True

## 53. NAVINFLUOR p143 value 33.09
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: Balance as at March 31, 2023 | 7.81 | 2.20 | 1.31 | 21.77 | 33.09 | I. 	 Gross Block
- parser: label `Net block (I-II) Balance as at March 31, 2023 I. Gross Block` | column `Total` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Net block (I-II) Balance as at March 31, 2023 - Total` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Net block (I-II) Balance as at March 31, 2023 I. Gross Block - Total` | unit crore | period 2023-03-31 | keep True

## 54. NAVINFLUOR p144 value 1.13
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: Opening Balance | 7.93 | 6.80 | Charge for the year | 1.14 | 1.13 | Closing Balance
- parser: label `Depreciation` | column `As at March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Depreciation on investment properties` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Depreciation - Amount recognised in the Statement of Profit and Loss for investment properties` | unit crore | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 55. NAVINFLUOR p158 value 2.77
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: –  Cash and Bank Balances | 27.54 | 34.81 | –  Investments | 1.85 | 2.77 | –  Trade receivables
- parser: label `– Investments` | column `As at March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Investments (non-current assets)` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Investments (Financial assets, Measured at Amortised Cost)` | unit crore | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 56. NAVINFLUOR p135 value 7.96
- page head: Financial Section / Corporate Overview / 264 / 265 / Annual Report 2023-24 / Statutory Reports / Consolidated Balance Sheet / as at March 31, 2024 / Amount ` in crores unless otherwise stated / Partic
- around value: 90.02 | 5.38 | c. | Provisions | 32 | 12.12 | 7.96 | d. | Current tax liabilities (Net)
- parser: label `c. Provisions` | column `Amount ` in crores unless otherwise stated As at March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Current liabilities c. Provisions` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Current liabilities c. Provisions` | unit crore | period 2023-03-31 | keep True

## 57. NAVINFLUOR p151 value (15.49)
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: (1.47) | Interest expense | - | - | (0.95) | (14.54) | (15.49) | Interest paid | -
- parser: label `Interest expense` | column `As at March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Interest expense - Borrowings` | unit crore | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']
- v2+guards: label `Interest expense - Borrowings (Liabilities from financing activities)` | unit crore | period 2023-03-31 | keep True | rejected: period 2024-03-31 rejected: header supports ['2023']

## 58. NAVINFLUOR p55 value 445.46
- page head: Corporate Overview / Statutory Reports / Financial Section / 104 / 105 / Annual Report 2023-24 / Analysis of the Consolidated P&L Statement / Revenue / The Company’s consolidated revenue for FY 2023-2
- around value: 935.43 | 896.01 | Employee expenses | 285.84 | 249.41 | Other expenses | 445.46 | 381.67 | Total expenses
- parser: label `Other expenses` | column `2023-24 2023-24` | unit crore | period 2024-03-31 | page unit crore
- v1+guards: label `Other expenses` | unit crore | period 2024-03-31 | keep True | rejected: unit 'rupees' rejected: header carries a scale or no currency mark
- v2+guards: label `Other expenses (Consolidated Profit and Loss Statement)` | unit crore | period 2024-03-31 | keep True

## 59. NAVINFLUOR p163 value 2,050
- page head: Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended March 31, 2024 / Notes Forming Part of the Consolidated Financial Statements / as at and for the year ended M
- around value: - | 1,365 | October 24, 2016 | October 23, 2026 | 554.40 | 1,825 | 2,050 | March 19, 2018 | March 18, 2028
- parser: label `October 24, 2016 October 23, 2026` | column `March 31, 2023` | unit crore | period 2023-03-31 | page unit crore
- v1+guards: label `Non-convertible debentures due October 23, 2026 - March 31, 2023` | unit crore | period 2023-03-31 | keep True
- v2+guards: label `Share options outstanding at end of year, grant October 24, 2016, expiry October 23, 2026 - March 31, 2023` | unit count | period 2023-03-31 | keep True
