# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-08 20:45 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies). Off-pilot verified rows: fresh6 after checker round 10, 20 of 22 right.
- T-124 (Wolf): re-ask of the 136 pilot partials done 20:40: 64 right / 70 partly / 2 wrong by hand read (pilot set now 528/600 = 88.0%); report `D:\RealityEngine\reports\2026-11-08_t124_reask_136_partials.xlsx`, grades `D:\RealityEngine\pilot10\answer_reask\graded.jsonl`. q12 store (12 hold-out cos) building in `<Wolf scratchpad bea35aad>/q12/` (`build3.log`, then `build4.sh` reruns stores..checks with the known_at fix, log `build4.log`); 156 questions ready in `D:\RealityEngine\q12\answers\questions_{C,D}.json`, briefs `tasks/handoff/T-124_q12_{C,D}_brief.md`.
- Store defects found: `shp_pledge` and `shp_holder` empty in live pilot10.db; MARUTI net debt leaves out non-current investments.
- T-129 (worker, 8 Nov): kpi default takes the year-to-date period a call/release states (Q2 -> H1, Q3 -> 9M, Q4 keeps FY, annual reports unchanged) -- 294 periods moved on a pilot10 copy; `derive_quarters` wrote 51 derived Q2/Q3/Q4 flow rows; number_check fails `source_scale_mismatch` (MARUTI-127 only, 2 entries: 4,136 and 18,740 crore sourced in million). All 51 derived rows come back quarantined (synthetic quote): `row_checks.py` needs a derived-row rule before they serve. Blueprint 9j.
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
7. T-129: add a derived-row rule to `row_checks.py` (the 51 `derived_cumulative_v1` rows fail `quote_on_page` / `label_present` on the synthetic quote, so all 51 are quarantined) and re-run `--part checks`; then rebuild the live kpi part (294 periods move).

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
