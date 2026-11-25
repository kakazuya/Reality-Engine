# T-242 deck widening: what the two reader options add (measured 25 Nov 2026, no model calls)

Measured with the shipped selection code, `observations.pages_from_store`, over every universe store at
`C:/RealityEngine/tg_build/universe_fy27` that holds both a `routes.csv` and its `cNN.db`: **677 stores**
(687 `cNN` directories exist; the rest have no `routes.csv`). `doc_types=('deck',)`, default routes
`('table_or_chart','needs_ocr')`; each option is one run on top of that same default.

| option | extra deck pages |
|---|---|
| default (today) | 4,683 pages read |
| `--deck-few-figures` | +2,307 |
| `--deck-jumbled-min 0.60` | +3,240 |
| `--deck-jumbled-min 0.65` | +2,483 |
| `--deck-jumbled-min 0.68` | +1,906 |
| `--deck-jumbled-min 0.69` | +1,677 |
| `--deck-jumbled-min 0.70` | +1,438 |
| `--deck-jumbled-min 0.72` | +933 |
| `--deck-jumbled-min 0.74` | +415 |
| `--deck-jumbled-min 0.75` | +114 |

The default 4,683 is every `table_or_chart` deck page (the route census' 17,571 deck pages),
so the two options add pages the router today sends nowhere: a `no_figures` page whose reason says 1-3 printed
figures, and a `needs_ocr` page whose reason says the text layer is jumbled at a label-dictionary share at or
above SHARE. No routes.csv is rewritten and no prompt changes (`read_gate.fingerprint('deck')` stays
`ea5e621d2826`); a jumbled page is read from its own text layer and its rows carry
`text_source='text_layer_jumbled'`.

## `--deck-few-figures`: 20 random additions (seed 21), first 300 characters of the stored text

| # | page id | text |
|---|---|---|
| 1 | `c2973` `D:/RealityEngine/raw/pilot60_history/PERSISTENT/investor_presentation/af8dcc9a-f620-4510-84df-81f3f77ff6af.pdf` p6 | Our journey over 36+ years has been shaped with Cloud, Data and AI… / o Pivot to AI-led, platform-driven / services strategy / o New growth vectors at the intersection / of industries, tech and geographies / o Enhanced focus on outcome-based / models / o Driving enterprise-wide transformation / through AI and A |
| 2 | `c571` `D:/RealityEngine/raw/pilot60_history/BHARATROHAN/investor_presentation/1b6d94b9-b779-4fee-a9f0-fe7c19fcf47e.pdf` p4 | 5 key pillars driving BharatRohan's scalable growth and long-term value / 100M+ acres / analyzed potential / End-to-end platform / across the value chain / Higher yields / stronger incomes / Continuous innovation / in agronomy & data / Expanding / across regions and markets / BharatRohan combines technology, farmer trust |
| 3 | `c443` `D:/RealityEngine/raw/pilot60_history/AVG/investor_presentation/7a422a45-9505-4ec1-bf36-c5c72132f601.pdf` p28 | Green & Sustainable initiatives / Rhino 5536E EV – Fleet 55 Tonnage Launch / Nestle Sanand / BE 5528+ 4x2 (BS-VI) - 1st LNG Fleet Launch / ITC Pune |
| 4 | `c647` `D:/RealityEngine/raw/pilot60_history/BOROSCI/investor_presentation/ad9793b6-6da8-477f-b5fd-7fec5705c110.pdf` p19 | 18 / Customers in Scientific Segment / FY25 / Emphasis on Widening Our Footprint Across Key Customer Segments / ✔ / Perfectly / aligned / product / range / of / Borosil Scientific to serve the growing / industry / segments / like / Food / & / Beverage, Feed, Dairy etc. / ✔ / Launch of Biopharma SHAKTI in the / Union Budget 2026-27 will |
| 5 | `c348` `D:/RealityEngine/raw/pilot60_history/ARVSMART/investor_presentation/30df9aa4-5257-4668-bf0e-109a08a1f3d7.pdf` p36 | 35 / Information Update I Q1 FY27 I / THANK YOU / ARVIND SMARTSPACES LTD / (CIN: L45201GJ2008PLC055771) / REGISTERED & CORPORATE OFFICE: / 24, Govt. Servant’s Society, / Adj. Municipal Market, / C. G. Road, Ahmedabad- 380 009 / Tel: +91 79 68267000 / www.arvindsmartspaces.com / INVESTOR RELATIONS / AMIT CHAMARIA| CFO / E: am |
| 6 | `c647` `D:/RealityEngine/raw/pilot60_history/BOROSCI/investor_presentation/8c1f0a01-a8f0-4326-8bdb-a7d29fddf9dd.pdf` p12 | 11 / Made in India Edge / The Made in India Edge / Major / manufacturing / facilities / across / Bharuch, / Nashik, Pune, & Vadodara producing 4500+ SKUs / Integrating research & development and design / with manufacturing to achieve innovation & growth / Patented LabQuest dispenser & QR-coded volumetric / glassware demons |
| 7 | `c673` `D:/RealityEngine/raw/pilot60_history/BSOFT/investor_presentation/c77114f1-0209-4454-8632-6b1bb70306f0.pdf` p6 | For further information please contact: / Investors / Analysts / Abhinandan Singh / Media / Tanushree Mahanty / +91 9820293450 / +91 9899195348 / abhinandan.singh@birlasoft.com / tanushreem1@birlasoft.com / Investor Update | Q1 FY 2026-27 / 6 |
| 8 | `c319` `D:/RealityEngine/raw/pilot60_history/ARE&M/investor_presentation/e0da0bd0-b9a4-4d63-be97-802f5dc1df6e.pdf` p6 | 5 / APPLICATIONS / • Pioneers in VRLA batteries in India / • Application - Telecom, Railways, Power Control, Solar, UPS / • Market Leader in Telecom sector/Largest exporter for VRLA batteries / • Largest Integrated Facility for MVRLA Batteries / INDUSTRIAL / • Applications – 2W, 3W, 4W & CV’s / • First AGM battery |
| 9 | `c665` `D:/RealityEngine/raw/pilot60_history/BRITANNIA/investor_presentation/76e0ab43-4d86-446e-9009-3cc9c3624e5c.pdf` p13 | w w w . b r i t a n n i a . c o . i n / 12 / Adjacency Businesses / 03 / Adjacent Bakery Businesses* / grew >20% during the / quarter / Dairy – Cheese, Ghee, Milk Drinks leading / the business into double-digit growth / International Business – Resilient rebound into mid- / teens growth across key geographies / Nepal |
| 10 | `c80` `D:/RealityEngine/raw/pilot60_history/ACI/investor_presentation/2d96605d-1b82-447f-be9b-01b51b9cf3f3.pdf` p23 | 22 / 3. Sulphate of Potash / High value, chloride-free potash fertilizer with a vital role in enhancing crop / quality and yield / K2SO4 / Only manufacturer of natural / sea brine-based SOP in India / 1,30,000 MTPA / Manufacturing Capacity / Position / • KTMS (kainite type mixed salt) had higher NaCl / content (Sodium |
| 11 | `c356` `D:/RealityEngine/raw/pilot60_history/ASARFI/investor_presentation/0a2df344-bcda-4183-a129-57cb3bce544f.pdf` p26 | Asarfi Hospital Limited | Investor Presentation Q2’FY27 / Leadership Team / Harendra Singh / Promoter & CFO / • / A visionary entrepreneur inspired by the Company’s / purpose – Health for All / • / Believes good leaders are passionate about learning / and focused on building world-class organisations / • / B.Sc. (Elect |
| 12 | `c04` `D:/RealityEngine/raw/pilot60_history/360ONE/investor_presentation/0a4c09d6-1893-4cf3-9476-ac5ab0721303.pdf` p23 | 360 ONE / Link to Download Data Book / 20 / Data reported across previous quarters is now continued to be reported in a Data Book, maintained in an excel format on our website. The Link for the data book is hosted below. / Click here to access the Databook / Click here to access the Databook / Contents of the D |
| 13 | `c05` `D:/RealityEngine/raw/pilot60_history/3BBLACKBIO/investor_presentation/8a7483ed-9d7b-455f-8beb-cbc1037e44fc.pdf` p26 | TPE participated at the world’s largest medical trade fair, MEDICA, held annually in Düsseldorf, Germany, / serves as a global marketplace for medical technology, diagnostics, and digital health, attracting exhibitors / and visitors from over 70 countries. / TRUPCR® Europe – Events & Conferences 2025-26 |
| 14 | `c509` `D:/RealityEngine/raw/pilot60_history/BATLIBOI/investor_presentation/db57adca-42db-4ade-8be9-b9b6e5142b25.pdf` p17 | Widespread Sales and Distribution Network in India / 16 / Corporate Office / Manufacturing Facility / Sales & Service Offices / Resident Office / Mysuru / Coimbatore / Ludhiana / New Delhi / Ahmedabad / Surat / Aurangabad / Mumbai / Pune / Kolhapur / Guntur / Kolkata / Chennai / Mohali / Bengaluru / Rajkot / Corporate Office / Manufacturing Fac |
| 15 | `c600` `D:/RealityEngine/raw/pilot60_history/BIRLANU/investor_presentation/96de717f-8244-4dfd-99b8-d079df9ebe01.pdf` p37 | 36 / Roofs / Engineered Wood / Product Range / Eco-Flooring / Vinyl / Laminates / Installed Capacity / • / 15 million SQM |
| 16 | `c149` `D:/RealityEngine/raw/pilot60_history/AGARWALEYE/investor_presentation/36dba630-b69c-4a3e-a55f-ec6abe4cb3f4.pdf` p38 | 37 / Highly Experienced Board / Education institute attended / DR RANJAN RAMDAS PAI / Non-Executive Independent Director / Founder & Chairman, Manipal Education and / Medical Group / Manipal Academy of Higher Education / VENKATRAMAN BALAKRISHNAN / Non-Executive Independent Director / Ex-Chairman, Infosys BPO, / Whole-t |
| 17 | `c274` `D:/RealityEngine/raw/pilot60_history/ANNU/investor_presentation/3683123a-979f-49da-8a4b-51d4d4029646.pdf` p11 | Business Verticals At a Glance / Railway / signalling / OFC and quad-media works / for / railway / signalling / and / communication networks / Customers: Eastern Railway, / Howrah Division (government) / Telecom / infrastructure / OFC laying (overhead and / underground), tower and / cabling work, and network / O&M / Custo |
| 18 | `c355` `D:/RealityEngine/raw/pilot60_history/ASALCBR/investor_presentation/f18ea67b-149f-470e-8443-c067ebc3d78d.pdf` p27 | 26 / Further Strengthening Position In Keralam: Acquires SDF Industries / Deal Structure / o Resolution Plan / under IBC NCLT / Kochi Bench – / Approved April 16, / 2026 / Acquisition Cost / o Total Acquisition cost / Rs 30.85 Cr / o SDF Industries Ltd. / Becomes Wholly / Owned Subsidiary / Location / o / Thrissur, Keralam, |
| 19 | `c355` `D:/RealityEngine/raw/pilot60_history/ASALCBR/investor_presentation/4f357731-aa69-4e0d-9238-3e69a45505bf.pdf` p21 | 20 / Further Strengthening Manufacturing Capabilities In Keralam / Acquired SDF Industries / Deal At A Glance / • / Resolution Plan under IBC / NCLT Kochi Bench – / Approved April 16, 2026 / • / Total Acquisition cost Rs / 30.85 Cr / • / SDF Industries Ltd. / Becomes Wholly Owned / Subsidiary / • / Thrissur, Keralam, Border |
| 20 | `c116` `D:/RealityEngine/raw/pilot60_history/ADSL/investor_presentation/54689e5a-213a-4402-82cd-e06e86049067.pdf` p14 | 13 / Brazil / Australia / Singapore / Japan / Mumbai, India / China / US / Canada / UK / Belgium / Germany / Italy / Ireland / Spain / UAE / India, 32% / Rest of World, 68% / Revenue / Breakup / Headquarters / Subsidiaries / Branches |

Reading: a mixed bag, as the router's own figure count predicts. Real content pages (capacity, acquisition cost,
revenue breakup) sit beside deck covers, contact and thank-you pages, which print one or two phone numbers or
percentages. A read of these pages costs one hy4 call each and mostly returns nothing on the cover pages; the
checks quarantine a contact/letterhead row (`junk_measure`) and `is_cover_letter` drops a filing cover page, but a
deck cover is not dropped by any script rule, so the option trades calls for recall.

## `--deck-jumbled-min 0.70`: 20 random additions (seed 21), first 300 characters of the stored text

| # | page id | text |
|---|---|---|
| 1 | `c264` `D:/RealityEngine/raw/pilot60_history/ANGELONE/investor_presentation/a698e293-bee6-48d7-aa19-25376f9e38fe.pdf` p19 | 18 / Credit distribution: A large untapped layer / LIFE CYCLE ST AGE / Establishing / MARKET OPPORTUNITY · WITHIN OUR USE R POOL / Large, underserved pool · low penetration of digital players / >₹ 1,000 Bn / (FY26) / Loans taken by our users from the market / 38.6 Mn / Angel One user base / 151+ k / Ever taken credit user |
| 2 | `c470` `D:/RealityEngine/raw/pilot60_history/BAJAJFINSV/investor_presentation/a8f7fb43-ae21-4fe6-b90a-f5c9f0615750.pdf` p100 | 7.3% / 6.2% / 4.2% / 2.9% / 2.5% / 2.0% / 1.4% / 0.9% / China / India / Taiwan / Malaysia Singapore Thailand HongKong / Japan / GDP PER CAPITA CAGR / FY 2015-2025 / 5,923 / 2,539 / 2,084 / 1,501 / 448 / 313 / 201 / 72 / 1,545 / 1,075 / 654 / 1,894 / 175 / 245 / 170 / 25 / Singapore / Taiwan / Japan / South / Korea / Malyasia / China / Thailand / India / Insuranc |
| 3 | `c93` `D:/RealityEngine/raw/pilot60_history/ADANIPORTS/investor_presentation/02e48f16-0c29-41d1-b78d-28b3b999d5ae.pdf` p34 | 33 / Consistent delivery track record over the past several years / KPI – Key Performance Indicator | EBITDA – Earnings Before Interest, Tax, Depreciation & Amortization | Capex – Capital expenditure | MMT – Million Metric Tonne / Numbers are restated wherever applicable / Comparison of guidance vs reporte |
| 4 | `c783` `D:/RealityEngine/raw/pilot60_history/CHOLAFIN/investor_presentation/0227e682-447f-45c9-9e24-0b57175220a2.pdf` p87 | Capital & Liquidity risk | Sufficient Tier 1 capital / Common Equity / Tier -1 capital requirement / (at least 9% of RWA)- 19,407 / Regulatory requirement / Common Equity / Tier-1 capital maintained / (14.9% of RWA)- 32,082 / Tier-1 Capital held as on 30th Sep’26 / Per regulatory / guidance, NBFCs to / maintain at |
| 5 | `c38` `D:/RealityEngine/raw/pilot60_history/AAVAS/investor_presentation/958687b4-0318-48fa-8bc9-3a52a4563a59.pdf` p15 | Investor Presentation H1FY27 / Diversified Institutional Shareholding / Shareholding Pattern as on / 30th Sep 2026 / Top Institutional Shareholders as on 30th Sep 2026 / DII includes Mutual Funds, Insurance Companies & Alternate Investment Funds (Category III) / ^ holding through various schemes / Funds / * inc |
| 6 | `c498` `D:/RealityEngine/raw/pilot60_history/BANKBARODA/investor_presentation/afc4157e-1d75-4f0f-b074-231c0efe8d75.pdf` p44 | 43 / Bank of Baroda (Botswana) Ltd. / (Subsidiary Holding – 100%) / Bank of Baroda (Kenya) Ltd. / (Subsidiary Holding – 86.70%) / Bank of Baroda (Uganda) Ltd. / (Subsidiary Holding – 80%) / Overseas Subsidiaries Performance / Note: Financial year end for Uganda and Kenya is December. / ❑Total Deposits stands at INR |
| 7 | `c324` `D:/RealityEngine/raw/pilot60_history/ARIHANT/investor_presentation/c85820e0-2912-47f6-a7d6-7b317ea4be22.pdf` p16 | 15 / PROJECT PORTFOLIO / INR 17,900 Mn / COMMERCIAL GDV / 7 Ongoing Commercial Projects / INR 9,300 Mn / ARIHANT SHARE / Our economic interest / 9.70 Lakh Sq. Ft. / TOTAL AREA / Grade A office space / Commercial Projects / PROJECT / LOCATION / SQ FT / GDV / ( IN ₹ Mn) / ARIHANT SHARE / (IN ₹ Mn) / HILTON / GUINDY / 3,00,000 / 5,000 / 3,200 / SUBL |
| 8 | `c496` `D:/RealityEngine/raw/pilot60_history/BANDHANBNK/investor_presentation/d6ee07b5-f824-4ecd-bf6f-03f7e9d8bcc1.pdf` p34 | Credit Rating / *Rating of ICRA is for ₹ 30 bn only, **Rating of ICRA is for ₹ 0.75 bn only #erstwhile GRUH Finance Limited transferred to Bandhan Bank Ltd / ^ Represents SR's received against stress loan transferred during the quarter ended December 31, 2025. The Net Book value of all the SR's is NIL a |
| 9 | `c520` `D:/RealityEngine/raw/pilot60_history/BCLIND/investor_presentation/6e61bb4c-836e-43b3-8621-66e3be954832.pdf` p25 | 3 / 10 / 2024 / 2034 / 24 / Ethanol : Multi-Billion Dollar Opportunity and India needs to catch up / Sources : The International Energy Agency (IEA) ; Industry Report1,2,3 / India Ethanol Market Size USD Billion2 / Global Ethanol Market Size USD Billion1 / India, Brazil, and Indonesia to collectively / drive nearly tw |
| 10 | `c285` `D:/RealityEngine/raw/pilot60_history/ANURAS/investor_presentation/707d555d-bafe-4ca3-8167-27d74c90d85e.pdf` p13 | ‹#› / Anupam Rasayan India Limited | / Evolution of Anupam / 12 / Anupam Rasayan India Limited | / PHASE III- / THE ACCELERATION / 2023 / • Raised ₹5,000 mn. through QIP / • Commissioned Solar Power Plant of 5.4MW at Bharuch / 2024 / • Raised ₹5,500 mn. through Preferential Issue / • Commissioned Hybrid Power Plant of 9.6 |
| 11 | `c512` `D:/RealityEngine/raw/pilot60_history/BBOX/investor_presentation/cb97a9e1-30f2-4c8b-9c2c-ad7bd3b93572.pdf` p24 | 23 / Consolidated P&L Statement / Particulars (in ` crore) / FY21 / FY22 / FY23 / FY24 / FY25 / FY26 / Revenue from Operations / 4,674 / 5,370 / 6,288 / 6,282 / 5,967 / 6,322 / Gross Profit / 1,497 / 1,549 / 1,640 / 1,714 / 1,794 / 1,930 / Gross Profit Margin / 32.0% / 28.9% / 26.1% / 27.3% / 30.1% / 30.5% / Total Other Expenses / 1,145 / 1,289 / 1,370 / 1,286 / 1,263 |
| 12 | `c533` `D:/RealityEngine/raw/pilot60_history/BELRISE/investor_presentation/b4812477-8831-47df-9b43-0c15aa8b7054.pdf` p9 | Update on Key Strategies / 8 / 2-Wheelers / 3-Wheelers / • / Secured an additional chassis order from a fast- / growing 2W & 3W OEM for a high-volume / model; Start of Production (SOP): Q4 FY27 at / Bangalore facility / • / Won a chassis order for an existing model of a / leading Indian 2W OEM; SOP: Q4 FY27 at / Samb |
| 13 | `c343` `D:/RealityEngine/raw/pilot60_history/ARTEMISMED/investor_presentation/bf6ee7a3-305d-45f9-bc61-41412715aa8f.pdf` p4 | IP Volume / Business Overview / Expanding Access to Advanced Healthcare while delivering exceptional clinical outcomes, Target capacity ~2,000 beds by 2029 / One of the largest hospitals in / Delhi-NCR / Artemis Medicare / 15% increase in FAR and / Purchase of additional FAR to 2.15 / will enable to add another |
| 14 | `c04` `D:/RealityEngine/raw/pilot60_history/360ONE/investor_presentation/0a4c09d6-1893-4cf3-9476-ac5ab0721303.pdf` p14 | 360 ONE / Key Quarterly Financial Highlights / 11 / P/L Summary (INR Crs) / Q1 FY26 / Q2 FY26 / Q3 FY26 / Q4 FY26 / Q1 FY27 / YoY% / Total Wealth AUM (ex-custody) / 4,05,995 / 4,20,898 / 4,36,697 / 4,20,608 / 4,74,159 / 16.8% / Wealth ARR AUM / 1,94,773 / 2,03,208 / 2,18,957 / 2,16,734 / 2,41,896 / 24.2% / 360 ONE Plus (DPMS / NDPMS-RIA) / 71,073 / 7 |
| 15 | `c101` `D:/RealityEngine/raw/pilot60_history/ADFFOODS/investor_presentation/6ef3e1c7-cc6f-417a-b766-4b5b12ce09d8.pdf` p50 | 49 / Consolidated 5-year Financial Highlights / Particulars (INR crores unless stated) / FY22 / FY23 / FY24 / FY25 / FY26 / Profit & Loss Highlights / Revenue from Operations / 421.2 / 450.3 / 520.3 / 589.6 / 683.2 / Gross Profit / 211.5 / 235.9 / 276.2 / 341.4 / 410.5 / Gross Profit (%) / 50.2% / 52.4% / 53.1% / 57.9% / 60.1% / EBITDA / 66.6 / 80.6 / 104. |
| 16 | `c454` `D:/RealityEngine/raw/pilot60_history/AXISBANK/investor_presentation/ef2c7ef5-2fbb-494d-9dc4-1ddee192faa7.pdf` p14 | Quarterly Results Q1FY27 / 4 / 1QAB: Quarterly Average Balance; MEB: Month End Balance; 2Bank’s focus segments include Small Business Banking (SBB), Small & Medium Enterprises (SME), Mid Corporate, Rural, Personal Loans (PL) and / Credit Card Advances 3 Market share by volume for Q1Y27; 4 NPCI data for t |
| 17 | `c631` `D:/RealityEngine/raw/pilot60_history/BMW/investor_presentation/76a59f4c-9ae4-49c8-ab41-fb9e6be5fe00.pdf` p5 | Key Quarterly Highlights / Note: / 1. Operating EBITDA Margin calculated on Operating Income; / 2. PAT attributable to the owners of the company / Particulars / Operating Income / Operating EBITDA1 / PAT2 / Q1 FY27 / 16,600 / 3,369 / 1,912 / Growth YoY / 11.6% / 7.1% / 25.8% / Growth QoQ / (20.8%) / (41.6%) / (42.3%) / Margin (%) / - |
| 18 | `c470` `D:/RealityEngine/raw/pilot60_history/BAJAJFINSV/investor_presentation/22b7460d-3b6c-4f52-8161-eae8ecf3e635.pdf` p30 | 1,230 / 1,173 / 1,357 / 1,434 / 896 / 595 / 794 / 942 / 1,085 / 1,781 / FY 22 / FY 23 / FY 24 / FY 25 / FY26 / Embedded Value / Networth / Value in Force (VIF) / 1.3% / 2.1% / 1.5% / -1.5% / -0.4% / FY 22 / FY 23 / FY 24 / FY 25 / FY26 / Bajaj Life – Embedded Value & ROEV / Operating & Assumption change variance (as % of VIF) / Low operating experi |
| 19 | `c149` `D:/RealityEngine/raw/pilot60_history/AGARWALEYE/investor_presentation/36dba630-b69c-4a3e-a55f-ec6abe4cb3f4.pdf` p31 | 30 / Our Hub and Spoke Network Model / 11 / 21 / 38 / 66 / 89 / 79 / 91 / 116 / 142 / 164 / 16 / 24 / 26 / 28 / 35 / 106 / 136 / 180 / FY22 / FY23 / FY24 / FY25 / FY26 / Number of Facilities across India and Africa (#) / Primary / Secondary / Tertiary / 28.4% CAGR Growth in Total Facilities over FY22 – FY26 / 236 / Description / Primary Facilities / Surgical Facil |
| 20 | `c220` `D:/RealityEngine/raw/pilot60_history/AMAGI/investor_presentation/aa4478eb-de07-46ef-96ec-95e2e6c1aba4.pdf` p10 | BIG BETS · AGENTIC OPERATIONS / Execution moves to agents. Judgment stays with people. / TODAY · people operate the software / TOMORROW · the software operates itself / ON AIR / JUDGMENT / LAYER / EXECUTION / LAYER / decide, approve, / handle exceptions / decide, approve, / handle exceptions / people watching screens, 24×7, |

Reading: at share >= 0.70 the printed figures and labels are readable (`Revenue from Operations 4,674 5,370
6,288 ...`, shareholding percentages, order and capex sentences); the failures are proper nouns and words the
dictionary does not carry, plus occasional letter-spacing (`ST AGE`, `USE R POOL`, `Malyasia`). That is exactly
what a high label-dictionary share means: the labels are dictionary words, the names are not. Pages below 0.70
(shares down to 0.60) were not sampled here; the count table above is the cost of lowering SHARE.

Re-run 25 Nov 2026 with the merged selection code (worktree `20261125T161136Z`): every count above reproduced
exactly -- 677 stores, 17,571 deck rows (`table_or_chart` 4,683, `no_figures` 6,451, `needs_ocr` 6,143,
`text_ok` 294), default reads 4,683, and the additions `--deck-few-figures` 2,307 / 0.60 3,240 / 0.65 2,483 /
0.70 1,438 / 0.75 114. A sample's text is the store's `doc_page.text` for that `doc_key`/`page`, first 300
characters; the throwaway script that drew the samples lived in the authoring worktree's `.tmp` and is not committed.

Reproduce the counts (no model call), from the repo root:

```python
from pathlib import Path
from reality_engine.v2.observations import pages_from_store
root = Path("C:/RealityEngine/tg_build/universe_fy27")
stores = [p / f"{p.name}.db" for p in root.iterdir()
          if (p / "routes.csv").is_file() and (p / f"{p.name}.db").is_file()]

def kept(**option):
    return {(str(s), p["doc_key"], p["page"]) for s in stores
            for p in pages_from_store(s, doc_types=("deck",), **option)}

base = kept()
print(len(base), len(kept(deck_few_figures=True) - base), len(kept(deck_jumbled_min=0.70) - base))
# 4683 2307 1438
```
