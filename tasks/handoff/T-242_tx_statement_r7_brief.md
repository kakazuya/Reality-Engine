# T-242 brief: transcript statements r7 - explicit own-period cues bound to a figure must anchor; past-tense recaps keep their period

Ticket: T-242
permission: workspace-write (your worktree only)
Author: Eagle (27 Nov 02:15 IST, from the r6 review D:/RealityEngine/t242/grades/tx_r6_review_eagle.md). Reviewer: Wolf (non-author).
Base: main (tx r6 merged e289b61f).

Goal: the statements r6 still loses a right period for, or relabels wrongly, get their period from an explicit cue bound to the figure, without
undoing r3-r6 (stay-empty cases stay empty; the 36 graded-R rows of tx394_grade_r2 unchanged).

Files: reality_engine/v2/obs_speaker.py (anchored_period and its helpers), reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md
(statement-window / prepared-remark anchor bullet).

Accept:
- python -m pytest -q reality_engine/tests/test_obs_speaker.py ; python -m pytest -q reality_engine/tests/test_observations.py (each passes).
- Every evidence statement below gets the period named; every keep-case keeps r6's result; all r3-r6 tests still pass.
- Measured like r6 (5 store shards over the closed r3 copy C:/RealityEngine/t242/tx394_reparse/tx394_r3.db with the r6 helper scripts as a model,
  or the sharded --reparse path), compared with r6's numbers (regained 1,769 / lost 1,115 / relabelled 301 vs r3): lost must fall, relabelled-worse
  must not rise; 20 random newly regained + 20 still-lost (seed 7) with statement text in your answer. If the full measure cannot finish by 05:15,
  report the per-statement evidence results and say the measure is owed.

## Evidence (r6 output -> what the statement prints; call period in brackets)
Lost, must anchor:
1. YASHO [Q4 FY26 or Q1 FY27 call]: "On capital expenditure, the planned outlay for FY27 stands at INR250 crores." -> FY27 (a named FY bound to the figure,
   forward or not).
2. PSB [Q1 FY27]: "Slippages are broadly in line with the previous quarters, this time these slippages are at Rs.207 crores and the slippage ratio is
   at 0.18% for the quarter, so overall it will be annualised ..." -> Q1 FY27 ('for the quarter' / 'this time' bound to the figure wins over
   'previous quarters' comparative and the forward 'will be annualised').
3. TRIVENI [Q4 FY26]: "... with an average sugar pricing of refined at ₹42.20 and sulphitation at about ₹41.50 today, it has broadly been the same in
   this quarter ..." -> Q4 FY26 ('in this quarter').
4. HINDZINC [Q4 FY26 call, guidance for FY27 or FY26 per the call]: "In line with Board approved growth projects, our growth capex guidance for the year
   would be in the range of $350 million to $400 million." -> the call's guidance year (on a Q4 call the coming FY; on Q1-Q3 the current FY).
5. WELENT [Q4 FY26]: "Revenue from operations stood at INR845 crores, marking a 9% year-on-year decline." -> the call period (an 'X stood at <figure>'
   with only a year-on-year comparative and no other period cue is the call's own period).
Relabelled worse, must keep r3's period:
6. TARACHAND: "On our last earnings call in January, I had shared that the company was targeting to close Q4 with revenue of INR100 crores plus ..." ->
   Q4 FY26 (r6 gave FY27): a past-tense recap ('had shared', 'last earnings call') never moves to a later year.
7. UNOMINDA [Q2 FY25]: "TG Uno Minda has started commercial production from expansion project at its Neemrana plant ..." -> r3 Q2 FY25 (r6 Q1 FY27):
   a completed action ('has started') keeps the call period.
Keep-cases (r3-r6 must hold): HFCL, IOLCP, CUB, KTKBANK #36, EMSLIMITED #43, ASKAUTOLTD, MEDANTA, BLS, SOLARINDS, ARMANFIN, AZAD, PDSL, MMP.

## Steps
1. Find each evidence statement in the closed r3 copy (doc_key, page, call period) and print r6's anchored_period trace for it.
2. Rules: (a) 'for FYnn' / 'planned ... for FYnn' / 'in FYnn' bound to a figure anchors FYnn; (b) 'for the quarter' / 'this time' / 'in this
   quarter' / 'this quarter' bound to a figure beats a 'previous quarters' comparative and a trailing forward clause; (c) guidance 'for the year'
   -> the call's guidance year; (d) 'X stood at <figure>' with only a YoY comparative -> call period; (e) a past-tense recap or completed action
   never takes a later period than the call.
3. One test per evidence row (statement text as fixture) + keep-cases.
4. Measure as above; docs.

## Limits
Never write D:/RealityEngine or C:/RealityEngine (scratch only in the worktree .tmp; read DBs read-only or via the sqlite backup API); no model calls;
do not change the v3 prompt; pytest per file; never kill processes by name; structural rules only. Hard stop 05:30 IST 27 Nov (Shivam: all
operations stop by 08:00).
Stop if: a rule changes a graded-R row beyond period, or a keep-case, and cannot be narrowed in 2 tries.
Budget: ~100 tool calls.
