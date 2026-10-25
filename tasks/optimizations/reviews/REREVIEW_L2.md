# Re-review task — L2 document lookups after the fix round

You are a reviewer, not the author. Workspace: `C:/Users/warri/Downloads/IDM-worktrees/20261025T074948Z-e3822c50`
(branch `dsh/20261025T074948Z-e3822c50`). The first review's defects are in
`tasks/optimizations/reviews/FIX_L2.md` (section "Reviewer defects (verbatim)"); the fix is commit HEAD.

## Goal
Confirm each of the 10 defects is fixed and the fix introduced no new wrong answers.

## Rules
Do not edit or commit tracked files; scratch only under `./.tmp/review/`. Read-only on all data. Re-run things yourself.

## Acceptance checks
1. For each defect D1–D10: re-run your own repro (the failing call / EXPLAIN QUERY PLAN / timing) and mark FIXED or NOT FIXED with evidence (≤ 3 lines each).
2. The original brief's live checks (`tasks/optimizations/lookups/L2_DOC_LOOKUPS.md`, AC2) still give the right answers.
3. New risk: document lists now come from the DuckDB snapshot (`ar_docs`, `cc_docs`, `bse_ann`). Check whether any
   document that exists in the live SQLite stores (`concall_facts`, `ar_facts`, `bse_announcements`, `corporate_documents`)
   after the snapshot date is now invisible to `docs()`; report counts per store.
4. Date matching still correct for 3 companies at d-1/d/d+1/d+4.

## Test command(s)
```bash
python -m unittest discover -s plugins/reality-data/tests -p "test_lookups_docs.py"
```

## Budget
≤ 50 tool calls; ≤ 40 min; $0 paid.

## Final answer (≤ 40 lines)
VERDICT: PASS | FAIL | PASS-WITH-NOTES, then one line per check, then DEFECTS (file:line + one-line fix).
