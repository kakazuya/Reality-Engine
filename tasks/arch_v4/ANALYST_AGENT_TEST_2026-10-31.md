# Analyst agent test — free model answers bank questions with typed stores (31 Oct 2026)

> **Controller review, 31 Oct:** the verdict stands. Two corrections, neither changes it. "No adjusted price atom" below is wrong: `price.close` is the adjusted close, and it is the raw level that the store lacks. Q10 and Q11 accept XBRL-rounded share counts as exact, which the read grade marks PARTIAL; on that standard RIGHT would be lower still. The sample was screened first (1,111 eligible of 2,098), so this rate does not apply to the whole bank.

**Verdict: KILL.** The free-model analyst got **7 of 24 RIGHT (29.2%)** on the rows that are not
ILL_POSED and not CORRECT_NOT_IN_DATA. The fixed rule was under 50% RIGHT means kill. Wilson 95%
interval **[14.9%, 49.2%]**; the point estimate is below the threshold and the interval's upper bound
is also below 50%. The rule was fixed before the run and did not move. A pass would only have allowed
a design proposal for Shivam; a kill allows none.

The free model is not the main problem. With native typed tools it answered all 40 rows (no empty
replies, no bad JSON) at 8.2 s and 19.7k input tokens per question. The failures are the bank's
premises (11/40 ILL_POSED), missing store rows (10 data gaps), and a tool surface that cannot sort,
aggregate or chart (6 tool gaps). The model also returned the wrong measure or person on several
rows where the data was held (Q03, Q06, Q13, Q23, Q24, Q25, Q35, Q36, Q37, Q39).

## 1. Sample, frozen before the first model call

- Sources: `tasks/pilot60/INSTANCES.jsonl` (2,098 rows) with parent metadata from
  `tasks/master_bank/MASTER_BANK.jsonl` (1,073 parents), the premise audit
  (`PREMISE_AUDIT_2026-10-31.jsonl`) and the read grade (`TRUTH_PANEL_READ_2026-10-31.jsonl`).
- Seed `20261040`, n=40. The list was frozen at **2026-10-31T08:34:12Z**;
  `questions.jsonl` sha256 **`e9cadd2272d5a750de4a92babd234c6d88536b698e311a503c220d976b1edf24`**
  (`manifest.json`). The first model call was at **08:38:32Z**, after the freeze; the graded 40-row
  run was **08:53:19–08:58:46Z**. No row was added, removed or rewritten after the freeze
  (`select_questions --check` still passes the same sha).
- Selection rules, in order, with counts (2,098 instances; every row has its reason in
  `exclusions.jsonl`):

| rule | excluded |
|---|---:|
| ILL_POSED in the read grade | 38 |
| premise audit verdict `false` | 196 |
| no entity | 6 |
| more than one entity | 415 |
| entity has no ISIN | 46 |
| entity ISIN not one of the 60 pilot names | 69 |
| question names a company other than the row entity | 123 |
| renamed parent retargeted to an unrelated pilot name | 56 |
| question does not name the row entity | 38 |
| **eligible** | **1,111** |

The 6 no-entity rows are macro/theme asks; the five typed tools bind to one company, so they are
outside this test's tool surface. They are recorded in `exclusions.jsonl`, not silently dropped.
The 415 multi-entity rows are excluded for the same binding reason and because their text names
companies other than the row entity.

- Stratification: primary family quotas (largest remainder, floor 1), one row per parent, at most two
  rows per company, and at least 10 judgement/study rows. Final: 15 families (1:9, 2:8, 3:4, 9:4,
  6:2, 12:2, 14:2, 17:2, and one each of 4, 10, 11, 15, 16, 19, 20), **11 judgement/study rows**
  (`answer_kind=explanation` or ripple200), 17 variations300, 17 reddit200, 6 open300. As-of dates:
  23 at 2026-10-19, 6 at 2026-09-24, and 11 spread from 2024-06-04 to 2026-10-27.
- The `renamed_parent_mismatch` rule was added before freezing because three candidates kept the
  parent's old company name (`CENTURYTEX (now VIKASWSP)`, `SUVENPHAR (now ALKEM)`,
  `RUCHI (now VIKASWSP)`); the master bank's real successors are ABREL, COHANCE and PATANJALI.

## 2. The agent

- Model `beam-free`, same endpoint, key, stable `x-opencode-session`, retry rules and
  `cost_ledger.record_usage` as `tasks/arch_v4/reader_test/beam_client.py`. No other model, no paid
  model, $0.
- **Protocol deviation, recorded:** the first pass used a JSON-text tool protocol. On 14 of 40 rows
  the free tier returned only reasoning and an empty `content` (up to four attempts), so the run was
  stopped before grading. A one-call probe showed the same prompt produces a correct native
  `tool_calls` response when the tools are declared as OpenAI-style functions. The graded run uses
  **native typed tool calling** — the same model, endpoint, session and ledger, with the five tools as
  function schemas and a sixth `submit_answer` output function. This is the same client, not a
  different model.
- Tools, read-only, over the mounted pilot stores (`mode=ro&immutable=1`):
  `fact_query` (atom, entity, dims, period range, order, limit), `claim_search`, `chunk_search`
  (FTS over `chunks_v3_pilot.db`), `list_atoms`, `calculator`. Every SQL read adds
  `substr(known_at,1,10) <= as_of`; the wrapper, not the model, owns `as_of`. A tool argument that
  names a later date returns `as_of_refused` instead of rows. The model never passed a later date on
  the graded run (0 refusals), but the wrapper test proves it would.
- At most 12 data-tool calls per question; `submit_answer` is the output channel and does not count.
  The graded run used 133 data-tool calls over 40 questions (mean 3.33, maximum 6), so the cap was
  never binding.
- Every tool call/result is in `runs/tool_log.jsonl`; every question's full transcript is in
  `runs/transcripts/Qnn.json`; `runs/results.jsonl` has the answer, working, missing, call trace,
  usage and number check.
- Output: `answer`, short `working`, and `missing`; "not in data" is accepted as a typed negative.
- Number check: every numeric token in the answer is tested against the numbers in the tool results
  and calculator results. A percentage that equals 100x a calculator result is accepted as the same
  number with a unit (this is why Q20's 53.10% is supported); a rounded/mental number is not.
  Run-time and post-run checks are both in the artifacts; the post-run check (after the unit-aware
  fix) is the one used for grading.

## 3. Result and the fixed rule

| Verdict | Rows |
|---|---:|
| RIGHT | **7** |
| PARTIAL | **7** |
| WRONG | **10** |
| ILL_POSED | **11** |
| CORRECT_NOT_IN_DATA | **5** |
| **Total** | **40** |

- Denominator for the rule: rows not ILL_POSED and not CORRECT_NOT_IN_DATA = **24**.
- RIGHT = **7/24 = 29.17%**; Wilson 95% **14.91%–49.17%**.
- **KILL** (under 50%).
- Sensitivity: if the three least-certain RIGHTs (Q10, Q20, Q33) were disallowed, it is 4/24 = 16.7%.
  If every PARTIAL were generously counted as RIGHT (which the definitions do not allow), it would
  be 14/24 = 58.3%; each of the 7 PARTIALs misses an asked part, uses a nearby measure, or carries
  an unsupported number. The strict rule is the number above.
- The engine's read-grade result on the same rows is not better: the 3 rows that overlap the read
  panel (Q23, Q30, Q40) are all engine WRONG; this agent is WRONG on one and PARTIAL on two.

## 4. The 40 rows

Full reasons and every looked-up value are in `grades.jsonl`. `Cause` is the primary failure cause.

| # | mid | company | verdict | cause | reason |
|---:|---|---|---|---|---|
| 01 | MB0050#MI | ASHIANA | CORRECT_NOT_IN_DATA | data_gap | FY25 AR has no change-in-control disclosure; the only Clause 5A text is in the FY24 AR. |
| 02 | MB0106#MS | PRESTIGE | CORRECT_NOT_IN_DATA | data_gap | Only raw price.close is held; no split/dividend-adjusted atom. |
| 03 | MB0111#MS | EDELWEISS | WRONG | reasoning | Note 5 misread as "Debenture redemption reserve: NA"; standalone Note 5 is employee benefits (30.54/2.20/-2.40 Cr) and consolidated Note 5 is net profit margin (5.56%). Geographic split correctly absent. |
| 04 | MB0121#MI | JUBLINGREA | CORRECT_NOT_IN_DATA | data_gap | Latest public holding is Jun 2026 (53.79%); no Sep 2026 row. |
| 05 | MB0124#MI | KHADIM | RIGHT | none | 40.11% Sep 2026 public holding. |
| 06 | MB0175#MI | WPIL | WRONG | reasoning | Price shows -9.0% by 3 Feb 2025 and -40.6% by 14 Feb; the answer says the held data has no quantified impact. Rolling tariff-news correlation is not held. |
| 07 | MB0212#L | GRASIM | ILL_POSED | premise | GRASIM has no dairy segment; the "dairy peers" premise is false. |
| 08 | MB0244#MI | UFLEX | RIGHT | none | 44.58% Sep 2026 promoter holding. |
| 09 | MB0259#L | POWERGRID | ILL_POSED | premise | Segments are transmission/consultancy/telecom; no manufacturing facilities. |
| 10 | MB0274#MS | TEJASNET | RIGHT | none | 53.28% promoter; 181,410,000 shares; derived promoter count 96,655,248. |
| 11 | MB0280#MI | DDEVPLSTIK | RIGHT | none | 103,477,000 shares; 75.0% promoter. |
| 12 | MB0284#L | BOSCHLTD | CORRECT_NOT_IN_DATA | data_gap | No deck dated 2026-07-29; nearest is 2026-08-10. |
| 13 | MB0299#L | GRASIM | WRONG | reasoning | Returns a capex table, not the capacity-expansion timeline; mixes Q3FY26 1,058->1,137 KTPA with the Q4FY26 deck it cites (996->1,075), and omits ECH/CPVC pre-commissioning and Lyocell mid-2027. |
| 14 | MB0309#L | PIDILITIND | RIGHT | none | YTD high 1,620.7 on 2026-06-25 (also 29 June). |
| 15 | MB0315#L | BOSCHLTD | PARTIAL | data_gap | FY25 AR solar commissioning (~75%), BGSW lab 2HY2025 and ChiP plant are real, but there is no clean "newly commissioned facilities" statement; deck/concall absent. |
| 16 | MB0319#MS | EDELWEISS | ILL_POSED | premise | Financial-services group (agency/holding/unallocated); no manufacturing facilities. |
| 17 | MB0326#MI | WPIL | PARTIAL | data_gap | Margin profile 16-20%, Q2 18.87%, standalone 20.01%, H1 16.09% verified; no MOU in the call; full normalisation path omitted. |
| 18 | MB0347#MS | KALYANKJIL | ILL_POSED | premise | Jewellery retailer; no mobile-PLI/mobile segment. |
| 19 | MB0352#L | SUNPHARMA | ILL_POSED | premise | Pharma company with 40 sites; no 4.5 GW capacity. |
| 20 | MB0443#MS | SAIL | RIGHT | none | SAIL -20.02% and Nifty Metal -10.63% on 4 Jun 2024; 10.63/20.02 = 53.10%. |
| 21 | MB0530#MS | APLAPOLLO | ILL_POSED | premise | Steel-pipes maker; no Sanand plant/phase 1 in the held documents. |
| 22 | MB0565#L | SUNPHARMA | ILL_POSED | premise | ISRF JV belongs to Cochin Shipyard; no ISRF JV for SUNPHARMA. |
| 23 | MB0618#MS | KALYANKJIL | WRONG | reasoning | CEO is Sanjay Raghuraman; the held tables list him at 19.34/17.36M (FY25 AR) and 21.27M (FY24 AR). The answer used MD T.S. Kalyanaraman and said CEO pay was not disclosed. |
| 24 | MB0835#MS | HINDPETRO | WRONG | arithmetic | Expiry sessions Oct 1/8/15 average 50.97%, but ordinary sessions average 55.37% (answer says 54.56%): Oct 8 is double-counted and Oct 9 omitted. |
| 25 | MB0856#L | HINDALCO | WRONG | tool_gap | Daily/weekly prices are held; the agent has no chart/pattern tool and says the data cannot answer. |
| 26 | MB0886#MI | HEGAM | ILL_POSED | premise | Entity is HEG Ltd, not a newly listed HEG Advanced Materials; no prospectus or listing-day move; 2021-10-27 is the store's first date. |
| 27 | MB0917#L | HINDALCO | PARTIAL | data_gap | No order-inflow announcements; DII 24.23->19.95% and FII 32.10->35.60% are right, but no return comparison. |
| 28 | MB0967#L | POWERGRID | PARTIAL | data_gap | CWIP 50,419 Cr (Jun-26) and 29,603 Cr (Dec-24), depreciation 5.28% for 12 years then 1.1-1.3%; no capitalised interest or CWIP ratio. |
| 29 | MB0976#MS | INDHOTEL | ILL_POSED | premise | Hotel Services and Air/Institutional Catering segments; no BPC or fashion segment. |
| 30 | MB0978#MS | INDHOTEL | PARTIAL | data_gap | Real payback anecdotes (Taj Ganges 40% EBITDA in Q1; Ekta Nagar break-even in 100 days), but no per-store capex or maturity earnings; the 500-600 Cr routine-capex figure is not tool-backed. |
| 31 | MB0984#MS | ANANDRATHI | ILL_POSED | premise | Wealth manager, not a bank/NBFC; no NIM or loan growth. |
| 32 | MB0998#MS | KEC | CORRECT_NOT_IN_DATA | data_gap | No holdco-level split and no asset-monetisation repayment amount; only consolidated/standalone debt and net-debt/EBITDA ratios. |
| 33 | MB1002#MS | TATAELXSI | RIGHT | none | Nitin Pai (24 Apr 2026): "all our revenues and growth or lack of it is organic"; no acquisition/goodwill effect in the held data. |
| 34 | MB1017#MI | UFBL | ILL_POSED | premise | Restaurant/food hospitality, not an air-conditioner manufacturer. |
| 35 | MB1026#MS | TATAELXSI | WRONG | tool_gap | High 3,857.0 (2026-08-10), low 3,169.0 (2026-09-24) and daily volume are held; the answer says the volume series is truncated and gives up. |
| 36 | MB1035#MI | HINDOILEXP | WRONG | tool_gap | Daily closes are held; 50/200-day SMAs are computable, but the answer says only a 20-day series exists. |
| 37 | MB1053#MS | ANANDRATHI | WRONG | tool_gap | Earnings dates are in results/announcement chunks and price/volume are held; the answer says the dates/analysis are absent. |
| 38 | MB1055#MS | APLAPOLLO | PARTIAL | tool_gap | EPS 27.28->43.34 (+58.9%, mental; calculator 58.87) and no defence evidence, but Nifty is held and relative strength was not computed. |
| 39 | MB1060#MI | UNIVASTU | WRONG | tool_gap | ISIN INE562X01013 is in the pilot (blank symbol); the answer used the name, got "not a pilot symbol", and said not in data. |
| 40 | MB1070#MI | AURUM | PARTIAL | reasoning | 2026-09-22 (70.70%, 75,026, close 222.04) and 2026-09-24 (61.04%, 41,158, 220.22) are right, but the two sessions are not consecutive and the "two days" event is ambiguous. |

### RIGHT and PARTIAL: looked-up values

| qid | looked-up value (source) |
|---|---|
| Q05 | public holding 40.11% at 2026-09-30 (`hold.pct`, known 2026-10-16) |
| Q08 | promoter 44.58% at 2026-09-30 (`hold.pct`, known 2026-10-16) |
| Q10 | promoter 53.28% at 2026-09-30; total shares 181,410,000; 0.5328 x 181,410,000 = 96,655,248 (`hold.pct`, `price.shares_out`) |
| Q11 | shares 103,477,000; promoter 75.0% at 2026-09-30 (`price.shares_out`, `hold.pct`) |
| Q14 | high 1,620.7 on 2026-06-25 and 2026-06-29 (`price.high`) |
| Q20 | SAIL 166.35 -> 133.05 = -20.02%; Nifty Metal 10,048.55 -> 8,980.15 = -10.63%; 10.63/20.02 = 53.10% (`price.close`, `macro.index_close`) |
| Q33 | "all our revenues and growth or lack of it is organic" (Nitin Pai, concall 2026-04-24, chunk 94576); revenue FY25 3,729.05 Cr -> FY26 3,757.42 Cr; no goodwill atom |
| Q15 | AR p60/p174: Phase 2 group-captive solar commissioning ~75% green energy; BGSW lab expected 2HY2025; p148 ChiP Chennai plant |
| Q17 | margin profile 16-20%; Q2 18.87%; standalone 20.01%; H1 16.09%; no MOU in the 4/11 Nov 2025 call (`claim` 621981/621986/621991/621996) |
| Q27 | DII 24.23% (Sep-25) -> 19.95% (Jun-26); FII 32.10% -> 35.60%; close 886.70 / 956.60 / 941.80 / 900.45 (`hold.pct`, `price.close`) |
| Q28 | CWIP 50,419 Cr consolidated (30 Jun 2026), 29,603 Cr (31 Dec 2024); depreciation 5.28% for 12 years then ~1.1-1.3% over 23 years (chunks 51553, 48862, 36472) |
| Q30 | Taj Ganges new 100-room wing PBT-positive first quarter, 40% EBITDA margin (chunk 95562); Ekta Nagar break-even within 100 days (chunk 94215); FY26 capex > 1,000 Cr, ~650 Cr renovations (chunk 94824) |
| Q38 | EPS 27.28 (FY25) -> 43.34 (FY26) = +58.87%; Nifty 50 series is held (`macro.index_close`); no defence references |
| Q40 | 2026-09-22: delivery 70.70%, qty 75,026, close 222.04; 2026-09-24: 61.04%, 41,158, 220.22 (`price.delivery_pct/qty/close`) |

## 5. Failure causes

| cause | rows | what it covers |
|---|---:|---|
| premise | 11 | the instance generator's company substitution left another company's specific fact in the question (GRASIM dairy, POWERGRID manufacturing, EDELWEISS facilities, KALYANKJIL mobile-PLI, SUNPHARMA 4.5 GW, APLAPOLLO Sanand, SUNPHARMA ISRF, INDHOTEL BPC/fashion, ANANDRATHI NIM/loan, UFBL AC, HEGAM listing) |
| data_gap | 10 | no adjusted price atom; no Sep-2026 JUBLINGREA holding; no 2026-07-29 BOSCHLTD deck; no holdco split or monetisation repayment; no per-store capex; no capitalised interest; no MOU; no order-inflow announcements; no change-in-control in FY25 AR |
| tool_gap | 6 | no aggregation/order-by-value/count (Q35, Q36, Q37), no chart/pattern tool (Q25), blank-symbol entity resolution (Q39), no relative-strength helper (Q38); the model would have to page 50 rows at a time and compute outside the tool |
| reasoning | 5 | wrong Note 5 (Q03), ignored available price event (Q06), mixed deck vintages (Q13), wrong person/role (Q23), ambiguous event selection (Q40) |
| arithmetic | 1 | Q24 ordinary-session average (Oct 8 double-counted, Oct 9 omitted) |
| none | 7 | the seven RIGHT rows |

A number that failed the tool/calculator check was listed against its row: **7 rows flagged**, of
which **3 have a genuinely unsupported number** (Q23 has 111.7, 112.8 and 0.9; Q30 has 500; Q38 has
58.9) and 4 only restate a number from the question (Q17 "4", Q19 "4.5", Q36 "50/200", Q40 "60").
Q20's 53.10% is supported after the percent-unit rule (calculator 0.530969).

## 6. Time, tokens and the 2,681-row estimate

| Measure | Value |
|---|---:|
| Questions | 40 |
| Final answers | 40/40 (0 empty, 0 bad JSON) |
| Data-tool calls | 133 (mean 3.33, max 6; cap 12) |
| Model turns | 151 (mean 3.77) |
| Mean / median seconds per question | 8.16 / 7.74 (min 3.40, max 14.12) |
| Sum of per-question time | 326.4 s (5 min 26 s) |
| Input / output tokens | 789,400 / 22,937 |
| Mean per question | 19,735 input / 573 output |
| Cost | $0.00 (`beam-free`) |
| Estimate for 2,681 rows, same rate | **~6.1 h single-threaded**; 52.9M input / 1.54M output tokens |
| PIT breaches | **0** |
| `as_of_refused` tool results | 0 (the model never asked for a later date) |
| Tool errors | 3 (2 `bad_args`, 1 `unknown_entity`) |

The estimate is a straight extrapolation from this sample; the bank's 2,681 rows contain many more
long price series, so the tool-call count (not the model time) is likely to grow. A parallel run
would need the same stable-session and ledger discipline.

Per-question values (`total_secs`, `n_tool_calls`, `usage.prompt_tokens`, `usage.completion_tokens`;
the same fields are in `runs/results.jsonl`):

| qid | secs | tool calls | input tok | output tok |
|---|---:|---:|---:|---:|
| Q01 | 9.6 | 6 | 34,816 | 540 |
| Q02 | 3.5 | 1 | 4,473 | 193 |
| Q03 | 9.4 | 3 | 32,685 | 580 |
| Q04 | 5.4 | 2 | 10,850 | 377 |
| Q05 | 4.8 | 2 | 7,917 | 236 |
| Q06 | 8.1 | 3 | 14,496 | 482 |
| Q07 | 8.6 | 4 | 25,924 | 589 |
| Q08 | 4.8 | 2 | 8,130 | 238 |
| Q09 | 6.1 | 3 | 6,934 | 459 |
| Q10 | 10.5 | 4 | 22,671 | 693 |
| Q11 | 4.9 | 3 | 9,730 | 359 |
| Q12 | 14.1 | 6 | 44,965 | 862 |
| Q13 | 7.7 | 3 | 13,486 | 734 |
| Q14 | 7.4 | 3 | 17,675 | 580 |
| Q15 | 12.2 | 4 | 38,373 | 747 |
| Q16 | 7.8 | 4 | 21,958 | 440 |
| Q17 | 6.0 | 4 | 11,056 | 543 |
| Q18 | 5.5 | 2 | 7,544 | 520 |
| Q19 | 10.7 | 5 | 38,128 | 642 |
| Q20 | 6.1 | 2 | 7,928 | 405 |
| Q21 | 7.5 | 4 | 23,796 | 366 |
| Q22 | 7.5 | 4 | 19,566 | 299 |
| Q23 | 12.5 | 3 | 22,001 | 1,211 |
| Q24 | 14.0 | 5 | 19,918 | 1,748 |
| Q25 | 6.0 | 2 | 11,197 | 473 |
| Q26 | 8.0 | 4 | 19,386 | 441 |
| Q27 | 9.7 | 5 | 26,826 | 664 |
| Q28 | 9.2 | 3 | 21,702 | 722 |
| Q29 | 10.8 | 4 | 27,966 | 607 |
| Q30 | 9.3 | 4 | 28,135 | 730 |
| Q31 | 5.7 | 2 | 9,339 | 314 |
| Q32 | 10.1 | 4 | 25,752 | 552 |
| Q33 | 6.8 | 2 | 10,730 | 392 |
| Q34 | 12.3 | 5 | 51,295 | 619 |
| Q35 | 6.2 | 3 | 17,079 | 361 |
| Q36 | 6.6 | 2 | 8,279 | 475 |
| Q37 | 5.6 | 1 | 4,307 | 414 |
| Q38 | 11.5 | 5 | 28,920 | 723 |
| Q39 | 3.4 | 1 | 2,502 | 190 |
| Q40 | 10.2 | 4 | 30,965 | 1,417 |

## 7. Point-in-time checks

- The wrapper test `test_real_store_refuses_a_later_as_of_and_hides_later_rows` (Q02, as_of
  2026-09-30) asks for `as_of=2026-10-02`; the wrapper returns `as_of_refused`. It then queries
  `price.close` from 2026-10-01 to 2026-10-31 and gets **zero rows**; the 2026-09-29/30 rows are
  returned with `known_at <= 2026-09-30`.
- A synthetic test (`test_pit_wrapper_drops_a_later_row`, `test_pit_wrapper_refuses_a_later_as_of`)
  proves the same with a row known 2026-10-25 and an as_of of 2026-10-19.
- The 40 graded rows produced **0 PIT breaches**: every returned row had `known_at` on or before the
  question's as_of. No tool result came from a later document; the model never requested one.

## 8. Comparison with the engine on the same 40 rows

The v4 gate results file has all 40 mids. Contract grades: **4 ANSWERED (10%)**, 29 PARTIAL,
3 BLOCKED_SCHEMA, 2 BLOCKED_TOOL, 2 NOT_IN_DATA.

- The 4 engine-ANSWERED rows are Q05 (40.1%), Q08 (44.6%), Q10 (53.28%) and Q11 (75.0%). The agent
  is RIGHT on all four and gives the same values (Q08 uses 44.58% vs the engine's rounded 44.6%).
- The 3 rows that overlap the 127-row read panel are Q23, Q30 and Q40; the read grade has all three
  engine answers as **WRONG**. On those, this agent is **WRONG 1 (Q23), PARTIAL 2 (Q30, Q40)**.
- On the other 36 rows (all except the 4 ANSWERED), the engine has no contract answer: 29
  PARTIAL, 3 BLOCKED_SCHEMA, 2 BLOCKED_TOOL, 2 NOT_IN_DATA. Three of those are the read-panel rows
  above (Q23, Q30, Q40); on the remaining 33 the agent answered all 33, with 3 RIGHT (Q14, Q20, Q33)
  and the rest PARTIAL/WRONG/ILL_POSED. The engine's PARTIALs are mostly a scalar near the ask (a
  close, a return, a segment) with the asked measure missing — the same `MEASURE_NOT_ANSWERED`
  pattern the read grade found in 66 of 127 rows.
- Read against the fixed rule, the engine's 4/40 contract answers are 4/40 = 10% RIGHT (if all four
  values are accepted), below the agent's 7/40 and below the agent's 7/24 on the rule denominator.
  Neither comes near the 95% gate.

## 9. What this says for a design proposal (not made, because the rule is a kill)

If the kill is revisited after the bank and tools change, the evidence points at:

1. **Premise repair first.** 11/40 are ill-posed because the instance generator kept the parent
   company's fact. No reader or analyst can answer them. This is the same defect the read grade
   found in 33% of answered rows.
2. **A query surface that can sort/aggregate.** Q35-Q37 failed because the model can fetch at most
   50 rows per call and cannot compute a max/min/average/count over a series. `fact_query` needs
   `order_by=value desc`, `aggregate=max|min|mean|count`, or a `window`/`top_n` argument.
3. **A chart/pattern primitive** for weekly OHLC and 50/200-day SMA by period; the current
   `price.sma` has no period dimension (Q35, Q36).
4. **Entity resolution by ISIN even when the pilot symbol is blank** (Q39); and a `list_atoms`
   result that is not truncated (the first native pass hid `price.*` atoms from `list_atoms`).
5. **Number discipline:** the model still did mental arithmetic on Q23/Q30/Q38; keep the calculator
   mandatory and reject a rounded/mental number rather than accepting it.

## 10. Acceptance checks and reproduce

```bash
python -m pytest tasks/arch_v4/analyst_test -q
# 11 passed (includes the later-date refusal and the unsupported-number flag)

python -m tasks.arch_v4.analyst_test.select_questions --check
# frozen OK: 40 questions sha256=e9cadd2272d5a750de4a92babd234c6d88536b698e311a503c220d976b1edf24

python -m tasks.arch_v4.analyst_test.run_agent --force
# 40/40 final, 08:53:19–08:58:46Z

python -m tasks.arch_v4.analyst_test.recheck_numbers
# rows=40 flagged=7 unsupported=3

python -m tasks.arch_v4.analyst_test.make_grades
# RIGHT 7, PARTIAL 7, WRONG 10, ILL_POSED 11, CNID 5; 7/24 = 29.17%, Wilson [0.1491, 0.4917]

python -m tasks.arch_v4.analyst_test.report_stats
# 133 tool calls, 151 model turns, 326.4 s, 789,400 / 22,937 tokens
```

## 11. Limits and caveats

- One grader, 40 rows; the Wilson interval is wide. The point estimate and the upper bound are both
  below 50%, but the sample is small.
- The 11 ILL_POSED rows are excluded from the kill denominator; they are a sample defect, not an
  agent failure. The read grade uses the same rule. If the 11 were counted as WRONG, the rate would
  be 7/35 = 20%.
- The model/API returned empty content on 14/40 under the JSON-text protocol. That is a real
  free-tier behaviour, not a data result; the graded run switched to native tool calls after the
  probe. The first JSON-text pilot answers are not graded.
- The tool wrapper was fixed during the pilot (doc_types JSON strings, missing query default,
  `limit` as `5.0`, `list_atoms` truncation). The graded run is the final wrapper; the fixes are in
  the tests.
- One name-check miss: Q26's "HEG Advanced Materials" matched the "HEG" alias of HEG Ltd
  (INE545A01024), so it slipped the string-based sampling filter. It is graded ILL_POSED; no row was
  swapped after the freeze.
- The `looked_up` values were read with SQL against the mounted pilot stores, never from the agent's
  tool log. The stores are the 2026-10-19 snapshot plus rows to 2026-10-28 in `text.passage`.
- The engine comparison uses the 40 mids in `GATE_RESULTS_instances_strict.jsonl`; the 3 read-panel
  verdicts come from `TRUTH_PANEL_READ_2026-10-31.jsonl`.

## 12. Files

- `tasks/arch_v4/analyst_test/questions.jsonl` — frozen 40 rows; `manifest.json` — sha256, seed,
  timestamps, exclusions; `exclusions.jsonl` — one reason per instance.
- `tasks/arch_v4/analyst_test/__init__.py`, `tools.py`, `agent.py`, `beam.py`, `number_check.py`,
  `run_agent.py`, `select_questions.py`, `recheck_numbers.py`, `report_stats.py`, `make_grades.py`,
  `test_analyst.py`.
- `tasks/arch_v4/analyst_test/runs/results.jsonl` — answers, traces, usage, number check;
  `tool_log.jsonl` — every call/result; `transcripts/` — full per-question transcripts;
  `number_recheck.jsonl`, `results_rechecked.jsonl`, `stats.json`.
- `tasks/arch_v4/analyst_test/grades.jsonl` — 40 hand verdicts with looked-up values;
  `summary.json` — counts, rule, Wilson.
- `tasks/arch_v4/ANALYST_AGENT_TEST_2026-10-31.md` — this report.
