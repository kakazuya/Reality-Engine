# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-05 00:50 IST (Eagle)

## Now
Golden-rule step 4-5: pilot on KEC, BAJFINANCE, HINDALCO (`reality_engine/data/pilot3/pilot3.db`, script-built, served by the `reality-data` pilot3_* tools). Method, schema and every result: `docs/PILOT3_BLUEPRINT.md`; build rules: `docs/DB_BUILD_GUIDELINES.md`. Hand-read grade of 185 answers (answer_run2): 154 right, 30 partly, 1 wrong.
Live db rebuilt 4 Nov after the dates/guidance/tools merges (backups `D:\RealityEngine\pilot3\*_before_dates_merge_2026-11-04.db`); long history of 2-4 Nov: `tasks/archive/STATE_2026-11-04_before_night_loop.md`.
Fast checks merged 4 Nov (guide O9): `build --part kpi --symbols KEC` 125 s vs 503 s for all; `python -m reality_engine.pilot3.checkpages run` replays 314 graded pages in ~6 s (baseline 145 found: KEC 29/78, BAJFINANCE 59/113, HINDALCO 57/123); fix rounds run `pytest reality_engine/tests -q -k pilot3 -m "not slow"`, full suite at merge.
KPI rounds 1-3, three faults and T-066 merged 5 Nov (T-064, T-066): checkpages 145, `test_pilot3_kpi.py` 72 passed. Hand read still low: INFY 12, HINDALCO 7 of 20; next rules in blueprint section on KPIs.

T-054 merged 4 Nov (guide section 5): `plugins/code-tools/` (run-and-exit `outline`, `typecheck`) replaces code-intel; briefs need seven fields incl. `Evidence:` (`context_pack._REQUIRED_FIELDS`). T-055 built 4 Nov, loop-1 qset fixes 4 Nov (guide section 6): `reality_engine/night_eval/` (Q1-Q3, A1, A3-A7, decide, audit; 27 tests); real set 1271 questions ok. T-056 4 Nov: `reality_engine/pilot3/profile.py` + `--profile` on docs_collect/build/kpi/transcripts/guidance (pilot10 profile, MARUTI build verified); MCP pilot3_* tools take any `REALITY_PILOT3_DB` database (guide O10, blueprint section 9). Loop 2 merged 4 Nov: segments, bank and insurer lines, deals, insider, index tables (blueprint 9, 9a). Loop 3 merged 4 Nov: printed comparatives `comparatives.py` (T-057), speakers and guidance precision (blueprint, guide O). Report: `tasks/night_loop/loops/loop_03_report.md`. Guidance recall merged (T-058, 83 rows). MARUTI real transcripts added: `pilot10\scratch\add_maruti_transcripts.py`.

**Running:** T-067, the real answer test: 60 fixed dev questions per company (`D:\RealityEngine\pilot10nswer_a2\`, seed 20261105), DeepSeek through the MCP only, Opus grades by hand. Rebuild of all parts first; A1 728/898 on `pilot10\scratch\w_kpi8.db`. Guidance open: a steady-state or multi-year target stored under a fiscal year (ETERNAL 5-6%, 60% CAGR). The worker profile `~/.dsh/profiles/headless/cordis.patch.yml` gets `REALITY_PILOT3_DB` for the run: restore it after (backup `.bak_2026-11-05`).

## Next action
1. T-054 aftercare: profiles swapped to `tasks/dsh_profiles/code-tools.insert.yml` (backups `*.bak_2026-11-04`); `plugins/code-intel` to the Recycle Bin; Shivam reconnects MCPs.
2. Loop run (Shivam's go, 4 Nov 05:45 IST): `tasks/night_loop/` (GOAL, PILOT10, LOOP_BRIEF, HANDOFF, loops/); loop 1
   to 3 done, no more loop sessions (Shivam, 4 Nov): the main session runs 2 dsh workers at once. NEXT: T-067 grade; Shivam approves the question set (`D:\RealityEngineeports6-11-05_question_set_dev.xlsx`); the model budget question is parked until the grade shows whether wrong KPI rows cost answers; then a period for steady-state and multi-year guidance.
3. Hand-grade the 43 re-answers (31 earlier non-right + 12 guidance-recall checks); report as HTML in `D:\RealityEngine\reports\`; blueprint results history.
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
