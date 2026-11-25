# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-25 19:55 IST (dsh)
History `docs/state_history/` (previous: `STATE_2026-11-19_2005.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md` (sections 12-15); Fable tests `tasks/FABLE_TESTS_2026-11-10.md`; run ledger `D:/RealityEngine/ledger/ledger.db`.

## Now (Shivam 11 Nov: settle extraction for every page; DeepSeek ~USD 100-200/month, free models first)
- Stores `D:/RealityEngine/{p20/p20new.db,u8/u8.db,q12/q12.db,n10/n10.db,pilot10/pilot10.db}`; u8/p20/q12 rebuilt 11 Nov 17:10, backups `*_before_rebuild_2026-11-11.db`; reality-data restart needed.
- Extraction: `v2/page_words.py` -> `page_layout.py` -> `page_route.py` (T-189, four routes; `table_or_chart` read on the page IMAGE, `needs_ocr` on its OCR words since T-238, plus the two T-242 deck options) -> `reference_geom.py` (T-185) -> `page_reader.py` writes page_cell verified/unverified/quarantined, served by `pilot3_cells`. T-199 atoms (`page_atom` v10): `docs/PILOT3_BLUEPRINT.md` T-199 block.
- Checker T-225 merged 18 Nov: Dots right cells kept dev 384/426, FROZEN 464/773 (60.0%, baseline 47.7%), 0 wrong; Beam frozen 8 wrong (text layer). Target >=95% not met; T-225 open. Split `D:/RealityEngine/t225_split`; notes V2 contract "Round 1-5".
- Free models: `beam-free`, `longcat-2.5-free`, `iceman-contributor-free` on Go.
- 24-25 Nov T-242: empty window page = `no_rows`; `scripts/grade_pack.py` builds the 60-row pack; rubrics `docs/grading/`. Fix 2: named call, dates, label-first, guidance, holding route; audits 2/3/4: 33R8P3W4M / 32R12P4M / 45R3P (fix 3; quote first 14/16). Fix 3: call rank, 25/named call, label subset. Fix 4: named call filters both sources (call or filing date ±3 d), 25 rows whole under 19 kB, Share Capital+period = printed line (BIGBLOC wrong-call 15->0).

## Next action (Shivam 15 Nov: Telegram companies first, on-demand build; fix known issues in 1-2 days, then build)
00000. 25 Nov 19:50 (Wolf): deck gates merged; next: swap rechecked decks_r1.db, load_symbols.
00000. 25 Nov 19:15 (Wolf): sonnet_settle guarded (stale >5 min, 25 runs/window); OFF until Shivam's OK + one smoke run.
00000. 25 Nov 19:30 (Eagle) events: r7b (fund_raise) and r8 (order_win) merged; fresh7 gate (40 never-seen stores, code cb741c24) FAILS: order_win 35/10/14/1, fund_raise 31/8/16/0 -> VERIFIED_KINDS stays empty (served unverified). Retrieval fix 1 merged 20:00 (tools serve verified obs_fact first; audit Qs 13->20/20) -> fresh-question audit after MCP restart. NEXT: hy4 model reading + script check (Shivam's call pending).
00000. 25 Nov 21:55 deck widening merged (off by default): `--deck-few-figures` +2,307 pages; `--deck-jumbled-min` 0.70 +1,438 (samples readable, Wolf); `tasks/t242_deck_widening_measure.md`. NEXT: read both into a separate hy4 db, checkpoint grade, then load.
0. Roles (16 Nov): Claude writes store design and code; DeepSeek and Flash 3.8 medium boilerplate only; agy runs the model Shivam names. Go key 1 only.
1. T-214/T-218 Telegram build: plan `tasks/handoff/T-214_TG_BUILD_PLAN.md`, queue `D:/RealityEngine/tg_build/build_queue.csv`, stores `tg_build/measure10/c01..c91`; repair notes `tasks/store_repair/INDEX.md`, grid `reports/store_repair_grid.xlsx`.
2. T-213: r15 MERGED (`answer/answer_checker.py` C1-C5 + repair): run B 54/9/1 -> 57/7/0; next checks on Telegram stores, frozen halves.
3. T-210 merged; T-211 monthly job next (Wolf).

## Recipes
Store copy: checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE`. Merge: grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl. Store diff: `reality_engine.scripts.store_diff`.
- 25 Nov AR re-grade gates merged (Hydrogen, T-242): 5(c) unnamed-sub 184 unverified, 535 reset to company, 0 R changed. Next: --recheck AR copy, non-author grade, then load.
