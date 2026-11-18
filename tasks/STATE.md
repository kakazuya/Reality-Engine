# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-18 09:30 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-15_1530.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.
- T-188 reader bake-off and T-189 answer test: `docs/V2_SCHEMA_CONTRACT.md` s14, `reports/2026-11-12_four_model_answer_test.html`.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
0a. 18 Nov 09:30 (Eagle): stores moved to C: SSD (C:/RealityEngine, junctions at D: paths; raw PDFs stay on D: raw_docs_from_stores). R-020 MERGED (23607cb5) and in 84/91 live stores; 7 held (c06 c12 c20 c40 c44 c62 c87: a right or possibly right figure lost, read pages; R-020 note). R-013 + FY fix in 82/91; R-021 in 85/91 (+R-021b, R-022). Held: c09 c31 c61 c87 c88 (jumbled scans: confirmed rows lost with no XBRL, sample mixed right/wrong; needs page reads) and c75 (December year-end). --accept refuses a changed live store. ar_notes: as-filed+restated (c72 fixed). Filing register + link follower MERGED, run on 91 (Wolf). Wolf: results/AR fetched (R-014); next c02 c07 c39 re-run, c59 results doc, no-call-held records. Then notes PP&E/CWIP, commitments, ratios; trial 2.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c10`. Repair notes R-001..R-006 as cards (code, tables, tags, scope) in `tasks/store_repair/INDEX.md`; grid stores x parts `reports/store_repair_grid.xlsx` (`store_repair note grid`). 16 Nov: R-004 MERGED (re-run on c01 after R-005, then c02-c09, hand-read each); R-005 KPI lakh unit fixed, accepted c01 c03 c04 c07, refused c02 c05 c06 c08 c09 c10 await hand-read. R-002: 34 of 37 no-transcript companies filed none on either exchange (record no call filed); 600 NSE transcripts on Drive (`raw/nse_announcements/tg_queue_2026-11-16`), BSE feed 19 Oct-16 Nov fetching into `analysis/bse_announcements.db` (stores read `reality_engine/data/` copy: copy rows across). Next session: read `tasks/handoff/T-217_T-218_T-219_HANDOFF_2026-11-16c.md` (jobs to restart, open items). Proposed: two-tier fixes + per-company completeness check.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0; next checks on Telegram stores, frozen halves.
3. T-210 merged; T-211 monthly job next (Wolf).
5. T-216 agy DNS retry.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.

