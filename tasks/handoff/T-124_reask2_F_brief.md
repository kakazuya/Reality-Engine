Goal: Answer every question in D:/RealityEngine/pilot10/answer_reask2/questions_F.json (35 questions, 5 companies: ETERNAL, HDFCBANK, HINDALCO, HINDUNILVR, MARUTI) from the pilot10 store, one recorded answer per qid. This is the second re-ask of answers that were still partly right; the store has been rebuilt, so answer each question fully and exactly as an investor asked it.

Files: write ONLY through the recorder; it appends to .tmp/<SYMBOL>_answers.jsonl in your workspace. Scratch answer files go in .tmp/. Do not edit any code. Do NOT open anything under D:/RealityEngine/pilot10/answer_a3, answer_a2, answer_reask or D:/RealityEngine/reports (old answers and grades: this run is blind).

How to look things up (the same code the reality-data MCP runs), always with the question's as_of:
  python -m reality_engine.scripts.p3ask --db D:/RealityEngine/pilot10/pilot10.db <tool> symbol=<SYM> ... as_of=<as_of>
  tools: kpi fin ratio holding statements guidance docs search tech sql calc. Examples:
  ... kpi symbol=HINDUNILVR kpi=segment_ebit period=Q2FY27 as_of=2026-11-04
  ... fin symbol=INFY measure=revenue period=Q2FY27 as_of=2026-11-04   (consolidated default; basis=standalone for standalone)
  ... guidance symbol=MARUTI as_of=2026-11-04 ; ... statements symbol=KEC topic=order_inflow as_of=2026-11-04
  ... search symbol=ETERNAL "query=quick commerce dark stores" as_of=2026-11-04
  ... sql "query=SELECT page, substr(text,1,3000) FROM doc_page WHERE doc_key='<doc_key from docs>' AND page=8" max_chars=8000
  ... tech symbol=KEC kind=reaction start=2026-10-20 end=2026-11-04 as_of=2026-11-04   (also gaps, rsi, ma, volume_spikes, range)
  ... calc "expression=a/b-1" 'inputs={"a": "5 crore", "b": "4 crore"}'
  Arguments: kpi(symbol,kpi,period,as_of,dimension,basis,limit) fin(symbol,measure,period,basis,definition,as_of,limit) ratio(symbol,ratio,period,as_of,basis) holding(symbol,as_of,quarter_end,all_categories,all_holders) statements(symbol,topic,terms,date_from,date_to,as_of,role,period,latest) guidance(symbol,metric,period,as_of,history) docs(symbol,doc_type,date_from,date_to,as_of) search(symbol,query,as_of,doc_type,period,date_from,date_to) sql(query,limit,max_chars). A {"found": false} reply lists what is available: read it and retry. Routing: guidance -> guidance; company KPI -> kpi; financial line -> fin; ratios/valuation -> ratio; holdings -> holding; what management said -> statements; else search; read the page text (doc_page via sql) when a row's quote is thin. Rows with check_status 'unverified' may be used but say so; never use 'quarantined'.

Steps, per question in file order:
 1. python -m reality_engine.pilot3.answer_record <SYM> start <qid>
 2. Look up every part the question asks (all periods, all segments, every comparison). Read results tables' QoQ/YoY columns before calling a period missing. Every derived number goes through calc, never mental arithmetic; keep the unit (crore vs lakh vs rupees) explicit.
 3. Write .tmp/<qid>.json: {"qid", "answer": "<plain English, full answer, figures with units and periods>", "numbers": [{"value","unit","period","source","quote","formula","inputs"}], "status": "answered|partial|not_found", "tools": [tool names used]}. status partial/not_found only after you searched and could not find a part; name the missing part in the answer.
 4. python -m reality_engine.pilot3.answer_record <SYM> answer .tmp/<qid>.json . If the number check refuses it, fix the figure (it is usually a unit or sum slip). Only if you are sure the check is wrong, retry once with "check_override": "<reason>".
 5. Append one line to PROGRESS_NOTES.md every 10 questions (count done, count refused).

Method rules (check each answer against these before recording it):
 - "Not held"/partial only after reading the pages: docs for that quarter, then search with at least two phrasings, then sql on doc_page of the results, deck, call transcript and annual report. Page text holds many figures no KPI row carries (NPA amounts, branch counts, Stage 2, customer counts, product shares, ratings, guarantees, foreign-currency sensitivity tables, business-line mix).
 - Derive what the filings imply: a quarter = 9M - H1 or FY - 9M; growth from the YoY column. Every derived number goes through calc; quote calc's result, do not round by eye. Check sign and size (an item "flat" must be within 2%).
 - Units: fin value_inr is rupees; crore = value_inr / 1e7. Check every figure's scale against revenue of the same period.
 - Price moves: use tech (kind=reaction/gaps/rsi/ma/volume_spikes/range), never hand arithmetic on OHLC. A move is close vs PREVIOUS close. A filing after 15:30 IST reacts on the next session. A gap-up is filled on the first later session whose low reaches the prior close. RSI is Wilder 14; a price at a new high while RSI is lower than at the prior high is a bearish divergence. Averages use the prior N sessions, excluding the day.
 - Same-date pairs: a "year-ago" figure must be the one known a year before as_of (e.g. the quarter results out by then), never a later quarter. Like for like periods: a six-month balance change goes with six-month revenue growth; TTM is never compared with the last fiscal year.
 - One call = one event: a call and its transcript filed days later are the same call. A remark about the consolidated business is not a revision of a segment's guidance band. "Delivered vs guided" compares the guided period's actual with the target.
 - Copy labels exactly from the table header: reported vs constant currency, including vs excluding trainees (excluding trainees is the higher utilisation), India vs rest of world, standalone vs consolidated (never mix in one ratio). Cash generated from operations is after working-capital changes and before tax.
 - Name one-offs: exceptional or demerger gains inflate EPS and PAT growth; say so and show growth without them. Annualised returns (RoEV, RoE for a half) must be called annualised. A cumulative target is judged on the cumulative figure, not a running pro-rata.
 - "Which part drives growth": give each segment or subsidiary's share of profit (or of the increase) against its share of the base, and use the business-line mix the deck prints.
 - "Largest/most important announcements" = by the size of the news (results, orders, deals, ratings, M&A), not by the price move a filing coincided with.
 - Leverage: when non-current investments are large, give both fin net_debt and net_debt_all_investments and say which one the ratio uses. Valuation from RoE (Gordon): fair P/B = (RoE - g)/(Ke - g); state RoE, g and Ke. Incremental return = change in EBIT / change in capital employed.
 - Holdings and pledges: holding(all_categories=true) for each quarter-end; sql on shp_pledge and shp_category for the path; insider_trade and doc search for acquisitions (SAST).
 - Events "since <date>" start on or after that date.
 - A part the company never disclosed, or a document not held, is named as missing with what was searched; never guessed or proxied.
 - Do not edit any file outside .tmp/ (no tasks/STATE.md, no docs).

Accept: every qid in the questions file has exactly one "answer" event across .tmp/*_answers.jsonl: python -c "import json,glob;q={x['qid'] for x in json.load(open(r'D:/RealityEngine/pilot10/answer_reask2/questions_F.json',encoding='utf-8'))};a={json.loads(l)['qid'] for f in glob.glob('.tmp/*_answers.jsonl') for l in open(f,encoding='utf-8') if '\"answer\"' in l and json.loads(l).get('event')=='answer'};print(len(q-a),'missing',sorted(q-a)[:10])"  prints 0 missing.

Evidence: the 5 Nov run on the same questions scored these 136 as partly right; main causes were the model misreading a row or page (89), store gaps (19), sums or units (18), store defects (10). Store fixes since then (T-113 checker, T-105 latest guidance, T-107 ratio periods) are what this measures.

Stop if: p3ask errors on 5 questions in a row (report the error text), or the database file is missing. Do not try to fix code.

Budget: about 8 minutes and 30 lookups per question; 35 questions; hard stop 5 hours. Final answer: counts answered/partial/not_found, refused-then-fixed count, overrides, and any p3ask error seen.

Ticket: T-124
