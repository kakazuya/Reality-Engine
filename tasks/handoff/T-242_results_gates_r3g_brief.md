# T-242 brief: results gates r3g - sectioned BS measures, components never take block totals, auditor-note scope, statute %, CF movement (agy Hydrogen high, 27 Nov 06:55, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: main at/after 836b4aa5 (results r3c-r3f merged).

Goal: results ckpt_0005 failed 45/4/11/0. Fix note (read first): D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_0005.fix.md.
Pack with page_text: C:/RealityEngine/t242/results_ckpt5/pack.jsonl (row number = line number). Structural rules only, in the
results row gates of reality_engine/v2/observations.py (`apply_results_row_gates` and helpers; search the r3e/r3f rules);
rows end unverified/quarantined or with the corrected measure, never deleted.

Evidence: the fix note's 11 W rows; the pack rows #5, #6, #9, #23, #27, #39, #40, #41, #43, #48, #53.

## Kinds (one test each from the pack row's page_text, plus a counter-test)
1. Sectioned line: a line under a printed 'Non-current' / 'Current' (or 'Long-term' / 'Short-term') heading never takes the bare
   total measure (#23 ABFRL '(iii) Deposits' 38.29 -> not 'deposits'; #40 ADJIA short-term borrowings -> not 'borrowings'; #9
   current loans; #41 non-current provisions; #53 non-current lease liabilities). Use the existing sectioned measure if the
   measure dictionary has one (search for long_term_/short_term_/non_current_/current_ names), else keep the section in
   segment and set status unverified. Counter: a line printed 'Total borrowings' or a page with no section heading keeps
   'borrowings'.
2. Component, not block total: a component line under a block whose total is printed on the page never takes the total's
   measure (#6 ATHARVA 'Furniture' -> not gross_block; #43 one working-capital line -> not changes_in_working_capital; #48
   OCI 'Items that will not be reclassified ...' -> not other_comprehensive_income) -> unverified. Extend the r3e component
   rule beyond 'comprise' headings. Counter: the printed 'Total' / 'Gross block' row keeps its measure.
3. Auditor-note scope: a figure inside an auditor's paragraph about a subsidiary/joint venture ("Group's share of total
   assets", "financial statements of <subsidiary> ... reflect total assets of") is never entity_scope company (#5 ATIL
   2,182.21) -> scope subsidiary or unverified.
4. Statute threshold: "not more than 10% / 25% of the paid-up capital" (buy-back, Companies Act limits) is a limit, never
   shareholding_pct or any company figure (#27 ADVENZYMES) -> quarantined.
5. CF movement: a cash-flow line starting 'Change in' / '(Increase)/decrease in' / 'Movement in' never maps to a balance
   measure (#39 'Change in other bank balance' -> not other_bank_balances) -> unverified with value_kind change if present.

## Measure (pack only - operations stop 08:00)
Re-run the gates on the 60 pack rows plus 200 seeded results rows (seed 7) from a COPY of D:/RealityEngine/hy4_out/obs_results_fy27.db
taken with the sqlite3 backup API into your .tmp (the live DB is written by a loop; never a plain file copy). Report rows changed
per rule, 0 status change on the 45 R rows of ckpt_0005 (R = rows not named in the fix note), and per rule 10 seeded changed
rows judged right/wrong.

Files: reality_engine/v2/observations.py, reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_results_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_results_gates.py ; test_observations.py ; test_ar_sections.py ;
test_deck_guards.py - each separately, pass; 0 graded-R change; the 11 W rows end not-wrong.
Stop if: a rule changes any graded-R row after 2 tries: drop that rule, report. HARD STOP 07:45 IST (Shivam: operations
stop by 08:00) - commit what passes.
Pitfalls: pytest, not unittest; never commit temp dirs or PROGRESS_NOTES.md; never write under C:/RealityEngine or
D:/RealityEngine (copies in .tmp); no model calls; never kill processes by name.
Budget: ~50 minutes.
