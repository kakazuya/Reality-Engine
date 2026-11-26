# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-26 12:35 IST (agy)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; backups `*_before_rebuild_2026-11-11.db`.
- Extraction: `v2/page_words.py`->`page_layout.py`->`page_route.py` (T-189; `table_or_chart` on IMAGE, `needs_ocr` on OCR since T-238 + T-242 deck options)->`reference_geom.py` (T-185)->`page_reader.py` -> `page_cell` verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `PILOT3_BLUEPRINT.md`.
- 24-26 Nov T-242: `grade_pack.py`, `docs/grading/`. audits 4-8: 45R3P / 36R1P11M / 35R5P2W5M1N / 29R16P1W1M1N / 29R7P2W10M; 9 26R6P6W9M1N. F3/4: 25-row <19kB; call by call/filing date ±3d. F5: printed call-date docs. F9: sibling, 3 sent/turn, aliases; audit9 23->32R. F8: paraphrase/IDF, disclaimed not first, quarantined never served; audit8 27->32R. F7: company first, group election; audit7 30->39R. F6: quarantined disclosed, obs fallback, aliases.
- OCR fill (`scripts/ocr_fill.py`): Kilo+Zen, per-route AIMD (`--start/--max-workers`), Zen rotates Nemotron VL / DeepSeek Flash by speed.
- 26 Nov tx statements: window (Eagle 0e8b95f3) -> r3 explicit-own-period-only (call_period 27,022->9,531) -> r4 as-on/quarterly cues (8,575) -> r5 own-period token bound to its figure beats sentence blocks, guidance takes its named target FY (`tasks/t242_statement_r3_measure.md`); 394 reparse r5 **9,959** (r3 9,579), 1,651 regained / 1,276 dropped vs r3, 0 graded-R change beyond period; tests 70+177.
- 26 Nov results gates r2+r3: cash-flow/adjustments, basis (standalone-only filer), duration fill, current/non-current, scope backing, statute junk.
- 26 Nov AR gates r4: jv/associate scopes, printed-name scope, junk; deck untied values.
- 26 Nov extractors (next build): guidance superseded/entity/split; KPI quote-scale check.
- 26 Nov deck r7/r8: scope, HoH/QoQ, quarter cue, segment not total
- 26 Nov junk gates r5/r6: decorative slide numbers; bare FY tokens, 'N (word)' echoes.
- 26 Nov `gate_not_company`: industry/country/peer/customer rows never verified (read + recheck); recheck keeps not_company/subsidiary_unnamed.
- hy4 bulk: one Drive fetch per doc.
- 26 Nov Go reader bake-off (T-242): only `hy4-flash-free` is image-capable and fast on 40 shared pages (37/40, median 9.5 s); `beam-free` 34/40 at 18 s (text only), `iceman` 35/40 at 130 s (text only), `hungerg-free` 19/40 at 95 s (6-request cap, reasoning off). Registry: `extract_deck_figures.MODELS` (`hungerg-free` added, `beam-free` effort low); results + 30-row packs staged `.tmp/go_bakeoff_deliver/` (copy to `C:/RealityEngine/t242/go_bakeoff/`).
- Run ledger hook incremental.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 26 Nov T-242 events r2 (`filing_events.py`, `test_filing_events_model.py`, 196 passed): cached `C:/RealityEngine/t242/model_v2/` (`0` hy4 reqs); `fresh8` W+J 25/25; vs v1 243/259 R unchanged (0 regressions); `VERIFIED_KINDS` empty.
00000. 26 Nov deck-wide: rechecked copy swapped into obs_decks_wide.db (backup _before_r5ocr), LOADED via SUPPLEMENTS 08:10 (39,941 rows, 176 stores). OCR rows QUARANTINED (grade2 FAIL 18R/13P/5W/24J); `ocr_fill --classify` merged.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.
26 Nov 12:30 HANDOFF Wolf->Eagle (Wolf CLI restart): see tasks/handoff/T-242_wolf_handoff_2026-11-26.md.
