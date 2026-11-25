# T-242: fresh-store strict grade of 60 order_win events after round 8 (DeepSeek, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: grade `order_win` events from 40 stores NO fix was tuned on (fresh7, round 8; 23 companies, at most 4 rows each).
fresh5 (round 6) graded 39/5/14/2 and fresh6 (round 6 code) 31/4/23/2; rounds 7-8 fixed those causes. fresh7 was built with the merged round-8 code (cb741c24). This decides whether
order_win may re-enter VERIFIED_KINDS. Every row is stored `unverified` (no kind is gated); grade it as if verified.

Files:
- Rows: C:/RealityEngine/t242/audit_orderwin_fresh7/pack.jsonl, one JSON per line. Fields: id, event_id, store, symbol,
  doc_key, page, kind, status, title, filing_date, event_date, amount_inr_cr, amount_usd_mn, value_text, customer,
  customer_desc, quote, entity_scope, detail. Round 6-8 rules: a tax/regulatory/court order, an approval, a board outcome or an appointment is not an order; an L1-only filing is not an order; a subsidiary's order is right when
  entity_scope='subsidiary' and detail names the printed subsidiary; a JV/consortium order stores the company's printed
  share (detail notes the gross value); an undisclosed customer is NULL with 'customer not disclosed' in detail.
- Page text: C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page(doc_key, page, text). Open it
  read-only (`file:...?mode=ro`, uri=True). Read pages 1-3.
- You write NO files and make no commits. Your final answer carries the results.

Evidence: the fresh5 grade of round 6 was 39/5/14/2 (C:/RealityEngine/t242/audit_orderwin_fresh5/grades.csv); rounds 7-8 were tuned on fresh5/fresh6 only. fresh7 is 40 stores no round has seen.

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
