# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-11 21:30 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-11_1430.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-13); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db` (DEVELOPER_GUIDE s7).

## Now (Shivam 11 Nov: settle extraction for every page, text or image; DeepSeek budget ~USD 100-200/month, free models first)
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`. u8/p20/q12 replaced 11 Nov 17:10 by rebuilds (T-161..T-166, v8.1, T-187); backups `*_before_rebuild_2026-11-11.db`. reality-data MCP restart needed (also loads `pilot3_fact`).
- Extraction design: word boxes for every page (`v2/page_words.py`, text layer or OCR) -> layout text (`v2/page_layout.py`) -> free reader in grid format -> position check (`v2/reference_geom.py`, T-185 column model) -> `v2/page_reader.py` (T-183) writes page_cell verified/unverified.
- Hand-read truth (Opus, 7 hardest frozen2 pages, scorer `v2/truth_score.py`): Dots grid+image 89.5% on figures, recall 90%; Beam 78%, Iceman 71% recall; LongCat 110/110 on the one table it read (12/30 pages timed out). Checker after T-185: 0 wrong confirmed (Dots), misses 174 of 264 right cells; garbled scan text layers still confirm wrong cells (T-175).
- Free models on Go (11 Nov): `beam-free`, `longcat-2.5-free` (images), `iceman-contributor-free`; both keys hit LongCat 429s; Kilo free key 1 exhausted, Dots `@kilo2` works.
- T-188 done (merged 11 Nov 21:30): truth for all 30 frozen2 pages (`handread/`, 1,303 cells; halves `split_hard_normal.csv`; scores `score_local.csv`, `score_local_by_half.txt`). P/R all-30: Haiku 5.5 medium image 91.1/95.2, ~9 s/page (`run_haiku_imggrid`); Dots image 83.8/89.6; DeepSeek v4.1-flash image 82.9/75.0, 72 s; GLM-OCR local v2 80.8/64.4, 27 s; LightOnOCR-3 75.8/59.0; PaddleOCR-VL-1.6 38.0/39.8; Dots on layout text 62/67 (text layer or OCR alike). TextRecognizer finds 98.2% of truth numbers (text layer 96.2%), 139 pages/min. 1050 Ti: llama.cpp CUDA 12.4 works, 13.5 fails (Pascal dropped). Local readers lose tables/charts without a layout stage.
- Disclosures (ledger): p20 99.6% was fitted to its own questions (honest 54.8%); original T-177 frozen pages were seen while tuning, frozen2 replaces them.
- Local readers: `v2/local_reader.py` (llama.cpp b12284 CUDA 12.4, `D:/RealityEngine/tools/llamacpp/cuda12.4`; Q8_0 GGUF + mmproj in `D:/RealityEngine/models/`, list `MODELS.md`); 1.9-3.0 GB VRAM.

## Merged 11 Nov
T-182 page_words, T-180 reader_score + bake-off, T-183 page_reader, T-185 position check v2, T-186 `pilot3_fact` (one call: preferred figure + source + known_at + inputs; XBRL first for annual lines; mismatch flag), T-187 guidance round 5, T-184 run ledger, T-188 HP OCR arm + local readers.

## Next action
1. Restart reality-data; re-run the T-179 answer timing with `pilot3_fact` (calls and seconds per answer).
2. Guidance precision round: added rows 13/20 right in a grader sample; add a `gross_margin` metric (BEL 42%, DLF 45% now dropped).
3. `pilot3_fin` serves an annual-report figure before XBRL for annual lines (APOLLOHOSP FY25 revenue): same XBRL-first rule as fact.
4. T-175 garbled text-layer detector; re-run LongCat on frozen2 with a longer timeout; run T-183 on u8 decks/results within free quotas.
5. T-188 follow-up: layout/region crop before local readers (GLM-OCR), and a Dots + DeepSeek cross-check combination scored on frozen2.
6. CHOLAFIN KPI branch comparison; s10 store + T-172 frozen split + T-170 baseline; T-166 follow-ups; board backfill.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy.

## Merge recipe
Grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
