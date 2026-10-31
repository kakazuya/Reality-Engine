# Quote-verified reader test — 40 document questions (31 Oct 2026)

**Verdict: kill the free-model reader under the rule fixed before the run.** 13 of 40 answers are
RIGHT (32.5%, Wilson 95% 20.1%–48.0%). The rule was: under 50% RIGHT means kill the model
reader and fall back to retrieval with quotes only. The upper bound is below 50%, so the sample
error does not reach the threshold. Three of the five mandated rows are RIGHT.

The test is not mainly a retrieval failure. The right passage was in the ten excerpts for most
rows where the bank's gold is in the corpus (23/29 golds the locator found); among
the 14 rows graded PARTIAL or WRONG, reading and number discipline failed
13 times against 1 retrieval failure.
The corpus itself is incomplete: 10 of the 13 CORRECT_NOT_STATED rows are
data gaps — the announcement, transcript or comparison date is not in the held corpus at the
question's `as_of` — not reader errors.

## 1. What was measured

### Sample, fixed before any model call

- Source: `tasks/master_bank/MASTER_BANK.jsonl` (1,073 parents) and
  `tasks/pilot60/INSTANCES.jsonl` (2,098 instances).
- Pilot definition: a company with at least one chunk in `pilot/pilot60/chunks_v3_pilot.db`
  (87 ISINs — the store is wider than the 60-name pilot universe). The brief's 108,078 chunks
  are all present.
- Eligibility rule: single-stock parents that name their company, are in the pilot corpus,
  and ask what the company said/disclosed in its own documents. Analytical, price-move,
  shareholding and valuation asks were excluded. Every parent row has its rule-level reason
  in `reader_test/eligibility_parents.jsonl` (1,073 rows; 45 eligible, 1,028 excluded with a
  written reason).
- Seed `20261031`; five mandated parents added first, then 35 in seed order from the eligible
  pool. The list was frozen at **2026-10-31T00:36:32Z**:
  `questions.jsonl` sha256 `5801011c4cdce973478b6338fbdb76b1f7ccc494cb3f130684e01e8b6f772d51`. No row was added, removed or
  rewritten after that point. The first Beam call (a one-line connectivity probe) was at
  **2026-10-31T00:37:21Z**, after the freeze; the 40-question run followed. The mandatory parents
  are MB0337, MB0345, MB0355, MB0415 and MB0540; MB0415 is a market-wide list question and is
  bound to SAIL because that is the only named pilot company the reader can query.

### Retrieval

- Filters first, in SQL: `isin = company`, `doc_type` in the question's evidence classes,
  `known_at <= as_of` (the as_of day is inclusive to 23:59:59), quality A/B, char length 80–6,000.
- FTS5 over the **body only** (the header repeats the company name and produces letterheads),
  with a strict AND tier and a broader OR tier over question terms, generic synonyms, quoted
  phrases, collocations and numbers.
- Local rerank: term coverage, phrase hits, numbers, date proximity, recency, management/opening
  remarks, and a penalty for cover letters (`Ref.: Co.Secy`, `Registered Office`, `CIN`, stock
  exchange addresses). Ten chunks go to the model; long chunks show the densest 1,800-character
  window around the query terms, not their first 1,500 characters.
- No paid embeddings; `chunk_vec_ref` is empty in this store anyway.

### Reader and checks

- `beam-free`, `reasoning_effort=low`, `max_tokens=3000`, stable `x-opencode-session` per call,
  every 200 response written through `cost_ledger.record_usage` (caller `v4_reader_test`).
- The model returns `{answer, quote, chunk_id, missing}` or `not stated`.
- A quote is accepted only if the normalised text is a substring of a supplied chunk (`exact`),
  or the same words in the same order survive punctuation folding (`words`). Every number in the
  answer must be in the quote or already in the question. Page/note citations and fiscal-period
  labels are not treated as company numbers. Retrieval is closed before the model is called:
  no new chunk can appear to support a quote.
- Grading was by hand, one row at a time, against the question, the bank rubric/gold and the
  retrieved chunk: RIGHT, PARTIAL, WRONG, CORRECT_NOT_STATED, plus the failure cause.
  A fabricated quote or a central unsupported number is WRONG. A "not stated" answer that carries
  a supporting quote (Q30, Q32) is graded on its content, not on the formatting contradiction.
  CORRECT_NOT_STATED means the held documents do not state the asked fact (data gap), the ask is
  not answerable from the source, or the premise is out of the pilot scope.

## 2. The 40 rows

| # | mid | company | question | verdict | cause | quote | why |
|---:|---|---|---|---|---|---|---|
| 01 | MB0337 | APLAPOLLO | APLAPOLLO 8 MT by FY28 — slipped or on track? | **RIGHT** | none | yes | Exact bank gold; quote verbatim. |
| 02 | MB0345 | HINDALCO | Hindalco's renewable-energy capacity: how much does it have,… | **WRONG** | reading | yes | Quote verifies 470 MW but the answer adds 53 MW, 30 MW and 523 MW that are not in the quote, and misreads hydro as 'idl… |
| 03 | MB0355 | SAIL | SAIL ne Q1FY27 mein capital repairs aage khiske kyun, aur out… | **RIGHT** | none | yes | Why (repairs advanced at IISCO/Durgapur/Bokaro) and recovery (Q2-Q4 volumes higher) both answered from a verbatim quote. |
| 04 | MB0415 | SAIL | Which companies disclosed a plant shutdown or force majeure i… | **CORRECT_NOT_STATED** | scope | no | The pilot corpus has no SAIL shutdown/force-majeure disclosure (one rumour-verification announcement only); the capital… |
| 05 | MB0540 | SAIL | SAIL advanced capital repairs into Q1 FY27 to free up later q… | **RIGHT** | none | yes | Correctly separates the Q1 promise from realised later-quarter output; no later-quarter results were known at 2026-10-0… |
| 06 | MB0557 | POLYCAB | Is Polycab's capex funded by debt or internal accruals, and h… | **RIGHT** | none | yes | Internal-accrual funding stated verbatim. |
| 07 | MB0437 | POLICYBZR | PB Fintech fell 36% on 24 September 2026. What was scheduled… | **CORRECT_NOT_STATED** | data_gap | no | No POLICYBZR announcement after 2026-08-13 in the corpus; the 24/27 Sep 2026 filings and the price move are absent. |
| 08 | MB0045 | JSWSTEEL | JSW Steel (NSE: JSWSTEEL) ke latest annual report mein owners… | **RIGHT** | none | yes | FY25 control judgement, pages 230/290 and the disclosure all given; page citations are provenance, not company numbers. |
| 09 | MB0338 | TITAGARH | Titagarh Rail Systems is 'ready to ramp up' wagon output. To… | **RIGHT** | none | yes | 1,200 wagons/month and the sustainable-demand condition both quoted. |
| 10 | MB0385 | HDFCBANK | What were HDFC Bank's key audit matters in its latest annual… | **PARTIAL** | reading | yes | Gives two of the three KAMs in the retrieved passage (IT program development, life-insurance revenue timing) but omits… |
| 11 | MB0393 | KAYNES | Kaynes Technology filed a 'Change in Management' on 13 May 20… | **CORRECT_NOT_STATED** | data_gap | no | No 13 May 2026 Change in Management announcement in the corpus (the 13 May document is the investor deck). |
| 12 | MB0347 | DIXON | Dixon's operating margin compressed because the mobile-PLI be… | **RIGHT** | none | yes | Next-fiscal restoration ('27-'28) and the three drivers quoted. |
| 13 | MB0526 | BEL | BEL guided 15% revenue growth for FY27. What did Q1 FY27 actu… | **PARTIAL** | retrieval | yes | 15% guidance and confidence are right, but Q1 FY27 actual growth (20%) is in chunk 95675, which was not among the ten e… |
| 14 | MB0360 | BEL | BEL ne FY27 ke liye 15% growth bola tha — kaunsa half-year us… | **CORRECT_NOT_STATED** | ask_mismatch | no | 15% guidance is in the call, but no half-year skew is stated; the question's specific ask has no held answer. |
| 15 | MB0380 | MANKIND | Mankind ki subsidiary mein auditor resignation kab hui, aur k… | **CORRECT_NOT_STATED** | data_gap | no | No 28 Sep 2026 auditor-resignation filing for Bharat Serums in the corpus. |
| 16 | MB0351 | POLYCAB | Polycab has started BharatNet execution. Over how many years… | **RIGHT** | none | yes | Three-year BharatNet execution and the March start both quoted. |
| 17 | MB0439 | TRENT | Trent fell 14.77% on 7 April 2025. Was there a company disclo… | **CORRECT_NOT_STATED** | data_gap | no | Only Trent decks are held for Apr 2025; the 5 Apr 2025 pre-open update is absent. |
| 18 | MB0447 | KEI | KEI rose 9.49% on 4 August 2026 after results filed at 20:52… | **CORRECT_NOT_STATED** | data_gap | no | The Q1 FY27 concall (chunk 96033) states operating margin 12.43% but is known 2026-08-10, after this question's 2026-08… |
| 19 | MB0377 | TATASTEEL | Tata Steel's Q1 FY27 filing: did it carry an audit qualificat… | **WRONG** | reading | yes | Answer says 'not stated' while quoting the annual report's 'no qualification' sentence: self-contradictory, and the quo… |
| 20 | MB0535 | ULTRACEMCO | UltraTech's volume growth and capacity additions: did the FY2… | **WRONG** | reading | no | Q1 FY27 call (chunk 95489, in the ten excerpts) states 8.7 MT commissioned and 200.1 MT domestic capacity, 212.7 MT by… |
| 21 | MB0072 | CGPOWER | What did CG Power and Industrial Solutions (NSE: CGPOWER)'s m… | **CORRECT_NOT_STATED** | data_gap | no | Only the 12 May 2025 cover letter is held; the call transcript body is absent (one chunk). |
| 22 | MB0252 | KPRMILL | How many manufacturing facilities does K.P.R. Mill (NSE: KPRM… | **PARTIAL** | reading | yes | 12 facilities is right; the answer says locations are not stated although the deck lists business/plant detail. Count w… |
| 23 | MB0386 | SUZLON | Suzlon's latest results: what did the auditor's declaration s… | **WRONG** | reading | no | Quote is a paraphrase, not verbatim ('NCLT-approved' vs the report's wording), and it comes from the FY26 annual report… |
| 24 | MB0625 | SUZLON | How much did Suzlon pay its statutory auditor last year? | **RIGHT** | none | yes | FY26 consolidated statutory-auditor fee of Rs 1.48 crore quoted. |
| 25 | MB0341 | RVNL | RVNL's BharatNet work: what execution timeline did management… | **PARTIAL** | reading | yes | Three-year implementation timeline right; the same chunk says the second part is 10 years of maintenance, which the ans… |
| 26 | MB0352 | SUZLON | Suzlon says 4.5 GW of manufacturing capacity is fully operati… | **PARTIAL** | reading | yes | Correctly says conversion timing is not stated, but the gates quoted are industry-wide (4.2 GW, transmission/land), not… |
| 27 | MB0343 | BEL | BEL ka QRSAM order kis approval ka wait kar raha hai, aur kab… | **RIGHT** | none | yes | CCS approval and 'maximum by September' both quoted. |
| 28 | MB0618 | DIXON | What is Dixon's CEO paid, and how has that changed in three y… | **PARTIAL** | reading | yes | FY26 pay (Rs 703 lakh incl. Rs 295 lakh commission) right; the three-year change is not stated and no prior-year figure… |
| 29 | MB0324 | HINDPETRO | HINDPETRO mou margin path call 2026-07-29 | **CORRECT_NOT_STATED** | data_gap | no | Only the 29 Jul 2026 cover letter is held; the call transcript body is absent (one chunk). |
| 30 | MB0531 | POLYCAB | Polycab ne Q1FY27 mein 3.2 billion capex kiya — annual plan s… | **CORRECT_NOT_STATED** | data_gap | yes | Rs 3.2 bn Q1 capex is stated, but no annual plan is held, so ahead/behind cannot be answered. The answer string is 'not… |
| 31 | MB0349 | ULTRACEMCO | UltraTech says cement demand for the country grew about 4% in… | **CORRECT_NOT_STATED** | ask_mismatch | no | The 4% demand sentence exists in chunk 90704 but gives no reason the market is not stronger; the asked reason is not st… |
| 32 | MB0530 | KEI | KEI's Sanand phase 1 was late by about six months and commiss… | **CORRECT_NOT_STATED** | data_gap | yes | Sanand phase 1 was commissioned Dec 2025 after a ~6-month delay; no revised target date is stated, so 'did it meet its… |
| 33 | MB0544 | BEL | BEL is waiting for CCS approval on QRSAM. Is that order alrea… | **PARTIAL** | reading | yes | QRSAM is not in the order book and the Rs 55,000 cr pipeline / Rs 30,000 cr QRSAM split is quoted; the cover effect is… |
| 34 | MB0332 | DIXON | Dixon's Vivo joint venture: from which quarter does managemen… | **RIGHT** | none | yes | Exact bank gold; Q3 of the current fiscal quoted. |
| 35 | MB0348 | KEI | KEI's operating margin improved in FY26. By how much, and wha… | **PARTIAL** | reading | yes | 10.46% vs 10.18% quoted correctly; the second ask (what it says about the cable pricing environment) is left unanswered. |
| 36 | MB0331 | KEI | KEI Industries' first phase at Sanand: what month did it actu… | **RIGHT** | none | yes | December 2025 commissioning and ~6-month delay both quoted. |
| 37 | MB0340 | NTPC | NTPC has over 33 GW under construction. What is the coal/hydr… | **RIGHT** | none | yes | 33 GW split (16.5 coal / 1.9 hydro / 15 renewable) quoted; coal correctly named largest. |
| 38 | MB0395 | TRUALT | TruAlt ke promoter ne kab pledge banaya, aur kitne shares ka?… | **PARTIAL** | reading | yes | Answers the 2023 initial pledge (26% of shares) from a Nov 2025 call, not the latest Sep 2026 pledge; the exact share c… |
| 39 | MB0622 | TRUALT | How many shares did TruAlt's promoter actually pledge in Sept… | **CORRECT_NOT_STATED** | data_gap | no | No Sep 2026 pledge announcement is held for TruAlt (latest announcements Aug/Oct 2026); the share count is absent. |
| 40 | MB0344 | ULTRACEMCO | UltraTech's capacity is 184 million tonnes including India Ce… | **PARTIAL** | reading | yes | 184 -> 212 MT target right; the same chunk states a 3-year delivery window, which the answer wrongly calls not stated. |

### Counts

| Verdict | Rows |
|---|---:|
| RIGHT | 13 |
| PARTIAL | 10 |
| WRONG | 4 |
| CORRECT_NOT_STATED | 13 |
| **Total** | **40** |

| Failure cause | Rows | What it means |
|---|---:|---|
| none | 13 | RIGHT |
| reading | 13 | the needed passage was in the ten excerpts (or the answer was in the quote) and the model still missed, misread or broke the quote/number rule |
| retrieval | 1 | the passage is in the corpus but did not reach the ten excerpts |
| data_gap | 10 | the document, comparison date/plan or transcript is not in the held corpus |
| ask_mismatch | 2 | the document states the premise but not the asked fact (no half-year skew; no reason for weak demand) |
| scope | 1 | market-wide premise, SAIL-only binding |

### Quote discipline

| Result of the fixed checks | Rows |
|---|---:|
| verified (quote verbatim, every new number in the quote or the question) | 23 |
| not stated (no quote) | 12 |
| rejected contradiction ("not stated" plus a quote) | 3 |
| rejected number (a new number outside the quote) | 1 |
| rejected quote (not verbatim) | 1 |

2 WRONG answers carried a real quote (Q02, Q19); 12 non-RIGHT answers in
total carried a verbatim quote (the two WRONG plus ten PARTIAL). Q23 was WRONG with a paraphrased
quote and is not in that count. This is the risk the Gate 95 review named: a wrong reading can
still carry a real quote.

Sensitivity, so the kill is not an artefact of counting data gaps against the model:

- All 40: 13/40 = 32.5% RIGHT.
- Drop the 10 pure data-gap rows: 13/30 = 43.3% RIGHT.
- Drop all 13 rows that are CORRECT_NOT_STATED: 13/27 = 48.1% RIGHT.

Even the most generous cut is below 50%. The data-gap cut (43.3%) is the fairest reading of "could a
reader answer the held documents"; it still fails the fixed rule.

## 3. What failed

### Reading failures (13)

These are the rows where the evidence was available and the model did not use it correctly.

- **Numbers outside the quote (Q02).** It quoted 470 MW correctly, then added 53 MW, 30 MW and
  523 MW from another part of the same chunk; the quote did not carry them. The rule rejects the
  answer.
- **Self-contradiction (Q19).** It answered "not stated" while quoting the annual report's "does
  not contain any qualification" sentence, and the quote was from the AR, not the Q1 filing.
- **Evidence in the excerpts ignored (Q20).** Chunk 95489 was among the ten excerpts and states
  8.7 MT commissioned, 200.1 MT domestic capacity and 212.7 MT by FY27; the answer said not stated.
- **Wrong document/paraphrase (Q23).** The auditor quote came from the FY26 annual report and was
  not verbatim ("NCLT-approved" for the report's wording), while the question asked about the Q1
  results.
- **Multi-part drop (Q25, Q33, Q40).** The timeline/target was right, but the same chunk carried
  the second part (10 years of maintenance; the cover effect; the 3-year delivery window) and the
  answer called it not stated.
- **Partial extraction (Q10, Q22, Q28, Q35, Q38).** Two of three KAMs; a facility count without
  locations; one year of CEO pay without the three-year change; margin numbers without the pricing
  read; a 2023 pledge instead of the September 2026 one.
- **Gates not tied to the company (Q26).** The answer said Suzlon's 4.5 GW conversion timing was
  not stated but used industry-wide commissioning and transmission/land constraints as the gate,
  not a company-specific statement.

The pattern is consistent: the model can copy a sentence, but it does not reliably (a) keep every
number inside the quote, (b) notice a second asked part in the same passage, or (c) refuse to
answer when the quote only covers the premise.

### Retrieval failures (1)

- **Q13, BEL Q1 FY27 actual growth.** Chunk 95675 says "you've done 20% in the first quarter";
  it was rank 11 and did not reach the ten excerpts. The answer correctly gave the 15% guidance
  and confidence, then said the actual was not stated.

This is a date/period-ranking miss, not a vocabulary miss. A date-aware query (the named results
date ± a few days) would probably fix this class.

**PIT check on Q18.** The Q1 FY27 KEI concall (chunk 96033) states an operating margin of 12.43%,
but it is first known on 2026-08-10; Q18's as_of is 2026-08-04. That is a future document and must
not be used. The 3 Aug results filing does not state an operating margin, so "not stated" is the
correct answer here. A retriever that pulled the concall would have leaked the future.

### Data gaps (10) — the reader is right to say "not stated"

The pilot chunk store does not hold the document, or the comparison the question needs, for
these rows:

- **Q07** POLICYBZR: no announcement after 2026-08-13; the 24/27 Sep 2026 crash and clarification
  are missing.
- **Q11** KAYNES: no 13 May 2026 Change in Management announcement (the 13 May document is the
  investor deck).
- **Q15** MANKIND: no 28 Sep 2026 auditor-resignation filing for Bharat Serums.
- **Q17** TRENT: only decks for Apr 2025; the 5 Apr 2025 pre-open update is missing.
- **Q18** KEI: the Q1 FY27 operating margin is stated in the 10 Aug 2026 concall, which is after
  the 4 Aug 2026 as_of; the 3 Aug results filing does not state it.
- **Q21** CGPOWER: the 12 May 2025 "transcript" document is a single cover-letter chunk; the call
  body is missing.
- **Q29** HINDPETRO: the 29 Jul 2026 "transcript" is also a single cover-letter chunk.
- **Q30** POLYCAB: Q1 capex is stated (Rs 3.2 bn) but no annual plan is held, so ahead/behind
  cannot be answered.
- **Q32** KEI: Sanand phase 1 was commissioned Dec 2025 after a ~6-month delay, but no revised
  target date is held.
- **Q39** TRUALT: the Sep 2026 pledge announcement is not in the store (latest announcements are
  Aug/Oct 2026).

The two cover-letter-only transcripts and the missing announcement batches are ingestion gaps, not
reader errors. They are also why a quote-only fallback is honest: it can say "no held document
states this" without inventing prose.

### Ill-posed or out-of-scope (3)

- **Q04** MB0415 asks which companies disclosed a shutdown/force majeure. The bank's gold maps
  SAIL's advanced capital repairs to this question, but the SAIL passage never calls it a shutdown
  or force majeure, and the other named companies are outside the pilot binding. "Not stated" is
  the right answer for the held corpus.
- **Q14** BEL: the 15% guidance is in the call, but no half-year skew is stated; the question asks
  for the skew.
- **Q31** ULTRACEMCO: the 4% demand sentence is in chunk 90704, but management gives no reason the
  market is not stronger. The ask has no held answer.

## 4. Retrieval: what worked and what did not

| Tried | Result |
|---|---|
| Naive OR over the question's words, header+body | Returned letterheads and cover letters ("Ref.: Co.Secy", "Registered Office", "CIN", "Phiroze Jeejeebhoy"). Not usable. |
| Body-only FTS, entity + doc_type + `known_at` filters in SQL | Removed the company-name/letterhead match and the PIT leak. This is the base that worked. |
| Strict AND tier + broad OR tier, then local rerank | AND found the exact passages on specific asks; OR supplied recall when the wording differed. Rerank on term coverage/phrases/numbers was needed to keep the AND results on top. |
| Cover-letter and paragraph/unknown-speaker penalty | Pushed "Our Ref"/"By portal" chunks below Q&A and opening remarks. This was the single largest ranking fix. |
| Recency + named-date proximity | Helped current guidance (BEL, Suzlon, UltraTech) and hurt old-document questions (a 2024 call can outrank a 2025 answer without it). |
| Unit and synonym expansion ("MT" → million tonne capacity, "margin" → operating margin, "CCS" for approval) | Needed for the terse/Hinglish asks; it made the gold retrievable for APLAPOLLO and SAIL. |
| Focused 1,800-char window inside a long chunk | The pilot chunks run to 5,000 chars; the first 1,500 chars often stopped before the answer. This changed several not-stated rows into answered ones (Q25, Q34). |
| All-five-types widening | Recall rose, but the hinted type can be crowded out (Q13's BEL concall was rank 11). A hard type hint plus a date window is the next thing to try, not more types. |

The gold locator is not perfect: it found 29 of the 40 bank golds and placed 23 of those 29 in the
top ten. Some of its misses are genuinely absent quotes; some are short structured golds (a filing
title plus timestamp) that token overlap cannot isolate. Treat the 23/29 as a retrieval indicator,
not an accuracy number.

## 5. Time, Beam calls, errors

| Measure | Final pass |
|---|---:|
| Questions | 40 |
| Beam calls | 40 |
| Beam errors / non-200 after retries | 0 |
| Mean seconds per question | 10.26 s |
| Median seconds per question | 9.39 s |
| Mean retrieval seconds | 5.39 s |
| Mean Beam seconds | 2.97 s |
| Sum of per-question times | 6 min 50 s |
| Input / output tokens | 202,538 / 15,017 |
| Cost | $0.00 (`beam-free`) |

The ledger has 80 entries for this caller: the Q03 smoke call, the first full pass (39 calls,
because Q03 resumed from the smoke call) and the final pass (40 calls). 388,054 input and 28,720
output tokens in total, all at $0.

## 6. The five mandated rows

| Row | Parent | Verdict | Note |
|---|---|---|---|
| Q01 | MB0337 | RIGHT | APLAPOLLO 8 MT by FY28, exact gold quote. |
| Q02 | MB0345 | WRONG | Hindalco 470 MW right, but it added 53/30/523 MW outside the quote and dropped the cost ask. |
| Q03 | MB0355 | RIGHT | SAIL repairs at IISCO/Durgapur/Bokaro and Q2–Q4 recovery, quoted. |
| Q04 | MB0415 | CORRECT_NOT_STATED | No SAIL shutdown/force-majeure disclosure; market-wide scope not answerable. |
| Q05 | MB0540 | RIGHT | Correctly separates the Q1 promise from the later-quarter output, which was not yet reported at 2026-10-07. |

## 7. Recommendation

**Kill the model reader for now. Fall back to retrieval with quotes only.**

- Return the top 3–5 passages with company, document type, filing date, page and a highlighted
  match. Do not generate an answer, a summary or a number. The 23/29 gold-in-top-ten result says
  this will put usable evidence in front of a human or a later deterministic extractor.
- Keep the SQL filters, body-only FTS, AND/OR tiers, cover-letter penalty and focused windows. Add
  a date-aware query for results-day questions and a doc-type hint that is not crowded out by the
  other four types.
- The "not stated" state must be a search result, not a model opinion: run the broad search across
  all held types and report what was checked. 10 of this run's 13 not-stated rows are
  missing documents, not missing reasoning.
- If a model reader is revisited, it needs: quote-first output with a parser-owned number field,
  a checklist for every asked part, a refusal rule when any part lacks a quote, and a hand audit
  each run. On this sample the free model is not close to that. Shivam's rule that the LLM never
  sets a number remains the right boundary; this test says the free reader is not yet safe enough
  to extend the model's role.

**What would change the answer:** a corpus with the missing announcement/transcript bodies, a
date-aware retriever, and a reader that is scored on multi-part completeness. Re-run on a fresh
seed after those, not on this list.

## 8. Caveats

- One grader, 40 rows; the Wilson interval is wide. The fixed rule is about the point estimate and
  the interval stays below 50%, but the sensitivity cuts (43.3% and 48.1%) show how much the
  corpus gaps matter.
- The gold locator is a token-overlap heuristic. It cannot isolate very short structured golds and
  it sometimes picks the question sentence instead of the answer sentence. The verdicts were made
  by hand against the retrieved chunk, not by the locator.
- The pilot store is not the live DB: 87 ISINs, 2,488 documents, 108,078 chunks, no announcement
  batches after mid-Aug 2026 for some names, and cover-letter-only transcripts.
- The final pass used 1,800-character focused windows. A different window or a larger context
  could move a few rows; the reading-failure pattern (numbers outside the quote, dropped second
  parts) would remain.
- The free Beam tier returned 200 on every final call, but 40 calls do not prove it at scale.

## 9. Reproduce

```bash
python -m tasks.arch_v4.reader_test.select_questions --freeze
python -m tasks.arch_v4.reader_test.run_reader --no-model --force   # retrieval baseline
python -m tasks.arch_v4.reader_test.run_reader --force              # 40 Beam calls
python -m tasks.arch_v4.reader_test.reverify_results               # re-check saved answers
python -m tasks.arch_v4.reader_test.review                         # hand-grading packet
python -m tasks.arch_v4.reader_test.make_grades                    # 40 grades
python -m pytest tasks/arch_v4/reader_test -q                      # 21 tests
```

Artifacts: `questions.jsonl` (frozen), `questions.manifest.json`, `eligibility_parents.jsonl`,
`retrieval.jsonl`, `results.jsonl`, `grades.jsonl`, `review.md`, and the code/tests in
`tasks/arch_v4/reader_test/`.
