# T-242: strict read-gate grade of 60 v3 transcript statements (DeepSeek, read-only, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: grade 60 verified management STATEMENT rows strictly against the transcript page text. They come from a 15-call
pilot of the new transcript reader (prompt v3). The grade decides whether the reader may read in bulk
(bar: at least 70% right and at most 5% wrong + junk).

Files:
- Rows: C:/RealityEngine/t242/v3_grade/pack.jsonl, one JSON object per line with id, observation_id, symbol, doc_key,
  page, measure, speaker, statement (the stored text), question_context, direction and status.
- Page text: the store DB that holds doc_key, one of C:/RealityEngine/tg_build/full394/cNNN/cNNN.db, table
  doc_page(doc_key, page, text). Open it read-only (`file:...?mode=ro`). Read the row's page AND the page before
  it, because a speaker's turn can start on the previous page.
- Call date: doc.known_at in the same store. The call reports the last quarter that ended before that month
  (Indian fiscal year April-March: Q1 = Apr-Jun).
- You are read-only: write no files. Your FINAL ANSWER carries the results (below).

Evidence: the 15-call pilot (C:/RealityEngine/t242/pilot_v3.db, 60 pages) stored 269 statements, 156 of them verified,
all with a speaker. A 5-call blind test before this graded window statements 25/4/0/1 of 30.

Steps:
1. For every row, grade R (right), P (partial), W (wrong) or J (junk). Be strict:
   - Statement rows: the text is verbatim from the page. The speaker is the person who actually said it, a
     management name. Check the last "Name:" label before the text, including on the previous page. A wrong
     speaker, or an analyst stored as management = W; a missing speaker = P. A passage cut mid-sentence or with no
     referent = P. Greetings or boilerplate = J.
2. Final answer, part 1: a CSV block with columns id,grade,reason (reason: one short line naming the printed words checked), 60 lines.
3. Final answer, part 2: counts R/P/W/J, and the 3 commonest failure kinds.

Accept: the final answer holds 60 CSV lines with grades in {R,P,W,J} and the counts.
Stop if: a row's doc_key or page cannot be found in any store (grade it J with reason "page not found" and go on);
never write any file.
Budget: about 90 minutes; read-only.
