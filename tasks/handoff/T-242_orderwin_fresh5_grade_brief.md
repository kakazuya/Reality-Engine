# T-242: fresh-store strict grade of 60 verified order_win events after round 6 (Hydrogen, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: grade verified `order_win` events from 40 stores NO fix was tuned on (fresh5, round 6). Earlier grades were on
tuned stores (round 4: 46/11/2/1; round-5 audit: 52/0/8/0 -> round 6). This decides whether order_win holds on unseen filings.

Files:
- Rows: C:/RealityEngine/t242/audit_orderwin_fresh5/pack.jsonl, one JSON per line. Fields: id, event_id, store, symbol,
  doc_key, page, kind, status, title, filing_date, event_date, amount_inr_cr, amount_usd_mn, value_text, customer,
  customer_desc, quote, entity_scope, detail. Round 6 rules: L1-only filings are never verified; a subsidiary's order
  is right when entity_scope='subsidiary' and detail names the printed subsidiary.
- Page text: C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page(doc_key, page, text). Open it
  read-only (`file:...?mode=ro`, uri=True). Read pages 1-3.
- You write NO files and make no commits. Your final answer carries the results.

Steps:
1. Grade each row strictly R / P / W / J against the filing text:
   - Kind: the filing announces an order, contract or LoA won by THIS company. Never an order: a bid in progress,
     L1 status only, an order placed BY the company, an MoU without value, a subsidiary's order stored as the
     parent's without saying so, or a repeat of an older order.
   - amount_inr_cr = this order's printed value in crore. 1 crore = 100 lakh = 10 million. USD only when printed
     in USD. If the value is printed with and without GST, either is right when value_text says which.
   - customer = the printed customer (an anonymised customer is right when the filing withholds the name).
   - Grade: a non-order, a wrong amount, a wrong company or a wrong customer = W; a missing amount when one is
     printed, or a wrong date = P; a duplicate of another pack row (same company, same order, same amount) = J.
2. Final answer, part 1: a CSV block with columns id,grade,reason (reason: one short line naming the printed words
   checked), 60 lines.
3. Final answer, part 2: counts R/P/W/J, and the 3 commonest failure kinds, each with its row ids.

Accept: 60 CSV lines with grades in {R,P,W,J}, plus the counts.
Stop if: a page cannot be found (grade it J "page not found" and go on).
Budget: about 60 minutes.
