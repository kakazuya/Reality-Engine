# Task — test only: can a quote-verified evidence reader answer document questions?

## Goal
Text parts almost never pass (97 of 1,116 even on contract), and the executor never reads the 108,078 chunks in `chunks_v3_pilot.db`. Before anyone builds a reader, measure one. This is a kill-or-keep test, not a build: read `tasks/arch_v4/GATE95_REVIEW_2026-10-31.md` idea 4.

## Work
1. Pick 40 questions by a committed seed from `tasks/master_bank/MASTER_BANK.jsonl` and `tasks/pilot60/INSTANCES.jsonl`: asks about what a company said or disclosed, naming a pilot company, with a premise that holds. Exclude a row only with a written reason. Commit the list before running anything, and do not change it afterwards. Include MB0337, MB0345, MB0355, MB0415, MB0540.
2. Retrieve: filter chunks by entity, document type and `known_at <= as_of` before any model sees them, then FTS. Try query terms from the question and synonyms. Naive OR search returns letterheads, so report what worked. No paid embeddings.
3. Read: free Beam (`beam-free`, `reasoning_effort=low`, `cost_ledger.record_usage`, stable session id) returns an answer with a quote, or `not stated`.
4. Reject any answer whose quote is not verbatim in the retrieved chunk. Numbers come only from the quote.
5. Grade all 40 by hand against the question, the rubric and the chunk: RIGHT, PARTIAL, WRONG, CORRECT_NOT_STATED, and whether the failure was retrieval or reading.

## Report
`tasks/arch_v4/READER_TEST_2026-10-31.md`: the 40 rows with verdicts, the right rate with a Wilson interval, retrieval vs reading failures, wrong answers that carried a real quote, seconds per question, Beam calls and errors.

Verdict rule, fixed in advance: under 50% RIGHT means kill the model reader and fall back to retrieval with quotes only; 50% or more means propose a design for Shivam, who must rule because the design says the LLM never sets a number.

## Limits
Do not change `reality_engine/query/v4/` or any grader. Test code lives in `tasks/arch_v4/reader_test/`. Point-in-time holds. Use `pilot/pilot60/chunks_v3_pilot.db` read-only under `REALITY_DATA_ROOT`.

## Acceptance checks
- Question list committed before the first model call.
- All 40 graded, none dropped after running.

## Test command(s)
```bash
python -m pytest tasks/arch_v4/reader_test -q
```
Include tests for the verbatim-quote check and the `known_at` filter.
