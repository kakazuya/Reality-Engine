# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-11 14:45 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-11_1430.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-13 = reference pages, readers, completeness); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`.

## Now (Shivam 11 Nov: settle extraction for every page, text or image; free models in peak)
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`.
- Extraction design under test (T-180/T-182): word boxes for every page (`v2/page_words.py`: text layer upright, else OCR `ocr_page`) -> layout text (`v2/page_layout.py`, one line per printed line) -> free reader in GRID format (`reference_pages transcribe --input layout --format grid`) -> position check (`v2/reference_geom.py`: value on its label's line, header above) -> unread numbers = recall gap. Grid fixed the 8k-token truncation: IHCL p049 unread 158 -> 23, Bharti p046 292 -> 90, ~90% of cells position-verified, all three readers agree.
- Hand-read truth (Opus, 7 hardest frozen2 pages, `reference_pages_frozen2/handread/`): Dots grid+image 89.5% precision on figures, 90% recall; checker confirms 98.5%-right but misses 75% of right cells on hard pages; garbled scan text layer makes the checker confirm wrong cells (Beam f016). Scorer `v2/truth_score.py`.
- DeepSeek budget ~USD 100-200/month (Shivam 11 Nov): new work on Beam/Kilo; LongCat/MiniMax unavailable on Go today.

- Run ledger live (Shivam 11 Nov): `D:/RealityEngine/ledger/ledger.db` via `reality_engine/scripts/run_ledger.py` (DEVELOPER_GUIDE s7); Stop hook ingests workers + this session; report `D:/RealityEngine/reports/2026-11-11_run_ledger.xlsx`. Disclosures logged: p20 99.6% was fitted to its own 230 questions (honest 54.8%); T-177 frozen pages p008/p010/p029/p031/p034/p056 were opened while tuning the position check, so a fresh frozen set is needed before quoting reader scores.

## Running (DeepSeek off-peak from 15:30 IST, Go key 1)
- T-186 answer-ready `fact` lookup: dsh/20261111T100652Z-e5027efc.
- T-185 position check v2 MERGED: on hand-read unseen pages confirmed-wrong 1->0 (Dots) / 59->26 (Beam); misses 199->174. Garbled scan layers still pass wrong cells (T-175).
- T-187 guidance round 5 (4 management targets lost by the rebuild; gross margin as ebitda_margin): dsh/20261111T100939Z-a783c62b.
- Rebuild on copies `D:/RealityEngine/rebuild_2026-11-11/`: u8 and p20 done (kpi +472/+1,119, statements +2,204/+6,366, share_capital +164/+166; shp_category -54/-80 = pre-2022-07 index rows outside compute window; guidance lost 4 right rows -> T-187), q12 in kpi. Live stores NOT swapped until T-187 merges.

## Next action
1. T-180 done (frozen2): Dots grid+image recall 84% vs r10 36%, first build 41%; precision unmeasured. Next: hand-read precision sample (Shivam 6 pages) and a reader without a daily cap before T-183 runs a store.
2. Hand-settle remaining reference disputes from page images (`v2/reference_pages/png/`), frozen copy under `frozen/`.
3. Production page reader (new ticket): per store, every table page -> grid reader -> position check -> `page_cell` rows verified/unverified + per-page unread count; second pass on unread lines.
4. Compare rebuilt p20/u8/q12 with live (row counts per table, earlier-right rows kept), swap in, restart reality-data MCP (T-161..T-166, v8.1 go live).
5. CHOLAFIN KPI branch dsh/20261110T104212Z-67ceeb28 4-store comparison; s10 store + T-172 frozen split + T-170 baseline.
6. T-166 follow-ups; board backfill; `raw_market/masters`, `transcripts_raw` into a main doc.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy.

## Merge recipe
Grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
