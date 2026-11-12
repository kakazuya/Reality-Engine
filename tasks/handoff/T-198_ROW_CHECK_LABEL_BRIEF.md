Ticket: T-198

Goal: stop the independent row checker from quarantining a company's own printed figure because of words inside that
figure's own label qualifier, make cross-document checks compare like with like, and make `pilot3_fact` say plainly
when the company states a figure it did not prefer. General rules for every company and metric; no tuning to a
question or a company.

## Anti-overfitting rules (binding)
- Never open `D:/RealityEngine/aurobindo/questions/`, `answers/`, `report/`, `rerun_t195/`, `D:/RealityEngine/aurobindo_ab/`,
  or any grades file. No company, product, person or figure literal in code or tests
  (`test_pilot3_no_company_literals.py` must pass); fixtures use invented companies and numbers.
- A rule change is judged by how many rows it moves on stores the test questions never touched (pilot10), not by one row.

## Evidence (T-196, 12 Nov, traced by Opus on `D:/RealityEngine/aurobindo/aurobindo.db`)
- `kpi_series` row 1012 (deck p16, known 2025-05-26): quote "EBITDA (before Forex and Other Income)\n1,792\n1,687\n6.2%\n1,628\n10.1%\n6,605".
  `row_check` status `quarantined` (`row_checks_v2`). `row_check_fail` reasons: `label_conflict` x2 ("label 'other
  income' of non_interest_income sits between the ebitda label and the number"; "... is nearer the number than
  ebitda"), `multi_number` ("6 numbers in the quote: column not pinned"), `uncorroborated`, `cross_doc` ("1 independent
  source(s) disagree by more than 1.5%"). Row 1020 (call transcript, same 6,605) also quarantined on `cross_doc`.
- Consequence: `p3ask fact symbol=<it> metric=ebitda period=FY25 as_of=2025-06-30` routes to `fin` and serves the
  derived 6,582.8 crore (F_EBITDA) as preferred, `why_this_one` "the preferred xbrl_derived figure"; the answerer
  trusted "preferred". With a later as_of a later deck row (unverified) is served instead, so the defect hides only
  at early dates.
- Likely cross_doc witness: a different definition of the same metric (an "EBITDA before R&D" row, 8,148) or the
  derived figure. Verify which; do not guess.

## Method
1. Reproduce on a COPY (copy recipe: checkpoint, copy into `.tmp`, `PRAGMA journal_mode=DELETE`) with
   `python -m reality_engine.pilot3.build --profile D:/RealityEngine/aurobindo/aurobindo_profile.json --out <copy> --part checks`
   and read `row_check_fail` for the rows above. Write the failing tests first (fixture rows).
2. **Label span rule** (`reality_engine/pilot3/row_checks.py`, `label_hits`, `nearest_strong_label`, the `label_conflict`
   and `label_foreign` checks): a metric label's span includes a qualifier that follows it in brackets or after
   "before / excluding / ex- / net of / including" up to the line end or closing bracket. A foreign label that lies
   inside that span is part of the definition, never a conflict. Fixtures across sectors: "EBITDA (before Forex and
   Other Income)", "Revenue (net of GST)", "PAT (after exceptional items)", "Net interest income (excluding other
   income)", "Order inflow (including L1)". Each must pass; a real conflict ("Other income 120" on its own line between
   the label and the number) must still fail.
3. **Definition key and like-for-like cross_doc**: derive a `definition` key from the qualifier (normalised words, e.g.
   `before:forex,other_income`, `before:r_and_d`); `cross_doc` compares a row only with witnesses of the same metric,
   period, basis AND definition key; a derived figure (F_EBITDA etc.) is never a cross_doc witness against a
   company-stated row of a different definition. Store the key on the check row (and on `kpi_series` if a column is
   cheap; additive migration in `schema.py`).
4. **multi_number with a pinned column**: when the table row's numbers align with column headers that `kpi.py`'s
   `_kept_columns(cols, current)` already resolves, the column is pinned; do not fail `multi_number` then.
5. **`pilot3_fact` honesty** (`plugins/reality-data/server/lookups_pilot3.py` `fact()` ~2305 and `_fact_route`): when the
   served figure is derived and a company-stated row exists for the same metric/period/basis known on or before as_of
   (any check status, including quarantined), add `company_stated` = {value, unit, definition, source, check_status,
   why_not_preferred} and make `why_this_one` say so. Never write "preferred" for a derived figure without naming the
   company-stated one beside it.
6. Rebuild `--part checks` (then `preferred` if it reads check status) on COPIES of aurobindo and pilot10 with main code
   and with the branch, same starting copy, and diff `row_check` statuses: per table and status, rows moved
   quarantined->unverified/verified and the reverse. Write `.tmp/T-198_DIFF.md` with counts per store and 15 sampled
   moved rows per store (quote, page, old/new status, reason), so Opus can hand-check them.

## Files
`reality_engine/pilot3/row_checks.py`, `reality_engine/pilot3/schema.py` (if a column is added),
`plugins/reality-data/server/lookups_pilot3.py` (`fact`, `_fact_route` only; T-197 owns topic/statements/search/docs/cells),
tests `reality_engine/tests/test_row_checks.py`, `reality_engine/tests/test_pilot3_row_check_serve.py`,
`reality_engine/tests/test_pilot3_preferred.py`; docs `docs/PILOT3_BLUEPRINT.md` (row checks section),
`docs/DEVELOPER_GUIDE.md`.

## Accept
- Tests pass one file per process (`--basetemp=.tmp/pt<n>`, new name each run): `test_row_checks.py`,
  `test_pilot3_row_check_serve.py`, `test_pilot3_preferred.py`, `test_pilot3_no_company_literals.py`, plus new tests.
- `.tmp/T-198_DIFF.md` exists with both stores' status-move counts and samples; zero rows move from quarantined to
  verified without a passing label/definition reason shown.

## Stop if
- more than 3% of pilot10's checked rows change status (report counts, stop for review);
- a fix needs a company/metric literal outside the vocabulary files.

## Budget
3 hours, one session, DeepSeek off-peak. Never write live stores. Do not commit PROGRESS_NOTES.md.
