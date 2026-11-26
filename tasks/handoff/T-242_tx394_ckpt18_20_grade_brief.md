# T-242 grade: 394 transcripts audit ckpt_0018-0020, live loop (agy Hydrogen, read-only, 26 Nov 2026; Wolf records - Eagle wrote the v3 prompt)

permission: read-only

Ticket: T-242

Goal: grade 60 statements of audit checkpoints 18, 19 and 20 of the live 394-transcript read (rows from the checkpoint plus a
seeded fill, from a snapshot of D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db). You wrote neither the prompt nor
the gates. An EMPTY period is right when the statement carries no own-period cue; a filled period must be the
statement's own period. Bar: >= 70% R and <= 5% W+J (measurement only since 26 Nov; nothing blocks on it).

Files:
- Rows: C:/RealityEngine/t242/tx394_ckpt18_20/pack.jsonl (ids = line numbers 1-60). Each row carries its page_text,
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
3. Final answer, part 1: a CSV block with columns id,grade,qc,reason, 60 lines.
4. Final answer, part 2: counts R/P/W/J, the step-2 lists, and the 3 commonest failure kinds with
   row ids.

Accept: the final answer holds 60 CSV lines with grades and the counts.
Bar: at least 70% R and at most 5% W+J.
Stop if: a page cannot be found (grade it J "page not found" and go on). Never write a file.
Budget: about 60 minutes.
