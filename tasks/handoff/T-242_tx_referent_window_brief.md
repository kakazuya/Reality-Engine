# T-242: transcripts - statements that open on an unresolved referent or mid-sentence (DeepSeek, 26 Nov 2026, Eagle)

Ticket: T-242

Goal: the 394 surprise audit 2 (dsh 76ad80de, non-author) passed 53/7/0/0. All 7 P rows are one defect: the stored
statement starts after the words that give it meaning. Fix it with a STRUCTURAL rule in reality_engine/v2/obs_speaker.py
that widens the statement window backwards on the same page, so the statement stays a verbatim page substring.
Do not change the v3 prompt; its fp must stay 2fae7ddac53e.

Files: reality_engine/v2/obs_speaker.py, reality_engine/tests/test_obs_speaker.py, docs/DEVELOPER_GUIDE.md (obs_speaker
entries).

Evidence: C:/RealityEngine/t242/audit_tx394_2/pack.jsonl (ids = line numbers; each row has page_text, speaker,
statement, question_context):
- unresolved referent with empty or unrelated question_context: #6 "this materializes", #20 "both of these",
  #26 "this increase", #27 "that range", #29 "The brand", #30 "those issues";
- mid-sentence start: #37 "across the portfolio and you will get ...".

Steps:
1. Sentence snap: when a statement does not start at a sentence start on its page (the text before it in the same
   speaker turn does not end in . ? ! or a speaker label), move its start back to that sentence's start.
2. Referent widen: when the first sentence opens on an anaphor (this, that, these, those, both, it, they, such, the
   same, the + a noun that is not named earlier in the statement) and question_context shares none of the anaphor's
   noun's content words, prepend the previous sentence of the SAME speaker turn (one sentence, at most 60 words).
   Never cross a speaker label, never into the analyst's question, never past the page start.
3. If neither 1 nor 2 can apply (turn starts on the previous page, or the previous sentence is also only an anaphor),
   leave the statement and set a detail note `referent_outside_window`; do not change status.
4. Tests: one per evidence shape (quote the page text from the pack), plus counter-tests: a statement already at a
   sentence start with a named subject stays unchanged; an anaphor resolved by question_context stays unchanged; a
   widen never crosses a speaker label.
5. Measure on copies only (never write D:/RealityEngine/hy4_out): C:/RealityEngine/t242/reparse/tx394_v3_r4.db and
   C:/RealityEngine/t242/reparse/fy27_v3_r3.db (in-process over all statements). Report per DB: statements snapped,
   widened, noted; 20 quoted before/after samples per rule; the 7 evidence rows' new statements; every graded R row in
   regrade_fy27_r3, regrade_tx394_r4, tx394_ckpt6..8, audit_tx394, audit_tx394_2 and tx_fy27_surprise1 whose
   statement text changes (expected: some widen; each must still be a verbatim page substring and by the same speaker).

6. Duplicates (measured 26 Nov by Eagle): D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db (read-only) holds 220,812
   observation rows, of which 29,966 are repeats of the same (doc_key, page, measure, value_text). page_read has no
   repeated (doc_key, page), so the repeats come from overlapping 5-page windows (or from two loops that briefly
   wrote at once on 25-26 Nov). In the `--recheck` path, keep one row per (doc_key, page, measure, normalised
   value_text, speaker): keep the verified one first, then the lowest observation_id. Report the count dropped per
   DB on the copies, and confirm the reloaded statements in a store hold no exact repeats. Test it.

Accept: tests pass (per file); all 7 evidence rows widened or snapped to a self-contained statement; every changed
statement is a verbatim substring of its page by the stored speaker; at most 15% of statements change per DB; v3 fp
unchanged.
Stop if: more than 15% of statements change in either DB, or any widened statement crosses a speaker label.
Budget: about 90 minutes; write scope is your worktree only.
