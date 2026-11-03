Goal: answer the 100 pilot questions of ONE company (named at the top of this brief by the controller as SYM) using ONLY the reality-data MCP tools, to measure how good and how fast the pilot3 database + MCP are. You are the investor's analyst: give the answer, the numbers, and where each came from.
Questions: `D:\RealityEngine\pilot3\answer_run\<SYM>_questions.json` (qid, question, as_of). Answer in file order. A question with as_of answers as of that date (pass `as_of` to the tools).
Allowed tools for answering: the reality-data MCP tools `pilot3_kpi`, `pilot3_fin`, `pilot3_ratio`, `pilot3_holding`, `pilot3_statements`, `pilot3_docs`, `pilot3_search`, `pilot3_sql` (and the older reality-data tools only if a pilot3 tool cannot serve). NOT allowed: reading any .db, PDF, raw folder or sandbox directly (no sqlite3, no python over data, no grep over data). A number the filings do not state is computed from tool results (growth, ratio, share): show the inputs and the formula.
Per question, exactly this sequence:
1. `python D:\RealityEngine\pilot3\answer_run\record.py <SYM> start <qid>` (shell; this and step 3 are the only shell calls allowed).
2. Answer with the MCP tools. At most 8 tool calls per question; if not found by then, status `not_found` with what you tried.
3. Write the answer JSON to `.tmp\a.json` in your workspace: {"qid", "answer" (2-4 sentences, plain), "numbers": [{"value","unit","period","source": "document p<page> or table row_id", "quote": exact quote if from text}], "status": "answered" | "partial" | "not_found", "tools": [the MCP tools you called, in order]} and run `python D:\RealityEngine\pilot3\answer_run\record.py <SYM> answer .tmp\a.json`.
Do not change any repo file. Do not grade yourself. Do not skip questions; if the run must stop, stop between questions.
Files: none in the repo (record.py writes .tmp\<SYM>_answers.jsonl in your workspace; you write .tmp\a.json)
Accept: .tmp\<SYM>_answers.jsonl holds one `answer` event for each of the 100 qids.
Stop if: the reality-data MCP pilot3 tools are not available in your session (report the tool list you see) or record.py fails twice.
Budget: 900 tool calls, 3.5 hours.
Ticket: T-049
Report: count answered / partial / not_found, total minutes, the 5 slowest questions, every case where a tool returned an error, and which questions you think the database lacks data for.
