# Query layer v1 — strict bench report

Same 150-case sample (`SAMPLE.jsonl`, 30 regressions) and the same held databases, read-only. `RESULTS_v0.jsonl` is the merged v0 run; `RESULTS_v1.jsonl` is v1 (sub-question decomposition + named-document preference + relevance filter + EVIDENCE rerank). Both are re-graded here by `grade_v1.py`, which is stricter than `run_bench.finish`.

Strict rules: every sub-question must be evidence-backed; wrong metric family or wrong entity -> WRONG; evidence from a document other than the one named (when it exists) -> WRONG; stale evidence without a reason -> PARTIAL; unrelated rows reduce the grade.

## 1. Grade, strict

| grade | v0 strict | v1 strict | delta | v0 bench | v1 bench |
|---|---|---|---|---|---|
| ANSWERED | 6 | 13 | 7 | 17 | 14 |
| PARTIAL | 101 | 106 | 5 | 106 | 105 |
| WRONG | 16 | 0 | -16 | 0 | 0 |
| BLOCKED_SCHEMA | 17 | 18 | 1 | 17 | 18 |
| BLOCKED_TOOL | 9 | 11 | 2 | 9 | 11 |
| NOT_IN_DATA | 1 | 2 | 1 | 1 | 2 |

**Regressions (30):** strict ANSWERED 3 -> 7; PARTIAL 21 -> 16; WRONG 2 -> 0; BLOCKED 3 -> 5.

### By family (first family in the case)

| family | cases | v0 ANSWERED | v1 ANSWERED | v0 PARTIAL | v1 PARTIAL | v0 WRONG | v1 WRONG |
|---|---|---|---|---|---|---|---|
| 1 | 21 | 1 | 4 | 12 | 11 | 4 | 0 |
| 11 | 6 | 0 | 0 | 6 | 5 | 0 | 0 |
| 12 | 4 | 0 | 0 | 4 | 4 | 0 | 0 |
| 13 | 4 | 0 | 0 | 0 | 3 | 0 | 0 |
| 14 | 8 | 0 | 2 | 4 | 3 | 1 | 0 |
| 15 | 6 | 0 | 0 | 5 | 6 | 0 | 0 |
| 16 | 17 | 0 | 0 | 14 | 12 | 1 | 0 |
| 17 | 6 | 0 | 0 | 5 | 6 | 1 | 0 |
| 18 | 3 | 0 | 0 | 3 | 3 | 0 | 0 |
| 19 | 4 | 0 | 0 | 3 | 1 | 0 | 0 |
| 2 | 20 | 5 | 7 | 9 | 9 | 3 | 0 |
| 20 | 5 | 0 | 0 | 3 | 3 | 0 | 0 |
| 3 | 3 | 0 | 0 | 3 | 3 | 0 | 0 |
| 4 | 3 | 0 | 0 | 2 | 1 | 0 | 0 |
| 6 | 20 | 0 | 0 | 18 | 20 | 0 | 0 |
| 9 | 3 | 0 | 0 | 1 | 2 | 1 | 0 |
| None | 17 | 0 | 0 | 9 | 14 | 5 | 0 |

### By source bank

| bank | cases | v0 ANSWERED | v1 ANSWERED | v0 PARTIAL | v1 PARTIAL | v0 WRONG | v1 WRONG |
|---|---|---|---|---|---|---|---|
| open300 | 38 | 0 | 0 | 27 | 30 | 1 | 0 |
| reddit200 | 30 | 0 | 2 | 17 | 24 | 8 | 0 |
| ripple200 | 23 | 0 | 0 | 20 | 16 | 1 | 0 |
| shivam30 | 30 | 3 | 7 | 21 | 16 | 2 | 0 |
| variations300 | 29 | 3 | 4 | 16 | 20 | 4 | 0 |

## 2. The 30 regressions

| mid | v0 strict | v1 strict | question | first strict reason |
|---|---|---|---|---|
| MB0001 | PARTIAL | PARTIAL | AEROFLEX products + close on a date |  |
| MB0002 | PARTIAL | ANSWERED | 532627 latest AR: control change |  |
| MB0003 | PARTIAL | BLOCKED_SCHEMA | 544161 business + segments | blocked: the declared fix is a new table/fetch |
| MB0004 | PARTIAL | PARTIAL | P/B now vs stored |  |
| MB0005 | PARTIAL | PARTIAL | DEEDEV Aug-2026 concall remark |  |
| MB0006 | PARTIAL | PARTIAL | KRISHNADEF segment revenue, latest quarter |  |
| MB0007 | PARTIAL | PARTIAL | Bank of Maharashtra net NPA % |  |
| MB0008 | ANSWERED | ANSWERED | ZENTEC 3-yr price CAGR |  |
| MB0009 | PARTIAL | PARTIAL | VISHNU Note 5 of latest results + geo split |  |
| MB0010 | PARTIAL | ANSWERED | VINCOFE public shareholding Sep 2026 |  |
| MB0011 | PARTIAL | PARTIAL | Why gold stocks fell Jun–Jul 2026 |  |
| MB0012 | BLOCKED_SCHEMA | BLOCKED_SCHEMA | HFC securitisation leader, QoQ/YoY with NPA guard | blocked: the declared fix is a new table/fetch |
| MB0013 | PARTIAL | PARTIAL | OMCs: record Q4 then loss Q1; earliest PIT signal |  |
| MB0014 | BLOCKED_SCHEMA | BLOCKED_SCHEMA | MONQ50 ETF jump/fall + tracking error | blocked: the declared fix is a new table/fetch |
| MB0015 | PARTIAL | PARTIAL | Garware: tariff hit, then negative correlation |  |
| MB0016 | PARTIAL | PARTIAL | RBI repo hike causes; PIB or RBI only |  |
| MB0017 | PARTIAL | PARTIAL | Second-hand electronics boom CY2026: who benefits |  |
| MB0018 | PARTIAL | PARTIAL | Coal gasification drafts vs the earlier scheme |  |
| MB0019 | PARTIAL | PARTIAL | PARAGMILK on El Niño; dairy peers | sub-question 2 not addressed: 'dairy peers' |
| MB0020 | PARTIAL | PARTIAL | Data-centre tax holiday outcome so far |  |
| MB0021 | WRONG | NOT_IN_DATA | What was the delivery volume (delivered quantity, not total  | blocked: the declared fix is a new table/fetch |
| MB0022 | ANSWERED | ANSWERED | What is the promoter holding of NSE: BLACKBUCK as of Septemb |  |
| MB0023 | WRONG | ANSWERED | How many manufacturing facilities does Ganesha Ecosphere hav |  |
| MB0024 | PARTIAL | ANSWERED | What are the key products of Chemcon Speciality Chemicals pe |  |
| MB0025 | BLOCKED_SCHEMA | BLOCKED_SCHEMA | How many equity shares does Lumax Auto Technologies have, an | blocked: the declared fix is a new table/fetch |
| MB0026 | NOT_IN_DATA | NOT_IN_DATA | What did BSE: 540879 show on page 21 (of 79) of its investor | blocked: the declared fix is a new table/fetch |
| MB0027 | PARTIAL | PARTIAL | What did ISIN INE864I01014 say about its fuel-cell capacity  | sub-question 1 not addressed: 'What did ISIN INE864I01014 say about its fuel-cel |
| MB0028 | ANSWERED | ANSWERED | What was the YTD high price of BSE: 532810 in 2026 (value an |  |
| MB0029 | PARTIAL | BLOCKED_SCHEMA | What did NSE: SAILIFE say about its newly commissioned facil | blocked: the declared fix is a new table/fetch |
| MB0030 | PARTIAL | PARTIAL | Per the transcript of 18 September 2026 of 540678 / COCHINSH |  |

## 3. Fixed cases (strict v0 not ANSWERED -> strict v1 ANSWERED)

| mid | v0 strict | question | why v1 is clean | answer lead |
|---|---|---|---|---|
| MB0002 | PARTIAL | 532627 latest AR: control change | clean under the strict rules | JPPOWER: close 14.0 on 2026-03-31; ar 2026-07-04 pNone: e at the link: http:// jppowerventures.com/wp-content/uploads/20 |
| MB0010 | PARTIAL | VINCOFE public shareholding Sep 2026 | clean under the strict rules | Public holding % 2026-09-30 = 64.99 % (shp_index, known 2026-10-13); Minimum public shareholding maintained in hands of  |
| MB0023 | WRONG | How many manufacturing facilities does Ganesha Ecosphere have, per its investor  | clean under the strict rules | named deck 2026-08-05: Manufacturing Facilities - = 6.00 - (deck_figures, known 2026-08-03); State-of-the-art manufactur |
| MB0024 | PARTIAL | What are the key products of Chemcon Speciality Chemicals per its investor prese | clean under the strict rules | deck 2026-05-22 p21: No 2 | - | 2 | - Sr No 3 | - | 3 | - Sr No 4 | - | 4 | - Installed Capacity (MTPA) - HMDS, CMIC, Br |
| MB0245 | WRONG | Himadri Speciality Chemical (NSE: HSCL) mein promoter ki holding Sep 2026 tak ki | clean under the strict rules | Promoter holding % 2026-09-30 = 52.49 % (shp_index, known 2026-10-13); Promoter holding % 2026-06-30 = 52.5 % (shp_index |
| MB0883 | PARTIAL | Vodafone Idea: did the promoter group raise its stake through the preferential i | clean under the strict rules | Promoter holding change (pp) 2026-03-31 -> 2026-06-30 = 0.00 pp (computed, known 2026-07-21); December 31, 2025 amendmen |
| MB0885 | WRONG | Which large-cap had the biggest promoter stake sale in the last year, and did th | clean under the strict rules | promoter holding change (pp), IRFC -3.46pp (2025-09-30->2026-09-30); COALINDIA -2.00pp (2025-09-30->2026-09-30); JSWSTEE |

All fixed cases (7): MB0002, MB0010, MB0023, MB0024, MB0245, MB0883, MB0885

Cases that got a worse strict grade under v1 (12): MB0003, MB0029, MB0148, MB0416, MB0417, MB0472, MB0619, MB0637, MB0640, MB0715, MB0728, MB0808

## 4. Remaining top blockers

| blocker | cases | examples |
|---|---|---|
| blocked: the declared fix is a new table/fetch | 31 | MB0003, MB0012, MB0014, MB0021, MB0025 |
| hop did not answer: RIPPLE+RIPPLE: hop failed: RIPPLE (policy RBI_Monetary_Policy: RBI Gov | 3 | MB0609, MB0793, MB0801 |
| hop did not answer: COMPARE: hop failed: COMPARE (no comparable metric for two peers filed | 2 | MB0004, MB0424 |
| hop did not answer: RIPPLE: hop failed: RIPPLE (policy RBI_MPC_Minutes: RBI Minutes of the | 2 | MB0013, MB0015 |
| hop did not answer: RIPPLE: hop failed: RIPPLE (policy RBI_Monetary_Policy: RBI Governor’s | 2 | MB0016, MB0197 |
| hop did not answer: RIPPLE: hop failed: RIPPLE (policy Ministry of Youth Affairs and Sport | 2 | MB0020, MB0224 |
| hop did not answer: EXPECTATIONS: hop failed: EXPECTATIONS (the held numbers may answer th | 2 | MB0839, MB0898 |
| hop did not answer: RIPPLE: hop failed: RIPPLE (policy RBI_Monetary_Policy: RBI Full Docum | 2 | MB0151, MB0154 |
| hop did not answer: RIPPLE+EVIDENCE: hop failed: RIPPLE (policy RBI_MPC_Minutes: RBI Minut | 2 | MB0159, MB0199 |
| hop did not answer: RIPPLE+RIPPLE+RIPPLE: hop failed: RIPPLE (policy RBI_Monetary_Policy:  | 2 | MB0806, MB0829 |
| hop did not answer: EVIDENCE: hop failed: EVIDENCE (no passage matching 'products' in the  | 1 | MB0001 |
| hop did not answer: EVIDENCE: hop failed: EVIDENCE (no passage matching 'concall' in the t | 1 | MB0005 |

## 5. Rule audit (strict rows touched)

| rule | rows |
|---|---|
| sub-question | 187 |
| different metric | 14 |
| unrelated row | 10 |
| stale: | 5 |
| exists, but | 1 |
| follow-up was | 1 |

A row with no strict reason but a PARTIAL grade is the bench's own hop failure (the strict rules added nothing); the blocker column names it.
