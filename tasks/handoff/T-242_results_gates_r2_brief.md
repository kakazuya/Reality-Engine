# T-242 brief: results gates r2 (cash-flow measures, basis, period duration, scale inheritance, JV scope)

Goal: results-page rows carry the right measure kind for cash-flow lines, the statement basis, the column's period duration and the inherited scale, so the results checkpoint passes (>= 70% R) without losing graded R rows.
Files: reality_engine/v2/observations.py (results row gates, `apply_results_row_gates`), reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest -q reality_engine/tests/test_results_gates.py ; python -m pytest -q reality_engine/tests/test_observations.py ; python -m pytest -q reality_engine/tests/test_ar_sections.py ; python -m pytest -q reality_engine/tests/test_deck_guards.py  (all pass)
Evidence: D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_0001.fix.md (FAIL 40R/20P/0W/0J, every P kind with row ids); full grade with reasons: agy job 20261125T212603Z-3639e519 (grade text copied to D:/RealityEngine/t242/grades/results_ckpt0001_3639e519.md is the fix note; pack rows with page text at C:/RealityEngine/t242/results_ckpt1/pack.jsonl, ids = line numbers).
Stop if: a rule changes > 3% of verified rows on a copy of D:/RealityEngine/hy4_out/obs_results_fy27.db; any graded-R row (results_ckpt1 R rows, and the passing results pilot grade C:/RealityEngine/t242/results_pilot / results_r5 if present) changes status; per-company rules.
Budget: ~110 tool calls
Ticket: T-242

## Steps (structural cues only)
1. Cash-flow pages (page or previous-page heading "cash flow"): a line "... paid", "Increase/(Decrease) in X", "(Increase)/Decrease in X", "Proceeds from ...", "Repayment of ..." never takes the P&L or balance-sheet measure of X; map to a cash-flow measure if the measure dictionary has one (cf.*), else keep `NEW:` and unverified.
2. Basis: from the page or previous-page heading ("Standalone"/"Consolidated" statement, segment report, ratios); a filing holding both with neither on the page -> basis '' and the row unverified (reason `basis_unstated`).
3. Period: from the column header including its duration ("Quarter ended", "Half year ended", "Nine months ended", "Year ended", "As at"); when two columns share the end date and the row lacks the duration -> unverified (`period_duration_missing`); a bare year or a release/press date is not a period -> unverified.
4. Scale: a statement page whose header omits the scale line inherits it from the previous/next page of the same statement (same doc, same statement heading); per-share measures (EPS, DPS, book value per share) never take a money scale.
5. Entity: apply the r4 jv/associate scope rules (merged 98ae61ac for AR) to results pages; a "share of (loss)" keeps its negative sign.
6. Measure on a COPY of obs_results_fy27.db via recheck (or a scratch script calling the gates): rows changed per rule, share of verified, graded-R rows changed (0), 20 random changed rows (seed 7). Then tests and docs.

## Limits
Never write live DBs (D:/RealityEngine/hy4_out, C:/RealityEngine/tg_build). No model calls. pytest per file. Never kill processes by name.
