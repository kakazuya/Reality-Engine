# T-242: AR ckpt_0002 fix - periods must be printed, a date is never a value (Hydrogen, 25 Nov 2026, Eagle for Wolf)

Ticket: T-242

Goal: AR audit checkpoint 2 (obs_ar_fy27, prompt fp 48d75aa69de7) failed 53/3/3/1 (W+J 6.7%). Wolf owns AR but is out of
quota, so Eagle took it over (Shivam, 25 Nov). Add script row gates in reality_engine/v2/observations.py; do not change
the AR prompt, and the fingerprint must stay 48d75aa69de7. Use structural rules, patterns only.

Evidence (C:/RealityEngine/t242/ar_grade_ckpt2/pack.jsonl, ids = line numbers; each row carries page_text):
- #46 AFSL p244 count.shares 166,667: period 'December 2019', but the column is 'P.Y.' (March 31, 2025). Neither
  'December' nor '2019' is printed on the page.
- #49 63MOONS p93 shareholding_pct 0.23: period 'March 2022', but the table says 'As on 31st March, 2026'. '2022' is
  not printed on the page.
- #13 ARL p6 NEW:director_term_effective_date: value 1.0 from value_text 'December 01, 2026'. A date is never a
  number.
- #34 AIAENG p36: period 'end of Financial Year' has no year.
- #21 BALKRISIND p343: consolidated group currency sensitivity tagged entity_scope='subsidiary'.
- #39 5PAISA p144: basis 'consolidated' taken from prose ("fractional entitlements, which were consolidated").

Steps:
1. Period printed check (AR number rows): a row whose period names a year (or FY) that is printed neither on its page
   nor in the previous page's text is `unverified` with reason `period_not_printed`. Reuse `period_in_text` or the
   same year logic. A period with no year at all ('end of Financial Year', 'P.Y.', 'C.Y.') is `unverified`
   `period_no_year`, unless an instant/label rule already resolved it to a printed date.
2. Date as value: a number row whose value_text parses as a date (month name + day/year, dd.mm.yyyy, dd/mm/yyyy, ISO)
   is dropped (junk), whatever the measure.
3. Basis only from a heading: AR basis set from the word 'consolidated' inside running prose (not a heading or table
   title line) is cleared. Look at how the page-head basis rule works (`basis_source`) and keep headings.
4. entity_scope='subsidiary' on a row whose page heading says Consolidated / Group and whose label names no subsidiary
   goes back to 'company'.
5. Tests for each shape (patterns only), with counter-tests: a printed 'As at 31 March 2026' column stays verified; a
   previous page's 'Year ended March 31, 2025' header carries over.
6. Measure on a copy: reparse C:/RealityEngine/t242/reparse/ar_r1.db or a fresh backup of
   D:/RealityEngine/hy4_out/obs_ar_fy27.db (sqlite backup to your worktree .tmp; never write hy4_out). Report:
   - rows each rule touches;
   - 20 sampled rows per rule, quoted with page evidence;
   - the 7 evidence rows' new state;
   - every row graded R in ar_grade_ckpt2 (grades.csv beside the pack) and ar_grade_fresh2 that changes status
     (target 0).
7. Docs: a DEVELOPER_GUIDE entry beside the AR row-gate entries. Commit in the worktree.

Accept: tests pass (test_v2_guards.py and the AR tests you touch); #13 dropped; #46, #49 and #34 unverified; #21 and
#39 fixed; 0 graded R rows lose verified; AR fp unchanged.
Stop if: rule 1 unverifies more than 8% of verified AR rows (report the share and 20 examples before going on).
Budget: about 2 hours; write scope is your worktree only.
