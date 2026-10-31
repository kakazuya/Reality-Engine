# Task — read and grade the truth panel row by row against the stores

## Goal
`tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` reports a truth number from "the panel", but the panel's verdicts come from rules in `tasks/answer_bench/truth_grade.py` (`truth_verdict`). Nobody read the answers. Rule RIGHT never compares a value with the store, and PARTIAL rests partly on a lexical rubric that agreed with the hand check on only 8 of 40. So the number may be wrong in either direction. Produce the read grade. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Input
`tasks/arch_v4/TRUTH_PANEL_BLIND_2026-10-31.jsonl`: every contract-answered panel row, with mid, question, as_of, entity and answer. The rule verdicts are removed. Do not open `TRUTH_PANEL_2026-10-31.jsonl` until step 3.

## Work
1. For each row decide, as a careful analyst would, whether the answer truly answers the question as written. Look up the value yourself with `mcp__reality-data__*` tools, as of the row's date. Do not call the v4 engine. Use the parent's `rubric` in `tasks/master_bank/MASTER_BANK.jsonl` as guidance only.
   - **RIGHT:** a reader could rely on it. Entity, period, measure and value are all correct and every part of the question is met.
   - **PARTIAL:** a correct value that answers only part of the question. Say which part is missing.
   - **WRONG:** wrong entity, measure, period or value, or an answer that does not address the question.
   - **ILL_POSED:** the question's premise is false or names another company, so no answer can be right. Name the evidence. Report these apart; do not count them as RIGHT.
2. Write `tasks/arch_v4/TRUTH_PANEL_READ_2026-10-31.jsonl` as you go, one row per mid: verdict, one-line reason, the value you looked up with its source, and the tool call that gave it. Rerunnable: skip mids already written.
3. Only when every row has a verdict, compare with the rule verdicts: a confusion table, and every row where they differ in RIGHT versus not. Report the rule grader's false RIGHTs and false WRONGs, with the shape check responsible for each false WRONG.
4. Report to `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md`: the read RIGHT rate among answered rows with a Wilson interval, multiplied by the measured answered share; the ILL_POSED share; the top 5 reasons for not-RIGHT with counts; and which rule checks to keep or change. Propose changes; do not edit the grader.

## Limits
- Do not change any grader, the bank, the store or the panel file.
- Never mark a row RIGHT from the answer's own citation. A value must be read back separately.
- If a tool cannot settle a row, the verdict is `UNVERIFIED` with the reason, not a guess. Keep the count.
- No paid models.

## Acceptance checks
- Every blind row has a verdict and a reason. Every RIGHT and PARTIAL has a looked-up value with its source.
- The confusion table adds up to the row count.
- Tests pass.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_truth_grade.py -q
```
