# Task — judgement and forecast asks stop returning a spot value

## Goal
Idea 5 in `tasks/arch_v4/GATE95_REVIEW_2026-10-31.md`; see also `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md`. A question asks for a judgement, a forecast or a study, no operator exists, and the engine returns a nearby scalar marked as answered. `MB0616` ("share price on Diwali 2027") returns today's close. `MB1073#MI` ("distribution or absorption?") returns one day's delivery and a price change. These answers are wrong and look answered. Make them say plainly that the engine cannot answer them. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work
1. Measure first, on `tasks/answer_bench/GATE_RESULTS_v4_strict.jsonl`: rows where the ask is a judgement, forecast or study and every part is a plain scalar with no rule or operator behind it. `SHAPE_JUDGEMENT_NO_RULE` and `SHAPE_FORECAST_SPOT` in `tasks/answer_bench/truth_grade.py` are a starting point; use them for measurement only and do not import a grader into the engine. Split by phrase and family.
2. In `reality_engine/query/v4/decompose.py`, emit a typed `unmapped` part naming the kind of ask (judgement, forecast or study) and the operator it would need. Keep any measured facts the question plainly asks for as their own parts, but the case is not `case_answered` unless every part is answered.
3. Do not catch asks that do have an operator or rule: `near_high`, the verdict rules and held rules keep working. Prove it with the routing count across the 2,098 instances and the 74 regression instances, before and after.
4. Run the gate on your code. **The contract count will fall and that is correct; state by how much.** List each regression row that changes, with the reason.
5. Hand-check 20 changed rows by a committed seed: was the old answer truly not an answer to the question? Any that was a real answer is a bug to fix.

## Limits
- Do not build new operators or an agent. Both wait for Shivam.
- Do not change the bank, graders or stores. Do not change `execute.py` except what a typed part needs.

## Acceptance checks
- Tests using `MB0616`, `MB1073`, a held-rule verdict ask that still answers, and a `near_high` ask that still answers.
- PIT breaches stay 0. The report ends with `Docs updated:`.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_decompose.py reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_run.py -q
```
