# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-25 11:55 IST (dsh)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker T-225 merged 18 Nov: Dots right cells kept dev 384/426, FROZEN 464/773 (60.0%, baseline 47.7%), 0 wrong; Beam frozen 8 wrong (text layer). Target >=95% not met; T-225 open. Split `D:/RealityEngine/t225_split`; notes V2 contract "Round 1-5".
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.
00000. 25 Nov 12:00 (Eagle merged dsh 18474700): empty question_context filled from the printed analyst turn (4.5% of empties, 0/30 wrong); _flex_regex quote bug fixed.
- 24-25 Nov T-242: empty window page = `no_rows`; `scripts/grade_pack.py` builds the 60-row pack (checkpoint first, seeded fill, 2x30 parts); rubrics `docs/grading/`.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 25 Nov 10:25 (Wolf merged dsh 81c60cde): AR basis carried from the previous page's heading onto continuation pages (181 rows on 9 pages, 0 conflicts). AR year/duration non-figures unverified (agy 87999d39, Eagle merged: 92 of 13,521 live verified; recheck to apply).
00000. 25 Nov 13:00 (Eagle) events: fresh5 (40 untuned stores) failed order_win 39/5/14/2 and fund_raise 31/7/22/0 -> VERIFIED_KINDS empty; re-run events before any load. order_win r7 merged (21/21 fixed; DBs C:/RealityEngine/t242/orderwin_r7d/). fund_raise r7 broke 9 graded R -> r7b (DeepSeek, after 15:30). AR ckpt_0002 FAIL 53/3/3/1 -> row gates merged 16:10 (printed periods, report-year periods, dates never values) -> recheck live AR + re-grade. Transcripts: fy27 ckpt_0003 re-grade PASS 48/10/1/1, r3 live; 394 ckpt_0006 re-grade PASS 48/11/0/1, r4 live 15:50. NEXT: grade both kinds on a new untuned store set (fresh6).
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`; 16 Nov detail in `docs/state_history/STATE_2026-11-18_0930.md`.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0; next checks on Telegram stores, frozen halves.
3. T-210 merged; T-211 monthly job next (Wolf).


## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.

