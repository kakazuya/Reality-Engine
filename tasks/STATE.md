# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-08 17:40 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies). Off-pilot verified rows: fresh6 after checker round 10, 20 of 22 right.
- T-124 (Wolf): 311 harvested investor questions reframed to 156 (scratch `q12/t124_reframed.csv`); store `q12.db` (12 hold-out companies + 170 FY25-27 docs) building in Wolf scratchpad `q12/` (log `build3.log`); then a model answers via `python -m reality_engine.scripts.p3ask --db <q12.db>` and Opus grades.
- T-126 (Wolf): Drive files other machines uploaded are now in the T-102 manifest (`drive_index_unlisted`, 122,832 rows added); re-run after any upload.
- T-125 (Wolf): worker `20261108T114201Z-41e0aa80` built `project_rules`/`project_state` tools, never-cut rulings hook, char caps; merged `cec49db`, RULINGS 6.6k and STATE 2.5k chars; Shivam /mcp to load the tools.
- T-127 (Wolf): merged dsh `20261108T124200Z-67ccd079`: merge refused without a worker review row or without tests for new code; third code worker refused; `ruling add` intake. Next round: rule_ledger mapping, full-run checklist gate.
- T-120 (Wolf): pilot10 2019-2024 history build done 17:28 (6,359 docs, kpi 4,771 verified / 22,060 unverified / 3,157 quarantined); T-121 ocr part running (`build.log`), then re-run kpi.
- Waiting Shivam: T-116, T-118, T-121, T-122. Shivam's ticket board (always synced): `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

## Next action
1. Finish q12 build, run T-124 ask + grade, report HTML + xlsx in `D:\RealityEngine\reports\`.
2. Re-run T-118 with guidance/KPI factors on the history db, then T-119.
3. Ticket the `ar_facts` scale/column bug; fresh hidden hold-out for checker round 10.
4. Sweep 3 GB new raw under `D:/RealityEngine/raw/pilot60_history/{HDFCBANK,SBILIFE,INFY,MARUTI,ETERNAL}` to Drive.
5. After any `--part stores`: re-run `--part preferred` then `--part checks`. Shivam must /mcp after server changes.

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
