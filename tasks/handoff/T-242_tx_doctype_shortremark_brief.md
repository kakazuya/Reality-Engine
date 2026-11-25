# T-242: transcripts - non-call documents, moderator speakers, short content-free remarks (DeepSeek, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: a surprise audit of 60 random verified statements from the whole universe transcript run (Wolf, Sonnet graders,
C:/RealityEngine/t242/tx_fy27_surprise1/) scored 45/9/2/4, so W+J is 10%, over the 5% bar. Fix the three causes with
STRUCTURAL script rules in reality_engine/v2/obs_speaker.py (and, for step 1, the transcript page selection in
reality_engine/v2/observations.py). Do not change the v3 prompt; its fp must stay 2fae7ddac53e.

Files: reality_engine/v2/obs_speaker.py, reality_engine/v2/observations.py (the transcript doc/page selection only),
reality_engine/tests/test_obs_speaker.py, reality_engine/tests/test_v2_guards.py, docs/DEVELOPER_GUIDE.md.

Evidence: C:/RealityEngine/t242/tx_fy27_surprise1/summary.md, grades_part00.csv and grades_part01.csv, plus the pack
files there (part 0 rows 5, 16, 24, 25; part 1 rows 24, 26).
- Non-call documents typed as a transcript: AGM minutes (part0 n=16); a deck whose slide heading "Profit After Tax"
  became the speaker (part0 n=25).
- A company introduction stored under the speaker "Moderator" (part1 n=24).
- Short content-free remarks: "We have done well." (part0 n=5); a hand-over, "Kedar, I think his question was on
  products." (part0 n=24); a fragment, "So that's a meaningful swing." (part1 n=26), whose referent sits in the
  previous sentence.

Steps:
1. Doc check: a transcript document must show call turns, meaning at least 3 speaker-label lines ("Name:" or
   "Moderator:") across its pages. A document without them is not a call: its statements are unverified with reason
   `not_a_call`, and the page reader skips it in future runs. A speaker that is not a person's name (a slide or table
   heading like "Profit After Tax", or a line with digits or financial terms) is never a speaker.
2. Moderator: a statement whose speaker is the moderator or operator is never a management statement: unverified,
   reason `speaker_moderator`.
3. Short remarks: a passage of at most 8 words with no figure and no named entity or product is dropped when it is
   (a) generic praise or assessment ("We have done well", "That's a good point"), (b) a pointer to another speaker or
   question ("I think his question was on ..."), or (c) a sentence that only refers back ("So that's a meaningful
   swing", "That is the reason") while question_context is empty or does not supply the referent. Reuse the existing
   substantive-clause test.
4. Tests for each shape, plus counter-tests: a short answer with a figure ("Yes, 14% for the year.") stays; a short
   answer naming a product stays; a real call with labels on only some pages stays.
5. Measure on copies only (never write D:/RealityEngine/hy4_out): C:/RealityEngine/t242/reparse/fy27_v3_r3.db and
   C:/RealityEngine/t242/reparse/tx394_v3_r4.db. Report:
   - statements and docs each rule touches per DB;
   - 20 sampled per rule, quoted;
   - every graded R row in regrade_fy27_r3, regrade_tx394_r4, tx394_ckpt6, tx394_ckpt7, tx394_ckpt8, audit_tx394 and
     tx_fy27_surprise1 that changes (target 0);
   - the 6 evidence rows' new state.

Accept: tests pass; all 6 evidence W/J rows are dropped or unverified; 0 graded R rows change; at most 1.5% of
statements touched per DB; v3 fp unchanged.
Stop if: the doc check flags more than 3% of transcript documents (report 20 of them first), or a graded R row changes
after two attempts.
Budget: about 2 hours; write scope is your worktree only.
