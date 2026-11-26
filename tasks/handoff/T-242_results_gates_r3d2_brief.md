# T-242 brief: results gates r3d2 - the r3d ambiguity rule must not touch rows outside a real two-values-one-date group

Ticket: T-242
permission: workspace-write (your worktree only)
Author: Eagle (27 Nov ~01:00 IST). Reviewer/recorder: Wolf (non-author).
Base: branch dsh/20261126T151707Z-ee04de04 (head 1b9fedb3) = r3d (agy 55c573aa, 5e484078) + r3e. Neither is on main yet.

Goal: r3d's `results_period_duration_ambiguous` rule (strip a duration back to the bare date, unverified) fires only on rows that are really in a
residue group - one printed label on one page with two or more DIFFERENT values for one date key whose column position cannot be read. Every other
row keeps its period and status exactly as before r3d.

Files: reality_engine/v2/observations.py (the r3d residue / column-position code and where apply_results_row_gates calls it),
reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md (results r3d bullet).

Accept:
- python -m pytest -q reality_engine/tests/test_results_gates.py ; then test_observations.py, test_ar_sections.py, test_deck_guards.py (one per call; pass).
- On the graded packs, 0 graded-R rows change status or period versus main: C:/RealityEngine/t242/results_ckpt1/pack.jsonl, results_grade_r2,
  results_grade_r3c/pack.jsonl, results_ckpt2/pack.jsonl, results_ckpt3/pack.jsonl, results_ckpt4/pack.jsonl (R = rows not named W/P/J in each
  fix note: D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_000N.fix.md, and results_grade_r2/fix.md). In particular these 8 rows that r3d
  downgrades today must be unchanged: ASARFI 48901, AAVAS 8962, BBTCL 3906, AKSHOPTFBR 11178, AKSHOPTFBR 11185, AMITSEC 37761, AEONXDIGI 26019,
  AVONMORE 94458 (observation ids in obs_results_fy27.db).
- r3d's own targets still fixed: AGARWALEYE 40bffc47 p9 '(a) Basic' 3.2 and 2.11 not 'Quarter ended'; AGARWALEYE 74f27462 p11 4.21 not 'Quarter ended';
  AANCHALISP dde8dc7b p9 'f) Depreciation' 61.54 not 'Quarter ended'.
- r3e's six ckpt_0002 fixes unchanged (APMIN 43952, ASTRONMULT 4987, ARCHIDPLY 44943, AMIC 37433, ALANKIT 32092, BLUECOAST 11486).

Evidence: the r3e worker (dsh ee04de04) measured the 8 graded-R downgrades above with reason `results_period_duration_ambiguous`; see
tasks/t242_results_measure.md (r3e section, 'Open problems') in the base branch.

## Steps
1. For each of the 8 rows: read its page (store doc_page, read-only) and print why the rule fired (group members, values, date key). Expect one of:
   a single value per label/date (not a group), equal values repeated (not ambiguous), or a group whose column position IS readable.
2. Narrow the rule so it requires >= 2 DIFFERENT values for the same (label, basis, segment, date key) on the page AND an unreadable column position;
   when only one value exists, or values are equal, leave the row exactly as it was (no strip, no status change).
3. Tests: one keep-case per distinct cause found in step 1 (synthetic page text), plus the r3d positive cases still passing.
4. Measure on a sqlite-backup copy of D:/RealityEngine/hy4_out/obs_results_fy27.db (WAL - never a plain file copy) with the gate function
   (flagged rows only is enough): rows the rule touches before/after, the 8 rows, and 20 random still-touched rows (seed 7) with page text.
5. Docs: DEVELOPER_GUIDE results r3d bullet -> r3d2 with the numbers.

## Limits
Never write D:/RealityEngine or C:/RealityEngine (scratch only in the worktree .tmp); no model calls; pytest per file; never kill processes by name;
structural rules only. Finish before 06:00 IST 27 Nov (Shivam: all operations stop by 08:00).
Stop if: a narrowing that keeps the 8 rows loses an r3d target in 2 tries.
Budget: ~80 tool calls.
