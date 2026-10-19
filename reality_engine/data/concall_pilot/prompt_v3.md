You are reading the transcript of an Indian listed company's earnings conference call (concall). Extract what an
equity investor needs to judge the business outlook. Return ONE JSON object only (no prose, no markdown fences) with
exactly these keys. Every "quote" must be copied verbatim from the transcript (a short span, at most 40 words). Copy
numbers exactly as printed (keep commas, decimals and units). Never invent: if something is not in the transcript,
use null or an empty list.

{
  "period_discussed": "quarter/year the call reviews, e.g. Q1 FY26",
  "participants": ["management names and roles"],
  "guidance": [ {"metric": "", "value": "", "unit": "", "period": "", "basis": "standalone|consolidated|segment|unknown",
                 "direction": "new|raised|maintained|lowered|withdrawn|unclear", "firmness": "firm|indicative|aspirational",
                 "quote": "", "question_gist": ""} ],
  "capex": [ {"amount": "", "unit": "", "period": "", "purpose": "", "funding": "", "quote": "",
              "question_gist": ""} ],
  "order_book": [ {"value": "", "unit": "", "as_of": "", "inflow_or_pipeline": "", "quote": ""} ],
  "capacity_and_projects": [ {"item": "", "status": "", "timeline": "", "quote": ""} ],
  "demand_commentary": [ {"segment_or_market": "", "signal": "positive|neutral|negative|mixed", "statement": "", "quote": ""} ],
  "margin_and_cost_commentary": [ {"item": "", "signal": "positive|neutral|negative|mixed", "statement": "", "quote": ""} ],
  "pricing_and_competition": [ {"statement": "", "signal": "positive|neutral|negative|mixed", "quote": ""} ],
  "balance_sheet_and_cash": [ {"item": "", "statement": "", "quote": ""} ],
  "risks_and_headwinds": [ {"risk": "", "severity": "low|medium|high", "quote": ""} ],
  "one_offs_and_surprises": [ {"item": "", "impact": "", "quote": ""} ],
  "analyst_pushback": [ {"topic": "", "question_gist": "", "answer_quality": "direct|partial|evasive", "quote": ""} ],
  "management_tone": {"overall": "confident|optimistic|neutral|cautious|defensive", "score": "integer -2..2",
                      "rationale": "one or two sentences"},
  "key_numbers": [ {"metric": "", "value": "", "unit": "", "period": "", "quote": "", "question_gist": ""} ],
  "investor_takeaway": "three sentences: what changed, what matters next, what to watch"
}

"question_gist" is optional (guidance/capex/key_numbers): fill it only under rule 3.

STRICT RULES (v3; v2 kept, review §6 merged):
1. Quotes: copy a contiguous span exactly, word for word, including "not", "no", "never". Never paraphrase. Quote
   MANAGEMENT's words; in analyst_pushback put the analyst's question only in question_gist and quote management's
   answer. For a numeric item in key_numbers, capex, order_book or guidance, every number in value/amount must also
   appear in quote; the only exception is rule 3, where the number must appear in question_gist (order_book:
   inflow_or_pipeline). A bare "Yes"/"No" quote cannot support a number.
2. Scope: before a capex or guidance item, name whose money/outlook it is - the listed company, a subsidiary, a
   JV/associate, or the parent/global entity. A JV/project total or a parent/global figure is not the company's
   capex/guidance: omit it, or put the company's own share in amount (capex) or value (guidance) and say "JV total,
   not company capex" / "global parent, not India" in purpose/metric; name the subsidiary/JV. Example: ELITe 50:50 JV
   total INR 1,600 cr, Ester's share INR 250-270 cr -> amount INR 250-270 cr, purpose "ELITe JV (50:50), Ester share;
   project total INR 1,600 cr, not company capex"; BASF global capex to 2028 is not BASF India guidance.
3. Analyst numbers: a number that appears only in an analyst's question does not go into key_numbers, order_book,
   guidance or capex unless management confirms it. If management confirms it, add "(confirmed analyst's figure)" to
   metric (capex: purpose; order_book: inflow_or_pipeline), put the analyst's number and question in question_gist
   (order_book: inflow_or_pipeline), set period/as_of to the commitment date, and quote management's confirmation. If
   management does not repeat the number, omit it.
   Example: analyst says "income tax paid was Rs 2.3 crore"; management explains advance tax but never repeats 2.3
   -> no key_numbers item.
4. direction: raised/maintained/lowered only if the call refers to an earlier guidance figure; "well on track",
   "maintain", "reiterate", "stick to", "on course" = maintained (unclear if no prior figure is identifiable), never
   new; new only for a figure/outlook first introduced in this call; if unsure, unclear.
5. basis: standalone/consolidated ONLY if that word is said for that figure; if metric already says
   standalone/consolidated, set basis to it; segment only if the figure is stated for a segment; otherwise unknown.
6. Attribute correctly: if management corrects an analyst or itself, use the corrected statement; a guidance item
   must be the company's own outlook - not an industry figure, not an analyst estimate, not a parent/global figure.
7. A capex item needs a money amount; capacity (tonnes, units) is not a capex amount. If no amount is stated, do not
   create a capex item - put the statement in capacity_and_projects or as qualitative guidance.
8. period/as_of: a reporting period or measurement date, not a start date or the call date. Cumulative capex:
   "since May 2023" or the fiscal year; orders: as_of = order-book date, delivery/completion in inflow_or_pipeline.
9. unit: a unit token from the transcript (%, bps, INR crore, INR million, USD million, tonnes, x, ...), never a
   noun phrase ("UK revenues") - that noun belongs in metric. A multiple: value 2 unit x (or value double unit x). If
   the transcript's unit is inconsistent (e.g. "dollar loan ... INR 10 million"), unit unclear and say why in
   statement/period; do not silently pick one.
10. If the call gives two different figures for the same thing, record both and mark "inconsistent in call" in
    metric, statement or inflow_or_pipeline; do not silently pick one.
11. Do not infer what is not said: no funding source, dividend status, reason, or period unless stated. If the
    transcript is garbled or ambiguous, write unclear rather than picking a meaning.
12. management_tone must match the results and outlook discussed (a guidance cut with falling revenue is not
    optimistic).
13. investor_takeaway: only facts stated in the call; no new themes.

Company: {company} ({symbol}); call disclosed on {date}.

TRANSCRIPT:
{text}
