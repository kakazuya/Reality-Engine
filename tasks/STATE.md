# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-21 03:20 IST (Wolf)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; only table_or_chart read, on the page IMAGE) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker T-225 merged 18 Nov: Dots right cells kept dev 384/426, FROZEN 464/773 (60.0%, baseline 47.7%), 0 wrong; Beam frozen 8 wrong (text layer). Target >=95% not met; T-225 open. Split `D:/RealityEngine/t225_split`; notes V2 contract "Round 1-5".
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 24 Nov (T-242, Eagle merged dsh d8719f81): deck ranges fill value_high (11 pilot rows), date/quarter/FY values unverified (21 rows, 0 verified lost).
00000. 24 Nov 19:50 (Eagle): T-242 v3 GATE PASSED (2fae7ddac53e), ckpt_0001 pass 46/13/1/0; hy4 on v3; speaker, cover-line, label fixes merged. NEXT: fy27_v3 reparse + ckpt re-grade; events r4 + city fix + loader repoint merged; AR re-grade after cb0efb86.
0000000. 24 Nov (dsh, merged): AR row gates (unit/ageing-party label/narrative growth/page-head basis): graded W/P 9 of 11 handled, R lost 0/42; fresh re-grade by Eagle.
00. 24 Nov 16:55 (Wolf): AR statement lines never verified (XBRL holds them); pilot verified 3,017->1,414 with Eagle's exemptions.
0000. 24 Nov 15:15 (Eagle): T-242 merged v2 guards 10-16 (f1fac770) + filing_events fixes 1-6 (tuned on the graded 60: fresh-seed grade needed). NEXT: reparse fresh 394_v2 snapshot -> Wolf grades 60 verified; events on 20 new stores -> Wolf grades.
000. 24 Nov 19:00 (Wolf): T-242: call statements gate (numbers only via v2/corroborate.py); deck whose-figure prompt GATE PASSED 55/4/0/1 (fp ea5e621d2826); deck bulk in hy4 loop; AR row guards dsh cb0efb86; v3 fy27 ckpt_0001 grading (dsh 5edabb75).
00. 20 Nov (Eagle): T-226 script_reader + T-227 script_cells on main (V2 contract s16); r32 rules; NEXT: write the 81 + rewrite the 10 with r32 (paused by T-242). T-225 round 10 (Eagle-t225-r10) unmerged, Shivam's call.
0a. 18 Nov store repairs : `docs/state_history/STATE_2026-11-19_2005.md`. Then notes PP&E/CWIP, commitments, ratios; trial 2.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`; 16 Nov detail in `docs/state_history/STATE_2026-11-18_0930.md`.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0; next checks on Telegram stores, frozen halves.
3. T-210 merged; T-211 monthly job next (Wolf).


## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.

