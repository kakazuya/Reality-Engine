# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-08 22:00 IST (Wolf, wrap-up at 400k)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies). Off-pilot verified rows: fresh6 after checker round 10, 20 of 22 right.
- T-124 (Wolf): re-ask2 of the 72 still-partly (9 Nov, rebuilt store): 30 right / 41 partly / 1 wrong; pilot set now 558/600 = 93.0%; of the 41, ~17 are undisclosed or documents not held; report `D:\RealityEngine
eports6-11-09_t124_reask2_72.xlsx`. Repeat faults: TTM vs FY, pre-window policy chain, Infosys parent guarantee, Maruti EV without investments.
- T-128 `pilot3_tech` (reaction, gaps, Wilder RSI, SMA crosses, volume spikes, range) merged. Store defects: shp tables empty in live pilot10 (fixed on copy), MARUTI net debt omits investments.
- T-125/126/127 merged (tools, Drive index, gates): merge refused without a worker review row or without tests for new code; third code worker refused; `ruling add` intake. Next round: rule_ledger mapping, full-run checklist gate.
- Waiting Shivam: T-116, T-118, T-121, T-122. Shivam's ticket board (always synced): `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

## Next action
Running 8 Nov 23:40 (Wolf): (a) re-ask2 DONE (graded, report written, worktrees removed); (b) q12 rebuild in order (`<bea35aad scratch>/q12/build5.sh`, log build5.log), then answer the 156 (briefs `T-124_q12_{C,D}_brief.md`); (c) T-130 unseen set u8 (8 companies): agy harvest DONE: 268 verified questions (company-specific + standard/conceptual) in `D:/RealityEngine/u8/questions/t130_questions_{a,b}.csv`; next Opus reframes them once the u8 store is built; u8 store builds after q12 (`<Wolf 82841833 scratch>/u8/build.sh`, no local OCR: HP only).
Done 8 Nov: live pilot10 rebuilt (backup `pilot10/scratch/pilot10_before_reask2_2026-11-08.db`): shp_pledge 73, shp_category 3,285, net_debt_all_investments line, segments read XBRL from Drive (rebuild had silently lost 1,334 rows); regression pilot10 31/31, all sets baseline (1 FAIL KIMS). Shivam: /mcp to restart reality-data. Lesson: never copy a db over one with a -wal file (stale WAL corrupted the swap; delete -wal/-shm first).
Later: history OCR (paused 18:24), T-127 round 2, T-118 re-run.

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
