# Task — kill-or-keep test: a free model answers bank questions by querying the stores itself

## Goal
The read grade (`tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md`) found 0 of 127 answered panel rows RIGHT. 66 return a nearby measure instead of the asked one: the decomposer turns an analytical question into a few scalar lookups, and nothing does the analysis. The grader, reading the same stores with tools, could work out the real answers. Test whether a free model with typed, point-in-time tools can answer bank questions. This is a test, not a build: no change to `reality_engine/query/v4/`. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Sample, frozen before any model call
40 rows by seed `20261040`, from `tasks/pilot60/INSTANCES.jsonl` and `tasks/master_bank/MASTER_BANK.jsonl`:
- Entity inside the 60 pilot names, or a question with no entity that the pilot stores can address.
- Not flagged `false` in `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl`, and not `ILL_POSED` in `tasks/arch_v4/TRUTH_PANEL_READ_2026-10-31.jsonl`.
- Do not take rows whose text names a different company from the row entity.
- Stratify across families, and include at least 10 judgement or study questions.
Write the list and its sha256 to `tasks/arch_v4/analyst_test/questions.jsonl` before the first model call. Record every exclusion rule with counts. No row may be swapped afterwards.

## The agent
- Model: `beam-free`, the same client and rules as `tasks/arch_v4/reader_test/beam_client.py` (stable session id, `cost_ledger.record_usage`). No other model, and no paid model. If the free tier blocks you, report the exact error and stop.
- Tools, read-only, with `as_of` enforced by the wrapper rather than by the model: a query over the `fact` store (atom, entity, dims, period range), `claim` search, chunk search over `pilot/pilot60/chunks_v3_pilot.db`, a list of atoms, and a calculator. Every row returned has `known_at <= as_of`. The model cannot pass a later date.
- At most 12 tool calls per question. Log every call and result.
- Output: the answer, the working in short form, and the part of the question it could not answer. "Not in the data" is allowed and is typed.
- Check every number in the answer against a tool result or a logged calculator result. A number that fails this check is listed against the row and counts against it when graded.

## Grading
Grade each row by hand against the question and the stores, using the same definitions as the read grade: RIGHT, PARTIAL, WRONG, ILL_POSED, CORRECT_NOT_IN_DATA. Look each value up separately with `mcp__reality-data__*` or SQL, never from the agent's own log. Where the question asks for a judgement, RIGHT requires a stated reason resting on correct numbers. If you are not sure, it is not RIGHT.

## Rule, fixed before the run
Under 50% RIGHT of the rows that are not ILL_POSED and not CORRECT_NOT_IN_DATA: kill. Report it plainly, and give the Wilson interval. The rule does not move after seeing results. A pass only allows a design proposal for Shivam.

## Report
`tasks/arch_v4/ANALYST_AGENT_TEST_2026-10-31.md`: verdict first; the 40 rows with verdict and reason; failure causes (tool gap, data gap, reasoning, arithmetic); seconds and tokens per question, and an estimate for 2,681 rows; PIT breaches; and a comparison with the engine's answers on the same rows.

## Limits
- Do not change the bank, graders, stores or `reality_engine/query/v4/`. Put code in `tasks/arch_v4/analyst_test/`.
- One heavy process at a time.

## Acceptance checks
- Test: the wrapper refuses a row after `as_of`, even when the model asks for a later date.
- Test: a number absent from the tool results is flagged.
- Questions frozen before the first model call, with the sha256 and timestamps in the report.
- All 40 rows graded, with a looked-up value for each RIGHT and PARTIAL.

## Test command(s)
```bash
python -m pytest tasks/arch_v4/analyst_test -q
```
