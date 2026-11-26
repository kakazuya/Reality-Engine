# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-26 18:05 IST (dsh T-242 xbrl annual; earlier Wolf 17:00)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- 26 Nov Shivam: never block reading; XBRL (`v2/xbrl_crosscheck.py`) + arithmetic (`v2/arith_checks.py`) check layers move status at load; provenance columns; ledgers `docs/ledgers/`. `docs/CONTINUOUS_STORE_ARCHITECTURE.md`.
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; backups `*_before_rebuild_2026-11-11.db`.
- Extraction: `v2/page_words.py`->`page_layout.py`->`page_route.py` (T-189; `table_or_chart` on IMAGE, `needs_ocr` on OCR since T-238 + T-242 deck options)->`reference_geom.py` (T-185)->`page_reader.py` -> `page_cell` verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `PILOT3_BLUEPRINT.md`.
- Retrieval audits 4-10 (`docs/grading/`); audit10 (26 Nov, first after results/AR loads, 48 q): 34R/2P/4W/7M, statements 16/16; next: asked-duration match, AR NEW-code reach, auditor-note scope (`C:/RealityEngine/t242/retrieval_audit10/report.md`).
- 26 Nov tx statements r3 -> r4 (failed) -> r5 merged: own-period token bound to its figure wins; period_anchored 9,959 (r3 9,579); r6 for 4 remaining cases (`tasks/t242_statement_r3_measure.md`).
- 26 Nov results gates r2-r3c merged (r3d recheck running); verified 14,171->11,069 on r3c copy (`tasks/t242_results_measure.md`).
- 26 Nov AR gates r4 swapped; r5+r6 code merged (subset-as-total, related-party scope, other-entity blocks, column periods); live AR DB not rechecked (6 h) - swap after a fresh recheck; r7 for ckpt_0004 kinds.
- 26 Nov events: read-provenance columns on `event` rows (T-242, dsh); script rows `read_model='script'`.
- 26 Nov xbrl check now also covers `fin_annual_line` (BS/H1/FY/CF): 2,448 match / 132 unit fix / 232 contradict; annual contradictions 70% real in the seed-7 sample, not installed; matches safe. `tasks/t242_xbrl_annual_measure.md`.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
000000. T-245 (Shivam 26 Nov): ALL operations stop by 08:00 IST Fri 27 Nov (Eagle hy4_ctl stop 07:45, Wolf fallback `.tmp/t245_stop_0800.sh`); then cleanup only: uploads to Drive, remove worktrees, keep essentials (`C:/RealityEngine/t242/T-245_keep_local.txt`), lean by 10:00. Words: `docs/rulings/RULINGS_VERBATIM.md`.
00000. 26 Nov events: order_win gated (fresh9 55/3/1/1); fund_raise r3 merged (fresh9 W/P/J 11/11 fixed, 0 R changed), fresh10 grade next. filing_events needs T228_STORE_ROOT.
00000. 26 Nov deck-wide rechecked copy loaded (39,941 rows); OCR rows quarantined.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.
26 Nov handoffs: `tasks/handoff/T-242_wolf_handoff_2026-11-26.md`, `T-242_eagle_handoff_2026-11-26_1300.md`.
