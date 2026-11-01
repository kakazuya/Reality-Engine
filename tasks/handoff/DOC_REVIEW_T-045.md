# T-045: Claude reads every doc line by line (Shivam, 2 Nov 2026)

**This is the first task of the new session.** Shivam's words: "you personally read all the documentations line by line and delete older entries that have went stale and modify for latest codebase."

## The rule for this task
- Claude reads every line itself. No dsh worker, subagent or script reads or judges for it. A script may find candidates, such as references to missing files, but never decides.
- For each doc: delete what is stale, and change what is wrong so it says what the code does now. Check claims against the code before keeping or changing them.
- A doc that is entirely stale is deleted. Git history keeps it.

## Size, measured 2 Nov
588 tracked `.md`, `.txt` and `.rst` files, 188,664 lines. `tasks/ar_study` alone is 97 files and 133,890 lines. Next largest: `tasks/arch_v4` 7,272; `tasks/archive` 4,870; `tasks/pilot60` 4,132; `tasks/optimizations` 3,667; `tasks/reddit_mining` 2,712; `tasks/dsh_tasks` 2,578; `tasks/master_bank` 2,265.

This will not fit in one session, so:
1. Work in this order: `AGENTS.md`, `tasks/STATE.md`, `tasks/RULINGS.md`, `docs/`, `machines/`, `tasks/FRAMEWORK.md`, `tasks/TASKS.md`, `tasks/arch_v4/`, then each remaining folder, smallest first, and `tasks/ar_study` last.
2. Keep a progress file, `tasks/handoff/DOC_REVIEW_PROGRESS.csv`: file, lines, lines read, kept, changed or deleted, reason, commit. Update it as each file finishes and commit in small batches, so a new session resumes at the right file.
3. At 400k context, write the wrap-up as usual. The next session continues from the progress file.

## Do not change without Shivam's ruling
- The frozen question bank (1,901 questions), its labels, and ruled rows.
- `tasks/RULINGS.md` rules: correct a stale path or fact only. Changing a rule's meaning is his call.
- `D:\RealityEngine\plans\DECISION_LOG.md`: append only. It is a record.
- Grade reports and measurements that are the only record of a result: keep the result; a stale surrounding claim can go.
- `D:\Shivam_Private\Manual Dumps`: never read it.

If a file looks like generated data, not documentation (`tasks/ar_study` may be), read enough to be sure, then ask Shivam before deleting the whole folder.

## Working next to the other session
The session named `neo-Info_Diffusion_Model` is still running T-035 and T-044, and owns these until it says otherwise: `reality_engine/pilot/`, `reality_engine/query/`, `plugins/dsh-worker/`, `reality_engine/scripts/job_watch.py`, `rule_ledger.py`, `worker_review.py`, `tasks/pilot60/proto3_text/`, `tasks/efficiency/`. Its merges also edit `docs/DEVELOPER_GUIDE.md` and `tasks/STATE.md`. So before editing those two, message that session, and commit in small batches.

Use your own prefixed worktree, or work on `main` in small commits after telling the other session. Do not close this session's jobs. Closing `neo-Info_Diffusion_Model` has killed workers before.
