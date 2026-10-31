# v4 truth grade — 2026-10-31

> **Rule grade, not the authority.** The verdicts below come from code rules that never compare a value with a store. The read grade is the number to trust: `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md`; current figures are in `tasks/STATE.md`.

Three numbers on the same 2,681-row bank with no check loosened. The contract number is the unchanged method (`tasks/answer_bench/grade_v2.py`); the shape number adds the named failures of `tasks/answer_bench/truth_grade.py`; the truth number is the truth panel, not the contract.

| number | value | method |
|---|---:|---|
| contract strict | 341/2681 = 12.7% | every part of the decomposer's own Ask carries §D.4 (unchanged) |
| contract + shape | 237/2681 = 8.8% | contract **and** no question-text shape failure |
| truth (panel) | 0.6% [Wilson 0.28, 1.26] | measured answered share × panel RIGHT rate among answered rows |

- drift, stated because the brief quotes 8.2%: the write-up in `GATE_V4_2026-10-31.md` recorded 221/2,681 = 8.2% on the same grader. This run re-executed every row on the current checkout and the rebuilt v4 pilot store and got 341/2681 = 12.7%. The method did not change; the store and the executor did (another worker owns them). The truth number did not move with it.
- the contract count is a *contract* count: 104 of the 341 rows that pass it fail a named shape check, and the truth panel puts true correctness near zero.

## The panel

- fixed block: 150 rows, seed 20261031 (committed, same rows on every run); fresh block: 40 rows, seed 20261034 (printed in every fresh row) — 40 new answered/unanswered rows each run, so a grader cannot be tuned to the fixed block.
- rows contract-answered: 127 of 190; the draw oversamples answered rows (2/3) because a bank-proportional panel would carry about twelve of them.
- answered rows RIGHT: 6/127 = 4.72% (Wilson [2.18, 9.92]). The 40-row hand sample says 3/40 = 7.5% [2.6, 19.9]; both say true correctness is a small fraction of a percent of the bank, and the hand sample was drawn from the previous run's 221 answered rows, not this run's.
- bank answered share (measured on all rows): 12.7% (341/2681).
- unanswered rows are never RIGHT: the truth estimate is the answered share times the answered RIGHT rate. The interval is the Wilson interval of that RIGHT rate, scaled by the measured share.
- each row is graded against the question as written, the parent's rubric (`required_steps` / `forbidden` / `ground_truth`, where the bank has one), and the stored row behind the answer (entity, period, value, quote).
- the panel's RIGHT rows this run: MB0005#L, MB0121#L, MB0005#MI, MB0110#MI, MB0124#MS, MB0005#L. Each is the value+date / passage shape the 40-row hand check calls RIGHT (#27, #11); a RIGHT row must be read against the store before it is trusted. Three false RIGHTs the first passes produced are now failed, and each is evidence the check is worth having: MB0275#MS answered Dalmia Bharat's share count with a 20,000-row `count` for another ISIN (the real count is 18,75,65,953; `holding("DALBHARAT")`), now `TRUTH_PART_OTHER_ENTITY`; MB0306#L answered Sun Pharma's 2026 YTD high with the 30 September row alone (1,863.6; the held NSE high is 2,046.9 on 31 July, `price_extreme`), now `SHAPE_PERIOD_MISMATCH`; MB0001#L answered IDEA "products" with `production` claim rows about cash, now `TRUTH_ROW_DIM_MISMATCH`.
- RIGHT rows wrongly failed by a shape check: **0** of the 3 rows the 40-row hand check calls RIGHT (`MB0280#L`, `MB0005#MI`, `MB0303#MS`); `test_v4_truth_grade.py` re-runs that assertion whenever the graded file is present.

## Failure table by named reason (largest first)

Contract-answered rows only — these are the rows the new checks remove from the pass count:

| rows | reason | example |
|---:|---|---|
| 51 | `SHAPE_JUDGEMENT_NO_RULE` | MB0346: the ask is a judgement/rule ask; no part carries a rule_used or verdict block |
| 25 | `SHAPE_PERIOD_MISMATCH` | MB0151: the ask names Q4FY26, Q1FY27; one reading (no period) answers neither |
| 13 | `SHAPE_COMPARE_ONE_SIDE` | MB0018: the ask compares sides; the answer carries one entity and no compare operator |
| 9 | `SHAPE_SET_ONE_ENTITY` | MB0037: the ask is a set/list/ranking; the answer carries one entity (0) and no count or ranked set |
| 4 | `SHAPE_CHANGE_OVER_WINDOW` | MB0131: the ask names July 2026; the change runs 2026-06-01..2026-07-31 first-to-last over the whole window |
| 4 | `SHAPE_LIST_DUMP` | MB0459: no limit is stated and list_distinct dumps 11600 rows with no aggregation (grader cap 200) |
| 3 | `SHAPE_DUPLICATE_VALUE` | MB0444#L: parts 0 and 1 return the same value 41,310 for the same period under different labels |
| 3 | `SHAPE_FORECAST_SPOT` | MB0616#L: the ask is a forecast; the answer is a spot market reading (price.close at 2026-10-19) |

Occurrences over all 2,681 rows (unanswered rows cannot answer a shape, so this line is diagnostic only): `SHAPE_SET_ONE_ENTITY` 184, `SHAPE_JUDGEMENT_NO_RULE` 112, `SHAPE_COMPARE_ONE_SIDE` 104, `SHAPE_PERIOD_MISMATCH` 102, `SHAPE_CHANGE_OVER_WINDOW` 20, `SHAPE_LIST_DUMP` 10, `SHAPE_DUPLICATE_VALUE` 9, `SHAPE_FORECAST_SPOT` 3

## Rubric cheap test (the brief's gate on rubric scoring)

- exact agreement with the 40 hand verdicts: **9/40** (agreement on RIGHT-vs-not: 32/32 judged rows, but the lexical scorer never returns RIGHT); the brief says 30 or the rubric is not usable.
- the scorer's verdicts: {'PARTIAL': 24, 'WRONG': 8, 'None': 8} over 32 judged rows; it certifies 0/3 rows the hand check calls RIGHT, and cannot judge 8/40 at all (no steps, no gold).
- of the 29 WRONG rows, 25 are not called RIGHT, but most are called PARTIAL: a prose step's words appear in a contract-complete answer even when the step's arithmetic was never done. That is the defect — the rubric describes a method, not a value to compare.
- measured on: `python tasks/answer_bench/truth_grade.py --rubric40`.
- verdict: rubric scoring is **NOT usable** as the truth metric. Where it exists it is one input to a panel verdict, never the verdict itself.

## Free-model judge (optional, item 4)

- an OpenCode Go key is present, so `tasks/answer_bench/truth_judge.py` can run: `python tasks/answer_bench/truth_judge.py --panel fresh40` grades the fresh 40 with free Beam and prints its agreement with the panel. No judge number is used by this report until that agreement is 90% or better on rows it has not seen.

## Shape checks left out (not deterministic)

- relative windows whose reference date the question does not state ("in a month", "last week"): no window to test. A relative *forward* window ("the next five sessions") is caught only when every part is a change over the past window — that is the one case where the output is unambiguously the wrong window.
- whether an executed figure is the *economically* right one ("do the assumptions flatter the loss"): needs judgement of the accounting, so it is caught only when the ask is a judgement ask with no rule output.
- thesis quality ("what would break the growth thesis"): only the no-rule-output half is checkable.
- set membership for companies outside the pilot: the answer cannot be checked for correctness, only for being one entity.
- magnitude sanity (a share count of 20,000): the store owner's call, not a grader rule; only a cross-entity read is caught (`TRUTH_PART_OTHER_ENTITY`).

