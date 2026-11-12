# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-12 01:45 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-12_0145.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page, text or image; DeepSeek budget ~USD 100-200/month, free models first)
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`. u8/p20/q12 replaced 11 Nov 17:10 by rebuilds (T-161..T-166, v8.1, T-187); backups `*_before_rebuild_2026-11-11.db`. reality-data MCP restart needed (also loads `pilot3_fact`).
- Extraction: `v2/page_words.py` (text layer/OCR) -> `v2/page_layout.py` -> `v2/page_route.py` (T-189, four routes; only table_or_chart is read, on the page IMAGE) -> `v2/reference_geom.py` position check (T-185) -> `v2/page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go; Kilo key 1 exhausted, Dots `@kilo2` quota ran out 12 Nov 00:31.
- T-188 reader bake-off (30 frozen2 pages, P/R): Haiku 91.1/95.2, Dots image 83.8/89.6, DeepSeek image 82.9/75.0, GLM-OCR local 80.8/64.4; details `docs/V2_SCHEMA_CONTRACT.md` s14 and `D:/RealityEngine/v2/reference_pages_frozen2/`.
- T-189 AUROPHARMA unseen test (12 Nov): 47/69 right = 68.1%, NOT passed (bar 92%); +6 correctly not held = 76.8%. Misses: answerer stopped early / no as_of on page reads 12, filing not fetched/extracted 6 (Q2FY27 transcript; SHP only promoter/public, no pledge), wrong row 2, arithmetic 2, page reading 0. Served cells P95.8/R85.8 on 20 hand-read pages. Report `D:/RealityEngine/reports/2026-11-12_aurobindo_test.html`; xlsx `2026-11-12_auropharma_t189.xlsx`; files `D:/RealityEngine/aurobindo/`.
- Disclosures (ledger): p20 99.6% fitted to its own questions (honest 54.8%); T-189 reader arms (Dots quota ran out, Haiku 166 pages, DeepSeek 16 pages deleted), HP MSIX missing.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (one call: preferred figure + source + known_at + inputs; XBRL first for annual lines; mismatch flag), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm + local readers.

## Next action
0. T-189 follow-ups (no per-company fixes): answerer must search more and pass as_of on `page`; fetch the newest call transcript; extract all SHP categories + pledge; fix share count from rounded capital, guidance stored as printed margin, call period Q1FY31; page_route over-routes (V2 s15). Then a fresh company. Unmerged branches: CHOLAFIN KPI (0 right rows lost on 5 stores, DEVELOPER_GUIDE conflict) waits for Shivam.
1. Restart reality-data; re-run the T-179 answer timing with `pilot3_fact` (calls and seconds per answer).
2. Guidance precision round: added rows 13/20 right in a grader sample; add a `gross_margin` metric (BEL 42%, DLF 45% now dropped).
3. `pilot3_fin` serves an annual-report figure before XBRL for annual lines (APOLLOHOSP FY25 revenue): same XBRL-first rule as fact.
4. T-175 garbled text-layer detector; re-run LongCat on frozen2 with a longer timeout; run T-183 on u8 decks/results within free quotas.
5. T-188 follow-up: layout/region crop before local readers (GLM-OCR), and a Dots + DeepSeek cross-check combination scored on frozen2.
6. s10 store + T-172 frozen split + T-170 baseline; T-166 follow-ups; board backfill.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy.

## Merge recipe
Grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
