# T-242: transcript statement fixes: speaker carry-over, speaker names, no-referent cuts, cover letters (DeepSeek, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: since Shivam's 24 Nov ruling, transcripts are gated on their verbatim STATEMENT rows. Two checkpoint grades
failed, strict and read-only:
- 394_v2 ckpt_0002: 6/6/0/0 of 12;
- fy27_v2 ckpt_0001: 13/7/0/1 of 21.

There were no wrong statements at all; every failure was a partial or junk row of one of four kinds:
- the speaker is missing, is the company name, or is a first name or initials only (10 rows);
- a short reply was cut with no referent (3 rows);
- a statement came from a page-1 filing cover letter (1 junk row).

Fix all four by script in the statement path of `reality_engine/v2/observations.py`, together with
`reality_engine/v2/obs_speaker.py`. Change no prompt text. The read_gate fingerprint must stay e95108f16e65; check:
`python -c "import reality_engine.v2.observations as o, reality_engine.v2.read_gate as g; o.TRANSCRIPT_PROMPT='v2'; print(g.fingerprint('transcript'))"`

Files:
- reality_engine/v2/observations.py: the statement path in build_observations ("stage M", `prose`) and reparse_db.
  reparse_db already builds a per-doc speaker context with obs_speaker.build_doc_context
  (`doc_speaker_ctx`, analyst_speakers and mgmt_speakers).
- reality_engine/v2/obs_speaker.py: build_doc_context, attribute_document, _name_matches_list, classify_speaker_role.
- reality_engine/tests/test_v2_guards.py, or a new test_statement_speaker.py.
- docs/DEVELOPER_GUIDE.md: one sentence per fix, added to the T-242 guards paragraph.
- Evidence (read-only):
  - checkpoint samples D:/RealityEngine/hy4_out/obs_transcripts_394_v2.db.audit/ckpt_0002.jsonl and
    D:/RealityEngine/hy4_out/obs_transcripts_fy27_v2.db.audit/ckpt_0001.jsonl;
  - the fix notes ckpt_0002.fix.md / ckpt_0001.fix.md beside them;
  - the reader DBs D:/RealityEngine/hy4_out/obs_transcripts_394_v2.db and obs_transcripts_fy27_v2.db. These are LIVE;
    open them read-only and copy them before any write.
  - Store page text: C:/RealityEngine/tg_build/full394/cNNN/cNNN.db for 394_v2, and
    C:/RealityEngine/tg_build/universe_fy27/cNNN/cNNN.db for fy27; table doc_page.

Evidence: 14 failing statement rows in the two checkpoint samples above (10 speaker missing/company name/initials, 3 no-referent cuts, 1 cover-letter J); dsh 635e3735 strict grade, counts in ckpt_0002.grade.json and fy27 ckpt_0001.grade.json; 0 wrong statements in 33.

Steps:
1. Read the checkpoint jsonl rows that are statements. Find the 14 failing rows by their pattern: empty speaker,
   a speaker equal to the company name, a speaker with one token or initials only, a statement under 60
   characters that opens with "Yes"/"No"/"That's right"/"Correct"/"It is" and names no subject, and a page-1
   cover letter. List each one with its page text.
2. Fix 1, speaker carry-over: a statement at the top of a page with no speaker label takes the last speaker of the
   previous page of the same doc. Use the stored page text of page-1 and build_doc_context. If the previous page
   ended with an analyst (question), the row is the analyst's, and it is not a management statement.
3. Fix 2, speaker resolution: a speaker equal to the company name, a first name only, or initials resolves to the
   full name in the doc's management list (mgmt_speakers from build_doc_context), but only when exactly one
   management name matches. Otherwise the row stays served, unverified, with the reason "speaker_unresolved".
4. Fix 3, no referent: a statement under 60 characters that only affirms or negates, with no noun subject of its
   own, is unverified with the reason "no_referent". Keep it, because question_context may still serve it.
5. Fix 4, cover letters: is_cover_letter() already returns [] for v2 pages. Find out why a page-1 cover-letter
   statement still got through (fy27 J row) and close that path.
6. Tests: each fix gets a case built from the real sentence, plus counter-cases (a labelled speaker is kept as
   it is; two management names sharing a first name gives speaker_unresolved; a long 'Yes, ...' answer with a
   subject is kept).
7. Measure on COPIES only:
   - copy both reader DBs to C:/RealityEngine/t242/fix_runs/ with sqlite backup;
   - run `python -m reality_engine.v2.observations --reparse --baseline <copy> --out <copy2> --stores-root <root>
     --doc-types transcript` (on main, --reparse with --stores-root now reads every store, not a sample);
   - report, per DB, statements verified before and after, and how many rows each fix changed, with 3 example
     rows per fix;
   - report what each of the 14 failing rows became.

Accept: `python -m pytest reality_engine/tests/test_v2_guards.py reality_engine/tests/test_transcript_prompt_v2.py
reality_engine/tests/test_observations.py reality_engine/tests/test_obs_speaker.py reality_engine/tests/test_no_control_chars.py -q`
passes; the fingerprint is unchanged; the measurement is in the final answer; the docs sentence is written.

Stop if:
- a fix needs prompt text;
- a fix would change more than 20% of verified statements in either DB: narrow it and report;
- the live reader DBs would be written.

Budget: about 2 hours; one worktree.

Pitfalls:
- Edit regexes as raw strings through Python or your editor, never through a bash heredoc (\b has been corrupted
  into \x08 before).
- The hy4 loop writes the live DBs, so read them only through `file:...?mode=ro` or a backup copy.
