# T-242: blind strict grade of 120 transcript rows (DeepSeek, read-only, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: grade 120 earnings-call rows strictly against the transcript page text. The rows were extracted from 5 calls
by two different reading methods. You are not told which method made which row, and you must not try to find out.
The grade decides which method Shivam keeps.

Files:
- Rows: C:/RealityEngine/t242/whole_grade/pack.jsonl, one JSON object per line with id, symbol, doc_key, page,
  record_type, measure, printed_label, value_text, value, value_high, unit, period, basis, segment, entity_scope,
  speaker, statement, question_context and status.
- Page text: the store DB that holds doc_key, one of C:/RealityEngine/tg_build/full394/cNNN/cNNN.db, table
  doc_page(doc_key, page, text). Open it read-only (`file:...?mode=ro`). Read the row's page AND the page before
  it, because a speaker's turn can start on the previous page.
- Call date: doc.known_at in the same store. The call reports the last quarter that ended before that month
  (Indian fiscal year April-March: Q1 = Apr-Jun).
- You are read-only: write no files. Your FINAL ANSWER carries the results (below).

Evidence: Shivam asked (24 Nov 17:15) to test reading a call in multi-page windows against reading it page by page.
A script count on the 27 pages read both ways shows statement speaker filled 100% vs 76%, and number period filled
84% vs 77%. Only a strict hand grade can say whether those filled values are RIGHT.

Steps:
1. For every row, grade R (right), P (partial), W (wrong) or J (junk). Be strict:
   - Number/guidance rows: the value_text is printed on that page. The measure is exactly the quantity printed. The
     unit and scale are right. The PERIOD is right for that sentence: resolve "this quarter", "current year",
     "last year" and "same quarter last year" from the call date, and check any growth % against the two values.
     A manager, not an analyst, said it, and it is the company's own figure (not an industry, government or other
     company's). One error in period or entity = W; a missing period or unit when one is printed = P.
   - Statement rows: the text is verbatim from the page. The speaker is the person who actually said it, a
     management name. Check the last "Name:" label before the text, including on the previous page. A wrong
     speaker, or an analyst stored as management = W; a missing speaker = P. A passage cut mid-sentence or with no
     referent = P. Greetings or boilerplate = J.
2. Final answer, part 1: a CSV block with columns id,grade,reason (reason: one short line naming the printed words checked), 120 lines.
3. Final answer, part 2: counts R/P/W/J overall, for statements and for numbers, and the 3 commonest failure kinds.

Accept: the final answer holds 120 CSV lines with grades in {R,P,W,J} and the counts.
Stop if: a row's doc_key or page cannot be found in any store (grade it J with reason "page not found" and go on);
never write any file.
Budget: about 90 minutes; read-only.
