# Task — make the rule grader agree with the read grade

## Goal
`tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md` read 127 answered rows: 0 RIGHT. The rule grader called 4 of them RIGHT, all false, because its RIGHT branch never compares a value with a store. Reading by hand on every run does not scale, so apply that report's proposals. The aim is a stricter, honest grader, not a higher number. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`. Code: `tasks/answer_bench/truth_grade.py`, `tasks/pilot60/gate_run.py`.

## Work
1. **RIGHT compares a value.** RIGHT requires the answer's entity, measure, period and value to equal a separate read of the store within a stated tolerance, and every part of the question to be met. Anything else is PARTIAL or WRONG. Use the store directly, not the answer's own citation.
2. **ILL_POSED is a verdict**, using the premise audit (`tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl`), the entity mismatch check and the read grade's evidence. It is reported in its own column and never counts as RIGHT. **Rows stay in the 2,681 denominator.** No scope change; only Shivam can rule on that.
3. **Retire the lexical rubric** as a verdict input. Keep `ground_truth` only where it is a number and the answer carries that number.
4. **Split `SHAPE_JUDGEMENT_NO_RULE`** so premise failures report as premise failures.
5. **`SHAPE_COMPARE_ONE_SIDE`:** a one-entity "stored vs computed" ask is a comparison of two measures. This is the one change that could let a row through, so list each row it affects. Such a row still needs both sides shown to pass.
6. **Panel rows carry `answer_full`** beside the 400-character `answer`.

## Validation
Run the new rules over the 111 read-graded questions, using `tasks/arch_v4/TRUTH_PANEL_READ_2026-10-31.jsonl` as truth. Report the confusion table. Target: no false RIGHT. If the raw answers for those rows are not available in your job, build the check to run from `tasks/answer_bench/GATE_RESULTS_v4_strict.jsonl`, test it on a fixture and give the controller the command.

## Limits
- No change to the bank, stores, `reality_engine/query/v4/` or the read-grade files.
- Never loosen a check to raise a score. Say plainly which direction each change moves the number.

## Acceptance checks
- Tests: `MB0106#MI`-style wrong value is not RIGHT; `MB0031#MS`-style half answer is not RIGHT; a matching value with all parts met is RIGHT; an ILL_POSED row stays in the denominator and is not RIGHT.
- `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md` stays the authority until a read of later answers agrees with the new rules.
- Report ends with `Docs updated:`.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_truth_grade.py -q
```
