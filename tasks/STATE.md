# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-12 14:10 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-12_1410.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page, text or image; DeepSeek budget ~USD 100-200/month, free models first)
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`. u8/p20/q12 replaced 11 Nov 17:10 by rebuilds (T-161..T-166, v8.1, T-187); backups `*_before_rebuild_2026-11-11.db`. reality-data MCP restart needed (also loads `pilot3_fact`).
- Extraction: `v2/page_words.py` (text layer/OCR) -> `v2/page_layout.py` -> `v2/page_route.py` (T-189, four routes; only table_or_chart is read, on the page IMAGE) -> `v2/reference_geom.py` position check (T-185) -> `v2/page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`.
- Checker (T-185) misses 174/264 right cells on 7 truth pages; garbled scan layers confirm wrong cells (T-175).
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go; Kilo key 1 exhausted, Dots `@kilo2` quota ran out 12 Nov 00:31.
- T-188 reader bake-off (30 frozen2 pages, P/R): Haiku 91.1/95.2, Dots image 83.8/89.6, DeepSeek image 82.9/75.0, GLM-OCR local 80.8/64.4; details `docs/V2_SCHEMA_CONTRACT.md` s14 and `D:/RealityEngine/v2/reference_pages_frozen2/`.
- T-189 AUROPHARMA, 4 models graded (12 Nov): Haiku 81.2%, DeepSeek 76.8%, Gemini 72.5%, MiMo 25/41; none passes 92%. Top miss = stopped early. Report `D:/RealityEngine/reports/2026-11-12_four_model_answer_test.html`. 12 Nov: SHP XBRL fetched (all categories, pledge, exact share count); Q2FY27 transcript not on BSE yet.
- HP TextRecognizer 1.0.1.0 installed and kept (T-190; key deleted, cert TrustedPeople only).
- Disclosures (ledger): p20 99.6% fitted to its own questions (honest 54.8%); T-189 reader arms (Dots quota ran out, Haiku 166 pages, DeepSeek 16 pages deleted), HP MSIX missing.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (one call: preferred figure + source + known_at + inputs; XBRL first for annual lines; mismatch flag), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm + local readers.

## Next action
0. T-191 A/B (`aurobindo_ab/`): all 4 arms answered (runs used 2,336 pages, now in `embed_2336_ab_run`; full 2,595 in `embed`, ~$0.0996 total). Haiku graded blind: 54/69 both arms, 4 flips each way. DeepSeek blind grading RUNNING (3 Opus graders). Next: report `reports/2026-11-12_semantic_ab.html`; answerer-found defects in `aurobindo_ab/STORE_DEFECTS_SEEN.md`.
T-194 MERGED 12 Nov 18:00: `pilot3_topic`, phrase-first search with match counts, page as_of refusal, `event` table (`build --part events`), pharma topic tags. Next: restart reality-data; build events on live stores.
1. T-192: rounds 3-4 failed review on Opus's pilot10 main-vs-branch diff (round 4: 4 HINDALCO India-capex targets hidden as Novelis; Q4-call flows -> Q4). Round 5 RUNNING 20261112T115218Z-d827ceff (brief J1-J3).
2. T-194 tool fixes: brief `tasks/handoff/T-194_TOOL_FIXES_BRIEF.md` waits for Shivam.
3. Branches: 22 unmerged; 5 answer-run note branches deletable; T-163 r4-7 / T-132 r10-12 need review; CHOLAFIN waits for Shivam.
4. Restart reality-data; T-179 timing with `pilot3_fact`; guidance `gross_margin`; `pilot3_fin` XBRL-first; T-175; T-188 follow-ups; s10 + T-172.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy.

## Merge recipe
Grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
