# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 09:05 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Report for Shivam: `D:/RealityEngine/reports/2026-11-09_overnight_report.html` (section 0 = morning update).
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`; live pilot set `pilot10/pilot10.db`.
- T-143 p20 baseline graded: 126 right / 102 partly / 2 wrong of 230 (P 53/57/1, Q 73/45/1); partly: undisclosed 57, held-not-read 20, raw missing 14, reading 10. Reports `reports/2026-11-09_t143_p20_baseline.*`. This is the v2 baseline.
- T-124 q12: C + D(SAIL 15) graded 42/41/1 + 9 scope_out (`reports/2026-11-09_t124_q12_C_D15.*`). D stopped at 15/78 (HP MCP hung under 5 subagents). D2 = the other 63 qids, brief `<Wolf scratch>/T-124_q12_D2_hp_brief.md`, questions `q12/answers/questions_D2.json`; start on HP after 09:30.
- SHP XBRL fetch (19 cos without xbrl SHP: u8 all incl CIPLA, KIMS, 8 p20) into `D:/RealityEngine/raw/nse_shp_xbrl_pilot` via `fetch_shp_xbrl_pilot --universe <scratch>/shp_universe.csv`; then rerun `--part stores` (shp) for u8, q12, p20.
- Gaps found: q12/p20 valuation series start 2023-10-03 (prices held from 2019: build window); Edelweiss announcements end 2024-03; 3 Edelweiss "2026-08-28 transcripts" are the 2016 Investor Day; ADANIPORTS transcripts 1-page stubs; price data ends 2026-11-03.
- Go key 2 hit 429 at 01:52: use account='1'. HP pwsh broken (spawn EPERM): HP workers answer via MCP; run number_check after.
- Waiting Shivam: T-131 OK, semantic search order, T-116, T-118, T-121, T-122.

## Next action
1. After 09:30: `hp_worker start <D2 brief> --pilot-db D:/RealityEngine/q12/q12.db --permission danger-full-access --account 1`; watch; copy `.tmp/*_answers.jsonl` to `q12/answers/D/`; number_check; grade; merge grades with `D/grades_D_part1.json`; rerun `answer_run_report --name t124_q12`.
2. SHP fetch done -> rebuild shp stores for u8/q12/p20 (store copy recipe), re-ask the SHP partlies.
3. Fix build window: valuation_daily/price from 2019 in pilot3 profile for new sets.
4. Answer-brief lines now in D2 brief (each quarter's deck; source known by as_of; no cross-company figures; TTM = 12 months by ex-date; scale-check AUM): carry into the standard brief.
5. After T-131 OK: T-132 brief (contract section 8), T-134 period engine brief.
6. raw_to_drive sweep for u8 + p20 raw + new SHP files.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
