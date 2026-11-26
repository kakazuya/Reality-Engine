# T-242 brief: arithmetic check layer for stored number rows (dsh DeepSeek, off-peak, 26 Nov, Wolf)

Ticket: T-242
permission: write (your worktree only)

Goal: a script check layer (no model) that flags stored number rows whose arithmetic is impossible, written as verdict
files beside the reads, exactly like `reality_engine/v2/xbrl_crosscheck.py` (read it first: module shape, verdict
JSON, CLI). Shivam 26 Nov: never block reading; checks improve accuracy by moving row status at load time.

Evidence (graded W rows these checks must catch):
- Results AVI p11 (obs_results_fy27, 'd.Employee benefits expenses' 350 printed 3.50): the column's components do not
  sum to the printed Total Expenses 2,661.03 = 2,655.02 + 3.50 + 0.34 + 2.17.
- Results ADVENZYMES p7: 0.05 read from the 2025 column for 2026 (2026 is (8.05)); the 2026 column no longer sums.
- AR ARCHIDPLY 'Chemicals in Kgs' 5,499.65 stored as raw_material_cost while the table's total is 19,070.11.
- AR ABB 'Nelamangala' 17.07 stored as capital_work_in_progress while the total is 94.77.
- Results ARVSMART: a 'net loss' stored positive as profit.
Rows carry `group_path` (42,849 of 56,666 results rows), `is_total` (9,149), `period`, `basis`, `value`, `scale`,
`doc_key`, `page`, `printed_label`, `measure`. Output DBs: D:/RealityEngine/hy4_out/obs_results_fy27.db,
obs_ar_fy27.db, obs_decks_fy27.db (open read-only; hy4 loops write them - use timeout=300).

## Steps
1. New module reality_engine/v2/arith_checks.py, CLI `--db <hy4 db>` -> --out-dir (default D:/RealityEngine/checks/arith; YOU run it with --out-dir .tmp/checks_arith, Wolf copies) <db stem>.jsonl
   (write to .tmp then replace), one verdict per flagged row: {id, verdict, rule, evidence, checker:'arith_checks'}.
2. Rule `sum_mismatch`: within one (doc_key, page, period, basis), a row with is_total=1 whose group_path children
   (rows whose group_path ends with the total's group) sum to a different value beyond 1% or rounding -> flag the
   total AND each child as `arith_sum_mismatch`; when exactly one child explains the gap by a power of ten (AVI 350 vs
   3.50), flag only that child `arith_unit_suspect` with the fixed value.
3. Rule `subset_as_total`: a row stored under a canonical TOTAL measure (raw_material_cost, capital_work_in_progress,
   borrowings, revenue_from_operations, total_*, ...) while another row on the same page/period/basis with the same
   measure (or is_total=1 in its group) is larger and the row is one of its components -> `arith_subset_as_total`.
4. Rule `sign`: measure/label says loss/expense vs profit with the opposite sign of what the label prints
   ('net loss' stored positive under pat/profit) -> `arith_sign`.
5. Rule `jump`: same symbol, measure, basis, period kind, across adjacent quarters/years in the same DB, a 90x-110x
   or 1/90-1/110 ratio -> `arith_jump` on the outlier.
6. Tests reality_engine/tests/test_arith_checks.py: one synthetic case per evidence row + counter-tests (a right total;
   a genuine sign-negative exceptional item; a real 2x growth).
7. Run it on the three DBs; report counts per rule and 20 seeded (seed 7) flagged rows per rule with page text read,
   judged right/wrong flag.
8. Docs: one DEVELOPER_GUIDE.md bullet beside the XBRL cross-check bullet.
Do NOT edit load_observations.py: Wolf wires the verdicts into the loader after review.

Files: reality_engine/v2/arith_checks.py, reality_engine/tests/test_arith_checks.py, docs/DEVELOPER_GUIDE.md.
Accept: python -m pytest -q reality_engine/tests/test_arith_checks.py passes; flag precision on your 20-row samples
>= 80% per rule (a rule under 80% is reported, not shipped); counts per rule per DB.
Stop if: a rule flags > 15% of a DB's verified rows: report and stop that rule.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine (your runs use --out-dir .tmp/checks_arith); no model
calls; never kill processes by name; hy4 DBs are live (read-only, timeout); empty beats wrong.
Budget: ~2 hours, ~150 tool calls.
