# T-242 brief: transcript statements r9 - reported "for the year" figure on a Q4 call; forward word before it (dsh DeepSeek, 27 Nov 05:52, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: main at/after 15341fbe (r8b merged).

Goal: three statements left empty after r8b (tasks/t242_statement_r3_measure.md, "Open for r9"). Fix only these in
reality_engine/v2/obs_speaker.py (`_explicit_own_period` guidance-year branch and helpers); change nothing else.

Evidence (must end as shown; call period in brackets):
1. [Q4 FY26] "Revenue for the year was INR 1,200 crores and we expect 15% growth next year." -> FY26 ("for the year"
   followed by a past/present reporting verb - was/were/stood/grew/rose/declined/is at - and a figure, before any
   forward word, is the call's own FY on a Q4 call).
2. [Q4 FY26] "EBITDA for the year stood at INR 300 crores, and we will continue to invest." -> FY26.
3. [Q4 FY26] "We expect revenue for the year to be around INR 1,500 crores." -> FY27 (a forward word BEFORE "for the
   year" in the same clause makes it the guidance year).
Keep (must not change): "For the year we expect 18% growth." [Q4 FY26] -> FY27; "Revenue for the year a year ago was 900
crores." [Q4 FY26] -> ''; "This compares with 15% in the same period last year; for the year we expect 18%" [Q2 FY27] ->
FY27; "Finance costs for the year stood at 562 million." [Q2 FY27] -> FY27; HINDZINC "our growth capex guidance for the
year would be in the range of $350 million to $400 million." [Q4 FY26] -> FY27; every r3-r8b test.
Also: on a Q1-Q3 call, case 1/2 phrasing ("Revenue for the year was ...") must NOT become the call FY unless r3-r8b
already did so (it is a year-to-date figure there) - add one counter-test on [Q2 FY27].

## Steps
1. Unit tests for every line above.
2. Implement (structural; no company names).
3. Docs: one r9 sentence in docs/DEVELOPER_GUIDE.md (r7/r8 paragraph); r9 section in tasks/t242_statement_r3_measure.md.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_statement_r3_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; python -m pytest -q
reality_engine/tests/test_observations.py - each separately, pass. No reparse measure (operations stop 08:00).
Stop if: a fix breaks an r3-r8b test after 2 tries: report and stop. HARD STOP 06:25 IST - commit what passes.
Pitfalls: pytest, not unittest; never commit temp dirs or PROGRESS_NOTES.md; never write under C:/RealityEngine or
D:/RealityEngine; no model calls; never kill processes by name.
Budget: ~30 minutes, ~45 tool calls.
