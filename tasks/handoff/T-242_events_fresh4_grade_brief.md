# T-242: strict milestone grade of 60 verified order wins after round 3 (DeepSeek, read-only, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: grade 60 VERIFIED filing events strictly against the filing's page text. They were extracted by
reality_engine/research/filing_events.py after three rounds of fixes, from 25 stores no round was tuned on. Only order_win is verified now (other kinds are
served unverified until each passes its own grade), so all 60 rows are order wins. The
grade checks whether the fixes hold on fresh data (bar: at least 70% right and at most 5% wrong + junk).

Files:
- Rows: C:/RealityEngine/t242/events_grade_fresh4/pack.jsonl, one JSON object per line. Its fields are id,
  event_id, store, symbol, doc_key, page, kind (order_win / order_amendment / capex_approval /
  capacity_commissioned / fund_raise), status, title, filing_date, event_date, seq, amount_inr_cr, amount_usd_mn,
  value_text, value_total, customer, execution_months, capacity_value, capacity_unit, plant, instrument,
  raise_stage and quote.
- Page text: C:/RealityEngine/tg_build/full394/<store>/<store>.db (store is given on the row), table
  doc_page(doc_key, page, text), and doc(doc_key, title, filing_date). Open it read-only (`file:...?mode=ro`). Read
  pages 1-4 of the filing.
- You are read-only: write no files. Your FINAL ANSWER carries the results.

Evidence: on the previous fresh set (20 other stores) order wins graded 25/5/0/0; the 5 P were printed customers left
empty. Round 3 added customer parsing for the annexure forms and turned an L-1 status or new letter of award into a
positive order win.

Steps:
1. For each row, grade R / P / W / J strictly:
   - kind is right for what the filing announces. A cancellation or reduction is order_amendment with a negative
     amount. A tax, GST or court order is never an event. A redemption, call option or covenant change is never a
     fund_raise. A results release or quarterly order roll-up is never a new order.
   - The amount is the printed amount of THIS event, in crore. Check lakh to crore (1 crore = 100 lakh) and million
     to crore yourself. A multi-item filing: this row's own item.
   - customer is the awarding entity's name, or empty when the filing names none.
   - Dates: the event_date is not later than the filing date. For capacity_commissioned the capacity, unit and plant
     are as printed, the commissioning is this filing's own news, and it is not a foundation stone.
   - fund_raise: an issuance (raise, issue, allot, QIP, preferential, rights or NCD placement), and raise_stage
     matches the step (proposed, approval or allotment).
   - Grades: a wrong kind, a wrong amount or a non-event = W. A wrong or missing customer when one is printed, a
     wrong stage, or a missing capacity unit = P. A duplicate of another row in the pack for the same filing step = J.
2. Final answer, part 1: a CSV block with columns id,grade,reason (reason: one short line naming the printed words
   checked), 60 lines.
3. Final answer, part 2: counts R/P/W/J overall and by kind, and the 3 commonest failure kinds.

Accept: the final answer holds 60 CSV lines with grades in {R,P,W,J} and the counts.
Stop if: a row's page cannot be found (grade it J with reason "page not found" and go on). Never write a file.
Budget: about 90 minutes; read-only.
