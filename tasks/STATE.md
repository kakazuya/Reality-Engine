# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-02 (Wolf)

## Now
**Pilot test on BAJFINANCE, HINDALCO and KEC, by Shivam's order of 2 Nov.** Workspace tickets no longer block it. The last prototype failed: 0 of 40 sampled answers right, 78% of numbers missed: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`.

## Next action
Apply that grade's five changes, rerun the same 3 companies, and grade the same questions by reading. Tickets in `tasks/TASKS.md`, section Schema and question map.

## Running
Write contracts and engine routing merged. OCR overlay worker `20261101T204312Z-47a63343` runs. First HP OCR job was cancelled: my brief named the 2019 to Feb 2024 set, not the prototype's documents. Stored text is fine except 352 thin deck pages and KEC's 10 concalls, which are cover letters. The 1 Nov report's character column was wrong.

## Where the project stands
Golden rule step 3, schema design, with the question bank accepted (1,901 questions, frozen). Gate on the old pilot: 12.7% contract strict, but 0 of 127 answered rows right on hand reading. Prototype on 3 companies failed its grade: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`. Full record: `tasks/arch_v4/GATE_STATE_2026-11-01.md`. Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`, last 5 entries.

## Never
Copy keys into files or print them. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or any model, or put amounts in the repo or decision log. Loosen a grader to raise a score. Push without Shivam's OK. Spend DeepInfra or use paid models without his OK. Change the question bank, labels or scope without his ruling. Assign pilot bank reasoning to a worker: Claude owns it, DeepSeek only reads.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, keep ours on `query/v4/__init__.py`, run the tests, update this file and each affected doc, commit ending `By: Wolf` and the co-author line. Copy `.tmp` DBs first, then remove the worktree and branch. Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. HP: `hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.

## Machines
How to operate each computer: `machines/README.md`. All HP work runs headless. Nothing is pushed without Shivam's OK.
