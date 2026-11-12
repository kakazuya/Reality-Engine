# T-199 completeness pass: check and repair an earlier answer set, part by part, from the store only

Ticket: T-199
Goal: an earlier run answered the 64 BLUESTARCO questions; a strict grader counts an answer right only when EVERY part is
right and complete. Re-check each answer against the store and repair it where a part is missing, unsupported, wrong, or
said "not found" too early. Input answers: `<INPUT>` (one JSON per line: qid, question, as_of, answer, tools, sources,
sql_reason, confidence). Write the final set to .tmp/answers/answers.jsonl (same fields plus "changed": true/false and
"change_note") in your workspace.

How to ask the store (shell, one call per lookup), from the repo root:
Set this in EVERY shell call, before python: `$env:REALITY_DATA_ALLOW_PAID_EMBED='1'` (PowerShell).
```
python -m reality_engine.scripts.p3ask --db D:/RealityEngine/bluestar/bluestar.db --qid <qid> --log .tmp/answers/calls.jsonl <tool> key=value ...
```
Tools: fact, cells, fin, ratio, kpi, guidance, statements, topic, semantic, holding, tech, docs, search, page, calc, sql
(same as `tasks/handoff/T-199_ANSWER_BRIEF.md`; read that file for their arguments). Always pass `as_of=<question as_of>`.

For each question, in order:
1. Split the question into its parts: every figure, period, basis, segment, comparison, reason, list item, and any
   "how/why/what did management say" element. Write the parts down for yourself.
2. For each part, check the answer: is it there, is it supported by a source known on or before as_of, is the number
   right (redo arithmetic; prefer a figure the company itself prints over your own computation, search for it before
   computing, and say which definition you used when you compute)?
3. A part said "not found" / "not stated": search again with at least three routes (topic with limit=25, semantic, search
   with two different phrasings, cells, and read the top pages with `page`) before keeping "not found". Statement
   questions: read the actual transcript pages, not only the statement rows.
4. Look-ahead: remove any source known after as_of and any fact only those sources give; if the store has nothing on or
   before as_of, say so and label the nearest later point as later.
5. Rewrite the answer only when a check failed; keep correct parts verbatim. Name the definition and basis of every
   computed figure.
6. Append one JSON line per question (also unchanged ones, "changed": false).

Files: write only .tmp/answers/answers.jsonl and .tmp/answers/calls.jsonl. Everything else read-only.
Accept: 64 lines, one per qid, valid JSON, every figure with a source.
Evidence: earlier answer sets lost most points on missed parts and early "not found" while the store held the data.
Stop if: you would need to open anything under D:/RealityEngine/bluestar/ other than bluestar.db (through p3ask) and
`<INPUT>`; the web (never); p3ask fails for every call.
Budget: 600 tool calls, 2.5 hours. Do not edit any code.
