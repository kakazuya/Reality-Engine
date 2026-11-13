# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-13 23:55 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-12_1410.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

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
000000. Shivam 13 Nov 23:50 (Eagle): roles for answer tests: DeepSeek builds, `gemini-4-hydrogen-high` (agy) answers, Opus 5.5 medium (agy `claude-opus-5-5-medium`) grades blind. Order: T-205 r13 = tool run seeded with the pack (arm S) vs pack path answered by Hydrogen (arm P), graded with r12/ds_a/ds_b; gather rounds on top in r14 (`tasks/handoff/T-205_R13_BRIEF.md`). Verdict on >=3 unseen companies: T-208 (KEI, MEDANTA, PVRINOX stores). T-209 universe SHP + pledge + balance sheet.
00000. Claude directs and reviews only; DeepSeek builds (13 Nov). T-207 MERGED: 6 stable factors need only P&L, promoter, insider, prices (`docs/research/T-207_factor_rewards.md`).
0000. T-205 r12 branch `dsh/20261113T103928Z-0a9aa11d` (c264b5a3, NOT merged; r13 builds on it): 40/64 right vs old tool runs 43, 46. BS-040 grade was wrong: `report_r12/BS-040_check.md`.
000. T-199 BLUESTARCO 13 Nov NOT passed (DeepSeek 82.8% / 73.4%, Haiku 56.2%). Store 45,173 atoms (25,672 verified). Open: derived capital_employed, page_reader doc types.
0. T-192 r5 MERGED 19:20 (MARUTI exports FY26->FY25 in 2 rows: follow-up). Live rebuilt 12 Nov 20:15 (all parts rc=0): aurobindo, pilot10, n10 (backups `*_before_t192_2026-11-12.db`). u8/p20/q12 NOT rebuilt (wait for page-by-page extraction).
1. T-191: `aurobindo_ab/STORE_DEFECTS_SEEN.md`.
2. T-194: events built on aurobindo only.
3. T-163/T-132 branches kept as archive/ tags (I-015); KPI guards 67ceeb28 needs rebase.
4. T-179; `pilot3_fin` XBRL-first; s10 + T-172.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff before a store merge: `reality_engine.scripts.store_diff` (DEVELOPER_GUIDE).

