# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-08 22:00 IST (Wolf, wrap-up at 400k)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies). Off-pilot verified rows: fresh6 after checker round 10, 20 of 22 right.
- T-124 (Wolf): re-ask of 136 pilot partials: 64 right / 70 partly / 2 wrong (pilot set 528/600 = 88.0%); report `D:\RealityEngine\reports\2026-11-08_t124_reask_136_partials.xlsx`.
- T-128 `pilot3_tech` (reaction, gaps, Wilder RSI, SMA crosses, volume spikes, range) merged. Store defects: shp tables empty in live pilot10 (fixed on copy), MARUTI net debt omits investments.
- T-125/126/127 merged (tools, Drive index, gates): merge refused without a worker review row or without tests for new code; third code worker refused; `ruling add` intake. Next round: rule_ledger mapping, full-run checklist gate.
- Waiting Shivam: T-116, T-118, T-121, T-122. Shivam's ticket board (always synced): `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

## Next action
Fixing the 70 partly + 2 wrong re-ask answers (Shivam 8 Nov). Done: T-128 `pilot3_tech` merged; T-129 (YTD period for flow KPIs, derived quarters, `source_scale_mismatch`) merged with Opus's stock/rate exemption; `row_checks.judge_derived`; `build_shp` empty-folder warning. SHP raw is back in `D:\RealityEngine\raw\nse_shp_xbrl_pilot` (591 files; delete after the rebuild). q12 build STOPPED 21:12 (extract re-ran kpi; ~1 h wasted).
1. Rebuild pilot10 on a copy: `cp D:/RealityEngine/pilot10/pilot10.db D:/RealityEngine/pilot10/scratch/p10_new.db`; parts `stores comparatives preferred ratios kpi segments checks` with `--profile tasks/night_loop/pilot10_profile.json --out <copy>`; check shp_pledge 78 rows, derived kpi rows not all quarantined; `regression_set score --all` (baseline 1 FAIL: KIMS); swap into live; restart reality-data MCP.
2. Re-ask the 72: `D:\RealityEngine\pilot10\answer_reask2\questions_{E,F}.json`; briefs = copy `tasks/handoff/T-124_q12_C_brief.md` pointed at pilot10.db + `tech` tool; two dsh workers (off-peak only), hand-grade, `answer_run_report --name t124_reask2`.
3. q12: run `build --profile <bea35aad scratch>/q12/q12_profile.json --out <scratch>/q12.db --part X` for kpi stores comparatives preferred ratios segments guidance notes checks; then answer the 156 (`D:\RealityEngine\q12\answers\questions_{C,D}.json`, briefs `tasks/handoff/T-124_q12_{C,D}_brief.md`).
4. History OCR paused 18:24 (restart cmd in docs/state_history), T-127 round 2, T-118 re-run.

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
