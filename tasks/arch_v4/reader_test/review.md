# Reader test — hand-grading packet

## Q01 MB0337 APLAPOLLO — verified

**Q:** APLAPOLLO 8 MT by FY28 — slipped or on track?

as_of=2026-10-31 types=concall,deck,results_notes template=A01 gold_found=True gold_in_top=True gold_rank=1
**Bank gold:** “And our long-term plan of 8-million-ton capacity by FY '28 remains totally on-track.”

**Answer:** The 8-million-ton capacity plan by FY28 remains totally on track.

**Quote:** our long-term plan of 8-million-ton capacity by FY '28 remains totally on-track

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [38222] concall 2026-05-06 p3 score=10.1 cov=2 phr=1 **GOLD** — Anubhav Gupta: Thanks, Akhilesh. Thanks for hosting us. And we also have our Chairman and Managing Director, Mr. Sanjay Gupta, on the call. So good morning, everyone and 
- [26909] annual_report 2026-08-21 p123 score=7.5 cov=3 phr=0 — RISK GOVERNANCE The Company's integrated Three Lines of Defence framework establishes clear accountability for risk ownership, independent oversight and assurance across 
- [38242] concall 2026-05-06 p12 score=6.95 cov=1 phr=1 — Rajesh Ravi: Okay. So next 2 months you are looking at May and June better traction to happen? Sanjay Gupta: Yes. I think because there was a little problem with steel in
- [34980] concall 2025-07-26 p17 score=6.9 cov=2 phr=1 — is my focus. But right now the things are not good for us. We are maintaining our margin going for a little bit 10%-15% growth that will come, we are concentrating on tha
- [26878] annual_report 2026-08-21 p65 score=6.65 cov=2 phr=0 — CAPITAL DEPLOYED HOW VALUE IS CREATED  Track infrastructure, housing, industrial and renewable trends  Identify RCC-to-steel substitution opportunities  Develop new pr
- [38234] concall 2026-05-06 p9 score=6.582 cov=1 phr=1 — Darshan Mehta: Okay, okay. Not general products, total volumes. Yes. And I -- so also our other expenses I think have grown 13% Q-o-Q. So just wanted to know is there any
- [31098] concall 2024-08-14 p5 score=6.5 cov=2 phr=1 — Number two is that we shall be taking market share from the secondary scrap steel because now the pricing gap between our products and the scrap steel pipe is like 5%, wh
- [26854] annual_report 2026-08-21 p19 score=6.5 cov=2 phr=0 — 5 Mn Ton to 8 Mn Ton by FY28 - funded entirely by internal cash flows, without debt or equity dilution - is the most visible expression of our confidence in the compoundi
- [51405] deck 2026-08-01 p9 score=5.65 cov=1 phr=0 — 8 Capacity Expansion Plan By FY28 Greenfield & Brownfield capacity Debottlenecking Total capacity 8 Mn Ton Structural Steel Existing capacity 5 Mn Ton Structural Steel 2 
- [26844] annual_report 2026-08-21 p5 score=4.825 cov=1 phr=0 — EXPANDING CAPACITY The most powerful statement of conviction we can make is not what we say. It is what we build. In FY26, we initiated the most ambitious expansion in ou

**Quote context:**

> ute EBITDA, which we had guided in our previous call. And hopefully things will become better as we move forward. But given the current atmosphere, our focus is on profitability rather than just pushing volumes. And our long-term plan of 8-million-ton capacity by FY '28 remains totally on-track. Our capex commitments, new land acquisition, new product development, distribution announcement in East India, that everything remains on track so that whenever things recover, we are quickly able to recover our lost volume and demonstrate good performance. That's all from our side. We'd like to take questions now.

**Gold locator:** chunk 38222 concall 2026-05-06 overlap=1.0 in_top=True


## Q02 MB0345 HINDALCO — rejected_number

**Q:** Hindalco's renewable-energy capacity: how much does it have, of what mix, and what did management say it does to cost?

as_of=2026-10-31 types=concall template=A01 gold_found=True gold_in_top=True gold_rank=4
**Bank gold:** “we have 470 megawatts of renewable energy capacity across solar, wind, hydro resources along with 35 megawatts of pump storage tie-ups”

**Answer:** At the end of FY26, Hindalco's renewable energy capacity stood at 470 megawatts, powered by solar, wind and idle sources, with 53 MW more to be added the next quarter and 30 MW storage-based power, taking total capacity to 523 MW by end of Q1 FY27. Management said these achievements reflect commitment to clean energy and reducing carbon intensity.

**Quote:** At the end of this year, our renewable energy capacity stands at 470 megawatts powered by solar, wind and idle sources.

**Verify:** status=rejected_number quote_ok=True kind=exact number_ok=False missing_numbers=['53', '30', '523']
**Model says missing:** No statement in the excerpts about what renewable energy does to cost.

**Retrieved chunks:**
- [38600] concall 2026-05-26 p3 score=18.1 cov=6 phr=2 — Satish Pai: Yes. Thank you, Subir, and good morning and evening, everyone. On Slide 5 to 10 of this presentation, you can see our achievements and progress across quarter
- [36517] concall 2025-11-13 p3 score=17.65 cov=6 phr=2 — Satish Pai: Yes. Thank you, Subir, and good afternoon and morning to everyone. Thank you for joining Hindalco's earning concall today. On Slides 5 to 9 of this presentati
- [35536] concall 2025-08-18 p3 score=16.729 cov=6 phr=2 — Satish Pai: Yes. Thank you, Subir. Good afternoon, and morning, everyone. Thank you for joining Hindalco's earnings call today. On Slides 5 to 9 of this presentation, you
- [37897] concall 2026-02-18 p3 score=15.75 cov=5 phr=2 **GOLD** — Satish Pai: Good afternoon and morning, everyone. Thank you for joining Hindalco's Earnings Con Call today. On Slide #5-10 of this presentation, you can see our progress 
- [34395] concall 2025-05-26 p4 score=15.3 cov=5 phr=2 — Satish Pai: Yes. Good afternoon and good morning, everyone. Thank you for joining Hindalco's Earnings Call today. On Slides #4 to #10 of this presentation, you can see ou
- [13016] annual_report 2025-07-28 p108 score=13.0 cov=6 phr=1 — Around 85-90% of the plant's power requirement is met by renewable energy sources 156 — 157 Hindalco Industries Limited Integrated Annual Report 2024-25 Corporate Overvie
- [13013] annual_report 2025-07-28 p106 score=12.55 cov=6 phr=1 — The estimated costs associated with developing this opportunity is ~ ₹223 crore. + Invest in research and development to innovate sustainable aluminium alloys and manufac
- [48269] deck 2025-11-21 p18 score=11.55 cov=5 phr=1 — Investor Day 2025 17 Hindalco India : Cost Position to improve further with captive coal Change in Energy Mix (%) Renewables reaching ~30% of total energy mix in FY33 > 9
- [45097] deck 2025-04-01 p42 score=11.4 cov=5 phr=1 — Investor Day 2025 41 Cost Position to improve further with captive coal Change in Energy Mix (%) Renewables reaching ~30% of total energy mix in FY33 > 98% 45 – 50% 35 - 
- [12945] annual_report 2025-07-28 p52 score=11.4 cov=4 phr=2 — Further, emphasis on risk performance is a core component of our quarterly and monthly business reviews (QBRs and MBRs), ensuring integration of risk management and busin

**Quote context:**

> onverting legacy sites into green ecosystems, including transforming Muri's residue pond into a 17.4-hectare bio-park and undertaking the country's first quarry restoration using over 1 lakh tons of bauxite residue. At the end of this year, our renewable energy capacity stands at 470 megawatts powered by solar, wind and idle sources. Hindalco Industries Limited May 22, 2026 Page 4 of 18 We remain on track to add other 53 megawatts in the coming quarter. At the same time, we are making strong progress in round-the-clock renewable energy initiatives with 30 megawatts of storage-based power scheduled for deployment this quarter, taking our total

**Gold locator:** chunk 37897 concall 2026-02-18 overlap=0.688 in_top=True


## Q03 MB0355 SAIL — verified

**Q:** SAIL ne Q1FY27 mein capital repairs aage khiske kyun, aur output kab recover hoga? (Hinglish)

as_of=2026-10-31 types=concall,deck,results_notes template=A02 gold_found=True gold_in_top=True gold_rank=6
**Bank gold:** “SAIL decided actually to advance some of its major capital repairs during quarter 1, so that it will be free after that and will start producing better in the next quarters.”

**Answer:** Capital repairs were advanced by design at IISCO, Durgapur and Bokaro, and output is expected to recover in subsequent quarters with production volumes more than last year.

**Quote:** That is because we advanced the capital repairs at IISCO at Durgapur and at Bokaro steel mill. So that was by design. So in Q2, Q3 and Q4, the production volumes will be more than that of last year.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [95798] concall 2026-08-01 p17 score=11.313 cov=2 phr=2 — Rajesh Ravi: I have 2 questions. First, given the volume decline and the low capex, which we have done in Q1, does -- could you give us a sense of what we are looking at 
- [92899] concall 2025-11-03 p18 score=11.2 cov=2 phr=2 — Vinit Thakur: Hi, sir. Good morning. Sir, I just want to know why is there a reduction in the OPM as in QoQ and year-on-year as well? Dr. Ashok Kumar Panda: Pardon? Can y
- [92873] concall 2025-11-03 p9 score=10.6 cov=2 phr=2 — Rajesh Ravi: Okay. And on the cost side, you mentioned that the coking coal prices will be higher by $6 to $7, right, in this quarter? Dr. Ashok Kumar Panda: It looks lik
- [92900] concall 2025-11-03 p18 score=10.525 cov=2 phr=2 — Vinit Thakur: Sir, could you shed some light on would we be back to original numbers around 12% or would we be going down or would we be around 11% as per last quarter? D
- [83251] annual_report 2026-09-01 p319 score=9.85 cov=2 phr=2 — ANNUAL REPORT 2025-26 Consolidated Financial Statements Sl. No. Name of the Jointly Controlled Entities Details of Differing Accounting Policy in comparison to Accounting
- [95764] concall 2026-08-01 p3 score=9.75 cov=2 phr=2 **GOLD** — Ashok Panda: Thank you very much, Mr. Ashish Kejriwal. Good morning, everyone. I welcome all our investors and analysts who are joining this results con-call for the fina
- [70812] annual_report 2025-08-25 p313 score=8.8 cov=2 phr=2 — ANNUAL REPORT 2024-25 309 44.C.2 In respect of one subsidiary of the Group and seven jointly controlled entities, as detailed below, certain accounting policies are not c
- [82874] annual_report 2026-09-01 p68 score=6.825 cov=3 phr=0 — 2.3 Expenditure Particulars FY 2025-26 FY 2024-25 Change % Raw Materials Consumed 49866 50810 -1.86 Employee Remuneration & Benefits 11392 11659 -2.29 Finance Cost 2158 2
- [82866] annual_report 2026-09-01 p65 score=6.75 cov=3 phr=0 — ANNUAL REPORT 2025-26 MDA Report During the Financial Year 2025–26, the Company’s Turnover stood at Rs.1,09,966 crore, reflecting an increase of 8% over the corresponding
- [83026] annual_report 2026-09-01 p136 score=6.69 cov=3 phr=0 — If the percentage of PBT to average Net-worth is 8% or above, amount of Pension contribution shall be limited to 9% of Basic Pay plus DA for Executives and 6% of Basic Pa

**Quote context:**

> rget is INR15,000 crores, and we are going on stream to achieve those figures. That is number one. And number two, on the volume front, as I told you, there is a reduction of around 0.1 million tonnes of production. That is because we advanced the capital repairs at IISCO at Durgapur and at Bokaro steel mill. So that was by design. So in Q2, Q3 and Q4, the production volumes will be more than that of last year. And on the yearly basis, there is expected to be a growth as compared to '25-'26. Moderator: Ladies and gentlemen, we will take that as the last question for today. I would now like to hand the conference over to the management for the

**Gold locator:** chunk 95764 concall 2026-08-01 overlap=1.0 in_top=True


## Q04 MB0415 SAIL — not_stated

**Q:** Which companies disclosed a plant shutdown or force majeure in the last quarter, and what did they say the financial effect was?

as_of=2026-10-07 types=concall,results_notes,announcement template=A06 gold_found=True gold_in_top=False gold_rank=None
**Bank gold:** “SAIL decided actually to advance some of its major capital repairs during quarter 1, so that it will be free after that and will start producing better in the next quarters.”

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** No excerpt for SAIL discloses a plant shutdown or force majeure in the last quarter or its financial effect.

**Retrieved chunks:**
- [83381] annual_report 2026-09-01 p421 score=11.475 cov=6 phr=0 — ANNUAL REPORT 2025-26 NOTICE Shri Alok Verma An accomplished and result-oriented technocrat, Mr. Alok Verma is a steel stalwart with over three decades of transformative 
- [70922] annual_report 2025-08-25 p399 score=10.8 cov=6 phr=0 — ANNUAL REPORT 2024-25 395 “RESOLVED THAT pursuant to the provisions of Section 148 and other applicable provisions, if any, of the Companies Act, 2013 and the Companies (
- [82796] annual_report 2026-09-01 p33 score=10.25 cov=5 phr=0 — BOARD’S REPORT » Your Company has undertaken several initiatives for the socio-economic development of SCs/STs and other weaker sections of the society which are mainly a
- [83193] annual_report 2026-09-01 p287 score=9.929 cov=5 phr=0 — 3.21.9 Useful lives of depreciable/ amortisable assets (tangible and intangible) Management reviews its estimate of the useful lives of depreciable/ amortisable assets at
- [82936] annual_report 2026-09-01 p89 score=9.89 cov=5 phr=0 — 3.22 Recent Accounting Pronouncements Ministry of Corporate Affairs (“MCA”) notifies new standard or amendments to the existing standards under Companies (Indian Accounti
- [88371] concall 2024-08-16 p5 score=9.4 cov=4 phr=0 — Amit Dixit: Okay. The second question is around debt. If I look at debt that has actually went up significantly compared to last quarter. And I also assume that finished 
- [94904] concall 2026-05-20 p6 score=8.43 cov=3 phr=0 — Chaitanya Iyer: Thank you So much. And the second question was in terms of -- so as you mentioned, we saw the impact of downward revision in rail prices. Can you please l
- [107109] results_notes 2026-07-24 p20 score=8.1 cov=3 phr=0 — In this regard, the Company also obtained opinions from the Additional Solicitor General of India as well as the Expert Advisory Committee (EAC) of Institute of Chartered
- [107108] results_notes 2026-07-24 p19 score=7.65 cov=3 phr=0 — CONSOLIDATED SEGMENT WISE REVENUE, RESULTS, ASSETS AND LIABILITIES ? crores unless stated otherwi CONSOLIDATED Quarter ended Year ended 30th June 2026 31st March 2026 30t
- [107110] results_notes 2026-07-24 p22 score=7.425 cov=3 phr=0 — carrying value of the non-current inventories need not be adjusted for any unforeseeable changes in the future prices. Accordingly, in view of the management, the carryin

**Gold locator:** chunk 95764 concall 2026-08-01 overlap=1.0 in_top=False

**Corpus probe (not shown to the model):**
- cov=5 [70352] annual_report 2025-08-25 — ANNUAL REPORT 2024-25 37 » For Skill Development and better employability, youths & women of peripheral villages have been provided vocational and specialized skill development training at various ITIs, Nursing tribal sc
- cov=5 [70934] annual_report 2025-08-25 — ANNEXURE TO THE NOTICE EXPLANATORY STATEMENT PURSUANT TO SECTION 102(1) OF THE COMPANIES ACT, 2013 Item No.5 Pursuant to the Government of India, Ministry of Steel Order No.S-14016/2/2023-BLA dated 13th January, 2025, Sh
- cov=5 [70645] annual_report 2025-08-25 — L27109DL1973GOI 006454 2 Name of the Listed Entity Steel Authority of India Limited 3 Year of incorporation 1973 4 Registered office address Ispat Bhawan, Lodhi Road, New Delhi – 110003 5 Corporate address Ispat Bhawan, 
- cov=5 [70939] annual_report 2025-08-25 — With academic credentials in Commerce and Law (B.Com., LLB.), he has been a trusted advisor to numerous companies and non- governmental organizations across India. Throughout his career, Mr. Roy has guided clients in str


## Q05 MB0540 SAIL — verified

**Q:** SAIL advanced capital repairs into Q1 FY27 to free up later quarters. Did the later quarters show the output recovery it implied?

as_of=2026-10-07 types=concall,results_notes template=A14 gold_found=True gold_in_top=True gold_rank=1
**Bank gold:** “SAIL decided actually to advance some of its major capital repairs during quarter 1, so that it will be free after that and will start producing better in the next quarters.”

**Answer:** SAIL stated that Q2, Q3 and Q4 production volumes will be more than last year and expected yearly growth versus 2025-26, but the excerpts do not show actual later-quarter output results.

**Quote:** in Q2, Q3 and Q4, the production volumes will be more than that of last year. And on the yearly basis, there is expected to be a growth as compared to '25-'26.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** actual production/output figures for Q2, Q3 and Q4 FY27

**Retrieved chunks:**
- [95764] concall 2026-08-01 p3 score=11.2 cov=4 phr=1 **GOLD** — Ashok Panda: Thank you very much, Mr. Ashish Kejriwal. Good morning, everyone. I welcome all our investors and analysts who are joining this results con-call for the fina
- [95798] concall 2026-08-01 p17 score=10.825 cov=3 phr=1 — Rajesh Ravi: I have 2 questions. First, given the volume decline and the low capex, which we have done in Q1, does -- could you give us a sense of what we are looking at 
- [92899] concall 2025-11-03 p18 score=8.55 cov=2 phr=1 — Vinit Thakur: Hi, sir. Good morning. Sir, I just want to know why is there a reduction in the OPM as in QoQ and year-on-year as well? Dr. Ashok Kumar Panda: Pardon? Can y
- [94904] concall 2026-05-20 p6 score=8.529 cov=3 phr=0 — Chaitanya Iyer: Thank you So much. And the second question was in terms of -- so as you mentioned, we saw the impact of downward revision in rail prices. Can you please l
- [92873] concall 2025-11-03 p9 score=8.4 cov=2 phr=1 — Rajesh Ravi: Okay. And on the cost side, you mentioned that the coking coal prices will be higher by $6 to $7, right, in this quarter? Dr. Ashok Kumar Panda: It looks lik
- [82764] annual_report 2026-09-01 p7 score=8.3 cov=4 phr=0 — Capital investments were directed toward revamping Blast Furnaces, rebuilding Coke Oven Batteries, and upgrading finishing mills. These targeted interventions aim to elim
- [83251] annual_report 2026-09-01 p319 score=7.65 cov=2 phr=1 — ANNUAL REPORT 2025-26 Consolidated Financial Statements Sl. No. Name of the Jointly Controlled Entities Details of Differing Accounting Policy in comparison to Accounting
- [83241] annual_report 2026-09-01 p308 score=6.75 cov=3 phr=0 — 41: OTHER EXPENSES Consumption of stores & spares Consumption 6436.58 6262.06 Less: Departmentally manufactured stores 724.48 695.96 Less: Finished products internally co
- [83203] annual_report 2026-09-01 p292 score=6.729 cov=3 phr=0 — A. BUILDINGS Buildings 2.06 - - 2.06 1.07 0.03 - 1.10 0.96 Total 2.06 - - 2.06 1.07 0.03 - 1.10 0.96 (i) Contractual obligations There are no contractual obligation to pu
- [82947] annual_report 2026-09-01 p94 score=6.713 cov=3 phr=0 — A. BUILDINGS Buildings 2.06 - - 2.06 1.07 0.03 - 1.10 0.96 Total 2.06 - - 2.06 1.07 0.03 - 1.10 0.96 (i) Contractual obligations There are no contractual obligation to pu

**Quote context:**

>  volume front, as I told you, there is a reduction of around 0.1 million tonnes of production. That is because we advanced the capital repairs at IISCO at Durgapur and at Bokaro steel mill. So that was by design. So in Q2, Q3 and Q4, the production volumes will be more than that of last year. And on the yearly basis, there is expected to be a growth as compared to '25-'26. Moderator: Ladies and gentlemen, we will take that as the last question for today. I would now like to hand the conference over to the management for the closing remarks. Ashok Panda: Yes. So from me, as a closing remark, thank you very much for your Q&A session. The foreca

**Gold locator:** chunk 95764 concall 2026-08-01 overlap=1.0 in_top=True


## Q06 MB0557 POLYCAB — verified

**Q:** Is Polycab's capex funded by debt or internal accruals, and how does the disclosure show it?

as_of=2026-10-07 types=concall template=A16 gold_found=True gold_in_top=False gold_rank=None
**Bank gold:** None: 3.2 INR billion (Q1 FY27) — “Capital expenditure during the quarter amounted to INR 3.2 billion, reflecting our continued commitment to building capacity and strengthening future growth drivers.”

**Answer:** Polycab's capex is funded through internal accruals, not debt, as disclosed in both the annual report and concall.

**Quote:** we continue to fund our strategic capacity expansions strictly through internal accruals

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [38273] concall 2026-05-08 p12 score=12.2 cov=4 phr=1 — Puneet Gulati: Understood. That's helpful. And lastly, if I may, you have a significant amount of cash. I know there is a nice capex plan, but you can fund it out of your
- [19942] annual_report 2026-06-09 p12 score=11.3 cov=4 phr=1 — CORPORATE OVERVIEW Message from the Chairman 11 Message from Joint MD 14 Manufacturing Excellence & Innovations 18 Infrastructure that Builds the Nation 29 Sustained Grow
- [19977] annual_report 2026-06-09 p46 score=9.25 cov=3 phr=1 — BUSINESS STRATEGY Future-ready Strategic Transformation Launched just twelve months ago as a five-year plan, Project SPRING is now the primary engine driving our most dyn
- [19931] annual_report 2026-06-09 p2 score=8.89 cov=3 phr=1 — INTEGRATED ANNUAL REPORT 2025-26 POLYCAB INDIA LIMITED India’s ascent on the global economic order offers a springboard for our ambitions. At Polycab, we are leveraging o
- [20443] annual_report 2026-06-09 p408 score=8.5 cov=4 phr=0 — 0.00 Customer 47 Capital management For the purpose of the Group capital management, capital includes issued equity capital, securities premium and all other equity reser
- [36041] concall 2025-10-28 p5 score=8.45 cov=3 phr=0 — Chirayu Upadhyaya: Thank you, Gandharv. Let me now take you through Slide 4 of the earnings presentation. For the quarter ended 30th September 2025, we are pleased to rep
- [20571] annual_report 2026-06-09 p505 score=8.425 cov=4 phr=0 — 0.00 Customer 44 Capital management For the purpose of the Company’s capital management, capital includes issued equity capital, securities premium and all other equity r
- [37144] concall 2026-01-22 p5 score=8.225 cov=3 phr=0 — Shashank Yagnick: Thank you, Niyant. Let me now take you through Slide 4 of the earnings presentation. For the quarter ended 31st December 2025, we are pleased to report 
- [38261] concall 2026-05-08 p5 score=8.15 cov=3 phr=0 — Shashank Yagnick: Thank you, Niyant. For the quarter ended March 31, 2026, we are pleased to report a strong performance with consolidated revenue growing 27% year-on-yea
- [38260] concall 2026-05-08 p4 score=7.545 cov=3 phr=0 — The Bank of England also held at 3.75% with markets now pricing 2 rate hikes this year. The ECB maintained rates at 2% but revised its 2026 inflation projection sharply u

**Quote context:**

> ising government capital expenditure and the domestic real estate revival, propelled us to our highest monthly revenues to date. Today, with a highly resilient balance sheet and a net cash position at `41.9 billion, we continue to fund our strategic capacity expansions strictly through internal accruals, redefining the benchmark for profitable growth. Accelerating Ahead of the Curve

**Gold locator:** chunk 39303 concall 2026-07-20 overlap=1.0 in_top=False


## Q07 MB0437 POLICYBZR — not_stated

**Q:** PB Fintech fell 36% on 24 September 2026. What was scheduled that day, and what did the exchange ask for afterwards?

as_of=2026-09-27 types=concall,announcement template=A08 gold_found=True gold_in_top=False gold_rank=None
**Bank gold:** POLICYBZR closed 1,207.2 on 2026-09-24, -36%, delivery 59.32%

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** The excerpts do not mention a 36% fall on 24 September 2026, what was scheduled that day, or any exchange query afterwards.

**Retrieved chunks:**
- [28120] annual_report 2026-09-05 p141 score=9.5 cov=4 phr=0 — These are also submitted to the Stock Exchanges on which the securities of the Company are listed in accordance with the requirements of the Listing Regulations and publi
- [53005] announcement 2026-08-05 p61 score=9.15 cov=3 phr=0 — M U L T I L A Y E R I N T E L L I G E N C E S T A C K ↑ IMPACT Powered by layers 1→2→3 Customer Experience · 24×7 service availability · 2× faster issue resolution · Sing
- [49958] deck 2026-05-11 p55 score=8.7 cov=3 phr=0 — 54 Every interaction captured, each signal converted to intelligence M U L T I L A Y E R I N T E L L I G E N C E S T A C K ↑ IMPACT Powered by layers 1→2→3 Customer Exper
- [107324] results_notes 2026-08-05 p61 score=8.7 cov=3 phr=0 — M U L T I L A Y E R I N T E L L I G E N C E S T A C K ↑ IMPACT Powered by layers 1→2→3 Customer Experience · 24×7 service availability · 2× faster issue resolution · Sing
- [27946] annual_report 2026-09-05 p36 score=8.65 cov=3 phr=0 — 65 Lakh 65 Lakh Customer calls monitored and transcribed monthly Customer calls monitored and transcribed monthly At scale, the Paisabazaar platform must continuously det
- [28123] annual_report 2026-09-05 p143 score=8.269 cov=3 phr=0 — STATUTORY REPORTS Integrated Annual Report FY 2025-26 PB Fintech Limited 269 Shareholding Pattern as on March 31, 2026 Category Category of shareholder No. of shareholder
- [32022] concall 2024-11-11 p5 score=7.4 cov=2 phr=0 — Sachin Dixit: Thanks Rasleen. Congrats Yashish and team on another great set of results. I had a couple of questions. The first one was in terms of growth. As Yashish alr
- [38347] concall 2026-05-12 p10 score=7.1 cov=2 phr=0 — Management: Dipanjan, largely, Paisabazaar has about 5.8 Cr consumers that it has acquired till date and that almost represents 50% of the active credit Indians in India.
- [27901] annual_report 2026-09-05 p4 score=7.02 cov=3 phr=0 — Members can join the AGM through VC/ OAVM mode 15 minutes before and after the scheduled time of the commencement of the AGM by following the procedure mentioned in the N
- [17205] annual_report 2025-09-04 p17 score=6.95 cov=3 phr=0 — The shareholders in the 15th Annual General Meeting of the Company held on September 23, 2023 had approved the payment of remuneration to Mr. Sarbvir Singh, in the nature

**Gold locator:** chunk 18537 annual_report 2025-09-09 overlap=0.556 in_top=False

**Corpus probe (not shown to the model):**
- cov=3 [107223] results_notes 2026-07-31 — SCRIP CODE: 543390 Sub: Intimation of Board Meeting under Regulation 29 of the Securities and Exchange Board of India (Listing Obligation and Disclosure Requirement) Regulations, 2015 and update on closure of trading win
- cov=3 [17423] annual_report 2025-09-04 — 11:00 A.M. (IST) Venue Video Conferencing/Other Audio- Means (OAVM) Financial Calendar for consideration of quarterly results for the FY 2025-26: For quarter ended on June 30, 2025 On or before August 14, 2025 For quarte
- cov=3 [18563] annual_report 2025-09-09 — 11:00 A.M. (IST) Venue Video Conferencing/Other Audio- Means (OAVM) Financial Calendar for consideration of quarterly results for the FY 2025-26: For quarter ended on June 30, 2025 On or before August 14, 2025 For quarte
- cov=3 [17312] annual_report 2025-09-04 — UTILISATION OF IPO PROCEEDS During the year under review, the IPO proceeds were utilized as per the objects stated in the prospectus of the Company and pursuant to Regulation 32 of the SEBI Listing Regulations. There wer


## Q08 MB0045 JSWSTEEL — verified

**Q:** JSW Steel (NSE: JSWSTEEL) ke latest annual report mein ownership ya control change ke baare mein kya likha hai? Kaunsa saal, kaunsa page, aur exactly kya disclosure hai?

as_of=2026-10-19 types=annual_report template=DBQ2 gold_found=None gold_in_top=False gold_rank=None
**Bank gold:** (none)

**Answer:** JSW Steel's latest annual report (FY25) discloses a judgement on control over JSW Realty & Infrastructure Private Limited (RIPL) on page 230 (standalone) and page 290 (consolidated): although the Company holds no ownership interest in RIPL, it concluded it has practical ability to direct RIPL's relevant activities unilaterally, given RIPL's dependency on the Company's funding of most of its operations through preference share subscriptions.

**Quote:** Though the Company does not hold any ownership interest in RIPL, the Company has concluded that the Company has practical ability to direct the relevant activities of RIPL unilaterally, considering RIPL’s dependency on the Company for funding significant portion of its operation through subscription to 76.27% of preference share capital amounting to I 355 crores issued by RIPL and significant portion of RIPL’s activities.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [7889] annual_report 2025-07-03 p230 score=7.75 cov=4 phr=0 — The estimates have been made considering the future expansion plans, additional time allowed for removal of iron ore after expiry of lease period, grade ascertained in th
- [8007] annual_report 2025-07-03 p290 score=7.729 cov=4 phr=0 — Inventory which is expected to be sold to third party is only considered for provision which is computed by comparing Net realisable value and cost. The estimation for pe
- [7822] annual_report 2025-07-03 p201 score=7.617 cov=4 phr=0 — 2.15 Performance evaluation: Pursuant to the provisions of the Companies Act, 2013 and Regulation 17(10), 19(4) and Part D of Schedule II of the SEBI (LODR) Regulations,
- [7865] annual_report 2025-07-03 p219 score=6.9 cov=3 phr=0 — A company's internal financial controls with reference to standalone financial statements includes those policies and procedures that (1) pertain to the maintenance of re
- [513] annual_report 2024-07-04 p58 score=6.536 cov=4 phr=0 — 05 / SUSTAINABILITY / ENVIRONMENT initiatives, monitoring progress against sustainability objectives, and vetting the annual Business Responsibility and Sustainability Re
- [52788] announcement 2026-08-01 p8 score=5.9 cov=2 phr=0 — IN TIIE NATIONAL COMPAI{Y LAW TRIBUNAI MI.]MBAI BENCH.I cP (cAA) NO. &/MB/2026 rN cA (cAA) No. t6/MB /2026 lv vt. v vlll becoming effective. Accordingly, the question of 
- [52777] announcement 2026-07-31 p3 score=5.45 cov=2 phr=0 — PRESS RELEASE 2 capital, more deliberate about the pace of our growth while managing key financial ratios across cycles. A stronger balance sheet and a meaningfully optim
- [51096] deck 2026-07-17 p14 score=5.129 cov=2 phr=0 — 13 JSW Steel Q1 FY27 Results Presentation / Environment: Our Targets & Commitments Target reduction for CO2 emissions, specific energy consumption, specific water consump
- [43946] deck 2025-01-24 p8 score=4.4 cov=2 phr=0 — 7 JSW Steel Q3 FY25 Results Presentation / Environment: Our Targets & Commitments Target reduction for CO2 emissions, specific energy consumption, specific water consumpt
- [47371] deck 2025-10-17 p8 score=4.325 cov=2 phr=0 — 7 JSW Steel Q2 FY26 Results Presentation / Environment: Our Targets & Commitments Target reduction for CO2 emissions, specific energy consumption, specific water consumpt

**Quote context:**

> ides individual housing units on rent to the employees of the Company or other group companies. RIPL is not allowed to sub-let or assign its rights under the arrangement without prior written consent of the Company. Though the Company does not hold any ownership interest in RIPL, the Company has concluded that the Company has practical ability to direct the relevant activities of RIPL unilaterally, considering RIPL's dependency on the Company for funding significant portion of its operation through subscription to 76.27% of preference share capital amounting to I 355 crores issued by RIPL and significant portion of RIPL's activities. ii) Det


## Q09 MB0338 TITAGARH — verified

**Q:** Titagarh Rail Systems is 'ready to ramp up' wagon output. To what monthly run-rate, and what single condition does management put on doing it?

as_of=2026-10-31 types=concall,deck template=A01 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** “it is also ready to ramp up and get to 1,200 wagons per month, but we shall be only doing that once we see sustainable business demand”

**Answer:** Management says the company is ready to ramp up wagon output to 1,200 wagons per month, but only once it sees sustainable business demand in terms of the business outlook, which would also follow finalization of the new railways tender.

**Quote:** it is also ready to ramp up and get to 1,200 wagons per month, but we shall be only doing that once we see sustainable business demand in terms of the business outlook, and that would also happen once the new tender of the railways is finalized.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [91503] concall 2025-06-06 p3 score=18.5 cov=7 phr=2 — Umesh Chowdhary: Thank you, Prachi. A very good afternoon to everybody, and thank you very much for joining this Q4 FY '25 and FY '25 Earnings Call of Titagarh Rail Syste
- [91525] concall 2025-06-06 p15 score=14.8 cov=6 phr=1 **GOLD** — Ravi Gupta: My first question is, could you provide an update on the timeline for achieving the targeted run rate of 1,200 wagons per month? And based on current producti
- [91506] concall 2025-06-06 p6 score=11.35 cov=4 phr=1 — And what are the timelines for products and approval? And what kind of revenue visibility we can expect over 3 to 5 years? Those are my first question, sir. Umesh Chowdha
- [69981] annual_report 2025-08-24 p34 score=11.153 cov=4 phr=2 — TRSL is reaonably confident of achieving the target of around During the year under review, the revenue from Freight Rail Systems segment (FRS) is higher by 5.64% and PBI
- [72593] annual_report 2025-09-04 p34 score=11.15 cov=4 phr=2 — TRSL is reaonably confident of achieving the target of around During the year under review, the revenue from Freight Rail Systems segment (FRS) is higher by 5.64% and PBI
- [91511] concall 2025-06-06 p10 score=10.88 cov=4 phr=1 — Koushik Mohan: 60 to 90 days. Okay. Sir. And in this year, how many cars that are we planning to sell? Any guidance do we have? Is there any specific number? Umesh Chowdh
- [91504] concall 2025-06-06 p5 score=10.813 cov=4 phr=1 — And the Vande Bharat is expected in end of Q4 or beginning of Q1 of the next financial year. The other great development that we've had is the propulsion division of the 
- [85809] annual_report 2026-09-08 p21 score=9.95 cov=5 phr=0 — TITAGARH RAIL SYSTEMS LIMITED Annual Report | 2025-2026 Corporate Overview Statutory Reports Financial Statements Management Discussion & Analysis exports and, over time,
- [100135] deck 2025-02-14 p12 score=8.05 cov=4 phr=0 — 11 Q3 FY25 - Key Business Updates 2,050 2,670 2,233 Q3 FY24 Q2 FY25 Q3 FY25 5,689 6,976 9M FY24 9M FY25 Wagons sold during the period Freight Rail Systems Passenger Rail 
- [69980] annual_report 2025-08-24 p34 score=7.6 cov=4 phr=0 — TITAGARH RAIL SYSTEMS LIMITED Annual Report | 2024-2025 Corporate Overview Statutory Reports Financial Statements Management Discussion & Analysis Management Discussion a

**Quote context:**

> s concerned, we have already touched on a number of occasions, 1,000 wagons per month. The overall wagon capacity is calibrated also on the overall business opportunity available. As far as the company is concerned, it is also ready to ramp up and get to 1,200 wagons per month, but we shall be only doing that once we see sustainable business demand in terms of the business outlook, and that would also happen once the new tender of the railways is finalized. But I can confirm that particularly with the expansion of the foundry that we are going to bring on stream within this financial year, we are, as a company, ready to ramp up our production

**Gold locator:** chunk 91525 concall 2025-06-06 overlap=1.0 in_top=True


## Q10 MB0385 HDFCBANK — verified

**Q:** What were HDFC Bank's key audit matters in its latest annual report, and did any repeat?

as_of=2026-10-07 types=annual_report,results_notes template=A04 gold_found=None gold_in_top=False gold_rank=None
**Bank gold:** (none)

**Answer:** The latest (FY26) annual report lists, among others, IT program development controls over application development, data migration and infrastructure, and the appropriateness of timing of revenue recognition for a life insurance subsidiary as key audit matters; the excerpt does not state whether any repeated.

**Quote:** Program development, which includes controls over existing and new IT application development, implementation, data migration and supporting infrastructure, which are relied upon for financial reporting process.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** Whether any key audit matter repeated from the prior year is not stated in the excerpts.

**Retrieved chunks:**
- [64728] annual_report 2025-07-14 p452 score=19.4 cov=6 phr=3 — Integrated Annual Report 2024-25 439 Statutory Reports and Financial Statements 13. As part of an audit in accordance with SAs, we exercise professional judgment and mai
- [65600] annual_report 2025-07-25 p435 score=18.95 cov=6 phr=3 — Integrated Annual Report 2024-25 439 Statutory Reports and Financial Statements 13. As part of an audit in accordance with SAs, we exercise professional judgment and mai
- [64725] annual_report 2025-07-14 p447 score=18.3 cov=6 phr=3 — I N D E P E N D E N T A U D I T O R ’ S R E P O R T 6. The following Key Audit Matters were included in the audit report issued by the joint auditors, G.D. Apte & Co. an
- [65597] annual_report 2025-07-25 p430 score=17.85 cov=6 phr=3 — I N D E P E N D E N T A U D I T O R ’ S R E P O R T 6. The following Key Audit Matters were included in the audit report issued by the joint auditors, G.D. Apte & Co. an
- [79643] annual_report 2026-07-11 p484 score=17.6 cov=5 phr=3 — 464 HDFC Bank Limited Integrated Annual Report 2025-26 Key Audit Matter How the matter was addressed in our audit   Program development, which includes controls over ex
- [94515] concall 2026-04-24 p4 score=6.9 cov=3 phr=0 — The USP of our build focuses on security. We have an OTP-less authentication. We have a lock, which is for enhanced security, and we have a full stack UPI-enabled wallet,
- [95522] concall 2026-07-24 p3 score=6.42 cov=2 phr=0 — Srinivasan Vaidyanathan: Thank you, Neerav. Good evening and a warm welcome to all the participants. We have today with us our CEO, Sashi Jagdishan, and our Deputy MD, Ka
- [95545] concall 2026-07-24 p12 score=6.05 cov=2 phr=0 — Srinivasan Vaidyanathan: The annual report we just published few days ago will show you the profile of maturity of borrowings. You'll see that INR40,000 crores or INR50,0
- [95530] concall 2026-07-24 p7 score=5.99 cov=2 phr=0 — new acquisitions because we were gearing ourselves to the new realm of better quality acquisitions. As we now move forward, you will and one should see a step up in as wh
- [95535] concall 2026-07-24 p8 score=5.953 cov=2 phr=0 — Srinivasan Vaidyanathan: Yes. Cost of funds benefit will play out and it is very much in the works, both in our annual review of plans and as well as our strategic review

**Quote context:**

> 464 HDFC Bank Limited Integrated Annual Report 2025-26 Key Audit Matter How the matter was addressed in our audit   Program development, which includes controls over existing and new IT application development, implementation, data migration and supporting infrastructure, which are relied upon for financial reporting process.   IT operations, which includes job scheduling, monitoring and backup and recovery.  Evaluating the design and testing the operating effectiveness of relevant key IT dependencies within the key business process, which included testing automated controls, interfaces and system generated reports, as applicable.  T


## Q11 MB0393 KAYNES — not_stated

**Q:** Kaynes Technology filed a 'Change in Management' on 13 May 2026. Who changed, in what role, and when did it take effect?

as_of=2026-10-31 types=results_notes,announcement template=A05 gold_found=False gold_in_top=False gold_rank=None
**Bank gold:** KAYNES: “Change in Management” filed 2026-05-13T18:05:03.23

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** who changed, the role, and the effective date of the Change in Management filing on 13 May 2026

**Retrieved chunks:**
- [38433] concall 2026-05-19 p12 score=8.75 cov=3 phr=0 — Nitin Arora: Sir, I don't want a number. The question was more what will change suddenly which will get your INR600 crores negative cash to breakeven? Our business remain
- [38426] concall 2026-05-19 p3 score=8.364 cov=3 phr=0 — Moderator: Sorry to interrupt you in between, sir. Your voice is subdued a little bit. Kaynes Technology India Limited May 14, 2026 Page 3 of 19 Ramesh Kunhikannan: Near-
- [38428] concall 2026-05-19 p7 score=7.913 cov=3 phr=0 — These initiatives across the organization are not just about improving the manufacturing metrics. These are about creating a culture of ownership, discipline, a continuou
- [50044] deck 2026-05-13 p14 score=7.6 cov=2 phr=0 — Cash Flow Statements (Consolidated) 13 FY26 FY25 FY24 Particulars (₹ Mn) Cash flow from operating activities 5,043 3,716 2,316 Profit before tax 1,674 626 401 Adjustment 
- [51594] deck 2026-08-07 p5 score=7.5 cov=3 phr=0 — Confidential © 2026 Copyright Kaynes Technology. All Rights Reserved Confidential Global Uncertainties Driving Longer Lead Times 4 US – Iran Conflict + AI / Data Centre B
- [31952] concall 2024-11-05 p21 score=6.9 cov=3 phr=0 — requirement that keeps coming in. And so there could be two, three effects on this, we have to consider. One is a technology effect. Over time, what will happen is that t
- [51611] deck 2026-08-07 p25 score=6.713 cov=3 phr=0 — Confidential © 2026 Copyright Kaynes Technology. All Rights Reserved Confidential Cash Flow Statement - Consolidated 24 FY26 FY25 FY24 Particulars (₹ Mn) Cash flow from o
- [38435] concall 2026-05-19 p13 score=6.335 cov=1 phr=0 — Ramesh Kunhikannan: Regarding the rail business, our Kavach product has received the initial approval, and we have got the trial orders. We are in the execution stage. We
- [50036] deck 2026-05-13 p2 score=6.135 cov=2 phr=0 — Kaynes Technology India Limited Investor Presentation | May 2026 Disclaimer 2 This presentation has been prepared by Kaynes Technology India Limited (“Company") solely fo
- [4011] annual_report 2024-08-17 p242 score=6.1 cov=3 phr=0 — B. OTHER EQUITY For the year ended 31 March, 2026 Particulars Reserves & Surplus Other Comprehensive Income Total Other Equity Non Controlling Interest Total Securities p

**Corpus probe (not shown to the model):**
- cov=4 [3755] annual_report 2024-08-17 — 11 March, 2026 Note: 1. Mr. Ramesh Kunhikannan was re-designated from the office of Managing Director to that of Executive Vice- Chairman in the category of Whole-Time Director with effect from 24 September, 2025. 2. Dr.
- cov=4 [4101] annual_report 2024-08-17 — 31 March, 2025 Impact of change in Discount Rate Present Value of Obligation at the end of the period 47.99 37.70 Impact due to increase of 1% 45.08 29.24 Impact due to decrease of 1% 51.37 34.91 Impact of change in sala
- cov=4 [3970] annual_report 2024-08-17 — 31 March, 2025 Impact of the change in Discount Rate Present Value of Obligation at the end of the period 24.35 21.92 Impact due to increase of 1% 22.38 20.10 Impact due to decrease of 1% 26.69 24.07 Impact of the change
- cov=4 [3808] annual_report 2024-08-17 — 10 November, 2025 due to other professional commitments further, he has confirmed that there are no other material reasons other than those provided. Mr. Heinz Franz Moitzi resigned as an Independent Director of the Comp


## Q12 MB0347 DIXON — verified

**Q:** Dixon's operating margin compressed because the mobile-PLI benefit expired. When does management expect the margin to normalise, and on what?

as_of=2026-10-31 types=concall,results_notes template=A02 gold_found=True gold_in_top=True gold_rank=1
**Bank gold:** “Operating margin for the quarter reflected temporary compression on account of expiry of Mobile PLI 1 in March '26 and from increased selling prices driven by elevated input costs”

**Answer:** Management expects operating margins to restore from the next fiscal of '27, '28, driven by component backward integration (display and camera modules), participation in mobile PLI 2 and ECMS.

**Quote:** strategic pivot towards component backward integration, including display and camera modules, along with participation in mobile PLI 2 and ECMS positions the company to drive absolute profit growth and restore operating margins from the next fiscal of '27, '28.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [95875] concall 2026-08-05 p3 score=21.6 cov=8 phr=2 **GOLD** — Atul Lall: I would like to warmly welcome all our stakeholders to discuss our Q1 performance for '26- '27. Key highlights for the quarter are as below. Revenues for the q
- [92697] concall 2025-10-24 p14 score=18.525 cov=7 phr=2 — Atul Lall: Pankajji, as we have been sharing with you that the way we look at our business is that we look at a large opportunity pool. And once we have the large opportu
- [91855] concall 2025-07-28 p18 score=15.75 cov=8 phr=1 — Atul Lall: For camera modules, we never mentioned it is going to be mid-teens. Please appreciate that when you are doing the manufacturing in India and to secure more ord
- [89705] concall 2025-01-24 p19 score=15.35 cov=8 phr=0 — Keyur Pandya: Congratulations on consistent performance. A couple of questions. First, on the mobile segment. So FY '26 being the last year of PLI incentives. Post that, 
- [89703] concall 2025-01-24 p18 score=14.8 cov=6 phr=1 — Amarnath Bhakat: Just want to ask two small questions just on the investment fund. Just two small questions. One, you can see this revenue is growing, but on quarter-on-q
- [84754] annual_report 2026-09-03 p87 score=10.7 cov=5 phr=0 — ISO 9001:2015, ISO 14001:2015, SA 8000 Strategic Focus Emphasis on components with higher engineering content. Leverage existing manufacturing scale. Enhance per-unit val
- [84766] annual_report 2026-09-03 p102 score=9.98 cov=5 phr=0 — We remain focused to strengthen capital efficiency and balance sheet quality. Improved asset utilisation, operating leverage and disciplined capital allocation supported 
- [85280] annual_report 2026-09-03 p509 score=8.35 cov=4 phr=0 — NOTES FORMING PART OF THE CONSOLIDATED FINANCIAL STATEMENTS (Contd.) Corporate Overview Statutory Reports Financial Statements 500 was granted by IFCI Limited, the design
- [84878] annual_report 2026-09-03 p192 score=8.312 cov=4 phr=0 — LED TV Refrigerators Corporate Overview Statutory Reports Financial Statements 182 During the year, we transferred our Lighting business into our 50:50 JV with Signify, w
- [85158] annual_report 2026-09-03 p428 score=7.05 cov=3 phr=0 — 7.5 Government grants Government Grants are recognised when there is a reasonable assurance that the same will be received and all attached conditions will be complied w

**Quote context:**

> d through increase in selling prices, percentage margins look optically lower, mostly in mobile and IT hardware business. While the sunset of Mobile 1 incentives impacted short-term percentage profitability, Dixon's strategic pivot towards component backward integration, including display and camera modules, along with participation in mobile PLI 2 and ECMS positions the company to drive absolute profit growth and restore operating margins from the next fiscal of '27, '28. Washing machine and refrigerator business witnessed temporary margin pressures on account of volatility in polymer prices, other related input costs and adverse foreign exc

**Gold locator:** chunk 95875 concall 2026-08-05 overlap=1.0 in_top=True


## Q13 MB0526 BEL — verified

**Q:** BEL guided 15% revenue growth for FY27. What did Q1 FY27 actually deliver, and is the guidance still credible?

as_of=2026-10-07 types=concall,results_notes template=A14 gold_found=True gold_in_top=False gold_rank=None
**Bank gold:** revenue growth: 15% (FY27) — “our balanced plan is 15% and I am confident we will reach 15%.”

**Answer:** The excerpts do not state an actual Q1 FY27 revenue growth figure; management said Q1 met internal expectations and maintained the 15% revenue growth guidance.

**Quote:** the Q1 was good, met our internal expectations, whatsoever we had planned, we have more or less executed all of that.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** actual Q1 FY27 revenue growth percentage delivered

**Retrieved chunks:**
- [95013] concall 2026-05-22 p20 score=13.7 cov=4 phr=1 — Manoj Jain: Yes. So, as we told future outlook for year '26-'27, after taking into consideration our present base, our present product mix, our present order book, etcete
- [95680] concall 2026-07-28 p20 score=13.5 cov=4 phr=1 — Moderator: Thank you. Ladies and gentlemen, we will take that as the last question for today. I would now like to hand the conference over to the management for the closi
- [88018] concall 2024-08-01 p12 score=12.69 cov=5 phr=1 — o o S//*dCf B/-/ARATEl£CT/?ON/CS OUA ' JTY. technology, innovation Bharat Electronics Limited July 29, 2024 Moderator: Amit Mahawar: Management: Amit Mahawar: Management:
- [88066] concall 2024-08-01 p12 score=12.682 cov=5 phr=1 — o o S//*dCf B/-/ARATEl£CT/?ON/CS OUA ' JTY. technology, innovation Bharat Electronics Limited July 29, 2024 Moderator: Amit Mahawar: Management: Amit Mahawar: Management:
- [88022] concall 2024-08-01 p19 score=12.58 cov=4 phr=1 — Harshit Kapadia: Thanks, Shubhangi. We would like to thank the management of Bharat Electronics Limited, Shri Manoj Jain - Chairman and Managing Director, Damodar Bhattad
- [106734] announcement 2026-08-05 p26 score=5.9 cov=2 phr=0 — 55.83 KL/ Crore 61.17 KL/ Crore Water intensity per rupee of turnover adjusted for Purchasing Power Parity (PPP) (Total water consumption / Revenue from operations adjust
- [106733] announcement 2026-08-05 p25 score=4.9 cov=1 phr=0 — 19.59 GJ/million USD 22.32 GJ/ million USD Energy intensity in terms of physical output - - Energy intensity (optional) - the relevant metric may be selected by the entit
- [106735] announcement 2026-08-05 p28 score=4.825 cov=1 phr=0 — 1.14 MT/ Crore Total Scope 1 and Scope 2 emission intensity per rupee of turnover adjusted for Purchasing Power Parity (PPP) (Total Scope 1 and Scope 2 GHG emissions / re
- [81674] annual_report 2026-08-05 p7 score=3.9 cov=0 phr=0 — 7 kesÀ mebyebOe ceW - efve³egefÊeÀ veece Deewj [erDeeF&Sve Þeer Decyejer<e ef$eheeþer ([erDeeF&Sve-11888363) pevce efleefLe 2 efomebyej 1968. ceb[ue ceW henueer efve³egef
- [106975] announcement 2026-08-13 p7 score=3.85 cov=1 phr=0 — 3RTRT, Vi^ 14 £I£IR ^JTTf^Rff^t tlHrddl'^4cti |Trr T^Rff3sirf % RT^ ?rich<'Jl ^ >T 4^ cd f%RI vid'Pl TTftfitT % "HM41=(, 3TRRffteHT dpkl Tf^ ?ff ft dild PPKI41 s,u,,^n (^

**Quote context:**

> the closing remarks. BHAMreucr/tON/cs QUALITY, TECHNOLOGY INNOVATION Bharat Electronics Limited July 27, 2026 Page 20 of 20 Manoj Jain: Yes. My closing remarks again is same as my starting remarks of the thing, that the Q1 was good, met our internal expectations, whatsoever we had planned, we have more or less executed all of that. And the future outlook remains the same. The revenue growth of 15%, EBITDA margin 21% to 23%, order inflow of more than INR20,000 crores including QRSAM, the R&D investment more than INR2,200 crores, capex more than INR1,200 crores with a typical defence non-defence business of 90:10. So, this guidance definitely w

**Gold locator:** chunk 95675 concall 2026-07-28 overlap=1.0 in_top=False


## Q14 MB0360 BEL — not_stated

**Q:** BEL ne FY27 ke liye 15% growth bola tha — kaunsa half-year usko uthana padega, aur management ne kya skew bataya? (Hinglish)

as_of=2026-10-31 types=concall,deck template=A02 gold_found=True gold_in_top=True gold_rank=1
**Bank gold:** revenue growth: 15% (FY27) — “our balanced plan is 15% and I am confident we will reach 15%.”

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** which half-year must lift FY27's 15% growth and the skew management stated

**Retrieved chunks:**
- [95675] concall 2026-07-28 p19 score=6.5 cov=1 phr=0 **GOLD** — Shriram Kapoor: Hi sir, thanks for the opportunity. Just wanted to ask about your 15% revenue growth guidance for this year. So, given that you've done 20% in the first q
- [95680] concall 2026-07-28 p20 score=6.418 cov=1 phr=0 — Moderator: Thank you. Ladies and gentlemen, we will take that as the last question for today. I would now like to hand the conference over to the management for the closi
- [88871] concall 2024-10-29 p3 score=6.25 cov=2 phr=0 — Ankush Sharma: Just two questions. One was on the order inflows. What we see for the first half, we've done about INR7,500-odd crores of inflows. Our guidance, I think, i
- [92949] concall 2025-11-04 p3 score=6.064 cov=1 phr=0 — Manoj Jain: Thank you. Good afternoon, everybody. So here is the financial highlights for H1 up to Q2 for financial year '25/'26. So this H1, we have achieved revenue fro
- [93716] concall 2026-01-29 p7 score=5.569 cov=1 phr=0 — Amit Anwani: Thank you. My first question, sir, with respect to the order. So, this year since 9M is quite strong, we will definitely be doing more than INR 27,000 crores
- [106730] announcement 2026-08-05 p20 score=4.3 cov=1 phr=0 — Provide the number of employees / workers having suffered high consequence workrelated injury / ill-health / fatalities (as reported in Q11 of Essential Indicators above)
- [81674] annual_report 2026-08-05 p7 score=3.9 cov=0 phr=0 — 7 kesÀ mebyebOe ceW - efve³egefÊeÀ veece Deewj [erDeeF&Sve Þeer Decyejer<e ef$eheeþer ([erDeeF&Sve-11888363) pevce efleefLe 2 efomebyej 1968. ceb[ue ceW henueer efve³egef
- [106738] announcement 2026-08-05 p34 score=3.85 cov=1 phr=0 — SL. No Initiative undertaken Details of the initiative (Web-link, if any, may be provided along-with summary) Outcome of the initiative 3. Water Conservation 1) Installe
- [106723] announcement 2026-08-05 p7 score=3.7 cov=1 phr=0 — 20 Units/SBUs are certified with QMS AS 9100D, and 8 SBUs/Divisions are certified with QMS ISO 9001, all 9 Units are certified with EMS ISO 14001, and all 9 Units are cer
- [106722] announcement 2026-08-05 p6 score=3.5 cov=1 phr=0 — No. Material issue identified Indicate whether risk or opportunity (R/O) Rationale for identifying the risk / opportunity In case of risk, approach to adapt or mitigate F

**Gold locator:** chunk 95675 concall 2026-07-28 overlap=1.0 in_top=True


## Q15 MB0380 MANKIND — not_stated

**Q:** Mankind ki subsidiary mein auditor resignation kab hui, aur kya file hua? (Hinglish)

as_of=2026-10-07 types=results_notes,announcement template=A04 gold_found=True gold_in_top=False gold_rank=None
**Bank gold:** MANKIND: “Please find attached intimation regarding resignation of Statutory Auditors of the Bharat Serums and Vaccines Limited, a matterial wholly owned subsidiary company.” filed 2026-09-28T15:49:15.627

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** Auditor resignation in a Mankind subsidiary and any filing related to it

**Retrieved chunks:**
- [23083] annual_report 2026-07-09 p212 score=10.25 cov=5 phr=0 — note 55 to the consolidated financial statements, the back-up of books of account was not kept on daily basis in servers physically located in India and for the matters s
- [10049] annual_report 2025-07-15 p192 score=9.2 cov=5 phr=0 — These financial statements and other financial information have been audited by other auditors, which financial statements, other financial information and auditor’s repo
- [23085] annual_report 2026-07-09 p213 score=8.425 cov=4 phr=0 — UDIN: 26528337CMVDDG7551 Place of Signature: New Delhi Date: May 19, 2026 Place of Signature: New Delhi Date: May 19, 2026 v The interim dividend declared and paid durin
- [23084] annual_report 2026-07-09 p212 score=8.38 cov=4 phr=0 — a) The respective managements of the Holding Company and its subsidiaries and associates which are companies incorporated in India whose financial statements have been 
- [9873] annual_report 2025-07-15 p120 score=8.369 cov=5 phr=0 — The Company has not provided any security and granted loans and advances in the nature of loans to companies, firms, Limited Liability Partnerships or any other parties d
- [38702] concall 2026-05-26 p17 score=5.2 cov=1 phr=0 — Alankar Garude: Got it. And one final question with your permission. You approved an investment of up to INR500 crores in one of your subsidiaries, Mankind Medicare. Curr
- [38678] concall 2026-05-26 p5 score=4.929 cov=1 phr=0 — Ashutosh Dhawan: Thank you so much. Thank you, Sheetal ji. A very good afternoon, everyone. Thank you all for taking time out to join our quarter 4 FY26 earnings call. To
- [31979] concall 2024-11-11 p3 score=3.6 cov=1 phr=0 — Rajeev Juneja: Thank you, Abhishek, and good evening, everyone. A very warm welcome to our Q2 & H1 FY25 earning call. I am delighted to share with you all that we have no
- [32853] concall 2025-01-30 p4 score=3.525 cov=1 phr=0 — Sheetal Arora: A very good afternoon to all. Thanks for joining us today for our Q3 & 9M FY25 earnings call. In the last quarter, we completed the acquisition of BSV, str
- [32854] concall 2025-01-30 p5 score=3.45 cov=1 phr=0 — Ashutosh Dhawan: Sure. Thank you, Sheetalji. Good afternoon, everyone. I'm delighted to have you all on our Q3 and 9M FY '25 earnings call with us. This marks the first q

**Gold locator:** chunk 22800 annual_report 2026-07-09 overlap=0.588 in_top=False

**Corpus probe (not shown to the model):**
- cov=4 [10051] annual_report 2025-07-15 — UDIN: 25528337BMLMZW5073 Place of Signature: New Delhi Date: May 21, 2025 Place of Signature: New Delhi Date: May 21, 2025 v) No dividend has been declared or paid during the year by the Holding Company, its subsidiarie
- cov=4 [9784] annual_report 2025-07-15 — 19. AUDITORS a. Statutory Auditors and their report At the AGM held on September 30, 2022, the Members of the Company appointed M/s Bhagi Bhardwaj Gaur & Co., Chartered Accountants, as joint statutory auditors for a ter
- cov=4 [22786] annual_report 2026-07-09 — 17. REMUNERATION OF DIRECTORS, KMP AND PARTICULARS OF EMPLOYEES The Board’s Report includes the requisite disclosures pursuant to Section 197(12) of the Act, read with Rule 5(1) of the Companies (Appointment and Annual
- cov=4 [22839] annual_report 2026-07-09 — 36 to the consolidated financial statements. (h) Disclosures as per the Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013 Disclosure in relation to the Sexual Harassment of Women


## Q16 MB0351 POLYCAB — verified

**Q:** Polycab has started BharatNet execution. Over how many years does that run, and from when?

as_of=2026-10-31 types=concall,deck,results_notes template=A02 gold_found=True gold_in_top=True gold_rank=3
**Bank gold:** “We have started the execution sometime in last quarter in March.”

**Answer:** BharatNet's execution (new infrastructure) runs over a period of 3 years, and Polycab started the execution sometime in the last quarter in March.

**Quote:** Bharat Net, the overall order size is around INR 8,000 crores. Out of that, INR 4,500 crores is the execution piece for new infrastructure which is over a period of 3 years. We have started the execution sometime in last quarter in March.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [34028] concall 2025-05-14 p15 score=7.8 cov=3 phr=0 — Chirayu Upadhyaya: Sure, Praveen. So, the ₹ 70 billion order book which I mentioned consists of two components. Of ₹ 70 billion, ₹ 40 billion is order book from the RDSS 
- [32788] concall 2025-01-29 p5 score=7.45 cov=3 phr=0 — Chirayu Upadhyaya: Thank you, Gandharv. I will first cover the quarterly numbers and then move to Project Spring. I request everyone to refer to Slide 4 of the earnings p
- [39323] concall 2026-07-20 p14 score=6.95 cov=2 phr=0 **GOLD** — Ashish Kanodia: Sure. And just last bit on the EPC side - on a full year basis because quarter-to-quarter, the execution could vary. But on a full year basis, what kind o
- [36043] concall 2025-10-28 p8 score=6.46 cov=2 phr=0 — Moderator: The first question comes from the line of Sonali from Jefferies Group. Sonali: Congratulations on a great set of numbers. Sir, my first question would be in th
- [36064] concall 2025-10-28 p18 score=6.35 cov=2 phr=0 — Natasha Jain: Two questions. One, Chirayu, can you give us the breakdown in terms of order book for RDSS and BharatNet as of today? Chirayu Upadhyaya: So, Natasha, the or
- [20090] annual_report 2026-06-09 p147 score=5.9 cov=2 phr=0 — STATUTORY REPORTS Management Discussion and Analysis EPC Segment The Engineering, Procurement & Construction (EPC) business recorded revenue of `16.7 billion, declining b
- [19943] annual_report 2026-06-09 p13 score=5.45 cov=2 phr=0 — Y E A R I N R E V I E W I N T H I S S E C T I O N This year reaffirmed our belief that enduring leadership is built on strong foundations and strengthened through discipl
- [19982] annual_report 2026-06-09 p49 score=5.3 cov=2 phr=0 — B U S I N E S S R E V I E W I N T H I S S E C T I O N Cables and Wires (C&W) The W&C business continues to grow on the back of strong demand from infrastructure, energy a
- [19944] annual_report 2026-06-09 p14 score=5.18 cov=2 phr=0 — YEAR IN REVIEW Chairman’s Message The International business remains an important pillar of our long-term growth agenda. During the year, we continued to deepen our prese
- [52335] announcement 2026-07-16 p21 score=4.3 cov=1 phr=0 — 30 Jun 26 30 Jun 26 (a) As the liabilities for gratuity and leave encashment are provided on actuarial basis for the Company as a whole, the amounts pertaining to the dir

**Quote context:**

> ll year basis because quarter-to-quarter, the execution could vary. But on a full year basis, what kind of revenue or execution can we expect from RDSS and Bharat Net? Shashank Yagnick: So Ashish, like you remember, Bharat Net, the overall order size is around INR 8,000 crores. Out of that, INR 4,500 crores is the execution piece for new infrastructure which is over a period of 3 years. We have started the execution sometime in last quarter in March. So we can safely say maybe 1/3rd of that should translate into revenue, maybe INR 800 crores to INR 1,000 crores may come from Bharat Net alone. And RDSS, we had overall order book when we starte

**Gold locator:** chunk 39323 concall 2026-07-20 overlap=1.0 in_top=True


## Q17 MB0439 TRENT — not_stated

**Q:** Trent fell 14.77% on 7 April 2025. Was there a company disclosure before the open, and what kind of update was it?

as_of=2025-04-07 types=announcement template=A08 gold_found=False gold_in_top=False gold_rank=None
**Bank gold:** TRENT: “Update for Q4 and Financial Year 2024-25” filed 2025-04-05T09:59:09.257

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** Any company disclosure before the open on 7 April 2025 and its type

**Retrieved chunks:**
- [99854] deck 2025-02-06 p1 score=-2.7 cov=1 phr=0 — 6th February 2025 Listing Department The National Stock Exchange of India Limited Exchange Plaza, Bandra-Kurla Complex, Bandra (East), Mumbai 400051 Symbol: TRENT Listing


## Q18 MB0447 KEI — not_stated

**Q:** KEI rose 9.49% on 4 August 2026 after results filed at 20:52 on 3 August. What did the numbers say about margin?

as_of=2026-08-04 types=announcement template=A08 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** “During FY25-'26, operating margin has improved to 10.46% against 10.18%.”

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** Margin figures (EBITDA margin or operating margin) for the quarter ended June 30, 2026

**Retrieved chunks:**
- [93658] concall 2026-01-29 p3 score=16.4 cov=5 phr=1 — Anil Gupta: Yes. Good morning. Thank you for joining this conference call. I'm Anil Gupta, CMD of KEI Industries Limited. The brief of this quarter, the Q3 is net sales. 
- [94774] concall 2026-05-12 p3 score=15.49 cov=4 phr=1 **GOLD** — Anil Gupta: Okay. Good afternoon, friends. I'm Anil Gupta, CMD, KEI Industries Limited. I will give brief about the financial results of this quarter as well as the full 
- [106706] announcement 2026-08-03 p8 score=15.2 cov=3 phr=0 — 14 Earnings per Equity Share: (of F 2/- each) (not annualised for quarters): a) Basic (F) 28.68 29.74 20.49 96.09 b) Diluted (Z) 28.66 29.72 20.47 96.02 Consolidated Segm
- [63116] annual_report 2025-07-07 p14 score=13.0 cov=4 phr=0 — 11 Integrated Annual Report 2024-25 The wires and cables industry – accounting for nearly 39% of the country’s electrical equipment sector – benefited directly from this 
- [94808] concall 2026-05-12 p15 score=12.95 cov=4 phr=1 — Akshay Gattani: And on the volume growth front, sir, volume growth is accelerating from 6.5% in FY26 to 16% to 18% in '27. So how would this impact operating leverage? An
- [90887] concall 2025-05-14 p3 score=12.413 cov=3 phr=1 — Anil Gupta: Good afternoon dear colleagues. Thank you very much for joining, I am Anil Gupta – Chairman and Managing Director, KEI Industries Limited along with me, Mr. R
- [86952] concall 2024-05-09 p3 score=12.3 cov=5 phr=0 — Anil Gupta: So thank you, Rahul. I'm Anil Gupta, CMD, KEI Industries Limited. I welcome all of you to this Investors Conference Call of KEI Industries Limited. So first, 
- [106702] announcement 2026-08-03 p6 score=11.8 cov=2 phr=0 — The above standalone financial results have been reviewed by the Audit Committee meeting held on August 03, 2026 and thereafter approved by the Board of Directors at thei
- [106703] announcement 2026-08-03 p7 score=11.725 cov=2 phr=0 — LIMITED REVIEW REPORT OF THE INDEPENDENT AUDITORS ON THE STANDALONE UNAUDITED FINANCIAL RESULTS FOR THE QUARTER ENDED ON JUNE 30, 2026 1. We have reviewed the accompanyin
- [63120] annual_report 2025-07-07 p20 score=11.2 cov=4 phr=0 — 17 Integrated Annual Report 2024-25 Output Outcomes Low Tension Cables EHV Cables (Up to 400kV) Solar Cables Instrumentation Cables ESP Cables Flat Cables Thermocouple Ca

**Gold locator:** chunk 94774 concall 2026-05-12 overlap=1.0 in_top=True

**Corpus probe (not shown to the model):**
- cov=5 [90930] concall 2025-05-14 — Ankit Soni: Sir Good Evening, Congratulation for the good set of numbers. Just one question from my side, so once your Sanand facility is operational, what time would we take to get on to a full optimum utilization of th
- cov=5 [90898] concall 2025-05-14 — Dhruv Bhatia: Right. And the second question I have sir is, it's a slightly more industry wide one. You are having some new very aggressive competitors talking about large amounts of CAPEX to enter the sector in the next
- cov=4 [89825] concall 2025-01-28 — Naushad Chaudhary: Yes, I take your point, sir, of growth and EBITDA margin should improve, but because of the EHV thing, do you think the volatility in the business going forward should increase because of the nature of
- cov=4 [94784] concall 2026-05-12 — Achal Lohade: Got it. So the contribution will be relatively small at this stage, right? Anil Gupta: No, it will. Quarter after quarter, it will keep growing. Achal Lohade: So FY26 will be smaller and FY27 will grow subs


## Q19 MB0377 TATASTEEL — rejected_contradiction

**Q:** Tata Steel's Q1 FY27 filing: did it carry an audit qualification, and what exactly does the stored field say?

as_of=2026-10-31 types=results_notes,announcement template=A04 gold_found=False gold_in_top=False gold_rank=None
**Bank gold:** TATASTEEL First quarter (2026-06-30): audit_opinion = 'Not applicable', Audited, filed 2026-07-30T19:54:09

**Answer:** not stated

**Quote:** The said report does not contain any qualification, reservation, adverse remark or disclaimer.

**Verify:** status=rejected_contradiction quote_ok=True kind=None number_ok=True missing_numbers=[]
**Model says missing:** audit qualification status for Tata Steel's Q1 FY27 filing

**Retrieved chunks:**
- [78001] annual_report 2026-06-03 p160 score=9.1 cov=4 phr=0 — The said report does not contain any qualification, reservation, adverse remark or disclaimer. Cost Auditors In terms of Section 148 of the Companies Act, 2013, the Comp
- [78265] annual_report 2026-06-03 p568 score=7.312 cov=2 phr=1 — N16 Item No. 6 – Material Related Party Transaction(s) with Tata Capital Limited Background, details, benefits and justification of the transaction(s): Tata Capital Limit
- [78268] annual_report 2026-06-03 p571 score=7.264 cov=2 phr=1 — Amount of Trade advance b. Tenure c. Whether same is self-liquidating? Point B(2) to B(7) and C(1) to C(6) is not applicable. Arm's length pricing: The RPTs will be enter
- [78036] annual_report 2026-06-03 p205 score=5.3 cov=2 phr=0 — • The trials have established the melting-refining and billet casting process parameters for NPI route stainless steel production process. Oily Bubble Flotation of Coal •
- [95923] concall 2026-08-06 p12 score=5.25 cov=1 phr=0 — Samita Shah: VP CFTRM - Tata Steel Limited Sumangal, I think there are lot of variables here because you're talking about domestic prices, you're talking about internatio
- [77895] annual_report 2026-06-03 p35 score=5.18 cov=2 phr=0 — RISK MANAGEMENT Community risk The communities proximate to Tata Steel’s operating locations across India and Europe have growing expectations on societal impact of busin
- [105230] deck 2026-07-30 p2 score=3.85 cov=1 phr=0 — 1 Page 1 of 3 Mumbai, July 30, 2026 Tata Steel reports Consolidated EBITDA of Rs 9,370 crores for the quarter ended June 30, 2026 Highlights: ▪ Consolidated Revenues for 
- [105231] deck 2026-07-30 p3 score=3.625 cov=1 phr=0 — 1 Page 2 of 3 Management Comments: Mr. T V Narendran, Chief Executive Officer & Managing Director: “Global operating environment remained complex, with the impact of deve
- [104952] deck 2026-07-02 p4 score=3.58 cov=1 phr=0 — 119th Annual General Meeting 3 We are committed to ‘Zero Harm’ Note: 1Employees refers to Permanent and Contract workforce, *Lost Time Injury Frequency Rate per million-m
- [90983] concall 2025-05-18 p6 score=3.1 cov=1 phr=0 — The valuation of investments in subsidiaries is tested against the present value of the future cash flows over the long term. For this, it is necessary to take a view on 


## Q20 MB0535 ULTRACEMCO — not_stated

**Q:** UltraTech's volume growth and capacity additions: did the FY26 additions land on the guided date?

as_of=2026-10-07 types=concall,deck template=A14 gold_found=True gold_in_top=True gold_rank=5
**Bank gold:** “which will take us from the current capacity of 184 million tons, 184 million includes India Cements and Kesoram capacities also from 184 million to take us to close to 212 million tons of capacity in India.”

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** the guided date for the FY26 capacity additions

**Retrieved chunks:**
- [80555] annual_report 2026-07-24 p30 score=15.5 cov=7 phr=1 — CHAIRMAN'S MESSAGE At the Aditya Birla Group, trust is built through experience. It is earned in thousands of everyday interactions—when people are given opportunities to
- [106413] announcement 2026-07-24 p2 score=15.1 cov=5 phr=2 — CARE A1+ Reaffirmed Long-term bank facilities RBI 2,400.00 CARE AAA; Stable Reaffirmed Non-convertible debentures SEBI 5,000.00 CARE AAA; Stable Assigned Details of instr
- [65993] annual_report 2025-07-28 p38 score=13.6 cov=5 phr=2 — 28.8 MTPA of organic capacity additions planned by FY 2026-27. Overall, your Company’s performance in FY 2024-25 is a clear reflection of our long-term future-ready strat
- [88678] concall 2024-10-23 p15 score=13.2 cov=5 phr=1 — Ashish Jain: Sir, my first question is on your capacity additions so while -- if I look at the regional breakup of the capacity addition, it's heavily skewed in favor of 
- [90704] concall 2025-05-02 p3 score=12.853 cov=5 phr=1 **GOLD** — Atul Daga: Thank you so much, Michelle and good evening, and a very warm welcome to all of you for this earnings call for Quarter 4, FY '25 for UltraTech. It's a maze of 
- [80570] annual_report 2026-07-24 p40 score=12.45 cov=5 phr=1 — INTRODUCTION II III IV V VI VII Built to Scale 205.5 MTPA Total grey cement capacity, including overseas operations as on April 2026 242.5 MTPA UltraTech’s target total g
- [95489] concall 2026-07-23 p4 score=12.29 cov=4 phr=1 — upwards. The discussion will not be complete if we don't talk about prices. Cement prices have been constructive during the quarter in the report. Our all India exit pric
- [80564] annual_report 2026-07-24 p36 score=12.225 cov=5 phr=1 — INTRODUCTION II III IV V VI VII With steadfast support of the India growth story, we are focused on our next horizon with a commitment to invest ₹16,000 crore to add anot
- [92724] concall 2025-10-27 p3 score=11.831 cov=4 phr=1 — Atul Daga: Thank you. Good evening, everyone, and welcome to the earnings call of UltraTech Cement for the quarter ended September '25. I realize it is a Saturday, and fo
- [90725] concall 2025-05-02 p11 score=10.829 cov=4 phr=1 — Raashi Chopra: Understood. And on Kesoram, if you were to exclude the Kesoram volumes and how much -- what was your volume growth or if you could just share the Kesoram v

**Gold locator:** chunk 90704 concall 2025-05-02 overlap=1.0 in_top=True

**Corpus probe (not shown to the model):**
- cov=5 [66096] annual_report 2025-07-28 — Initiatives such as renewable energy adoption, waste heat recovery systems, and alternative fuel usage will lead to cost savings, enhancing margins over the next two to three years. Additionally, logistical efficiencies,
- cov=5 [101536] deck 2025-07-21 — Organic growth plans on track 13 G : Greenfield, B : Brownfield, GU : Grinding Unit, IU : Integrated Unit, BT : Bulk Terminal Particulars Unit Project Cement Capacity (Mtpa) Capacity as at March-25 183.4 Nagpur, Maharash
- cov=5 [102373] deck 2025-10-18 — 12 Particulars Unit Project Cement Capacity (mtpa) Nagpur, Maharashtra (Debottlenecking) GU B 0.6 Panipat, Haryana (Debottlenecking) GU B 0.4 Jhajjar, Haryana (Debottlenecking) GU B 0.4 Banswara, Rajasthan (Debottlenecki
- cov=5 [102403] deck 2025-10-20 — 12 Particulars Unit Project Cement Capacity (mtpa) Nagpur, Maharashtra (Debottlenecking) GU B 0.6 Panipat, Haryana (Debottlenecking) GU B 0.4 Jhajjar, Haryana (Debottlenecking) GU B 0.4 Banswara, Rajasthan (Debottlenecki


## Q21 MB0072 CGPOWER — not_stated

**Q:** What did CG Power and Industrial Solutions (NSE: CGPOWER)'s management say about demand and margins on its 12 May 2025 earnings call, and who said it?

as_of=2026-10-19 types=concall template=DBQ5 gold_found=None gold_in_top=False gold_rank=None
**Bank gold:** (none)

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** No earnings call transcript or management commentary from 12 May 2025 about demand and margins is present in the excerpts.

**Retrieved chunks:**
- [62607] annual_report 2025-07-02 p254 score=7.2 cov=3 phr=0 — For S R B C & CO LLP Chartered Accountants ICAI Firm Registration No. 324982E/E300003 Amar Kaul Managing Director & CEO (DIN : 07574081) Vellayan Subbiah Chairman (DIN : 
- [54785] annual_report 2024-06-29 p130 score=6.9 cov=4 phr=0 — NON-CURRENT - OTHER FINANCIAL ASSETS ` crores As at 31-03-2026 As at 31-03-2025 Unsecured, considered good, unless otherwise stated Security deposits 10.02 6.05 Fixed dep
- [62606] annual_report 2025-07-02 p253 score=6.6 cov=3 phr=0 — (B) OTHER EQUITY For the year ended 31 March, 2025 ` crores Reserves and Surplus Items of Other Comprehensive Income (OCI) Total Other Equity Non- Controlling Interest (N
- [62522] annual_report 2025-07-02 p188 score=6.345 cov=3 phr=0 — NON-CURRENT - OTHER FINANCIAL ASSETS ` crores As at 31-03-2025 As at 31-03-2024 Unsecured, considered good, unless otherwise stated Deposits 6.05 7.55 Fixed deposits with
- [62650] annual_report 2025-07-02 p279 score=6.336 cov=3 phr=0 — NON-CURRENT - OTHERS FINANCIAL ASSETS ` crores As at 31-03-2025 As at 31-03-2024 Unsecured, considered good, unless otherwise stated: Deposits 9.27 7.75 Fixed deposits wi
- [99817] deck 2025-02-04 p5 score=6.0 cov=3 phr=0 — 01. Company overview RESTRICTED CG – snapshot of who we are today 4 15.3% FY24 EBITDA Margin3 INR97k cr Market cap1 4,000+ Permanent employees INR8,046cr FY24 Revenue 18 
- [99308] deck 2024-12-02 p5 score=3.95 cov=2 phr=0 — 01. Company overview RESTRICTED CG – snapshot of who we are today 4 15.3% FY24 EBITDA Margin3 INR1.15L cr Market cap1 3,300+ Permanent employees INR8,046cr FY24 Revenue 1
- [99328] deck 2024-12-02 p28 score=3.4 cov=1 phr=0 — RESTRICTED 4,767 5,388 6,166 3,340 2,110 2,179 2,674 2,830 FY22 FY23 FY24 H1FY25 Order intake Order backlog Industrial segment recorded the highest ever sales and order i
- [99837] deck 2025-02-04 p28 score=3.325 cov=1 phr=0 — RESTRICTED 4,767 5,388 6,166 5,962 2,110 2,179 2,674 3,712 FY22 FY23 FY24 9M FY25 Order intake Order backlog Industrial systems recorded the highest ever sales and order 
- [99329] deck 2024-12-02 p29 score=3.28 cov=1 phr=0 — RESTRICTED 2,151 2,865 4,315 3,119 1,558 2,279 3,731 5,131 FY22 FY23 FY24 H1FY25 Order intake Order backlog Power systems’ order intake at an all-time high with a 51% YoY

**Corpus probe (not shown to the model):**
- cov=3 [106247] announcement 2025-07-21 — Our Ref: COSEC/068/2025-26 21st July, 2025 By portal The Corporate Relationship Department BSE Limited 1st Floor, New Trading Ring Rotunda Building, Phiroze Jeejeebhoy Towers, Dalal Street, Mumbai 400 001 Scrip Code : 50
- cov=3 [106201] announcement 2025-01-23 — Our Ref: COSEC/241/2024-25 23rd January, 2025 By portal The Corporate Relationship Department BSE Limited 1st Floor, New Trading Ring Rotunda Building, Phiroze Jeejeebhoy Towers, Dalal Street, Mumbai 400 001 Scrip Code :
- cov=3 [106226] announcement 2025-04-30 — Our Ref: COSEC/012/2025-26 30th April, 2025 By portal The Corporate Relationship Department BSE Limited 1st Floor, New Trading Ring Rotunda Building, Phiroze Jeejeebhoy Towers, Dalal Street, Mumbai 400 001 Scrip Code : 5
- cov=3 [106264] announcement 2025-10-24 — Our Ref: COSEC/114/2025-26 24th October, 2025 By portal The Corporate Relationship Department BSE Limited 1st Floor, New Trading Ring Rotunda Building, Phiroze Jeejeebhoy Towers, Dalal Street, Mumbai 400 001 Scrip Code :


## Q22 MB0252 KPRMILL — verified

**Q:** How many manufacturing facilities does K.P.R. Mill (NSE: KPRMILL) report in its investor presentation dated 13 August 2026, and where are they?

as_of=2026-10-19 types=deck template=QA3 gold_found=None gold_in_top=False gold_rank=None
**Bank gold:** (none)

**Answer:** The investor presentation dated 13 August 2026 reports 12 hi-tech manufacturing facilities; their locations are not stated in the excerpt (only Karnataka is mentioned for the sugar/ethanol capacity).

**Quote:** K.P.R. Mill Limited is one of the leading vertically integrated apparel manufacturing Companies in India built on fabulous values with 12 hi-tech manufacturing facilities and over 31,000 employees.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** specific locations of the 12 manufacturing facilities

**Retrieved chunks:**
- [105679] deck 2026-08-13 p5 score=11.782 cov=3 phr=1 — About KPR... K.P.R. Mill Limited is one of the leading vertically integrated apparel manufacturing Companies in India built on fabulous values with 12 hi-tech manufacturi
- [54025] annual_report 2024-06-14 p36 score=9.9 cov=4 phr=1 — 23 Annual Report 2025-26 B. TECHNOLOGY ABSORPTION, RESEARCH AND DEVELOPMENT (R&D): 1. Specific areas in which R&D carried out by the Company: Further Improvement in Quali
- [61862] annual_report 2025-07-01 p14 score=9.68 cov=5 phr=0 — PROFILE OF DIRECTORS SEEKING APPOINTMENT/REAPPOINTMENT Pursuant to Regulation 36 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015 and Secre
- [105681] deck 2026-08-13 p7 score=9.543 cov=3 phr=0 — The Board of Directors has approved following Expansion cum Modernization Projects at its meeting on 10-08-2026 S.No. | Particulars Cost of the Expected time of Project c
- [102549] deck 2025-11-07 p5 score=9.025 cov=3 phr=1 — About KPR... K.P.R. Mill Limited is one of the leading vertically integrated apparel manufacturing Companies in India built on fabulous values with 12 hi-tech manufacturi
- [104447] deck 2026-05-14 p5 score=8.875 cov=3 phr=1 — K.P.R. Mill Limited 4 6 State of the Art Spinning Mills with a capacity to produce 1,00,000 MT of yarn and 10,500 MT of Vortex Viscose yarn 4 State of the Art Garment fac
- [103788] deck 2026-02-11 p5 score=8.86 cov=3 phr=1 — About KPR... K.P.R. Mill Limited is one of the leading vertically integrated apparel manufacturing Companies in India built on fabulous values with 12 hi-tech manufacturi
- [61909] annual_report 2025-07-01 p41 score=8.8 cov=3 phr=1 — ANNEXURETOTHE BOARD’S REPORT FOREIGN EXCHANGE EARNINGS AND OUTGO B. TECHNOLOGY ABSORPTION, RESEARCH AND DEVELOPMENT (R&D): 1. Specific areas in which R&D carried out by t
- [61931] annual_report 2025-07-01 p55 score=8.725 cov=3 phr=1 — FAMILIARISATION PROGRAMME Familiarisation Programme on the Company and its operations was conducted apprising the Independent Directors of the following: 1. Roles, Rights
- [107704] results_notes 2026-08-10 p7 score=8.65 cov=2 phr=0 — [SEGMENT REVENUE a) Textile 150,032| 144,499 148371 543,532 b) Sugar 41,983 34,802 26,028 1,17,288 ) Others 2,201 1,912] 2,236 8,354 Total 1,94,216 1,81,213 1,76,635| 6,6

**Quote context:**

> About KPR... K.P.R. Mill Limited is one of the leading vertically integrated apparel manufacturing Companies in India built on fabulous values with 12 hi-tech manufacturing facilities and over 31,000 employees. Exporting to leading international brands K.P.R. Mill Limited Textile & Apparel 6 State of the Art Spinning Mills with a capacity to produce 1,00,000 MT of yarn and 10,500 MT of Vortex Viscose yarn 4 State of the Art Garment facilities with a Capacity to produce 204 Million knitted Garments 2 State of the Art fabric processing facilities with a Capacity to process 25,000 MT of fabrics State of the Art fabric printing facility with a Ca


## Q23 MB0386 SUZLON — rejected_quote

**Q:** Suzlon's latest results: what did the auditor's declaration say?

as_of=2026-10-31 types=results_notes,announcement template=A04 gold_found=False gold_in_top=False gold_rank=None
**Bank gold:** SUZLON First quarter (2026-06-30): audit_opinion = 'Not applicable', Un-Audited, filed 2026-07-28T15:11:06

**Answer:** The auditor's report included an emphasis of matter drawing attention to Note 18, which describes the restatement of comparative financial information for the year ended 31 March 2025 due to the NCLT-approved Scheme of Arrangement, and stated that its opinion was not modified in respect of this matter.

**Quote:** Emphasis of Matter 4. We draw attention to Note 18 to the accompanying consolidated financial statements, which describes the restatement of the comparative financial information for the year ended 31 March 2025, to give effect to the Scheme of Arrangement approved by National Company Law Tribunal vide its order dated 29 April 2026. Our opinion is not modified in respect of this matter.

**Verify:** status=rejected_quote quote_ok=False kind=not_found number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [26593] annual_report 2026-08-21 p150 score=10.25 cov=5 phr=0 — The Company Secretary of the Company acts as the secretary to the Audit Committee. iv. The Chairman of the Audit Committee attended the Thirtieth Annual General Meetin
- [26572] annual_report 2026-08-21 p118 score=9.95 cov=5 phr=0 — During the year under review and up to the date of this Report, the Securities Issue Committee of the Board has allotted equity shares of ₹2 each pursuant to exercise of
- [26746] annual_report 2026-08-21 p368 score=9.1 cov=4 phr=0 — • Conclude on the appropriateness of Board of Directors’ use of the going concern basis of accounting and, based on the audit evidence obtained, whether a material uncert
- [26741] annual_report 2026-08-21 p362 score=8.5 cov=4 phr=0 — CONSOLIDATED FINANCIAL STATEMENTS Independent Auditor’s Report To the Members of Suzlon Energy Limited Report on the Audit of the Consolidated Financial Statements Opinio
- [26600] annual_report 2026-08-21 p161 score=8.312 cov=4 phr=0 — (VC / OAVM) Wednesday, September 27, 2023, at 11.00 a.m. • To approve conversion of loans into Equity shares. FY24 Twenty Ninth AGM Tuesday, September 10, 2024, at 11.00 
- [50852] deck 2026-06-12 p61 score=7.5 cov=3 phr=0 — Vote of Thanks © SUZLON Disclaimer This presentation and the accompanying slides (the “Presentation”), has been prepared by Suzlon Energy Limited (the “Company”), solely 
- [31831] concall 2024-11-01 p4 score=5.2 cov=2 phr=0 — Himanshu Mody: Thank you, JPC sir, and good evening, ladies and gentlemen. I would be using Slide #17 to #25 of our investor presentation, which has now been uploaded on 
- [36444] concall 2025-11-11 p13 score=5.0 cov=2 phr=0 — We take that -- plus also in the public sector, the time taken from the time it becomes material reaches to their whole process of completing and taking it, if normally o
- [35670] concall 2025-08-20 p6 score=4.85 cov=2 phr=0 — Sumit Kishore: My first question is in relation to the Q1 P&L. The Q1 interest cost seems to be up quarter-on- quarter, even though the company is net cash. Is there any 
- [30548] concall 2024-07-30 p3 score=4.025 cov=2 phr=0 — JP Chalasani: Welcome, everyone to the earnings call. I hope you had an opportunity to review our results and investor presentation. We will now share with you an overvie


## Q24 MB0625 SUZLON — verified

**Q:** How much did Suzlon pay its statutory auditor last year?

as_of=2026-10-27 types=annual_report,results_notes template=A20 gold_found=None gold_in_top=False gold_rank=None
**Bank gold:** (none)

**Answer:** Suzlon and its subsidiaries paid ₹1.48 Crore in total fees to statutory auditor Walker Chandiok & Co LLP on a consolidated basis during FY26.

**Quote:** Total fees for all the services paid by the Company and its subsidiaries, on consolidated basis to Walker Chandiok & Co LLP, the statutory auditors, is ₹1.48 Crore.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [26573] annual_report 2026-08-21 p120 score=10.15 cov=3 phr=1 — M/s. Walker Chandiok & Co LLP, Chartered Accountants (Firm Registration No.001076N/N500013), were appointed as the Statutory Auditors of the Company to hold office from 
- [26593] annual_report 2026-08-21 p150 score=9.925 cov=3 phr=1 — The Company Secretary of the Company acts as the secretary to the Audit Committee. iv. The Chairman of the Audit Committee attended the Thirtieth Annual General Meetin
- [26572] annual_report 2026-08-21 p118 score=9.85 cov=3 phr=1 — During the year under review and up to the date of this Report, the Securities Issue Committee of the Board has allotted equity shares of ₹2 each pursuant to exercise of
- [26500] annual_report 2026-08-21 p4 score=8.28 cov=2 phr=1 — THAT WORK GOOD (What We Create): Beneficial for customers, communities, economies, and the environment, while infusing positive human energy into every project. ENERGIES 
- [26601] annual_report 2026-08-21 p163 score=8.2 cov=3 phr=1 — During FY26, the Company has entered into various transactions with related parties as defined under Section 2(76) of the Act in accordance with the provisions of the Ac
- [37664] concall 2026-02-12 p17 score=6.4 cov=2 phr=0 — I would like to understand like what would be on the face of the P&L, like how much effective tax rate would be shown in the P&L? I would like to understand that sir. Rah
- [39693] concall 2026-08-04 p9 score=4.6 cov=1 phr=0 — Sweta Jain: And the revenues, if I understood correctly the previous answers, we will start actually witnessing something materially next year onwards from the Suzlon 2.0
- [50819] deck 2026-06-12 p17 score=4.3 cov=1 phr=0 — Wind-specific industrial-policy levers have converged across India, EU, and US Tailwind for players with deep domestic supply chains – to build durable competitive advant
- [50833] deck 2026-06-12 p37 score=3.85 cov=1 phr=0 — © SUZLON RE DevCo Long-term visibility and a de-risked development pipeline Turning India’s development bottleneck into opportunity Structural constraints Suzlon’s Soluti
- [50852] deck 2026-06-12 p61 score=3.625 cov=1 phr=0 — Vote of Thanks © SUZLON Disclaimer This presentation and the accompanying slides (the “Presentation”), has been prepared by Suzlon Energy Limited (the “Company”), solely 

**Quote context:**

> ervices paid by the listed entity and its subsidiaries, on consolidated basis to the statutory auditor and all entities in the network firm / network entity of which the statutory auditor is a part, is given below - Total fees for all the services paid by the Company and its subsidiaries, on consolidated basis to Walker Chandiok & Co LLP, the statutory auditors, is ₹1.48 Crore. 6.10 Disclosures in relation to the Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal), Act, 2013 - The details are as under: Particulars No. of cases No. of complaints filed during FY26 2 No. of complaints disposed of during FY26 2 No. of


## Q25 MB0341 RVNL — verified

**Q:** RVNL's BharatNet work: what execution timeline did management give, and what happens after the build phase?

as_of=2026-10-31 types=concall,results_notes template=A01 gold_found=True gold_in_top=True gold_rank=3
**Bank gold:** “For BharatNet, initially, there were some challenges. We faced some problems in execution also. But now the situation is quite better. It has improved. Work is going on in full swing in UP West and UP East also.”

**Answer:** Management gave a three-year timeline for implementing the BharatNet infrastructure at site.

**Quote:** BharatNet project is in two parts. First is the implementation of the infrastructure at site. The timeline is three years.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** What happens after the build phase is not stated in this excerpt.

**Retrieved chunks:**
- [82203] annual_report 2026-08-21 p85 score=10.7 cov=5 phr=0 — ANNUAL REPORT 2025-26 S. No. Agency / Client Name of Project Plan Head 77. East Coast Railway 3rd& 4th line between Jarapada & Talcher Road and Construction of New line b
- [81191] annual_report 2026-08-01 p44 score=10.25 cov=5 phr=0 — ANNUAL REPORT 2025-26 RAIL VIKAS NIGAM LIMITED S. No. Agency / Client Name of Project Plan Head 77. East Coast Railway 3rd& 4th line between Jarapada & Talcher Road and C
- [96254] concall 2026-08-18 p9 score=10.0 cov=4 phr=0 **GOLD** — For BharatNet, initially, there were some challenges. We faced some problems in execution also. But now the situation is quite better. It has improved. Work is going on i
- [81205] annual_report 2026-08-01 p48 score=9.913 cov=5 phr=0 — 3.9.3 Kolkata Metro Projects: 3.9.3.1 Indian Railways transferred the works of four major projects for extension of Kolkata Metro to RVNL in March 2010 viz. Joka-BBD Bag 
- [69560] annual_report 2025-08-22 p97 score=8.6 cov=5 phr=0 — 3.9.4 Kolkata Metro Projects: 3.9.4.1 Indian Railways transferred the works of four major projects for extension of Kolkata Metro to RVNL in March 2010 viz. • Joka-BBD Ba
- [67647] annual_report 2025-08-07 p97 score=8.525 cov=5 phr=0 — 3.9.4 Kolkata Metro Projects: 3.9.4.1 Indian Railways transferred the works of four major projects for extension of Kolkata Metro to RVNL in March 2010 viz. • Joka-BBD Ba
- [94064] concall 2026-02-09 p3 score=8.129 cov=3 phr=0 — Saleem Ahmad: Namaskar. Good afternoon, all of you. A very warm welcome to all of you in today's investor call for third quarter of Rail Vikas Nigam Limited. My name is S
- [94070] concall 2026-02-09 p6 score=7.95 cov=3 phr=0 — Ashish Shah: Okay. And how about the other order book of bidding-based, INR47,000 crores? Saleem Ahmad: Yes. Even that work is going on. Ashish Shah: So it's entirely und
- [94071] concall 2026-02-09 p6 score=7.8 cov=3 phr=0 — Ashish Shah: Right. And what's the kind of execution that one can hope from this order book? Because it's a complex set of mix, where Vande Bharat would be having a longe
- [96252] concall 2026-08-18 p5 score=7.725 cov=3 phr=0 — Further, the company expects its top line to grow by around 15%, while the bottom line is projected to increase by approximately 15-20%, reflecting continued business mom

**Quote context:**

>  Kumar Okay. And can you also provide details on how much CapEx we have incurred till now, our revenue recognition, and expected completion timeline for BharatNet, Vande Bharat Sleeper train, and others? Amit Tandon BharatNet project is in two parts. First is the implementation of the infrastructure at site. The timeline is three years. There are certain issues at the ground line, which are being sorted out, and this duct and fiber is being provided. This will take another six to eight months. It will be extended. The second part is for maintenance for the next 10 years. So, whatever is being implemented there and handed over, that is automat

**Gold locator:** chunk 96254 concall 2026-08-18 overlap=1.0 in_top=True


## Q26 MB0352 SUZLON — verified

**Q:** Suzlon says 4.5 GW of manufacturing capacity is fully operational. When does that capacity convert into revenue, and what gates it?

as_of=2026-10-31 types=concall,results_notes template=A02 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** “4.5 gigawatt manufacturing capacity fully operational expanding footprint with 3 AI-enabled smart factories to drive efficiency and scale.”

**Answer:** The excerpts do not state when the 4.5 GW converts into revenue; commissioning is gated by transmission and land acquisition challenges.

**Quote:** The industry commissioned around 4.2 gigawatts in FY '25. Though 28% growth is there, it falls short of expectations due to transmission and land acquisition challenges.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** when the 4.5 GW manufacturing capacity converts into revenue

**Retrieved chunks:**
- [39680] concall 2026-08-04 p3 score=29.4 cov=8 phr=5 — Ajay Kapur: Thank you. Good evening, everyone, and thank you for joining Suzlon's Q1 FY27 Earnings Call. FY27 has started strongly for Suzlon and the Indian wind industry
- [39049] concall 2026-06-02 p4 score=28.5 cov=9 phr=4 **GOLD** — Ajay Kapur: Thank you, J.P.C. Hello, everyone. It is great connecting with you today. Many of you may know me from my earlier associations, but for the benefit of the lar
- [37646] concall 2026-02-12 p3 score=23.025 cov=6 phr=4 — Rahul Jain: Thank you, J.P. Chalasani sir. Good afternoon, ladies and gentlemen. Many of you may know me from previous and earlier associations, but for the benefit of th
- [36428] concall 2025-11-11 p3 score=19.2 cov=7 phr=2 — Moderator: Ladies and gentlemen, good day, and welcome to the Suzlon Energy Limited Q2 FY '26 Earnings Conference Call. During this call, the company management may make 
- [34712] concall 2025-06-05 p3 score=18.613 cov=7 phr=2 — Moderator: Ladies and gentlemen, good day and welcome to the Suzlon Energy Limited Q4 FY '25 Earnings Conference Call. During this call, the company management may make c
- [26550] annual_report 2026-08-21 p72 score=12.5 cov=4 phr=1 — Additionally, geopolitical disruptions continue to impact global logistics and supply chains, potentially affecting timelines, and costs. To mitigate these risks, Suzlon 
- [26522] annual_report 2026-08-21 p23 score=9.1 cov=3 phr=1 — BUSINESS PERFORMANCE FY26 was a defining year for Suzlon, as we wove good energies into our daily choices, from how we innovate and manufacture to how we create value for
- [26532] annual_report 2026-08-21 p40 score=7.65 cov=2 phr=1 — SUZLON AT A GLANCE Manufacturing Locations in India Wind Turbines Good Energy People Manufacturing Capacity Cumulative Market Share in India Installed Wind Energy Assets 
- [26525] annual_report 2026-08-21 p25 score=7.425 cov=2 phr=1 — INDIA’S RENEWABLE ENERGY Sources: Ministry of New and Renewable Energy; India Brand Equity Foundation; Council on Energy, Environment and Water Data as of July 31, 2026 2
- [26539] annual_report 2026-08-21 p53 score=7.38 cov=2 phr=1 — SUPPLY CHAIN AND MANUFACTURING Suzlon is a vertically integrated renewable energy manufacturer, with in-house manufacturing capabilities for major wind turbine components

**Quote context:**

>  to execution Suzlon has set a new performance benchmark by delivering a record-breaking 1,550 megawatts this year, more than double the megawatts delivered last year. Suzlon Energy Limited May 29, 2025 Page 3 of 19 The industry commissioned around 4.2 gigawatts in FY '25. Though 28% growth is there, it falls short of expectations due to transmission and land acquisition challenges. However, with over 2.5 gigawatt commission in March last year and April this year combined, signalling a positive shift in execution pace. At Suzlon, we commissioned 336 megawatts in FY '25, with an additional 370-megawatt directed WTGs currently in the pre-commis

**Gold locator:** chunk 39049 concall 2026-06-02 overlap=1.0 in_top=True


## Q27 MB0343 BEL — verified

**Q:** BEL ka QRSAM order kis approval ka wait kar raha hai, aur kab tak? (Hinglish)

as_of=2026-10-31 types=concall,announcement template=A01 gold_found=True gold_in_top=True gold_rank=1
**Bank gold:** “we are just waiting for the CCS approval”

**Answer:** BEL is waiting for CCS approval for the QRSAM order, and expects it by maximum September.

**Quote:** it may go to Q1/Q2, maximum by September we will get and I am still sticking to that. Just CCS only is waiting for all of us

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [95641] concall 2026-07-28 p4 score=15.2 cov=5 phr=1 **GOLD** — Just wanted to get a little bit more understanding on that and also QRSAM order which seems to have been delayed? That is my first question, sir. Manoj Jain: Yes. So, let
- [95658] concall 2026-07-28 p11 score=11.825 cov=5 phr=0 — Dipen Vakil: Got it, sir. Sir, my second question is that, so for the order pipeline that you have suggested for INR55,000 crores, if we consider excluding QRSAM, which w
- [95643] concall 2026-07-28 p5 score=11.78 cov=5 phr=0 — Mohit Pandey: Yes, evening, sir. Am I audible? Manoj Jain: Yes, Mohit. Mohit Pandey: Yes, okay. Yes, sir, first question is again on orders. So, explanation on the Y-o-Y 
- [92951] concall 2025-11-04 p4 score=10.0 cov=3 phr=1 — Manoj Jain: Certainly. As we told last quarter also that we were expecting a good number of emergency procurement orders. So finally, we have received already some 11 ord
- [91300] concall 2025-05-29 p4 score=9.75 cov=3 phr=1 — And secondly, any update you would like to provide on the large pipeline orders such as QRSAM and corvette-linked orders? That would be very helpful, sir. Manoj Jain: Yes
- [81673] annual_report 2026-08-05 p7 score=5.9 cov=2 phr=0 — 4 The Board recommends the ordinary resolution set out at the Item No.7 of the Notice of AGM for approval by the Members of the Company. In respect of item No.8: The Gove
- [106738] announcement 2026-08-05 p34 score=5.63 cov=2 phr=0 — SL. No Initiative undertaken Details of the initiative (Web-link, if any, may be provided along-with summary) Outcome of the initiative 3. Water Conservation 1) Installe
- [106980] announcement 2026-08-13 p9 score=4.15 cov=1 phr=0 — R%3FF (HM^ WTSFI) Director (Human Resources) 2 T5TFT Designation R -^ Rb Appointment 3 TT =hKul Reason for Change R^ ,Rr> # dl'O 'id Date of Appointment 4 13/08/2026 R^ R
- [106981] announcement 2026-08-13 p9 score=4.075 cov=1 phr=0 — 1888162),R%?FT (RHUM) # R^ ,Rb - Appointment of Shri Anoop Kumar Rai (DIN: 11888162), Director (Marketing): R =KUI sbTT. SI. Particulars No R%3T4> TFTF XWT Name and DIN o
- [106966] announcement 2026-08-13 p3 score=4.0 cov=1 phr=0 — VUR'M 'O % W|l He does not have relationship with any other Directors of the Company and is not debarred from holding the office of Director by virtue of any SEBI order o

**Quote context:**

>  to worry. We are definitely going to meet the guidance given about the order inflow for this year. And QRSAM, we told we were highly optimistic to get it by March, but procedural delays we knew, that is why we told it may go to Q1/Q2, maximum by September we will get and I am still sticking to that. Just CCS only is waiting for all of us and hopefully, when CCS meets, I think they will clear QRSAM. Our side all inputs, every activity is over from all of our side. So, we are just waiting for the CCS approval and that time we will get the good news about QRSAM.

**Gold locator:** chunk 95641 concall 2026-07-28 overlap=1.0 in_top=True


## Q28 MB0618 DIXON — verified

**Q:** What is Dixon's CEO paid, and how has that changed in three years?

as_of=2026-10-27 types=annual_report,results_notes template=A20 gold_found=None gold_in_top=False gold_rank=None
**Bank gold:** (none)

**Answer:** Mr. Atul B. Lall, Vice Chairman & Managing Director, was paid an annual remuneration of INR 703 Lakhs including a Commission of INR 295 lakhs during FY 2025-26, excluding perquisite value of stock options exercised. How this changed over three years is not stated.

**Quote:** During FY 2025-26, Mr. Lall was paid an annual remuneration of INR 703 Lakhs including a Commission of INR 295 lakhs, excluding perquisite value of stock options exercised during the year.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** three-year change in pay; a separate CEO title/role

**Retrieved chunks:**
- [84733] annual_report 2026-09-03 p64 score=10.0 cov=4 phr=0 — Information about the appointee: (1) Background details: Mr. Atul B. Lall holds a master’s degree in management studies from the Birla Institute of Technology and Science
- [85266] annual_report 2026-09-03 p497 score=7.95 cov=3 phr=0 — 55 SEGMENT REPORTING The Chief Operating Decision Maker (CODM) comprises of the Board of Directors, Managing Director and Vice chairman and Chief financial officer which
- [84922] annual_report 2026-09-03 p228 score=7.8 cov=3 phr=0 — 17 To 27 And Clauses (B) to (I) of Sub-Regulation 2 of Regulation 46 of SEBI Listing Regulations Your Company is in compliance with the requirements stipulated under Regu
- [85089] annual_report 2026-09-03 p382 score=7.725 cov=3 phr=0 — 48 SEGMENT REPORTING The Chief Operating Decision Maker (‘CODM’) comprises of the Board of Directors, Vice Chairman and Managing Director and Chief Financial Officer whi
- [84910] annual_report 2026-09-03 p217 score=7.68 cov=3 phr=0 — REMUNERATION TO EXECUTIVE DIRECTORS The appointment and remuneration of Executive Directors, namely the Executive Chairman and Vice Chairman and Managing Director are gov
- [95880] concall 2026-08-05 p8 score=5.99 cov=2 phr=0 — Aditya Bhartia: Sure, sir. Sir, my second question is on working capital, wherein it appears that this quarter, working capital has increased a bit from the cash flow sta
- [91826] concall 2025-07-28 p3 score=5.8 cov=2 phr=0 — Bhoomika Nair: Good Evening, Everyone, and a Warm Welcome to the Q1 FY’26 Earnings Call of Dixon Technologies. We have the management today being represented by Mr. Atul 
- [95874] concall 2026-08-05 p2 score=5.8 cov=2 phr=0 — MODERATOR: MR. TANAY SHAH – DAM CAPITAL ADVISORS LIMITED Dixon Technologies (India) Limited July 31, 2026 Page 2 of 20 Moderator: Ladies and gentlemen, good day, and welc
- [94853] concall 2026-05-15 p2 score=5.05 cov=2 phr=0 — MODERATOR: MR. TANAY SHAH – DAM CAPITAL ADVISORS LIMITED Dixon Technologies (India) Limited May 12, 2026 Page 2 of 20 Moderator: Ladies and gentlemen, good day, and welco
- [91101] concall 2025-05-24 p3 score=5.029 cov=2 phr=0 — Bhoomika Nair: Good evening, everyone, and a warm welcome to the Q4 FY'25 Earnings Call of Dixon Technologies (India) Limited. We have the management today being represen

**Quote context:**

> ment (LITD. 02) of the BIS. He has also authored the book, 'Gita and India Inc.' He was also conferred with the MAN OF ELECTRONICS award by CEAMA (a leading industry body association) in 2022. (2) Past remuneration: During FY 2025-26, Mr. Lall was paid an annual remuneration of INR 703 Lakhs including a Commission of INR 295 lakhs, excluding perquisite value of stock options exercised during the year. (3) Recognition or awards: He has served as a member of the Technical Evaluation Committee for Electronic Manufacturing Services under M-SIPS (Electronic Manufacturing Services-EMS) constituted by the MeitY and served as a representative of ELCI


## Q29 MB0324 HINDPETRO — not_stated

**Q:** HINDPETRO mou margin path call 2026-07-29

as_of=2026-10-19 types=concall template=QA10 gold_found=None gold_in_top=False gold_rank=None
**Bank gold:** (none)

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** No mention of a margin path call on 2026-07-29 or MoU margin path in the excerpts.

**Retrieved chunks:**
- [56143] annual_report 2024-07-27 p238 score=8.3 cov=3 phr=1 — B. FINANCIAL PERFORMANCE The Corporation reported a strong financial performance with a Standalone Profit After Tax (PAT) of ₹17,175 crore during FY 2025–26. HPCL contin
- [106598] announcement 2026-07-31 p61 score=8.25 cov=1 phr=0 — The technology has been validated at laboratory and pilot scale, while Basic Design Engineering Package (BDEP) has been completed and detailed engineering is underway for
- [106606] announcement 2026-07-31 p72 score=7.9 cov=2 phr=0 — HP OFM Organic friction modifier for engine oils Reduces friction-related energy losses and emissions Initiatives by Marketing SBUs-Marketing SBUs have taken several init
- [106608] announcement 2026-07-31 p72 score=6.9 cov=1 phr=0 — 50 KL of Rain water harvested during the year 27 Vermicomposting arrangement at MPSPL Hazarwadi Vermicompost arrangement has been made inside plant which will convert org
- [106626] announcement 2026-07-31 p92 score=6.825 cov=1 phr=0 — DN: cn=BIRENDRA DUTT RATURI c=IN o=PERSONAL Reason: I am the author of this document Location: Date: 2026-07-14 12:09+05:30 91 www.hindustanpetroleum.com | www.x.com/HPCL
- [106561] announcement 2026-07-31 p1 score=6.78 cov=1 phr=0 — RAKESH KUMAR SINGH Date: 2026.07.31 17:55:46 +05'30' Creating Sustainable Value Through Responsible Business Business Responsibility and Sustainability Report 2025-26 Gov
- [66594] annual_report 2025-07-28 p205 score=5.925 cov=2 phr=1 — B. FINANCIAL PERFORMANCE The Corporation reported a strong financial performance with a Standalone Profit After Tax (PAT) of ₹ 7,365 Crore during FY 2024-25. HPCL conti
- [56144] annual_report 2024-07-27 p239 score=5.66 cov=4 phr=0 — C. STRATEGY HPCL’s strategy takes a balanced and pragmatic approach to the evolving energy landscape. The Corporation continues to strengthen its core business in traditi
- [56132] annual_report 2024-07-27 p224 score=5.238 cov=3 phr=0 — In MMT OTC Exchange OTC Exchange Refinery Margin 1,600 26.04 Nil Nil 20.43% Nil 20.43% Inventory as on March 31, 2026: Raw Material (mainly Crude) 985 1.47 Nil Nil Nil Ni
- [56277] annual_report 2024-07-27 p359 score=5.1 cov=2 phr=0 — Notes to the Standalone Financial Statements for the year ended 31st March, 2026 356 71 Financial Ratios Ratio 31.03.2026 31.03.2025 Variance (%) Reason for Variance (a) 

**Corpus probe (not shown to the model):**
- cov=3 [56141] annual_report 2024-07-27 — in High Sulphur Fuel Oil 180 CST margins, which fell to US$ -5.5 per barrel (lower by US$ 7.3 per barrel quarter-on-quarter) as seasonal cooling demand in the Middle East subsided and regional supplies increased. Gasolin
- cov=3 [56149] annual_report 2024-07-27 — 17 Railway Consumer Depots (RCDs), and all Total Fluid Management (TFM) locations and Bitumen Contractor Operated Depots (CODs). Read more on page 77 Aviation HPCL’s Aviation business recorded ATF sales of 1.16 MMT in FY
- cov=3 [55959] annual_report 2024-07-27 — Delivering Strong Performance HPCL reported a record Profit After Tax of ₹17,175 crore. Revenue from Operations stood at ₹4,78,543 crore, while EBITDA reached ₹33,182 crore. The Corporation achieved its highest-ever sale


## Q30 MB0531 POLYCAB — rejected_contradiction

**Q:** Polycab ne Q1FY27 mein 3.2 billion capex kiya — annual plan se aage ya peeche? (Hinglish)

as_of=2026-10-07 types=concall,deck template=A14 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** None: 3.2 INR billion (Q1 FY27) — “Capital expenditure during the quarter amounted to INR 3.2 billion, reflecting our continued commitment to building capacity and strengthening future growth drivers.”

**Answer:** not stated

**Quote:** Capital expenditure during the quarter amounted to INR 3.2 billion, reflecting our continued commitment to building capacity and strengthening future growth drivers.

**Verify:** status=rejected_contradiction quote_ok=True kind=None number_ok=True missing_numbers=[]
**Model says missing:** Whether Q1FY27 capex of INR 3.2 billion was ahead of or behind the annual plan; no quarterly benchmark against the annual plan is provided.

**Retrieved chunks:**
- [20003] annual_report 2026-06-09 p69 score=10.7 cov=5 phr=0 — VALUE CREATION ACROSS OUR ECOSYSTEM Financial Performance In FY 2025–26, Polycab delivered another year of strong financial performance, reporting revenue of `288,838 mil
- [39303] concall 2026-07-20 p4 score=10.325 cov=3 phr=0 **GOLD** — Shashank Yagnick: Thank you, Niyant. For the quarter ended June 30, 2026, we delivered another strong set of results, underscoring the resilience of our business model an
- [38261] concall 2026-05-08 p5 score=9.78 cov=4 phr=0 — Shashank Yagnick: Thank you, Niyant. For the quarter ended March 31, 2026, we are pleased to report a strong performance with consolidated revenue growing 27% year-on-yea
- [29500] concall 2024-05-17 p7 score=9.3 cov=5 phr=0 — Fostering product-led growth, we've expanded our brand portfolio across multiple price tiers in wires, ensuring comprehensive market coverage. The initiative has worked e
- [34013] concall 2025-05-14 p4 score=9.129 cov=4 phr=0 — Chirayu Upadhyaya: Thank you, Gandharv. Let me now draw your attention to Slide 4 of the Earnings Presentation. Polycab India Limited May 07, 2025 For the quarter ended 3
- [19941] annual_report 2026-06-09 p12 score=8.65 cov=4 phr=0 — 38,154.8 MTCO2e Emissions avoided due to renewable energy 79 IPR registered in FY 2025-26 We ensure the prudent allocation and efficient deployment of our financial capit
- [32789] concall 2025-01-29 p7 score=8.582 cov=4 phr=0 — These forward-looking statements reflect the management's best judgment and analysis as of today. Actual results may differ materially from the current expectations based
- [20112] annual_report 2026-06-09 p167 score=8.5 cov=4 phr=0 — STATUTORY REPORTS | BUSINESS RESPONSIBILITY & SUSTAINABILITY REPORT Principle 2: Businesses should provide goods and services in a manner that is sustainable and safe Ess
- [20164] annual_report 2026-06-09 p213 score=8.38 cov=4 phr=0 — STATUTORY REPORTS | BOARD’S REPORT a strong emphasis on customer-centric innovation, ensures that W&C remains central to Polycab’s long- term value creation. Fast-Moving
- [19947] annual_report 2026-06-09 p17 score=8.312 cov=4 phr=0 — YEAR IN REVIEW Message from the Joint Managing Directors Against a backdrop of global uncertainty and a competitive domestic landscape, Polycab delivered a strong perform

**Gold locator:** chunk 39303 concall 2026-07-20 overlap=1.0 in_top=True


## Q31 MB0349 ULTRACEMCO — not_stated

**Q:** UltraTech says cement demand for the country grew about 4% in the quarter. What did management give as the reason the market is not stronger?

as_of=2026-10-31 types=concall,deck,results_notes template=A02 gold_found=True gold_in_top=False gold_rank=None
**Bank gold:** “We believe that this quarter, cement demand overall for the country would have grown around 4%. And in that backdrop, UltraTech has done close to 10% volume growth.”

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** The excerpts do not state that cement demand for the country grew about 4% in the quarter, nor management's reason for the market not being stronger.

**Retrieved chunks:**
- [91738] concall 2025-07-24 p3 score=12.7 cov=4 phr=1 — Atul Daga: Thank you so much, Reyo. Good morning, good afternoon, and good evening to everyone, and welcome to our Q1 FY '26 Earnings Call. Let me straight away dive into
- [89751] concall 2025-01-28 p3 score=12.5 cov=4 phr=1 — Atul Daga: Good afternoon and welcome all of you to our Earnings Call for Q3 FY25. First and foremost, wishing you all a very successful and a Happy 2025. We often talk a
- [93774] concall 2026-01-30 p4 score=12.125 cov=5 phr=0 — With thousands of kilometers under construction or planned across all regions, this is going to be huge. Elevated metro requires 11,000 metric tons per kilometer. Undergr
- [90520] concall 2025-03-04 p4 score=11.982 cov=4 phr=1 — The IHB in the rural markets, retail market depends on the contractor who deploys masons and electricians. UltraTech has existing relationships with the contractors and c
- [80682] annual_report 2026-07-24 p124 score=11.78 cov=4 phr=1 — I II III IV STATUTORY REPORTS VI VII Dankuni and Surat, seven high-speed rail corridors and twenty new National Waterways. Pursuant to the Union Budget 2025-26 announceme
- [95489] concall 2026-07-23 p4 score=11.26 cov=4 phr=0 — upwards. The discussion will not be complete if we don't talk about prices. Cement prices have been constructive during the quarter in the report. Our all India exit pric
- [80585] annual_report 2026-07-24 p51 score=10.85 cov=4 phr=1 — STRATEGIC REVIEW IV V VI VII Expansion of the wires and cables market The Indian wires and cables market, valued at USD 9.32 billion in 2024, is set for substantial growt
- [80552] annual_report 2026-07-24 p29 score=10.3 cov=4 phr=0 — CHAIRMAN’S MESSAGE Dear Shareholders, In a global landscape defined by volatility, geopolitical tension, and accelerating technological change, FY 2025‑26 has been a mile
- [81678] annual_report 2026-08-17 p1 score=9.7 cov=4 phr=0 — DHIRAJ KAPOOR Date: 2026.08.17 17:33:08 +05'30' UltraTech Cement Limited Chairman’s Speech Twenty-Sixth Annual General Meeting Monday, 17th August, 2026 – 3.00 pm through
- [106414] announcement 2026-07-24 p3 score=8.7 cov=3 phr=0 — In April 2026, an additional 8.7 MTPA was commissioned. As a result, UltraTech’s total domestic grey cement manufacturing capacity has crossed the 200 MTPA milestone, sta

**Gold locator:** chunk 90704 concall 2025-05-02 overlap=1.0 in_top=False

**Corpus probe (not shown to the model):**
- cov=4 [86873] concall 2024-05-06 — Atul Daga: Thank you. Good evening, everybody. One more quarter and one more year has gone by and at UltraTech, we have not got tired up growing. We have not yet exhausted all our resources to keep doing that up. This ye
- cov=4 [90519] concall 2025-03-04 — Atul Daga: Thank you so much. Good afternoon, everybody, and welcome to this call. I guess you are all wired-up today, but we are here to unwind you. Let me first talk about Grey Cement because that is our core and a ver
- cov=4 [88644] concall 2024-10-23 — Atul Daga: Thank you. Good evening, everybody, and welcome to this Earnings Call today. This quarter, I believe, has turned out as expected. Pre-election slowdown followed by a slowdown in April, June, with elections and
- cov=4 [87768] concall 2024-07-23 — Atul Daga: Thank you so much. Good afternoon, good evening, and welcome to everybody on this call for the Earnings of UltraTech Cement for Q1 FY '25. Let me begin by talking about -- a bit about demand and how we perceiv


## Q32 MB0530 KEI — rejected_contradiction

**Q:** KEI's Sanand phase 1 was late by about six months and commissioned in December 2025. Did the company meet its own revised date?

as_of=2026-10-07 types=concall,results_notes template=A14 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** “You are aware that our Sanand plant was commissioning of first phase was delayed by around 6 months. So we commissioned the first phase in the December '25.”

**Answer:** not stated

**Quote:** You are aware that our Sanand plant was commissioning of first phase was delayed by around 6 months. So we commissioned the first phase in the December '25.

**Verify:** status=rejected_contradiction quote_ok=True kind=None number_ok=True missing_numbers=[]
**Model says missing:** whether the company met its own revised date; no revised target date is stated

**Retrieved chunks:**
- [85295] annual_report 2026-09-05 p17 score=14.5 cov=6 phr=1 — used in utilities, renewable energy, oil and gas and infrastructure projects. The United States market had slowed as tariff uncertainty affected customer decisions. With 
- [94774] concall 2026-05-12 p3 score=10.725 cov=4 phr=0 **GOLD** — Anil Gupta: Okay. Good afternoon, friends. I'm Anil Gupta, CMD, KEI Industries Limited. I will give brief about the financial results of this quarter as well as the full 
- [85379] annual_report 2026-09-05 p95 score=10.25 cov=5 phr=0 — BIODIVERSITY AND ECOSYSTEMS Healthy ecosystems support resilient communities, reliable water systems and long-term economic activity. None of our reported plants or offic
- [96041] concall 2026-08-10 p6 score=9.9 cov=2 phr=1 — Praveen Sahay: Thank you for the Opportunity. Just further clarification on the margin side because in the P&L, we can see there is a change in the inventory, which is on
- [85561] annual_report 2026-09-05 p261 score=9.869 cov=5 phr=0 — 1 Year 1-2 Years 2-3 Years More than 3 Years Cable Plant at Sanand, Ahmedabad - Phase-II * 9,556.63 - - - 9,556.63 * The first phase of commercial production of greenfiel
- [85635] annual_report 2026-09-05 p354 score=9.853 cov=5 phr=0 — 3 Years Cable Plant at Sanand, Ahmedabad - Phase-II * 9,556.63 - - - 9,556.63 * The first phase of commercial production of greenfield cable plant commenced during the cu
- [96044] concall 2026-08-10 p7 score=8.7 cov=3 phr=0 — Am I right? Rajeev Gupta: Yes, sir. Raman KV: So yes, sir, I just want to understand in Sanand what kind of products are we catering to? And the Phase 2 in which we will 
- [96054] concall 2026-08-10 p11 score=8.513 cov=3 phr=0 — Achal Lohade: Got it. Sir, second question I had was with respect to Sanand plant. Given INR2,000 crores of capex and the EHV and the non-EHV mix, how do we look at the a
- [85320] annual_report 2026-09-05 p42 score=8.5 cov=4 phr=0 — DISCUSSING THE FINANCIAL PERFORMANCE FOR THE YEAR We delivered strong and broad-based financial performance during FY 2025-26. Net sales reached ` 11,748 crore, marking a
- [103572] deck 2026-02-07 p11 score=8.2 cov=4 phr=0 — Strategically Located Manufacturing Facilities & Strong R&D Capabilities Plant Location Start Date Capacity (As of 31st Dec, 25) Bhiwadi 1996 • Cable – 62,200 Kms • House

**Gold locator:** chunk 94774 concall 2026-05-12 overlap=1.0 in_top=True


## Q33 MB0544 BEL — verified

**Q:** BEL is waiting for CCS approval on QRSAM. Is that order already in the order book, and what happens to cover when it lands?

as_of=2026-10-07 types=concall,announcement template=A15 gold_found=True gold_in_top=True gold_rank=1
**Bank gold:** “we are just waiting for the CCS approval”

**Answer:** QRSAM is not yet in the order book; it is awaiting CCS approval and is part of the INR55,000 crore pipeline, of which roughly INR30,000 crores is QRSAM. What happens to cover when it lands is not stated.

**Quote:** total INR55,000 crores, out of that INR30,000 crores roughly will be QRSAM

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** what happens to cover when it lands

**Retrieved chunks:**
- [95641] concall 2026-07-28 p4 score=19.0 cov=6 phr=2 **GOLD** — Just wanted to get a little bit more understanding on that and also QRSAM order which seems to have been delayed? That is my first question, sir. Manoj Jain: Yes. So, let
- [95658] concall 2026-07-28 p11 score=15.85 cov=6 phr=1 — Dipen Vakil: Got it, sir. Sir, my second question is that, so for the order pipeline that you have suggested for INR55,000 crores, if we consider excluding QRSAM, which w
- [92951] concall 2025-11-04 p4 score=15.4 cov=5 phr=2 — Manoj Jain: Certainly. As we told last quarter also that we were expecting a good number of emergency procurement orders. So finally, we have received already some 11 ord
- [88018] concall 2024-08-01 p12 score=14.7 cov=7 phr=1 — o o S//*dCf B/-/ARATEl£CT/?ON/CS OUA ' JTY. technology, innovation Bharat Electronics Limited July 29, 2024 Moderator: Amit Mahawar: Management: Amit Mahawar: Management:
- [88066] concall 2024-08-01 p12 score=14.69 cov=7 phr=1 — o o S//*dCf B/-/ARATEl£CT/?ON/CS OUA ' JTY. technology, innovation Bharat Electronics Limited July 29, 2024 Moderator: Amit Mahawar: Management: Amit Mahawar: Management:
- [81673] annual_report 2026-08-05 p7 score=5.9 cov=2 phr=0 — 4 The Board recommends the ordinary resolution set out at the Item No.7 of the Notice of AGM for approval by the Members of the Company. In respect of item No.8: The Gove
- [106738] announcement 2026-08-05 p34 score=5.6 cov=2 phr=0 — SL. No Initiative undertaken Details of the initiative (Web-link, if any, may be provided along-with summary) Outcome of the initiative 3. Water Conservation 1) Installe
- [106980] announcement 2026-08-13 p9 score=4.15 cov=1 phr=0 — R%3FF (HM^ WTSFI) Director (Human Resources) 2 T5TFT Designation R -^ Rb Appointment 3 TT =hKul Reason for Change R^ ,Rr> # dl'O 'id Date of Appointment 4 13/08/2026 R^ R
- [106981] announcement 2026-08-13 p9 score=4.075 cov=1 phr=0 — 1888162),R%?FT (RHUM) # R^ ,Rb - Appointment of Shri Anoop Kumar Rai (DIN: 11888162), Director (Marketing): R =KUI sbTT. SI. Particulars No R%3T4> TFTF XWT Name and DIN o
- [106741] announcement 2026-08-05 p40 score=3.979 cov=1 phr=0 — users involved in installation and commissioning of the products and systems, usage of the systems during its active life and those involved in maintaining the system dur

**Quote context:**

> t would be the quantum of base orders that you are expecting in this year? BHAMreucr/tON/cs QUALITY, TECHNOLOGY INNOVATION Bharat Electronics Limited July 27, 2026 Page 11 of 20 Manoj Jain: Put together, I told now, total INR55,000 crores, out of that INR30,000 crores roughly will be QRSAM, then around INR15,000 crores plus is these platform orders, and remaining will be the other base orders of smaller quantities, support, services, or AMCs, all this put together remaining. Dipen Vakil: Got it, sir. Got it. That's all from my side. Thank you so much and all the best. Moderator: Thank you. The next question comes from the line of Atul Tiwari 

**Gold locator:** chunk 95641 concall 2026-07-28 overlap=1.0 in_top=True


## Q34 MB0332 DIXON — verified

**Q:** Dixon's Vivo joint venture: from which quarter does management expect it to start showing up in revenue?

as_of=2026-10-31 types=concall,deck template=A01 gold_found=True gold_in_top=True gold_rank=5
**Bank gold:** “We expect the JV to commence operations and start reflecting in our revenues from Q3 of the current fiscal.”

**Answer:** Management expects the Vivo joint venture to commence operations and start reflecting in revenues from Q3 of the current fiscal.

**Quote:** We expect the JV to commence operations and start reflecting in our revenues from Q3 of the current fiscal.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [91827] concall 2025-07-28 p3 score=16.9 cov=7 phr=1 — Atul Lall: Thanks, Bhoomika. Good evening, ladies and gentlemen. This is Atul Lall, and we also have on the call today our CFO – Saurabh Gupta. Thank you very much for jo
- [95877] concall 2026-08-05 p6 score=15.55 cov=6 phr=1 — Joint venture with Signify continues to deliver robust revenue growth, backed by strong growth in indoor lighting portfolio, led by bats and down liters. While the lighti
- [95876] concall 2026-08-05 p5 score=13.98 cov=5 phr=1 — We expect the operations to commence from Q3 of this fiscal. We are expanding the capacities of camera module in subsidiary Q Tech, which is an ECMS beneficiary for smart
- [95901] concall 2026-08-05 p17 score=12.3 cov=4 phr=1 — Ravi Swaminathan: Hi, sir. Thanks for taking my question. I have one question regarding servers global market. We have big players like Foxconn, etcetera, who have almost
- [95875] concall 2026-08-05 p3 score=12.182 cov=5 phr=0 **GOLD** — Atul Lall: I would like to warmly welcome all our stakeholders to discuss our Q1 performance for '26- '27. Key highlights for the quarter are as below. Revenues for the q
- [84964] annual_report 2026-09-03 p299 score=10.85 cov=4 phr=1 — INDEPENDENT AUDITOR’S REPORT KEY AUDIT MATTER Key audit matters are those matters that, in our professional judgment, were of most significance in our audit of the standa
- [84804] annual_report 2026-09-03 p140 score=10.49 cov=4 phr=1 — INDUSTRY OVERVIEW AND STATE OF COMPANY’S AFFAIRS The global electronics market is growing at 5% CAGR and is expected to reach 6Tn by 2030 whereas the Indian electronics m
- [85125] annual_report 2026-09-03 p412 score=10.453 cov=4 phr=1 — OTHER MATTER We did not audit the financial statements and other financial information of two subsidiaries whose financial statements reflect total assets of Rs. 2,17,116
- [85243] annual_report 2026-09-03 p474 score=10.431 cov=4 phr=1 — NOTES FORMING PART OF THE CONSOLIDATED FINANCIAL STATEMENTS (Contd.) Dixon Technologies (India) Limited 465 Integrated Annual Report 2025-26 Particulars As at 31st March,
- [84932] annual_report 2026-09-03 p240 score=9.7 cov=3 phr=1 — V. HOLDING, SUBSIDIARY AND ASSOCIATE COMPANIES (INCLUDING JOINT VENTURES) Corporate Overview Statutory Reports Financial Statements 230 100% Subsidiary 24. (i) Whether C

**Quote context:**

> r- on-quarter growth as consumer demand strengthens and we have a strong order book. We received the PN3 approval for our JV with Vivo in July '26, and we are now working towards the consummation of the transaction. We expect the JV to commence operations and start reflecting in our revenues from Q3 of the current fiscal. Construction of our 1 million Dixon Technologies (India) Limited July 31, 2026 Page 4 of 20 square feet facility in Noida with higher capacities for our anchor customer is almost completed.

**Gold locator:** chunk 95875 concall 2026-08-05 overlap=1.0 in_top=True


## Q35 MB0348 KEI — verified

**Q:** KEI's operating margin improved in FY26. By how much, and what does that say about the pricing environment for cables?

as_of=2026-10-31 types=concall,results_notes template=A02 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** “During FY25-'26, operating margin has improved to 10.46% against 10.18%.”

**Answer:** During FY25-26, KEI's operating margin improved to 10.46% against 10.18%.

**Quote:** During FY25-'26, operating margin has improved to 10.46% against 10.18%.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** what the margin improvement says about the pricing environment for cables

**Retrieved chunks:**
- [85294] annual_report 2026-09-05 p15 score=16.1 cov=7 phr=1 — ANIL GUPTA Chairman-cum-Managing Director The wires and cables segment grew by 22.32% during the year. Higher copper and aluminum prices contributed to value growth, whil
- [94774] concall 2026-05-12 p3 score=13.55 cov=5 phr=1 **GOLD** — Anil Gupta: Okay. Good afternoon, friends. I'm Anil Gupta, CMD, KEI Industries Limited. I will give brief about the financial results of this quarter as well as the full 
- [90887] concall 2025-05-14 p3 score=12.864 cov=5 phr=1 — Anil Gupta: Good afternoon dear colleagues. Thank you very much for joining, I am Anil Gupta – Chairman and Managing Director, KEI Industries Limited along with me, Mr. R
- [96033] concall 2026-08-10 p3 score=12.745 cov=4 phr=1 — Anil Gupta: Thank you, Achal. Good afternoon. I'm Anil Gupta, CMD, KEI Industries Limited. I hope that you must have received a brief of our Q1 results, it must be with y
- [96048] concall 2026-08-10 p9 score=12.65 cov=4 phr=1 — Umang Mehta: Congrats on a strong margin trend. Sir, first question was again on margin. So you mentioned product mix and efficiencies in the operations. Actually, sir, 5
- [90894] concall 2025-05-14 p7 score=12.6 cov=5 phr=1 — Rajeev Gupta: Pranay, what is your exact query? Pravin Sahay: So sir, what I believe is, if there is an improvement uptrend in the LME prices, there would be a some gain 
- [85320] annual_report 2026-09-05 p42 score=11.85 cov=6 phr=0 — DISCUSSING THE FINANCIAL PERFORMANCE FOR THE YEAR We delivered strong and broad-based financial performance during FY 2025-26. Net sales reached ` 11,748 crore, marking a
- [105496] deck 2026-08-07 p19 score=9.1 cov=4 phr=0 — Revenue growth of 22.97% YoY in Q1 FY27. Growth was driven by broad-based demand in Wires & Cables and balanced business performance. EBITDA growth of 39.57% YOY in Q1 
- [105298] deck 2026-08-03 p1 score=8.65 cov=4 phr=0 — KEI INDUSTRIES LIMITED KEI Industries Limited Q-1 FY 2027 Earnings Presentation August 03, 2026 Revenue growth of 22.97% YoY in Q1 FY27. Growth was driven by broad-based
- [63120] annual_report 2025-07-07 p20 score=8.6 cov=5 phr=0 — 17 Integrated Annual Report 2024-25 Output Outcomes Low Tension Cables EHV Cables (Up to 400kV) Solar Cables Instrumentation Cables ESP Cables Flat Cables Thermocouple Ca

**Quote context:**

> r '25. And second and last phase is expected to be commissioned in the fourth quarter of FY26, '27. In financial year '25-'26, average copper price increased by 16.85% and average aluminum prices increased by 9.91%. During FY25-'26, operating margin has improved to 10.46% against 10.18%. EBITDA in this financial year -- full financial year is INR1,387 crores, up by 30.56% compared to last year. EBITDA/net sales margin is 11.81% as against 10.92% in the previous year. So the profit after tax in financial year '25-'26 is INR918 crores with a PAT margin of 7.82%. Domestic institutional cable sale, wire and cable has been INR2,688 crores. However

**Gold locator:** chunk 94774 concall 2026-05-12 overlap=1.0 in_top=True


## Q36 MB0331 KEI — verified

**Q:** KEI Industries' first phase at Sanand: what month did it actually get commissioned, and how far behind the original plan was that?

as_of=2026-10-31 types=concall,deck template=A01 gold_found=True gold_in_top=True gold_rank=4
**Bank gold:** “You are aware that our Sanand plant was commissioning of first phase was delayed by around 6 months. So we commissioned the first phase in the December '25.”

**Answer:** The first phase at Sanand was commissioned in December 2025, about 6 months behind the original plan.

**Quote:** our Sanand plant was commissioning of first phase was delayed by around 6 months. So we commissioned the first phase in the December '25.

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [96044] concall 2026-08-10 p7 score=14.7 cov=5 phr=1 — Am I right? Rajeev Gupta: Yes, sir. Raman KV: So yes, sir, I just want to understand in Sanand what kind of products are we catering to? And the Phase 2 in which we will 
- [96054] concall 2026-08-10 p11 score=13.65 cov=6 phr=0 — Achal Lohade: Got it. Sir, second question I had was with respect to Sanand plant. Given INR2,000 crores of capex and the EHV and the non-EHV mix, how do we look at the a
- [85295] annual_report 2026-09-05 p17 score=12.3 cov=6 phr=0 — used in utilities, renewable energy, oil and gas and infrastructure projects. The United States market had slowed as tariff uncertainty affected customer decisions. With 
- [94774] concall 2026-05-12 p3 score=11.313 cov=5 phr=0 **GOLD** — Anil Gupta: Okay. Good afternoon, friends. I'm Anil Gupta, CMD, KEI Industries Limited. I will give brief about the financial results of this quarter as well as the full 
- [94808] concall 2026-05-12 p15 score=10.925 cov=5 phr=0 — Akshay Gattani: And on the volume growth front, sir, volume growth is accelerating from 6.5% in FY26 to 16% to 18% in '27. So how would this impact operating leverage? An
- [85379] annual_report 2026-09-05 p95 score=10.1 cov=5 phr=0 — BIODIVERSITY AND ECOSYSTEMS Healthy ecosystems support resilient communities, reliable water systems and long-term economic activity. None of our reported plants or offic
- [96050] concall 2026-08-10 p9 score=10.028 cov=4 phr=0 — Moderator: We take the next question from the line of Disha from Trinetra Asset Managers. KEI Industries Limited August 04, 2026 Page 9 of 19 Disha: Most of my questions 
- [85294] annual_report 2026-09-05 p15 score=9.856 cov=5 phr=0 — ANIL GUPTA Chairman-cum-Managing Director The wires and cables segment grew by 22.32% during the year. Higher copper and aluminum prices contributed to value growth, whil
- [85328] annual_report 2026-09-05 p49 score=8.65 cov=4 phr=0 — KEY INITIATIVES FOR THE YEAR Capacity expansion and technological advancement We accelerated progress on the Sanand project, a ` 1,900‑2,000 crore greenfield facility set
- [63117] annual_report 2025-07-07 p15 score=8.48 cov=5 phr=0 — 12 KEI Industries Limited Our stainless-steel wire division remained stable with annual sales of ` 212 crore and 89% capacity utilization. As India consolidates its posit

**Quote context:**

> r wire capacity and for cables, the growth will come from Sanand plant. We are expecting 17% to 18% volume growth in this current financial year, which will mainly coming from Sanand new facility. You are aware that our Sanand plant was commissioning of first phase was delayed by around 6 months. So we commissioned the first phase in the December '25. And second and last phase is expected to be commissioned in the fourth quarter of FY26, '27. In financial year '25-'26, average copper price increased by 16.85% and average aluminum prices increased by 9.91%. During FY25-'26, operating margin has improved to 10.46% against 10.18%. EBITDA in this

**Gold locator:** chunk 94774 concall 2026-05-12 overlap=1.0 in_top=True


## Q37 MB0340 NTPC — verified

**Q:** NTPC has over 33 GW under construction. What is the coal/hydro/renewable split, and which of those is the largest single block?

as_of=2026-10-31 types=concall,deck,results_notes template=A01 gold_found=True gold_in_top=True gold_rank=8
**Bank gold:** “We have over 33 GW of capacity under construction comprising 16.5 GW of coal-based capacity, about 1.9 GW of hydro and around 15 GW of renewable energy, and this is providing a solid foundation for near- to medium-term g”

**Answer:** NTPC has over 33 GW under construction, comprising 16.5 GW coal-based, about 1.9 GW hydro, and around 15 GW renewable energy; coal is the largest single block.

**Quote:** We have over 33 GW of capacity under construction comprising 16.5 GW of coal-based capacity, about 1.9 GW of hydro and around 15 GW of renewable energy

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]

**Retrieved chunks:**
- [39439] concall 2026-08-02 p9 score=16.9 cov=7 phr=0 — In FY26, we added 9.6 gigawatt of new capacity, and 1.9 gigawatt has already been added in FY27 till date. We continue to set benchmarks in operational excellence, consis
- [25316] annual_report 2026-08-04 p9 score=16.38 cov=9 phr=0 — NTPC LIMITED | 13 12 | INTEGRATED ANNUAL REPORT 2025-26 Our Group’s Overview Innovating for Sustainability Statutory Disclosures Statutory and Financial Results For secto
- [25447] annual_report 2026-08-04 p71 score=13.15 cov=7 phr=0 — ACS-ARR Gap (DISCOMs) ₹0.06/kWh (FY25) ₹0.21/kWh (FY24) -71.4%, Sharp improvement in performance Historic Milestones in FY 2025–26 • NDC target achievement ahead of sched
- [25315] annual_report 2026-08-04 p8 score=13.069 cov=7 phr=0 — NTPC LIMITED | 11 10 | INTEGRATED ANNUAL REPORT 2025-26 Our Group’s Overview Innovating for Sustainability Statutory Disclosures Statutory and Financial Results Energisin
- [25444] annual_report 2026-08-04 p70 score=12.7 cov=6 phr=0 — GLOBAL ENERGY & POWER SECTOR LANDSCAPE | FY 2025–26 The year 2025 marked a significant inflection point in the global power sector. For the first time, renewable energy a
- [25449] annual_report 2026-08-04 p72 score=12.664 cov=6 phr=0 — SEGMENT-WISE / PRODUCT-WISE PERFORMANCE Power Generation NTPC Group generated 432.2 BU of electricity in FY 2025–26, marginally lower than 438.6 BU in FY 2024–25, primari
- [36271] concall 2025-11-06 p8 score=11.956 cov=5 phr=0 — Some of the other key developments include business transfer agreement for transfer of coal mines from NTPC to NTPC Mining Limited was signed for hiving off coal mining b
- [37389] concall 2026-02-04 p7 score=11.927 cov=5 phr=0 **GOLD** — The issue was oversubscribed by around 8X, which shows the investors' confidence and favorable market perception. Some of the other key points on financial results are as
- [39438] concall 2026-08-02 p7 score=11.66 cov=5 phr=0 — Beginning with Indian economy and the structural outlook, India continues to be the fastest- growing major economy, with IMF projecting GDP growth of 6.4% in 2026, well a
- [51267] deck 2026-07-27 p12 score=10.85 cov=5 phr=0 — • • Overview - Operation and Under Construction Capacity (GW) ~ ======;:=====;::==::::::;:::::::=====:------:---------- tr.rllafllll NTPC Mode O·peration Under Constructi

**Quote context:**

> ion (DX) Awards. We are pursuing growth through a balanced expansion across conventional and clean energy segments while maintaining a strong focus on fuel security, on-time execution and prudent capital allocation. We have over 33 GW of capacity under construction comprising 16.5 GW of coal-based capacity, about 1.9 GW of hydro and around 15 GW of renewable energy, and this is providing a solid foundation for near- to medium-term growth. To strengthen fuel assurances and value creation, we are also working on coal gassification, which has the potential to operationalize gas assets continuously. On the nuclear front, we are progressing steadi

**Gold locator:** chunk 37389 concall 2026-02-04 overlap=1.0 in_top=True


## Q38 MB0395 TRUALT — verified

**Q:** TruAlt ke promoter ne kab pledge banaya, aur kitne shares ka? (Hinglish)

as_of=2026-10-31 types=announcement template=A05 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** TRUALT: “TruAlt Bioenergy Limited has informed the exchange regarding creation of Pledge of shares by Mrs. Kamala Murugesh Nirani” filed 2026-09-28T19:26:25.913

**Answer:** The promoter's shares were initially pledged in 2023, when the consortium of banks decided to avail 26% of the shares; these were later released and re-pledged after listing as compliance. The exact number of shares pledged is not stated.

**Quote:** consortium of banks at that moment initially decided to avail let 26% of the shares. That was long back, I am referring in 2023

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** exact number of shares pledged

**Retrieved chunks:**
- [36816] concall 2025-11-19 p18 score=7.5 cov=3 phr=0 — Vibhor Tomar: Okay. And earlier, this pledging was done because of what reason like for getting the funding from the banks? Anand Kishore: Because we are getting the fund
- [36815] concall 2025-11-19 p17 score=7.05 cov=3 phr=0 **GOLD** — Vibhor Tomar: Yes. Hi. So, my question is basically regarding the pledging which you have done yesterday. So, was there any particular reason for that? Because I guess yo
- [39649] concall 2026-08-04 p14 score=4.7 cov=2 phr=0 — Shriram Palaniappan: Sir, and may I know the when the loan related to the pledged shares will be repaid by? Anand Kishore: Sir, so basically the this loan is not against 
- [38821] concall 2026-05-28 p23 score=3.625 cov=1 phr=0 — Parth Shah: Hi, sir. I wanted to ask you, last year, you closed the book at 1,800 crores. So on an absolute basis, what can we expect from this year? And second question 
- [37727] concall 2026-02-13 p11 score=3.58 cov=1 phr=0 — Charchit Maloo: 36 to 37 for the year. Okay. And like what kind of EBITDA margin are we targeting for Q4? Vijay Nirani: It is looking somewhere in the range of 20% to 22%
- [47471] deck 2025-10-19 p15 score=3.4 cov=1 phr=0 — IMPRESSIVE MARKET DEBUT Marking a significant milestone in its corporate journey, TruAlt Bioenergy Limited was successfully listed on the BSE Limited on October 03, 2025.
- [53110] announcement 2026-08-07 p1 score=-1.8 cov=1 phr=0 — August 7, 2026 BSE Limited, National Stock Exchange of India Limited, Department of Corporate Services, The Listing Department, Phiroze Jeejeebhoy Towers, Exchange Plaza,
- [36826] concall 2025-11-19 p21 score=3.55 cov=1 phr=0 — Piyush Bangar: Okay. And what will be the IRR expectation from this project? Anand Kishore: So assuming that my plant runs at the capacity of 85% to 90% capacity utilizat

**Quote context:**

> Vijay Murugesh Nirani: Yes, please. Anand Kishore: So, pledging is basically not done for the purpose of interest because initially, we have been availed the bank borrowing from the State Bank of India, Narheda. The consortium of banks at that moment initially decided to avail let 26% of the shares. That was long back, I am referring in 2023. Now, as a listing for getting the company listed as a listing compliance, those shares were re-pledged. So, we have released the pledge. And then again, we were given 45 days timeline to again re-pledge the share once listing is done. So, because we were nearing the 45 days timeline, we have again re-ple

**Gold locator:** chunk 36815 concall 2025-11-19 overlap=0.615 in_top=True


## Q39 MB0622 TRUALT — not_stated

**Q:** How many shares did TruAlt's promoter actually pledge in September 2026?

as_of=2026-10-27 types=announcement template=A20 gold_found=True gold_in_top=True gold_rank=2
**Bank gold:** TRUALT: “TruAlt Bioenergy Limited has informed the exchange regarding creation of Pledge of shares by Mrs. Kamala Murugesh Nirani” filed 2026-09-28T19:26:25.913

**Answer:** not stated

**Quote:** (none)

**Verify:** status=not_stated quote_ok=False kind=None number_ok=True missing_numbers=[]
**Model says missing:** the number of shares pledged in September 2026

**Retrieved chunks:**
- [36816] concall 2025-11-19 p18 score=7.5 cov=3 phr=0 — Vibhor Tomar: Okay. And earlier, this pledging was done because of what reason like for getting the funding from the banks? Anand Kishore: Because we are getting the fund
- [36815] concall 2025-11-19 p17 score=7.05 cov=3 phr=0 **GOLD** — Vibhor Tomar: Yes. Hi. So, my question is basically regarding the pledging which you have done yesterday. So, was there any particular reason for that? Because I guess yo
- [39649] concall 2026-08-04 p14 score=6.3 cov=3 phr=0 — Shriram Palaniappan: Sir, and may I know the when the loan related to the pledged shares will be repaid by? Anand Kishore: Sir, so basically the this loan is not against 
- [37734] concall 2026-02-13 p13 score=5.225 cov=2 phr=0 — Prashant Shah: Hello. Is my voice audible? Vijay Nirani: Yes sir. TruAlt Bioenergy Limited February 09, 2026 Page 13 of 21 Prashant Shah: So, I had one general question. 
- [38824] concall 2026-05-28 p24 score=5.18 cov=2 phr=0 — Vijaykumar Nirani: It's a lot larger, sir. Per litre, if you see, it's about INR10 to INR11 now, or about INR11.5, I could say. Charchit: No, I'm asking about ethanol. Li
- [51314] deck 2026-07-28 p26 score=3.529 cov=1 phr=0 — STANDALONE PERFORMANCE - THREE MONTHS ENDED (All amounts are in ₹ Cr. unless otherwise stated) Particulars For the 3 months ended June 30, 2026 For the 3 months ended Jun
- [51311] deck 2026-07-28 p21 score=3.5 cov=1 phr=0 — Mudhol (Bagalkot, Karnataka) ▪ 95% civil construction completed, 70% mechanical erection completed. ▪ Major equipment including digesters have neared completion, with hyd
- [51312] deck 2026-07-28 p22 score=3.469 cov=1 phr=0 — UPDATE ON STATUTORY & EXECUTION STATUS ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪ Badami (Bagalkot, Karnataka) ▪ 90% civil construction completed, 65% mechanical erection completed ▪ Major eq
- [51313] deck 2026-07-28 p23 score=3.464 cov=1 phr=0 — RETAIL FUEL SEGMENT ▪ 7 outlets currently operational; 4 additional stations set to launch by in the coming months. ▪ Network to reach 11 operational outlets across Karna
- [51303] deck 2026-07-28 p11 score=3.453 cov=1 phr=0 — SEGMENT-WISE HIGHLIGHTS FOR THREE MONTHS ENDED JUNE 30, 2026 I N V E S T O R P R E S E N T A T I O N • Q 1 F Y 2 0 2 6 - 2 7 07 EBITDA ₹ 34.78 Cr. (Q1 FY 26) ₹ 126.56 Cr.

**Gold locator:** chunk 36815 concall 2025-11-19 overlap=0.615 in_top=True


## Q40 MB0344 ULTRACEMCO — verified

**Q:** UltraTech's capacity is 184 million tonnes including India Cements and Kesoram. What is the target it is being expanded to, and over what period?

as_of=2026-10-31 types=concall,deck,announcement template=A01 gold_found=True gold_in_top=True gold_rank=1
**Bank gold:** “which will take us from the current capacity of 184 million tons, 184 million includes India Cements and Kesoram capacities also from 184 million to take us to close to 212 million tons of capacity in India.”

**Answer:** UltraTech's capacity of 184 million tons is being expanded to close to 212 million tons of capacity in India; the excerpts do not state a precise completion period beyond the end of the expansion program.

**Quote:** from 184 million to take us to close to 212 million tons of capacity in India

**Verify:** status=verified quote_ok=True kind=exact number_ok=True missing_numbers=[]
**Model says missing:** exact period/date for reaching the 212 million ton target

**Retrieved chunks:**
- [90704] concall 2025-05-02 p3 score=19.25 cov=8 phr=1 **GOLD** — Atul Daga: Thank you so much, Michelle and good evening, and a very warm welcome to all of you for this earnings call for Quarter 4, FY '25 for UltraTech. It's a maze of 
- [88645] concall 2024-10-23 p4 score=18.412 cov=8 phr=1 — And as per our announced organic growth plans, we should be reaching 184 million tons of capacity by FY '27 in India. Onto the acquisitions. RAK White, a white cement com
- [106414] announcement 2026-07-24 p3 score=18.0 cov=8 phr=1 — In April 2026, an additional 8.7 MTPA was commissioned. As a result, UltraTech’s total domestic grey cement manufacturing capacity has crossed the 200 MTPA milestone, sta
- [89752] concall 2025-01-28 p4 score=17.28 cov=8 phr=1 — Central government capex which clocked 20% plus YoY growth in 2024 was down about 12% in April to November 24. State government CAPEXes were also down. CAPEXes by PSUs we
- [89757] concall 2025-01-28 p6 score=16.4 cov=7 phr=1 — Sumangal Nevatia: Yes, clearly. Sir, my second question is more on the south region. Now we have seen four acquisitions in the last year to where we have been involved. I
- [99563] deck 2025-01-23 p17 score=15.8 cov=6 phr=2 — UltraTech’s Capacity in southern states post acquisitions 16 Grey Cement Capacity (Mtpa) in Southern States States Existing Capacity India Cements Kesoram* Total Capacity
- [89761] concall 2025-01-28 p8 score=15.725 cov=7 phr=1 — Amit Murarka: And lastly, for Kesoram, could you provide 9-months financials as well? Atul Daga: We haven't seen that here. It would be there on their own website. Amit M
- [80563] annual_report 2026-07-24 p36 score=15.425 cov=7 phr=1 — MESSAGE FROM THE MANAGING DIRECTOR Dear Shareholders, The defining feature of the global and domestic economies in FY 2025-26 was resilience in the face of volatility. Th
- [80664] annual_report 2026-07-24 p112 score=15.269 cov=7 phr=1 — I II III ESG PERFORMANCE V VI VII Building trust through leadership Material Issues: G1: Business ethics and corporate governance G1   Business ethics and corporate g
- [80625] annual_report 2026-07-24 p78 score=15.229 cov=7 phr=1 — I II III ESG PERFORMANCE V VI VII Biodiversity considerations are deeply integrated into our land-use planning and site operations, with a clear focus on identifying and 

**Quote context:**

> which INR7,000 crores is towards strategic investments, the ongoing expansion program, which will take us from the current capacity of 184 million tons, 184 million includes India Cements and Kesoram capacities also from 184 million to take us to close to 212 million tons of capacity in India. Cost improvements, we are on course to deliver the overall plan in the 3-year time window.

**Gold locator:** chunk 90704 concall 2025-05-02 overlap=1.0 in_top=True

