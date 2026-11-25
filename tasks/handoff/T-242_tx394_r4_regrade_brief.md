# T-242 re-grade: 394 transcripts ckpt_0006 after the pleasantry fix (DeepSeek, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: 394 transcript checkpoint 6 failed 48/8/1/3. The 3 J were a welcome line, "Very fine question, Ashok", and an
"I'll defer to" hand-over; generic 'Management' speakers were stored verified. The fixes (r3 greeting/question_end by
Eagle, and the pleasantry/defer/generic-speaker rules by Hydrogen e06f005b) were re-parsed into a copy. Grade 60
statements from that copy: 12 from the checkpoint and 48 random. You wrote neither the prompt nor the fixes.

Files:
- Rows: C:/RealityEngine/t242/regrade_tx394_r4/pack.jsonl (ids = line numbers 1-60). Each row carries its page_text,
  speaker, statement, question_context and status.
- Rubric: docs/grading/statement_rubric.md. Follow it exactly, including the question_context check (match / mismatch /
  empty).
- Neighbouring pages: C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page, read-only
  (`file:...?mode=ro`).
- You write and commit NO files. Your final answer carries the results.

Evidence: ckpt_0006 grades C:/RealityEngine/t242/tx394_ckpt6/grades.csv (48/8/1/3); the 3 J lines are absent from the r4 copy (Eagle checked).

Steps:
1. Grade each row R / P / W / J by the rubric:
   - the statement is printed on the page, said by the stored speaker (management, not the analyst or moderator);
   - figures are copied exactly;
   - it makes sense alone or through its question_context;
   - greetings, hand-overs, logistics and disclaimers are J.
2. Also list any row whose speaker is a bare title or 'Management', and any hand-over, thanks or praise line that is
   still stored.
3. Final answer, part 1: a CSV block with columns id,grade,qc,reason, 60 lines.
4. Final answer, part 2: counts R/P/W/J, the step-2 lists, and the 3 commonest failure kinds with
   row ids.

Accept: the final answer holds 60 CSV lines with grades and the counts.
Bar: at least 70% R and at most 5% W+J.
Stop if: a page cannot be found (grade it J "page not found" and go on). Never write a file.
Budget: about 60 minutes.
