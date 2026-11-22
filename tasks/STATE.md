# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-21 03:20 IST (Wolf)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker T-225 merged 18 Nov: Dots right cells kept dev 384/426, FROZEN 464/773 (60.0%, baseline 47.7%), 0 wrong; Beam frozen 8 wrong (text layer). Target >=95% not met; T-225 open. Split `D:/RealityEngine/t225_split`; notes V2 contract "Round 1-5".
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
000. 23 Nov 01:50 (Wolf): merged T-238 gap1 OCR, stage M transcripts, O (statements 96% vs Opus), N (deck verified 63.1->64.4%). Running: 91 transcripts (t238/obs_transcripts_91o.db), 91 OCR-deck read (.tmp/t238read), OCR 394, harvest. NEXT: basis_conflict ticket, AR OCR pages, wire obs/events into stores (T-239), 394 raw fetch on Shivam's go.
00. 20 Nov (Eagle): T-226 `v2/script_reader.py` on main (V2 contract s16): round 26 = 3,544 verified, 1,712 unverified, 0 wrong served after reviews 3-6; report D:/RealityEngine/reports/2026-11-20_t226_overnight.html. T-227 (option 1): `v2/script_cells.py` wrote script_cell to the 10 measured stores (5,256 rows); pilot3_cells serves script_rows (restart reality-data). Rule set t227-r30 (V2 s16). r30 dry run on the 81: 20,217 verified, 13,938 unverified (.tmp/sf/unseen81). Seventh review F1/F2 fixed (r32). NEXT: write the 81 + rewrite the 10 with r32; option 2 re-aimed (fill gaps, frozen questions on segments/BS/CF lines), awaiting Shivam.
0. 19 Nov 15:35 (Eagle; Shivam: all capacity on checker quality): MERGED `v2/cell_judge.py` v3.1 (Wolf) and `v2/silver_score.py`. Round 10 on branch Eagle-t225-r10 (27b004a8, worktree IDM-worktrees/Eagle-t225-r10; dsh review F1-F7 fixed): truth wrong 9 -> 0; store silver verified 18,563 -> 19,477, silver wrong 77 -> 66; NOT merged (293 right store cells lost; c31 p3 H1-under-Q wrong).  Next: Shivam's call on merging round 10, then blend -> printed rows.
0a. 18 Nov store repairs : `docs/state_history/STATE_2026-11-19_2005.md`. Then notes PP&E/CWIP, commitments, ratios; trial 2.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`; 16 Nov detail in `docs/state_history/STATE_2026-11-18_0930.md`.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0; next checks on Telegram stores, frozen halves.
3. T-210 merged; T-211 monthly job next (Wolf).


## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.

