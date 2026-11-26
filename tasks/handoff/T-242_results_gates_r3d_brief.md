# T-242 brief: results gates r3d - one label, two values, one date: resolve the duration by column position, never by date alone

Ticket: T-242
permission: workspace-write (your worktree only)
Author: Eagle (26 Nov 15:55). Grader/recorder: Wolf (non-author).

Goal: when one printed label on a results page holds two different values for the same end date (quarter column and
year/9M/half-year column both end 31.03.2026 or 30.09.2026), each row gets the duration of ITS column, read from the
column position of its value on the label's line; when the position cannot be read, the row keeps the bare date
(no duration word) and stays unverified. No row may carry 'Quarter ended <date>' for a year/half-year/9M value.

Files: reality_engine/v2/observations.py (results period helpers: `_results_duration_dates_one` ~line 5874,
`_results_period_reason` line 6104, the per-page loop in `apply_results_row_gates` line 6250),
reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md (the results r3c bullet).

Accept:
- python -m pytest -q reality_engine/tests/test_results_gates.py ; then separately test_observations.py, test_ar_sections.py,
  test_deck_guards.py (all pass; pytest per file).
- A `--recheck` of a FRESH copy of D:/RealityEngine/hy4_out/obs_results_fy27.db (copy under your worktree .tmp; open
  the live file read-only with timeout=300, the hy4 loop writes it) changes 0 graded-R rows of:
  C:/RealityEngine/t242/results_ckpt1 (R ids by pack line: 1,3,4,5,6,7,9,10,12,13,14,15,17,18,19,20,21,22,23,27,28,29,32,34,38,39,40,41,42,44,45,47,49,50,53,54,55,56,57,58),
  C:/RealityEngine/t242/results_grade_r2 (R = rows not listed W/P in its fix.md), and
  C:/RealityEngine/t242/results_grade_r3c/pack.jsonl (R = rows not named in D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_0001.fix.md).
- Residue count (definition below) falls from its baseline to <= 10% of baseline; 0 rows newly verified with a duration
  that disagrees with their column.

Evidence (live obs_results_fy27.db, all unverified today):
- AGARWALEYE doc 40bffc47-0399-49e9-ab81-0ff268215167 p9 '(a) Basic': 1.65 'Quarter ended 30-Sep-26' (Q2, right) and
  3.2 'Quarter ended 30-Sep-26' (H1, WRONG); 1.07 and 2.11 'Quarter ended 30-Sep-25' (2.11 is H1, WRONG).
- AGARWALEYE doc 74f27462-e928-46ee-9027-6e54260f1586 p11 '(a) Basic': 1.25 and 4.21 both 'Quarter ended 31-Mar-26'
  (4.21 is the year).
- AANCHALISP doc dde8dc7b-9fea-4f0f-8eb2-2b2fc8e6b560 p9 'f) Depreciation and amortization': 15.22 and 61.54 both
  'Quarter ended 31.03.2026' (61.54 is the year).
- AGL doc 73e63ebf p3 and ASITCFIN doc 2b88c2df p14: fixed in r3c by abstaining - keep them fixed (they are keep-cases).
- Wolf's r3c measure: 51 groups / 122 rows of this residue. Some come from the READER (period already says
  'Quarter ended'), so the rule must also correct or strip a reader-written duration, not only gate fills.

Residue definition (measure before and after): rows on one (doc_key, page) with the same printed_label, basis,
segment and date key, two or more distinct values, and the same duration word on all of them (or no duration word).

## Steps
1. Reproduce: count the residue on your fresh copy; list the 4 evidence groups with their periods.
2. Ordered header: from the page's header block return the ORDERED column list [(date key, duration)] - the same parse
   `_results_duration_dates_one` already does, kept in print order (a 'Quarter ended' group spans its dates, then
   'Half year / Nine months / Year ended' groups). Return None when the number of dates and groups cannot be paired.
3. Column position: for a row in a residue group, find the page line(s) starting with its printed_label (the value line
   may follow on the next lines in this text layer: take the numbers after the label up to the next label), read the
   numbers in order, and take the index of the row's value (match on the printed digits; when the same value appears
   twice the position is ambiguous). index -> ordered column -> duration. Set period '<Duration label> <date as
   printed>' and period_source 'column_position'.
4. Unresolved (no ordered header, count mismatch, ambiguous value): strip a duration word from the period back to the
   bare printed date, status unverified, reason `results_period_duration_ambiguous: <label> prints <n> values for <date>`.
5. Only residue groups are touched; a page where each label has one value per date is left exactly as today.
6. Tests with synthetic text for the 3 evidence groups (Q + H1, Q + year, reader-written 'Quarter ended' on the year
   value), the ambiguous-equal-values case, and keep-cases AGL/ASITCFIN and a normal one-value-per-date page.
7. Recheck the fresh copy; report: residue before/after, rows resolved by position, rows stripped, graded-R changes
   (must be 0), and 20 random changed rows (seed 7) each with the label line and header you read.
8. Docs: DEVELOPER_GUIDE results r3c bullet -> r3d with the measured numbers. STATE.md one line.

## Limits and pitfalls
- Never write the live DB or any file under D:/RealityEngine or C:/RealityEngine; scratch only in your worktree .tmp.
- No model calls. Never kill processes by name. pytest per file (memory cap).
- The text layer often splits a value line across lines and prints '-' for blanks: a '-' is a column, count it.
- OCR digits ('2 69', '{57.62)'): normalise as the existing helpers do; when a value cannot be matched, treat it as
  unresolved (step 4), never guess.
- Structural only, no per-company rules.

Stop if: the column-position read changes any graded-R row and cannot be fixed in 2 tries; or the change passes ~150 lines.
Budget: ~110 tool calls.
