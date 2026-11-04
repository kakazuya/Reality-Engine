# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-04 23:20 IST (Eagle)

## Now
Golden-rule step 4-5: pilot on KEC, BAJFINANCE, HINDALCO (`reality_engine/data/pilot3/pilot3.db`, script-built, served by
the `reality-data` pilot3_* tools). Method, schema and every result: `docs/PILOT3_BLUEPRINT.md`; build rules:
`docs/DB_BUILD_GUIDELINES.md`. Hand-read grade of 185 answers (answer_run2): 154 right, 30 partly, 1 wrong.
Live db rebuilt 4 Nov after the dates/guidance/tools merges (backups `D:\RealityEngine\pilot3\*_before_dates_merge_2026-11-04.db`); long history of 2-4 Nov: `tasks/archive/STATE_2026-11-04_before_night_loop.md`.
Fast checks merged 4 Nov (guide O9): `build --part kpi --symbols KEC` 125 s vs 503 s for all; `python -m
reality_engine.pilot3.checkpages run` replays 314 graded pages in ~6 s (baseline 145 found: KEC 29/78, BAJFINANCE
59/113, HINDALCO 57/123); fix rounds run `pytest reality_engine/tests -q -k pilot3 -m "not slow"`, full suite at merge.

T-054 merged 4 Nov (guide section 5): `plugins/code-tools/` (run-and-exit `outline`, `typecheck`) replaces code-intel;
briefs need seven fields incl. `Evidence:` (`context_pack._REQUIRED_FIELDS`). T-055 built 4 Nov, loop-1 qset fixes 4 Nov
(guide section 6): `reality_engine/night_eval/` (Q1-Q3, A1, A3-A7, decide, audit; 27 tests); real set 1271 questions ok. T-056 4 Nov: `reality_engine/pilot3/profile.py` + `--profile` on docs_collect/build/kpi/transcripts/guidance (pilot10 profile, MARUTI build verified); MCP pilot3_* tools take any `REALITY_PILOT3_DB` database (guide O10, blueprint section 9). Loop 2 merged 4 Nov: segments, bank and insurer lines, deals, insider, index tables (blueprint 9, 9a). Loop 3 merged 4 Nov: printed comparatives `comparatives.py` (T-057), speakers and guidance precision (blueprint, guide O). Report: `tasks/night_loop/loops/loop_03_report.md`. Guidance recall merged (T-058, 83 rows). MARUTI real transcripts added: `pilot10\scratch\add_maruti_transcripts.py`.

**Running (4 Nov night):** KPI three faults (T-064) and October filings (T-065) workers. Main on copy `pilot10\scratch\w_guid2.db`: A1 709/898 = 79%, guards not run, `pilot10.db` stale. KPI branches not merged (round 3: 141 of 200). Guidance fix merged (T-062, 90 rows); open: a steady-state or multi-year target stored under a fiscal year (ETERNAL 5-6%, 60% CAGR). Re-answer of 43 questions done (KEC 13, BAJ 15, HIN 15): `D:\RealityEngine\pilot3\answer_run3\`; worktrees removed.

## Next action
1. T-054 aftercare: profiles swapped to `tasks/dsh_profiles/code-tools.insert.yml` (backups `*.bak_2026-11-04`);
   `plugins/code-intel` to the Recycle Bin; Shivam reconnects MCPs.
2. Loop run (Shivam's go, 4 Nov 05:45 IST): `tasks/night_loop/` (GOAL, PILOT10, LOOP_BRIEF, HANDOFF, loops/); loop 1
   to 3 done, no more loop sessions (Shivam, 4 Nov): the main session runs 2 dsh workers at once.
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
