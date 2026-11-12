# T-199 answer run: answer the 64 BLUESTARCO questions from the store only

Ticket: T-199
Goal: answer every question in D:/RealityEngine/bluestar/answers/questions_in.json (64 questions about Blue Star Ltd, NSE
BLUESTARCO, BSE 500067) using ONLY the store D:/RealityEngine/bluestar/bluestar.db through the p3ask tool, exactly as a
model on the reality-data MCP would. One answer per question, with its sources, written to .tmp/answers/answers.jsonl in
your workspace (create the folder).

How to ask the store (shell, one call per lookup):
Set this in EVERY shell call, before python: `$env:REALITY_DATA_ALLOW_PAID_EMBED='1'` (PowerShell).
```
python -m reality_engine.scripts.p3ask --db D:/RealityEngine/bluestar/bluestar.db --qid <qid> --log .tmp/answers/calls.jsonl <tool> key=value ...
```
Tools (same as the MCP's pilot3_* tools; list arguments with a bad call and read the error):
- `fact symbol=BLUESTARCO metric=<revenue|pat|ebitda_margin|...> period=<Q1FY27|FY26> [basis=standalone] as_of=<date>`: ANY single
  number first. It now also serves figures read from results/deck/announcement table and chart pages (`source: page_atom`).
- `cells symbol=BLUESTARCO terms="<words>" [period=Q2FY26] as_of=<date>`: every printed figure of the table and chart pages
  (results statements, segment tables, balance sheets, ratio tables, deck charts and KPI tiles), one row per figure with its
  resolved period, basis, unit and value. `unverified` rows are served and must be labelled as such in the answer.
- `fin` reported/derived financial lines; `ratio` margins, ROE, PE, market cap; `kpi` company-stated KPIs (order book,
  segment revenue, capacity); `guidance` forward targets and revisions; `statements topic=... terms=...` what management
  said in calls; `holding symbol= as_of= [category=promoter|fpi_total|mf] [quarters=5]` shareholding, pledge, share count;
  `tech` price reaction, 52-week range; `docs` list documents; `search terms=...` any text; `page doc_key= page=` read a page;
  `topic symbol=BLUESTARCO topic="<theme>" as_of=<date> [limit=25]`: everything the store holds on one theme across every
  call and document, grouped by date. Use it FIRST for what the company said or did on a theme across calls, and for list
  questions; raise limit when it says items were cut.
  `semantic symbol=BLUESTARCO query="<a sentence>" as_of=<date> [limit=8]`: pages ranked by meaning (Nemotron 8B page
  vectors over every page); use it for theme and wording questions, then read the pages it returns with `page`.
  `calc expression=... inputs=...` arithmetic; `sql` only when no typed tool can answer (say why in the answer).
- Always pass `as_of=<the question's as_of>`; rows known after it must not be used, and never cite a document filed after it.

Steps:
1. For each question, in order: route by shape (single number -> fact first, then cells/fin/kpi; what management said ->
   topic / statements / semantic; targets -> guidance; lists -> topic with a high limit). Try at least two routes and a
   `search` or `semantic` before saying a figure is not held. Answer EVERY part the question asks (each figure, period,
   segment, reason); before writing, re-read the question and check each part is covered.
2. Compute what the filings do not state (margins, shares, growth) from stored inputs, and show the inputs and formula.
3. Write one JSON line per question to .tmp/answers/answers.jsonl:
   {"qid", "question", "as_of", "answer" (1-5 sentences with figures, units, periods, basis; if not found: "data not found" +
   what was searched + nearest supporting point labelled as such), "tools" (list), "sources" ([{"doc_key","doc_type","page",
   "known_at"}] of every figure used), "sql_reason" (empty unless sql was used), "confidence" (high|medium|low)}
   Append after each question (so a stop keeps the work).
4. Final answer: count answered / not found, tool calls total, and the 5 questions you found hardest.

Files: write only .tmp/answers/answers.jsonl and .tmp/answers/calls.jsonl (p3ask writes it). The store and the questions file
are read-only.
Accept: answers.jsonl has 64 lines, one per qid, valid JSON, every figure with a source.
Evidence: the store holds 263 documents (decks, results, transcripts, annual reports, announcements) filed 2024-04-01 to
2026-11-11, quarterly XBRL, KPI series, management statements, guidance, shareholding, prices, page vectors, and ~43,000
figures read from table and chart pages (page_atom).
Stop if: you would need to open anything under D:/RealityEngine/bluestar/questions/, D:/RealityEngine/bluestar/truth/,
D:/RealityEngine/bluestar/report/, any answers_* folder or any other database or file (never); you would need the web
(never); p3ask fails for every call (report); `semantic` returns an error on its first call (report the error, continue
without it).
Budget: 700 tool calls, 3 hours. Do not edit any code.
