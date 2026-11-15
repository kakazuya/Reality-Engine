# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-15 16:30 IST (Wolf)
History `docs/state_history/` (previous: `STATE_2026-11-15_1530.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

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

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
0. Roles: DeepSeek builds; agy `gemini-4-argon-high` first, then Hydrogen high (high only); Haiku reads images; Opus medium grades blind. Go key 1 only.
1. T-214 Telegram build: plan + pre-build fix order in `tasks/handoff/T-214_TG_BUILD_PLAN.md`; queue `D:/RealityEngine/tg_build/build_queue.csv` (93: tiers 11/6/76, PEAD score via Haiku). T-215 DONE 15 Nov (delete scoped to --root; the 603 GB were `drive:` pseudo-path rows). T-178 DONE: audit-only (re-keyed first-build deck facts recall 47.4% vs script 26.9%, frozen precision 78.3% < 95%); xlsx `D:/RealityEngine/reports/2026-11-11_t178_first_build_rekey.xlsx`; AR fiscal-year by filing_month_rule 7.5% wrong. Next: 10-company measured build.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0 (not blind, report s5b). Next checks (theme calls, C4 figure) measured on Telegram stores with frozen halves.
3. T-210 MERGED 15 Nov: factor_deep peak 0.64 GB; results `docs/research/T-210_factor_deep_study.md`, outputs `D:/RealityEngine/research/t210_2026-11-14/`. Sparse arm flawed (complete-case coverage). T-211 monthly job next (Wolf).
4. T-212 DONE 15 Nov: Q2FY27 XBRL 5,242 filings / 2,904 symbols; raw swept to Drive.
5. T-216 agy retry on DNS drops. T-209: raw `nse_shp_xbrl_universe` on Drive (27,307 files, md5-checked), local copy deleted 15 Nov.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff before a store merge: `reality_engine.scripts.store_diff` (DEVELOPER_GUIDE).

