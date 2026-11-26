# T-242 brief: transcript statements r8 - two narrow period fixes on r7 (dsh DeepSeek, 27 Nov 05:25, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: main at/after f105dfba (r7 + Wolf review fixes merged).

Goal: two misreads left after r7 (tasks/t242_statement_r3_measure.md, "Open for r8"). Fix exactly these in
reality_engine/v2/obs_speaker.py (`_explicit_own_period`, `_BOUND_FY_CUE_RE` and helpers); change nothing else.

Evidence (must end as shown; call period in brackets):
1. [Q4 FY26] "Revenue for the year a year ago was 900 crores." -> '' or FY25, never FY26. A base cue ('a year ago',
   'last year', 'previous year', 'same period last year') in the sentence blocks the r7 guidance-year rule
   (`_GUIDANCE_YEAR_CUE_RE` branch) and the Q4 "for the year" -> call FY path.
   Counter-tests that must stay: HINDZINC [Q4 FY26] "our growth capex guidance for the year would be in the range of
   $350 million to $400 million." -> FY27; "Finance costs for the year stood at 562 million." [Q2 FY27] -> FY27.
2. [Q2 FY26] "Our guidance for FY25-'26 is revenue of INR 700 crores." and "planned outlay for FY 25-26 stands at INR
   250 crores" -> FY26 (a two-year span 'FYaa-bb' / "FYaa-'bb" names the year ending bb), as the plain 'FY25-26'
   token already does. Counter: "FY '25 revenue was INR 500 crores" [Q2 FY26] keeps FY25.

## Steps
1. One unit test per evidence line and counter-test in reality_engine/tests/test_obs_speaker.py; keep every r3-r7 test.
2. Implement the two rules (structural, no company names in code).
3. Docs: one r8 sentence in the r7 paragraph of docs/DEVELOPER_GUIDE.md; tick the two items in
   tasks/t242_statement_r3_measure.md "Open for r8".

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_statement_r3_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; python -m pytest -q
reality_engine/tests/test_observations.py - each separately, pass; the evidence lines end as shown.
No reparse measure this round (operations stop 08:00); say so in the report.
Stop if: a fix breaks an r3-r7 test after 2 tries: report and stop. HARD STOP 06:25 IST (peak starts 06:30) -
commit what passes.
Pitfalls: pytest, not unittest; never commit temp dirs (.pt_*, .pp*; use --basetemp under .tmp/ which is
gitignored); never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill processes by name.
Budget: ~55 minutes, ~70 tool calls.
