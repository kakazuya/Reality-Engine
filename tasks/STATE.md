# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 03:00 IST (Wolf, wrap-up at 400k)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Overnight report for Shivam: `D:/RealityEngine/reports/2026-11-09_overnight_report.html`.
- Stores (DELETE journal mode, so sandboxed workers can open them ro): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`; live pilot set `pilot10/pilot10.db` (558/600).
- T-130 u8 graded: 108 right / 41 partly / 0 wrong of 149 (G 56/13, H 52/28); reports `reports/2026-11-09_t130_u8*.xlsx`. Partly causes: undisclosed 19, page held but not read 13 (only latest deck read), SHP not fetched for u8 6, compute 2.
- T-124 q12: C done (78, in `D:/RealityEngine/q12/answers/C/`, NOT graded); D running on HP `hp-20261109T021026-4d75f5`.
- T-143 pilot20 baseline running on HP: P `hp-20261109T024927-0c8865` (111 q), Q `hp-20261109T025104-0fff6a` (119 q incl. 28 Apollo). Questions `D:/RealityEngine/p20/answers/questions_{P,Q}.json`, reframe map `p20/questions/reframe_*.tsv`.
- T-135 calc catalog merged (MCP `pilot3_calc_catalog` live after reality-data restart). T-131 contract DRAFT waits Shivam's OK; T-132 prototype `tasks/v2/T-132_proto_cells.py`.
- Go key 2 hit 429 at 01:52: use account='1'. HP pwsh is broken (spawn EPERM): HP workers answer via MCP, skip the recorder check; run number_check after.
- Waiting Shivam: T-131 OK, T-116, T-118, T-121, T-122.

## Next action
1. HP jobs D, P, Q: `python -m reality_engine.scripts.hp_worker status <job>`; copy `C:/RE/jobs/<job>/repo/.tmp/*_answers.jsonl` (scp zen7s@100.78.87.112) to `D:/RealityEngine/<set>/answers/<letter>/`; `REALITY_PILOT3_DB=<db> python -m reality_engine.pilot3.number_check <files>`.
2. Hand-grade q12 C+D and p20 P+Q (redo sums); grades json -> graded jsonl with `<Wolf fdf6b4bc scratch>/make_graded.py` -> `answer_run_report --name t124_q12` / `t143_p20_baseline`. p20 P+Q = the v2 baseline.
3. Fetch SHP XBRL for u8+q12 companies (pledge, FPI/MF gaps).
4. Answer briefs: "a four-quarter question reads each quarter's deck/results, not only the latest".
5. After Shivam's T-131 OK: T-132 brief from contract section 8 (header stacks, infographic reader, sha256 dedupe), T-134 period engine brief.
6. raw_to_drive sweep for u8 + p20 raw.
7. Remove worktrees `20261108T202256Z-7b279bee` (G), `20261108T204010Z-bf6e78b7` (C; add its review row) and agy `Wolf-agy-20261108T195902Z-e3060045`, `Wolf-agy-20261108T201344Z-62b4f9ea`; answers already copied.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row in `worker_reviews.jsonl` first (gate). `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, run changed test files one per process, update this file and docs, commit `By: <identity>`; remove the worktree; log to the decision log.
