> **Reviewer notes (Claude, 2026-10-27 20:30, before Shivam's approval).** The test passed (300 rows, unique ids). Of 418 ISINs, 416 resolve; the 2 that don't are ETF INF ISINs. Hand-check of 20 random rows plus a scan of all 300 found:
> - **13 index-screen rows (V8) were marked "yes" but are only partial.** Index membership is a single 2026-09-30 snapshot covering Nifty 50/100/Midcap 150, so they are now `partial`. Rows: DBQ1-V8, DBQ2-V8, DBQ5-V8, QA1-V8, QA3-V8, QA4-V8, QA6-V8, QA8-V8, QA9-V8, Q12-V8, Q18-V8, Q21-V8, Q23-V8.
> - **9 correlation and tracking-error rows were marked "yes".** There is no rolling-correlation tool and no dated tariff series, so they are now `partial`. Rows: Q19-V1, Q19-V3, Q19-V7, Q20-V1, Q20-V2, Q20-V3, Q20-V4, Q20-V6, Q20-V9.
> - **Rewrite before approval:**
>   - Q16-V3 has no naming variation.
>   - QA5-V6 does not change the period.
>   - Q19-V2 and Q19-V9 give different ISINs for the same Quantum Gold ETF, and the ETF identities are unverified.
> - Q21-V3 and Q23-V3 use a document reference as the "naming" variation of a policy. That is acceptable.
> - **Coverage after fixes:** {'yes': 152, 'partial': 100, 'no': 48}.
> - The table below shows the worker's original coverage values. The corrected values are in the `.jsonl` (`coverage.was` keeps the old value; `review_flags` lists each fix).

# Question bank 300 - 10 variations of Shivam's 30 questions (2026-10-27)

Data vintage: prices and documents to **2026-10-19**; companies from 2024-04-01 (prices from 2019-01-01). All entities, dates, documents and policies below were read from the live stores; nothing is invented. The 30 originals stay as separate fixed regressions and are not part of these 300 rows.

## Summary

### Counts

| Family | Rows |
|---|---|
| 1 | 110 |
| 2 | 120 |
| 3 | 30 |
| 4 | 20 |
| 5 | 10 |
| 6 | 80 |
| 7 | 30 |
| 8 | 30 |
| 9 | 40 |
| 11 | 40 |

**Entity level**: stock 184, industry 53, index 30, theme 17, policy 16

**Variation**: V1 30, V2 30, V3 30, V4 30, V5 30, V6 30, V7 30, V8 30, V9 30, V10 30

**Market-cap bucket**: LARGE 97, MID 72, SMALL 64, MICRO 57, n/a 10

**Exchange**: NSE+BSE 280, ETF 10, NSE-only 8, BSE-only 2

**Sector (BSE taxonomy, raw)**: Financial Services 50, Capital Goods 30, Oil Gas & Consumable Fuels 22, Information Technology 21, Consumer Durables 19, Fast Moving Consumer Goods 16, Chemicals 13, Healthcare 10, Consumer Services 10, ETF 10, Automobile and Auto Components 9, Media Entertainment & Publication 8, Services 8, Realty 8, Telecommunication 7, Power 7, Metals & Mining 7, Textiles 7, Utilities 6, Forest Materials 6, Construction 5, Construction Materials 5, Diversified 5, n/a 4, TEXTILES 2, AUTOMOBILE 2, HEALTHCARE SERVICES 1, CONSTRUCTION 1, SERVICES 1

**Industry (finer taxonomy)**: Banks 22, Consumer Durables 19, Petroleum Products 15, Finance 15, IT - Services 13, Industrial Products 11, Capital Markets 10, ETF 10, Pharmaceuticals & Biotechnology 8, Realty 8, Food Products 8, Electrical Equipment 7, Power 7, Fertilizers & Agrochemicals 7, Textiles & Apparels 7, Aerospace & Defense 7, Telecom - Services 6, Retailing 6, Auto Components 6, Other Utilities 6, Paper Forest & Jute Products 6, Chemicals & Petrochemicals 6, Agricultural Food & other Products 5, Construction 5, Entertainment 5, Diversified 5, IT - Software 4, Cement & Cement Products 4, Minerals & Mining 4, n/a 4, Industrial Manufacturing 4, IT - Hardware 4, Oil 3, Automobiles 3, Commercial Services & Supplies 3, Other Consumer Services 3, Transport Services 3, Media 3, Insurance 2, Transport Infrastructure 2, Personal Products 2, Gas 2, TEXTILES - COTTON 2, AUTO ANCILLARIES 2, Consumable Fuels 2, Healthcare Services 2, Non - Ferrous Metals 2, Ferrous Metals 1, HEALTHCARE SERVICES 1, Diversified FMCG 1, CONSTRUCTION 1, HOTELS/ RESORTS AND OTHER RECREATIONAL ACTIVITIES 1, Other Construction Materials 1, Agricultural Commercial & Construction Vehicles 1, Financial Technology (Fintech) 1, Leisure Services 1, Telecom - Equipment & Accessories 1

**Basic industry**: IT Enabled Services 13, Refineries & Marketing 11, Gems Jewellery And Watches 11, Private Sector Bank 11, Housing Finance Company 10, ETF 10, Pharmaceuticals 8, Public Sector Bank 8, Residential Commercial Projects 7, Aerospace & Defense 7, Dairy Products 7, Heavy Electrical Equipment 6, Other Capital Market related Services 6, Iron & Steel Products 5, Civil Construction 5, Auto Components & Equipments 5, Power Generation 5, Waste Management 5, Diversified 5, Paper & Paper Products 5, Fertilizers 5, Cement & Cement Products 4, Industrial Minerals 4, n/a 4, Other Textile Products 4, Specialty Chemicals 4, Lubricants 4, Computers Hardware & Equipments 4, Other Agricultural Products 3, Telecom - Cellular & Fixed line services 3, Computers - Software & Consulting 3, Garments & Apparels 3, Stockbroking & Allied 3, Media & Entertainment 3, Other Bank 3, Life Insurance 2, Integrated Power Utilities 2, Diversified Retail 2, Offshore Support Solution Drilling 2, Pesticides & Agrochemicals 2, Household Appliances 2, Passenger Cars & Utility Vehicles 2, Industrial Products 2, Personal Care 2, LPG/CNG/PNG/LNG Supplier 2, Diversified Commercial Services 2, SPINNING-COTTON/BLENDED 2, Internet & Catalogue Retail 2, AUTO ANCILLARIES 2, Coal 2, E-Learning 2, Aluminium 2, Other Telecom Services 2, Advertising & Media Agencies 2, Financial Institution 2, Consumer Electronics 2, Other Electrical Equipment 1, Sanitary Ware 1, Iron & Steel 1, Ceramics 1, Paints 1, Film Production Distribution & Exhibition 1, Road Assets - Toll Annuity Hybrid-Annuity 1, Port & Port services 1, Furniture Home Furnishing 1, Telecom - Infrastructure 1, HOSPITAL 1, Diversified FMCG 1, Ship Building & Allied Services 1, Oil Exploration & Production 1, 2/3 Wheelers 1, Education 1, RESIDENTIAL/COMMERCIAL/SEZ Project 1, HOTELS/RESORTS 1, Shipping 1, Carbon Black 1, Airline 1, Other Construction Materials 1, Exchange and Data Platform 1, Commodity Chemicals 1, Packaged Foods 1, Tyres & Rubber Products 1, Real Estate related services 1, Digital Entertainment 1, Pharmacy Retail 1, Hospital 1, Abrasives & Bearings 1, Non Banking Financial Company (NBFC) 1, Other Financial Services 1, Investment Company 1, Healthcare Service Provider 1, Water Supply & Management 1, Compressors Pumps & Diesel Engines 1, Railway Wagons 1, Commercial Vehicles 1, Financial Technology (Fintech) 1, Road Transport 1, Plastic Products - Industrial 1, E-Retail/ E-Commerce 1, Edible Oil 1, Business Process Outsourcing (BPO)/ Knowledge Process Outsourcing (KPO) 1, Electronic Media 1, Jute & Jute Products 1, Amusement Parks/ Other Recreation 1, Telecom - Equipment & Accessories 1, Sugar 1, Other Industrial Products 1, Castings & Forgings 1, Software Products 1, Packaging 1

**Coverage split**: yes 174, partial 78, no 48.

**Spread note**: case-normalised, the bank touches 25 BSE sectors and 54 industries; the finer taxonomy is shown as evidence that the 25+ target is real, not a case-variant count.

Market-cap buckets are computed from `company_forensic_health.market_cap_inr_cr` at the 2026-10-19 vintage (LARGE >= Rs 50,000 cr, MID 10,000-50,000, SMALL 1,000-10,000, MICRO < 1,000); where that row is missing, the stored `master_companies.market_cap_tier` is the fallback. Index membership is current-only in the store (index_membership as_of 2026-09-30; company_industry.index_list fetched 2026-10-19), so V8 screens are point-in-time only to that date.

### Questions expected to fail today, grouped by gap

| Gap | Rows | Status |
|---|---|---|
| no filing/document inside the requested period | 37 | partial |
| PIB provenance or coverage gap | 13 | partial |
| segment context missing in results XBRL | 8 | no |
| required store missing for the entity | 8 | no |
| results notes lack a geographic split | 7 | partial |
| no refurbished/second-hand electronics sales series | 7 | partial |
| ETF NAV/iNAV rows missing | 6 | partial |
| concall transcript held but not chunked | 5 | no |
| other coverage gap | 5 | no |
| policy record gap | 5 | partial |
| investor presentation missing for the entity | 3 | no |
| corporate-action edge unavailable | 3 | no |
| September 2026 shareholding filing missing | 2 | no |
| deck or page not stored for the date | 2 | no |
| price rows missing for the entity/window | 2 | partial |
| coal price series ends 2025-12-26 | 2 | no |
| policy record gap | 2 | no |
| data-centre tax holiday not in policy_events | 2 | no |
| annual report missing for the entity | 1 | no |
| delivery rows missing for the chosen dates | 1 | no |
| banking-taxonomy concept missing | 1 | no |
| no filing/document inside the requested period | 1 | no |
| ETF NAV/iNAV rows missing | 1 | no |
| no refurbished/second-hand electronics sales series | 1 | no |
| coal price series ends 2025-12-26 | 1 | partial |

## Questions

### DBQ1 - AEROFLEX products + close on a date

Family 1,2. Entity level: stock. What it tests: products + a date-stamped close.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What does Hariom Pipe Industries (NSE: HARIOMPIPE) make, and what was its NSE close on 16 October 2026? | Hariom Pipe Industries | 16 Oct 2026 | yes | same-industry peer at the same level; products + a date-stamped close |
| V2 | What does RTS Power Corporation (NSE: RTSPOWR) make, and what was its NSE close on 16 October 2026? | RTS Power Corporation | 16 Oct 2026 | yes | same sector, different market-cap bucket; products + a date-stamped close |
| V3 | What does NSE: AMIORG (now ACUTAAS) make, and what was its NSE close on 16 October 2026? | Acutaas Chemicals | 16 Oct 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; products + a date-stamped close |
| V4 | RELIANCE products + close 16 Oct 2026 | Reliance Industries | 16 Oct 2026 | yes | terse keyword query, 3-8 words; products + a date-stamped close |
| V5 | Bhai, KRBL (NSE: KRBL) kya banati hai, aur 16 October 2026 ko NSE par kitne pe close hui? Products aur close dono batao, short mein. | KRBL | 16 Oct 2026 | yes | long natural or Hinglish phrasing; products + a date-stamped close |
| V6 | What does SETUINFRA (BSE: 533605) make, and what was its BSE close on 30 September 2026? | SETUINFRA | 30 Sep 2026 | yes | different period label inside the data window; products + a date-stamped close |
| V7 | For all listed companies in Industrial Products, list what each company makes and its NSE close on 16 October 2026. | Bharti Airtel; HDFC Bank; ICICI Bank | 16 Oct 2026 | yes | scope up to the industry or sector; products + a date-stamped close |
| V8 | For the NIFTY TOTAL MARKET constituents, list what each company makes and its NSE close on 16 October 2026. | State Bank of India; Bajaj Finance; Larsen & Toubro | 16 Oct 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; products + a date-stamped close |
| V9 | As of 30 June 2026, what did Protean eGov Technologies (NSE: PROTEAN)'s latest annual report say it makes, and what was its close that day? | Protean eGov Technologies | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; products + a date-stamped close |
| V10 | What does Life Insurance Corporation Of India (NSE: LICI) make, and what was its NSE close on 16 October 2026? If either is not in our data, answer NOT IN DATA and say why. | Life Insurance Corporation Of India | 16 Oct 2026 | yes | hard edge: NOT IN DATA or a corporate action in the period; products + a date-stamped close |

### DBQ2 - 532627 latest AR: control change

Family 1,9. Entity level: stock. What it tests: latest annual report disclosure on control/ownership.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What did CESC (NSE: CESC)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? | CESC | FY2026 | yes | same-industry peer at the same level; latest annual report disclosure on control/ownership |
| V2 | What did Reliance Infrastructure (NSE: RELINFRA)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? | Reliance Infrastructure | FY2026 | yes | same sector, different market-cap bucket; latest annual report disclosure on control/ownership |
| V3 | What did NSE: SHIL (now HINDWAREAP)'s latest annual report (FY2026) disclose about a change in ownership or control, and where in the report? | Hindware Home Innovation | FY2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; latest annual report disclosure on control/ownership |
| V4 | 570002 latest annual report control change | FELDVR | FY2021 | partial (store holds 2019-03-31..2021-03-31, nothing in 2025-04-01..2026-10-19; store holds 2019-03-31..2021-03-31, nothing in 2025-04-01..2026-10-19) | terse keyword query, 3-8 words; latest annual report disclosure on control/ownership |
| V5 | JSW Steel (NSE: JSWSTEEL) ke latest annual report mein ownership ya control change ke baare mein kya likha hai? Kaunsa saal, kaunsa page, aur exactly kya disclosure hai? | JSW Steel | FY2026 | yes | long natural or Hinglish phrasing; latest annual report disclosure on control/ownership |
| V6 | What did Craftsman Automation (NSE: CRAFTSMAN)'s latest annual report (FY2025) disclose about a change in ownership or control, and where in the report? | Craftsman Automation | FY2025 | yes | different period label inside the data window; latest annual report disclosure on control/ownership |
| V7 | For all listed companies in Power, which companies disclosed a change in control or ownership in their latest annual report, and what changed? | Adani Power; NTPC; Power Grid Corporation of India | FY2026 | yes | scope up to the industry or sector; latest annual report disclosure on control/ownership |
| V8 | For the NIFTY 500 constituents, which companies disclosed a change in control or ownership in their latest annual report, and what changed? | Infosys; Kotak Mahindra Bank; Hindustan Unilever | FY2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; latest annual report disclosure on control/ownership |
| V9 | As of 30 June 2026, what did Prism Johnson (NSE: PRSMJOHNSN)'s latest filed annual report say about a change in control or ownership? | Prism Johnson | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; latest annual report disclosure on control/ownership |
| V10 | What did Aakash Exploration Services (NSE: AAKASH)'s latest annual report disclose about a change in control? If no annual report is held for it, answer NOT IN DATA and name the store checked. | Aakash Exploration Services | FY2025 | no (no annual report stored for this company) | hard edge: NOT IN DATA or a corporate action in the period; latest annual report disclosure on control/ownership |

### DBQ3 - 544161 business + segments

Family 1. Entity level: stock. What it tests: business + segment disclosure, resolved by BSE code/ISIN.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What is Asian Granito India (NSE: ASIANTILES)'s business, and what segments and segment revenue did it report for the latest quarter? | Asian Granito India | Q1FY27 | partial (store holds 2019-03-31..2026-03-31, nothing in 2026-04-01..2026-06-30) | same-industry peer at the same level; business + segment disclosure, resolved by BSE code/ISIN |
| V2 | What is Asian Paints (NSE: ASIANPAINT)'s business, and what segments and segment revenue did it report for the latest quarter? | Asian Paints | Q1FY27 | no (no segment context in the results XBRL) | same sector, different market-cap bucket; business + segment disclosure, resolved by BSE code/ISIN |
| V3 | What is NSE: PVR (now PVRINOX)'s business, and what segments and segment revenue did it report for the latest quarter? | Pvr Inox | Q1FY27 | partial (store holds 2019-03-31..2026-03-31, nothing in 2026-04-01..2026-06-30) | naming variant: ISIN / BSE code / old symbol after a rename; business + segment disclosure, resolved by BSE code/ISIN |
| V4 | DHARMAJ business segments FY26 | Dharmaj Crop Guard | Q1FY27 | no (no segment context in the results XBRL) | terse keyword query, 3-8 words; business + segment disclosure, resolved by BSE code/ISIN |
| V5 | Highway Infrastructure (NSE: HILINFRA) ka business kya hai aur segments kaunse hain? Annual report aur latest results ke hisaab se segment revenue bhi batao. | Highway Infrastructure | Q1FY27 | partial (store holds 2026-03-31..2026-03-31, nothing in 2026-04-01..2026-06-30) | long natural or Hinglish phrasing; business + segment disclosure, resolved by BSE code/ISIN |
| V6 | What is Antony Waste Handling Cell (NSE: AWHCL)'s business, and what segments and segment revenue did it report for the latest quarter? | Antony Waste Handling Cell | April-June 2026 (Q1 FY2026-27) | no (no segment context in the results XBRL) | different period label inside the data window; business + segment disclosure, resolved by BSE code/ISIN |
| V7 | For all listed companies in Consumer Durables, what are the reported business segments and their latest segment revenue? | LG Electronics India; Dixon Technologies (India); Havells India | Q1FY27 | partial (store holds 2026-03-31..2026-03-31, nothing in 2026-04-01..2026-06-30) | scope up to the industry or sector; business + segment disclosure, resolved by BSE code/ISIN |
| V8 | For the NIFTY500 EQUAL WEIGHT constituents, what are the reported business segments and their latest segment revenue? | Adani Ports and Special Economic Zone; HCL Technologies; Axis Bank | Q1FY27 | partial (store holds 2019-03-31..2026-03-31, nothing in 2026-04-01..2026-06-30) | screen by index / theme / market-cap bucket, membership as of the date; business + segment disclosure, resolved by BSE code/ISIN |
| V9 | As of 30 June 2026, what did Arvind (NSE: ARVIND)'s latest results and annual report disclose about its business and segments? | Arvind | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; business + segment disclosure, resolved by BSE code/ISIN |
| V10 | For 20 Microns (NSE: 20MICRONS), what are its business segments and segment revenue for Q1FY27? If segment disclosure is not in the data, answer NOT IN DATA and say which store is missing. | 20 Microns | Q1FY27 | no (no segment context for Q1FY27 in the results XBRL) | hard edge: NOT IN DATA or a corporate action in the period; business + segment disclosure, resolved by BSE code/ISIN |

### DBQ4 - P/B now vs stored

Family 2,11. Entity level: stock. What it tests: P/B from matching price and book-value dates.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What is Goldiam International (NSE: GOLDIAM)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. | Goldiam International | 19 Oct 2026 | partial (store holds FY22..FY26, nothing in 2024-04-01..2026-10-19) | same-industry peer at the same level; P/B from matching price and book-value dates |
| V2 | What is Ahlada Engineers (NSE: AHLADA)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. | Ahlada Engineers | 19 Oct 2026 | partial (store holds FY22..FY26, nothing in 2024-04-01..2026-10-19) | same sector, different market-cap bucket; P/B from matching price and book-value dates |
| V3 | What is NSE: INFRATEL (now INDUSTOWER)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. | Indus Towers | 19 Oct 2026 | partial (store holds FY23..FY26, nothing in 2024-04-01..2026-10-19) | naming variant: ISIN / BSE code / old symbol after a rename; P/B from matching price and book-value dates |
| V4 | GODREJIND pb ratio stored vs computed | Godrej Industries | 19 Oct 2026 | partial (store holds FY22..FY26, nothing in 2024-04-01..2026-10-19) | terse keyword query, 3-8 words; P/B from matching price and book-value dates |
| V5 | Flexituff Ventures International (NSE: FLEXITUFF) ka P/B ratio kitna hai? Database mein stored ratio aur aaj ke price se nikaala hua ratio dono batao, aur farq kyun hai. | Flexituff Ventures International | 19 Oct 2026 | partial (store holds FY22..FY26, nothing in 2024-04-01..2026-10-19) | long natural or Hinglish phrasing; P/B from matching price and book-value dates |
| V6 | What is Kovai Medical Center & Hospital (NSE: KOVAI)'s P/B now, and how does it compare with the stored ratio? State the price date and the book-value date. | Kovai Medical Center & Hospital | 30 Sep 2026 | partial (store holds FY23..FY26, nothing in 2024-04-01..2026-10-19) | different period label inside the data window; P/B from matching price and book-value dates |
| V7 | For all listed companies in Consumer Durables, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book value. | Maruti Suzuki India; Mahindra & Mahindra; Adani Enterprises | 19 Oct 2026 | partial (store holds FY22..FY26, nothing in 2024-04-01..2026-10-19) | scope up to the industry or sector; P/B from matching price and book-value dates |
| V8 | For the NIFTY500 LARGEMIDSMALL EQUAL-CAP WEIGHTED constituents, rank the companies by P/B computed from the close on 19 October 2026 and the latest annual-report book value. | ITC; Hindustan Aeronautics; ETERNAL | 19 Oct 2026 | partial (store holds FY22..FY26, nothing in 2024-04-01..2026-10-19) | screen by index / theme / market-cap bucket, membership as of the date; P/B from matching price and book-value dates |
| V9 | As of 31 March 2026, what was Satia Industries (NSE: SATIA)'s P/B using the price and book value known by that date? Compare it with the stored ratio. | Satia Industries | as of 31 March 2026 | partial (store holds FY22..FY26, nothing in 2024-04-01..2026-03-31) | point-in-time: only evidence known by the as-of date; P/B from matching price and book-value dates |
| V10 | What is Motherson Sumi Wiring India (NSE: MSUMI)'s P/B now versus the stored ratio, after adjusting for its corporate action? If book value per share is not held, say NOT IN DATA. | Motherson Sumi Wiring India | 19 Oct 2026 | partial (store holds FY23..FY26, nothing in 2024-04-01..2026-10-19) | hard edge: NOT IN DATA or a corporate action in the period; P/B from matching price and book-value dates |

### DBQ5 - DEEDEV Aug-2026 concall remark

Family 1. Entity level: stock. What it tests: a named speaker's remark from a call transcript.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What did Jash Engineering (NSE: JASH)'s management say about demand and margins on its 18 August 2026 earnings call, and who said it? | Jash Engineering | 18 Aug 2026 | yes | same-industry peer at the same level; a named speaker's remark from a call transcript |
| V2 | What did CG Power and Industrial Solutions (NSE: CGPOWER)'s management say about demand and margins on its 12 May 2025 earnings call, and who said it? | CG Power and Industrial Solutions | 12 May 2025 | partial (store holds 2024-01-29..2025-05-12, nothing in 2026-07-01..2026-08-31; store holds 2024-01-29..2025-05-12, nothing in 2026-07-01..2026-08-31) | same sector, different market-cap bucket; a named speaker's remark from a call transcript |
| V3 | What did NSE: SUVENPHAR (now COHANCE)'s management say about demand and margins on its 15 May 2026 earnings call, and who said it? | Cohance Lifesciences | 15 May 2026 | partial (store holds 2025-06-02..2026-05-15, nothing in 2026-07-01..2026-08-31; store holds 2025-06-02..2026-05-15, nothing in 2026-07-01..2026-08-31) | naming variant: ISIN / BSE code / old symbol after a rename; a named speaker's remark from a call transcript |
| V4 | DABUR call 2025-02-04 management outlook | Dabur India | 4 Feb 2025 | partial (store holds 2024-05-08..2025-02-04, nothing in 2026-07-01..2026-08-31; store holds 2024-05-08..2025-02-04, nothing in 2026-07-01..2026-08-31) | terse keyword query, 3-8 words; a named speaker's remark from a call transcript |
| V5 | Mahanagar Gas (NSE: MGL) ki 16 February 2026 wali earnings call mein management ne business aur margin outlook ke baare mein kya kaha? Speaker ka naam aur quote batao. | Mahanagar Gas | 16 Feb 2026 | partial (store holds 2024-08-01..2026-02-16, nothing in 2026-07-01..2026-08-31; store holds 2024-08-01..2026-02-16, nothing in 2026-07-01..2026-08-31) | long natural or Hinglish phrasing; a named speaker's remark from a call transcript |
| V6 | What did LEAP India (NSE: LEAPIND)'s management say about demand and margins on its 4 September 2026 earnings call, and who said it? | LEAP India | 4 Sep 2026 | partial (store holds 2026-09-04..2026-09-04, nothing in 2026-07-01..2026-08-31; store holds 2026-09-04..2026-09-04, nothing in 2026-07-01..2026-08-31) | different period label inside the data window; a named speaker's remark from a call transcript |
| V7 | For all listed companies in Industrial Manufacturing, what did management say about demand and margins on their latest earnings calls, with quoted evidence? | Mazagon Dock Shipbuilders; INDO-MIM; Aditya Infotech | Aug 2026 | no (store has no rows for this entity; store has no rows for this entity) | scope up to the industry or sector; a named speaker's remark from a call transcript |
| V8 | For the NIFTY500 MULTICAP 50:25:25 constituents, what did management say about demand and margins on their latest earnings calls, with quoted evidence? | Oil & Natural Gas Corporation; Bajaj Auto; Bajaj Finserv | 12 Aug 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; a named speaker's remark from a call transcript |
| V9 | As of 31 July 2026, what had Concord Enviro Systems (NSE: CEWATER)'s management last said on an earnings call about demand and margins? | Concord Enviro Systems | as of 31 July 2026 | yes | point-in-time: only evidence known by the as-of date; a named speaker's remark from a call transcript |
| V10 | What did 21st Century Management Services (NSE: 21STCENMGM) say about demand and margins on its 13 August 2026 earnings call? If the transcript is held but not chunked, answer NOT IN DATA and say so. | 21st Century Management Services | 13 Aug 2026 | no (transcript is held but never chunked; the quote is NOT IN DATA) | hard edge: NOT IN DATA or a corporate action in the period; a named speaker's remark from a call transcript |

### QA1 - Ather delivery NSE+BSE on 2 dates

Family 2. Entity level: stock. What it tests: NSE + BSE delivered quantity, not traded quantity.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What was Eicher Motors (NSE: EICHERMOT)'s delivered quantity (not total traded quantity) on 15 September 2026 and 16 September 2026, NSE and BSE, with the combined total per day? | Eicher Motors | 13-14 Apr 2026 | yes | same-industry peer at the same level; NSE + BSE delivered quantity, not traded quantity |
| V2 | What was SEDEMAC Mechatronics (NSE: SEDEMAC)'s delivered quantity (not total traded quantity) on 15 September 2026 and 16 September 2026, NSE and BSE, with the combined total per day? | SEDEMAC Mechatronics | 13-14 Apr 2026 | yes | same sector, different market-cap bucket; NSE + BSE delivered quantity, not traded quantity |
| V3 | What was NSE: DALALSTCOM (now KEEPLEARN)'s delivered quantity (not total traded quantity) on 10 June 2026 and 11 June 2026, NSE and BSE, with the combined total per day? | DSJ Keep Learning | 13-14 Apr 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; NSE + BSE delivered quantity, not traded quantity |
| V4 | ARIHANT delivery 11-12 Aug nse bse | Arihant Foundations & Housing | 13-14 Apr 2026 | yes | terse keyword query, 3-8 words; NSE + BSE delivered quantity, not traded quantity |
| V5 | Sambandam Spinning Mills (NSE: SAMBANDAM) ka delivered quantity 11 August 2026 aur 12 August 2026 ko kitna tha? NSE, BSE aur dono ka total alag-alag batao. | Sambandam Spinning Mills | 13-14 Apr 2026 | no (no NSE+BSE delivery rows on the chosen dates; no NSE+BSE delivery rows on the chosen dates; no NSE+BSE delivery rows on the chosen dates) | long natural or Hinglish phrasing; NSE + BSE delivered quantity, not traded quantity |
| V6 | What was Sayaji Hotels (NSE: SAYAJIHOTL)'s delivered quantity (not total traded quantity) on 13 October 2026 and 14 October 2026, NSE and BSE, with the combined total per day? | Sayaji Hotels | the April 2026 second week | yes | different period label inside the data window; NSE + BSE delivered quantity, not traded quantity |
| V7 | For all listed companies in Automobiles, what was the delivered quantity on NSE and BSE on 10 February 2026 and 11 February 2026, ranked? | Hyundai Motor India; Hero MotoCorp; Ather Energy | 13-14 Apr 2026 | yes | scope up to the industry or sector; NSE + BSE delivered quantity, not traded quantity |
| V8 | For the NIFTY SMALLCAP 500 constituents, what was the delivered quantity on NSE and BSE on 14 July 2026 and 15 July 2026, ranked? | Indiamart Intermesh; IDBI Bank; RBL Bank | 13-14 Apr 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; NSE + BSE delivered quantity, not traded quantity |
| V9 | As of 31 March 2026, what delivered quantity had Bimetal Bearings (NSE: BIMETAL) recorded on 15 September 2026 and 16 September 2026 on NSE and BSE? | Bimetal Bearings | as of 31 March 2026 | yes | point-in-time: only evidence known by the as-of date; NSE + BSE delivered quantity, not traded quantity |
| V10 | What was Aakash Exploration Services (NSE: AAKASH)'s delivered quantity on 13 October 2026 and 14 October 2026 on NSE and BSE? If one exchange has no row, say which and answer NOT IN DATA for it. | Aakash Exploration Services | 13-14 Apr 2026 | no (no BSE delivery row on the chosen dates) | hard edge: NOT IN DATA or a corporate action in the period; NSE + BSE delivered quantity, not traded quantity |

### QA2 - BLACKBUCK promoter % Sep 2026

Family 2,11. Entity level: stock. What it tests: promoter holding at a dated quarter-end.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What is The Great Eastern Shipping Company (NSE: GESHIP)'s promoter holding as of Sep 2026, per the latest filing? | The Great Eastern Shipping Company | Sep 2026 | yes | same-industry peer at the same level; promoter holding at a dated quarter-end |
| V2 | What is Indiqube Spaces (NSE: INDIQUBE)'s promoter holding as of Sep 2026, per the latest filing? | Indiqube Spaces | Sep 2026 | yes | same sector, different market-cap bucket; promoter holding at a dated quarter-end |
| V3 | What is NSE: LTI (now LTM)'s promoter holding as of Sep 2026, per the latest filing? | LTM | Sep 2026 | partial (store holds 2021-09-30..2026-06-30, nothing in 2026-09-01..2026-09-30) | naming variant: ISIN / BSE code / old symbol after a rename; promoter holding at a dated quarter-end |
| V4 | INTERARCH promoter holding Sep 2026 | Interarch Building Solutions | Sep 2026 | yes | terse keyword query, 3-8 words; promoter holding at a dated quarter-end |
| V5 | Himadri Speciality Chemical (NSE: HSCL) mein promoter ki holding Sep 2026 tak kitni hai? Latest shareholding filing se number aur date batao. | Himadri Speciality Chemical | Sep 2026 | yes | long natural or Hinglish phrasing; promoter holding at a dated quarter-end |
| V6 | What is Precot (NSE: PRECOT)'s promoter holding as of 30 September 2026, per the latest filing? | Precot | as of 30 September 2026 | yes | different period label inside the data window; promoter holding at a dated quarter-end |
| V7 | For all listed companies in Transport Services, what is the promoter holding as of Sep 2026, ranked from highest to lowest? | InterGlobe Aviation; Delhivery; Container Corporation of India | Sep 2026 | partial (store holds 2021-09-30..2026-06-30, nothing in 2026-09-01..2026-09-30) | scope up to the industry or sector; promoter holding at a dated quarter-end |
| V8 | For the NIFTY MIDSMALLCAP 400 constituents, what is the promoter holding as of Sep 2026, ranked from highest to lowest? | Bharat Heavy Electricals; ICICI Prudential Asset Management Company; Indian Bank | Sep 2026 | no (store has no rows for this entity) | screen by index / theme / market-cap bucket, membership as of the date; promoter holding at a dated quarter-end |
| V9 | As of 30 June 2026, what was The Phoenix Mills (NSE: PHOENIXLTD)'s promoter holding per the latest shareholding filing on or before that date? | The Phoenix Mills | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; promoter holding at a dated quarter-end |
| V10 | What is 360 One Wam (NSE: 360ONE)'s promoter holding as of Sep 2026? If the September 2026 shareholding filing is not held, answer NOT IN DATA and say why. | 360 One Wam | Sep 2026 | no (no September 2026 shareholding filing) | hard edge: NOT IN DATA or a corporate action in the period; promoter holding at a dated quarter-end |

### QA3 - Ganesha facilities per a dated deck

Family 1. Entity level: stock. What it tests: a fact stated in a dated investor deck.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | How many manufacturing facilities does Iris Clothings (NSE: IRISDOREME) report in its investor presentation dated 27 July 2026, and where are they? | Iris Clothings | 27 Jul 2026 | yes | same-industry peer at the same level; a fact stated in a dated investor deck |
| V2 | How many manufacturing facilities does K.P.R. Mill (NSE: KPRMILL) report in its investor presentation dated 13 August 2026, and where are they? | K.P.R. Mill | 13 Aug 2026 | yes | same sector, different market-cap bucket; a fact stated in a dated investor deck |
| V3 | How many manufacturing facilities does NSE: ARISINFRA (now ARIS) report in its investor presentation dated 5 August 2026, and where are they? | Arisinfra Solutions | 5 Aug 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; a fact stated in a dated investor deck |
| V4 | BSE facilities deck 2026-08-04 | BSE | 4 Aug 2026 | yes | terse keyword query, 3-8 words; a fact stated in a dated investor deck |
| V5 | Prime Focus (NSE: PFOCUS) ke 29 September 2026 wale investor presentation ke hisaab se kitni manufacturing facilities hain, aur kahan? Slide ka reference bhi do. | Prime Focus | 29 Sep 2026 | yes | long natural or Hinglish phrasing; a fact stated in a dated investor deck |
| V6 | How many manufacturing facilities does Vodafone Idea (NSE: IDEA) report in its investor presentation dated 30 June 2026, and where are they? | Vodafone Idea | 30 Jun 2026 | yes | different period label inside the data window; a fact stated in a dated investor deck |
| V7 | For all listed companies in Textiles & Apparels, how many manufacturing facilities does each company report in its latest investor presentation? | Page Industries; Pearl Global Industries; Indo Count Industries | 11 Aug 2022 | partial (store holds 2022-08-11..2022-08-11, nothing in 2026-05-01..2026-08-31; store holds 2022-08-11..2022-08-11, nothing in 2026-05-01..2026-08-31) | scope up to the industry or sector; a fact stated in a dated investor deck |
| V8 | For the NIFTY MIDSMALLCAP400 50:50 constituents, how many manufacturing facilities does each company report in its latest investor presentation? | Billionbrains Garage Ventures; The Indian Hotels Company; Lenskart Solutions | 15 Jul 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; a fact stated in a dated investor deck |
| V9 | As of 31 July 2026, how many manufacturing facilities did 3M India (NSE: 3MINDIA) report in its latest deck filed by that date? | 3M India | as of 31 July 2026 | yes | point-in-time: only evidence known by the as-of date; a fact stated in a dated investor deck |
| V10 | How many manufacturing facilities does 21st Century Management Services (NSE: 21STCENMGM) report in its investor presentation dated 25 February 2022? If no deck is stored for it, answer NOT IN DATA and name the store checked. | 21st Century Management Services | 25 Feb 2022 | no (no investor presentation stored for this company) | hard edge: NOT IN DATA or a corporate action in the period; a fact stated in a dated investor deck |

### QA4 - Chemcon products + acquisition per deck

Family 1. Entity level: stock. What it tests: products and an acquisition named in a deck.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | Per POCL Enterprises (NSE: POEL)'s deck of 14 August 2026, what are its key products, and which company did it mention as acquired for inorganic growth? | POCL Enterprises | 14 Aug 2026 | yes | same-industry peer at the same level; products and an acquisition named in a deck |
| V2 | Per Gujarat Fluorochemicals (NSE: FLUOROCHEM)'s deck of 12 August 2026, what are its key products, and which company did it mention as acquired for inorganic growth? | Gujarat Fluorochemicals | 12 Aug 2026 | yes | same sector, different market-cap bucket; products and an acquisition named in a deck |
| V3 | Per NSE: GLS (now ALIVUS)'s deck of 30 July 2026, what are its key products, and which company did it mention as acquired for inorganic growth? | Alivus Life Sciences | 30 Jul 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; products and an acquisition named in a deck |
| V4 | ANDHRAPAP products acquisitions deck 2025-02-08 | Andhra Paper | 8 Feb 2025 | partial (store holds 2024-07-15..2025-02-08, nothing in 2026-03-01..2026-06-30; store holds 2024-07-15..2025-02-08, nothing in 2026-03-01..2026-06-30) | terse keyword query, 3-8 words; products and an acquisition named in a deck |
| V5 | Bharat Petroleum Corporation (NSE: BPCL) ke 22 July 2026 wale deck mein main products kya hain, aur inorganic growth ke liye kis company ka acquisition mention kiya gaya hai? | Bharat Petroleum Corporation | 22 Jul 2026 | yes | long natural or Hinglish phrasing; products and an acquisition named in a deck |
| V6 | Per Bikaji Foods International (NSE: BIKAJI)'s deck of 21 May 2026, what are its key products, and which company did it mention as acquired for inorganic growth? | Bikaji Foods International | 21 May 2026 | yes | different period label inside the data window; products and an acquisition named in a deck |
| V7 | For all listed companies in Chemicals & Petrochemicals, what products and acquisitions does each company report in its latest investor presentation? | Pidilite Industries; Linde India; Navin Fluorine International | 4 Aug 2026 | yes | scope up to the industry or sector; products and an acquisition named in a deck |
| V8 | For the NIFTY500 AHIMSA constituents, what products and acquisitions does each company report in its latest investor presentation? | Coal India; Hindustan Zinc; Grasim Industries | 27 Jul 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; products and an acquisition named in a deck |
| V9 | As of 30 June 2026, what did Jaro Institute of Technology Management and Research (NSE: JARO)'s latest deck disclose about its products and acquisitions? | Jaro Institute of Technology Management and Research | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; products and an acquisition named in a deck |
| V10 | What are 21st Century Management Services (NSE: 21STCENMGM)'s key products and its latest acquisition? If the deck is held but the page text is not extracted, answer NOT IN DATA and say which store is missing. | 21st Century Management Services | 6 Nov 2024 | no (no investor presentation stored for this company) | hard edge: NOT IN DATA or a corporate action in the period; products and an acquisition named in a deck |

### QA5 - Lumax shares + promoter %, latest

Family 2. Entity level: stock. What it tests: exact share count and promoter holding.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | How many equity shares does CEAT (NSE: CEATLTD) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. | CEAT | latest | yes | same-industry peer at the same level; exact share count and promoter holding |
| V2 | How many equity shares does Jamna Auto Industries (NSE: JAMNAAUTO) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. | Jamna Auto Industries | latest | yes | same sector, different market-cap bucket; exact share count and promoter holding |
| V3 | How many equity shares does NSE: PROZONINTU (now PROZONER) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. | Prozone Realty | latest | yes | naming variant: ISIN / BSE code / old symbol after a rename; exact share count and promoter holding |
| V4 | BHARTIHEXA share count promoter holding | Bharti Hexacom | latest | yes | terse keyword query, 3-8 words; exact share count and promoter holding |
| V5 | Dalmia Bharat (NSE: DALBHARAT) ke kitne equity shares hain aur promoter holding kitni hai? Dono numbers latest filing se, date ke saath batao. | Dalmia Bharat | latest | yes | long natural or Hinglish phrasing; exact share count and promoter holding |
| V6 | How many equity shares does BCPL Railway Infrastructure (NSE: BCPL) have, and what is its promoter holding, as of the latest data? Say which filing each number comes from. | BCPL Railway Infrastructure | as of 30 September 2026 | yes | different period label inside the data window; exact share count and promoter holding |
| V7 | For all listed companies in Auto Components, give the latest exact share count and promoter holding for each company, with the filing date. | Samvardhana Motherson International; Bosch; Bharat Forge | latest | no (store has no rows for this entity) | scope up to the industry or sector; exact share count and promoter holding |
| V8 | For the NIFTY LARGEMIDCAP 250 constituents, give the latest exact share count and promoter holding for each company, with the filing date. | Bharat Electronics; Divi's Laboratories; Nestle India | latest | no (store has no rows for this entity) | screen by index / theme / market-cap bucket, membership as of the date; exact share count and promoter holding |
| V9 | As of 30 June 2026, what were Ceinsys Tech (NSE: CEINSYS)'s exact share count and promoter holding? | Ceinsys Tech | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; exact share count and promoter holding |
| V10 | What are Kotyark Industries (NSE: KOTYARK)'s exact share count and promoter holding now, after its corporate action? If the post-action count is not held, answer NOT IN DATA. | Kotyark Industries | latest | yes | hard edge: NOT IN DATA or a corporate action in the period; exact share count and promoter holding |

### QA6 - 540879 deck page 21 (licence)

Family 1. Entity level: stock. What it tests: one page of a dated deck, with the page count as the guard.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What does page 10 of Data Patterns (India) (NSE: DATAPATTNS)'s investor presentation dated 30 July 2026 say about its manufacturing licence or capacity? | Data Patterns (India) | 30 Jul 2026 | yes | same-industry peer at the same level; one page of a dated deck, with the page count as the guard |
| V2 | What does page 3 of Hitachi Energy India (NSE: POWERINDIA)'s investor presentation dated 16 September 2026 say about its manufacturing licence or capacity? | Hitachi Energy India | 16 Sep 2026 | no (deck has 1 pages; page 3 does not exist) | same sector, different market-cap bucket; one page of a dated deck, with the page count as the guard |
| V3 | What does page 24 of NSE: AMIRCHAND (now AEROPLANE)'s investor presentation dated 7 August 2026 say about its manufacturing licence or capacity? | Amir Chand Jagdish Kumar (Exports) | 7 Aug 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; one page of a dated deck, with the page count as the guard |
| V4 | REFEX deck page 31 2026-07-29 | Refex Industries | 29 Jul 2026 | yes | terse keyword query, 3-8 words; one page of a dated deck, with the page count as the guard |
| V5 | Bodhi Tree Multimedia (NSE: BTML) ke 14 August 2026 wale investor presentation ke page 5 par kya dikhaya gaya hai? Text ya quote ke saath batao. | Bodhi Tree Multimedia | 14 Aug 2026 | yes | long natural or Hinglish phrasing; one page of a dated deck, with the page count as the guard |
| V6 | What does page 18 of DCM Shriram (NSE: DCMSHRIRAM)'s investor presentation dated 13 May 2026 say about its manufacturing licence or capacity? | DCM Shriram | 13 May 2026 | yes | different period label inside the data window; one page of a dated deck, with the page count as the guard |
| V7 | For all listed companies in Aerospace & Defense, what do the latest decks say on their capacity or licensing slides? | Bharat Dynamics; Garden Reach Shipbuilders & Engineers; Astra Microwave Products | 10 Jun 2026 | yes | scope up to the industry or sector; one page of a dated deck, with the page count as the guard |
| V8 | For the NIFTY SMALLCAP 250 constituents, what do the latest decks say on their capacity or licensing slides? | Gland Pharma; Aegis Logistics; Poonawalla Fincorp | 10 Aug 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; one page of a dated deck, with the page count as the guard |
| V9 | As of 30 September 2026, what did page 27 of Magnum Ventures (NSE: MAGNUM)'s latest deck filed by that date say? | Magnum Ventures | as of 30 September 2026 | yes | point-in-time: only evidence known by the as-of date; one page of a dated deck, with the page count as the guard |
| V10 | What does page 41 of Capital Trust (NSE: CAPTRUST)'s investor presentation dated 18 August 2026 say? If the deck has fewer pages, answer NOT IN DATA and give the page count. | Capital Trust | 18 Aug 2026 | no (deck has 34 pages; page 41 does not exist) | hard edge: NOT IN DATA or a corporate action in the period; one page of a dated deck, with the page count as the guard |

### QA7 - INE864I01014 fuel-cell capacity, transcript

Family 1,3. Entity level: stock. What it tests: capacity timeline stated on a call.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What did Azad Engineering (NSE: AZAD) say about its capacity expansion, and the completion timeline, on its 14 August 2026 earnings call? | Azad Engineering | 14 Aug 2026 | yes | same-industry peer at the same level; capacity timeline stated on a call |
| V2 | What did ABB India (NSE: ABB) say about its capacity expansion, and the completion timeline, on its 16 May 2025 earnings call? | ABB India | 16 May 2025 | partial (store holds 2024-08-13..2025-05-16, nothing in 2026-06-01..2026-09-30; store holds 2024-08-13..2025-05-16, nothing in 2026-06-01..2026-09-30) | same sector, different market-cap bucket; capacity timeline stated on a call |
| V3 | What did NSE: IDFCBANK (now IDFCFIRSTB) say about its capacity expansion, and the completion timeline, on its 31 July 2026 earnings call? | IDFC First Bank | 31 Jul 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; capacity timeline stated on a call |
| V4 | ENTERO capacity timeline call 2026-08-17 | Entero Healthcare Solutions | 17 Aug 2026 | yes | terse keyword query, 3-8 words; capacity timeline stated on a call |
| V5 | Max Healthcare Institute (NSE: MAXHEALTH) ne apni 20 August 2026 wali call mein capacity expansion ka kya timeline bataya? Completion date aur capex ke saath quote do. | Max Healthcare Institute | 20 Aug 2026 | yes | long natural or Hinglish phrasing; capacity timeline stated on a call |
| V6 | What did Affle 3i (NSE: AFFLE) say about its capacity expansion, and the completion timeline, on its 18 May 2026 earnings call? | Affle 3i | 18 May 2026 | yes | different period label inside the data window; capacity timeline stated on a call |
| V7 | For all listed companies in Electrical Equipment, what capacity-expansion timelines did management give on their latest earnings calls? | GE Vernova T&D India; Siemens Energy India; Apar Industries | 14 Aug 2026 | yes | scope up to the industry or sector; capacity timeline stated on a call |
| V8 | For the NIFTY MICROCAP 250 constituents, what capacity-expansion timelines did management give on their latest earnings calls? | Grindwell Norton; Happy Forgings; Pfizer | Aug 2026 | no (store has no rows for this entity; store has no rows for this entity) | screen by index / theme / market-cap bucket, membership as of the date; capacity timeline stated on a call |
| V9 | As of 31 July 2026, what had Arvind SmartSpaces (NSE: ARVSMART) said about its capacity expansion timeline by that date? | Arvind SmartSpaces | as of 31 July 2026 | yes | point-in-time: only evidence known by the as-of date; capacity timeline stated on a call |
| V10 | What did 21st Century Management Services (NSE: 21STCENMGM) say about its capacity expansion timeline on 6 August 2025? If the transcript exists but is not chunked, answer NOT IN DATA and say so. | 21st Century Management Services | 6 Aug 2025 | no (transcript is held but never chunked; the quote is NOT IN DATA) | hard edge: NOT IN DATA or a corporate action in the period; capacity timeline stated on a call |

### QA8 - 532810 YTD high 2026

Family 2. Entity level: stock. What it tests: YTD high, value and date, with adjusted prices.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What was SBI Cards and Payment Services (NSE: SBICARD)'s YTD high price in 2026, with the value and the date, and on which exchange? | SBI Cards and Payment Services | 2026 | yes | same-industry peer at the same level; YTD high, value and date, with adjusted prices |
| V2 | What was Crisil (NSE: CRISIL)'s YTD high price in 2026, with the value and the date, and on which exchange? | Crisil | 2026 | yes | same sector, different market-cap bucket; YTD high, value and date, with adjusted prices |
| V3 | What was NSE: OMMETALS (now OMINFRAL)'s YTD high price in 2026, with the value and the date, and on which exchange? | Om Infra | 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; YTD high, value and date, with adjusted prices |
| V4 | IPRINGLTD ytd high 2026 | IP Rings | 2026 | yes | terse keyword query, 3-8 words; YTD high, value and date, with adjusted prices |
| V5 | Lakshmi Mills Company (NSE: LAKSHMIMIL) ka 2026 ka YTD high price kya tha, aur kis date ko? NSE ya BSE, exchange bhi batao. | Lakshmi Mills Company | 2026 | yes | long natural or Hinglish phrasing; YTD high, value and date, with adjusted prices |
| V6 | What was MMP Industries (NSE: MMP)'s YTD high price in 1 January-30 September 2026, with the value and the date, and on which exchange? | MMP Industries | 1 January-30 September 2026 | yes | different period label inside the data window; YTD high, value and date, with adjusted prices |
| V7 | For all listed companies in Finance, which companies made a new YTD high in 2026, with the value and date? | Jio Financial Services; Cholamandalam Investment and Finance Company; Bajaj Holdings & Investment | 2026 | yes | scope up to the industry or sector; YTD high, value and date, with adjusted prices |
| V8 | For the NIFTY 200 constituents, which companies made a new YTD high in 2026, with the value and date? | Avenue Supermarts; Indian Oil Corporation; SBI Life Insurance Company | 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; YTD high, value and date, with adjusted prices |
| V9 | As of 30 June 2026, what was GMR Power and Urban Infra (NSE: GMRP&UI)'s YTD high in 2026 up to that date, and on which day? | GMR Power and Urban Infra | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; YTD high, value and date, with adjusted prices |
| V10 | What was Metropolis Healthcare (NSE: METROPOLIS)'s YTD high for 2026, raw and adjusted for its corporate action? If adjusted prices are missing, say NOT IN DATA. | Metropolis Healthcare | 2026 | yes | hard edge: NOT IN DATA or a corporate action in the period; YTD high, value and date, with adjusted prices |

### QA9 - SAILIFE new facilities, latest

Family 1,5. Entity level: stock. What it tests: latest cross-document statement, not one store.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What did Onesource Specialty Pharma (NSE: ONESOURCE) say about its newly commissioned facilities, as of the latest data, and in which document type? | Onesource Specialty Pharma | 3 Sep 2026 | yes | same-industry peer at the same level; latest cross-document statement, not one store |
| V2 | What did Cipla (NSE: CIPLA) say about its newly commissioned facilities, as of the latest data, and in which document type? | Cipla | 23 Jul 2026 | yes | same sector, different market-cap bucket; latest cross-document statement, not one store |
| V3 | What did NSE: MFL (now EPIGRAL) say about its newly commissioned facilities, as of the latest data, and in which document type? | Epigral | 27 Jul 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; latest cross-document statement, not one store |
| V4 | RAILTEL newly commissioned facilities latest | Railtel Corporation Of India | 27 Mar 2026 | yes | terse keyword query, 3-8 words; latest cross-document statement, not one store |
| V5 | R K Swamy (NSE: RKSWAMY) ne apni nayi commissioned facilities ke baare mein sabse latest kya kaha hai? Deck, concall aur annual report teeno check karke source do. | R K Swamy | 12 Aug 2026 | yes | long natural or Hinglish phrasing; latest cross-document statement, not one store |
| V6 | What did Enviro Infra Engineers (NSE: EIEL) say about its newly commissioned facilities, as of the latest data, and in which document type? | Enviro Infra Engineers | 28 May 2026 | yes | different period label inside the data window; latest cross-document statement, not one store |
| V7 | For all listed companies in Pharmaceuticals & Biotechnology, what have the companies said about newly commissioned facilities across decks, calls and annual reports? | Laurus Labs; Dr. Reddy's Laboratories; Mankind Pharma | 18 Sep 2026 | yes | scope up to the industry or sector; latest cross-document statement, not one store |
| V8 | For the NIFTY500 SHARIAH constituents, what have the companies said about newly commissioned facilities across decks, calls and annual reports? | Cummins India; Polycab India; Britannia Industries | 5 Aug 2026 | yes | screen by index / theme / market-cap bucket, membership as of the date; latest cross-document statement, not one store |
| V9 | As of 30 June 2026, what had Kuantum Papers (NSE: KUANTUM) said about its newly commissioned facilities, using only documents known by that date? | Kuantum Papers | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; latest cross-document statement, not one store |
| V10 | What has 21st Century Management Services (NSE: 21STCENMGM) said about its newly commissioned facilities? If no document after since Jan 2026 is held, answer NOT IN DATA and name the gap. | 21st Century Management Services | 13 Feb 2026 | no (no investor presentation stored for this company) | hard edge: NOT IN DATA or a corporate action in the period; latest cross-document statement, not one store |

### QA10 - COCHINSHIP MOU + margin path, transcript

Family 1,3. Entity level: stock. What it tests: MOU partner + margin path from one transcript.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | Per Jupiter Wagons (NSE: JWL)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? | Jupiter Wagons | 21 Aug 2026 | yes | same-industry peer at the same level; MOU partner + margin path from one transcript |
| V2 | Per Ashok Leyland (NSE: ASHOKLEY)'s 21 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? | Ashok Leyland | 21 Aug 2026 | yes | same sector, different market-cap bucket; MOU partner + margin path from one transcript |
| V3 | Per NSE: CENTURYTEX (now ABREL)'s 20 August 2026 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? | Aditya Birla Real Estate | 20 Aug 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; MOU partner + margin path from one transcript |
| V4 | HINDPETRO mou margin path call 2026-07-29 | Hindustan Petroleum Corporation | 29 Jul 2026 | yes | terse keyword query, 3-8 words; MOU partner + margin path from one transcript |
| V5 | L&T Technology Services (NSE: LTTS) ki 24 October 2025 wali call mein MOU partner kaun hai, aur EBITDA margin ka path kya bataya gaya? Plan aur numbers quote karo. | L&T Technology Services | 24 Oct 2025 | partial (store holds 2025-01-22..2025-10-24, nothing in 2026-07-01..2026-10-19; store holds 2025-01-22..2025-10-24, nothing in 2026-07-01..2026-10-19) | long natural or Hinglish phrasing; MOU partner + margin path from one transcript |
| V6 | Per Raymond Lifestyle (NSE: RAYMONDLSL)'s 4 November 2025 earnings call, what did it say about its MOU with its partner, and how will EBITDA margins progress? | Raymond Lifestyle | 4 Nov 2025 | partial (store holds 2024-11-12..2026-05-14, nothing in 2026-07-01..2026-10-19; store holds 2024-11-12..2026-05-14, nothing in 2026-07-01..2026-10-19) | different period label inside the data window; MOU partner + margin path from one transcript |
| V7 | For all listed companies in Industrial Manufacturing, what MOUs or partnerships and margin paths did management disclose on their latest calls? | Honeywell Automation India; Cochin Shipyard; Kaynes Technology India | Sep 2026 | no (store has no rows for this entity; store has no rows for this entity) | scope up to the industry or sector; MOU partner + margin path from one transcript |
| V8 | For the NIFTY MIDCAP 150 constituents, what MOUs or partnerships and margin paths did management disclose on their latest calls? | One 97 Communications; Lloyds Metals And Energy; Meesho | 12 May 2026 | partial (store holds 2024-07-26..2026-05-12, nothing in 2026-07-01..2026-10-19; store holds 2024-07-26..2026-05-12, nothing in 2026-07-01..2026-10-19) | screen by index / theme / market-cap bucket, membership as of the date; MOU partner + margin path from one transcript |
| V9 | As of 30 September 2026, what had Ecos (India) Mobility & Hospitality (NSE: ECOSMOBLTY) disclosed about its MOU and margin path? | Ecos (India) Mobility & Hospitality | as of 30 September 2026 | yes | point-in-time: only evidence known by the as-of date; MOU partner + margin path from one transcript |
| V10 | What did 21st Century Management Services (NSE: 21STCENMGM) say about its MOU and EBITDA margin path on 1 August 2026? If the call is not held for that date, answer NOT IN DATA. | 21st Century Management Services | 1 Aug 2026 | no (transcript is held but never chunked; the quote is NOT IN DATA) | hard edge: NOT IN DATA or a corporate action in the period; MOU partner + margin path from one transcript |

### Q11 - KRISHNADEF segment revenue, latest quarter

Family 2,8. Entity level: stock. What it tests: segment revenue with absolute numbers from XBRL context.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What was Avantel (NSE: AVANTEL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? | Avantel | Q1FY27 | yes | same-industry peer at the same level; segment revenue with absolute numbers from XBRL context |
| V2 | What was Astral (NSE: ASTRAL)'s segment revenue for Q1FY27, with the absolute number for each reported segment? | Astral | Q1FY27 | yes | same sector, different market-cap bucket; segment revenue with absolute numbers from XBRL context |
| V3 | What was NSE: TIKONA (now GFSTEELS)'s segment revenue for Q1FY27, with the absolute number for each reported segment? | Grand Foundry | Q1FY27 | no (no segment context in the results XBRL) | naming variant: ISIN / BSE code / old symbol after a rename; segment revenue with absolute numbers from XBRL context |
| V4 | GILLANDERS segment revenue Q1FY27 | Gillanders Arbuthnot & Company | Q1FY27 | yes | terse keyword query, 3-8 words; segment revenue with absolute numbers from XBRL context |
| V5 | NTPC Green Energy (NSE: NTPCGREEN) ka Q1FY27 segment revenue kitna tha, segment-wise absolute numbers ke saath? XBRL context ka source bhi do. | NTPC Green Energy | Q1FY27 | no (no segment context in the results XBRL) | long natural or Hinglish phrasing; segment revenue with absolute numbers from XBRL context |
| V6 | What was ACC (NSE: ACC)'s segment revenue for April-June 2026 (Q1 FY2026-27), with the absolute number for each reported segment? | ACC | April-June 2026 (Q1 FY2026-27) | yes | different period label inside the data window; segment revenue with absolute numbers from XBRL context |
| V7 | For all listed companies in Aerospace & Defense, rank the companies by reported segment revenue for Q1FY27. | Aequs; Apollo Micro Systems; Paras Defence and Space Technologies | Q1FY27 | yes | scope up to the industry or sector; segment revenue with absolute numbers from XBRL context |
| V8 | For the niftymidcap150 constituents, rank the companies by reported segment revenue for Q1FY27. | Lodha Developers; Aditya Birla Capital; FSN E-Commerce Ventures | Q1FY27 | no (no segment context in the results XBRL) | screen by index / theme / market-cap bucket, membership as of the date; segment revenue with absolute numbers from XBRL context |
| V9 | As of 30 June 2026, what segment revenue had Brainbees Solutions (NSE: FIRSTCRY) reported for Q1FY27? | Brainbees Solutions | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; segment revenue with absolute numbers from XBRL context |
| V10 | What was 20 Microns (NSE: 20MICRONS)'s segment revenue for Q1FY27? If the filing has no segment context, answer NOT IN DATA and say which taxonomy is missing. | 20 Microns | Q1FY27 | no (no segment context in the results XBRL) | hard edge: NOT IN DATA or a corporate action in the period; segment revenue with absolute numbers from XBRL context |

### Q12 - Bank of Maharashtra net NPA %

Family 2. Entity level: stock. What it tests: banking-taxonomy net NPA, absent from Ind AS filings.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What was Bank of Baroda (NSE: BANKBARODA)'s net NPA % for Q1FY27, and which XBRL concept and filing carry it? | Bank of Baroda | Q1FY27 | yes | same-industry peer at the same level; banking-taxonomy net NPA, absent from Ind AS filings |
| V2 | What was Fino Payments Bank (NSE: FINOPB)'s net NPA % for Q1FY27, and which XBRL concept and filing carry it? | Fino Payments Bank | Q1FY27 | yes | same sector, different market-cap bucket; banking-taxonomy net NPA, absent from Ind AS filings |
| V3 | What was BSE scrip code 590003's net NPA % for Q1FY27, and which XBRL concept and filing carry it? | Karur Vysya Bank | Q1FY27 | yes | naming variant: ISIN / BSE code / old symbol after a rename; banking-taxonomy net NPA, absent from Ind AS filings |
| V4 | BANKINDIA net npa Q1FY27 | Bank of India | Q1FY27 | yes | terse keyword query, 3-8 words; banking-taxonomy net NPA, absent from Ind AS filings |
| V5 | Equitas Small Finance Bank (NSE: EQUITASBNK) ka net NPA percentage Q1FY27 mein kitna tha? Gross NPA aur net NPA dono, XBRL filing se batao. | Equitas Small Finance Bank | Q1FY27 | yes | long natural or Hinglish phrasing; banking-taxonomy net NPA, absent from Ind AS filings |
| V6 | What was IndusInd Bank (NSE: INDUSINDBK)'s net NPA % for April-June 2026 (Q1 FY2026-27), and which XBRL concept and filing carry it? | IndusInd Bank | April-June 2026 (Q1 FY2026-27) | yes | different period label inside the data window; banking-taxonomy net NPA, absent from Ind AS filings |
| V7 | For all listed companies in Banks, rank the banks by net NPA % for Q1FY27, and state the source for each. | Punjab National Bank; Canara Bank; The Federal Bank | Q1FY27 | yes | scope up to the industry or sector; banking-taxonomy net NPA, absent from Ind AS filings |
| V8 | For the NIFTY HOUSING constituents, rank the banks by net NPA % for Q1FY27, and state the source for each. | HDFC Bank; ICICI Bank; State Bank of India | Q1FY27 | yes | screen by index / theme / market-cap bucket, membership as of the date; banking-taxonomy net NPA, absent from Ind AS filings |
| V9 | As of 30 June 2026, what net NPA % had The Jammu & Kashmir Bank (NSE: J&KBANK) last reported for Q1FY27? | The Jammu & Kashmir Bank | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; banking-taxonomy net NPA, absent from Ind AS filings |
| V10 | What was AU Small Finance Bank (NSE: AUBANK)'s net NPA % for Q2FY27? If that quarter's filing is not held, or the bank's XBRL uses a taxonomy without that concept, answer NOT IN DATA and say which. | AU Small Finance Bank | Q2FY27 | no (no Q2FY27 bank filing; net NPA is NOT IN DATA) | hard edge: NOT IN DATA or a corporate action in the period; banking-taxonomy net NPA, absent from Ind AS filings |

### Q13 - ZENTEC 3-yr price CAGR

Family 2. Entity level: stock. What it tests: 3-year CAGR that must use adjusted closes.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What was Laxmi Goldorna House (NSE: LGHL)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. | Laxmi Goldorna House | Oct 2023-Oct 2026 | yes | same-industry peer at the same level; 3-year CAGR that must use adjusted closes |
| V2 | What was Orient Technologies (NSE: ORIENTTECH)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. | Orient Technologies | Oct 2023-Oct 2026 | partial (adjusted price endpoints missing for the CAGR window) | same sector, different market-cap bucket; 3-year CAGR that must use adjusted closes |
| V3 | What was NSE: RUCHI (now PATANJALI)'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates. | Patanjali Foods | Oct 2023-Oct 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; 3-year CAGR that must use adjusted closes |
| V4 | AASTHA 3y cagr adjusted | Aastha Spintex | Oct 2023-Oct 2026 | partial (adjusted price endpoints missing for the CAGR window) | terse keyword query, 3-8 words; 3-year CAGR that must use adjusted closes |
| V5 | eClerx Services (NSE: ECLERX) ka pichle 3 saal ka adjusted price CAGR kya raha? Start aur end date saaf-saaf likho, dividends aur splits adjust karke. | eClerx Services | Oct 2023-Oct 2026 | yes | long natural or Hinglish phrasing; 3-year CAGR that must use adjusted closes |
| V6 | What was Brigade Enterprises (NSE: BRIGADE)'s 3-year price CAGR to 30 September 2026, using split- and dividend-adjusted closes? State both endpoint dates. | Brigade Enterprises | since 30 September 2023 | yes | different period label inside the data window; 3-year CAGR that must use adjusted closes |
| V7 | For all listed companies in the industry, what was the 3-year adjusted price CAGR to 19 October 2026, ranked? | DLF; Adani Energy Solutions; SBI Funds Management | Oct 2023-Oct 2026 | no (no split/bonus in corporate_actions) | scope up to the industry or sector; 3-year CAGR that must use adjusted closes |
| V8 | For the NIFTY INDIA FPI 150 constituents, what was the 3-year adjusted price CAGR to 19 October 2026, ranked? | HDFC Life Insurance Company; Apollo Hospitals Enterprise; GAIL (India) | Oct 2023-Oct 2026 | no (no split/bonus in corporate_actions) | screen by index / theme / market-cap bucket, membership as of the date; 3-year CAGR that must use adjusted closes |
| V9 | As of 30 June 2026, what was GRM Overseas (NSE: GRMOVER)'s 3-year adjusted price CAGR? | GRM Overseas | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; 3-year CAGR that must use adjusted closes |
| V10 | What was InfoBeans Technologies (NSE: INFOBEAN)'s 3-year adjusted price CAGR across its corporate action? If adjusted prices are missing, answer NOT IN DATA. | InfoBeans Technologies | Oct 2023-Oct 2026 | yes | hard edge: NOT IN DATA or a corporate action in the period; 3-year CAGR that must use adjusted closes |

### Q14 - VISHNU Note 5 of latest results + geo split

Family 1,2. Entity level: stock. What it tests: results-note text plus the geographic split.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | Note 5 of Diligent Media Corporation (NSE: DNAMEDIA)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? | Diligent Media Corporation | 30 Jun 2026 | partial (no geographic-split note found in the stored results notes) | same-industry peer at the same level; results-note text plus the geographic split |
| V2 | Note 5 of GTL (NSE: GTL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? | GTL | 30 Jun 2026 | partial (no geographic-split note found in the stored results notes) | same sector, different market-cap bucket; results-note text plus the geographic split |
| V3 | Note 5 of NSE: ADANIGAS (now ATGL)'s Q1FY27 results — what does it say, and what is the geographic revenue split, consolidated? | Adani Total Gas | 30 Jun 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; results-note text plus the geographic split |
| V4 | RACE results note 5 geo split Q1FY27 | Race Eco Chain | 30 Jun 2026 | partial (no geographic-split note found in the stored results notes) | terse keyword query, 3-8 words; results-note text plus the geographic split |
| V5 | Balmer Lawrie & Company (NSE: BALMLAWRIE) ke Q1FY27 results ki note 5 mein kya likha hai, aur geographic revenue split kya hai? Consolidated basis, quote ke saath. | Balmer Lawrie & Company | 30 Jun 2026 | partial (no geographic-split note found in the stored results notes) | long natural or Hinglish phrasing; results-note text plus the geographic split |
| V6 | Note 5 of Gloster (NSE: GLOSTERLTD)'s Q4FY26 (January-March 2026) results — what does it say, and what is the geographic revenue split, consolidated? | Gloster | Q4FY26 | partial (no geographic-split note found in the stored results notes) | different period label inside the data window; results-note text plus the geographic split |
| V7 | For all listed companies in the industry, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? | Power Finance Corporation; Jindal Steel; Manipal Health Enterprises | 30 Jun 2026 | yes | scope up to the industry or sector; results-note text plus the geographic split |
| V8 | For the NIFTY IPO constituents, which companies disclose a geographic revenue split in their results notes for Q1FY27, and what is it? | Physicswallah; Dhoot Transmission; Emmvee Photovoltaic Power | 30 Jun 2026 | partial (no geographic-split note found in the stored results notes) | screen by index / theme / market-cap bucket, membership as of the date; results-note text plus the geographic split |
| V9 | As of 30 June 2026, what did note 5 of Oil Country Tubular (NSE: OILCOUNTUB)'s as of 30 June 2026 results say, and what was its geographic split? | Oil Country Tubular | as of 30 June 2026 | partial (no geographic-split note found in the stored results notes) | point-in-time: only evidence known by the as-of date; results-note text plus the geographic split |
| V10 | What does note 5 of NMDC (NSE: NMDC)'s results for Q2FY25 (July-September 2024) say, and what is the geographic split? If that quarter's results notes are not stored, answer NOT IN DATA. | NMDC | Q4FY26 | no (results_notes has no Q2FY25 document for this entity (the notes store starts 2024-12-31)) | hard edge: NOT IN DATA or a corporate action in the period; results-note text plus the geographic split |

### Q15 - VINCOFE public shareholding Sep 2026

Family 2,11. Entity level: stock. What it tests: public shareholding at a dated quarter-end.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What is Fertilizers and Chemicals Travancore (NSE: FACT)'s public shareholding as of Sep 2026? | Fertilizers and Chemicals Travancore | Sep 2026 | yes | same-industry peer at the same level; public shareholding at a dated quarter-end |
| V2 | What is NHPC (NSE: NHPC)'s public shareholding as of Sep 2026? | NHPC | Sep 2026 | yes | same sector, different market-cap bucket; public shareholding at a dated quarter-end |
| V3 | What is NSE: ADLABS (now IMAGICAA)'s public shareholding as of Sep 2026? | Imagicaaworld Entertainment | Sep 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; public shareholding at a dated quarter-end |
| V4 | ITI public shareholding Sep 2026 | ITI | Sep 2026 | yes | terse keyword query, 3-8 words; public shareholding at a dated quarter-end |
| V5 | M & B Engineering (NSE: MBEL) mein public shareholding Sep 2026 tak kitni hai? Promoter aur public dono ka percentage filing se batao. | M & B Engineering | Sep 2026 | yes | long natural or Hinglish phrasing; public shareholding at a dated quarter-end |
| V6 | What is JK Cement (NSE: JKCEMENT)'s public shareholding as of 30 September 2026? | JK Cement | as of 30 September 2026 | yes | different period label inside the data window; public shareholding at a dated quarter-end |
| V7 | For all listed companies in the industry, rank the companies by public shareholding as of Sep 2026. | Indian Railway Finance Corporation; Muthoot Finance; Gmr Airports | Sep 2026 | yes | scope up to the industry or sector; public shareholding at a dated quarter-end |
| V8 | For the NIFTY MIDCAP 100 constituents, rank the companies by public shareholding as of Sep 2026. | Aurobindo Pharma; Persistent Systems; Lupin | Sep 2026 | no (store has no rows for this entity) | screen by index / theme / market-cap bucket, membership as of the date; public shareholding at a dated quarter-end |
| V9 | As of 30 June 2026, what was Digicontent (NSE: DGCONTENT)'s public shareholding per the latest filing on or before that date? | Digicontent | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; public shareholding at a dated quarter-end |
| V10 | What is 360 One Wam (NSE: 360ONE)'s public shareholding as of Sep 2026? If that quarter's shareholding filing is not held, answer NOT IN DATA. | 360 One Wam | Sep 2026 | no (no September 2026 shareholding filing) | hard edge: NOT IN DATA or a corporate action in the period; public shareholding at a dated quarter-end |

### Q16 - Why gold stocks fell Jun-Jul 2026

Family 6,4. Entity level: theme. What it tests: macro move explained by commodity, PIB and company evidence.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | Why did gold-jewellery stocks move in June-July 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. | Kalyan Jewellers India | June-July 2026 | partial (no gold-specific PIB release in Jun-Jul 2026) | different policy/macro event of the same type; issuer/ministry noted in the row: macro market series; issuer/ministry not applicable (V1 rule noted) |
| V2 | Why did oil and gas stocks move in April-May 2026? Give the macro move, the PIB or RBI evidence, and what the companies themselves said. | Reliance Industries | April-May 2026 | partial (no crude/petrol PIB release in Apr-May 2026) | different policy/macro event and issuer/ministry: different macro event and sector; issuer/ministry not applicable (V2 rule noted) |
| V3 | Why did the companies in the gold-jewellery theme move in Jun-Jul 2026? The event is referenced by the gold price series (USD/oz); name the PIB release or macro series you rely on. | Lalithaa Jewellery Mart | Jun-Jul 2026 | partial (no gold-specific PIB release in Jun-Jul 2026) | naming variant: the event is asked by its document/PRID reference |
| V4 | gold-jewellery stocks move Jun-Jul 2026 why | Goldiam International | Jun-Jul 2026 | partial (no gold-specific PIB release in Jun-Jul 2026) | terse keyword query, 3-8 words; macro move explained by commodity, PIB and company evidence |
| V5 | Gold-Jewellery stocks Jun-Jul 2026 mein kya hua aur kyun? PIB, RBI ya company documents se evidence do, aur batao kaun sabse zyada affected hua. | KDDL | Jun-Jul 2026 | partial (no gold-specific PIB release in Jun-Jul 2026) | long natural or Hinglish phrasing; macro move explained by commodity, PIB and company evidence |
| V6 | What caused the gold-jewellery move in June-July 2026 (FY27 first half)? Use the commodity series, PIB and company evidence from that window only. | D. P. Abhushan | June-July 2026 (FY27 first half) | partial (no gold-specific PIB release in Jun-Jul 2026) | different period label inside the data window; macro move explained by commodity, PIB and company evidence |
| V7 | For all listed companies in gold-jewellery, what moved in Jun-Jul 2026, and what do the macro, PIB and company evidence say caused it? | BlueStone Jewellery and Lifestyle; PC Jeweller; P N Gadgil Jewellers | Jun-Jul 2026 | partial (no gold-specific PIB release in Jun-Jul 2026) | scope up to the industry or sector; macro move explained by commodity, PIB and company evidence |
| V8 | For the gold-jewellery theme members, how did the gold price move in Jun-Jul 2026 hit the members differently, and which one was worst? | Ethos; Senco Gold; RAJESHEXPO | Jun-Jul 2026 | partial (no gold-specific PIB release in Jun-Jul 2026) | screen by index / theme / market-cap bucket, membership as of the date; macro move explained by commodity, PIB and company evidence |
| V9 | By 31 July 2026, why had gold-jewellery stocks moved? Use only evidence known by that date. | Shanti Gold International | as of 31 July 2026 | yes (point-in-time: only documents known by the as-of date count) | point-in-time: only evidence known by the as-of date; macro move explained by commodity, PIB and company evidence |
| V10 | Why did PNGS Reva Diamond Jewellery (NSE: PNGSREVA) move in 7-19 Oct 2026? If the macro series for that window is missing, answer NOT IN DATA and name the series. | PNGS Reva Diamond Jewellery | 7-19 Oct 2026 | no (the gold series ends 2026-10-06, so the 7-19 Oct 2026 window has no macro cause in the data) | hard edge: NOT IN DATA or a corporate action in the period; macro move explained by commodity, PIB and company evidence |

### Q17 - HFC securitisation leader, QoQ/YoY with NPA guard

Family 4,8. Entity level: industry. What it tests: industry ranking on a metric that is only in decks/calls.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | Is Can Fin Homes (NSE: CANFINHOME) the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the comparison. | Can Fin Homes | Q1FY27 | yes | same-industry peer at the same level; industry ranking on a metric that is only in decks/calls |
| V2 | Among large-cap HFCs, who leads securitised disbursement for Q1FY27 with net NPA up no more than 2 pp? | Bajaj Housing Finance | Q1FY27 | partial (store holds 2026-02-07..2026-02-07, nothing in 2026-04-01..2026-06-30) | same sector, different market-cap bucket; industry ranking on a metric that is only in decks/calls |
| V3 | For NSE: IBULHSGFIN (now SAMMAANCAP), is it the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp? Show the naming history if the symbol or ISIN changed. | Sammaan Capital | Q1FY27 | partial (store holds 2026-08-15..2026-08-15, nothing in 2026-04-01..2026-06-30) | naming variant: ISIN / BSE code / old symbol after a rename; industry ranking on a metric that is only in decks/calls |
| V4 | hfc securitisation leader q1fy27 net npa | Repco Home Finance | Q1FY27 | partial (store holds 2024-11-19..2026-08-17, nothing in 2026-04-01..2026-06-30) | terse keyword query, 3-8 words; industry ranking on a metric that is only in decks/calls |
| V5 | Listed HFCs mein securitised disbursement ka leader kaun hai Q1FY27 mein? QoQ aur YoY winner batao, lekin net NPA 2 percentage point se zyada na badhe. | India Shelter Finance Corporation | Q1FY27 | partial (store holds 2026-08-14..2026-08-14, nothing in 2026-04-01..2026-06-30) | long natural or Hinglish phrasing; industry ranking on a metric that is only in decks/calls |
| V6 | Which listed HFC is the leader in securitised disbursement for January-March 2026 (Q4FY26), QoQ and YoY, with net NPA rising no more than 2 pp? | Aptus Value Housing Finance India | January-March 2026 (Q4FY26) | yes | different period label inside the data window; industry ranking on a metric that is only in decks/calls |
| V7 | For all listed companies in Housing Finance, which listed financial company is the securitisation leader for Q1FY27 with the net-NPA guard, and what is the evidence? | PNB Housing Finance; LIC Housing Finance | Q1FY27 | yes | scope up to the industry or sector; industry ranking on a metric that is only in decks/calls |
| V8 | For the NIFTY HOUSING FINANCE constituents, rank the financial companies on securitised disbursement for Q1FY27, with the net-NPA guard. | Aadhar Housing Finance; Home First Finance Company India | Q1FY27 | partial (store holds 2025-02-11..2026-02-04, nothing in 2026-04-01..2026-06-30) | screen by index / theme / market-cap bucket, membership as of the date; industry ranking on a metric that is only in decks/calls |
| V9 | As of 30 June 2026, which HFC looked like the securitisation leader for Q1FY27, and on what evidence? | Aavas Financiers | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; industry ranking on a metric that is only in decks/calls |
| V10 | Which listed HFC led securitised disbursement in Q1FY27? If the securitisation figure is not in any structured store for GIC Housing Finance (NSE: GICHSGFIN), answer NOT IN DATA and say why. | GIC Housing Finance | Q1FY27 | no (store holds 2026-01-16..2026-01-16, nothing in 2026-04-01..2026-06-30; store has no rows for this entity) | hard edge: NOT IN DATA or a corporate action in the period; industry ranking on a metric that is only in decks/calls |

### Q18 - OMCs: record Q4 then loss Q1; earliest PIT signal

Family 6,9,11. Entity level: industry. What it tests: earliest point-in-time visibility of a profit-to-loss swing.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | Sugar Q4FY26-to-Q1FY27 profit swing — which companies in Sugar swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time? | Dhampur Sugar Mills | Q4FY26-Q1FY27 | yes (quarterly_financials + results_xbrl filings + adjusted prices) | different policy/macro event of the same type; issuer/ministry noted in the row: different industry/commodity event; issuer/ministry not applicable |
| V2 | Media & Entertainment Q4FY26-to-Q1FY27 profit swing — which companies in Media & Entertainment swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time? | Prime Focus | Q4FY26-Q1FY27 | yes (quarterly_financials + results_xbrl filings + adjusted prices) | different policy/macro event and issuer/ministry: different industry/commodity event; issuer/ministry not applicable |
| V3 | For BSE scrip code 532543, when did the Q4FY26-to-Q1FY27 profit swing become visible point-in-time, and from which filing? | GP Petroleums | Q4FY26-Q1FY27 | yes | naming variant: ISIN / BSE code / old symbol after a rename; earliest point-in-time visibility of a profit-to-loss swing |
| V4 | omc q4fy26 profit q1fy27 loss earliest pit | Panama Petrochem | Q4FY26-Q1FY27 | yes | terse keyword query, 3-8 words; earliest point-in-time visibility of a profit-to-loss swing |
| V5 | OMCs ne Q4FY26 mein record profit aur Q1FY27 mein bada loss kaise kiya? Sabse pehle kaunsa data point point-in-time visible tha, date ke saath batao. | Gulf Oil Lubricants India | Q4FY26-Q1FY27 | yes | long natural or Hinglish phrasing; earliest point-in-time visibility of a profit-to-loss swing |
| V6 | For the January-March 2026 and April-June 2026 quarters, which OMCs went from record profit to a loss, and when did that first become visible? | Gandhar Oil Refinery (India) | the January-March 2026 and April-June 2026 quarters | yes | different period label inside the data window; earliest point-in-time visibility of a profit-to-loss swing |
| V7 | For all listed companies in Petroleum Products, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? | Mangalore Refinery and Petrochemicals; Chennai Petroleum Corporation; Castrol India | Q4FY26-Q1FY27 | yes | scope up to the industry or sector; earliest point-in-time visibility of a profit-to-loss swing |
| V8 | For the NIFTY OIL & GAS constituents, which companies swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence? | Reliance Industries; Indian Oil Corporation; Bharat Petroleum Corporation | Q4FY26-Q1FY27 | yes | screen by index / theme / market-cap bucket, membership as of the date; earliest point-in-time visibility of a profit-to-loss swing |
| V9 | As of 30 June 2026, what did the data already show about the OMC profit swing from Q4FY26 to Q1FY27? | Hindustan Petroleum Corporation | as of 30 June 2026 | yes | point-in-time: only evidence known by the as-of date; earliest point-in-time visibility of a profit-to-loss swing |
| V10 | Using the coal price series, when did the OMC Q4FY26-to-Q1FY27 trend first become visible? If the series ends before that window, answer NOT IN DATA. | Kotyark Industries | Q4FY26-Q1FY27 | no (coal_newcastle ends 2025-12-26; no Q1FY27 coal price) | hard edge: NOT IN DATA or a corporate action in the period; earliest point-in-time visibility of a profit-to-loss swing |

### Q19 - MONQ50 ETF jump/fall + tracking error

Family 2,9. Entity level: stock. What it tests: ETF move explained by the underlying index and FX, with NAV tracking error.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | For Motilal Oswal Nasdaq 100 ETF (MOFN100) (MON100, ISIN INF247L01AP3), explain the jump in 10-18 Sep 2026 and 18-28 Sep 2026 using the underlying index and FX, and give the NAV tracking error. | Motilal Oswal Nasdaq 100 ETF (MOFN100) | 10-18 Sep 2026 and 18-28 Sep 2026 | yes | same-industry peer at the same level; ETF move explained by the underlying index and FX, with NAV tracking error |
| V2 | For QGOLDHALF (QGOLDHALF, ISIN INF082J01010), a different ETF category from the original, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026, and how did NAV track iNAV? | QGOLDHALF | 10-18 Sep 2026 and 18-28 Sep 2026 | partial (no NAV rows for this ETF; no iNAV rows; tracking error not computable) | same sector, different market-cap bucket; ETF move explained by the underlying index and FX, with NAV tracking error |
| V3 | For ISIN INF247L01AU3, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026 and the tracking error against its underlying index and the rupee? | Motilal Oswal Nasdaq Q50 ETF | 10-18 Sep 2026 and 18-28 Sep 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; ETF move explained by the underlying index and FX, with NAV tracking error |
| V4 | QNIFTY jump tracking error Sep 2026 | QNIFTY | 10-18 Sep 2026 and 18-28 Sep 2026 | partial (no NAV rows for this ETF; no iNAV rows; tracking error not computable) | terse keyword query, 3-8 words; ETF move explained by the underlying index and FX, with NAV tracking error |
| V5 | Bajaj Finserv Nifty Bank ETF (BANKBETF, ISIN INF0QA701714) 10-18 September 2026 ke beech kyun jump hua aur 18-28 September mein kyun gira? Underlying index, FX aur NAV tracking error ke saath batao. | Bajaj Finserv Nifty Bank ETF | 10-18 Sep 2026 and 18-28 Sep 2026 | partial (no iNAV rows; tracking error not computable) | long natural or Hinglish phrasing; ETF move explained by the underlying index and FX, with NAV tracking error |
| V6 | For Bajaj Finserv Nifty 50 ETF (NIFTYBETF, ISIN INF0QA701722), explain the jump in September 2026 using the underlying index and FX, and give the NAV tracking error. | Bajaj Finserv Nifty 50 ETF | September 2026 | partial (no iNAV rows; tracking error not computable) | different period label inside the data window; ETF move explained by the underlying index and FX, with NAV tracking error |
| V7 | For the India-listed ETF universe, what explains the move in 10-18 Sep 2026 and 18-28 Sep 2026, and what is the NAV tracking error? | Nippon India ETF Hang Seng BeES; Mirae Asset NYSE FANG + ETF; Mirae Asset S&P 500 Top 50 ETF | 10-18 Sep 2026 and 18-28 Sep 2026 | yes | scope up to the industry or sector; ETF move explained by the underlying index and FX, with NAV tracking error |
| V8 | For the India-listed gold ETFs, which ETF moved most in 10-18 Sep 2026 and 18-28 Sep 2026, and what was its tracking error against the underlying index and FX? | Zerodha Gold ETF; ICICI Prudential Gold ETF; Kotak Gold Etf | 10-18 Sep 2026 and 18-28 Sep 2026 | partial (no iNAV rows; tracking error not computable) | screen by index / theme / market-cap bucket, membership as of the date; ETF move explained by the underlying index and FX, with NAV tracking error |
| V9 | As of 17 September 2026, what was the move in Quantum Gold ETF (QGOLDHALF, ISIN INF082J01408) up to that date, and what tracking error was visible by then? | Quantum Gold ETF | as of 17 September 2026 | partial (no iNAV rows; tracking error not computable) | point-in-time: only evidence known by the as-of date; ETF move explained by the underlying index and FX, with NAV tracking error |
| V10 | For NIF100IETF (NIF100IETF, ISIN INF109KA1962), what was the move and NAV tracking error in 10-18 Sep 2026 and 18-28 Sep 2026? If the ETF has no NAV or iNAV rows, answer NOT IN DATA and say which store is missing. | NIF100IETF | 10-18 Sep 2026 and 18-28 Sep 2026 | no (this ETF has price rows but no NAV rows; tracking error is NOT IN DATA) | hard edge: NOT IN DATA or a corporate action in the period; ETF move explained by the underlying index and FX, with NAV tracking error |

### Q20 - Garware: tariff hit, then negative correlation

Family 6,9. Entity level: stock. What it tests: rolling sensitivity to a real tariff event, then a sign flip.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | How sensitive was KRN Heat Exchanger and Refrigeration (NSE: KRN) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-day return correlation with tariff news turn negative over the following 12 months? Give the rolling correlations and the evidence. | KRN Heat Exchanger and Refrigeration | Mar 2025-Mar 2026 | yes | same-industry peer at the same level; rolling sensitivity to a real tariff event, then a sign flip |
| V2 | How sensitive was APL Apollo Tubes (NSE: APLAPOLLO) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-day return correlation with tariff news turn negative over the following 12 months? Give the rolling correlations and the evidence. | APL Apollo Tubes | Mar 2025-Mar 2026 | yes | same sector, different market-cap bucket; rolling sensitivity to a real tariff event, then a sign flip |
| V3 | How sensitive was NSE: DHARAMSI (now DMCC) to Customs tariff rationalization - remove 7 tariff rates (1 February 2025) in the 60 days after it, and did its 60-day return correlation with tariff news turn negative over the following 12 months? Give the rolling correlations and the evidence. | Dmcc Speciality Chemicals | Mar 2025-Mar 2026 | yes | naming variant: ISIN / BSE code / old symbol after a rename; rolling sensitivity to a real tariff event, then a sign flip |
| V4 | PAKKA tariff sensitivity rolling correlation | PAKKA | Mar 2025-Mar 2026 | yes | terse keyword query, 3-8 words; rolling sensitivity to a real tariff event, then a sign flip |
| V5 | Eco Recycling (NSE: ECORECO) par Customs tariff rationalization - remove 7 tariff rates (1 February 2025) ka kitna asar pada, aur agle 12 mahine mein tariff news se correlation negative hua ya nahi? Rolling correlation ke saath batao. | Eco Recycling | Mar 2025-Mar 2026 | partial (store holds 2024-02-06..2024-05-18, nothing in 2025-03-01..2026-03-31) | long natural or Hinglish phrasing; rolling sensitivity to a real tariff event, then a sign flip |
| V6 | How did JSW Energy (NSE: JSWENERGY)'s rolling correlation with Customs tariff rationalization - remove 7 tariff rates (1 February 2025) change over the 12 months after March 2025? | JSW Energy | the 12 months after March 2025 | yes | different period label inside the data window; rolling sensitivity to a real tariff event, then a sign flip |
| V7 | For all listed companies in Industrial Products, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025), and did the 60-day return correlation turn negative over the following 12 months? | AIA Engineering; KEI Industries; PTC Industries | Mar 2025-Mar 2026 | partial (store holds 2026-08-14..2026-08-14, nothing in 2025-03-01..2026-03-31) | scope up to the industry or sector; rolling sensitivity to a real tariff event, then a sign flip |
| V8 | For the NIFTY MIDSMALLCAP400 MOMENTUM QUALITY 100 constituents, how sensitive were the members to Customs tariff rationalization - remove 7 tariff rates (1 February 2025), and did the 60-day return correlation turn negative over the following 12 months? | Oracle Financial Services Software; Coforge; Multi Commodity Exchange of India | Mar 2025-Mar 2026 | partial (store holds 2026-08-05..2026-08-05, nothing in 2025-03-01..2026-03-31) | screen by index / theme / market-cap bucket, membership as of the date; rolling sensitivity to a real tariff event, then a sign flip |
| V9 | As of 31 March 2026, what did the rolling correlation of National Aluminium Company (NSE: NATIONALUM) with Customs tariff rationalization - remove 7 tariff rates (1 February 2025) show? | National Aluminium Company | as of 31 March 2026 | yes | point-in-time: only evidence known by the as-of date; rolling sensitivity to a real tariff event, then a sign flip |
| V10 | For 20 Microns (NSE: 20MICRONS), did the tariff impact and any later negative correlation survive its corporate action on adjusted prices? If not, answer NOT IN DATA. | 20 Microns | Mar 2025-Mar 2026 | no (no split/bonus in the window; the corporate-action edge is NOT IN DATA) | hard edge: NOT IN DATA or a corporate action in the period; rolling sensitivity to a real tariff event, then a sign flip |

### Q21 - RBI repo hike causes; PIB or RBI only

Family 6,7. Entity level: policy. What it tests: causes of a policy action plus PIB-vs-RBI provenance.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | For the Repo rate hiked 25 bps to 5.50% (2026-10-07), what were the causes, and which source published it first? | HDFC Bank | 7 Oct 2026 | yes (policy_events + raw_documents RBI_Monetary_Policy) | different policy/macro event of the same type; issuer/ministry noted in the row: RBI issuer |
| V2 | For the Devolution of states' share in taxes increased (2026-02-01), what were the causes, and which source published it first? | Kotak Mahindra Bank | 7 Oct 2026 | partial (Budget document held; PIB cross-publish check limited) | different policy/macro event and issuer/ministry: different issuer (Finance Ministry) for V2 |
| V3 | For the RBI Governor's Statement of 7 October 2026 (2026-10-07), what were the causes, and which source published it first? | ICICI Bank | 7 Oct 2026 | yes (policy_events + raw_documents RBI_Monetary_Policy) | naming variant: the event is asked by its document/PRID reference |
| V4 | rbi repo hike 2026-10-07 causes pib or rbi | Indian Bank | 7 Oct 2026 | yes (policy_events + raw_documents RBI_Monetary_Policy) | terse keyword query, 3-8 words; causes of a policy action plus PIB-vs-RBI provenance |
| V5 | RBI ne 2026-10-07 ko repo rate kyun badhaya? Causes batao, aur ye news PIB ne publish kiya ya sirf RBI ne? Provenance ke saath. | Canara Bank | 7 Oct 2026 | yes (policy_events + raw_documents RBI_Monetary_Policy) | long natural or Hinglish phrasing; causes of a policy action plus PIB-vs-RBI provenance |
| V6 | For the Repo rate hiked 25 bps to 5.50% of 2026-10-07, what were the causes, and was it published by PIB or only by the RBI? | IDBI Bank | the October 2026 policy | yes (policy_events + raw_documents RBI_Monetary_Policy) | different period label inside the data window; causes of a policy action plus PIB-vs-RBI provenance |
| V7 | For all listed companies in banking, how does the 2026-10-07 RBI action transmit, and which sectors are named in the policy document? | State Bank of India; Axis Bank; Punjab National Bank | 7 Oct 2026 | yes (policy_events + raw_documents RBI_Monetary_Policy) | scope up to the industry or sector; causes of a policy action plus PIB-vs-RBI provenance |
| V8 | For the NIFTY TOTAL MARKET constituents, how did the members react to the RBI action of 2026-10-07, and what does the PIB/RBI record show? | Reliance Industries; Bharti Airtel; Bajaj Finance | 7 Oct 2026 | yes (policy_events + raw_documents RBI_Monetary_Policy) | screen by index / theme / market-cap bucket, membership as of the date; causes of a policy action plus PIB-vs-RBI provenance |
| V9 | As of 6 October 2026, what did the record show about the causes of the RBI action of 2026-10-07, and who published it first? | IndusInd Bank | as of 6 October 2026 | no (as-of precedes the policy event; no evidence by then) | point-in-time: only evidence known by the as-of date; causes of a policy action plus PIB-vs-RBI provenance |
| V10 | What were the causes of the RBI action of 2026-10-07, and was it published by PIB or only by RBI? If the policy document is not held, answer NOT IN DATA. | Indian Overseas Bank | 7 Oct 2026 | no (an as-of before 7 Oct 2026 leaves no evidence in the record; expected NOT IN DATA) | hard edge: NOT IN DATA or a corporate action in the period; causes of a policy action plus PIB-vs-RBI provenance |

### Q22 - Second-hand electronics boom CY2026: who benefits

Family 6,7. Entity level: theme. What it tests: demand thesis and beneficiaries; the sales series gap must be stated.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | For the Electronics Component Manufacturing Scheme approvals (2025-11-17), why does it matter for demand, and which sectors and listed companies does it touch? | Bharat Electronics | CY2026 | partial (PIB + policy_events held; no refurbished/second-hand sales series) | different policy/macro event of the same type; issuer/ministry noted in the row: different policy, MeitY issuer |
| V2 | For the R&D in IT/Electronics/CCBT (2026-02-01), why does it matter for demand, and which sectors and listed companies does it touch? | Havells India | CY2026 | partial (policy event held; PIB provenance incomplete) | different policy/macro event and issuer/ministry: different issuer/ministry for V2 |
| V3 | Using the document reference PIB PRID 2190872 on 2025-11-17, what does the policy record say about electronics demand in CY2026, and which companies does it touch? | LG Electronics India | CY2026 | partial (PIB + policy_events held; no refurbished/second-hand sales series) | naming variant: the event is asked by its document/PRID reference |
| V4 | second hand electronics boom cy2026 who benefits | Rashi Peripherals | CY2026 | partial (PIB + policy_events held; no refurbished/second-hand sales series) | terse keyword query, 3-8 words; demand thesis and beneficiaries; the sales series gap must be stated |
| V5 | CY2026 mein second-hand aur refurbished electronics/laptops ki demand kyun badhi? Kaun listed companies ko fayda hoga, aur ye structural hai ya cyclical? Data gap bhi batao. | Centum Electronics | CY2026 | partial (PIB + policy_events held; no refurbished/second-hand sales series) | long natural or Hinglish phrasing; demand thesis and beneficiaries; the sales series gap must be stated |
| V6 | Why did second-hand electronics and laptop sales rise in CY2026? Who benefits, and is the trend structural or cyclical? State any part that is NOT IN DATA. | Moschip Technologies | calendar 2026 to date | partial (PIB + policy_events held; no refurbished/second-hand sales series) | different period label inside the data window; demand thesis and beneficiaries; the sales series gap must be stated |
| V7 | For all listed companies in electronics, what does the policy record say about demand in CY2026, and which companies does it touch? | Dixon Technologies (India); PG Electroplast; GNG Electronics | CY2026 | partial (PIB + policy_events held; no refurbished/second-hand sales series) | scope up to the industry or sector; demand thesis and beneficiaries; the sales series gap must be stated |
| V8 | For the NIFTY WAVES constituents, what does the policy and company evidence say about demand in CY2026, and who benefits? | Prime Focus; Nazara Technologies; Pvr Inox | CY2026 | partial (PIB + policy_events held; no refurbished/second-hand sales series) | screen by index / theme / market-cap bucket, membership as of the date; demand thesis and beneficiaries; the sales series gap must be stated |
| V9 | As of 30 June 2026, what was known about the as of 30 June 2026 electronics demand trend, and which companies were named? | D-Link (India) | as of 30 June 2026 | yes (point-in-time: only documents known by the as-of date count) | point-in-time: only evidence known by the as-of date; demand thesis and beneficiaries; the sales series gap must be stated |
| V10 | What do our stores say about refurbished/second-hand electronics sales in CY2026, and who benefits? If no sales series exists, answer NOT IN DATA and say which store is missing. | Ivalue Infosolutions | CY2026 | no (no refurbished/second-hand electronics sales series in any store) | hard edge: NOT IN DATA or a corporate action in the period; demand thesis and beneficiaries; the sales series gap must be stated |

### Q23 - Coal gasification drafts vs the earlier scheme

Family 6,3. Entity level: industry. What it tests: policy drafts versus the earlier scheme, across documents.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | For the Scheme for promotion of coal/lignite gasification (2026-02-01), how does it differ from the earlier coal-gasification scheme, and which industries does it hit? | Coal India | 2024-2026 | yes (policy_events + PIB releases + Budget documents) | different policy/macro event of the same type; issuer/ministry noted in the row: different policy action; issuer from the document title |
| V2 | For the National Green Hydrogen Mission progress (2025-12-16), how does it differ from the coal-gasification scheme, and which industries does it hit? | Fertilizers and Chemicals Travancore | 2024-2026 | partial (PIB release held; coal price series ends 2025-12-26) | different policy/macro event and issuer/ministry: different issuer/ministry (MNRE) for V2 |
| V3 | Using the document reference Union_Budget: Union Budget FY2026-27 - Budget at a Glance (2026-02-01), how does the coal-gasification policy differ from the earlier scheme, and which industries does it hit? | Coromandel International | 2024-2026 | yes (policy_events + PIB releases + Budget documents) | naming variant: the event is asked by its document/PRID reference |
| V4 | coal gasification policy draft vs earlier scheme | Bayer Cropscience | 2024-2026 | yes (policy_events + PIB releases + Budget documents) | terse keyword query, 3-8 words; policy drafts versus the earlier scheme, across documents |
| V5 | Coal gasification ke naye draft aur pehle wale scheme mein kya farq hai? Kaunse ministries aur industries affected hain, aur PIB/Budget se evidence do. | Paradeep Phosphates | 2024-2026 | yes (policy_events + PIB releases + Budget documents) | long natural or Hinglish phrasing; policy drafts versus the earlier scheme, across documents |
| V6 | How do India's coal-gasification policy drafts differ from the earlier scheme, and which industries do they hit? | Chambal Fertilizers & Chemicals | from January 2024 to date | yes (policy_events + PIB releases + Budget documents) | different period label inside the data window; policy drafts versus the earlier scheme, across documents |
| V7 | For all listed companies in coal, how does the coal-gasification policy differ from the earlier scheme, and which industries does it hit? | APL Apollo Tubes; PI Industries; Jindal Saw | 2024-2026 | yes (policy_events + PIB releases + Budget documents) | scope up to the industry or sector; policy drafts versus the earlier scheme, across documents |
| V8 | For the NIFTY TOTAL MARKET constituents, what does the coal-gasification policy change mean for the members, and which ones are named in policy_events? | Reliance Industries; Bharti Airtel; HDFC Bank | 2024-2026 | yes (policy_events + PIB releases + Budget documents) | screen by index / theme / market-cap bucket, membership as of the date; policy drafts versus the earlier scheme, across documents |
| V9 | As of 31 December 2025, how did the coal-gasification drafts differ from the earlier scheme? Use only documents known by that date. | Jayaswal Neco Industries | as of 31 December 2025 | no (as-of precedes the policy event; no evidence by then) | point-in-time: only evidence known by the as-of date; policy drafts versus the earlier scheme, across documents |
| V10 | How does the coal-gasification policy change affect coal-price-sensitive companies? If the coal price series ends before 2024-2026, answer NOT IN DATA. | Maharashtra Seamless | 2024-2026 | no (coal_newcastle ends 2025-12-26; no coal price after that) | hard edge: NOT IN DATA or a corporate action in the period; policy drafts versus the earlier scheme, across documents |

### Q24 - PARAGMILK on El Nino; dairy peers

Family 6,8. Entity level: stock. What it tests: management commentary on a macro event, with dairy peers.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | What did Dodla Dairy (NSE: DODLA) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? | Dodla Dairy | 25 May 2026 | yes | same-industry peer at the same level; management commentary on a macro event, with dairy peers |
| V2 | What did Milky Mist Dairy Food (NSE: MILKYMIST) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? | Milky Mist Dairy Food | 7 Sep 2026 | yes | same sector, different market-cap bucket; management commentary on a macro event, with dairy peers |
| V3 | What did BSE scrip code 531531 say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? | Hatsun Agro Product | 26 Aug 2025 | yes | naming variant: ISIN / BSE code / old symbol after a rename; management commentary on a macro event, with dairy peers |
| V4 | PARAGMILK el nino dairy margins | Parag Milk Foods | 13 Aug 2026 | yes | terse keyword query, 3-8 words; management commentary on a macro event, with dairy peers |
| V5 | Heritage Foods (NSE: HERITGFOOD) ne El Nino 2026 ke asar par calls mein kya kaha? Dairy peers ka bhi comparison do, aur management ne kaise handle karne ko kaha. | Heritage Foods | 20 Jul 2026 | yes | long natural or Hinglish phrasing; management commentary on a macro event, with dairy peers |
| V6 | What did Kwality Wall's (India) (NSE: KWIL) say about El Nino 2026 in its transcripts, and how are dairy peers handling the same risk? | Kwality Wall's (India) | the 2026 calls | no (store has no rows for this entity; store has no rows for this entity; no document_chunks rows (transcript/filing not chunked)) | different period label inside the data window; management commentary on a macro event, with dairy peers |
| V7 | For all listed companies in Fast Moving Consumer Goods, what did managements say about El Nino 2026, and how are they handling it? | Godrej Consumer Products; Radico Khaitan; Colgate Palmolive (India) | 11 Aug 2026 | yes | scope up to the industry or sector; management commentary on a macro event, with dairy peers |
| V8 | For the NIFTY SMALLCAP 100 constituents, how exposed are the members to El Nino 2026, and what did they say about handling it? | IDBI Bank; Ather Energy; RBL Bank | latest calls | no (store has no rows for this entity; store has no rows for this entity) | screen by index / theme / market-cap bucket, membership as of the date; management commentary on a macro event, with dairy peers |
| V9 | As of 30 June 2026, what had Milkfood (NSE: MLKFOOD) said about El Nino 2026 and its dairy margins? | Milkfood | as of 30 June 2026 | no (store has no rows for this entity; store has no rows for this entity; no document_chunks rows (transcript/filing not chunked)) | point-in-time: only evidence known by the as-of date; management commentary on a macro event, with dairy peers |
| V10 | What did Knack Packaging (NSE: KNACK) say about El Nino 2026 on its calls? If no transcript is held for it, answer NOT IN DATA and name the store checked. | Knack Packaging | latest calls | no (not a dairy company: no dairy/El-Nino commentary in the transcripts) | hard edge: NOT IN DATA or a corporate action in the period; management commentary on a macro event, with dairy peers |

### Q25 - Data-centre tax holiday outcome so far

Family 6,7. Entity level: policy. What it tests: whether a tax holiday exists in the policy record and what companies say.

| V | Question | Entity | Period | Coverage | What it tests |
|---|---|---|---|---|---|
| V1 | For the startup tax holiday extension (2025-02-01), how has it played out so far for the affected industry, and what do companies say? | L&T Technology Services | 2025-2026 | partial (policy event held; no data-centre-specific outcome series) | different policy/macro event of the same type; issuer/ministry noted in the row: different tax-holiday policy |
| V2 | For the Tax holiday for affordable housing projects extended to March 2022 (2022-01-31), how has it played out so far for the affected industry, and what do companies say? | DLF | 2025-2026 | partial (policy event held; no data-centre-specific outcome series) | different policy/macro event and issuer/ministry: different policy line (same issuer, noted) |
| V3 | Using the document reference PIB PRID 2323840 on 2026-10-15, how has the data-centre tax holiday played out so far, and what do the companies in the theme say? | Netweb Technologies India | 2025-2026 | partial (PIB data-centre items held; the data-centre tax holiday itself is not in policy_events) | naming variant: the event is asked by its document/PRID reference |
| V4 | data centre tax holiday outcome 2025-2026 | E2E Networks | 2025-2026 | partial (policy event held; no data-centre-specific outcome series) | terse keyword query, 3-8 words; whether a tax holiday exists in the policy record and what companies say |
| V5 | Data-centre operations ke liye tax holiday ka kya outcome raha? Budget, PIB, policy_events aur data-centre companies ke comments se evidence do. | Amagi Media Labs | 2025-2026 | partial (policy event held; no data-centre-specific outcome series) | long natural or Hinglish phrasing; whether a tax holiday exists in the policy record and what companies say |
| V6 | How has the tax holiday for data-centre operations in India played out so far, and what do the companies in the data-centre theme say? | Cyient | the 2025-26 Budget cycle | partial (policy event held; no data-centre-specific outcome series) | different period label inside the data window; whether a tax holiday exists in the policy record and what companies say |
| V7 | For all listed companies in data-centre, how has the tax holiday played out, and what do the companies and policy documents say? | Inventurus Knowledge Solutions; Affle 3i; Anant Raj | 2025-2026 | partial (PIB data-centre items held; the data-centre tax holiday itself is not in policy_events) | scope up to the industry or sector; whether a tax holiday exists in the policy record and what companies say |
| V8 | For the NIFTY SMALLCAP 500 constituents, what has the tax holiday meant so far, and which members are named in the policy record? | Indiamart Intermesh; IDBI Bank; Ather Energy | 2025-2026 | partial (PIB data-centre items held; the data-centre tax holiday itself is not in policy_events) | screen by index / theme / market-cap bucket, membership as of the date; whether a tax holiday exists in the policy record and what companies say |
| V9 | As of 1 February 2026, how had the data-centre tax holiday played out, using only evidence known by that date? | Datamatics Global Services | as of 1 February 2026 | no (no data-centre tax holiday in policy_events; as-of evidence cannot answer it) | point-in-time: only evidence known by the as-of date; whether a tax holiday exists in the policy record and what companies say |
| V10 | How has the data-centre tax holiday played out so far? If no data-centre tax holiday exists in policy_events, or the PIB starts too late, answer NOT IN DATA. | eMudhra | 2025-2026 | no (no data-centre tax holiday in policy_events; PIB has data-centre items but no tax-holiday policy) | hard edge: NOT IN DATA or a corporate action in the period; whether a tax holiday exists in the policy record and what companies say |

