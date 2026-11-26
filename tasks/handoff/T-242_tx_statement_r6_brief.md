# T-242 brief: transcript statements r6 - four narrow period fixes on r5 (dsh DeepSeek, off-peak, 26 Nov, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: main at/after 389e009e (r4+r5 merged).

Goal: r5 is merged (net better than r3: period_anchored 9,959). Eagle's review D:/RealityEngine/t242/grades/tx_r5_review_eagle.md
(read first) found four remaining structural misses. Fix exactly these in reality_engine/v2/obs_speaker.py
(`anchored_period`, `_explicit_own_period` and helpers); change nothing else.

Evidence (must end as shown):
1. 'for the quarter' / 'during the quarter' bound to the figure beats a same-quarter-last-year comparative -> call quarter:
   IOLCP "EBITDA for the quarter rose 19.5% ... up from Rs. 58.2 crores in the same quarter last year"; BLS "revenue for the
   quarter was INR 891 crores, up 25% from INR 711 crores in the same quarter last year"; SOLARINDS "volume for the quarter
   grew by 16% year-on-year".
2. 'Q1 of FY27' form -> Q1 FY27 (ARMANFIN "Q1 of FY27 has been an encouraging start"); also 'Q2 of FY 27', 'first quarter
   of FY27'.
3. Named FY with a space or apostrophe -> that FY: AZAD "guidance ... for FY '25" -> FY25; 'FY 27', "FY'27", 'FY-27'.
4. 'during the year' / 'first half of the year' never resolve to the call QUARTER: TARACHAND "FY '26 ... deployed INR1,434
   million during the year" -> FY26 (was Q4 FY26); PDSL "During the first half of the year" -> H1 of the call's FY (or empty
   when the call is Q1) (was Q2 FY26); MMP "During the year" -> the call's FY (was Q2 FY27).
Keep r5's stay-empty cases empty (HFCL, CUB 'NIM for FY26' on a Q1 call, KTKBANK #36, EMSLIMITED #43) and its regains.

## Steps
1. One unit test per evidence line (as synthetic statements with a call period) + keep all r5 tests.
2. Implement the four rules.
3. Measure: reparse a COPY of the r3 baseline C:/RealityEngine/t242/tx394_reparse/tx394_r3.db's page_reply source - use
   the same `--reparse` command as tasks/t242_statement_r3_measure.md on a copy of D:/RealityEngine/hy4_out/
   obs_transcripts_394_v3.db taken with the sqlite backup API (the live DB is written by a loop; never a plain file copy) -
   report period_anchored vs r5's 9,959 and 0 graded-R change beyond period (C:/RealityEngine/t242/tx394_grade_r2).
4. Docs: r6 section in tasks/t242_statement_r3_measure.md; DEVELOPER_GUIDE.md bullet.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_statement_r3_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; test_observations.py - each separately, pass; the 9
evidence statements end as shown; period_anchored >= 9,959.
Stop if: a rule anchors a stay-empty case after 2 tries: report and stop. Hard stop by 06:00 IST Fri 27 Nov (Shivam:
operations stop by 08:00) - commit what passes.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine (copies in .tmp); no model calls;
never kill processes by name.
Budget: ~2 hours, ~120 tool calls.
