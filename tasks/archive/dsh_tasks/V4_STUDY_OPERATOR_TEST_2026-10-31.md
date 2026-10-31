# Task — v4 study operator cheap test: near-high count and forward return

## Goal
Idea 5 in `tasks/arch_v4/GATE95_REVIEW_2026-10-31.md`: judgement and study asks collapse into a spot value. Before building more, test one operator on MB1044 and MB1047 across all their instances. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md` and the idea 5 section only.

- MB1044: "HAL is within 2% of its 52-week high. How many prior sessions this year were this close, and what followed?" Steps: count sessions within 2% of the 52-week high, compute forward 10-day returns, report. Forbidden: counting only the successful breakouts.
- MB1047: "Trent at a new high: what share of the last year's trading days were within 5% of the then-current 52-week high?" Steps: per-row distance, share within 5%, state the persistence. Forbidden: using today's 52-week high for historical rows.

## Work
1. One typed operator in `reality_engine/query/v4/`, reached through the decomposer and executor, not special-cased by mid. For each session: the then-current 52-week high from rows dated on or before it, distance from it, a threshold count or share, and an optional forward return.
2. **No look-ahead:** nothing dated after `as_of` enters. A forward window must end on or before `as_of`; a window that does not is counted separately as incomplete and named in the answer, never dropped silently.
3. The answer lists every qualifying session or a count with the full return distribution (winners and losers), the window, the threshold, the price basis and the exchange. State raw basis. If a corporate action falls inside the 52-week window, name it in the answer; do not compare across it silently.
4. Run every instance of both parents. Grade each by hand: recompute one value per row independently from the store with SQL, separate from the operator's code. Give RIGHT / PARTIAL / WRONG with a one-line reason in `tasks/arch_v4/STUDY_OPERATOR_TEST_2026-10-31.md`.

## Limits
- Do not change `MASTER_BANK.jsonl`, `INSTANCES.jsonl`, or any grader.
- Do not change how other asks route, beyond what the operator needs. Prove it with the regress count before and after.
- If a name has no 52 weeks of history, return a typed NID with the reason.

## Kill rule, fixed in advance
If the operator answers fewer than half of the instances RIGHT, say so and stop. Report the reasons. Do not build more operators here, whatever the result.

## Acceptance checks
- Every instance has a verdict with an independently recomputed value.
- A test proves a row after `as_of` cannot change the result, and that the 52-week high is the then-current one rather than today's.
- A test proves losers are counted.
- PIT breaches stay 0.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_decompose.py reality_engine/tests/test_v4_run.py -q
```
