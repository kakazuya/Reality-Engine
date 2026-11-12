# T-191 semantic A/B, arm B: answer the 69 AUROPHARMA questions from the store only

Ticket: T-191
Goal: answer every question in D:/RealityEngine/aurobindo/answers/questions_in.json (69 questions about Aurobindo Pharma,
NSE AUROPHARMA) using ONLY the store D:/RealityEngine/aurobindo_ab/aurobindo.db through the p3ask tool, exactly as a model
on the reality-data MCP would. One answer per question, with its sources, written to
.tmp/answers/answers.jsonl in your workspace (create the folder).

How to ask the store (shell, one call per lookup):
Set this in EVERY shell call, before python: `$env:REALITY_DATA_ALLOW_PAID_EMBED='1'` (PowerShell).
```
python -m reality_engine.scripts.p3ask --db D:/RealityEngine/aurobindo_ab/aurobindo.db --qid <qid> --log .tmp/answers/calls.jsonl <tool> key=value ...
```
Tools (same as the MCP's pilot3_* tools; list arguments with a bad call and read the error):
- `fact symbol=AUROPHARMA metric=<revenue|pat|ebitda_margin|...> period=<Q1FY27|FY26> [basis=standalone] as_of=<date>`: ANY single number first.
- `fin` reported/derived financial lines (revenue, PAT, capex, borrowings, EPS, cash flow lines); `ratio` margins, ROE, PE, market cap;
  `kpi` company-stated KPIs (US formulations, Europe, ANDA filings, R&D); `cells symbol=AUROPHARMA terms="<words>" [period=]`:
  figures read from deck/results table and chart pages (status `unverified` = say so in the answer);
  `guidance` forward targets and revisions; `statements topic=... terms=...` what management said in calls;
  `holding symbol= as_of= [category=promoter|fpi_total|mf] [quarters=5]` shareholding, pledge, share count;
  `tech` price reaction, 52-week range; `docs` list documents; `search terms=...` any text; `page doc_key= page=` read a page;
  `semantic symbol=AUROPHARMA query="<a sentence>" as_of=<date> [limit=8]`: pages ranked by meaning (Nemotron 8B page
  vectors), for what-management-said, topic and paraphrase questions; read the pages it returns with `page`;
  `calc expression=... inputs=...` arithmetic; `sql` only when no typed tool can answer (say why in the answer).
- Always pass `as_of=<the question's as_of>`; rows known after it must not be used.

Steps:
1. For each question, in order: route by shape (single number -> fact first; then fin/kpi/cells; statements for what
   management said; guidance for targets). Try at least two routes and a `search` before saying a figure is not held.
2. Compute what the filings do not state (margins, shares, growth) from stored inputs, and show the inputs and formula.
3. Write one JSON line per question to .tmp/answers/answers.jsonl:
   {"qid", "question", "as_of", "answer" (the answer in 1-4 sentences with figures, units, periods, basis;
   if not found: "data not found" + what was searched + nearest supporting point labelled as such),
   "tools" (list of tool names used), "sources" ([{"doc_key","doc_type","page","known_at"}] of every figure used),
   "sql_reason" (empty unless sql was used), "confidence" (high|medium|low)}
   Append after each question (so a stop keeps the work).
4. Final answer: count answered / not found, tool calls total, and the 5 questions you found hardest.

Files: write only .tmp/answers/answers.jsonl and .tmp/answers/calls.jsonl (p3ask writes it). The store and the questions file are read-only.
Accept: answers.jsonl has 69 lines, one per qid, valid JSON, every figure with a source.
Evidence: the store holds 367 documents (decks, results, transcripts, annual reports, announcements) known up to
2026-11-09, quarterly XBRL, KPI series, statements, guidance, shareholding, prices, and page cells read from deck and results page images (Dots and Haiku).
Stop if: you would need to open anything under D:/RealityEngine/aurobindo/questions/, D:/RealityEngine/aurobindo/truth/,
D:/RealityEngine/aurobindo/report/, any answers_* folder
or any other database or file (never); you would need the web (never); p3ask fails for every call (report); `semantic` returns an error on its first call (report the error, stop).
Budget: 700 tool calls, 3 hours. Do not edit any code.
