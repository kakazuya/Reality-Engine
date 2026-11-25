# T-242 surprise audit: 60 statements from the whole universe (fy27) transcript run, pre-load (Hydrogen, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: universe transcripts are fully read (6,701 pages) and the ckpt_0003 re-grade on the r3 copy passed 48/10/1/1.
Before loading, this audit grades 60 statements from the WHOLE live store, no checkpoint rows, to find defects the
checkpoints miss. Prompt author: Eagle (v3, fp
2fae7ddac53e); you did not write it, and Wolf records the result.

Files:
- Rows: C:/RealityEngine/t242/audit_txfy27/pack.jsonl (ids = line numbers 1-60). Each row carries its page_text, speaker,
  statement, question_context and status.
- The rubric: docs/grading/statement_rubric.md. Follow it exactly, including the question_context check (match /
  mismatch / empty).
- Neighbouring pages: C:/RealityEngine/tg_build/universe_fy27/<store>/<store>.db, table doc_page, read-only
  (`file:...?mode=ro`).
- You write and commit NO files. Your final answer carries the results.

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
