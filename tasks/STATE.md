# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-08 21:10 IST (T-128 worker)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies). Off-pilot verified rows: fresh6 after checker round 10, 20 of 22 right.
- T-124 (Wolf): re-ask of the 136 pilot partials done 20:40: 64 right / 70 partly / 2 wrong by hand read (pilot set now 528/600 = 88.0%); report `D:\RealityEngine\reports\2026-11-08_t124_reask_136_partials.xlsx`, grades `D:\RealityEngine\pilot10\answer_reask\graded.jsonl`. q12 store (12 hold-out cos) building in `<Wolf scratchpad bea35aad>/q12/` (`build3.log`, then `build4.sh` reruns stores..checks with the known_at fix, log `build4.log`); 156 questions ready in `D:\RealityEngine\q12\answers\questions_{C,D}.json`, briefs `tasks/handoff/T-124_q12_{C,D}_brief.md`.
eports6-11-08_t124_reask_136_partials.xlsx`, grades `D:\RealityEngine\pilot10nswer_reask\graded.jsonl`. q12 store (12 hold-out cos) building in `<Wolf scratchpad bea35aad>/q12/` (`build3.log`, then `build4.sh` reruns stores..checks with the known_at fix, log `build4.log`); 156 questions ready in `D:\RealityEngine\q12nswers\questions_{C,D}.json`, briefs `tasks/handoff/T-124_q12_{C,D}_brief.md`.
- T-128 (worker, 8 Nov): `pilot3_tech` computes filing-day reaction, gaps (held/fill), Wilder RSI with divergence, SMA 50/200 and last crosses, volume spikes vs the prior 20 sessions and 52-week range, in `plugins/reality-data/server/lookups_tech.py` (registered + routed in `server.py`, `p3ask tech`); `test_pilot3_tech.py` 15 passed, `test_lookups_pilot3.py` 24 passed / 1 skipped; blueprint 9i. Next: restart the reality-data MCP (no data rebuild).
- Store defects found: `shp_pledge` and `shp_holder` empty in live pilot10.db; MARUTI net debt leaves out non-current investments.
- T-125/126/127 merged (tools, Drive index, gates): merge refused without a worker review row or without tests for new code; third code worker refused; `ruling add` intake. Next round: rule_ledger mapping, full-run checklist gate.
- T-120 (Wolf): pilot10 2019-2024 history build done 17:28 (6,359 docs, kpi 4,771 verified / 22,060 unverified / 3,157 quarantined); T-121 ocr part running (`build.log`), then re-run kpi.
- Waiting Shivam: T-116, T-118, T-121, T-122. Shivam's ticket board (always synced): `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

## Next action
1. When `build4.log` shows Q12_FIX_DONE: copy q12.db to `D:/RealityEngine/q12/q12.db`, start two dsh answer workers with the C/D briefs (worktree, workspace-write, account 1, off-peak), grade by hand, `answer_run_report --name t124_q12_answers`.
2. Ranked fixes for the re-ask misses (final message 8 Nov 20:45): await Shivam's pick, then ticket.
3. History OCR paused 18:24: restart `build --profile tasks/night_loop/pilot10hist_profile.json --out D:/RealityEngine/pilot10/history/pilot10hist.db --part ocr --ocr-max-seconds 30000`, then its kpi.
4. T-127 round 2: rule_ledger mapping, full-run checklist gate.
5. Re-run T-118 with guidance/KPI factors on the history db; ticket the `ar_facts` scale/column bug.
6. Restart the reality-data MCP to serve consolidated-first kpi (commit ffb58fe).

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
