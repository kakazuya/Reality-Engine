# T-242: obs_speaker - pleasantries, defer/hand-over lines and generic speakers (Hydrogen, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: 394 transcripts ckpt_0006 failed 48/8/1/3. Three J rows are content-free lines that `greeting_only` on main does
not catch, and three P rows have a generic or empty speaker stored as verified. Fix with STRUCTURAL rules (patterns
only, no company names) in reality_engine/v2/obs_speaker.py without dropping real answers.

Evidence (C:/RealityEngine/t242/tx394_ckpt6/pack.jsonl, ids = line numbers):
- #29 UFLEX "Thank you, Surajit and welcome to all the participants for the Q2 earnings call of UFlex." (welcome only)
- #32 SINGERIND "Very ﬁne quesƟon, Ashok." (praise of a question; note OCR ligatures ﬁ and Ɵ)
- #50 NH "On the second part, maybe I'll defer to Sandhya or Anesh on that, insurance sitting inside a listed company."
  (defer / hand-over)
- #9 LLOYDSME and #48 ASTRAMICRO speaker 'Management'; #53 KTKBANK speaker '' (empty). These are stored verified.
`greeting_only(...)` and `_greeting_sentence(...)` return False for #29, #32 and #50.

Steps:
1. Normalise OCR ligatures before matching (ﬁ->fi, ﬂ->fl, Ɵ->ti, and the like); never change the stored text.
2. Extend greeting_only (drop) to lines with NO figure where every sentence is one of:
   - thanks plus a welcome to participants or the call;
   - praise of a question ("very fine/good/great/pertinent question[, Name]");
   - defer or hand-over ("I'll defer to X", "let me hand over to X", "X will answer/take that", "I'll request X to")
     with no substantive clause after it.
   A line that ALSO carries a substantive clause or figure stays.
3. Speaker: a statement whose speaker is empty, 'Management', 'Company', 'Moderator' or a bare designation (CFO, ED
   (Finance)) is `unverified` with reason `speaker_generic`, unless the label resolver finds a full management name.
4. Tests from the quoted shapes (patterns only), plus counter-tests: "Thank you. Our revenue grew 12% to Rs 500 crore"
   stays; "I'll defer to Sandhya; but on margins, we expect 14% next year" stays.
5. Measure in your worktree on copies only (never write D:/RealityEngine/hy4_out). Use the r3 universe copy
   C:/RealityEngine/t242/reparse/fy27_v3_r3.db and the 394 snapshot C:/RealityEngine/t242/tx394_ckpt6/snap.db.
   Reparse a sample of 300 pages each with `python -m reality_engine.v2.observations --reparse --baseline <copy> --out
   .tmp/<new> --only <selector>`; see docs/FIX_LOOP.md for --only. Report:
   - rows each rule touches per set;
   - 20 sampled dropped lines per rule, quoted;
   - every row graded R in C:/RealityEngine/t242/regrade_fy27_r3/pack.jsonl, tx394_ckpt6/pack.jsonl and
     audit_tx394/pack.jsonl that the rules would drop or unverify (target 0; each pack has a grades.csv beside it, id,grade).
6. Docs: a DEVELOPER_GUIDE entry next to the other obs_speaker entries. Commit in the worktree.

Accept: tests pass (test_obs_speaker.py, test_v2_guards.py); all 3 J lines dropped; the 3 generic-speaker rows are
unverified; 0 R rows dropped; transcript v3 fp unchanged (2fae7ddac53e).
Stop if: a rule drops a line with a figure, or drops more than 1.5% of statements in either sample.
Budget: about 90 minutes; write scope is your worktree only.
