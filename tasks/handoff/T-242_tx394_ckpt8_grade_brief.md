# T-242: strict grade of 394 transcripts audit checkpoint 8 (DeepSeek, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: the 394 v3 reader stopped at audit checkpoint 8 (ckpt_0008). Grade 60 statements (14 from the checkpoint,
the rest random from the run) so reading may resume. Earlier: ckpt 4-5 passed 42/18/0/0 and 42/17/0/1; today's
surprise audit 49/10/1/0. Prompt author: Eagle (v3, fp
2fae7ddac53e); you did not write it, and Wolf records the result.

Files:
- Rows: C:/RealityEngine/t242/tx394_ckpt8/pack.jsonl (ids = line numbers 1-60). Each row carries its page_text, speaker,
  statement, question_context and status.
- The rubric: docs/grading/statement_rubric.md. Follow it exactly, including the question_context check (match /
  mismatch / empty).
- Neighbouring pages: C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page, read-only
  (`file:...?mode=ro`).
- You write and commit NO files. Your final answer carries the results.

Evidence: ckpt_0006 re-grade on the r4 copy passed 48/11/0/1 (C:/RealityEngine/t242/regrade_tx394_r4); this is the first checkpoint read with the merged pleasantry/generic-speaker rules.
Accept: the final answer holds 60 CSV lines with grades and the counts.

Steps:
1. Grade each row R / P / W / J by the rubric:
   - the statement is printed on the page, said by the stored speaker (the right person, not the analyst);
   - figures are copied exactly;
   - the statement makes sense alone or through its question_context.
2. Final answer, part 1: a CSV block with columns id,grade,qc,reason (qc = match/mismatch/empty), 60 lines.
3. Final answer, part 2: counts R/P/W/J, and the 3 commonest failure kinds with row ids.

Bar: at least 70% R and at most 5% W+J.
Stop if: a page cannot be found (grade it J "page not found" and go on). Never write a file.
Budget: about 60 minutes.
