# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-04 03:55 IST (Eagle)

## Now
Golden-rule step 4-5: pilot on KEC, BAJFINANCE, HINDALCO (`reality_engine/data/pilot3/pilot3.db`, script-built, served by
the `reality-data` pilot3_* tools). Method, schema and every result: `docs/PILOT3_BLUEPRINT.md`; build rules:
`docs/DB_BUILD_GUIDELINES.md`. Hand-read grade of 185 answers (answer_run2): 154 right, 30 partly, 1 wrong.
Live db rebuilt 4 Nov after the dates/guidance/tools merges (backups `D:\RealityEngine\pilot3\*_before_dates_merge_2026-11-04.db`).
Long history of 2-4 Nov: `tasks/archive/STATE_2026-11-04_before_night_loop.md`.
Fast checks merged 4 Nov (guide O9): `build --part kpi --symbols KEC` 125 s vs 503 s for all; `python -m
reality_engine.pilot3.checkpages run` replays 314 graded pages in ~6 s (baseline 145 found: KEC 29/78, BAJFINANCE
59/113, HINDALCO 57/123); fix rounds run `pytest reality_engine/tests -q -k pilot3 -m "not slow"`, full suite at merge.

T-054 merged 4 Nov (guide section 5): `plugins/code-tools/` (run-and-exit `outline`, `typecheck`) replaces code-intel;
briefs need seven fields incl. `Evidence:` (`context_pack._REQUIRED_FIELDS`). T-055 built 4 Nov, loop-1 qset fixes 4 Nov
(guide section 6): `reality_engine/night_eval/` (Q1-Q3, A1, A3-A7, decide, audit; 27 tests); real set 1271 questions ok.

**Running (4 Nov):** nothing. Re-answer of 43 questions done (KEC 13, BAJ 15, HIN 15): `D:\RealityEngine\pilot3\answer_run3\`; worktrees removed.

## Next action
1. T-054 aftercare: profiles swapped to `tasks/dsh_profiles/code-tools.insert.yml` (backups `*.bak_2026-11-04`);
   `plugins/code-intel` to the Recycle Bin; Shivam reconnects MCPs.
2. Loop run (Shivam's go, 4 Nov 05:45 IST): `tasks/night_loop/` (GOAL, PILOT10, LOOP_BRIEF, HANDOFF, loops/); loop 1
   running (`run_loop.py`), 5 loops; peak-hour workers are Sonnet (`sonnet_worker.py`). Wrapper merges between loops.
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
