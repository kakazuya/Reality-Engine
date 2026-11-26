# T-242 brief: AR row gates r5 - subsets, related-party scope, foreign entity blocks, column periods (agy Hydrogen high, 26 Nov, Wolf)

Ticket: T-242
permission: write (your worktree only)
Base: main.

Goal: AR audit ckpt_0003 failed 37 R / 11 P / 12 W / 0 J and all 12 W rows were VERIFIED. Add structural row gates in
reality_engine/v2/observations.py (`apply_ar_row_gates` ~5000 and its helpers: `_ar_subset_as_total_reason` ~4807,
`_ar_keep_subsidiary_scope` ~4654, `_ar_parent_backed` ~4033, `_ar_entity_named` ~4019, `_ar_period_reason` ~4545)
so each W kind ends unverified (or right), with 0 change to rows graded R.

Evidence (read first): D:/RealityEngine/hy4_out/obs_ar_fy27.db.audit/ckpt_0003.fix.md (W rows by cause, with ids).
Pack with page_text: C:/RealityEngine/t242/ar_grade_ckpt3/pack.jsonl (id = line number). Grades (R ids = all except
P 1,6,11,14,19,24,33,38,46,54,57 and W 3,5,7,10,21,25,39,42,43,47,48,59).

## Steps
1. For each W row read the pack row + page_text; confirm which existing gate missed it and why (file:line).
2. Subset as total: extend `_ar_subset_as_total_reason`: a label that is an item (named material, place, project,
   currency, entity) under a heading whose table prints its own total, stored as a canonical total measure -> unverified
   `ar_subset_as_total` (#10, #21, #25, #42); an 'Other Equity'/'Grand Total' row never maps to one reserve (#39).
3. Related-party notes: in a related-party / transactions-with-related-parties block, the named party is the
   counterparty; entity_scope 'subsidiary' only when the printed relationship category of that party says subsidiary
   (#7 category 'significant influence' -> not subsidiary); a company's own issuance is never 'subsidiary' (#5); a
   related-party line stored as a generic sale measure under another printed category -> unverified (#3).
4. Another entity's statements: a page (or page run) headed by a different company's name or 'Financial statements of
   <other entity>' -> entity_scope 'subsidiary', unverified when the name is not resolvable (#47).
5. Period from the value column only: a period equal to the text of a non-period column ('Period to which the amount
   relates', 'Year of dispute', 'Forum') -> unverified `ar_period_from_text_column` (#43).
6. Authorised shares: count.shares under an 'Authorised' heading -> NEW:authorised_shares or unverified (#48).
7. Wide tables: a value in a table of > 8 columns whose row has a different number of numeric cells than the header ->
   unverified `ar_wide_table_misaligned` (#59).
8. Units (P): when a row has no unit and the page, facing page or note header prints '(in lakhs/crore/millions/
   thousands/hundreds)', carry the unit and scale (#1, #11, #14, #19, #24, #33, #46, #54); keep verified status rules.
9. Tests in reality_engine/tests/test_ar_row_guards.py: one per W row (synthetic text from page_text) + counter-tests
   from 3 R rows (13 related-party subsidiary right, 18 stepdown subsidiary right, 55 subsidiary right).
10. Docs: DEVELOPER_GUIDE.md AR gates r5 bullet.

Files: reality_engine/v2/observations.py, reality_engine/tests/test_ar_row_guards.py, docs/DEVELOPER_GUIDE.md.

Accept (yours): python -m pytest -q reality_engine/tests/test_ar_row_guards.py ; then test_ar_sections.py ;
test_observations.py ; test_results_gates.py ; test_deck_guards.py - each separately, all pass.
Accept (Wolf after you): `--recheck` of a fresh copy of obs_ar_fy27.db: all 12 W unverified or right, 0 of the 37 R
change status, verified rows changed <= 8% with a 20-row seed-7 sample of downgrades judged; then a fresh non-author grade.

Stop if: a rule changes any R row's status and 2 tries do not fix it: report and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill
processes by name; regexes edited with the file editor; empty beats wrong; structural rules only, never per company.
Budget: ~90 minutes, ~150 tool calls.
