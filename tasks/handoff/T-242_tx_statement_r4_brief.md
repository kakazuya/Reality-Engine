# T-242 brief: transcript statements r4 - win back own-period anchors r3 drops (agy Hydrogen high, 26 Nov, Wolf)

Ticket: T-242
permission: write (your worktree only)
Base: main at/after e8a03846 (tx r3 merged).

Goal: r3 (merged) emptied 17,742 call-period anchors to stop wrong default anchors; Eagle's non-author review
(D:/RealityEngine/t242/grades/tx_r3_review_eagle.md, read it first) PASSED it but found right periods lost where the
statement carries an OWN-period cue r3 does not read. r4 reads those cues; it must not bring back any wrong anchor.

Evidence (pack C:/RealityEngine/t242/tx394_grade_r2, rows graded R that r3 emptied):
- ASHOKA: "As on 31st December 2024 ..." on a Q3 FY25 call (31 Dec 2024 = the call's period end) -> Q3 FY25.
- HINDZINC: "lowest quarterly zinc cost ..." -> call quarter.
- POONAWALLA #18: "... basis March 2026 balance sheet" on a Q4 FY26 call -> Q4 FY26 / as-at date.
- UJJIVANSFB: "stood at Rs. 25,274 crores ... growth over December 23" -> the figure is the call's own period; the
  comparative only names the base.
- AEROFLEX #22: "quarterly revenue crossing INR200 crores" -> call quarter.
r3's correct drops that must STAY empty: HFCL future quarter; IOLCP "same quarter last year"; CUB "NIM for FY26" on a Q1
call; BPLPHARMA future milestones; BOROLTD H1 figure on a Q2 call; KTKBANK #36 Y-o-Y comparative figure; EMSLIMITED #43
"results of the last quarter" (W rows 36/43 stay empty, 47 stays FY25).
Also: 'Cost-to-income ratio:' (CUB) was stripped as a speaker label - strip a leading label only when it names a roster
speaker or carries a role word (CEO, CFO, MD, Chairman, Director, Head, Officer, Moderator), never a metric heading.

Code: reality_engine/v2/obs_speaker.py - printed_call_period (~1460), anchored_period (~1478), _COMPARATIVE_CUE_RE
(~1443), strip_leading_speaker_label (~2026), _is_heading_label (~288). Measure note: tasks/t242_statement_r3_measure.md.

## Steps
1. Read Eagle's review, the r3 measure note and anchored_period.
2. Own-period cues in anchored_period, each giving the call's own period only:
   a. "as on / as at / as of / basis <date>" where <date> equals the call's period end (any printed date form);
      a different date gives no anchor.
   b. "quarterly <metric/figure>" / "this quarter's" -> call quarter.
   c. "<figure> stood at / was / reached ... (growth|up|increase) over <date a year before the period end>" -> the
      figure is own period (the comparative names only the base). Only when the base date is exactly one year (or one
      quarter) before the call's period end.
   Never anchor when a forward cue (will, expect, target, guidance, by FY.., next quarter), "same quarter last year",
   "last quarter", an explicit other FY/H/Q, or a future date is present.
3. Label strip: keep r3's strip of roster speakers; skip it when the label is a metric heading (no roster name, no
   role word).
4. Tests in reality_engine/tests/test_obs_speaker.py: one per evidence line above (5 regain cases, 7 stay-empty cases,
   CUB heading kept). Keep every r3 test passing.
5. Docs: docs/DEVELOPER_GUIDE.md r3 bullet + a short r4 section in tasks/t242_statement_r3_measure.md.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_statement_r3_measure.md. Nothing else.

Accept (yours): python -m pytest -q reality_engine/tests/test_obs_speaker.py ; then test_observations.py - each
separately, all pass.
Accept (Wolf/Eagle after you; do not try): reparse of a fresh tx394 copy: of the 5 R rows those with a cue regain
their period, W 36/43/47 stay fixed, and 0 new wrong periods on a fresh 20-row non-author sample of regained anchors.

Stop if: a cue rule would anchor any of the 7 stay-empty cases and 2 tries do not fix it: report and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill
processes by name; regexes edited with the file editor; empty beats wrong.
Budget: ~60 minutes, ~120 tool calls.
