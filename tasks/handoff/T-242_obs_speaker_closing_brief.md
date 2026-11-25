# T-242: obs_speaker - closing remarks and "get back to you" deferrals (DeepSeek, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: since the pleasantry fix (e06f005b), each transcript checkpoint grade still shows one J line: a closing thanks or a
deferral to after the call. Drop content-free closing and deferral lines with STRUCTURAL rules in
reality_engine/v2/obs_speaker.py (extend greeting_only); never drop a line carrying a figure or a substantive clause.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md (the
obs_speaker entries).

Evidence (ids are lines of each pack.jsonl):
- C:/RealityEngine/t242/regrade_tx394_r4/pack.jsonl #56 KTKBANK: "...Thank you very much. Thank you one and all."
  (closing remarks, J).
- C:/RealityEngine/t242/tx394_ckpt7/pack.jsonl #17: Varun Agarwal "...get back to you post this call" (pure deferral,
  J).
- C:/RealityEngine/t242/audit_txfy27/pack.jsonl #10: a closing thank-you plus a generic governance platitude (J), and
  #17: closing pleasantries wrapping a vague outlook (P).
- Not junk (keep): "Thank you for the question, Mr. Jehan." when it is followed by an answer in the same statement
  (regrade_tx394_r4 #19).

Steps:
1. greeting_only also drops a figure-free passage in which every sentence is one of:
   - a closing thanks ("thank you (all|one and all|everyone) (for joining|for your time|for your questions)?",
     "wish you (all) a good (evening|day)", "we look forward to (interacting|speaking) (again|next quarter)");
   - a deferral ("(we|I) will (get back|come back|revert) (to you)? (on that|offline|post this call|after the call)",
     "please (reach out|get in touch) (with|to) our (IR|investor relations)", "we can take (it|this) offline").
   Reuse the ligature normalisation and the substantive-clause test already in the module.
2. Tests: one per shape, plus counter-tests (a closing line that also states guidance or a figure stays; "we will get
   back to growth of 15%" stays).
3. Measure on copies only (never write D:/RealityEngine/hy4_out). Use C:/RealityEngine/t242/reparse/tx394_v3_r4.db and
   C:/RealityEngine/t242/reparse/fy27_v3_r3.db. Report:
   - lines each rule would drop per DB (in-process over all statements);
   - 20 sampled dropped lines quoted;
   - every row graded R in regrade_fy27_r3, regrade_tx394_r4, tx394_ckpt6, tx394_ckpt7, tx394_ckpt8, audit_tx394 and
     audit_txfy27 (grades.csv beside each pack where present, else the grades in tasks/efficiency/worker_reviews.jsonl)
     that would be dropped (target 0).
4. Docs: DEVELOPER_GUIDE entry beside the pleasantry entry. Commit in the worktree.

Accept: test_obs_speaker.py and test_v2_guards.py pass; the 3 J lines above are dropped; 0 graded R rows dropped;
transcript v3 fp unchanged (2fae7ddac53e).
Stop if: a rule drops a line with a figure, or more than 0.5% of statements in either DB.
Budget: about 75 minutes; write scope is your worktree only.
