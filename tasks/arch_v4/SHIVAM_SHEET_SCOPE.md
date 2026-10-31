# Sheet B - 20 set, ranking and theme questions answered over the 60 pilot names

**Hand-built demonstrations, not engine output.** Prepared 31 Oct 2026 for Shivam's scope ruling (Gate 95% review, idea 6). Nothing here is a v4 run; every answer was produced by me with one read-only SQL query, and the store, table and filter are named under each row. The point is to show what a scoped answer looks like and where it is plainly weak, so you can rule on idea 6.

**Population and seed.** The 373 master-bank parents whose entity level is `industry`, `theme`, `index`, `market-wide`, `market-cap bucket` or `sector` (the set class; `policy` and `macro` parents are excluded because they are transmission chains, not sets). Sampled with seed `20261031`, 20 rows.

**The scope used in every answer:** "over the 60 pilot names" = the 60 ISINs in `tasks/pilot60/UNIVERSE.csv`. That intersection is small: 12 of the 149 NIFTY MIDCAP 150 members, 24 of the 250 NIFTY LARGEMIDCAP 250 members, 1 of the 10 FPI-150 membership windows held (`market_state_pilot.company_membership_pit`, snapshot 2026-09-30). A set answer can only be as complete as that intersection.

**Result in one line:** 7 of 20 can be answered as a list or count over the 60; 4 of those 7 are *text searches over concall extracts* (a count of mentions, not a structured set); 2 are weak proxies; 11 have no 60-name answer at all.

| Result | Rows |
|---|---|
| A list or count over the 60, with values and provenance | MB0108 (pilot-wide rank only), MB0217, MB0361, MB0368, MB0372, MB0392, MB0409 |
| Only a weak proxy | MB0647, MB0736 |
| No 60-name answer: the atom or cohort does not exist in the pilot | MB0088, MB0143, MB0146, MB0167, MB0384, MB0428, MB0520, MB0691, MB0724, MB0729, MB0764 |

---

**1. MB0108** (index, ranking) - "For the NIFTY INDIA FPI 150 constituents, what was the 3-year adjusted price CAGR to 19 October 2026, ranked?"
- Scoped answer: 1 of the held FPI-150 members is a pilot name (IDEA, +0.8%: 12.00 -> 12.28). Pilot-wide rank as context (58 of 60 have both closes): PANACHE +108.8%, STLTECH +76.0%, ANANDRATHI +66.0%; worst RAJESHEXPO -49.5%, DHARAN -53.6%, INE070C01037 -56.6%. `pilot/pilot60/market_state_pilot.db company_state_daily` close on 2023-10-19 and 2026-10-19.
- Weak because: the requested universe is FPI 150 and the pilot holds 1 member; a one-name ranking is not a ranking.
- Satisfied? ______

**2. MB0143** (industry, ranking) - "Is IBULHSGFIN (now SAMMAANCAP) the leader in securitised disbursement among listed HFCs for Q1FY27, with net NPA up no more than 2 pp?"
- Scoped answer: 0 of 60. `sector_pit.db company_sector_pit` lists 13 HFCs, none of them a pilot name; `concall_facts.cc_items` has securitisation mentions for 5 pilot names (ANANDRATHI 5, POWERGRID 2, BOSCHLTD, ASHOKA, AURUM 1 each) but no disbursement amount.
- Weak because: the cohort is empty and the metric (securitised disbursement, net NPA) is not a held atom.
- Satisfied? ______

**3. MB0146** (industry, ranking) - "Which listed HFC is the leader in securitised disbursement for January-March 2026, QoQ and YoY, with net NPA rising no more than 2 pp?"
- Scoped answer: 0 of 60 (same empty HFC cohort as MB0143).
- Weak because: no HFC in the pilot and no securitisation-disbursement or net-NPA atom anywhere in the pilot stores.
- Satisfied? ______

**4. MB0167** (index, ranking) - "For the India-listed ETF universe, what explains the move in 10-18 Sep 2026 and 18-28 Sep 2026, and what is the NAV tracking error?"
- Scoped answer: 0 of 60. The pilot holds no ETF; `fact_v4_pilot.fact` has `macro.etf_premium` for 5 market-wide ETFs, none of them a pilot entity.
- Weak because: the cohort is outside the pilot by construction; a 60-equity-name scope cannot answer an ETF question.
- Satisfied? ______

**5. MB0217** (industry, ranking) - "For all listed companies in Fast Moving Consumer Goods, what did managements say about El Nino 2026, and how are they handling it?"
- Scoped answer: 2 of 60 mention El Nino (`concall_facts.db cc_items` statement/quote LIKE '%El Ni%'): DALBHARAT ("uncertainties surrounding the progress of monsoon due to potential effect of El Nino continues to warrant close monitoring") and BAJFINANCE ("the super El Nino did not impact the country"). Neither is in the FMCG cohort; no FMCG name mentions it.
- Weak because: the answer is a quote search over extracted items, not a structured disclosure set; absence is not proof the topic was not discussed.
- Satisfied? ______

**6. MB0361** (market-wide, list) - "Which companies guided FY27 EBITDA margin recovery, and what is the evidence for each?"
- Scoped answer: 33 of 60 have at least one `guidance` item mentioning margin (`concall_facts.cc_items[list_name=guidance]`). Most: ASHIANA 17, STLTECH 16, JUBLINGREA 15, KHADIM 15, DDEVPLSTIK 13, UFLEX 13 items. The store has quotes, not a signed "recovery yes/no" field.
- Weak because: a count of margin mentions is not a recovery-guidance set; direction and magnitude need reading each quote.
- Satisfied? ______

**7. MB0368** (market-wide, list) - "Which managements said they are evaluating acquisitions or inorganic growth, and which have actually signed something?"
- Scoped answer: 9 of 60 have a guidance item mentioning acquisition or inorganic growth: AURUM 5, DALBHARAT 3, BOSCHLTD 2, and 1 each for INDHOTEL, ASHIANA, ANANDRATHI, ALKEM, WPIL, ANURAS. `concall_facts.cc_items`.
- Weak because: "said they are evaluating" is extractable; "actually signed something" needs the announcement store and a matching rule, which this query does not do.
- Satisfied? ______

**8. MB0372** (market-wide, list) - "Which managements said they will reduce net debt this financial year, and by how much?"
- Scoped answer: 5 of 60 mention net debt in a guidance item: STLTECH 4, GRASIM 2, UFLEX 2, HINDALCO 1, APLAPOLLO 1. `concall_facts.cc_items[list_name=guidance]`.
- Weak because: the reduced amount is not a field; the count is a mention count, not a commitment with a number.
- Satisfied? ______

**9. MB0384** (market-wide, NOT IN DATA) - "emphasis-of-matter paragraphs in latest results filings"
- Scoped answer: no 60-name answer. `results_xbrl.filings` holds `audit_opinion` for 2,527 pilot-name filings but the values are the LODR declaration, not the paragraph: 1,009 "Not applicable", 995 NULL, 495 "Declaration of unmodified opinion", 28 "Statement on impact of audit qualification". No emphasis-of-matter text is stored.
- Weak because: the field the question asks for does not exist; a scoped answer would need the PDF.
- Satisfied? ______

**10. MB0392** (market-wide, fact) - "How many auditor-resignation and auditor-appointment filings are in the announcement store, and what does the gap between them say?"
- Scoped answer: 38,513 announcements for the 60 names (`bse_announcements.db ann`, 1.95M rows market-wide); 272 headlines mention an auditor; 15 mention both auditor and resign, 140 both auditor and appoint. Examples: APLAPOLLO "Resignation of Statutory Auditor of material subsidiary" (2025-08-11), BIGBLOC "Resignation of Internal Auditor" (2026-04-21), ALKEM "appointment of M/s Deloitte ... as Statutory Auditors" (2024-05-29).
- Weak because: the counts are headline text matches, not a classified filing stream; 140 "appoint" hits include routine audited-results boilerplate.
- Satisfied? ______

**11. MB0409** (market-wide, ranking) - "Which companies disclosed a tax or regulatory demand in Q2 FY27 that is large relative to their profit?"
- Scoped answer: 6 demand/penalty announcements in Q2 FY27 for the 60: APLAPOLLO 2, ASHIANA 2, INDHOTEL 1, UBL 1 (`bse_announcements.ann`, NEWS_DT 2026-07-01..2026-09-30). Q1 FY27 consolidated PAT from `fact_v4_pilot.fact[fin.pat]`: APLAPOLLO 263.11 cr, ASHIANA 13.11 cr, INDHOTEL 390.81 cr, UBL 166.28 cr.
- Weak because: the demand amount is not in the announcement metadata (it sits in the attached PDF), so "large relative to profit" cannot be computed from the stores.
- Satisfied? ______

**12. MB0428** (market-wide, explanation) - "On 1 February 2021 the Nifty 50 rose 4.74%. Which policy lines in the store were published around that date, and do they explain it?"
- Scoped answer: no 60-name answer. The policy store (`macro.policy`, 7,314 rows in the pilot fact view) is market-wide and not keyed to the 60; a 60-name slice of it is not a meaningful boundary.
- Weak because: this is a market-wide event question; scoping it to 60 companies would answer a different question.
- Satisfied? ______

**13. MB0520** (theme, explanation) - "EV adoption badhne se kaunse auto-component names jeetenge aur kaun harenge?"
- Scoped answer: 1 of 60. `sector_pit.db` has exactly one pilot name in Auto Components (BOSCHLTD); the other 10 auto-component ISINs sit outside the pilot.
- Weak because: a winners-and-losers answer over one name is not an answer.
- Satisfied? ______

**14. MB0647** (market-cap bucket) - "Container freight doubles ... importers hold more inventory, the cash cycle lengthens, short-term debt rises. Which listed mid-caps are most exposed?"
- Scoped answer: partial. `fact_v4_pilot.fact` holds inventory for 56 of 60 and total debt for 54, but receivables for only 3; COGS is not held, so inventory days and the cash cycle cannot be computed. A held-data proxy is inventory / revenue at the latest period_end, which is not the question.
- Weak because: the exposure measure the question needs (cash-cycle days) is not computable from held atoms.
- Satisfied? ______

**15. MB0691** (industry) - "A shipping route closes ... the exporter's finished stock piles up ... Which listed exporters are most exposed?"
- Scoped answer: no 60-name answer. No export-revenue or geographic-split atom exists in the pilot stores; `fin.segment_value` carries segment EBIT/revenue, not an export split.
- Weak because: the exposure denominator (export share of revenue) is missing.
- Satisfied? ______

**16. MB0724** (industry) - "Two hospital chains add beds in the same metro. Trace the beds, then occupancy, then pricing per procedure ... Which listed chain is most exposed?"
- Scoped answer: 0 of 60 hospital chains (`sector_pit.db`); the nearest pilot name is INDHOTEL (hotels). No beds, occupancy or per-procedure price atom.
- Weak because: the cohort is empty and the operating metrics are not held (NG13).
- Satisfied? ______

**17. MB0729** (industry) - "A bank decides to build a small-ticket personal-loan book. Trace it to the NBFC's borrower acquisition cost, then ticket size, then credit cost ..."
- Scoped answer: no 60-name answer. The pilot holds NBFC names but no acquisition-cost, ticket-size or credit-cost atom; `hold.pct` and `fin.*` do not carry them.
- Weak because: a three-step transmission with none of its three inputs held.
- Satisfied? ______

**18. MB0736** (market-wide) - "A company raises equity and repays debt. Trace the interest saving, then the PAT, then the rating, then the cost of the next borrowing. Is the equity cheaper than the debt?"
- Scoped answer: partial. Interest expense for 56 of 60 and total debt for 54 (`fact_v4_pilot.fact`), so the interest saving on a hypothetical repayment can be computed per name; no credit-rating store exists, so the last two links cannot.
- Weak because: half the chain is missing, and the hypothetical needs a declared repay amount.
- Satisfied? ______

**19. MB0764** (industry) - "Freight doubles. How many quarters before the importer's cash cycle lengthens, and what does the past cycle say it cost in interest?"
- Scoped answer: partial. Inventory and interest expense are held for most of the 60; receivables for 3; no freight series keyed to the 60 and no historical cash-cycle series, so the lag cannot be measured.
- Weak because: the lag is the question, and the series needed to measure it is absent.
- Satisfied? ______

**20. MB0088** (index, NOT IN DATA) - "For the niftymidcap150 constituents, rank the companies by reported segment revenue for Q1FY27."
- Scoped answer: 12 of the 149 members are pilot names (DALBHARAT, HINDPETRO, SAIL, KALYANKJIL, ATGL, ALKEM, NLCINDIA, TATAELXSI, UBL, APLAPOLLO, GMRAIRPORT, PRESTIGE). Segment revenue exists only at fiscal year ends: latest 2026-03-31, 36 rows over 10 pilot names (`fact_v4_pilot.fact[fin.segment_value]`, dims `metric=revenue`). No Q1FY27 segment revenue is held.
- Weak because: the quarter asked for is not stored, and 10 of the 12 members have no segment-revenue row at all.
- Satisfied? ______

---

*Counts in this sheet were measured on 31 Oct 2026 against the pilot stores with one read-only query per row; the full commands are in the session log. This sheet is a set of hand-built demonstrations, not v4 engine output, and must not be read as an engine score.*
