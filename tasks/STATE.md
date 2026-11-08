# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-08 17:40 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies). Off-pilot verified rows: fresh6 after checker round 10, 20 of 22 right.
- T-124 (Wolf): 311 harvested investor questions reframed to 156 (scratch `q12/t124_reframed.csv`); store `q12.db` (12 hold-out companies + 170 FY25-27 docs) building in Wolf scratchpad `q12/` (log `build3.log`); then a model answers via `python -m reality_engine.scripts.p3ask --db <q12.db>` and Opus grades.
- T-125/126/127 merged (tools, Drive index, gates): merge refused without a worker review row or without tests for new code; third code worker refused; `ruling add` intake. Next round: rule_ledger mapping, full-run checklist gate.
- T-120 (Wolf): pilot10 2019-2024 history build done 17:28 (6,359 docs, kpi 4,771 verified / 22,060 unverified / 3,157 quarantined); T-121 ocr part running (`build.log`), then re-run kpi.
- Waiting Shivam: T-116, T-118, T-121, T-122. Shivam's ticket board (always synced): `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

## Next action
WRAP-UP 8 Nov 19:25 (Wolf, 400k). Running: q12 build (`<Wolf scratchpad>/q12/build3.sh`, log `build3.log`; kpi 9/12 at 19:24, then stores..checks). History OCR PAUSED at 18:24 to speed q12: restart `build --profile tasks/night_loop/pilot10hist_profile.json --out D:/RealityEngine/pilot10/history/pilot10hist.db --part ocr --ocr-max-seconds 30000`, then re-run its kpi.
1. When q12 shows Q12_DONE: answer the 156 rows of `<Wolf scratchpad>/q12/t124_reframed.csv` via `p3ask --db <q12.db>`, grade, write the JSONL, run `answer_run_report --name t124_q12_answers`.
2. Re-ask the 136 pilot partials (`D:/RealityEngine/pilot10/answer_a3/grades.tsv`) on live pilot10.db, grade, report (offered to Shivam, awaiting yes).
3. HINDUNILVR Beauty & Wellbeing EBIT Q2FY27 stored 1,242 and VERIFIED; results p8 prints 1,235: add to T-122 regression labels, checker fix.
4. T-127 round 2: rule_ledger mapping, full-run checklist gate. Shivam /mcp (dsh-worker for code_worker_limit, reality-data for project_rules).
5. Re-run T-118 with guidance/KPI factors on the history db; ticket the `ar_facts` scale/column bug.

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
