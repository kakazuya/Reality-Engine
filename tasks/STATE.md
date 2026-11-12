# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-12 22:10 IST (T-201)
History `docs/state_history/` (previous: `STATE_2026-11-12_1410.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md`; Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10 (T-161..T-166, v8.1, T-187), backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; table_or_chart read on the page image) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scans confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go; Kilo key 1 exhausted, Dots `@kilo2` quota ran out 12 Nov 00:31.
- T-188 reader bake-off (30 frozen2 pages, P/R): Haiku 91.1/95.2, Dots image 83.8/89.6, DeepSeek image 82.9/75.0, GLM-OCR local 80.8/64.4; details `docs/V2_SCHEMA_CONTRACT.md` s14 and `D:/RealityEngine/v2/reference_pages_frozen2/`.
- T-189 AUROPHARMA, 4 models graded (12 Nov): Haiku 81.2%, DeepSeek 76.8%, Gemini 72.5%, MiMo 25/41; none passes 92%. Report `D:/RealityEngine/reports/2026-11-12_four_model_answer_test.html`. SHP XBRL fetched (all SHP categories); Q2FY27 transcript not on BSE yet.
- HP TextRecognizer 1.0.1.0 installed (T-190; cert TrustedPeople only).
- Disclosures (ledger): p20 99.6% fitted to its own questions (honest 54.8%); T-189 reader arms (Dots quota ran out, 182 pages deleted), HP MSIX missing.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (preferred figure + source + known_at + inputs), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm.

## T-192 (merged 12 Nov)
Rules and rebuilt-copy numbers: `docs/PILOT3_BLUEPRINT.md` s9p and DEVELOPER_GUIDE T-192 bullets (ROE average equity, company EBITDA first, `count_basis`, sentence-scope entities with `entity_unsure`, filing-quarter call periods, Q4 flows keep the year).

## Next action
000. T-198 MERGED 21:55 (label qualifier = definition, like-for-like cross_doc, fact `company_stated`); run `--part checks` on live stores. T-197 RUNNING 20261112T153055Z-22cfe831. T-199 BLUESTARCO question harvest (agy 20261112T160642Z-e26e8c9d), freeze before build; atom design after T-197.
00. T-195 DONE: re-run after fixes, DeepSeek 85.5% / 84.1%, Haiku 76.8%; `reports/2026-11-12_aurobindo_rerun.html`. T-196 DONE (`reports/2026-11-12_why_answers_stop.html`).
0. T-192 r5 MERGED 19:20 (MARUTI exports FY26->FY25 in 2 rows: follow-up). Live rebuilt 12 Nov 20:15 (all parts rc=0): aurobindo, pilot10, n10 (backups `*_before_t192_2026-11-12.db`). u8/p20/q12 NOT rebuilt (wait for page-by-page extraction).
1. T-191 A/B DONE (`reports/2026-11-12_semantic_ab.html`): Haiku 54 vs 54; DeepSeek 53 vs 42 but semantic touched no flip. Route `aurobindo_ab/STORE_DEFECTS_SEEN.md` to follow-ups.
2. T-194 MERGED 18:00; events built on aurobindo only.
3. Branches: T-163 r4-7 / T-132 r10-12 need review; CHOLAFIN waits for Shivam.
4. T-179 timing; guidance `gross_margin`; `pilot3_fin` XBRL-first; T-175; T-188; s10 + T-172.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Store diff (T-201): `python -m reality_engine.scripts.store_diff --store <db> --profile <json> --parts <parts> --base main --head <ref>`; gates a merge. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
