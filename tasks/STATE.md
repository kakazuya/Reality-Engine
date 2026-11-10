# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-10 10:40 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`, prices/valuation 2019 -> 9 Nov 2026; pilot set `pilot10/pilot10.db`. Go key 1 only.
- Pilot20 FINAL 9 Nov (strict dates + Shivam's ruling: unpublished = 'data not found' + nearest supporting point): **229 / 230 right** (`reports/2026-11-09_p20_final_230.xlsx`); without the ruling 211. Only ADANIPORTS-005 left (figure only on a later transcript). Call questions dated at transcript filing (`questions_P/Q.json` keep `as_of_original`).
- T-154 semantic stays (Shivam), alongside the table store; index `p20/embed/` (~$0.48 spent).
- Merged today: T-134 period engine, T-155 prices from 2019, T-139 rating rationales (41 texts, `D:/RealityEngine/outside_doc/ratings_p20`), T-132 round 1 (cells store `D:/RealityEngine/v2/p20_r1`, ~8/30 right), T-156 sql as_of guard, T-157 transcripts (p20 135 -> 151).
- Waiting Shivam: T-116, T-118, T-121, T-122, T-125, T-126.

## Running
- LIVE DEFECT p20 kpi_series: 1,466 OFCF rows stored as capex (fixed on main by T-133; KPI rebuild after v8.1).
- T-160 n10 (AUBANK BALRAMCHIN SRF LT DMART TATAPOWER ICICIGI DIXON JUBLFOOD MCX): agy harvest 20261109T182713Z-4d398312; build `D:/RealityEngine/n10/build.sh` (fetch running). Held audit DONE: 82/106 u8+q12 misses answerable from held docs (`reports/2026-11-10_held_not_queryable_audit.xlsx`) -> T-161..T-166. Bake-off LongCat vs Beam `night_loop/bakeoff_lc_beam` running.

- T-132 r9 MERGED 09:45 (Opus results 21/30, deck 22/30, replay 136/136; store `D:/RealityEngine/v2/p20_r9`, samples `D:/RealityEngine/v2/review/samples`); r10 job 20261110T041508Z-c1d00b5c (`tasks/handoff/T-132_r10_brief.md`). Headless Opus grading STOPPED (Shivam 10 Nov 10:30): reviews now by a separate read-only dsh worker. T-133 v8 MERGED 10:55 (dsh review: 190/200, live KPI +253 right/0 lost; review `plugins/dsh-worker/runtime/jobs/20261110T050407Z-6337de5b/result.md`); v8.1 (`tasks/handoff/T-133_v81_brief.md`) MUST land before any KPI rebuild (~30 junk dividend_income/total_income cells). T-165 done (12/12 claimed, 32 tests) under dsh review 20261110T052537Z-7ecaeb7d; T-133 v8.1 running 20261110T052550Z-491c3466. Queued (no dsh starts 11:30-15:30): T-166, T-164, T-163 (`tasks/handoff/T-16x_*_brief.md`). T-162 code merged 10 Nov (SHP known_at = earlier pm-safe file stamp; 29/25/34 p20/u8/q12 filings move earlier) -> takes effect with the same rebuild. T-161/T-159 merged (b9e58ae5; PILOT3_BLUEPRINT 9m): `docs_collect --measure` = 15 retypes, 0 re-dates -> rebuild p20/u8/q12 docs + transcripts/guidance, restart MCP.

## Next action
1. Carry into every answer brief: strict as_of on all tools incl. sql; search-before-'not found' with the searched list; nearest supporting point labelled (ruling 9 Nov, T-158 gate).
2. T-157 follow-up: Coal India 9, Havells 3, Titan 1 calls not found (widen BSE subject filter); run the fetcher on u8 and q12.
3. T-133 label map: families approved per family after merge; then T-150 units at write.
4. T-139 step 2 merged 22:20: `pilot3_ratings` / `p3ask ratings` over `D:/RealityEngine/outside_doc/ratings.db` now p20+u8+q12: 138 rationales, 592 actions, 28 cos (9 Nov 23:59). Next: India Ratings detail JSON, monthly industry data.
5. Standard answer brief: carry the strict-PIT and 'not disclosed' rules from `<Wolf scratch>/T-156_round4_hp.md`.
6. raw_to_drive sweep (u8 + p20 raw, SHP, transcripts_raw, raw_market masters copied back today).

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row first; merge --no-ff --no-commit; drop PROGRESS_NOTES.md; tests per file; docs; commit `By:`; remove worktree.
