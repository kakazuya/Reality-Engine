# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-01 20:11 IST (hp worker)

## Now
**Workspace fix first, by Shivam's order: `tasks/WORKSPACE_FIX_2026-11-01.md`.** OCR, extraction and database design wait until its step 4 passes.

## Next action
In a fresh session, which restarts the dsh-worker server with the start gate: (1) Shivam quizzes it on his rulings. (2) Enforce worker tool-call budgets in code: the start gate worker used 266+ against 120. (3) Run the full test suite on the HP, not the MSI, and find why it reaches 7.5 GB; `test_commit_replays_the_identity...` fails only when the launcher's `GIT_AUTHOR_NAME` is set. (4) Do step 3 of the plan. (5) Step 4, question map.

## Running
Nothing. Context pack (84 KB to 5.6 KB) and start gate are merged.

## Waiting on Shivam
- HP headless proof: the unlocked-desktop repeat **passed** 1 Nov 20:05–20:10 IST (`headless20c`): `SessionFlags` 1 before/during/after, 20/20 rows, 0 text diffs, 0 watched windows/focus, no `conhost`. Section 14.7 of `tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md`.
- Quiz a fresh session on his rulings, to test `tasks/RULINGS.md`.
- Haiku on about 100 fresh OCR pages, batches of 8: `tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md`.
- Blank `as_of` default, truth panel, reader kill: see `tasks/arch_v4/GATE_STATE_2026-11-01.md`.

## Where the project stands
Golden rule step 3, schema design, with the question bank accepted (1,901 questions, frozen). Gate on the old pilot: 12.7% contract strict, but 0 of 127 answered rows right on hand reading. Prototype on 3 companies failed its grade: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`. Full record: `tasks/arch_v4/GATE_STATE_2026-11-01.md`. Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`, last 5 entries.

## Never
Copy keys into files or print them. Send `Manual Dumps/` to the HP or any model, or put amounts in the repo or decision log. Loosen a grader to raise a score. Push without Shivam's OK. Spend DeepInfra or use paid models without his OK. Change the question bank, labels or scope without his ruling. Assign pilot bank reasoning to a worker: Claude owns it, DeepSeek only reads.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, keep ours on `query/v4/__init__.py`, run the tests, update this file and each affected doc, commit ending `By: Wolf` and the co-author line. Copy `.tmp` DBs first, then remove the worktree and branch. Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. HP: `hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.

## Machines
How to operate each computer: `machines/README.md`. All HP work runs headless. Nothing is pushed without Shivam's OK.
