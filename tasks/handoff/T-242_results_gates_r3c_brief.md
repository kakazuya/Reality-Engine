# T-242 brief: results gates r3c - a carried or keyed duration never lands on the wrong column (agy Hydrogen high, 26 Nov, Wolf)

Ticket: T-242
permission: write (your worktree only)
Base: branch dsh/20261126T041452Z-097adfea (r3b, head 03814625). Build on r3b; keep every r3b test passing.

Goal: r3b's duration fills (`_results_duration_dates`, `_results_duration_dates_one`, `_results_period_reason` in
reality_engine/v2/observations.py ~5841-6010) stop writing a wrong duration on a period. r3b changed 0 graded-R rows but
Eagle's non-author review FAILED it on two structural defects (D:/RealityEngine/t242/grades/results_r3b_review_eagle.md):

D1 'Year ended' on a non-year-end date: 89 rows, 64 newly verified (APOLLOIN 82, ARVINDFASN 6, AMBIT 1).
   APOLLOIN p6 header: 'Year to Date figures for current period ended | Year to Date figures for previous year ended |
   Year Ended' over '30.09.2026 30.06.2026 30.9.2025 30.09.2026 30.09.2025 31.03.2026'. 'Year Ended' binds to 31.03.2026
   only. p7 is the half-year cash flow, columns '30.09.2026 | 30.09.2025', no duration word. r3b carried 'year' to
   30.09 on p7 -> '(Increase)/Decrease in Trade Receivable' 'Year ended 30.09.2025' VERIFIED. Wrong.
   Also AGL p3 rows got 'Year ended 30 Jun 2026' (a quarter date).
D2 'Quarter ended' on the year column: 74 rows (AGL 43, ASITCFIN 31). AGL p3 prints '31 Mar 2026' in two columns (Q4
   and the full year); both values got 'Quarter ended 31 Mar 2026' (442 = quarter, right; 2,034 = year, WRONG).
   ASITCFIN p14: 6,123.00 revenue = year, labelled quarter.

Page texts (read-only): C:/RealityEngine/t242/results_r3c/d902768d_p6.txt, d902768d_p7.txt (APOLLOIN), fd361297_p6/p7
(APOLLOIN, other quarter), 628e8a80_p2/p3 (AGL), ee5c764d_p13/p14 (ASITCFIN). First line of each names doc and store.

Cause: a duration resolved for a date KEY is applied to every column with that end date, even when the date is printed
in more than one column (quarter + year, quarter + YTD); and a duration carried from the previous page fills such a date.

## Steps
1. Read the r3b diff (`git diff 99136962..HEAD -- reality_engine/v2/observations.py`) and the r3b section of
   tasks/t242_results_measure.md.
2. Ambiguous dates: when an end date is printed in more than one column of the header block (on the carrying page OR
   the current page), mark that date ambiguous: never carry its duration to the next page and never fill it by key;
   leave the period as printed (no duration) unless a column-position binding is certain.
3. 'Year' only on a year end: never fill 'Year ended' on a date that is not 31 March (or the company's stated fiscal
   year end) unless the header binds the word to that exact single column. 'Half year'/'Nine months'/'Quarter' carry
   as r3b does when unambiguous.
4. Empty beats wrong: if unsure, leave the period without a duration (the row stays unverified via the existing
   duration-missing gate). Never upgrade a row on a filled duration that step 2 or 3 now refuses.
5. Tests in reality_engine/tests/test_results_gates.py, built from the page texts above as synthetic text:
   APOLLOIN p6->p7 (30.09 on p7 gets no 'Year'), AGL p3 (the 2,034 year column never gets 'Quarter'; 442 keeps
   'Quarter ended'), ASITCFIN p14 (6,123.00 not 'Quarter'), AGL 30 Jun never 'Year ended'. Keep all r3b keep-cases
   (ckpt1 #1, #3, #7, #22, #32, #55) passing.
6. Docs: update the r3b bullet in docs/DEVELOPER_GUIDE.md and tasks/t242_results_measure.md with the r3c rule.

Files: reality_engine/v2/observations.py, reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_results_measure.md. Nothing else.

Accept (yours): python -m pytest -q reality_engine/tests/test_results_gates.py ; then test_observations.py ;
test_ar_sections.py ; test_deck_guards.py - each file separately, all pass.
Accept (Wolf runs after you, do not try): full recheck of a fresh copy: 0 of the 68 graded-R rows change status,
D1 count 0 ('Year ended' on a non-31-March date) and D2 count 0 on AGL/ASITCFIN, then Eagle's fresh 20-row sample of
upgrades with 0 W.

Stop if: a fix breaks an r3b keep-case and 2 tries do not fix it: report and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill
processes by name; regexes edited with the file editor; do not delete r3b's carried-header support - narrow it.
Budget: ~60 minutes, ~120 tool calls.
