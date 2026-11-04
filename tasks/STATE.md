# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-04 18:30 IST (Eagle)

## Now
Golden-rule step 4-5: pilot on KEC, BAJFINANCE, HINDALCO (`reality_engine/data/pilot3/pilot3.db`, script-built, served by
the `reality-data` pilot3_* tools). Method, schema and every result: `docs/PILOT3_BLUEPRINT.md`; build rules:
`docs/DB_BUILD_GUIDELINES.md`. Hand-read grade of 185 answers (answer_run2): 154 right, 30 partly, 1 wrong.
Live db rebuilt 4 Nov after the dates/guidance/tools merges (backups `D:\RealityEngine\pilot3\*_before_dates_merge_2026-11-04.db`).
Long history of 2-4 Nov: `tasks/archive/STATE_2026-11-04_before_night_loop.md`.
Fast checks merged 4 Nov (guide O9): `build --part kpi --symbols KEC` 125 s vs 503 s for all; `python -m
reality_engine.pilot3.checkpages run` replays 314 graded pages in ~6 s (baseline 145 found: KEC 29/78, BAJFINANCE
59/113, HINDALCO 57/123); fix rounds run `pytest reality_engine/tests -q -k pilot3 -m "not slow"`, full suite at merge.
T-066 branch line (5 Nov, `kpi.py` only): checkpages is 145 again (KEC 29, BAJFINANCE 59, HINDALCO 57) after round 3's
`_PLAN_LEAD`/`_FORWARD` guards cost six answers; "YTD"/"till date" are now period qualifiers (a YTD flow dates to
H1/9M via `_ytd_period`) and "would" is a hedge, not a plan. `test_pilot3_kpi.py` 72 passed; `w_kpi8.db` A1 728/898
(KEC 64, HINDALCO 75, unchanged); KEC `order_intake` now holds H1FY27 and 9MFY26 too, the H1FY27/Q2FY27 dev questions
stay unmet. Next: merge the branch line and re-run the round's hand read on the 13 added rows.

T-054 merged 4 Nov (guide section 5): `plugins/code-tools/` (run-and-exit `outline`, `typecheck`) replaces code-intel;
briefs need seven fields incl. `Evidence:` (`context_pack._REQUIRED_FIELDS`). T-055 built 4 Nov, loop-1 qset fixes 4 Nov
(guide section 6): `reality_engine/night_eval/` (Q1-Q3, A1, A3-A7, decide, audit; 27 tests); real set 1271 questions ok. T-056 4 Nov: `reality_engine/pilot3/profile.py` + `--profile` on docs_collect/build/kpi/transcripts/guidance (pilot10 profile, MARUTI build verified); MCP pilot3_* tools take any `REALITY_PILOT3_DB` database (guide O10, blueprint section 9). Loop 2 merged 4 Nov: segments, bank and insurer lines, deals, insider, index tables (blueprint 9, 9a). T-057 next: printed QoQ/YoY comparatives.

**Running (4 Nov evening):** loop 3 (`loops/loop_03_brief.md`), DeepSeek workers until 06:30 IST. Re-answer of 43 questions done (KEC 13, BAJ 15, HIN 15): `D:\RealityEngine\pilot3\answer_run3\`; worktrees removed.

## Next action
1. T-054 aftercare: profiles swapped to `tasks/dsh_profiles/code-tools.insert.yml` (backups `*.bak_2026-11-04`);
   `plugins/code-intel` to the Recycle Bin; Shivam reconnects MCPs.
2. Loop run (Shivam's go, 4 Nov 05:45 IST): `tasks/night_loop/` (GOAL, PILOT10, LOOP_BRIEF, HANDOFF, loops/); loop 1
   and 2 done, loop 3 is the last (Shivam, 4 Nov); then the main session runs 2 dsh workers at once, no loop sessions.
3. Hand-grade the 43 re-answers (31 earlier non-right + 12 guidance-recall checks); report as HTML in
   `D:\RealityEngine\reports\`; blueprint results history.
4. Then, in order: XBRL segments, core document set and download triage, XBRL calibration, sector vocabularies,
   10-company test (a bank, an insurer, an IT company included). Known KPI defects: BAJ deck cost of funds one quarter
   early, junk `nim_pct` rows, 1-page BSE filings with no page text.

## Never
Copy keys into files or print them. Read `D:\Shivam_Private\Manual Dumps`. Loosen a grader. Push without Shivam's OK.
Spend DeepInfra or use paid models without his OK. Change the question bank, labels or scope without his ruling.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop
`PROGRESS_NOTES.md`, run the changed test files one per process under the RAM watchdog, update this file and each
affected doc, commit ending `By: Eagle` and the co-author line. Copy `.tmp` outputs first, then remove the worktree.
Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`.

Machines: `machines/README.md`. All HP work runs headless.

- 2026-11-04 T-061 KPI precision round 3 (branch `dsh/20261104T164945Z-1c188316`): six general rules in `reality_engine/pilot3/kpi.py` + lexicon (split numbers/decimals, lakh units, right-aligned table columns, quote/neg/subject guards, plan/list/share-of guards, 100x abs outlier gate, monthly/investee page skip). Build `w_kpi6.db`: A1 727/898 (KEC 64 vs 66 and HINDALCO 75 vs 76 below baseline), hand read seed 20261111 KEC 18/20 only (BAJFINANCE 17, HINDALCO 12, HDFCBANK 16, SBILIFE 16, INFY 5, SUNPHARMA 14, MARUTI 15, HINDUNILVR 12, ETERNAL 16); round fails its 18/20 precision target and needs the segment-table/debt-table families fixed. `test_pilot3_kpi.py` 66 passed, checkpages 145.
- 2026-11-04 T-064 KPI three faults (branch `dsh/20261104T174800Z-71a918cc`): general rules in `reality_engine/pilot3/kpi.py` + `lexicon/common.yaml` — a table row with more values than its header columns is not that header's row (segment table gives no company total), a block heading does not own the next label's value (`_own_row_hits`: "Leverage Net Debt" is net debt, not a leverage ratio), only `_STOCK_METRICS` get a Q4 twin (flows such as ROE/EBITDA margin do not), a direction word is a change not a level ("DSO is down 2 days"), a shorter label alias is skipped under its longer form ("EBITDA as a %" under "... of TO"), and a number glued to a known unit ("4.5x", "25kt") is a value. Build `w_kpi7.db` (all ten, 202 s): A1 728/898 — KEC 64 vs 66 and HINDALCO 75 vs 76 below combined3, both also below on a fresh pre-T-064 build; the three named fault classes are zero (no segment revenue as total, no crore amount as `net_debt_to_ebitda`, no Q4 flow twin). Hand read seed 20261113: INFY 12/20, HINDALCO 7/20, HINDUNILVR 18/20 (remaining wrong classes: USD tables as crore, six-month figures dated to the quarter, year token "2026" as revenue, capex commitments, Novelis/segment income as total). `test_pilot3_kpi.py` 71 passed, checkpages 139 found (the 145 recorded for round 3 is stale: the pre-T-064 code also measures 139 on the current live db).
