# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 02:05 IST (Wolf: T-135)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`.

## Now
- Live store `D:\RealityEngine\pilot10\pilot10.db` (10 companies). Off-pilot verified rows: fresh6 after checker round 10, 20 of 22 right.
- T-124 (Wolf): re-ask2 of the 72 still-partly (9 Nov, rebuilt store): 30 right / 41 partly / 1 wrong; pilot set now 558/600 = 93.0%; of the 41, ~17 are undisclosed or documents not held; report `D:\RealityEngine
eports6-11-09_t124_reask2_72.xlsx`. Repeat faults: TTM vs FY, pre-window policy chain, Infosys parent guarantee, Maruti EV without investments.
- T-128 `pilot3_tech` (reaction, gaps, Wilder RSI, SMA crosses, volume spikes, range) merged. Store defects: shp tables empty in live pilot10 (fixed on copy), MARUTI net debt omits investments.
- T-135 calc catalog: `p3ask catalog`, 14 formulas, tests 30 pass; MCP + merge pending.
- T-125/126/127 merged (tools, Drive index, gates): merge refused without a worker review row or without tests for new code; third code worker refused; `ruling add` intake. Next round: rule_ledger mapping, full-run checklist gate.
- Waiting Shivam: T-116, T-118, T-121, T-122. Shivam's ticket board (always synced): `D:\RealityEngine\reports\ticket_board.{xlsx,html}`.

- v2 store design (Shivam 9 Nov 01:10, P1): T-131..T-144; plan + lanes + pilot20 proposal in `D:/RealityEngine/reports/2026-11-09_v2_design_plan.html`. Pilot20 new 10 (Bharti, Apollo Tyres, Asian Paints, Titan, Adani Ports, Indian Hotels, Pidilite, Coal India, HDFC AMC, Havells): raw fetch running (`<Wolf 82841833 scratch>/p20/`), baseline on today's design first, then v2 = redesign delta.

## Next action
Wrap-up 9 Nov 01:30 (Wolf, 400k). Running, all on job_watch: q12 rebuild (`<bea35aad scratch>/q12/build5.sh`, still on kpi since 23:34, slow Drive fetches); agy T-154 embedding price check `20261108T195902Z-e3060045` (report cheaper/costlier vs Nemotron); Apollo Tyres BSE fetch (`<Wolf 82841833 scratch>/p20/fetch_apollo.log`, after the p20 fetch).
1. u8 build FAILED at ratios: `ratios._quarters` max() over known_at None (fin_quarter_xbrl rows with no known_at; q12 hit the same at 20:08). Fix: find why stores leaves known_at NULL for u8 (check `SELECT symbol,count(*) FROM fin_quarter_xbrl WHERE known_at IS NULL`), fix at source, test; then rerun parts ratios segments notes checks with `--profile <Wolf 82841833 scratch>/u8/u8_profile.json --out <Wolf 82841833 scratch>/u8/u8.db`; checkpoint + copy to D:/RealityEngine/u8/u8.db; start dsh on `tasks/handoff/T-130_u8_{G,H}_brief.md` (off-peak only); hand grade; `answer_run_report --name t130_u8`.
2. q12: when build5 ends, checkpoint q12.db and copy to D:/RealityEngine/q12/q12.db (no -wal beside it); dsh on `T-124_q12_{C,D}_brief.md`; grade; report.
3. Pilot20 (T-143): p20 raw fetched (`<Wolf 82841833 scratch>/p20/`, profile `p20new_profile.json`, Apollo in, NTPC out); build manifest from pilot60_history/manifest.csv filtered to the 10 into `<Wolf 82841833 scratch>/p20/raw/manifest.csv`, build on today's design (u8 build.sh order); reframe harvest CSVs in `D:/RealityEngine/p20/questions/` (a 165 rows incl. 35 NTPC to drop, b 219; harvest Apollo Tyres separately); baseline answers + grade.
4. T-131 v2 schema contract (Wolf, Shivam OK) from `D:/RealityEngine/reports/2026-11-09_v2_design_plan.html`; lanes there; tickets T-131..T-153. Open question to Shivam: semantic-search ticket after the table store?
5. Sweep new raw (`D:/RealityEngine/raw/pilot60_history/<u8 + p20 symbols>`) to Drive with raw_to_drive after builds. Later: history OCR, T-127 r2, T-118.

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
