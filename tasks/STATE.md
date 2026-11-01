# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-02 (Wolf)

## Now
**Pilot test on BAJFINANCE, HINDALCO and KEC, by Shivam's order of 2 Nov.** Workspace tickets no longer block it. The last prototype failed: 0 of 40 sampled answers right, 78% of numbers missed: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`.

## Next action
**New session, first task, by Shivam's order of 2 Nov: T-045. Claude personally reads every doc line by line, deletes stale entries and corrects the rest to the current code. Brief: `tasks/handoff/DOC_REVIEW_T-045.md`.**

Session `neo-Info_Diffusion_Model` keeps the rest:
1. T-044 worker `20261101T224005Z-22f89c1a` (finished-job watch): review, merge, then attach `job_watch status` to a hook on every prompt.
2. Drop the Workers sheet from `reality_engine/scripts/rule_ledger.py`: `reality_engine/scripts/worker_review.py` (T-043, merged) covers it. On every worker finish, add its row to `tasks/efficiency/worker_reviews.jsonl`, then run `worker_review build`.
3. T-035 running: log `.tmp/proto3/extract_t035.log`, DB `.tmp/proto3/extract_t035.db`, spend ceiling $8 on estimated cost (from the 2 Nov hand-off note, not a ruling by Shivam). Then recheck disputes; load facts; answer the same questions; grade by reading. KEC's 10 transcripts are now in `chunks_v3_pilot.db` (T-037); backup in `D:\RealityEngine\backups`.

## Running
From session `neo-Info_Diffusion_Model`, which must stay open: T-035 extraction on the MSI and the T-044 worker.

## Where the project stands
Golden rule step 3, schema design, with the question bank accepted (1,901 questions, frozen). Gate on the old pilot: 12.7% contract strict, but 0 of 127 answered rows right on hand reading. Prototype on 3 companies failed its grade: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`. Full record: `tasks/arch_v4/GATE_STATE_2026-11-01.md`. Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`, last 5 entries.

## Never
Copy keys into files or print them. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or any model, or put amounts in the repo or decision log. Loosen a grader to raise a score. Push without Shivam's OK. Spend DeepInfra or use paid models without his OK. Change the question bank, labels or scope without his ruling. Assign pilot bank reasoning to a worker: Claude owns it, DeepSeek only reads.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, keep ours on `query/v4/__init__.py`, run the tests, update this file and each affected doc, commit ending `By: Wolf` and the co-author line. Copy `.tmp` DBs first, then remove the worktree and branch. Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. HP: `hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.

## Machines
How to operate each computer: `machines/README.md`. All HP work runs headless. Nothing is pushed without Shivam's OK.
