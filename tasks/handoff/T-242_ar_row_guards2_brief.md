# T-242: annual-report row guards round 2: subset rows, unknown units, basis conflicts (DeepSeek, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: stop annual-report rows that are wrong from being stored `verified`. A strict fresh grade of 60 verified AR rows
after the statement gate was 49 right / 4 partial / 7 wrong / 0 junk (11.7% wrong; the bar is at most 5%). Add four
script guards to `reality_engine/v2/observations.py` so those wrong rows are stored `unverified` with a reason, while
the right rows stay verified.

Evidence (the strict grade: C:/RealityEngine/t242/ar_grade_fresh/grades.csv; rows: ar_grade_fresh/pack.jsonl,
taken from C:/RealityEngine/t242/pilot_ar_reparsed2.db, table observation):
- #10 AVEER p86: measure trade_payables, printed_label "More than 3 years", value 1.72 lakh. That is one ageing
  bucket stored as total trade payables.
- #42 (related-party note): "Purchase of raw materials - Beekaylon Synthetics" stored as raw_material_cost, with
  unit "`" and scale 1.0 on a page printed "In Lakhs".
- #30 BHARATFORG p63: measure profit_before_tax_growth_yoy, printed_label "an increase of", printed_axis empty,
  11.2%. The prose is about consolidated revenue, not PBT.
- #28 BALPHARMA p183: unit "vehicle", scale 1.0 (printed_label "- vehicle loans"; the page is INR lakhs).
- #56: the page is headed "Notes to the standalone financial statements", but the row is stored
  basis=consolidated.
- #9, #15, #19, #39 (P): unit empty although the page prints "(Rs. in lacs)", "(times)" or "(in millions)".

Code map (read these first; use code-tools `outline` on observations.py, do not read the whole file):
- `apply_ar_statement_gate` and `apply_number_gates`, near line 3682. Add the new AR guards here (doc_type
  annual_report only), as a new function `apply_ar_row_guards2(rows, page_text)` called from apply_number_gates (or
  from where apply_number_gates is called; pass the page text through).
- `infer_unit_family` (line ~1093), `UNIT_PATTERNS` (~993), `UNIT_SCALE` (~1335).
- Basis: the `row["basis"] = detect_basis(...)` chain, ~line 3491-3496, and `page_basis(page_text)` at line 2302.
- `--reparse` re-runs build_observations plus the number gates on stored replies (DEVELOPER_GUIDE "--reparse").

Steps:
1. Unknown unit: on an AR number row, `unit` non-empty and `infer_unit_family(unit) == ""` -> unverified, reason
   `ar_unit_unknown: <unit>`.
2. Missing unit with a page note: on an AR money row with an empty unit, if the page prints exactly one
   "(… in lakhs / lacs / crore / million / thousand …)" money note, fill unit and scale from it (record
   `unit_source='page_note'` in status_reason), keeping the row's status. If the page prints two different money
   notes, leave it.
3. Subset label: an AR number row whose printed_label is an ageing bucket ("More than N years", "N-M years",
   "< 6 months", "0-30 days", "Not due") or names a party (Pvt / Private Limited / Ltd / Limited / LLP), while the
   measure is not an ageing / related-party / subsidiary / segment measure (see OFF_STATEMENT_WORDS) and the row
   has no segment/customer dimension -> unverified, reason `ar_subset_label`.
4. Narrative growth: an AR row whose measure ends in `_growth_yoy` (or similar growth ids) with an empty
   printed_axis and a printed_label holding none of the measure's own words (for example "an increase of") ->
   unverified, reason `ar_growth_unlabelled`.
5. Basis conflict: on AR pages where `page_basis(page_text)` is non-empty and differs from the row's basis ->
   unverified, reason `ar_basis_conflict`. Do not overwrite the basis; a page that prints both bases already
   returns "".
6. Tests in `reality_engine/tests/test_ar_row_guards.py` (extend it): one test per guard built from the evidence
   rows above, plus a right row that must stay verified (for example "Trade payables turnover 0.04 Times" and
   "Return on Capital Employed 18.55%").
7. Run `--reparse` of C:/RealityEngine/t242/pilot_ar_reparsed2.db into a NEW copy
   C:/RealityEngine/t242/pilot_ar_guards2.db (never in place; copy first). Report:
   - verified counts before and after, plus counts by new reason;
   - for the 60 graded rows, matched by symbol+page+measure+value: how many of the 7 W and 4 P are no longer
     verified, and how many of the 49 R lost verified. Target: all 7 W not verified, at most 3 R lost.
8. Docs: one paragraph in docs/DEVELOPER_GUIDE.md beside the AR statement gate paragraph.

Pitfalls:
- The Bash heredoc mangles `\n` and `\b` in Python source. Edit with the edit tool, never `cat <<EOF` into .py.
  `test_no_control_chars.py` must pass.
- Do not touch transcript code: process_window, apply_transcript_number_gate and statement speaker code are being
  changed by another worker.
- No per-company rules; structural patterns only.
- Run pytest per file, not the whole suite (RAM).

Accept: `python -m pytest reality_engine/tests/test_ar_row_guards.py reality_engine/tests/test_ar_statements.py
reality_engine/tests/test_observations.py reality_engine/tests/test_no_control_chars.py -q` passes. The step 7 report
shows 7/7 W not verified and at most 3 R lost.
Stop if: more than 3 graded R rows lose verified after two attempts. Report which guard costs them and stop.
Budget: about 2 hours; write scope is your worktree only.
