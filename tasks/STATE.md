# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-04 03:55 IST (Eagle)

## Now
Golden-rule step 4-5: pilot on KEC, BAJFINANCE, HINDALCO (`reality_engine/data/pilot3/pilot3.db`, script-built, served by
the `reality-data` pilot3_* tools). Method, schema and every result: `docs/PILOT3_BLUEPRINT.md`; build rules:
`docs/DB_BUILD_GUIDELINES.md`. Hand-read grade of 185 answers (answer_run2): 154 right, 30 partly, 1 wrong.
Live db rebuilt 4 Nov after the dates/guidance/tools merges (backups `D:\RealityEngine\pilot3\*_before_dates_merge_2026-11-04.db`).
Long history of 2-4 Nov: `tasks/archive/STATE_2026-11-04_before_night_loop.md`.

## Running (4 Nov)
- dsh `20261103T213546Z-24770afb` T-049 fast checks (`build --symbols`, `checkpages`, `slow` marker; brief
  `tasks/dsh_tasks/T049_FAST_CHECKS_2026-11-04.md`).
- dsh `20261103T214846Z-2fb0c85c` T-054 code-tools replaces code-intel (brief `tasks/dsh_tasks/T054_CODE_TOOLS_2026-11-04.md`).
- Re-answer of 43 questions done (KEC 13, BAJ 15, HIN 15): `D:\RealityEngine\pilot3\answer_run3\`; worktrees removed.

## Next action
1. Review and merge the two running workers as they finish (merge recipe below). After T-054: back up and swap the
   code-intel block for code-tools in `~/.dsh/profiles/headless/cordis.patch.yml` and `web/cordis.patch.yml`, move
   `plugins/code-intel` to the Recycle Bin, ask Shivam to reconnect MCPs.
2. Night loop (awaiting Shivam's approval): goal and evals `tasks/night_loop/GOAL.md`; first build the frozen evals
   (T-055, brief `tasks/dsh_tasks/T055_NIGHT_EVAL_2026-11-04.md`, after fast checks merge), take the baseline, then one
   headless Opus loop at a time. No headless session without Shivam's explicit go.
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

## Machines
How to operate each computer: `machines/README.md`. All HP work runs headless.
