# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-02 (Wolf)

## Now
**Workspace fix first, by Shivam's order: `tasks/WORKSPACE_FIX_2026-11-01.md`.** OCR, extraction and database design wait until its step 4 passes.

## Next action
Tickets live in `tasks/TASKS.md`, and the session card shows what is open and waiting on Shivam. Next: T-002 hook blocks, because later checks rely on them; then T-001 worker budgets, T-003 merge gate, T-014 question map. Start from a fresh session: the running dsh-worker server still has the old start gate, and only a restart enforces `Ticket:`.

## Running
Nothing.

## Where the project stands
Golden rule step 3, schema design, with the question bank accepted (1,901 questions, frozen). Gate on the old pilot: 12.7% contract strict, but 0 of 127 answered rows right on hand reading. Prototype on 3 companies failed its grade: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`. Full record: `tasks/arch_v4/GATE_STATE_2026-11-01.md`. Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`, last 5 entries.

## Never
Copy keys into files or print them. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or any model, or put amounts in the repo or decision log. Loosen a grader to raise a score. Push without Shivam's OK. Spend DeepInfra or use paid models without his OK. Change the question bank, labels or scope without his ruling. Assign pilot bank reasoning to a worker: Claude owns it, DeepSeek only reads.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, keep ours on `query/v4/__init__.py`, run the tests, update this file and each affected doc, commit ending `By: Wolf` and the co-author line. Copy `.tmp` DBs first, then remove the worktree and branch. Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. HP: `hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.

## Machines
How to operate each computer: `machines/README.md`. All HP work runs headless. Nothing is pushed without Shivam's OK.
