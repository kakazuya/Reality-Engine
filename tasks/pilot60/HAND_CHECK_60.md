# Hand check — 60 pilot instance answers (20 per bucket)

Source rows behind each answer are re-read from chunks_v3 / the live stores. Auto checks flag a wrong entity, evidence after as_of, or no evidence at all.

## 1. MB0001#L — LARGE — Telecommunication
- entity: IDEA(INE669E01016)
- question: AEROFLEX products + close on a date
- grade: ANSWERED | answer: IDEA: close 12.6 on 2026-10-16; annual_report 2026-08-05T13:44:13 p144 ANNUAL REPORT 2025-26: ANNUAL REPORT 2025-26
Corporate
Governance Report
Business Responsibility
and Sustainability Report
Financial
Statements
Directors’ Report &
Management Discussion and Analysis Repo | annual_report 2026-08-05T13:44:13 p178 ANNU
- evidence: 2026-10-19:SERIES:SERIES:IDEA, 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#144, 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#178
- source: ref 2026-10-19:SERIES:SERIES:IDEA
- source: ref 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#144
- source: ref 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#178
- source: ref 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#175
- auto: clean

## 2. MB0002#L — LARGE — Power
- entity: POWERGRID(INE752E01010)
- question: 532627 latest AR: control change
- grade: ANSWERED | answer: POWERGRID: close 296.1 on 2026-03-31; concall 2026-05-25T15:46:13 p16 Opening remarks: So, in terms of innovation and 
technology, is it at par with what is being done globally, or are there some more innovations that 
you are considering to enhance your asset manage
- evidence: 2026-10-19:SERIES:SERIES:POWERGRID, 2026-05-25:EVIDENCE:chunks_v3:sha256:bdb435f515b90513306c5cd40b04f025c9e82fb3fad0a9e8e14f06ed508f14d9#16
- source: ref 2026-10-19:SERIES:SERIES:POWERGRID
- source: ref 2026-05-25:EVIDENCE:chunks_v3:sha256:bdb435f515b90513306c5cd40b04f025c9e82fb3fad0a9e8e14f06ed508f14d9#16
- auto: clean

## 3. MB0008#L — LARGE — Power
- entity: POWERGRID(INE752E01010)
- question: ZENTEC 3-yr price CAGR
- grade: ANSWERED | answer: POWERGRID: 2023-10-03 close 199.6 -> 2026-10-19 close 250.3, return 25.5% (752 sessions), CAGR 7.7% over 3.0y
- evidence: 2026-10-19:SERIES:SERIES:POWERGRID
- source: ref 2026-10-19:SERIES:SERIES:POWERGRID
- auto: clean

## 4. MB0010#L — LARGE — Power
- entity: POWERGRID(INE752E01010)
- question: VINCOFE public shareholding Sep 2026
- grade: ANSWERED | answer: Shares outstanding (paid-up/face value)  = 9,300,600,000 shares (computed, known 2026-08-05); MAJOR SHAREHOLDING GoI - = 51.3 % (deck_figures, known 2026-02-02); MAJOR SHAREHOLDING FIIs - = 24.7 % (deck_figures, known 2026-02-02); POWERGRID: 2026-09-01 close 264.6 -> 2026-09-30 close 260.5, return -1.5% (21 sessions)
- evidence: 2026-08-05:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1708756_05082026105713_WEB.xml, 2026-02-02:FACTS:deck_figures:cb68abaa1fe2807869a67ab05859806978e2cf39e03cc1e770ce260c692beb0d#6, 2026-02-02:FACTS:deck_figures:cb68abaa1fe2807869a67ab05859806978e2cf39e03cc1e770ce260c692beb0d#6
- source: ref 2026-08-05:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1708756_05082026105713_WEB.xml
- source: ref 2026-02-02:FACTS:deck_figures:cb68abaa1fe2807869a67ab05859806978e2cf39e03cc1e770ce260c692beb0d#6
- auto: clean

## 5. MB0022#L — LARGE — Fast Moving Consumer Goods
- entity: HINDUNILVR(INE030A01027)
- question: What is the promoter holding of NSE: BLACKBUCK as of September 2026?
- grade: ANSWERED | answer: Employee Net Promoter Score 2024 = 93.0 % (ar_facts, known 2025-05-29); Remaining stake in Uprising Science Private Limited to be acquired per Share Purchase and Subscription Agreement 2025-01-22 = 9.50 % (ar_facts, known 2025-05-29); Board approved acquisition of 90.5% stake in Uprising Science Private Limited, with a
- evidence: 2025-05-29:FACTS:ar_facts:39621#9, 2025-05-29:FACTS:ar_facts:39621#137, 2025-05-29:FACTS:ar_facts:39621#137
- source: ref 2025-05-29:FACTS:ar_facts:39621#9
- source: ref 2025-05-29:FACTS:ar_facts:39621#137
- source: ref 2025-07-04:FACTS:shp_index:2025-06-30
- auto: clean

## 6. MB0023#L — LARGE — Metals & Mining
- entity: HINDALCO(INE038A01020)
- question: How many manufacturing facilities does Ganesha Ecosphere have, per its investor presentation of 5 August 2026?
- grade: ANSWERED | answer: plants certified as single-use plastic free zones - = 15.0 plants (deck_figures, known 2024-05-24); pilot project for removal of invasive species (non-native plants) - = 2,000 saplings (deck_figures, known 2024-11-11); A pilot project for the removal of invasive species (non-native plants) completed at Utkal - = 20.0 t
- evidence: 2024-05-24:FACTS:deck_figures:ad09aa32bcbd8dbf01049bbbe316887198422b52f6f6b2820c5b30e0d8feb4d1#6, 2024-11-11:FACTS:deck_figures:41ee356083f4f862ca0431b01b979f0c4d12cf96d087fdce8a248a9398017176#8, 2025-02-13:FACTS:deck_figures:d2ffe66e5da05373300f05d0bb87385f6f4b1c83091849cc129fe366b469d988#7
- source: ref 2024-05-24:FACTS:deck_figures:ad09aa32bcbd8dbf01049bbbe316887198422b52f6f6b2820c5b30e0d8feb4d1#6
- source: ref 2024-11-11:FACTS:deck_figures:41ee356083f4f862ca0431b01b979f0c4d12cf96d087fdce8a248a9398017176#8
- source: ref 2025-02-13:FACTS:deck_figures:d2ffe66e5da05373300f05d0bb87385f6f4b1c83091849cc129fe366b469d988#7
- source: ref 2025-07-28:FACTS:ar_facts:39280#66
- auto: clean

## 7. MB0024#L — LARGE — Construction Materials
- entity: GRASIM(INE047A01021)
- question: What are the key products of Chemcon Speciality Chemicals per its investor presentation of 22 May 2026, and whom did it mention as acquired 
- grade: ANSWERED | answer: Revenue from Operations % Change = 15.0 % (deck_figures, known 2026-05-20); Revenue from Operations % Change = 18.0 % (deck_figures, known 2026-05-20); Add/(Less): Tax Expense % Change = 25.0 % (deck_figures, known 2026-05-20); deck 2026-05-20T14:55:04 p19 Chemicals: Chemicals
Earnings Presentation  |  Q4FY26
Chlorine 
- evidence: 2026-05-20:FACTS:deck_figures:79ab74b4ebe3f3afdb87bd5407ca31430d87eb986a83318b45da7cdbd7b9246a#37, 2026-05-20:FACTS:deck_figures:79ab74b4ebe3f3afdb87bd5407ca31430d87eb986a83318b45da7cdbd7b9246a#37, 2026-05-20:FACTS:deck_figures:79ab74b4ebe3f3afdb87bd5407ca31430d87eb986a83318b45da7cdbd7b9246a#37
- source: ref 2026-05-20:FACTS:deck_figures:79ab74b4ebe3f3afdb87bd5407ca31430d87eb986a83318b45da7cdbd7b9246a#37
- auto: clean

## 8. MB0028#L — LARGE — Financial Services
- entity: BAJFINANCE(INE296A01032)
- question: What was the YTD high price of BSE: 532810 in 2026 (value and date)?
- grade: ANSWERED | answer: BAJFINANCE: 2026-01-01 close 973.1 -> 2026-10-19 close 957.4, return -1.6% (196 sessions), high 1,159 (2026-08-05), low 801.5 (2026-03-30), 5 daily closes within 1% of an edge
- evidence: 2026-10-19:SERIES:SERIES:BAJFINANCE
- source: ref 2026-10-19:SERIES:SERIES:BAJFINANCE
- auto: clean

## 9. MB0034#L — LARGE — Telecommunication
- entity: IDEA(INE669E01016)
- question: RELIANCE products + close 16 Oct 2026
- grade: ANSWERED | answer: IDEA: close 12.6 on 2026-10-16; annual_report 2026-08-05T13:44:13 p144 ANNUAL REPORT 2025-26: ANNUAL REPORT 2025-26
Corporate
Governance Report
Business Responsibility
and Sustainability Report
Financial
Statements
Directors’ Report &
Management Discussion and Analysis Repo | annual_report 2026-08-05T13:44:13 p178 ANNU
- evidence: 2026-10-19:SERIES:SERIES:IDEA, 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#144, 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#178
- source: ref 2026-10-19:SERIES:SERIES:IDEA
- source: ref 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#144
- source: ref 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#178
- source: ref 2026-08-05:EVIDENCE:chunks_v3:sha256:cf1fd51c68298a84469783fb3ca3933d3ca466530b171b9cf151dd12d7266eea#175
- auto: clean

## 10. MB0035#L — LARGE — Telecommunication
- entity: IDEA(INE669E01016)
- question: Bhai, KRBL (NSE: KRBL) kya banati hai, aur 16 October 2026 ko NSE par kitne pe close hui? Products aur close dono batao, short mein.
- grade: ANSWERED | answer: Spectrum holdings - = 8,030 MHz (deck_figures, known 2025-09-10); 2024 ET Retail Awards for Vi Shop: Customer Engagement & Experience Initiative - = 2,024 - (deck_figures, known 2025-09-10); Best customer experience strategy for the year (19th CX Strategy Summit & Awards) - = 19.0 th (deck_figures, known 2025-09-10); I
- evidence: 2025-09-10:FACTS:deck_figures:3f41dc6629620d6f2ded8de48c5f01da2ca0f1411687e036cb1fd85158ac473b#4, 2025-09-10:FACTS:deck_figures:3f41dc6629620d6f2ded8de48c5f01da2ca0f1411687e036cb1fd85158ac473b#4, 2025-09-10:FACTS:deck_figures:3f41dc6629620d6f2ded8de48c5f01da2ca0f1411687e036cb1fd85158ac473b#4
- source: ref 2025-09-10:FACTS:deck_figures:3f41dc6629620d6f2ded8de48c5f01da2ca0f1411687e036cb1fd85158ac473b#4
- auto: clean

## 11. MB0071#L — LARGE — Healthcare
- entity: SUNPHARMA(INE044A01036)
- question: What did Jash Engineering (NSE: JASH)'s management say about demand and margins on its 18 August 2026 earnings call, and who said it?
- grade: ANSWERED | answer: Gross margin= (Net Sales – Material Cost) / Net Sales * 100 - = 100.0 - (deck_figures, known 2026-09-22); Margin money/ security against guarantees/ commitments non-current As at March 31, 2019 2019-03-31 = 2.60 ` in Million (ar_facts, known 2020-08-04); Balances held as margin money original maturity more than 12 mont
- evidence: 2026-09-22:FACTS:deck_figures:c2183d9ab5aeb1906a2b7599291831dc870b783350af22018bd0e5a5dc006b35#9, 2020-08-04:FACTS:ar_facts:83904#217, 2020-08-04:FACTS:ar_facts:83904#219
- source: ref 2026-09-22:FACTS:deck_figures:c2183d9ab5aeb1906a2b7599291831dc870b783350af22018bd0e5a5dc006b35#9
- source: ref 2020-08-04:FACTS:ar_facts:83904#217
- source: ref 2020-08-04:FACTS:ar_facts:83904#219
- auto: clean

## 12. MB0079#L — LARGE — Power
- entity: POWERGRID(INE752E01010)
- question: As of 31 July 2026, what had Concord Enviro Systems (NSE: CEWATER)'s management last said on an earnings call about demand and margins?
- grade: ANSWERED | answer: EBITDA-Gross Margin Growth (%) - = 0.00 % (deck_figures, known 2024-07-29); EBITDA-Gross Margin Growth (%) - = -6.00 % (deck_figures, known 2024-07-29); EBITDA-Gross Margin - = 2.00 % (deck_figures, known 2025-08-01); concall 2026-05-25T15:46:13 p8 Opening remarks (cont.): 
 Strategic Drivers Powering Transmission Inv
- evidence: 2024-07-29:FACTS:deck_figures:51d5f7472df4b66548dd58501ec17f43b336756b129dfa944566074ad3a20c41#13, 2024-07-29:FACTS:deck_figures:51d5f7472df4b66548dd58501ec17f43b336756b129dfa944566074ad3a20c41#13, 2025-08-01:FACTS:deck_figures:a7e468d9f22d86b2183acd2022cb962fb5dcc6589526e3c951ae4d76d99c5408#18
- source: ref 2024-07-29:FACTS:deck_figures:51d5f7472df4b66548dd58501ec17f43b336756b129dfa944566074ad3a20c41#13
- source: ref 2025-08-01:FACTS:deck_figures:a7e468d9f22d86b2183acd2022cb962fb5dcc6589526e3c951ae4d76d99c5408#18
- auto: clean

## 13. MB0086#L — LARGE — Construction Materials
- entity: GRASIM(INE047A01021)
- question: What was ACC (NSE: ACC)'s segment revenue for April-June 2026 (Q1 FY2026-27), with the absolute number for each reported segment?
- grade: ANSWERED | answer: India Saree segment consumption - = 10.0 - (deck_figures, known 2022-05-24); India Saree segment consumes fibre - = 10.0 lakh ton (deck_figures, known 2022-05-24); Chemicals segment revenue - = 5.00 YoY (deck_figures, known 2026-02-10); GRASIM: 2026-06-01 close 3,103 -> 2026-06-30 close 3,100, return -0.1% (21 sessions
- evidence: 2022-05-24:FACTS:deck_figures:14e8260ca56bc9d1f10691411a92724f093e8d4cc8a0bfb742ed9c09a8d66aff#18, 2022-05-24:FACTS:deck_figures:14e8260ca56bc9d1f10691411a92724f093e8d4cc8a0bfb742ed9c09a8d66aff#18, 2026-02-10:FACTS:deck_figures:0709a9dea1749f2e8da7517e2ac23e09b0d36a6ee4231007f75e974fc8c57139#23
- source: ref 2022-05-24:FACTS:deck_figures:14e8260ca56bc9d1f10691411a92724f093e8d4cc8a0bfb742ed9c09a8d66aff#18
- source: ref 2026-02-10:FACTS:deck_figures:0709a9dea1749f2e8da7517e2ac23e09b0d36a6ee4231007f75e974fc8c57139#23
- source: ref 2026-05-20:FACTS:deck_figures:79ab74b4ebe3f3afdb87bd5407ca31430d87eb986a83318b45da7cdbd7b9246a#23
- auto: clean

## 14. MB0089#L — LARGE — Financial Services
- entity: BAJFINANCE(INE296A01032)
- question: As of 30 June 2026, what segment revenue had Brainbees Solutions (NSE: FIRSTCRY) reported for Q1FY27?
- grade: ANSWERED | answer: Business segment wise AUM - = 48.0 - (deck_figures, known 2022-01-18); Business segment wise AUM - = 46.0 - (deck_figures, known 2022-04-26); Business segment wise AUM - = 46.0 - (deck_figures, known 2022-07-27); BAJFINANCE: close 1,005 on 2026-06-30
- evidence: 2022-01-18:FACTS:deck_figures:b151efca86c4f0c7abd0ea5f021bd4105daa4c25ff9890f408563e40ac7f4773#3, 2022-04-26:FACTS:deck_figures:831a5667331c55197aa9bc309bada701f98ccc1f257926ec08d78218cab6d841#3, 2022-07-27:FACTS:deck_figures:910a1ca77364fc5d1c32eb0244474e30a7b30041ea8aad554142f27a2de57def#3
- source: ref 2022-01-18:FACTS:deck_figures:b151efca86c4f0c7abd0ea5f021bd4105daa4c25ff9890f408563e40ac7f4773#3
- source: ref 2022-04-26:FACTS:deck_figures:831a5667331c55197aa9bc309bada701f98ccc1f257926ec08d78218cab6d841#3
- source: ref 2022-07-27:FACTS:deck_figures:910a1ca77364fc5d1c32eb0244474e30a7b30041ea8aad554142f27a2de57def#3
- source: ref 2023-01-27:FACTS:deck_figures:34ca38fceb67dcdec68bf62582b8a63358be4585711967a26680ec1da23302a2#20
- auto: clean

## 15. MB0096#L — LARGE — Financial Services
- entity: BAJFINANCE(INE296A01032)
- question: What was IndusInd Bank (NSE: INDUSINDBK)'s net NPA % for April-June 2026 (Q1 FY2026-27), and which XBRL concept and filing carry it?
- grade: ANSWERED | answer: Net NPA - = 0.12 % (deck_figures, known 2026-07-30); Consolidated net NPA ratio 31 March 2024 = 0.37 % (ar_facts, known 2024-06-26); Consolidated Net NPA 31 March 2024 = 0.37 % (ar_facts, known 2024-06-26); BAJFINANCE: 2026-06-01 close 889.0 -> 2026-06-30 close 1,005, return 13.0% (21 sessions)
- evidence: 2026-07-30:FACTS:deck_figures:0ad80c00b39d6ba036b6fc6356f3626497994eba470af52d958e151680b9044f#16, 2024-06-26:FACTS:ar_facts:13887#43, 2024-06-26:FACTS:ar_facts:13887#119
- source: ref 2026-07-30:FACTS:deck_figures:0ad80c00b39d6ba036b6fc6356f3626497994eba470af52d958e151680b9044f#16
- source: ref 2024-06-26:FACTS:ar_facts:13887#43
- source: ref 2024-06-26:FACTS:ar_facts:13887#119
- source: ref 2024-06-26:FACTS:ar_facts:13887#121
- auto: clean

## 16. MB0099#L — LARGE — Financial Services
- entity: BAJFINANCE(INE296A01032)
- question: As of 30 June 2026, what net NPA % had The Jammu & Kashmir Bank (NSE: J&KBANK) last reported for Q1FY27?
- grade: ANSWERED | answer: Net NPA - = 0.41 % (deck_figures, known 2026-04-29); Consolidated net NPA ratio 31 March 2024 = 0.37 % (ar_facts, known 2024-06-26); Consolidated Net NPA 31 March 2024 = 0.37 % (ar_facts, known 2024-06-26); BAJFINANCE: close 1,005 on 2026-06-30
- evidence: 2026-04-29:FACTS:deck_figures:c6bba06190fefaa0e07dd13a2a02db9b05c2ad2cc96f5779b8378685f5052086#21, 2024-06-26:FACTS:ar_facts:13887#43, 2024-06-26:FACTS:ar_facts:13887#119
- source: ref 2026-04-29:FACTS:deck_figures:c6bba06190fefaa0e07dd13a2a02db9b05c2ad2cc96f5779b8378685f5052086#21
- source: ref 2024-06-26:FACTS:ar_facts:13887#43
- source: ref 2024-06-26:FACTS:ar_facts:13887#119
- source: ref 2024-06-26:FACTS:ar_facts:13887#121
- auto: clean

## 17. MB0109#L — LARGE — Automobile and Auto Components
- entity: BOSCHLTD(INE323A01026)
- question: As of 30 June 2026, what was GRM Overseas (NSE: GRMOVER)'s 3-year adjusted price CAGR?
- grade: ANSWERED | answer: BOSCHLTD: close 39,900 on 2026-06-30
- evidence: 2026-06-30:SERIES:SERIES:BOSCHLTD
- source: ref 2026-06-30:SERIES:SERIES:BOSCHLTD
- auto: clean

## 18. MB0110#L — LARGE — Telecommunication
- entity: IDEA(INE669E01016)
- question: What was InfoBeans Technologies (NSE: INFOBEAN)'s 3-year adjusted price CAGR across its corporate action? If adjusted prices are missing, an
- grade: ANSWERED | answer: IDEA: 2023-10-03 close 12.0 -> 2026-10-19 close 12.3, return 2.3% (752 sessions), CAGR 0.8% over 3.0y
- evidence: 2026-10-19:SERIES:SERIES:IDEA
- source: ref 2026-10-19:SERIES:SERIES:IDEA
- auto: clean

## 19. MB0121#L — LARGE — Chemicals
- entity: PIDILITIND(INE318A01026)
- question: What is Fertilizers and Chemicals Travancore (NSE: FACT)'s public shareholding as of Sep 2026?
- grade: ANSWERED | answer: Shares outstanding (paid-up/face value)  = 1,017,800,000 shares (computed, known 2026-08-04); Promoters - = 69.3 % (deck_figures, known 2026-02-03); shareholding in Cipy Poly Urethanes Pvt. Ltd. (CIPY) - before 22nd April, 2021 = 70.0 % (deck_figures, known 2021-05-13); PIDILITIND: 2026-09-01 close 1,644 -> 2026-09-30 
- evidence: 2026-08-04:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1707695_04082026053354_WEB.xml, 2026-02-03:FACTS:deck_figures:ebfab2066712454b90fda3e9f2b00af71b214e562ede14fe771d722f8baab5ff#39, 2021-05-13:FACTS:deck_figures:aa438b5ca10d1ac74982a914ab3cc48e232ba4f130cbf317de1e25df6b891856#10
- source: ref 2026-08-04:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1707695_04082026053354_WEB.xml
- source: ref 2026-02-03:FACTS:deck_figures:ebfab2066712454b90fda3e9f2b00af71b214e562ede14fe771d722f8baab5ff#39
- source: ref 2021-05-13:FACTS:deck_figures:aa438b5ca10d1ac74982a914ab3cc48e232ba4f130cbf317de1e25df6b891856#10
- auto: clean

## 20. MB0122#L — LARGE — Power
- entity: POWERGRID(INE752E01010)
- question: What is NHPC (NSE: NHPC)'s public shareholding as of Sep 2026?
- grade: ANSWERED | answer: Shares outstanding (paid-up/face value)  = 9,300,600,000 shares (computed, known 2026-08-05); MAJOR SHAREHOLDING GoI - = 51.3 % (deck_figures, known 2026-02-02); MAJOR SHAREHOLDING FIIs - = 24.7 % (deck_figures, known 2026-02-02); POWERGRID: 2026-09-01 close 264.6 -> 2026-09-30 close 260.5, return -1.5% (21 sessions)
- evidence: 2026-08-05:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1708756_05082026105713_WEB.xml, 2026-02-02:FACTS:deck_figures:cb68abaa1fe2807869a67ab05859806978e2cf39e03cc1e770ce260c692beb0d#6, 2026-02-02:FACTS:deck_figures:cb68abaa1fe2807869a67ab05859806978e2cf39e03cc1e770ce260c692beb0d#6
- source: ref 2026-08-05:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1708756_05082026105713_WEB.xml
- source: ref 2026-02-02:FACTS:deck_figures:cb68abaa1fe2807869a67ab05859806978e2cf39e03cc1e770ce260c692beb0d#6
- auto: clean

## 21. MB0397#MS — MID-SMALL — Capital Goods
- entity: APLAPOLLO(INE702C01027)
- question: Welcorp filed an intimation about its credit rating. Who took the action and when was the press release issued?
- grade: ANSWERED | answer: APLAPOLLO: 2026-10-01 close 2,116 -> 2026-10-19 close 2,145, return 1.4% (12 sessions)
- evidence: 2026-10-20:SERIES:SERIES:APLAPOLLO
- source: ref 2026-10-20:SERIES:SERIES:APLAPOLLO
- auto: clean

## 22. MB0441#MS — MID-SMALL — Capital Goods
- entity: APLAPOLLO(INE702C01027)
- question: BHEL 4 Jun 2024 volume and delivery
- grade: ANSWERED | answer: APLAPOLLO: close 1,434 on 2024-06-04
- evidence: 2024-06-04:SERIES:SERIES:APLAPOLLO
- source: ref 2024-06-04:SERIES:SERIES:APLAPOLLO
- auto: clean

## 23. MB0577#MS — MID-SMALL — Capital Goods
- entity: APLAPOLLO(INE702C01027)
- question: What was the promoter holding in Titagarh last quarter? terse: TITAGARH promoter %
- grade: ANSWERED | answer: Promoter Total % holding FY22 = 34.5 % (ar_facts, known 2023-08-17); Apollo Mart (wholly owned subsidiary) bought 1,000,000 Shankara shares at Rs755.00 each from promoters via secondary market FY22 = 75.7 Rs crore (ar_facts, known 2023-08-17); Apollo Metalex Private Limited - % Shareholding FY23 = 100.0 % (ar_facts, kn
- evidence: 2023-08-17:FACTS:ar_facts:9534#215, 2023-08-17:FACTS:ar_facts:9534#290, 2023-08-17:FACTS:ar_facts:9534#107
- source: ref 2023-08-17:FACTS:ar_facts:9534#215
- source: ref 2023-08-17:FACTS:ar_facts:9534#290
- source: ref 2023-08-17:FACTS:ar_facts:9534#107
- source: ref 2023-08-17:FACTS:ar_facts:9534#127
- auto: clean

## 24. MB0890#MS — MID-SMALL — Consumer Services
- entity: INDHOTEL(INE053A01029)
- question: Zomato is now Eternal. Does my old Zomato holding map to the same ISIN, and how does the price history handle the name change?
- grade: ANSWERED | answer: Shareholding in Piem Hotels (existing) - = 51.6 % (deck_figures, known 2023-10-27); Resultant shareholding in Piem Hotels Ltd (lower bound) - = 51.6 % (deck_figures, known 2023-10-27); Resultant shareholding in Piem Hotels Ltd (upper bound) - = 58.6 % (deck_figures, known 2023-10-27)
- evidence: 2023-10-27:FACTS:deck_figures:35f12bfd0c2dde66374bafef92519ddc5fba1db27aff1012f809051117ba64a6#51, 2023-10-27:FACTS:deck_figures:35f12bfd0c2dde66374bafef92519ddc5fba1db27aff1012f809051117ba64a6#51, 2023-10-27:FACTS:deck_figures:35f12bfd0c2dde66374bafef92519ddc5fba1db27aff1012f809051117ba64a6#51
- source: ref 2023-10-27:FACTS:deck_figures:35f12bfd0c2dde66374bafef92519ddc5fba1db27aff1012f809051117ba64a6#51
- source: ref 2026-06-04:FACTS:ar_facts:42533#17
- auto: clean

## 25. MB0899#MS — MID-SMALL — Capital Goods
- entity: APLAPOLLO(INE702C01027)
- question: Suzlon has been hitting upper circuits repeatedly. Which band applies now, what was the last base-price reset, and when did it last open nor
- grade: ANSWERED | answer: Capex - = -6,520 Rs Mn (deck_figures, known 2026-05-02); Cost (per sq ft in Homes) - = 41.0 - (deck_figures, known 2026-05-02); Cost (per sq ft in Homes) - = 23.0 - (deck_figures, known 2026-05-02); APLAPOLLO: close 2,145 on 2026-10-19
- evidence: 2026-05-02:FACTS:deck_figures:5af7baa9f4f4088f74dba6999cd25d724ce9c4d106635203406d912ba253c4dd#18, 2026-05-02:FACTS:deck_figures:5af7baa9f4f4088f74dba6999cd25d724ce9c4d106635203406d912ba253c4dd#25, 2026-05-02:FACTS:deck_figures:5af7baa9f4f4088f74dba6999cd25d724ce9c4d106635203406d912ba253c4dd#25
- source: ref 2026-05-02:FACTS:deck_figures:5af7baa9f4f4088f74dba6999cd25d724ce9c4d106635203406d912ba253c4dd#18
- source: ref 2026-05-02:FACTS:deck_figures:5af7baa9f4f4088f74dba6999cd25d724ce9c4d106635203406d912ba253c4dd#25
- auto: clean

## 26. MB0900#MS — MID-SMALL — Telecommunication
- entity: TEJASNET(INE010J01012)
- question: Vodafone Idea trades in a narrow band. Is the 5% limit still on, and how does delivery behave on the days it touches the band?
- grade: ANSWERED | answer: TEJASNET: close 453.2 on 2026-10-19
- evidence: 2026-10-19:SERIES:SERIES:TEJASNET
- source: ref 2026-10-19:SERIES:SERIES:TEJASNET
- auto: clean

## 27. MB0901#MS — MID-SMALL — Power
- entity: NLCINDIA(INE589A01014)
- question: Jaiprakash Power: did the band change after the last base-price reset, and did the change coincide with the volume spike?
- grade: ANSWERED | answer: NLCINDIA: close 244.3 on 2026-10-19
- evidence: 2026-10-19:SERIES:SERIES:NLCINDIA
- source: ref 2026-10-19:SERIES:SERIES:NLCINDIA
- auto: clean

## 28. MB0916#MS — MID-SMALL — Financial Services
- entity: ANANDRATHI(INE463V01026)
- question: SBI: is the recent DII accumulation visible in the shareholding pattern, or only in the daily flow prints?
- grade: ANSWERED | answer: Profit After Tax - = 29.0 Y/Y (deck_figures, known 2026-01-12); Visakhapatnam - = 18.0 - (deck_figures, known 2026-04-09); This Is a Business of Patience and Time, Not Speed - = 2.00 - (deck_figures, known 2026-07-09)
- evidence: 2026-01-12:FACTS:deck_figures:1cf25decbbeef17042285714513e4114532554a5972d598bd52ae9802e8016a1#8, 2026-04-09:FACTS:deck_figures:5d9a6ba83df43dac214621e4001e0fb4bb7a27052950416deea4b24ee8786f3e#33, 2026-07-09:FACTS:deck_figures:1f1b4377c51b692180f87ff25c137ff1598c648ddc924d8f44804aaf1a1c063a#4
- source: ref 2026-01-12:FACTS:deck_figures:1cf25decbbeef17042285714513e4114532554a5972d598bd52ae9802e8016a1#8
- source: ref 2026-04-09:FACTS:deck_figures:5d9a6ba83df43dac214621e4001e0fb4bb7a27052950416deea4b24ee8786f3e#33
- source: ref 2026-07-09:FACTS:deck_figures:1f1b4377c51b692180f87ff25c137ff1598c648ddc924d8f44804aaf1a1c063a#4
- source: ref 2026-07-09:FACTS:deck_figures:1f1b4377c51b692180f87ff25c137ff1598c648ddc924d8f44804aaf1a1c063a#7
- auto: clean

## 29. MB0944#MS — MID-SMALL — Consumer Services
- entity: INDHOTEL(INE053A01029)
- question: When Eternal entered the Nifty 50, how much passive buying did that imply, and did the stock move before or after the effective date?
- grade: ANSWERED | answer: Nifty 50: close 22,889 on 2026-10-19 (-1.11% on the day)
- evidence: 2026-10-19:SERIES:SERIES:Nifty 50
- source: ref 2026-10-19:SERIES:SERIES:Nifty 50
- auto: clean

## 30. MB0946#MS — MID-SMALL — Capital Goods
- entity: APLAPOLLO(INE702C01027)
- question: HAL's weight in the Nifty 50 has changed with the stock. How much of the trading volume on rebalance days is index-driven?
- grade: ANSWERED | answer: Nifty 50: close 22,889 on 2026-10-19 (-1.11% on the day); deck 2026-05-02T16:10:06 p32 APL Apollo’s: ●
Construction sector contributes 30% of 
direct and indirect Co2 emissions
●
Structural steel is preferred for steel 
buildings because steel is
○
Infinitely recyclable
○
Easy to  | deck 2026-08-01T15:13:06 p32 ESG- DJ
- evidence: 2026-10-19:SERIES:SERIES:Nifty 50, 2026-05-02:EVIDENCE:chunks_v3:sha256:5af7baa9f4f4088f74dba6999cd25d724ce9c4d106635203406d912ba253c4dd#32, 2026-08-01:EVIDENCE:chunks_v3:sha256:46cfe8b723673da1f991cfb03a69f06027d4c64ef8e3fe799250bb64cec3ca56#32
- source: ref 2026-10-19:SERIES:SERIES:Nifty 50
- source: ref 2026-05-02:EVIDENCE:chunks_v3:sha256:5af7baa9f4f4088f74dba6999cd25d724ce9c4d106635203406d912ba253c4dd#32
- source: ref 2026-08-01:EVIDENCE:chunks_v3:sha256:46cfe8b723673da1f991cfb03a69f06027d4c64ef8e3fe799250bb64cec3ca56#32
- source: ref 2026-08-05:EVIDENCE:chunks_v3:sha256:69966017ee6ba16ad2ce2efd89fb9b51001d56dddcd3cc0ae99ef00f1b844661#14
- auto: clean

## 31. MB0951#MS — MID-SMALL — Fast Moving Consumer Goods
- entity: UBL(INE686F01025)
- question: Nestle India: is the last five years' growth from volume or from price and mix, and does that change the moat case?
- grade: ANSWERED | answer: UBL: close 918.9 on 2020-03-31; concall 2026-08-10T14:56:46 p0 Transcript: Registered & Corporate Office: UB Tower, UB City, #24, Vittal Mallya Road, Bengaluru – 560 001. INDIA 
Tel: (91-80) 4565 5000, Email: ublcorporate@ubmail.com, Web Site: www.unitedb | concall 2026-05-11T10:57:10 p0 Transcript: Registered & Corpor
- evidence: 2026-10-19:SERIES:SERIES:UBL, 2026-08-10:EVIDENCE:chunks_v3:sha256:c8772e0269dca28afba4c743b08a354cb16021e5301de319b700f485c5509f4e#0, 2026-05-11:EVIDENCE:chunks_v3:sha256:8298b21c6eb065dd5bef790383446aa3934a537183f1a1b7859e9c812344add8#0
- source: ref 2026-10-19:SERIES:SERIES:UBL
- source: ref 2026-08-10:EVIDENCE:chunks_v3:sha256:c8772e0269dca28afba4c743b08a354cb16021e5301de319b700f485c5509f4e#0
- source: ref 2026-05-11:EVIDENCE:chunks_v3:sha256:8298b21c6eb065dd5bef790383446aa3934a537183f1a1b7859e9c812344add8#0
- source: ref 2026-08-04:EVIDENCE:chunks_v3:sha256:ed1cbfb3c6cbdb2c000d47c34e4579a45398254c617fe8e906a450a5c98fd6ac#1
- auto: clean

## 32. MB0955#MS — MID-SMALL — Metals & Mining
- entity: SAIL(INE114A01011)
- question: JSW Steel: the last capex round was large. What incremental ROIC has it earned so far, and how far is it from the cost of capital?
- grade: ANSWERED | answer: People provided specialized/basic healthcare in vicinity 2011-2022 = 177.0 people (ar_facts, known 2022-09-19); Basic Earnings Loss Per Share From Continuing And Discontinued Operations 2022-03-31 = 29.1 INRPerShare (results_xbrl, known 2022-05-24); Basic Earnings Loss Per Share From Continuing And Discontinued Operati
- evidence: 2022-09-19:FACTS:ar_facts:75007#54, 2022-05-24:FACTS:results_xbrl:INDAS_85223_659637_24052022064939_WEB.xml, 2022-05-24:FACTS:results_xbrl:INDAS_85223_659637_24052022064939_WEB.xml
- source: ref 2022-09-19:FACTS:ar_facts:75007#54
- source: ref 2022-05-24:FACTS:results_xbrl:INDAS_85223_659637_24052022064939_WEB.xml
- auto: clean

## 33. MB0956#MS — MID-SMALL — Capital Goods
- entity: APLAPOLLO(INE702C01027)
- question: Polycab: does the ROIC still clear the cost of capital after the working-capital build, and what would a demand slowdown do to it?
- grade: ANSWERED | answer: APLAPOLLO: close 914.6 on 2022-03-31
- evidence: 2026-10-19:SERIES:SERIES:APLAPOLLO
- source: ref 2026-10-19:SERIES:SERIES:APLAPOLLO
- auto: clean

## 34. MB0957#MS — MID-SMALL — Capital Goods
- entity: APLAPOLLO(INE702C01027)
- question: ABB India: the margin is at a record. Is the ROIC being earned on new capacity or on a cyclical order book?
- grade: ANSWERED | answer: Heavy structural tube demand FY22 = 0.10 tonnes (ar_facts, known 2022-08-23); Project Visibility Area FY22 = 20.0 sq.ft. (ar_facts, known 2022-08-23); Project Visibility FY22 = 30.0 Projects (ar_facts, known 2022-08-23)
- evidence: 2022-08-23:FACTS:ar_facts:9535#11, 2022-08-23:FACTS:ar_facts:9535#11, 2022-08-23:FACTS:ar_facts:9535#11
- source: ref 2022-08-23:FACTS:ar_facts:9535#11
- auto: clean

## 35. MB0961#MS — MID-SMALL — Financial Services
- entity: ANANDRATHI(INE463V01026)
- question: HDFC Bank has never bought back stock. Is retained capital earning above the cost of equity, and should the payout change?
- grade: ANSWERED | answer: annual_report 2026-04-27T20:18:06 p260 CIN : L67120MH1995PLC086696: CIN : L67120MH1995PLC086696 

Notes to Ind AS Consolidated Financial Statements 
For the year ended March 31, 2026
42	 Pursuant to approval given by its shareholders vide postal ba | annual_report 2026-04-27T20:18:06 p214 CIN : L67120MH1995PLC086696: C
- evidence: 2026-04-27:EVIDENCE:chunks_v3:sha256:bb4949419a4681baae6ef532893e8b484f4c0dbd8ae8347ee146f38581b1edc3#260, 2026-04-27:EVIDENCE:chunks_v3:sha256:bb4949419a4681baae6ef532893e8b484f4c0dbd8ae8347ee146f38581b1edc3#214, 2026-04-27:EVIDENCE:chunks_v3:sha256:bb4949419a4681baae6ef532893e8b484f4c0dbd8ae8347ee146f38581b1edc3#213
- source: ref 2026-04-27:EVIDENCE:chunks_v3:sha256:bb4949419a4681baae6ef532893e8b484f4c0dbd8ae8347ee146f38581b1edc3#260
- source: ref 2026-04-27:EVIDENCE:chunks_v3:sha256:bb4949419a4681baae6ef532893e8b484f4c0dbd8ae8347ee146f38581b1edc3#214
- source: ref 2026-04-27:EVIDENCE:chunks_v3:sha256:bb4949419a4681baae6ef532893e8b484f4c0dbd8ae8347ee146f38581b1edc3#213
- auto: clean

## 36. MB0963#MS — MID-SMALL — Automobile and Auto Components
- entity: TMPV(INE155A01022)
- question: Tata Motors PV: where exactly is the EV and JLR capex going, and what return has the last cycle produced?
- grade: ANSWERED | answer: Basic Earnings Loss Per Share From Continuing And Discontinued Operations 2022-03-31 = -3.64 INRPerShare (results_xbrl, known 2022-05-13); Basic Earnings Loss Per Share From Continuing And Discontinued Operations 2022-03-31 = 1.07 INRPerShare (results_xbrl, known 2022-05-13); Basic Earnings Loss Per Share From Continui
- evidence: 2022-05-13:FACTS:results_xbrl:INDAS_84383_653961_13052022125921_WEB.xml, 2022-05-13:FACTS:results_xbrl:INDAS_84383_653961_13052022125921_WEB.xml, 2022-05-13:FACTS:results_xbrl:INDAS_84383_653961_13052022125921_WEB.xml
- source: ref 2022-05-13:FACTS:results_xbrl:INDAS_84383_653961_13052022125921_WEB.xml
- auto: clean

## 37. MB0964#MS — MID-SMALL — Metals & Mining
- entity: SAIL(INE114A01011)
- question: Adani Enterprises: do receivables and inventory growth run ahead of revenue, and what does the cash-conversion ratio say?
- grade: ANSWERED | answer: Adjustments For Dividend Income 2022-03-31 = 1,929,900,000 INR (results_xbrl, known 2022-05-24); Adjustments For Interest Income 2022-03-31 = 2,791,100,000 INR (results_xbrl, known 2022-05-24); Comprehensive Income For The Period 2022-03-31 = 119,505,900,000 INR (results_xbrl, known 2022-05-24); annual_report 2026-09-0
- evidence: 2022-05-24:FACTS:results_xbrl:INDAS_85223_659637_24052022064939_WEB.xml, 2022-05-24:FACTS:results_xbrl:INDAS_85223_659637_24052022064939_WEB.xml, 2022-05-24:FACTS:results_xbrl:INDAS_85223_659637_24052022064939_WEB.xml
- source: ref 2022-05-24:FACTS:results_xbrl:INDAS_85223_659637_24052022064939_WEB.xml
- auto: clean

## 38. MB0966#MS — MID-SMALL — Telecommunication
- entity: TEJASNET(INE010J01012)
- question: Vodafone Idea: how are the spectrum liabilities accounted for, and do the interest and amortisation assumptions flatter the loss?
- grade: ANSWERED | answer: Basic Earnings Loss Per Share From Continuing And Discontinued Operations 2024-03-31 = 4.83 INRPerShare (results_xbrl, known 2024-04-23); Basic Earnings Loss Per Share From Continuing And Discontinued Operations 2024-03-31 = 9.34 INRPerShare (results_xbrl, known 2024-04-23); Basic Earnings Loss Per Share From Continuin
- evidence: 2024-04-23:FACTS:results_xbrl:INDAS_104646_1106546_23042024050459.xml, 2024-04-23:FACTS:results_xbrl:INDAS_104646_1106546_23042024050459.xml, 2024-04-23:FACTS:results_xbrl:INDAS_104646_1106546_23042024050459.xml
- source: ref 2024-04-23:FACTS:results_xbrl:INDAS_104646_1106546_23042024050459.xml
- auto: clean

## 39. MB0968#MS — MID-SMALL — Financial Services
- entity: ANANDRATHI(INE463V01026)
- question: Yes Bank: are provisions keeping pace with the stressed book, and how much of the recovery is write-back rather than operating profit?
- grade: ANSWERED | answer: Profit Before Exceptional Items And Tax 2022-03-31 = 1,676,717,000 INR (results_xbrl, known 2022-04-13); Profit Before Exceptional Items And Tax 2022-03-31 = 440,777,000 INR (results_xbrl, known 2022-04-13); Profit Before Tax 2022-03-31 = 1,676,717,000 INR (results_xbrl, known 2022-04-13)
- evidence: 2022-04-13:FACTS:results_xbrl:INDAS_83513_634149_13042022050442_WEB.xml, 2022-04-13:FACTS:results_xbrl:INDAS_83513_634149_13042022050442_WEB.xml, 2022-04-13:FACTS:results_xbrl:INDAS_83513_634149_13042022050442_WEB.xml
- source: ref 2022-04-13:FACTS:results_xbrl:INDAS_83513_634149_13042022050442_WEB.xml
- auto: clean

## 40. MB0970#MS — MID-SMALL — Consumer Durables
- entity: KALYANKJIL(INE303R01014)
- question: Dixon: the margin guidance has been repeatedly cut. Which call first lowered it, and what did the market do after?
- grade: ANSWERED | answer: PBT margin FY22 = 2.80 % (ar_facts, known 2023-07-19); Other operating revenue - interest income from margin money deposits FY22 = 174.3 Rs million (ar_facts, known 2023-07-19); Interest income from margin money deposits (other operating revenue) FY22 = 180.7 Rs million (ar_facts, known 2023-07-19); concall 2026-08-08T
- evidence: 2023-07-19:FACTS:ar_facts:48488#15, 2023-07-19:FACTS:ar_facts:48488#71, 2023-07-19:FACTS:ar_facts:48488#97
- source: ref 2023-07-19:FACTS:ar_facts:48488#15
- source: ref 2023-07-19:FACTS:ar_facts:48488#71
- source: ref 2023-07-19:FACTS:ar_facts:48488#97
- auto: clean

## 41. MB0530#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: KEI's Sanand phase 1 was late by about six months and commissioned in December 2025. Did the company meet its own revised date?
- grade: ANSWERED | answer: HEGAM: close 542.4 on 2026-03-31
- evidence: 2026-10-07:SERIES:SERIES:HEGAM
- source: ref 2026-10-07:SERIES:SERIES:HEGAM
- auto: clean

## 42. MB0621#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: How much of Titagarh does FII money own right now?
- grade: ANSWERED | answer: HEGAM: 2026-07-28 close 651.0 -> 2026-10-19 close 219.1, return -66.3% (58 sessions)
- evidence: 2026-10-27:SERIES:SERIES:HEGAM
- source: ref 2026-10-27:SERIES:SERIES:HEGAM
- auto: clean

## 43. MB0863#MI — MICRO — General Diversified
- entity: AURUM(INE898S01029)
- question: IDBI Bank stake sale: is the spread worth it?
- grade: ANSWERED | answer: Promoter holding change (pp) 2026-06-30 -> 2026-09-29 = -9.80 pp (computed, known 2026-09-30); total shareholding in Aurum PropTech - = 24.9 - (deck_figures, known 2026-07-21); Promoter holding % 2025-09-30 = 47.0 % (shp_index, known 2026-03-13); AURUM: close 213.9 on 2026-10-23; annual_report 2026-08-26T19:22:47 p32 C
- evidence: 2026-09-30:FACTS:computed:promoter_change, 2026-07-21:FACTS:deck_figures:5f95c072fb72e0d414a8ebba9ceb474cd1c40594b2cf11bd5d122790a3391e07#9, 2026-03-13:FACTS:shp_index:2025-09-30
- source: ref 2026-09-30:FACTS:computed:promoter_change
- source: ref 2026-07-21:FACTS:deck_figures:5f95c072fb72e0d414a8ebba9ceb474cd1c40594b2cf11bd5d122790a3391e07#9
- source: ref 2026-03-13:FACTS:shp_index:2025-09-30
- auto: clean

## 44. MB1060#MI — MICRO — Other
- entity: (INE562X01013)
- question: HDFC Bank futures are at a premium to spot into expiry. Is the basis widening, and what has that meant for the stock after expiry?
- grade: ANSWERED | answer: Experience - = 17.0 years (deck_figures, known 2026-02-20); Experience - = 35.0 years (deck_figures, known 2026-02-20); Experience - = 17.0 years (deck_figures, known 2026-02-20)
- evidence: 2026-02-20:FACTS:deck_figures:0a625a73959a04ae2ae28de059a088db2818a64447fdfe4449ed5be65efb0337#7, 2026-02-20:FACTS:deck_figures:0a625a73959a04ae2ae28de059a088db2818a64447fdfe4449ed5be65efb0337#7, 2026-02-20:FACTS:deck_figures:0a625a73959a04ae2ae28de059a088db2818a64447fdfe4449ed5be65efb0337#7
- source: ref 2026-02-20:FACTS:deck_figures:0a625a73959a04ae2ae28de059a088db2818a64447fdfe4449ed5be65efb0337#7
- auto: clean

## 45. MB1061#MI — MICRO — Unclassified
- entity: AGVENTURES(INE321D01016)
- question: SBI saw a large OI addition at a strike above spot. Is that a ceiling the market expects, or a hedge?
- grade: ANSWERED | answer: Mr. Arvind Goenka - Experience - = 30.0 years (deck_figures, known 2024-05-24); Mr. Vijay Sabbarwal - Experience - = 25.0 years (deck_figures, known 2024-05-24); Mr. Muneesh Batta - Experience - = 20.0 years (deck_figures, known 2024-05-24); AGVENTURES: close 120.5 on 2026-09-24; annual_report 2025-07-04T19:20:14 p48 D
- evidence: 2024-05-24:FACTS:deck_figures:9680cc63dd6ae8ec5c5f126d858073978f75fc243b67f05a280e5299c360f1c0#24, 2024-05-24:FACTS:deck_figures:9680cc63dd6ae8ec5c5f126d858073978f75fc243b67f05a280e5299c360f1c0#24, 2024-05-24:FACTS:deck_figures:9680cc63dd6ae8ec5c5f126d858073978f75fc243b67f05a280e5299c360f1c0#24
- source: ref 2024-05-24:FACTS:deck_figures:9680cc63dd6ae8ec5c5f126d858073978f75fc243b67f05a280e5299c360f1c0#24
- source: ref 2025-07-04:FACTS:ar_facts:63409#16
- auto: clean

## 46. MB1062#MI — MICRO — General Diversified
- entity: ASHIANA(INE365D01021)
- question: Bajaj Finance: did shorts cover into the recent rally, and how much OI is left going into results?
- grade: ANSWERED | answer: ASHIANA: close 299.4 on 2025-09-30
- evidence: 2026-09-24:SERIES:SERIES:ASHIANA
- source: ref 2026-09-24:SERIES:SERIES:ASHIANA
- auto: clean

## 47. MB1063#MI — MICRO — Unclassified
- entity: UFBL(INE382M01027)
- question: ICICI Bank's rollover was lower than last expiry. Does that mean traders are exiting, or just moving to the next series early?
- grade: ANSWERED | answer: UFBL: close 723.0 on 2026-09-24; concall 2026-08-11T20:21:34 p14 Q&A: Ankit Gupta: 
Congratulations for great set of numbers. So, Rahul, on the gross margin front, if we have seen 
inflation, we are focusing more on Big Buffet, we are focusing more o | concall 2026-08-11T20:21:34 p12 Q&A (cont.) · Q: Congratulations on
- evidence: 2026-09-24:SERIES:SERIES:UFBL, 2026-08-11:EVIDENCE:chunks_v3:sha256:013cba2c1bffd83647eeffb2089d4e0d30094f1db7a3b9904ea3bd2b53dd1350#14, 2026-08-11:EVIDENCE:chunks_v3:sha256:013cba2c1bffd83647eeffb2089d4e0d30094f1db7a3b9904ea3bd2b53dd1350#12
- source: ref 2026-09-24:SERIES:SERIES:UFBL
- source: ref 2026-08-11:EVIDENCE:chunks_v3:sha256:013cba2c1bffd83647eeffb2089d4e0d30094f1db7a3b9904ea3bd2b53dd1350#14
- source: ref 2026-08-11:EVIDENCE:chunks_v3:sha256:013cba2c1bffd83647eeffb2089d4e0d30094f1db7a3b9904ea3bd2b53dd1350#12
- source: ref 2026-05-19:EVIDENCE:chunks_v3:sha256:ecd74dfe6bcf55d9a0eca3344b4c7a6e94c9fcc927a4bced3d0b5577710ead8e#13
- auto: clean

## 48. MB0397#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: Welcorp filed an intimation about its credit rating. Who took the action and when was the press release issued?
- grade: ANSWERED | answer: HEGAM: 2026-10-01 close 239.3 -> 2026-10-19 close 219.1, return -8.4% (12 sessions)
- evidence: 2026-10-20:SERIES:SERIES:HEGAM
- source: ref 2026-10-20:SERIES:SERIES:HEGAM
- auto: clean

## 49. MB0441#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: BHEL 4 Jun 2024 volume and delivery
- grade: ANSWERED | answer: HEGAM: close 397.5 on 2024-06-04
- evidence: 2024-06-04:SERIES:SERIES:HEGAM
- source: ref 2024-06-04:SERIES:SERIES:HEGAM
- auto: clean

## 50. MB0577#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: What was the promoter holding in Titagarh last quarter? terse: TITAGARH promoter %
- grade: ANSWERED | answer: Nivedan Vanijya Niyojan Ltd shareholding change (66,684 shares / 0.17% in FY22 to 0 in FY23) FY23 = 66,684 number (ar_facts, known 2024-06-28); Equity shares held by Non-Executive Director Shri Jayant Davar FY24 = 4.00 number (ar_facts, known 2024-06-28); Equity shares held by Non-Executive Director Shri Riju Jhunjhunw
- evidence: 2024-06-28:FACTS:ar_facts:38330#88, 2024-06-28:FACTS:ar_facts:38330#36, 2024-06-28:FACTS:ar_facts:38330#36
- source: ref 2024-06-28:FACTS:ar_facts:38330#88
- source: ref 2024-06-28:FACTS:ar_facts:38330#36
- auto: clean

## 51. MB0890#MI — MICRO — Unclassified
- entity: ASAHISONG(INE228I01012)
- question: Zomato is now Eternal. Does my old Zomato holding map to the same ISIN, and how does the price history handle the name change?
- grade: ANSWERED | answer: Promoter holding change (pp) 2026-06-30 -> 2026-09-30 = 0.08 pp (computed, known 2026-10-16); Mr. Jagdish Sheth, the current promoter of Atlas Life Sciences Private Limited, will serve as a Joint Managing Director until March 2025 alongside Mr. Arjun Jaykrishna who will serve as the Managing Director. - = 2,025 year (d
- evidence: 2026-10-16:FACTS:computed:promoter_change, 2022-08-17:FACTS:deck_figures:2ebbbd8ee0c8ef9724a677d2c1fde24f9d0ddd0104ff64936b3482a04a10ee3f#19, 2025-08-20:FACTS:ar_facts:10840#23
- source: ref 2026-10-16:FACTS:computed:promoter_change
- source: ref 2022-08-17:FACTS:deck_figures:2ebbbd8ee0c8ef9724a677d2c1fde24f9d0ddd0104ff64936b3482a04a10ee3f#19
- source: ref 2025-08-20:FACTS:ar_facts:10840#23
- source: ref 2025-10-11:FACTS:shp_index:2025-09-30
- auto: clean

## 52. MB0899#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: Suzlon has been hitting upper circuits repeatedly. Which band applies now, what was the last base-price reset, and when did it last open nor
- grade: ANSWERED | answer: Percentage of capex investments to improve environmental and social impacts 2024-25 = 58.0 % (ar_facts, known 2026-06-25); Basic Earnings Loss Per Share From Continuing And Discontinued Operations 2025-03-31 = 5.25 INRPerShare (results_xbrl, known 2025-05-19); Basic Earnings Loss Per Share From Continuing And Discontin
- evidence: 2026-06-25:FACTS:ar_facts:38328#68, 2025-05-19:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1443564_19052025091517_WEB.xml, 2025-05-19:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1443564_19052025091517_WEB.xml
- source: ref 2026-06-25:FACTS:ar_facts:38328#68
- source: ref 2025-05-19:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1443564_19052025091517_WEB.xml
- auto: clean

## 53. MB0900#MI — MICRO — Unclassified
- entity: AGVENTURES(INE321D01016)
- question: Vodafone Idea trades in a narrow band. Is the 5% limit still on, and how does delivery behave on the days it touches the band?
- grade: ANSWERED | answer: AGVENTURES: close 127.8 on 2026-10-19
- evidence: 2026-10-19:SERIES:SERIES:AGVENTURES
- source: ref 2026-10-19:SERIES:SERIES:AGVENTURES
- auto: clean

## 54. MB0901#MI — MICRO — Unclassified
- entity: AGVENTURES(INE321D01016)
- question: Jaiprakash Power: did the band change after the last base-price reset, and did the change coincide with the volume spike?
- grade: ANSWERED | answer: AGVENTURES: close 127.8 on 2026-10-19
- evidence: 2026-10-19:SERIES:SERIES:AGVENTURES
- source: ref 2026-10-19:SERIES:SERIES:AGVENTURES
- auto: clean

## 55. MB0916#MI — MICRO — General Diversified
- entity: UFLEX(INE516A01017)
- question: SBI: is the recent DII accumulation visible in the shareholding pattern, or only in the daily flow prints?
- grade: ANSWERED | answer: Virgin PET Chips – Panipat - = 168,000 MTPA (deck_figures, known 2026-06-29); Virgin PET Chips – Panipat - = 168,000 MTPA (deck_figures, known 2026-09-29); Panipat: Started vPET Chips Plant (Bottle and film Grade) 2024 = 2,024 - (deck_figures, known 2026-06-29)
- evidence: 2026-06-29:FACTS:deck_figures:e14435032896349d8649ac1305bbffc7f3ba05834396f5bd424b41fe559428f5#12, 2026-09-29:FACTS:deck_figures:5c669665bbb2fdb8151f4e2c9e74a4a721ae7aa1950261daecc8dee909c8137d#13, 2026-06-29:FACTS:deck_figures:e14435032896349d8649ac1305bbffc7f3ba05834396f5bd424b41fe559428f5#4
- source: ref 2026-06-29:FACTS:deck_figures:e14435032896349d8649ac1305bbffc7f3ba05834396f5bd424b41fe559428f5#12
- source: ref 2026-09-29:FACTS:deck_figures:5c669665bbb2fdb8151f4e2c9e74a4a721ae7aa1950261daecc8dee909c8137d#13
- source: ref 2026-06-29:FACTS:deck_figures:e14435032896349d8649ac1305bbffc7f3ba05834396f5bd424b41fe559428f5#4
- source: ref 2025-11-13:FACTS:results_xbrl:INTEGRATED_FILING_INDAS_1574393_13112025091548_WEB.xml
- auto: clean

## 56. MB0944#MI — MICRO — Chemicals
- entity: JUBLINGREA(INE0BY001018)
- question: When Eternal entered the Nifty 50, how much passive buying did that imply, and did the stock move before or after the effective date?
- grade: ANSWERED | answer: Nifty 50: close 22,889 on 2026-10-19 (-1.11% on the day)
- evidence: 2026-10-19:SERIES:SERIES:Nifty 50
- source: ref 2026-10-19:SERIES:SERIES:Nifty 50
- auto: clean

## 57. MB0946#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: HAL's weight in the Nifty 50 has changed with the stock. How much of the trading volume on rebalance days is index-driven?
- grade: ANSWERED | answer: Nifty 50: close 22,889 on 2026-10-19 (-1.11% on the day); annual_report 2026-06-25T16:26:19 p147 Notes to the Consolidated Financial Stat: Notes to the Consolidated Financial Statements 
for the year ended March 31, 2026
Notes to the Consolidated Financial Statements 
for the year ended March 31, 2026

(All amounts a 
- evidence: 2026-10-19:SERIES:SERIES:Nifty 50, 2026-06-25:EVIDENCE:chunks_v3:sha256:9911755d038ee71331ed4ed71548738710f1224d91784b8f13da797fcbdc23e6#147, 2026-06-25:EVIDENCE:chunks_v3:sha256:9911755d038ee71331ed4ed71548738710f1224d91784b8f13da797fcbdc23e6#102
- source: ref 2026-10-19:SERIES:SERIES:Nifty 50
- source: ref 2026-06-25:EVIDENCE:chunks_v3:sha256:9911755d038ee71331ed4ed71548738710f1224d91784b8f13da797fcbdc23e6#147
- source: ref 2026-06-25:EVIDENCE:chunks_v3:sha256:9911755d038ee71331ed4ed71548738710f1224d91784b8f13da797fcbdc23e6#102
- source: ref 2026-06-25:EVIDENCE:chunks_v3:sha256:9911755d038ee71331ed4ed71548738710f1224d91784b8f13da797fcbdc23e6#53
- auto: clean

## 58. MB0951#MI — MICRO — Unclassified
- entity: AGVENTURES(INE321D01016)
- question: Nestle India: is the last five years' growth from volume or from price and mix, and does that change the moat case?
- grade: ANSWERED | answer: AGVENTURES: close 558.8 on 2020-03-31; annual_report 2025-07-04T19:20:14 p6 ORIENTAL CARBON & CHEMICALS LIMITED (con: Mitali Gupta  (DIN- 11119860), who was 
appointed as an Additional Director, in Independent 
Category, by the Board of Directors of the Company with 
effect from May 28, 2025, in t | annual_report 2025-
- evidence: 2026-10-19:SERIES:SERIES:AGVENTURES, 2025-07-04:EVIDENCE:chunks_v3:sha256:020f55e14742d33d9599dbfd417d43888215d6ed0c3d9bedd4664a2e836220fc#6, 2025-07-04:EVIDENCE:chunks_v3:sha256:020f55e14742d33d9599dbfd417d43888215d6ed0c3d9bedd4664a2e836220fc#142
- source: ref 2026-10-19:SERIES:SERIES:AGVENTURES
- source: ref 2025-07-04:EVIDENCE:chunks_v3:sha256:020f55e14742d33d9599dbfd417d43888215d6ed0c3d9bedd4664a2e836220fc#6
- source: ref 2025-07-04:EVIDENCE:chunks_v3:sha256:020f55e14742d33d9599dbfd417d43888215d6ed0c3d9bedd4664a2e836220fc#142
- source: ref 2025-07-04:EVIDENCE:chunks_v3:sha256:020f55e14742d33d9599dbfd417d43888215d6ed0c3d9bedd4664a2e836220fc#65
- auto: clean

## 59. MB0955#MI — MICRO — General Diversified
- entity: WPIL(INE765D01022)
- question: JSW Steel: the last capex round was large. What incremental ROIC has it earned so far, and how far is it from the cost of capital?
- grade: ANSWERED | answer: Consolidated profit before tax - previous year FY21 = 134.4 Rs crore (ar_facts, known 2022-07-30); Consolidated sales - previous year FY21 = 994.8 Rs crore (ar_facts, known 2022-07-30); Domestic operations profit before tax - previous year FY21 = 79.4 Rs crore (ar_facts, known 2022-07-30)
- evidence: 2022-07-30:FACTS:ar_facts:95551#21, 2022-07-30:FACTS:ar_facts:95551#21, 2022-07-30:FACTS:ar_facts:95551#21
- source: ref 2022-07-30:FACTS:ar_facts:95551#21
- auto: clean

## 60. MB0956#MI — MICRO — Capital Goods
- entity: HEGAM(INE545A01024)
- question: Polycab: does the ROIC still clear the cost of capital after the working-capital build, and what would a demand slowdown do to it?
- grade: ANSWERED | answer: HEGAM: close 275.2 on 2022-03-31
- evidence: 2026-10-19:SERIES:SERIES:HEGAM
- source: ref 2026-10-19:SERIES:SERIES:HEGAM
- auto: clean

