# Task — make the v4 gate measure true answers: instance text fix and answer-shape checks

## Goal
The first v4 gate is 221/2681 strict (8.2%), but a hand check of 40 of those rows found 3 right, 7 partial, 30 wrong. The number overstates the truth, so it cannot steer the work. Make it honest. First read `tasks/arch_v4/GATE_V4_2026-10-31.md`, `tasks/arch_v4/GATE_V4_SAMPLE40.md` and `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work
1. **Instance text.** `tasks/pilot60/instantiate.py` rewrites `entities` but leaves the question naming the original company (samples #3, #10, #13, #19). Fix it so the text and the case entity agree. Where a question depends on a company-specific event that the substitute did not have (an Ola listing given to Bosch), do not instantiate it: record why. Keep `mid`s stable. Report how many instances changed and how many were withdrawn, and write the list to `tasks/pilot60/INSTANCE_FIXES_2026-10-31.md`. Keep a backup of the old `INSTANCES.jsonl`.
2. **Answer-shape checks in the grader, only ever stricter.** A part or case fails, with a named reason, when:
   - a set, list or ranking ask is answered from one entity;
   - a comparison ask lacks one side;
   - a judgement ask has no rule output;
   - a `change` or trend ask returns only first-to-last across the whole window when the ask names a period;
   - two parts return the same value under different labels;
   - a `list_distinct` dump exceeds a stated row limit without a named aggregation;
   - a forecast ask gets a spot price instead of a typed unmapped result;
   - the returned period is not the one asked for.

   Derive the ask shape from the question alone, not from what the executor returned. Do not relax any existing check. If a check needs a judgement you cannot make deterministically, say so and leave it out.
3. **Measure the new grader against hand verdicts.** Run it over the 40 rows in `GATE_V4_SAMPLE40.md` and any earlier hand-checked rows. Report how many WRONG rows it now fails and how many RIGHT rows it wrongly fails. RIGHT rows wrongly failed must be zero, or list each one with why.
4. **Re-run the gate:** `python tasks/pilot60/gate_run.py v4 --fresh`, then `v4report`. Update the gate report with old number, new number and failures by named reason, largest first. Draw a NEW hand-check sample of 40 with a new seed and judge it against stored rows as `GATE_V4_SAMPLE40_b.md`.

## Limits
- Do not touch `MASTER_BANK.jsonl`. Do not change executor or decomposer behaviour in this task.
- The raw gate output is about 355 MB: stream it. One heavy process at a time on this machine.

## Acceptance checks
- Old vs new number, and the new sample's RIGHT / PARTIAL / WRONG counts, reported plainly even if the number falls.
- Failure table by reason, so the next brief can be chosen from it.
- Tests pass.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_run.py reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_decompose.py -q
```
Add tests for each new grader check and for the instantiate fix.
