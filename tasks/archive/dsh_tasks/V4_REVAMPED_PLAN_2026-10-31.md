# Task — write the revamped plan to reach the 95% gate

## Goal
An independent review changed what we think the problem is. Write the plan Shivam reads in the morning, so he can see what changes and decide what only he can decide. This is a writing and analysis task. Do not change code or data.

## Read
`tasks/arch_v4/GATE95_REVIEW_2026-10-31.md` (the main input), `tasks/arch_v4/GATE_V4_2026-10-31.md`, `tasks/arch_v4/GATE_V4_SAMPLE40.md`, `tasks/handoff/QUEUE_2026-10-31.md`, `tasks/handoff/HANDOFF_2026-10-31.md`, `tasks/arch_v4/QUERY_V4_DESIGN.md` section H. The golden rule is atop `AGENTS.md`.

## Controller's decisions already made
- **Accepted, running:** truth grade (idea 1, `V4_TRUTH_GRADER`), lookup repair (idea 2, `V4_LOOKUP_REPAIR`), reader kill-or-keep test (idea 4, `V4_READER_TEST`).
- **Accepted, next:** scalar collapse and study operators (idea 5), starting with its cheap test once lookup repair merges.
- **Needs Shivam:** instance repair and `premise_false` (idea 3), scope ruling (idea 6), retiring the 30% strict checkpoint for a truth-panel target, the blank `as_of` default date, and any reader design.
- **Delayed:** fresh blind split and Beam lexicon, WP6, proxy pre-read. No further WP8 work once label promotion ends. OCR of the 1,073 files is not for gate purposes.
- **Rejected:** a store sanity rule from the Vodafone Idea example. Near-duplicate merging.

Verified by the controller: no grader or v4 code reads `required_steps`, `ground_truth` or `required_evidence`, and the bank has 743 `required_steps` and 203 `ground_truth`. The other numbers in the review are the reviewer's; label them measured or estimated as it does, and do not upgrade an estimate.

## Write `tasks/arch_v4/REVAMPED_PLAN_2026-10-31.md`
1. **The situation in 6 lines:** where we truly are, and why 95% on the bank as it stands is not reachable.
2. **Old plan vs new plan:** a table of what stays, changes, stops, and why.
3. **Work packages in order:** for each, the goal, dependency, worker-hours, machine, expected truth points as a range, the check that would kill it, and the measure of done. Respect the golden rule: no full chunking or re-embedding before the gate.
4. **Milestones as truth-panel numbers,** replacing the 30% strict checkpoint, proposed for Shivam's approval, with honest confidence.
5. **Shivam's decisions:** at most 6, each with the question in one sentence, options, recommendation, what it costs to wait, and which package it blocks. Include how to count parents vs instances and whether to widen the pilot, without presenting a re-scope as settled: he has said no re-scope (`DECISION_LOG.md:329`).
6. **Risks,** including looking like the denominator was shrunk to raise the score, and how each number stays honest.
7. **What this plan cannot promise.**

Add a section for anything you think the review got wrong or missed, with evidence from the files. Check a sample of its claims against the files you read, and say which you checked. Plain direct English, under 3 pages if you can.

## Acceptance checks
- Every number traces to a named file, marked measured or estimated.
- No package depends on a decision that has not been listed.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_run.py -q
```
