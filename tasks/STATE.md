# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 09:05 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Report for Shivam: `D:/RealityEngine/reports/2026-11-09_overnight_report.html` (section 0 = morning update).
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`; live pilot set `pilot10/pilot10.db`.
- T-143 p20 baseline graded: 126 right / 102 partly / 2 wrong of 230 (P 53/57/1, Q 73/45/1); partly: undisclosed 57, held-not-read 20, raw missing 14, reading 10. Reports `reports/2026-11-09_t143_p20_baseline.*`. This is the v2 baseline.
- T-124 q12: C + D(SAIL 15) graded 42/41/1 + 9 scope_out (`reports/2026-11-09_t124_q12_C_D15.*`). D stopped at 15/78 (HP MCP hung under 5 subagents). D2 = the other 63 qids, brief `<Wolf scratch>/T-124_q12_D2_hp_brief.md`, questions `q12/answers/questions_D2.json`; start on HP after 09:30.
- SHP XBRL fetch (19 cos without xbrl SHP: u8 all incl CIPLA, KIMS, 8 p20) into `D:/RealityEngine/raw/nse_shp_xbrl_pilot` via `fetch_shp_xbrl_pilot --universe <scratch>/shp_universe.csv`; then rerun `--part stores` (shp) for u8, q12, p20.
- Go key 1 only; HP pwsh broken (spawn EPERM): HP workers answer via MCP, run number_check after.
- Waiting Shivam: T-131 OK, semantic search order, T-116, T-118, T-121, T-122.

## T-154 semantic-search gain test (Shivam 9 Nov 14:15: no more embedding comparisons; measure gain on RIGHT answers; DeepInfra balance $0.80)
- Local bake-off DONE and stopped (`tasks/v2/T-154_bakeoff.py`, results `D:/RealityEngine/p20/t154/run_*.json`): 139 q, 16,457 pages, 1050 Ti: FinModernBERT r@5 20.9/r@20 48.9 (4.2 p/s), bge-m3 21.6/43.2 (4.0), bge-small 15.1/30.9 (38.3), FinBERT 2.9/10.8. HP NPU works only with fixed shapes + FP16 (`tasks/v2/T-154_npu_prep.py`): bge-small 17.6 p/s, same recall; QDQ int8 breaks recall (0.7%).
- RUNNING at 14:20: `embed_test embed --model 8b --max-usd 0.45 --out D:/RealityEngine/p20/embed` (REALITY_PILOT3_DB=p20new.db; text only, 14,376 pages FY25+ transcripts/decks/results/press/AR, est $0.37; resumable; log `D:/RealityEngine/p20/embed_8b.log`).
- NEXT: (1) add a `semantic` tool to `reality_engine/scripts/p3ask.py` + MCP (`plugins/reality-data/server`), reading the 8b cache npy/index, query via DeepInfra (gate REALITY_DATA_ALLOW_PAID_EMBED=1), filter symbol + known_at <= as_of; (2) re-ask on the MSI (key in env there, not HP) after 15:30: p20 partly+wrong minus raw_missing (~90) + 30 right as regression check, same brief + semantic tool; (3) hand-grade, report right before/after of 230.

## Next action
1. After 09:30: `hp_worker start <D2 brief> --pilot-db D:/RealityEngine/q12/q12.db --permission danger-full-access --account 1`; watch; copy `.tmp/*_answers.jsonl` to `q12/answers/D/`; number_check; grade; merge grades with `D/grades_D_part1.json`; rerun `answer_run_report --name t124_q12`.
2. SHP XBRL fetched (186 files, 0 failed) and `stores.build_shp` rerun on the three D: stores: all 29 companies now have 9-14 XBRL quarters + pledge rows. Re-ask the SHP partlies (u8 6, q12 ANANDRATHI-r069, IDEA-r113).
3. Fix build window: valuation_daily/price from 2019 in pilot3 profile for new sets.
4. Answer-brief lines now in D2 brief (each quarter's deck; source known by as_of; no cross-company figures; TTM = 12 months by ex-date; scale-check AUM): carry into the standard brief.
5. After T-131 OK: T-132 brief (contract section 8), T-134 period engine brief.
6. raw_to_drive sweep for u8 + p20 raw + new SHP files.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row first; merge --no-ff --no-commit; drop PROGRESS_NOTES.md; tests per file; docs; commit `By:`; remove worktree.
