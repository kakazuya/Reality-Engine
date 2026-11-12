# T-195 retry (r1): the answer IS in the store, find it and say why you stopped before

Ticket: T-195
Goal: in the T-195 re-run you answered these Aurobindo questions, and an independent grader marked each one NOT fully
right (incomplete, wrong period, a document filed after the question date, or "not found"). For every one of them the
complete answer IS held in the store on or before the question's as_of. Find it. Shivam wants to know why answers stop
early, so for each question also explain honestly what made you stop last time.
Input: D:/RealityEngine/aurobindo/rerun_t195/deepseek_r1/retry_in.json (qid, question, as_of, your_previous_answer,
your_previous_tools).
Tools: same as before, one shell call per lookup (PowerShell; set `$env:REALITY_DATA_ALLOW_PAID_EMBED='1'` first):
`python -m reality_engine.scripts.p3ask --db D:/RealityEngine/aurobindo/aurobindo.db --qid <qid> --log .tmp/retry/calls.jsonl <tool> key=value ...`
Tools: fact fin ratio kpi cells guidance statements holding tech docs search page calc semantic topic sql. `topic` returns
everything on a theme across all calls/documents with a count of what was cut (raise limit or narrow dates when cut);
`docs` lists documents by type and date; `page` reads a page; always pass as_of; never use a document known after as_of.
Steps:
1. For each qid: re-read your previous answer, then search until the answer is COMPLETE: every item of a list, the
   exact period asked, the latest document before as_of, every call that discussed it (read the call pages with page).
   Do not stop at the first plausible figure. At least: topic, docs for the period, page reads of the relevant pages.
2. Write one JSON line per qid to .tmp/retry/answers.jsonl: {"qid","answer" (complete, with figures, periods, sources),
   "sources" ([{"doc_key","doc_type","page","known_at"}]), "calls_this_time" (int), "what_was_missing" (what your previous
   answer lacked), "why_stopped" (honest: what you searched last time, what reply made you think you were done, which
   tool or document finally had it), "found" (true/false)}.
Files: write only .tmp/retry/answers.jsonl and .tmp/retry/calls.jsonl. Read nothing under D:/RealityEngine/aurobindo/questions/,
report/, truth/, rerun_t195/grading/ or blind/, nor D:/RealityEngine/aurobindo_ab/.
Accept: answers.jsonl has one valid line per qid in retry_in.json, each with why_stopped and what_was_missing.
Evidence: grader verdicts in the T-195 run (not shown to you on purpose); the store holds each answer as of the date.
Stop if: p3ask fails on every call (report). Never invent a figure: if after a real search (topic + docs + page reads of
every call in the period) you still cannot find it, say found=false and list exactly what you read.
Budget: 300 tool calls, 1.5 hours. Do not edit code.
