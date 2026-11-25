# T-242 results-page number gates — progress

- 2026-11-25 23:59: implemented `apply_results_row_gates` in `reality_engine/v2/observations.py` (junk -> quarantined, printed unit/scale line, entity scope, associate/holding/fragment) + `previous_pages_text`; wired into `apply_number_gates(doc_type="results")`, `recheck_db`, `process_page`; tests `reality_engine/tests/test_results_gates.py` (16 pass).
- Measured on `.tmp/results_recheck5.db` (copy of `D:/RealityEngine/hy4_out/obs_results_pilot.db`, `REALITY_RAW_FETCH=0`, 188 pages, 145 stores): verified 1,477 -> 1,421; junk 175 (55 verified, 3.72%), unit 715 (119 verified, 8.06%), scope reset 200, associate 1, holding 2, fragment 1; 0 of the 33 graded R rows changed; 9 J quarantined; 33/51/60 unverified; 5/6/27 scope company; 7 lakh rows scaled.
- Docs updated: docs/DEVELOPER_GUIDE.md (results row gates entry), tasks/STATE.md. Next: non-author 60-row grade of the rechecked copy, then load.
- Note: `DSH_WORKER_PROGRESS_NOTES` was not set in the pwsh environment and the job directory is outside the workspace-write sandbox, so this file is at the workspace root.
