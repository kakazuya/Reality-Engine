# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-11 20:10 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-11_1430.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-13); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db` (DEVELOPER_GUIDE s7).

## Now (Shivam 11 Nov: settle extraction for every page, text or image; DeepSeek budget ~USD 100-200/month, free models first)
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`. u8/p20/q12 replaced 11 Nov 17:10 by rebuilds (T-161..T-166, v8.1, T-187); backups `*_before_rebuild_2026-11-11.db`. reality-data MCP restart needed (also loads `pilot3_fact`).
- Extraction design: word boxes for every page (`v2/page_words.py`, text layer or OCR) -> layout text (`v2/page_layout.py`) -> free reader in grid format -> position check (`v2/reference_geom.py`, T-185 column model) -> `v2/page_reader.py` (T-183) writes page_cell verified/unverified.
- Hand-read truth (Opus, 7 hardest frozen2 pages, scorer `v2/truth_score.py`): Dots grid+image 89.5% on figures, recall 90%; Beam 78%, Iceman 71% recall; LongCat 110/110 on the one table it read (12/30 pages timed out). Checker after T-185: 0 wrong confirmed (Dots), misses 174 of 264 right cells; garbled scan text layers still confirm wrong cells (T-175).
- Free models on Go (11 Nov): `beam-free`, `longcat-2.5-free` (images), `iceman-contributor-free`; both keys hit LongCat 429s; Kilo free key 1 exhausted, Dots `@kilo2` works.
- T-188 (Eagle, 11 Nov 19:30-20:05, done except scoring): TextRecognizer read all 30 frozen2 pages on the HP (0 failed, 8,252 words, 139 pages/min recognition) into `reference_pages_frozen2/ocr_textrec/`; Dots grid on the PDF text layer 27/30 pages 1,416 rows vs 26/30 pages 1,398 rows on the TextRecognizer layout (`run_dots_layout`, `run_dots_ocrlayout`, 0 errors). `hp_ocr.py` gained `plan --pdf-dir` + `fetch --words-out`, `reference_pages transcribe --ocr-words`; the MSIX must be installed by a windowless WinExe in the interactive session (`Add-AppxPackage` over SSH fails 0x80070005), see `machines/HP_LAPTOP.md`. Next: Opus scores the arms against `handread/` (never opened here).
- Disclosures (ledger): p20 99.6% was fitted to its own questions (honest 54.8%); original T-177 frozen pages were seen while tuning, frozen2 replaces them.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (one call: preferred figure + source + known_at + inputs; XBRL first for annual lines; mismatch flag), T-187 guidance round 5, T-184 run ledger.

## Next action
1. Restart reality-data; re-run the T-179 answer timing with `pilot3_fact` (calls and seconds per answer).
2. Guidance precision round: added rows 13/20 right in a grader sample; add a `gross_margin` metric (BEL 42%, DLF 45% now dropped).
3. `pilot3_fin` serves an annual-report figure before XBRL for annual lines (APOLLOHOSP FY25 revenue): same XBRL-first rule as fact.
4. T-175 garbled text-layer detector; re-run LongCat on frozen2 with a longer timeout; run T-183 on u8 decks/results within free quotas.
5. T-188 scoring: Opus reads `reference_pages_frozen2/handread/` against `ocr_textrec/`, `run_dots_layout`, `run_dots_ocrlayout`; then the local readers (PaddleOCR-VL-1.6, GLM-OCR, LightOnOCR) on the 1050 Ti.
6. CHOLAFIN KPI branch comparison; s10 store + T-172 frozen split + T-170 baseline; T-166 follow-ups; board backfill.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy.

## Merge recipe
Grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
