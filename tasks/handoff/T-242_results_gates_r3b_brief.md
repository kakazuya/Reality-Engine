# T-242 brief: results gates r3b - stop r3 from downgrading graded-right rows; measure on the full copy

Goal: results gates r3 (merged 73f5778a) keep their fixes but change 0 graded-R rows; measured on a copy of the full results DB.
Files: reality_engine/v2/observations.py (results r2/r3 helpers), reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest -q reality_engine/tests/test_results_gates.py ; test_observations.py ; test_ar_sections.py ; test_deck_guards.py (all pass) AND a recheck of a fresh copy of D:/RealityEngine/hy4_out/obs_results_fy27.db changes 0 of the 40 graded-R rows of C:/RealityEngine/t242/results_ckpt1 (ids = pack line numbers; R ids: 1,3,4,5,6,7,9,10,12,13,14,15,17,18,19,20,21,22,23,27,28,29,32,34,38,39,40,41,42,44,45,47,49,50,53,54,55,56,57,58) and 0 of the 28 graded-R rows of C:/RealityEngine/t242/results_grade_r2 (grade in D:/RealityEngine/t242/grades / C:/RealityEngine/t242/results_grade_r2/fix.md lists W/P; R = the rest).
Evidence: Wolf's check on the r3 recheck copy C:/RealityEngine/t242/results_recheck/results_r3.db: verified 14,171 -> 10,848 (-23%); 6 graded-R rows downgraded:
 - 1, 3, 55: `results_period_duration_missing: no column duration header found for flow period '30.09.20..' / '31-March..' / '31-Mar-2..'` - the header exists (e.g. "Half year ended", "Year ended" on the previous line/page or as a merged header cell); the parser misses it.
 - 7, 22, 32: `results_cash_flow_measure` on rows that are cash-flow ADJUSTMENT lines graded R as stored ('Rent Received/Other Income' adjustment, 'Net gain on derecognition...', 'Interest income from investing activities') - check what measure they carry; a row already holding a cash-flow measure (or graded R as the printed cash-flow line) must not be downgraded.
 Also count rows per r3 rule (stats in C:/RealityEngine/t242/results_recheck/recheck_r3.log: results_period 9669, results_duration_filled 7419, results_cash_flow 2420, results_scope_reset 2961, results_dropped 760) and sample 20 downgraded rows per big rule (seed 7) to judge over-reach.
Stop if: a rule cannot be fixed without losing its W/J fixes on the r2 grade pack; > 2 tries per rule.
Budget: ~120 tool calls
Ticket: T-242

## Steps
1. Reproduce the 6 downgrades on a copy (scratch under your worktree .tmp; never the live DB).
2. Duration header: search the column header block (same page lines above the value's column, previous page tail for a carried header, merged cells like "Half year ended 30.09.2026") before declaring missing; when the table has a single flow column set with one end date and the statement title names the duration ("Statement of ... for the half year ended"), use it.
3. Cash-flow rule: skip rows whose measure is already a cash-flow/NEW:*_cash_flow measure or whose printed_label already says "adjustment"/"(cash flow)"; only remap P&L/BS measures.
4. Re-run the recheck on a fresh copy; report verified count, per-rule counts, graded-R changes (must be 0), 20 random downgrades per big rule.
5. Tests for both fixes (keep-cases from rows 1, 3, 7, 22, 32, 55 as synthetic text); docs.

## Limits
Never write live DBs; no model calls; pytest per file; never kill processes by name.
