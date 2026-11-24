# T-242: strict grade of fy27_v3 audit checkpoint 2 (60 verified statements) (DeepSeek, read-only, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: grade 60 verified management STATEMENT rows strictly against the transcript page text. They are the verified
statements of hy4's second 2,000-page audit checkpoint of the live fy27 v3 run, topped up with verified statements
from later pages, one per company. The grade decides whether the run may continue (bar: at least 70% right and at
most 5% wrong + junk).

Files:
- Rows: C:/RealityEngine/t242/v3_fy27_ckpt2/pack.jsonl, one JSON object per line with id, observation_id, symbol, doc_key,
  page, measure, speaker, statement (the stored text), question_context, direction and status.
- Page text: the store DB that holds doc_key, one of C:/RealityEngine/tg_build/universe_fy27/cNNN/cNNN.db, table
  doc_page(doc_key, page, text). Open it read-only (`file:...?mode=ro`). Read the row's page AND the page before
  it, because a speaker's turn can start on the previous page.
- Call date: doc.known_at in the same store. The call reports the last quarter that ended before that month
  (Indian fiscal year April-March: Q1 = Apr-Jun).
- You are read-only: write no files. Your FINAL ANSWER carries the results (below).

Evidence: checkpoint 1 of this run graded 46/13/1/0 (W: an analyst's name on a chairman's answer, AMTECH); the 394
run's checkpoint 1 graded 50/9/0/1 (J: a filing-letter line). Fixes since: speaker carried and resolved across pages,
rostered-analyst speaker unverified, '?'-ending passages unverified, duplicates and filing-letter lines dropped.

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
