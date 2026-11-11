# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-11 14:45 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-11_1430.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-13 = reference pages, readers, completeness); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`.

## Now (Shivam 11 Nov: settle extraction for every page, text or image; free models in peak)
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`.
- Extraction design under test (T-180/T-182): word boxes for every page (`v2/page_words.py`: text layer upright, else OCR `ocr_page`) -> layout text (`v2/page_layout.py`, one line per printed line) -> free reader in GRID format (`reference_pages transcribe --input layout --format grid`) -> position check (`v2/reference_geom.py`: value on its label's line, header above) -> unread numbers = recall gap. Grid fixed the 8k-token truncation: IHCL p049 unread 158 -> 23, Bharti p046 292 -> 90, ~90% of cells position-verified, all three readers agree.
- Script baseline r10 (`v2/table_cells.py`) on the 60 reference pages: recall 51% vs readers 69-79% (text input, before grid).

- Run ledger live (Shivam 11 Nov): `D:/RealityEngine/ledger/ledger.db` via `reality_engine/scripts/run_ledger.py` (DEVELOPER_GUIDE s7); Stop hook ingests workers + this session; report `D:/RealityEngine/reports/2026-11-11_run_ledger.xlsx`. Disclosures logged: p20 99.6% was fitted to its own 230 questions (honest 54.8%); T-177 frozen pages p008/p010/p029/p031/p034/p056 were opened while tuning the position check, so a fresh frozen set is needed before quoting reader scores.

## Running
- Grid runs, 60 reference pages, free Kilo: `D:/RealityEngine/v2/reference_pages/run_{dots,supervl,ultra}_grid`, `run_dots_imggrid` (layout + image); end lines in `grid_status.log`.
- Store rebuild on copies (`D:/RealityEngine/rebuild_2026-11-11/run_all.sh`, carry linked transcripts, reconcile, integrity gate, then parts): u8 DONE; p20 in `kpi`; q12 next. Live stores untouched until compared.
- T-180 scorer branch dsh/20261111T082116Z-259da7c5 (Beam): graded MERGE AFTER FIXES (recall must match by word position, dedupe). Eagle fixing at merge.

## Next action
1. When grid runs end: score them (reader_score, by word position) with r10 and text runs; write `D:/RealityEngine/reports/2026-11-12_t180_reader_bakeoff.xlsx`; decide model-in-build for tables.
2. Hand-settle remaining reference disputes from page images (`v2/reference_pages/png/`), frozen copy under `frozen/`.
3. Production page reader (new ticket): per store, every table page -> grid reader -> position check -> `page_cell` rows verified/unverified + per-page unread count; second pass on unread lines.
4. Compare rebuilt p20/u8/q12 with live (row counts per table, earlier-right rows kept), swap in, restart reality-data MCP (T-161..T-166, v8.1 go live).
5. CHOLAFIN KPI branch dsh/20261110T104212Z-67ceeb28 4-store comparison; s10 store + T-172 frozen split + T-170 baseline.
6. T-166 follow-ups; board backfill; `raw_market/masters`, `transcripts_raw` into a main doc.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy.

## Merge recipe
Grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
