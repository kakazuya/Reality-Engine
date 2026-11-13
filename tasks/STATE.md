# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-13 16:45 IST (Eagle, close)
History `docs/state_history/` (previous: `STATE_2026-11-12_1410.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10 (T-161..T-166, v8.1, T-187), backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go; Kilo key 1 exhausted, Dots `@kilo2` quota ran out 12 Nov 00:31.
- T-188 reader bake-off (30 frozen2 pages, P/R): Haiku 91.1/95.2, Dots image 83.8/89.6, DeepSeek image 82.9/75.0, GLM-OCR local 80.8/64.4; details `docs/V2_SCHEMA_CONTRACT.md` s14 and `D:/RealityEngine/v2/reference_pages_frozen2/`.
- T-189 AUROPHARMA (12 Nov): Haiku 81.2%, DeepSeek 76.8%; report `reports/2026-11-12_four_model_answer_test.html`.
- HP TextRecognizer 1.0.1.0 installed and kept (T-190; key deleted, cert TrustedPeople only).

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (preferred figure + source + known_at + inputs), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm.

## T-192 (merged 12 Nov)
Rules and rebuilt-copy numbers: `docs/PILOT3_BLUEPRINT.md` s9p and DEVELOPER_GUIDE T-192 bullets (ROE average equity, company EBITDA first, `count_basis`, sentence-scope entities with `entity_unsure`, filing-quarter call periods, Q4 flows keep the year).

## Next action
0000. T-205 evidence pack: r1-r3 merged (`reality_engine/answer/`); r2 judge enough 21/64; r3 judge running (Beam 20261113T100438Z-add44400, `.tmp/judge/pack_judge.csv` in its worktree). Next: read it; if < ~55/64 use a model-written lookup plan -> answer step + number check -> NEW unseen company.
000. T-199 BLUESTARCO DONE 13 Nov, NOT passed: first attempt DeepSeek 82.8% / 73.4%, Haiku 56.2% (blind Opus, 64 frozen q); 60/64 right in some set; losses routing 39, compute 11, reading 6, none missing data. Second pass 84.4%/76.6% (seen). `reports/2026-11-13_bluestar_atom_test.html`. Store: 45,173 atoms (25,672 verified), unseen 20-page sample value 95.5% / recall 81% on financial pages. Next: evidence-pack answerer (script runs every route, model writes from the pack), fix derived capital_employed, page_reader default doc types, then a NEW unseen company.
0. T-192 r5 MERGED 19:20 (MARUTI exports FY26->FY25 in 2 rows: follow-up). Live rebuilt 12 Nov 20:15 (all parts rc=0): aurobindo, pilot10, n10 (backups `*_before_t192_2026-11-12.db`). u8/p20/q12 NOT rebuilt (wait for page-by-page extraction).
1. T-191 follow-ups: `aurobindo_ab/STORE_DEFECTS_SEEN.md`.
2. T-194 MERGED 18:00; events built on aurobindo only.
3. Branches: T-163 r4-7 / T-132 r10-12 need review; CHOLAFIN waits for Shivam.
4. T-179 timing; guidance `gross_margin`; `pilot3_fin` XBRL-first; T-175; T-188; s10 + T-172.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff before a store merge: `reality_engine.scripts.store_diff` (DEVELOPER_GUIDE).

