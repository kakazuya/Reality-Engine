# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-25 10:20 IST (dsh)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker T-225 merged 18 Nov: Dots right cells kept dev 384/426, FROZEN 464/773 (60.0%, baseline 47.7%), 0 wrong; Beam frozen 8 wrong (text layer). Target >=95% not met; T-225 open. Split `D:/RealityEngine/t225_split`; notes V2 contract "Round 1-5".
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.
- 24 Nov (deck, merged): per-period footnote basis (56 rows changed; deck fp unchanged).
- 24 Nov T-242 (`observations.py`): empty page in a parsed window is `page_read` `no_rows`, not a failure; share = failures / attempted.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 25 Nov 10:25 (Wolf merged dsh 81c60cde): AR basis carried from the previous page's heading onto continuation pages (181 rows on 9 pages, 0 conflicts).
00000. 25 Nov 09:15 (Wolf): AR ckpt_0001 FAIL 51/5/1/3 -> 0ab885b6 AR gates (reference numbers, label durations, industry/country/peer: 298 of 11,086 verified). re-grade PASS 45/13/0/2, swapped live (Eagle recorded). --recheck now scans every store (agy 17ed580a; it used --sample 5). 394_v3 ckpt_0004 PASS 42/18/0/0. question_end fix: Eagle/Hydrogen.
00000. 25 Nov 08:40 (Eagle merged dsh a7c04bff): fund_raise round 5 (step amount, stage map, folds, vetoes): graded 60 all W/J/P fixed, 0 R lost, order_win 132/193 same; loader on events_r5_fresh{4,3}.db. 09:02 question_end narrowed (e9d77fc6; fy27_v3 r2 reparse -> re-grade -> swap, Wolf). order_win surprise audit FAIL 52/0/8/0 (L1, subsidiary orders, headline customer): fix agy 70ccab33; load no events until merged. NEXT: fresh-store fund_raise grade.
000. 24 Nov 19:00 (Wolf): T-242: call statements gate (numbers only via v2/corroborate.py); deck whose-figure prompt GATE PASSED 55/4/0/1 (fp ea5e621d2826); deck bulk in hy4 loop; AR row guards dsh cb0efb86; v3 fy27 ckpt_0001 grading (dsh 5edabb75).
0a. 18 Nov store repairs : `docs/state_history/STATE_2026-11-19_2005.md`. Then notes PP&E/CWIP, commitments, ratios; trial 2.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`; 16 Nov detail in `docs/state_history/STATE_2026-11-18_0930.md`.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0; next checks on Telegram stores, frozen halves.
3. T-210 merged; T-211 monthly job next (Wolf).


## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.

