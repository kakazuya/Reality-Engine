# T-045: Claude reads every doc line by line (Shivam, 2 Nov 2026)

**Shivam's ruling, 2 Nov, replaces "Claude reads it personally":** Haiku 5.5 reads, not Opus, in fresh sessions kept under 100k context. Run by `reality_engine/scripts/doc_review_loop.py` on branch `Wolf-t045-doc-review`; Opus reviews the branch before it merges to main.

## The rule for this task
- A script builds the queue and enforces the guards; only the reader judges a doc, and every changed claim is checked against the code first.
- For each doc: delete what is stale, and change what is wrong so it says what the code does now.
- The reader never deletes a whole file. It proposes `delete-proposed` in the progress file, and the reviewer applies those.

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

`tasks/archive/` is in scope: Shivam gave permission on 2 Nov. The project settings still deny reading it (`Read(tasks/archive/**)` in `.claude/settings.json`), so that rule has to be lifted before this folder is reviewed. Do not work around it.

If a file looks like generated data, not documentation (`tasks/ar_study` may be), read enough to be sure, then ask Shivam before deleting the whole folder.
