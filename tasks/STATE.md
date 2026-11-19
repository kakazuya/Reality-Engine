# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-19 21:40 IST (Eagle)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker T-225 merged 18 Nov: Dots right cells kept dev 384/426, FROZEN 464/773 (60.0%, baseline 47.7%), 0 wrong; Beam frozen 8 wrong (text layer). Target >=95% not met; T-225 open. Split `D:/RealityEngine/t225_split`; notes V2 contract "Round 1-5".
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.
- T-188 reader bake-off and T-189 answer test: `docs/V2_SCHEMA_CONTRACT.md` s14, `reports/2026-11-12_four_model_answer_test.html`.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00. 19 Nov 21:40 (Eagle; Shivam: rely less on models, a lost right cell is fine, a wrong one never): T-226 `v2/script_reader.py` on branch Eagle-script-first (30438cc3): model-free reader + cross-filing gate, V2 contract s16. dsh review r5: 7 wrong-served classes, all fixed with tests (26). Hand reads 4/60, 1/60, 0/60, 1/60, 0/60. Round 6: 3,310 passed, coverage 9%. Re-review dsh 20261119T150452Z-8f05257b running; merge after it. Next: XBRL exact agreement as second witness. Eval `.tmp/sf/`.
0. 19 Nov 15:35 (Eagle; Shivam: all capacity on checker quality): MERGED `v2/cell_judge.py` v3.1 (Wolf) and `v2/silver_score.py`. Round 10 on branch Eagle-t225-r10 (27b004a8, worktree IDM-worktrees/Eagle-t225-r10; dsh review F1-F7 fixed): truth wrong 9 -> 0; store silver verified 18,563 -> 19,477, silver wrong 77 -> 66; NOT merged (293 right store cells lost; c31 p3 H1-under-Q wrong). Store A/B: `.tmp/t225/resettle_db.py` + silver_score + cell_judge. Dots kilo2 quota hit 19 Nov 15:07. Next: Shivam's call on merging round 10, then blend -> printed rows.
0a. 18 Nov store repairs (R-020/R-013/R-021/R-022, held stores c09 c31 c61 c87 c88 c75, Wolf R-011/NAVKAR): `docs/state_history/STATE_2026-11-19_2005.md`. Then notes PP&E/CWIP, commitments, ratios; trial 2.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`; 16 Nov detail in `docs/state_history/STATE_2026-11-18_0930.md`.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0; next checks on Telegram stores, frozen halves.
3. T-210 merged; T-211 monthly job next (Wolf).
5. T-216 agy DNS retry.

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.

