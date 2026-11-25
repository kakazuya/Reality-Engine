# T-242 re-grade: universe transcripts ckpt_0003 after the r3 fixes (Hydrogen, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: universe transcript checkpoint 3 failed 48/8/0/4. The 4 J were boilerplate: a hand-over line, closing logistics,
"good night", and a welcome with "results uploaded". The r3 fixes (greeting_only, question_end narrowing, label and
hand-over checks, by Eagle; question_context fill) were re-parsed into a copy of the store. Grade 60 statements from
that copy: 17 from the checkpoint and 43 random. The prompt and fixes are Eagle's; you did not write them, and Wolf
records the result.

Files:
- Rows: C:/RealityEngine/t242/regrade_fy27_r3/pack.jsonl (ids = line numbers 1-60). Each row carries its page_text,
  speaker, statement, question_context and status.
- Rubric: docs/grading/statement_rubric.md. Follow it exactly, including the question_context check (match / mismatch /
  empty).
- Neighbouring pages: C:/RealityEngine/tg_build/universe_fy27/<store>/<store>.db, table doc_page, read-only
  (`file:...?mode=ro`).
- You write and commit NO files. Your final answer carries the results.

Steps:
1. Grade each row R / P / W / J by the rubric:
   - the statement is printed on the page, said by the stored speaker (management, not the analyst or moderator);
   - figures are copied exactly;
   - it makes sense alone or through its question_context;
   - greetings, hand-overs, logistics and disclaimers are J.
2. Also check every row that ends with a tag question (", right?", ", isn't it?"), which r3 now keeps. Is it a
   management statement (R or P) or really a question (W)? List those ids.
3. Final answer, part 1: a CSV block with columns id,grade,qc,reason, 60 lines.
4. Final answer, part 2: counts R/P/W/J, the tag-question ids with verdicts, and the 3 commonest failure kinds with
   row ids.

Bar: at least 70% R and at most 5% W+J.
Stop if: a page cannot be found (grade it J "page not found" and go on). Never write a file.
Budget: about 60 minutes.
