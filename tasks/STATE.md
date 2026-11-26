# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-26 01:40 IST (dsh)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; backups `*_before_rebuild_2026-11-11.db`.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; `table_or_chart` read on the page IMAGE, `needs_ocr` on its OCR words since T-238, plus the two T-242 deck options) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- 24-26 Nov T-242: `grade_pack.py`, `docs/grading/`. audits 4-8: 45R3P / 36R1P11M / 35R5P2W5M1N / 29R16P1W1M1N / 29R7P2W10M; 9 26R6P6W9M1N. F3/4: 25-row window <19 kB; named call by call or filing date ±3 d. F5: named call served by its printed call-date docs. F9: sibling election, 3 sentences/turn, aliases; audit9 23R->32R. F8: paraphrase/IDF, disclaimed targets not first, quarantined never served; audit8 27R->32R. F7: company figure first, group guidance election; audit7 30R->39R. F6: quarantined guidance disclosed (miss also lists served metrics), obs fallback, aliases.
- OCR fill (`scripts/ocr_fill.py`): Kilo+Zen, per-route AIMD (`--start/--max-workers`), Zen rotates Nemotron VL / DeepSeek Flash by speed.
- 26 Nov tx statement window (Eagle, 0e8b95f3): sentence snap + referent widen, page-local; recheck dedupes exact repeats. Filter r2: logistics/refusals/closings dropped; period from printed call period, comparatives never set it.
- 26 Nov results gates r2+r3: cash-flow/adjustments, basis (standalone-only filer), duration fill, current/non-current, scope backing, statute junk.
- 26 Nov AR gates r4: jv/associate scopes, printed-name scope, junk; deck untied values.
- 26 Nov extractors (next build): guidance superseded/entity/split; KPI quote-scale check.
- 26 Nov deck r7: scope, HoH/QoQ, quarter cue
- 26 Nov junk gates r5/r6: decorative slide numbers; bare FY tokens, 'N (word)' echoes.
- 26 Nov `gate_not_company`: industry/country/peer/customer rows never verified (read + recheck); recheck keeps not_company/subsidiary_unnamed.
- hy4 bulk: one Drive fetch per doc.
- Run ledger hook incremental.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 26 Nov (Eagle) events: order_win/fund_raise hy4 model + script check merged; VERIFIED_KINDS empty until fresh8 grade.
00000. 26 Nov deck-wide: rechecked copy swapped into obs_decks_wide.db (backup _before_r5ocr), LOADED via SUPPLEMENTS 08:10 (39,941 rows, 176 stores). OCR rows QUARANTINED (grade2 FAIL 18R/13P/5W/24J; needs a slide-type filter).
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.
26 Nov 01:40 NEXT (Wolf): fix 5 merged (15R/16); audit 6; review dsh 69650793 (OCR AIMD+Zen rotation), 437c0e4f (PDF cache); AR ar_r3 grade; deck swap; pack-up EOD.
