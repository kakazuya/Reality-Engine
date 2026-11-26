# T-242 re-grade: 394 transcripts ckpt_0014 after statements r3 (DeepSeek, read-only, 26 Nov 2026, Wolf runs, Eagle records)

permission: read-only

Ticket: T-242

Goal: 394 transcript checkpoint 14 re-parses failed (r1 30/26/1/3, r2 36/20/4/0; notes C:/RealityEngine/t242/tx394_grade_r1|r2/fix.md).
Statements r3 (merged e8a03846: sentence snap/widen, copied speaker labels stripped, period only on an explicit
own-period cue, else empty) was re-parsed into C:/RealityEngine/t242/tx394_reparse/tx394_r3.db. Grade 30 statements
from that copy (your part file). You wrote neither the prompt nor the fixes. An EMPTY period is right when the
statement carries no own-period cue; a period that is filled must be the statement's own period.

Files:
- Rows: C:/RealityEngine/t242/tx394_grade_r3/pack_part00.jsonl or pack_part01.jsonl, as your start line says (ids = line numbers 1-30). Each row carries its page_text,
  speaker, statement, question_context and status.
- Rubric: docs/grading/statement_rubric.md. Follow it exactly, including the question_context check (match / mismatch /
  empty).
- Neighbouring pages: C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page, read-only
  (`file:...?mode=ro`).
- You write and commit NO files. Your final answer carries the results.

Evidence: r2 grade notes C:/RealityEngine/t242/tx394_grade_r2/fix.md (periods taken from the call quarter for comparatives, fragments, copied labels).

Steps:
1. Grade each row R / P / W / J by the rubric:
   - the statement is printed on the page, said by the stored speaker (management, not the analyst or moderator);
   - figures are copied exactly;
   - it makes sense alone or through its question_context;
   - greetings, hand-overs, logistics and disclaimers are J.
2. Also list any row whose speaker is a bare title or 'Management', and any hand-over, thanks or praise line that is
   still stored.
3. Final answer, part 1: a CSV block with columns id,grade,qc,reason, 30 lines.
4. Final answer, part 2: counts R/P/W/J, the step-2 lists, and the 3 commonest failure kinds with
   row ids.

Accept: the final answer holds 30 CSV lines with grades and the counts.
Bar: at least 70% R and at most 5% W+J.
Stop if: a page cannot be found (grade it J "page not found" and go on). Never write a file.
Budget: about 60 minutes.
