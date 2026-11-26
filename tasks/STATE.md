# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-26 17:00 IST (Wolf, dsh T-242)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- 26 Nov Shivam: never block reading; XBRL (`v2/xbrl_crosscheck.py`) + arithmetic (`v2/arith_checks.py`) check layers move status at load; provenance columns; ledgers `docs/ledgers/`. `docs/CONTINUOUS_STORE_ARCHITECTURE.md`.
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; backups `*_before_rebuild_2026-11-11.db`.
- Extraction: `v2/page_words.py`->`page_layout.py`->`page_route.py` (T-189; `table_or_chart` on IMAGE, `needs_ocr` on OCR since T-238 + T-242 deck options)->`reference_geom.py` (T-185)->`page_reader.py` -> `page_cell` verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `PILOT3_BLUEPRINT.md`.
- 24-26 Nov T-242 retrieval audits 4-9 (`grade_pack.py`, `docs/grading/`); fixes F3-F9 in DEVELOPER_GUIDE; audit9 23->32R.
- OCR fill (`scripts/ocr_fill.py`): Kilo+Zen, per-route AIMD (`--start/--max-workers`), Zen rotates Nemotron VL / DeepSeek Flash by speed.
- 26 Nov tx statements r3 merged (e8a03846): sentence snap/widen, labels stripped, period only on an explicit own-period cue (call_period 27,022->9,531); r4 (own-period cues) under Eagle review. `tasks/t242_statement_r3_measure.md`.
- 26 Nov results gates r2/r3/r3b/r3c merged: cash-flow, basis, duration fill (r3c: a date printed in 2+ columns never filled by key, 'Year' only on 31 March), current/non-current, scope, statute junk. r3c copy C:/RealityEngine/t242/results_r3c/after.db: 0 graded-R status change, verified 14,171->11,069 (`tasks/t242_results_measure.md`).
- 26 Nov AR gates r4: jv/associate scopes, printed-name scope, junk; deck untied values.
- 26 Nov deck r7/r8: scope, HoH/QoQ, quarter cue, segment not total
- 26 Nov junk gates r5/r6: decorative slide numbers; bare FY tokens, 'N (word)' echoes.
- 26 Nov `gate_not_company`: industry/country/peer/customer rows never verified (read + recheck); recheck keeps not_company/subsidiary_unnamed.
- 26 Nov Go reader bake-off: no free Go model replaces hy4 (`C:/RealityEngine/t242/go_bakeoff/results.md`).
- 26 Nov events: read-provenance columns on `event` rows (T-242, dsh); script rows `read_model='script'`.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 26 Nov events: order_win gated (fresh9 55/3/1/1); fund_raise r3 merged (fresh9 W/P/J 11/11 fixed, 0 R changed), fresh10 grade next. filing_events needs T228_STORE_ROOT.
00000. 26 Nov deck-wide: rechecked copy swapped into obs_decks_wide.db (backup _before_r5ocr), LOADED via SUPPLEMENTS 08:10 (39,941 rows, 176 stores). OCR rows QUARANTINED (grade2 FAIL 18R/13P/5W/24J); `ocr_fill --classify` merged.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.
26 Nov handoffs: `tasks/handoff/T-242_wolf_handoff_2026-11-26.md`, `T-242_eagle_handoff_2026-11-26_1300.md`.
