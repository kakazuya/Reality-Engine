# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-08 17:40 IST (Wolf)
History: `docs/state_history/`. Method and results: `docs/PILOT3_BLUEPRINT.md`. Tickets: `task_board list`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies, row checks built). Off-pilot verified rows not yet trustworthy (~68% right on hold6/fresh6 before round 10; fresh6 after round 10: 20 of 22 right).
- T-124 (Wolf): 311 harvested investor questions reframed to 156 (scratch `q12/t124_reframed.csv`); store `q12.db` (12 hold-out companies + 170 FY25-27 docs) building in Wolf scratchpad `q12/` (log `build3.log`); then a model answers via `python -m reality_engine.scripts.p3ask --db <q12.db>` and Opus grades.
- T-126 (Wolf): Drive files other machines uploaded are now in the T-102 manifest (`drive_index_unlisted`, 122,832 rows added); re-run after any upload.
- T-125 (Wolf): worker `20261108T114201Z-41e0aa80` built `project_rules`/`project_state` tools, never-cut rulings hook, char caps; merged `cec49db`, RULINGS 6.6k and STATE 2.5k chars; Shivam /mcp to load the tools.
- T-120 (Wolf): pilot10 2019-2024 history build done 17:28 (6,359 docs, kpi 4,771 verified / 22,060 unverified / 3,157 quarantined); T-121 ocr part running (`build.log`), then re-run kpi.
- Waiting Shivam: T-116, T-118, T-121, T-122. Shivam's ticket board (always synced): `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

## Next action
1. Finish q12 build, run T-124 ask + grade, report HTML + xlsx in `D:\RealityEngine\reports\`.
2. Re-run T-118 with guidance/KPI factors on the history db, then T-119.
3. Ticket the `ar_facts` scale/column bug; fresh hidden hold-out for checker round 10.
4. Sweep 3 GB new raw under `D:/RealityEngine/raw/pilot60_history/{HDFCBANK,SBILIFE,INFY,MARUTI,ETERNAL}` to Drive.
5. After any `--part stores`: re-run `--part preferred` then `--part checks`. Shivam must /mcp after server changes.

## Never
Copy or print keys. Read `D:\Shivam_Private\Manual Dumps`. Loosen a grader. Push without Shivam's OK. Paid models without his OK. Change bank, labels or scope without his ruling.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run the changed test files one per process, update this file and each affected doc, commit ending `By: <identity>` and the co-author line. Copy `.tmp` outputs, remove the worktree. Log to the decision log; `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. Machines: `machines/README.md`; HP work headless.
