Ticket: T-179
Goal: Answer every question in D:/RealityEngine/t179/questions.json (60 questions, 25 companies; each row gives qid, symbol, db, as_of, question), one recorded answer per qid, in file order. This is run B1 of an answer test that measures correctness, tool calls and seconds per answer, so answer each question fully and exactly as asked, and do not batch: finish one question before starting the next.

Files: write ONLY through the recorder; it appends to .tmp/<SYMBOL>_answers.jsonl in your workspace. Scratch answer files go in .tmp/. Do not edit any code. Do not open any file under D:/RealityEngine except questions.json and the store named in each question's `db` (through p3ask only). Do NOT use the reality-data MCP tools or any other data tool: only p3ask calls are counted, and an answer built from an uncounted lookup is discarded.

How to look things up, always with the question's as_of, always with --qid and --log BEFORE the tool name (PowerShell, one call per command):
  $env:P3ASK_NO_SQL='1'; python -m reality_engine.scripts.p3ask --db <the question's db> --qid <qid> --log .tmp/calls.jsonl <tool> symbol=<SYM> ... as_of=<as_of>
  tools: kpi fin ratio holding statements guidance docs search tech page calc (tech: kind=reaction|gaps|rsi|ma|volume_spikes|range, for every price-move question). Examples:
  ... kpi symbol=SAIL kpi=sales_volume period=Q2FY27 as_of=2026-10-19
  ... fin symbol=UBL measure=revenue period=Q2FY27 as_of=2026-10-19   (consolidated default; basis=standalone for standalone)
  ... guidance symbol=POWERGRID as_of=2026-10-19 ; ... statements symbol=DLF topic=pre_sales as_of=2026-10-19
  ... search symbol=KIMS "query=occupancy ARPOB" as_of=2026-10-19
  ... page "doc_key=<doc_key from docs or search>" page=8 to_page=9 as_of=2026-10-19   (page text, at most 5 pages a call)
  ... calc "expression=a/b-1" 'inputs={"a": "5 crore", "b": "4 crore"}'
  Arguments: kpi(symbol,kpi,period,as_of,dimension,basis,limit) fin(symbol,measure,period,basis,definition,as_of,limit) ratio(symbol,ratio,period,as_of,basis) holding(symbol,as_of,quarter_end,all_categories,all_holders,category,quarters) statements(symbol,topic,terms,date_from,date_to,as_of,role,period,latest) guidance(symbol,metric,period,as_of,history) docs(symbol,doc_type,date_from,date_to,as_of) search(symbol,query,as_of,doc_type,period,date_from,date_to). A {"found": false} reply lists what is available: read it and retry. Routing: guidance -> guidance; company KPI -> kpi (an investor's words resolve: NIM / net interest margin -> nim_pct, credit cost / losses and provisions to assets -> credit_cost_bps, cost of funds / cost of borrowings -> cost_of_funds_pct; when one metric+period returns several values, quote the first row whose own quote prints the headline line and name the alternatives); financial line -> fin; ratios/valuation -> ratio; EVERY shareholding question -> holding, which returns each filed category with pct and pct_basis (promoter, public, mutual_funds, fpi_total, insurance, central_government_or_president_of_india ...; category=government/GoI|FPI|FII|MF|promoter|public|retail|DII and quarters=5 give a four-quarter path (baseline plus four quarters; an intra-quarter filing takes a slot) in one call; FPI sums use fpi_total, never its components added, one row per category and quarter, XBRL before the shp_index copy; a no-match filter lists categories_held); what management said -> statements; else search; read the page text (page tool) when a row's quote is thin. Rows with check_status 'unverified' may be used but say so; never use 'quarantined' -- but when a kpi reply carries held_quarantined for the period asked, report that figure as held but quarantined, never as 'not in data'. page(doc_key,page,to_page,as_of,max_chars).
  There is no raw SQL tool in this run: use the typed tools and the page tool. Every p3ask command starts with $env:P3ASK_NO_SQL='1'; as shown.

Steps, per question in file order:
 1. python -m reality_engine.pilot3.answer_record <SYM> start <qid>
 2. Look up every part the question asks (all periods, all segments, every comparison). Read results tables' QoQ/YoY columns before calling a period missing. Every derived number goes through calc, never mental arithmetic; keep the unit (crore vs lakh vs rupees) explicit.
 3. Write .tmp/<qid>.json: {"qid", "answer": "<plain English, full answer, figures with units and periods>", "numbers": [{"value","unit","period","source","quote","formula","inputs"}], "status": "answered|partial|not_found", "tools": [tool names used]}. status partial/not_found only after you searched and could not find a part; name the missing part in the answer.
 4. python -m reality_engine.pilot3.answer_record <SYM> answer .tmp/<qid>.json . If the number check refuses it, fix the figure (it is usually a unit or sum slip). Only if you are sure the check is wrong, retry once with "check_override": "<reason>".
 5. Append one line to .tmp/PROGRESS_NOTES.md every 10 questions (count done, count refused).

Pitfalls seen in the last run (fix these):
 - Before writing "not held" or partial for a figure, read the results and deck pages of that quarter (docs, then the page tool). Last run called bank NPA amounts, branch counts and 9M/FY insurer figures "not held" when the pages printed them.
 - A filing made after 15:30 IST reacts on the NEXT session: day 0 is the next trading day (doc known_at gives the time).
 - Never compare a trailing-twelve-month figure with the last fiscal year to show growth (they overlap); compare with the TTM a year earlier or the year-ago quarters.
 - RSI is Wilder's 14-day smoothing; a moving-average or volume multiple uses the PRIOR N sessions, not including the day itself. Say the method.
 - A ratio or return quoted as annualised must be called annualised. "Position in range" = (x-low)/(high-low).
 - fin rows give value_inr in rupees: divide by 1e7 for crore and check the scale against revenue before writing.
 - A "since <date>" chain must start with a change dated on or after that date; do not pick an earlier one.
 - Keep every ratio on one basis (standalone with standalone, consolidated with consolidated).
 - SELF-CHECK before recording: re-read every figure against the row it came from (value AND scale: a store row of 632 crore is never written 6,320); test the conclusion against your own figures (if receivable days rose faster than revenue, receivables outran revenue); a printed close or price comes from the price row, not memory.
 - A policy/event chain "since <date>" must name an event dated inside the window; if none is found, say so instead of using an earlier one.
 - Leverage and EV: when non-current investments are large, give fin net_debt and net_debt_all_investments and say which one the ratio uses.
 - Do not edit any file outside .tmp/ (no tasks/STATE.md, no docs).

Accept: every qid in the questions file has exactly one "answer" event across .tmp/*_answers.jsonl, and .tmp/calls.jsonl holds at least one line for every qid: python -c "import json,glob;q={x['qid'] for x in json.load(open(r'D:/RealityEngine/t179/questions.json',encoding='utf-8'))};a={json.loads(l)['qid'] for f in glob.glob('.tmp/*_answers.jsonl') for l in open(f,encoding='utf-8') if json.loads(l).get('event')=='answer'};c={json.loads(l)['qid'] for l in open('.tmp/calls.jsonl',encoding='utf-8')};print(len(q-a),'missing',len(q-c),'unlogged')"  prints 0 missing 0 unlogged.

Evidence: earlier runs on these stores took about 0.65 to 1.1 minutes per question (69 in 45 minutes, 37 in 41 minutes). Misses were mostly a misread row or page and sums or units. A part the store does not hold must be named as missing, never guessed or proxied.

Stop if: p3ask errors on 5 questions in a row (report the error text), or a database file is missing. Do not try to fix code.

Budget: about 4 minutes and 20 lookups per question; 60 questions; hard stop 4 hours. Final answer: counts answered/partial/not_found, refused-then-fixed count, overrides, and any p3ask error seen. Do not commit PROGRESS_NOTES.md.
