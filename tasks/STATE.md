# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-13 17:20 IST (Wolf)
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
00000. Shivam 13 Nov: Claude directs and reviews only; DeepSeek workers build. Board cut to 51 open (I-013..I-015). T-207 r1+r2 MERGED, audit clean, awaits Shivam: 6 stable factors need only P&L, promoter, insider, prices; 24m selection fails (stale signs) (`docs/research/T-207_factor_rewards.md`).
0000. T-205 (Wolf, 13 Nov 21:15): branch `dsh/20261113T103928Z-0a9aa11d` (c264b5a3, NOT merged): menu plan -> union gather -> reading copy -> one answer call -> script calc + citation check. Judge of packs: enough 41 / partly 23 / missing 0 of 64. Blind headless-Opus grade, 64 seen q: new path 40 right (62.5%), old tool runs 43 and 46 (13 Nov: 47, 53). Losses: routing 17. Packs judged enough 33/41 right, partly 7/23. NOT passed. Next (Shivam rules): second gather round, or tool run seeded with the pack. Details: JOURNAL 13 Nov Wolf; `bluestar/report_r12`.
000. T-199 BLUESTARCO 13 Nov NOT passed (DeepSeek 82.8% / 73.4%, Haiku 56.2%). Store 45,173 atoms (25,672 verified). Open: derived capital_employed, page_reader doc types.
0. T-192 r5 MERGED 19:20 (MARUTI exports FY26->FY25 in 2 rows: follow-up). Live rebuilt 12 Nov 20:15 (all parts rc=0): aurobindo, pilot10, n10 (backups `*_before_t192_2026-11-12.db`). u8/p20/q12 NOT rebuilt (wait for page-by-page extraction).
1. T-191: `aurobindo_ab/STORE_DEFECTS_SEEN.md`.
2. T-194: events built on aurobindo only.
3. Branches T-163 r4-7 / T-132 r10-12 unreviewed (I-015); CHOLAFIN waits for Shivam.
4. T-179; `pilot3_fin` XBRL-first; s10 + T-172.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff before a store merge: `reality_engine.scripts.store_diff` (DEVELOPER_GUIDE).

