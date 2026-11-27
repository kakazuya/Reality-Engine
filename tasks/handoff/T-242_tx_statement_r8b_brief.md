# T-242 brief: transcript statements r8b - narrow the r8 base-cue block; consecutive-year spans only (dsh DeepSeek, 27 Nov 05:40, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: branch dsh/20261126T235250Z-423166af (r8 + Wolf's span fix 8df16b14).

Goal: r8 failed Eagle's review (tasks/t242_statement_r3_measure.md, "r8 FAILED"). Fix exactly three things in
reality_engine/v2/obs_speaker.py; change nothing else.

Evidence (must end as shown; call period in brackets):
1. The base-cue block (`_for_the_year_names_base`) fires only when the base cue binds "for the year" itself
   ("for the year a year ago", "for the previous year", "last year, for the year" with no figure between), never when
   an own figure is compared against/over a base:
   - [Q4 FY26] "Revenue for the year was INR 1,200 crores against INR 1,000 crores last year" -> FY26
   - [Q4 FY26] "EBITDA for the year grew 20% over the previous year to INR 300 crores" -> FY26
   - [Q2 FY27] "This compares with 15% in the same period last year; for the year we expect 18%" -> FY27
   - keep: [Q4 FY26] "Revenue for the year a year ago was 900 crores." -> '' (or FY25)
2. A two-year span needs consecutive years in `_EXPLICIT_FY_RE` too (the bound cue already does on this branch):
   [Q2 FY27] "Our revenue guidance for FY27 - 20% to 25% growth is intact." -> FY27; "Our guidance for FY27 - 25 crore
   capex." -> FY27; keep "FY25-26" / "FY25-'26" / "FY27/28" -> ending year.
   The failing test `test_r8_review_span_needs_consecutive_years_not_a_figure` must pass.
3. A leading "For FYnn," with a comma bound to a figure: [Q2 FY27] "For FY27, 20% to 25% revenue growth." -> FY27
   (today ''). Keep CUB-style "NIM for FY26" on a Q1 call empty.

## Steps
1. Unit tests for every line above; keep all r3-r8 tests.
2. Implement (structural; no company names).
3. Docs: adjust the r8 sentence in docs/DEVELOPER_GUIDE.md; add an r8b note in tasks/t242_statement_r3_measure.md.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_statement_r3_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; python -m pytest -q
reality_engine/tests/test_observations.py - each separately, pass. No reparse measure (operations stop 08:00).
Stop if: a fix breaks an r3-r8 test after 2 tries: report and stop. HARD STOP 06:25 IST - commit what passes.
Pitfalls: pytest, not unittest; never commit temp dirs (.pt_*, .pp*; use --basetemp under .tmp/); never write under
C:/RealityEngine or D:/RealityEngine; no model calls; never kill processes by name.
Budget: ~40 minutes, ~50 tool calls.
