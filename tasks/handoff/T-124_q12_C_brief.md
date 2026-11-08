Goal: Answer every question in D:/RealityEngine/q12/answers/questions_C.json (78 questions, 6 companies; investor questions harvested from the web) from the q12 hold-out store, one recorded answer per qid. These companies were never used to build the extractors; the run measures how well the store answers real investor questions, so answer each question fully and exactly as an investor asked it.

Files: write ONLY through the recorder; it appends to .tmp/<SYMBOL>_answers.jsonl in your workspace. Scratch answer files go in .tmp/. Do not edit any code. Do not open any file under D:/RealityEngine/q12 except questions_C.json and q12.db (through p3ask).

How to look things up (the same code the reality-data MCP runs), always with the question's as_of:
  python -m reality_engine.scripts.p3ask --db D:/RealityEngine/q12/q12.db <tool> symbol=<SYM> ... as_of=<as_of>
  tools: kpi fin ratio holding statements guidance docs search sql calc. Examples:
  ... kpi symbol=SAIL kpi=sales_volume period=Q2FY27 as_of=2026-10-19
  ... fin symbol=UBL measure=revenue period=Q2FY27 as_of=2026-10-19   (consolidated default; basis=standalone for standalone)
  ... guidance symbol=POWERGRID as_of=2026-10-19 ; ... statements symbol=DLF topic=pre_sales as_of=2026-10-19
  ... search symbol=KIMS "query=occupancy ARPOB" as_of=2026-10-19
  ... sql "query=SELECT page, substr(text,1,3000) FROM doc_page WHERE doc_key='<doc_key from docs>' AND page=8" max_chars=8000
  ... calc "expression=a/b-1" 'inputs={"a": "5 crore", "b": "4 crore"}'
  Arguments: kpi(symbol,kpi,period,as_of,dimension,basis,limit) fin(symbol,measure,period,basis,definition,as_of,limit) ratio(symbol,ratio,period,as_of,basis) holding(symbol,as_of,quarter_end,all_categories,all_holders) statements(symbol,topic,terms,date_from,date_to,as_of,role,period,latest) guidance(symbol,metric,period,as_of,history) docs(symbol,doc_type,date_from,date_to,as_of) search(symbol,query,as_of,doc_type,period,date_from,date_to) sql(query,limit,max_chars). A {"found": false} reply lists what is available: read it and retry. Routing: guidance -> guidance; company KPI -> kpi; financial line -> fin; ratios/valuation -> ratio; holdings -> holding; what management said -> statements; else search; read the page text (doc_page via sql) when a row's quote is thin. Rows with check_status 'unverified' may be used but say so; never use 'quarantined'.

Steps, per question in file order:
 1. python -m reality_engine.pilot3.answer_record <SYM> start <qid>
 2. Look up every part the question asks (all periods, all segments, every comparison). Read results tables' QoQ/YoY columns before calling a period missing. Every derived number goes through calc, never mental arithmetic; keep the unit (crore vs lakh vs rupees) explicit.
 3. Write .tmp/<qid>.json: {"qid", "answer": "<plain English, full answer, figures with units and periods>", "numbers": [{"value","unit","period","source","quote","formula","inputs"}], "status": "answered|partial|not_found", "tools": [tool names used]}. status partial/not_found only after you searched and could not find a part; name the missing part in the answer.
 4. python -m reality_engine.pilot3.answer_record <SYM> answer .tmp/<qid>.json . If the number check refuses it, fix the figure (it is usually a unit or sum slip). Only if you are sure the check is wrong, retry once with "check_override": "<reason>".
 5. Append one line to PROGRESS_NOTES.md every 10 questions (count done, count refused).

Pitfalls seen in the last run (fix these):
 - Before writing "not held" or partial for a figure, read the results and deck pages of that quarter (docs, then sql on doc_page). Last run called bank NPA amounts, branch counts and 9M/FY insurer figures "not held" when the pages printed them.
 - A filing made after 15:30 IST reacts on the NEXT session: day 0 is the next trading day (doc known_at gives the time).
 - Never compare a trailing-twelve-month figure with the last fiscal year to show growth (they overlap); compare with the TTM a year earlier or the year-ago quarters.
 - RSI is Wilder's 14-day smoothing; a moving-average or volume multiple uses the PRIOR N sessions, not including the day itself. Say the method.
 - A ratio or return quoted as annualised must be called annualised. "Position in range" = (x-low)/(high-low).
 - fin rows give value_inr in rupees: divide by 1e7 for crore and check the scale against revenue before writing.
 - A "since <date>" chain must start with a change dated on or after that date; do not pick an earlier one.
 - Keep every ratio on one basis (standalone with standalone, consolidated with consolidated).
 - Do not edit any file outside .tmp/ (no tasks/STATE.md, no docs).

Accept: every qid in the questions file has exactly one "answer" event across .tmp/*_answers.jsonl: python -c "import json,glob;q={x['qid'] for x in json.load(open(r'D:/RealityEngine/q12/answers/questions_C.json',encoding='utf-8'))};a={json.loads(l)['qid'] for f in glob.glob('.tmp/*_answers.jsonl') for l in open(f,encoding='utf-8') if '\"answer\"' in l and json.loads(l).get('event')=='answer'};print(len(q-a),'missing',sorted(q-a)[:10])"  prints 0 missing.

Evidence: on the pilot10 companies the same tools gave 464 right / 136 partly of 600 (5 Nov); misses were mostly a misread row or page (89) and sums or units (18). The q12 store holds FY25-27 documents for 12 hold-out companies; a part it does not hold must be named as missing, never guessed or proxied.

Stop if: p3ask errors on 5 questions in a row (report the error text), or the database file is missing. Do not try to fix code.

Budget: about 6 minutes and 25 lookups per question; 78 questions; hard stop 3.5 hours. Final answer: counts answered/partial/not_found, refused-then-fixed count, overrides, and any p3ask error seen.

Ticket: T-124
