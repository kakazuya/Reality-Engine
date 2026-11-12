# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-12 19:20 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-12_1410.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10 (T-161..T-166, v8.1, T-187), backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go; Kilo key 1 exhausted, Dots `@kilo2` quota ran out 12 Nov 00:31.
- T-188 reader bake-off (30 frozen2 pages, P/R): Haiku 91.1/95.2, Dots image 83.8/89.6, DeepSeek image 82.9/75.0, GLM-OCR local 80.8/64.4; details `docs/V2_SCHEMA_CONTRACT.md` s14 and `D:/RealityEngine/v2/reference_pages_frozen2/`.
- T-189 AUROPHARMA, 4 models graded (12 Nov): Haiku 81.2%, DeepSeek 76.8%, Gemini 72.5%, MiMo 25/41; none passes 92%. Top miss = stopped early. Report `D:/RealityEngine/reports/2026-11-12_four_model_answer_test.html`. 12 Nov: SHP XBRL fetched (all categories, pledge, exact share count); Q2FY27 transcript not on BSE yet.
- HP TextRecognizer 1.0.1.0 installed and kept (T-190; key deleted, cert TrustedPeople only).
- Disclosures (ledger): p20 99.6% fitted to its own questions (honest 54.8%); T-189 reader arms (Dots quota ran out, Haiku 166 pages, DeepSeek 16 pages deleted), HP MSIX missing.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (preferred figure + source + known_at + inputs), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm.

## T-192 (merged 12 Nov)
Rules and rebuilt-copy numbers: `docs/PILOT3_BLUEPRINT.md` s9p and DEVELOPER_GUIDE T-192 bullets (ROE average equity, company EBITDA first, `count_basis`, sentence-scope entities with `entity_unsure`, filing-quarter call periods, Q4 flows keep the year).

## T-204 (12 Nov, branch)
`fetch_pilot60_history --fetch --out` now writes the run's universe rows (T-189 step 1 needs no ISIN filter); `coverage.documents` is capped at `max(limit*3,10)` (`documents=all` for every one, `documents_not_listed` counts the rest, `hidden_documents` in `coverage` only), a store without `page_cell` names it in `not_searched` only, and a `pilot3_topic` page is sized to its items (`max(6 kB, 3 kB x limit)`, 18 kB cap). KEC order book limit=2 as_of 2026-10-19: 8.1 -> 5.9 kB, 10 of 49 documents listed. Tests: `test_lookups_pilot3.py` 72 passed + 1 skipped, `test_fetch_manifest_out.py` 3, `test_pilot3_no_company_literals.py` 7, `test_store_routing.py` 7.

## Next action
000. T-199 BLUESTARCO atom test: hand-off `tasks/handoff/T-199_BLUESTAR_ATOM_PLAN.md` (fresh session: wait for T-202 merge, delete partial bluestar.db, build, route, OCR, atom brief). MERGED 12 Nov: T-197, T-198, T-201, T-203. RUNNING: T-202 round 2 20261112T173001Z-e88d8f6c.
00. T-195 DONE: re-run after fixes, DeepSeek 85.5% / 84.1% (2 runs), Haiku 76.8%; `reports/2026-11-12_aurobindo_rerun.html`. T-196 DONE (`reports/2026-11-12_why_answers_stop.html`).
0. T-192 r5 MERGED 19:20 (MARUTI exports FY26->FY25 in 2 rows: follow-up). Live rebuilt 12 Nov 20:15 (all parts rc=0): aurobindo, pilot10, n10 (backups `*_before_t192_2026-11-12.db`). u8/p20/q12 NOT rebuilt (wait for page-by-page extraction).
1. T-191 A/B DONE (`reports/2026-11-12_semantic_ab.html`); route `aurobindo_ab/STORE_DEFECTS_SEEN.md` to follow-ups.
2. T-194 MERGED 18:00; events built on aurobindo only.
3. Branches: T-163 r4-7 / T-132 r10-12 need review; CHOLAFIN waits for Shivam.
4. T-179 timing; guidance `gross_margin`; `pilot3_fin` XBRL-first; T-175; T-188; s10 + T-172.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff before a store merge: `reality_engine.scripts.store_diff` (DEVELOPER_GUIDE).
