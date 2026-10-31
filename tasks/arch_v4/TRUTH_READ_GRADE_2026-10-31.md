# Truth panel — read grade, 2026-10-31

The panel's truth number was produced by `truth_verdict()` in `tasks/answer_bench/truth_grade.py`. Nobody read the answers. This report is that read: 127 contract-answered panel rows, 111 distinct questions, each graded against the question as written and against the stores, with the value looked up separately. The rule verdicts were not opened until every row had a read verdict.

**Result: 0 of the 127 answered rows is RIGHT.** The rule grader's 4 RIGHTs are 3 PARTIALs and 1 WRONG. A third of the answered rows (42/127) are ILL_POSED — the question asserts something the held data contradicts, or names a different company — so no answer could have been right.

## Headline

| number | value | method |
|---|---:|---|
| read RIGHT among answered panel rows | **0/127 = 0.00%** [Wilson 0.00, 2.94] | each row read against the question and a store lookup |
| same, distinct questions | 0/111 = 0.00% [0.00, 3.35] | one verdict per mid (16 mids sit in both blocks) |
| measured answered share | **13.465%** (361/2681) | counted on the raw v4 run the panel was cut from |
| **read truth estimate** | **0.00%** [0.00, 0.40] | 0.00% × 13.465% |
| rule truth estimate (unchanged, for comparison) | 0.42% [0.17, 1.05] | 4/127 = 3.15% [1.23, 7.82] × 13.465% |
| ILL_POSED share among answered rows | **42/127 = 33.1%** (38/111 = 34.2% of questions) | reported apart, never counted as RIGHT |

The rule's point estimate (0.42%) sits **above** the read interval's upper bound (0.40%): the rule number is not just unsupported, it is too high. The read says the v4 executor got no answered question fully right in this panel.

Robustness, because zero is a strong claim: the single closest row is `MB0280#MS` (promoter holding right; the "exact" share count is the XBRL-rounded 946,500,000 instead of the held exact 946,531,653). If a reader allowed that rounding, the estimate becomes 1/127 = 0.79% [0.14, 4.33] → truth 0.11% [0.02, 0.58]. The conclusion does not change: true correctness is a small fraction of a percent of the bank, below the rule's 0.42%.

## What was graded, and how

- Input: `tasks/arch_v4/TRUTH_PANEL_BLIND_2026-10-31.jsonl` — 127 rows, 111 distinct mids, every contract-answered panel row. Rule verdicts absent, as designed.
- Output: `tasks/arch_v4/TRUTH_PANEL_READ_2026-10-31.jsonl` — one row per mid: `verdict`, `reason`, `looked_up` (value + source), `tool` (the call that produced it), plus a stable `reason_code` for counting. Rerunnable: the writer skips mids already in the file; 111/111 blind mids are covered.
- The blind file's `answer` field is the panel's own render, capped at 400 characters: 82 of 127 rows are truncated mid-answer. The cap is a display defect, not a fact about the answer, so the full answers were read from the raw run the panel was cut from (`C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\answer_bench\GATE_RESULTS_v4_strict.jsonl`, gitignored, outside the worktree). It is the same run: 111/111 blind rows match the raw run's answers in their 400-character prefix after whitespace normalisation. Nothing in the rule grader was run or reused.
- No row is UNVERIFIED: every question was settled against a store. Where a hidden detail could matter, the verdict rests on something visible and checkable (the measure returned, the period, the entity, a premise the store contradicts), not on the hidden number.
- Values were read back for every RIGHT/PARTIAL: `shp_index`/`ar_facts` via `holding()`, `px_nse_adj` via `price()`/`price_extreme()`/`sql`, `company_forensic_health` for stored P/B, `results_xbrl.filings` for filing timestamps, `corporate_actions` for bonuses, `circuit_hits`/`price_bands` for bands, `bse_announcements` for the Sunday filing. A probe row's own citation was never used as the value.

## Top 5 reasons for not-RIGHT (127 answered rows)

| rows | reason_code | what it means | example |
|---:|---|---|---|
| 66 | `MEASURE_NOT_ANSWERED` | the answer returns a different measure than the question asks — a price, volume, PAT, capex or a claim dump where a valuation, a return, an exposure or a judgement was asked | `MB0618#L`: "What is GRASIM's CEO paid" answered with a 2019-2026 price change; the quoted 2,048.80 is not even GRASIM's close (2,879.00) |
| 42 | `PREMISE_FALSE` | ILL_POSED: the question's stated fact is contradicted by the held data (22 rows) or it names a different company than the row entity (20 rows) | `MB0558#L`: HINDUNILVR's "1:2 bonus ex 4 June 2026" — no bonus in `corporate_actions` and the stock moved -0.54%; the bonus is TRENT's. `MB0997#L`: "Adani Green" asked of POWERGRID |
| 7 | `PART_MISSING` | a correct value that answers only part of the question | `MB0031#MS`: close 134.84 on 16 Oct 2026 is right; "what does it make" is not answered |
| 6 | `NO_SET_OR_RANKING` | a set/ranking/comparison ask answered from one entity | `MB0127`: "rank the companies by public shareholding as of Sep 2026" answered with GMRAIRPORT's own 32.84% at Jun 2026 |
| 4 | `PERIOD_MISMATCH` | the period returned is not the one asked | `MB0355#L`: FY21 capex (31 Mar 2021) for a Q1FY27 capital-repairs question |

Tail: `VALUE_WRONG` 1 (`MB0106#MI`, 15.80% vs the held 17.0% three-year CAGR), `COMPARE_MISSING` 1 (`MB0938`, Sun Pharma only, the 5,883.60 is the YoY increase, not revenue). The same order holds over the 111 questions (54 / 38 / 7 / 6 / 4 / 1 / 1).

## Confusion table (read × rule, 127 answered rows)

| read \ rule | RIGHT | PARTIAL | WRONG | total |
|---|---:|---:|---:|---:|
| RIGHT | 0 | 0 | 0 | **0** |
| PARTIAL | 3 | 1 | 3 | 7 |
| WRONG | 1 | 33 | 44 | 78 |
| ILL_POSED | 0 | 6 | 36 | 42 |
| total | **4** | **40** | **83** | **127** |

Same table over the 111 distinct questions: RIGHT 4/35/72; read PARTIAL 3/1/3, read WRONG 1/28/37, read ILL_POSED 0/6/32. Both add up.

The 83 rule-WRONG rows are right for the wrong reason in 36 cases (they are ILL_POSED, not answer failures) and wrong on the RIGHT-vs-not test in 3 cases (the read calls them PARTIAL). The 40 rule-PARTIAL rows are ILL_POSED in 6 cases and PARTIAL in only 1.

## RIGHT-versus-not disagreements — every row

Four rows, all of them rule-RIGHT:

| mid | entity | rule | read | why the read differs |
|---|---|---|---|---|
| `MB0031#MS` | EDELWEISS | RIGHT | PARTIAL | close 134.84 on 16 Oct 2026 verified; the question also asks what the company makes — not answered |
| `MB0032#MI` | ASHOKA | RIGHT | PARTIAL | close 104.95 verified; "what does it make" not answered |
| `MB0106#MI` | ASAHISONG | RIGHT | **WRONG** | 15.80% CAGR starts at the 3 Oct 2023 close (250.90), not the 30 Sep 2023 endpoint; from the held 29 Sep 2023 close (242.80) to 389.15 on 30 Sep 2026 the CAGR is **17.0%**. Neither endpoint date is stated, which the question explicitly demands |
| `MB0280#MS` | EDELWEISS | RIGHT | PARTIAL | promoter 31.54% at 30 Sep 2026 verified; the "exact" share count is the XBRL-rounded 946,500,000, 31,653 below the held exact 946,531,653 (`ar_facts`, AR FY26 p121 and p392) |

**The rule grader's false RIGHTs: 4 of 4.** Three are "answer half the question"; one is a wrong value that no check compared with a store.

**The rule grader's false WRONGs: 3** — `MB0064#L`, `MB0064#MI`, `MB0064#MS` (the P/B "stored vs computed" rows). The read calls all three PARTIAL: the computed P/B is there, the stored one is not. The shape check responsible in all three is **`SHAPE_COMPARE_ONE_SIDE`**: the question text contains "vs", so the check demands two entities or a compare operator, but "stored vs computed" is a comparison of two measures on one entity. This is the only check that fails a row the read does not.

## Which rule checks to keep or change

Conversion is over the 127 answered rows (what the check fired on → what the read says). No grader was edited.

| check | fires | read RIGHT | PARTIAL | WRONG | ILL_POSED | verdict |
|---|---:|---:|---:|---:|---:|---|
| `SHAPE_JUDGEMENT_NO_RULE` | 41 | 0 | 0 | 21 | 20 | **keep, split** — never certifies a right answer, but half its rows are premise failures, not missing verdicts |
| `TRUTH_RUBRIC_STEPS_MISSING` | 30 | 0 | 0 | 27 | 3 | **replace** — lexical word coverage; 27 of its rows fail for a measure the answer never returns, 3 are ILL_POSED. It describes a method, not a value |
| `TRUTH_ENTITY_TEXT_MISMATCH` | 14 | 0 | 0 | 0 | 14 | **keep** — 14/14 correct; misses 4 of the 18 names-another-company rows (they land in `SHAPE_JUDGEMENT_NO_RULE`) |
| `TRUTH_MEASURE_MISSING` | 7 | 0 | 1 | 6 | 0 | **keep** |
| `SHAPE_COMPARE_ONE_SIDE` | 7 | 0 | **3** | 4 | 0 | **change** — the source of all 3 false WRONGs; exclude one-entity measure-vs-measure comparisons |
| `SHAPE_SET_ONE_ENTITY` | 5 | 0 | 0 | 5 | 0 | **keep** |
| `SHAPE_PERIOD_MISMATCH` | 5 | 0 | 0 | 4 | 1 | **keep** |
| `TRUTH_OK` | 4 | **0** | 3 | 1 | 0 | **change** — the RIGHT branch never compares the value with a store, so its precision here is 0/4 |
| `SHAPE_FORECAST_SPOT` | 4 | 0 | 0 | 4 | 0 | **keep** |
| `SHAPE_CHANGE_OVER_WINDOW` | 4 | 0 | 0 | 4 | 0 | **keep** |
| `TRUTH_PART_OTHER_ENTITY` | 3 | 0 | 0 | 2 | 1 | **keep** |
| `TRUTH_GOLD_MISSING` | 3 | 0 | 0 | 0 | 3 | **keep only as a numeric test** — it fired on 3 ILL_POSED rows because a prose gold does not appear word-for-word |

Proposed changes, in order of effect on the number:

1. **Make the RIGHT branch compare a value.** `truth_verdict()` reaches `TRUTH_OK` when the contract is covered, the shapes hold and the prose rubric steps appear. It never reads a store. That is why all 4 RIGHTs are wrong and why `MB0106#MI` (a 1.2pp CAGR error) passed. A RIGHT should require the answer's (entity, measure, period, value) to equal a store read within tolerance; anything else is PARTIAL/WRONG.
2. **Add ILL_POSED as a first-class verdict.** 42/127 answered rows (33%) are unanswerable as written: 20 assert a fact the stores contradict (a 9.65% fall that did not happen, a 1:2 bonus that belongs to another company, a filing timestamp that belongs to another company), 18 name a company other than the row entity. Today they land in WRONG (36) or PARTIAL (6) and inflate the "answer" failure count. Naming them changes what the team fixes: the instance generator renames the company but keeps the parent's specific fact.
3. **Fix `SHAPE_COMPARE_ONE_SIDE`.** `_COMPARE_OFF_RE` already exempts "vs the stored"; extend it to any "stored vs computed" / same-entity measure comparison. This is the only false-WRONG source found (3/3).
4. **Retire the lexical rubric as a verdict input.** It agreed with the 40 hand verdicts on 8/40 (`truth_grade.py --rubric40`) and here it fires on 30 rows, 27 of which the read fails for a measure that is simply not returned, and 3 of which are ILL_POSED. Keep `ground_truth` only when it is a number and the answer carries the same number.
5. **Split `SHAPE_JUDGEMENT_NO_RULE`.** Half its rows (20/41) are premise failures, not missing `rule_used` blocks; reporting them as "the ask is a judgement ask" hides that the question itself is the defect.

Keep unchanged: `SHAPE_SET_ONE_ENTITY` (5/5 not-RIGHT), `SHAPE_FORECAST_SPOT` (4/4), `SHAPE_CHANGE_OVER_WINDOW` (4/4), `SHAPE_PERIOD_MISMATCH` (4/5), `TRUTH_ENTITY_TEXT_MISMATCH` (14/14), `TRUTH_PART_OTHER_ENTITY` (3/3), `TRUTH_MEASURE_MISSING` (7/7), `SHAPE_DUPLICATE_VALUE`, `SHAPE_LIST_DUMP` (both absent from this panel's answered block but sound in principle), and `TRUTH_NOT_ANSWERED` (the 63 unanswered rows are never RIGHT and are rightly outside the answered rate).

## What this means for the answer contract

- The executor does not answer the question it is given: 66/127 rows return a nearby atom (price, volume, PAT, capex) or a claim dump instead of the asked measure. That is the dominant failure, and it is invisible to any grader that reads the answer's shape.
- The panel cannot be made truthful by tightening the rule grader alone: 33% of its answered rows have a false premise. The instance generator needs a premise check against the stores before a row enters the bank — the held data already contradicts 20 of them.
- The one number to carry forward: **true correctness on the contract-answered rows is 0.00% [0.00, 0.40]** of the bank (13.465% answered), with 0/127 RIGHT and 33.1% ILL_POSED. The rule's 0.42% is above that upper bound.

## Limits

- The read is one analyst's reading. The 7 PARTIALs are the only judgement calls and each argues its missing part in the row's `reason`; everything else is decided by a store value, a filing timestamp, a corporate action or the entity identity.
- The panel's 400-character answer cap hides later parts on 82 of 127 rows. Full answers came from the same run's raw file; the fair-comparison check (111/111 prefix match) is in the method section.
- Only the contract-answered rows are graded here. The 63 unanswered panel rows are outside the answered rate by the task's definition; they are never RIGHT.
- The stores are read-only and were queried as of the snapshot date (`truth_2026-10-19.duckdb`, live SQLite for ownership/actions). A row whose as_of is after 2026-10-19 (e.g. `MB0616`, as_of 2026-10-27) was settled on the question's premise and on the 2026-10-19 snapshot values; the forecast rows do not depend on post-snapshot data.

## Verification

```
python -m pytest reality_engine/tests/test_v4_truth_grade.py -q
# 43 passed, 1 skipped (the skipped test needs the gitignored raw run in the worktree)
```

Artifact checks (all pass, rerunnable): 111 output rows = 111 distinct blind mids; every verdict in {RIGHT, PARTIAL, WRONG, ILL_POSED, UNVERIFIED}; every row has a reason; every RIGHT/PARTIAL has `looked_up` and `tool`; every ILL_POSED has held evidence; the confusion table sums to 127.

## Files

- `tasks/arch_v4/TRUTH_PANEL_READ_2026-10-31.jsonl` — new; the read grade, one row per mid (111 rows).
- `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md` — new; this report.
- Nothing else was touched: no grader, bank, store, panel file or engine code. The writer and analysis helpers live in `.tmp/` (scratch, not a deliverable).

## Note for the controller

The panel builder caps `answer` at 400 characters (`_panel_row` in `truth_grade.py`), which truncates 82 of 127 answered rows mid-part. A future read grade can only be done on the full answer, so either raise that cap or write `answer_full` beside it. I worked around it by reading the same run's raw file (gitignored, outside the worktree); it is not a change to the grader.

