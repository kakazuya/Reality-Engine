# STATE: the one live state. Last updated 2026-11-12 19:10 IST (T-192 round 5)
History `docs/state_history/` (prev `STATE_2026-11-12_0145.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` s12-15.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10 (T-161..T-166, v8.1, T-187), backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go; Kilo key 1 exhausted, Dots `@kilo2` ran out 12 Nov 00:31.
- T-188 bake-off (30 pages, P/R): Haiku 91.1/95.2, Dots 83.8/89.6, DeepSeek 82.9/75.0, GLM-OCR 80.8/64.4; `V2_SCHEMA_CONTRACT.md` s14.
- T-189 AUROPHARMA unseen test 12 Nov: 47/69 right = 68.1%, NOT passed (bar 92%); +6 not held = 76.8%. Misses: answerer stopped early/no as_of on page 12, filing not fetched 6 (Q2FY27 transcript; SHP no pledge), wrong row 2, arithmetic 2; cells P95.8/R85.8 on 20 pages. Report `D:/RealityEngine/reports/2026-11-12_aurobindo_test.html`.
- Ledger: p20 99.6% fitted to its own questions (honest 54.8%); T-189 arms (Dots quota out, Haiku 166 pages, DeepSeek 16 deleted), HP MSIX missing.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (preferred figure + source + known_at + inputs), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm.

## T-192 (12 Nov; r5 branch `dsh/20261112T115218Z-d827ceff`)
- R4: old-store column tolerance; data-proved entities with `entity_unsure`; own FY/9M/H1/YTD span wins over the call quarter, previous-sentence year fixed, Q4 column never an annual margin; period-scoped EBITDA route; non-results call keeps `call_period` NULL.
- R5: `guidance.sentence_entity` - the sentence's own scope (company, standalone/domestic/consolidated, geography, own project) beats the question's entity; only a scope-free sentence inherits a proven question entity; person names never entities (J1: HINDALCO's four India-capex rows group again). `kpi._q4_annual_flow` - a Q4 call keeps the year for an unlabelled flow (SBILIFE APE 221.1/242.7 bn, market share 21.4% = FY26), a stock at the quarter end takes Q4 (J2).
- Rebuilt both sides: five aurobindo rows right (ROE 9.9/9.93, EBITDA 6,605, FY25 margin 20.8, KPI Q1FY27 21.0, Lannett entity, 575,377,895 filed_exact); pilot10 104->102 group guidance rows (2 true subsidiaries), 0 true group targets lost, KPI 75 period changes = 1.2% of 6,185. `.tmp/T-192_DIFF.md`; live untouched.

## Next action
0. T-192 r5 review: `.tmp/T-192_DIFF.md`; then merge/rebuild live stores from `dsh/20261112T115218Z-d827ceff`. T-189: answerer searches more and passes as_of on `page`; newest transcript; all SHP categories + pledge; page_route over-routes (V2 s15), then a fresh company. Unmerged: CHOLAFIN KPI waits for Shivam.
1. Restart reality-data; T-179 answer timing with `pilot3_fact`.
2. Guidance precision: added rows 13/20 right; add `gross_margin` (BEL 42%, DLF 45%).
3-6. `pilot3_fin` XBRL-first for annual lines; T-175 garbled-layer detector; LongCat on frozen2; T-183 on u8 decks in quota; T-188 layout crop + Dots/DeepSeek cross-check; s10 + T-172/T-170; T-166 follow-ups; board backfill.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
