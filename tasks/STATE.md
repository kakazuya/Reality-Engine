# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-16 17:15 IST (Wolf)
History `docs/state_history/` (previous: `STATE_2026-11-15_1530.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.
- T-188 reader bake-off and T-189 answer test: `docs/V2_SCHEMA_CONTRACT.md` s14, `reports/2026-11-12_four_model_answer_test.html`.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact`, T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm.

## T-192 (merged 12 Nov)
Rules and rebuilt-copy numbers: `docs/PILOT3_BLUEPRINT.md` s9p and DEVELOPER_GUIDE T-192 bullets (ROE average equity, company EBITDA first, `count_basis`, sentence-scope entities with `entity_unsure`, filing-quarter call periods, Q4 flows keep the year).

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
0a. 16 Nov (Shivam): build ALL 91, then random trials. Running: `tg_measure_build` on `measure10/universe91.csv`; HP OCR loop to 05:40. Next: merge OCR into pages.db, then trial 1.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c10`. Repair notes R-001..R-006 as cards (code, tables, tags, scope) in `tasks/store_repair/INDEX.md`; grid stores x parts `reports/store_repair_grid.xlsx` (`store_repair note grid`). 16 Nov: R-004 MERGED (re-run on c01 after R-005, then c02-c09, hand-read each); R-005 KPI lakh unit fixed, accepted c01 c03 c04 c07, refused c02 c05 c06 c08 c09 c10 await hand-read. R-002: 34 of 37 no-transcript companies filed none on either exchange (record no call filed); 600 NSE transcripts on Drive (`raw/nse_announcements/tg_queue_2026-11-16`), BSE feed 19 Oct-16 Nov fetching into `analysis/bse_announcements.db` (stores read `reality_engine/data/` copy: copy rows across). Next session: read `tasks/handoff/T-217_T-218_T-219_HANDOFF_2026-11-16c.md` (jobs to restart, open items). Proposed: two-tier fixes + per-company completeness check.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0 (not blind, report s5b). Next checks (theme calls, C4 figure) measured on Telegram stores with frozen halves.
3. T-210 MERGED 15 Nov: factor_deep peak 0.64 GB; results `docs/research/T-210_factor_deep_study.md`, outputs `D:/RealityEngine/research/t210_2026-11-14/`. Sparse arm flawed (complete-case coverage). T-211 monthly job next (Wolf).
5. T-216 agy retry on DNS drops.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.

