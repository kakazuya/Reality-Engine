Ticket: T-192

Goal: fix, as general rules (never per company), five kinds of wrong stored rows that four independent Opus graders
found in the T-189 AUROPHARMA store (`D:/RealityEngine/aurobindo/aurobindo.db`). Every model that answered was caught
by them. A fix is right only when it is a rule any listed company gets through the same code.

Evidence (grader findings, 12 Nov; key `D:/RealityEngine/aurobindo/report/key_round1.csv`, grades `report/grades*.csv`):
1. ROE (question A25): `ratio_panel` roe FY26 = 9.24% = PAT 3,502.97 / CLOSING equity 37,883. The annual report
   (FY26 AR p113) states 9.9%; on AVERAGE owners' equity (32,653 + 37,891)/2 it is 9.93%. The row is labelled or read as
   return on average equity. Rule: ROE on average owners' equity when the opening figure is held; closing-equity
   ROE only when it is not, and then labelled `basis=closing_equity`.
2. EBITDA (A55): derived FY25 EBITDA = 6,582.79 cr includes the Rs 23 cr forex loss; the company reports EBITDA
   "before forex and other income" = 6,605 cr, 20.8% (FY25 deck p16, AR p47). A second `ratio_panel` row holds
   EBITDA 6,555.61 with margin 20.66%: two derivations that disagree. And `ebitda_margin_pct` FY25 = 21.4 is the
   Q4 FY25 quarter's margin filed under the annual period. Rules: one EBITDA definition (state it in the formula
   row; exclude forex gain/loss and other income when the statement prints them separately); a margin's numerator
   and denominator come from the same period and the same EBITDA row; an annual period is never filled from a
   quarter.
3. KPI (A03): a stored KPI row carries Q1 FY27 operating EBITDA margin 20.4%; deck p13 and p7 state 21.0%. Find where
   20.4 came from (likely the Q1 FY26 comparative column read as the current quarter) and fix the column rule.
4. Guidance (B04): guidance row `ebitda_margin` FY31 = 15 is Lannett's (a US subsidiary) margin from an analyst
   question (transcript c19eed01 p18), stored as group guidance; the transcript doc is also labelled with the wrong
   call period (Q1FY31). Rules: a target stated for a subsidiary/segment carries that entity and is never served as
   the group's; the call period comes from the filing record, not from a year mentioned in the text.
5. Share count (A39): `share_capital` held 575,400,000 = paid-up capital Rs 57.54 cr / face value, a rounded number
   served as exact. The exact 575,377,895 is in the SHP XBRL (fetched 12 Nov; the store now prefers it). Rule: a
   count derived from rounded capital is marked `derived_from_capital` and never preferred over a filed exact count.

Files: find the writers yourself first (`code-tools outline`, then grep): `reality_engine/pilot3/ratios.py`,
`reality_engine/pilot3/preferred.py`, `reality_engine/pilot3/stores.py`, `reality_engine/pilot3/kpi*.py`,
`reality_engine/pilot3/guidance*.py`, `reality_engine/pilot3/transcripts*.py`, their tests under
`reality_engine/tests/test_pilot3_*.py`. Docs: `docs/PILOT3_BLUEPRINT.md` (methods) and `docs/DEVELOPER_GUIDE.md`.

Steps:
1. For each defect, reproduce it on a COPY of the store in your `.tmp` (`python -m reality_engine.scripts.p3ask --db
   <copy> sql query=...`), find the writing function and line, and write the failing test first (fixture rows, no
   real DB in tests).
2. Fix as a rule. No symbol, company name or ISIN literal in code (`test_pilot3_no_company_literals.py` must pass).
3. Rebuild only the affected parts on copies of the six stores (`D:/RealityEngine/{p20/p20new.db, u8/u8.db,
   q12/q12.db, n10/n10.db, pilot10/pilot10.db, aurobindo/aurobindo.db}`; copy recipe: checkpoint, copy,
   `PRAGMA journal_mode=DELETE`) with `python -m reality_engine.pilot3.build --profile <profile> --out <copy> --part
   <part>`, and diff old vs new rows of the touched tables.
4. Write `.tmp/T-192_DIFF.md`: per store and defect, rows changed / added / removed, and 10 sampled changed rows with
   their source page, so an independent grader can check them.

Accept: `python -m pytest reality_engine/tests/test_pilot3_ratios.py reality_engine/tests/test_pilot3_preferred.py
reality_engine/tests/test_pilot3_no_company_literals.py -q` plus every new test, run one file at a time; the five
AUROPHARMA rows above come out right on the rebuilt copy; `.tmp/T-192_DIFF.md` exists; docs updated in the same
branch.

Limits and pitfalls: never write to the live stores under D:/RealityEngine (copies in `.tmp` only). Never loosen a
row check to make a test pass. Run tests per file (a one-process pilot3 pytest hit 7.9 GB on 4 Nov). Do not commit
PROGRESS_NOTES.md. Do not open `D:/RealityEngine/aurobindo/questions/` or any answers file.

Stop if: a fix would change more than 2% of a table's rows in any store other than aurobindo (report the count and
stop for review); or a defect needs a judgement about what the company meant (write it up, skip it).

Budget: 3 hours; one session.

## Round 2 (12 Nov 14:25, Opus review of dsh/20261112T075239Z-35e1d0fc; you start from that branch)
Keep: the ROE average-equity rule in `ratios.py` and the call period from `doc_period` in `guidance.py`.
Fix, verbatim review findings:
- R1. `ratios.py` / `statements.py` forex: the keys `forex_gain_loss`, `exchange_gain_loss`,
  `foreign_exchange_gain_loss` exist in NO store (checked: `SELECT DISTINCT line_item FROM fin_annual_line` and
  `fin_quarter_xbrl` on aurobindo.db), so EBITDA did not change. Find how the filed XBRL actually carries forex (grep
  the results_xbrl parser and the AUROPHARMA FY25 quarterly lines); if forex is not a separate filed line, do not
  derive it. Instead: when the company prints its own EBITDA (deck / press release KPI row, `kpi_series`), serve that
  as the preferred EBITDA and margin, with the derived one kept as a second, labelled row. And fix `ebitda_margin_pct`
  FY25 = 21.4, which is the Q4 FY25 quarter margin under the annual period: an annual row is never filled from a
  quarter.
- R2. `stores.py` line 287: you replaced the `known_at_source` text with "derived_from_capital". That destroys the
  provenance. Revert it; mark the derived count in its own field (or the `unit`/`definition` column the table has),
  and make the share-count preference (`lookups_pilot3` holding / `preferred`) pick a filed exact count (SHP
  `shp_category` total) over a capital-derived one for the same date.
- R3. Defect 3 (KPI Q1 FY27 operating EBITDA margin 20.4 vs 21.0 printed, deck p7/p13) and defect 4 (Lannett margin
  stored as group guidance) were not touched. Do them.
- R4. No tests were written. For every defect add a test that FAILS on main and passes on your branch (fixture rows).
  The 9 `test_pilot3_ratios.py` errors are a tmpdir problem: set `--basetemp=.tmp/pt` and make them run.
- R5. Steps 3-4 are required: rebuild the touched parts on store COPIES and write `.tmp/T-192_DIFF.md`.
Accept (round 2): the tests above pass one file at a time; `.tmp/T-192_DIFF.md` shows the five AUROPHARMA rows right
and per-store changed-row counts. Budget 3 hours.
