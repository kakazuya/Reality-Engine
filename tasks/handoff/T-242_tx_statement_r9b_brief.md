# T-242 brief: transcript statements r9b - past-tense "expected/targeted/guided/planned" is a recap, not a forward word (agy Hydrogen high, 27 Nov 07:20, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: branch dsh/20261127T002143Z-c59dbb00 (r9, failed review: tasks/t242_statement_r3_measure.md "r9 FAILED").

Goal: r9's forward-word-before-"for the year" rule (in `_explicit_own_period`, reality_engine/v2/obs_speaker.py) matches the
past tense "expected", so a recap gets the guidance year. Make forward cues exclude past tense used as a recap; change nothing else.

Evidence (must end as shown; call period in brackets):
1. [Q4 FY26] "We expected revenue for the year to be INR 1,100 crores, and it came in at INR 1,200 crores." -> FY26 or '' (never FY27).
2. [Q4 FY26] "We expect revenue for the year to be INR 1,100 crores." -> FY27 (present-tense twin).
3. [Q4 FY26] "We had targeted EBITDA for the year of INR 300 crores and delivered INR 320 crores." -> FY26 or ''.
Keep: every r3-r9 test (the r9 targets: "Revenue for the year was INR 1,200 crores and we expect 15% growth next year" -> FY26;
"We expect revenue for the year to be around INR 1,500 crores" -> FY27; "For the year we expect 18% growth." -> FY27).

## Steps
1. Find where `_FORWARD_CUE_RE` (or the r9 helper) accepts expected/targeted/guided/planned; exclude the past-tense forms when they
   are a recap (past tense of the forward verb, or "had" + participle). Check that other uses of `_FORWARD_CUE_RE` keep their tests.
2. One test function with the three lines above.
3. Docs: one r9b sentence in docs/DEVELOPER_GUIDE.md (r9 sentence); r9b note in tasks/t242_statement_r3_measure.md.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_statement_r3_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; python -m pytest -q reality_engine/tests/test_observations.py
- each separately, pass.
Stop if: excluding past tense breaks an r3-r9 test after 2 tries: report and stop. HARD STOP 07:45 IST - commit what passes.
Pitfalls: pytest, not unittest; never commit temp dirs or PROGRESS_NOTES.md; never write under C:/RealityEngine or D:/RealityEngine;
no model calls; never kill processes by name.
Budget: ~20 minutes.
