# T-242 brief: transcript statements r5 - an explicit own-period cue wins over sentence-wide blocks (dsh DeepSeek, off-peak, 26 Nov, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: branch Wolf-agy-20261126T081833Z-f27697a8 (r4). Keep r4's new cues.

Goal: r4 (Hydrogen f27697a8) regained 591 own-period anchors (Eagle's sample 20/20 right) but dropped 1,585 others
(sample: 11 of 20 were RIGHT periods lost, 3 wrong removed, 6 neutral): its sentence-wide forward / comparative
blocks override an explicit own-period cue that is bound to the figure. Net period_anchored 9,579 (r3) -> 8,575.
r5 must keep r4's regains and stop those losses. Eagle's review: D:/RealityEngine/t242/grades/tx_r4_review_eagle.md
(read first).

Evidence (must anchor, r4 empties them):
- ASKAUTOLTD "EBITDA in Q1 FY25 at Rs. 103 crore against Rs. 65 crore in the same quarter last year" -> Q1 FY25 (the
  comparative names the BASE of 65, the 103 figure is bound to "in Q1 FY25").
- TVSSCS "... to Rs. 813.3 crores in Q4 FY26" -> Q4 FY26.
- MEDANTA "During the quarter ... same quarter last year" -> the call quarter.
- "guidance of 25-30% for FY'25" -> FY25 (guidance takes its named target period; a forward word does not empty it).
Must stay empty (r3/r4): HFCL future quarter; IOLCP "same quarter last year" figure; CUB "NIM for FY26" on a Q1 call
(another period's figure, not the call's); KTKBANK #36 Y-o-Y comparative figure; EMSLIMITED #43 "last quarter".

Code: reality_engine/v2/obs_speaker.py `anchored_period` and r4's block helpers (diff: `git diff e8a03846..HEAD --
reality_engine/v2/obs_speaker.py` in the r4 worktree).

## Steps
1. Read Eagle's review and r4's diff; reproduce the 4 losses and the 5 stay-empty cases as unit tests first.
2. Binding: an explicit period token (Qn FYnn, FYnn, H1/H2 FYnn, "in the quarter", "during the quarter", "this
   quarter", an as-on date = period end) that is attached to the statement's main figure (same clause, before the
   next figure or comparative connector) anchors that period, whatever other words the sentence holds.
3. Comparatives: "against / vs / compared to / over <base>" or "same quarter last year" names the BASE only: it blocks
   anchoring of the base figure, never of the figure bound to an explicit own-period token.
4. Guidance/forward: a forward sentence with a named target period (for FY'25, by FY27, in H2) anchors that named
   period (it is guidance, not the call's quarter); with no named period it stays empty.
5. Measure on a fresh reparse of a COPY of D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db into the worktree .tmp
   (command in tasks/t242_statement_r3_measure.md): period_anchored vs r3 (9,579) and r4 (8,575); 0 change to the
   graded-R rows of C:/RealityEngine/t242/tx394_grade_r2 beyond period; list 20 seeded (seed 7) regained and 20
   newly dropped vs r3 with the statement text.
6. Docs: r5 section in tasks/t242_statement_r3_measure.md; DEVELOPER_GUIDE.md bullet.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_statement_r3_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_obs_speaker.py ; test_observations.py - each separately, pass;
the 4 evidence cases anchor and the 5 stay empty; reparse period_anchored >= r3's 9,579 with the drop list judged.
Stop if: a rule anchors any stay-empty case and 2 tries do not fix it: report and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine (reparse copy in .tmp); no
model calls; never kill processes by name; empty beats wrong.
Budget: ~2 hours, ~150 tool calls.
