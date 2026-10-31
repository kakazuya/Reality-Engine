# Task — v4 truth grade: score answers against the bank's own rubric, plus answer-shape checks

## Goal
The gate says 8.2% strict, but a hand check found 3 of 40 passing rows right. `grade_v2.py` takes its parts from the decomposer's own Ask, so the system marks its own homework, and no grader reads `rubric.required_steps` (743 of 1,073 parents), `forbidden` (743) or `ground_truth` (203). Build a truth grade beside the contract count. Read `tasks/arch_v4/GATE95_REVIEW_2026-10-31.md` idea 1, `tasks/arch_v4/GATE_V4_SAMPLE40.md`, and `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work
1. **Cheap test first.** Apply the rubric to the 40 sampled rows by hand. If its verdicts agree with the hand check on fewer than 30, say so; rubric scoring is then not usable and only the panel below remains. Correct sample row #4: Vodafone Idea's +34,552 cr matches the filing's own figures, so it is a wrong answer to that question, not a store defect. Fix that claim in `GATE_V4_2026-10-31.md` and `GATE_V4_SAMPLE40.md`.
2. **Answer-shape checks, derived from the question text alone, never from what the executor returned.** Fail with a named reason when: a set, list or ranking ask is answered from one entity; a comparison lacks a side; a judgement ask has no rule output; a period-named `change` returns first-to-last over the whole window; two parts return one value under different labels; a `list_distinct` dump exceeds a stated limit with no aggregation; a forecast gets a spot price; the returned period is not the one asked. Leave out any check you cannot make deterministic, and say which.
3. **Truth panel.** A fixed panel of 150 rows by a committed seed, stratified by bucket, family and answer shape, across answered and unanswered rows, plus a fresh random 40 on each run so it cannot be overfitted. Grade each against the question, rubric and stored rows, with RIGHT / PARTIAL / WRONG and a one-line reason, in `tasks/arch_v4/TRUTH_PANEL_2026-10-31.jsonl`. This panel is the authority.
4. **Free-model judge, optional.** Use free Beam (`beam-free`, `reasoning_effort=low`, `cost_ledger.record_usage`, stable session id) for the whole bank only if it agrees with the panel at 90% or better on rows it has not seen. Report the agreement either way. If it falls short, do not use it.
5. **Report.** A new gate_run mode prints three numbers side by side: contract strict (unchanged method), contract plus shape, truth (panel estimate with a Wilson interval). Add a failure table by named reason, largest first.

## Limits
- Only ever stricter. Do not relax or remove any existing check, and keep the old count visible.
- Do not change `MASTER_BANK.jsonl`, `INSTANCES.jsonl` or `instantiate.py`, and do not withdraw any row: instance repair needs Shivam's approval.
- Do not change executor or decomposer behaviour; another worker is editing `execute.py`.
- Raw gate output is about 355 MB: stream it. Regenerate it with `python tasks/pilot60/gate_run.py v4 --fresh` if absent. One heavy process at a time.

## Acceptance checks
- RIGHT rows wrongly failed by the shape checks: zero, or each one listed with why.
- All three numbers reported plainly, even if they fall.
- Tests pass, with a test for each shape check.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_truth_grade.py reality_engine/tests/test_v4_run.py -q
```
