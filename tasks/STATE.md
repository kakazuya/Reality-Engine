# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-26 01:40 IST (dsh)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; `table_or_chart` read on the page IMAGE, `needs_ocr` on its OCR words since T-238, plus the two T-242 deck options) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker T-225 (18 Nov): FROZEN 464/773 (60.0%), 0 wrong; target 95% not met, open. Notes: V2 contract "Round 1-5".
- 24-26 Nov T-242: `grade_pack.py`, `docs/grading/`. audits 2-6: 33R8P3W4M / 32R12P4M / 45R3P / 36R1P11M / 36R5P1W5M1N; 7 (fresh, paraphrased) 29R16P1W1M1N. F3/4: 25-row window <19 kB; named call by call or filing date ±3 d. F5: named-call obs_fact statements + doc_page hits come from its PRINTED call-date documents, not the filing-date window; 16 audit-5 statements by call date 4R3P9M -> 15R1P. F6: held-but-quarantined guidance disclosed, obs_fact guidance fallback, PAT/as-on aliases, all-ask-word sentence first, filed beats call figure >20%; audit-6 replay 36R->45R.
- OCR fill (`scripts/ocr_fill.py`): Kilo+Zen, per-route AIMD (`--start/--max-workers`), Zen rotates Nemotron VL / DeepSeek Flash by speed.
- 26 Nov tx statement window (Eagle, 0e8b95f3): sentence snap + referent widen, page-local; recheck dedupes exact repeats.
- 26 Nov `gate_not_company`: industry/country/peer/customer rows never verified (read + recheck); recheck keeps not_company/subsidiary_unnamed.
- 26 Nov bulk hy4 reads: one Drive fetch per doc (`raw_store.shared_cache`).

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 26 Nov (Wolf): results gate PASS 48/11/1/0 after gates; bulk results read running.
00000. 26 Nov 03:20 (Eagle) events: Shivam switched order_win/fund_raise to hy4 model + script check; merged (agy c858aea0, fp 546696b94a21): fresh5-7 graded W/J 69/70 fixed or unverified, R kept 92%. VERIFIED_KINDS empty until a fresh8 60-row grade per kind (Eagle).
00000. 26 Nov deck widening (+2,307 few-figure, +1,438 jumbled 0.70) reading into obs_decks_wide.db (ckpt 1-2 carried); sonnet_settle OFF till Shivam's OK.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.
- 25 Nov AR re-grade gates merged (Hydrogen, T-242): 5(c) unnamed-sub 184 unverified, 535 reset to company, 0 R changed. Next: --recheck AR copy, non-author grade, then load.
- 26 Nov: tx recheck waits for 0e8b95f3 (referent window + dedupe) (Eagle)
26 Nov 01:40 NEXT (Wolf): fix 5 merged (15R/16); audit 6; review dsh 69650793 (OCR AIMD+Zen rotation), 437c0e4f (PDF cache); AR ar_r3 grade; deck swap; pack-up EOD.
