# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-14 13:50 IST (Wolf)
History `docs/state_history/` (previous: `STATE_2026-11-14_0220.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10 (T-161..T-166, v8.1, T-187), backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go; Kilo key 1 exhausted, Dots `@kilo2` quota ran out 12 Nov 00:31.
- T-188 reader bake-off (30 frozen2 pages, P/R): Haiku 91.1/95.2, Dots image 83.8/89.6, DeepSeek image 82.9/75.0, GLM-OCR local 80.8/64.4; details `docs/V2_SCHEMA_CONTRACT.md` s14 and `D:/RealityEngine/v2/reference_pages_frozen2/`.
- T-189 AUROPHARMA (12 Nov): Haiku 81.2%, DeepSeek 76.8% (`reports/2026-11-12_four_model_answer_test.html`).

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (preferred figure + source + known_at + inputs), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm.

## T-192 (merged 12 Nov)
Rules and rebuilt-copy numbers: `docs/PILOT3_BLUEPRINT.md` s9p and DEVELOPER_GUIDE T-192 bullets (ROE average equity, company EBITDA first, `count_basis`, sentence-scope entities with `entity_unsure`, filing-quarter call periods, Q4 flows keep the year).

## Next action
0. Roles: DeepSeek builds; agy `gemini-4-hydrogen-high` answers, searches questions, codes on trial (shell works with the skip flag); Opus 5.5 medium grades blind. Go key 1 only (restart dsh-worker MCP).
1. DONE 14 Nov 05:00 (Wolf): r13 blind grades, report `D:/RealityEngine/reports/2026-11-14_r13_grading.html`. Paired BS-001..026: Hydrogen pack 24, DS lean B 22, DS pack 20, DS lean A 19; full 64: DS B 54, A 50, pack 46. 36 of 44 misses = routing. Wolf graded batches 2-8 inline (agy quota).
2. T-213: r14 archived (tag `archive/Wolf-T-213-r14b`). r15 MERGED 14 Nov: `answer/answer_checker.py` (C1-C5) + DeepSeek repair of flagged answers: run B 54/9/1 -> 57/7/0 (Wolf, not blind; report s5b). Left: facts in older calls never opened (BS-026/027/034/036). Next: theme-calls check.
3. T-212: Q2FY27 XBRL 2,597 symbols. Session cron died at close: run the fetch+parse by hand after 15 Nov 09:17, then raw_to_drive. T-208 r3 MERGED, s10 + bluestar rebuilt; verdict pending.
4. T-209 MERGED: `D:/RealityEngine/structured/structured_universe.db`; pledge flag 0 = 0%. Raw `nse_shp_xbrl_universe` to Drive pending.
5. T-210 panel needs 7 GB; MSI idles at ~5.9 GB free: run on HP or chunk it. `python -m reality_engine.research.factor_deep --out .tmp/t210 --project`.
6. T-207 accepted 14 Nov as continuous: T-211 = month-end re-run job (Wolf). KPI guards 67ceeb28 port: redo. BS-040 grade wrong (`report_r12/BS-040_check.md`). T-172 frozen split; T-191; T-194; T-179.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff before a store merge: `reality_engine.scripts.store_diff` (DEVELOPER_GUIDE).

