# T-242: fresh8 strict grade of model-first filing events, 60 rows per kind (agy Hydrogen high, read-only, 26 Nov 2026, Eagle)

Ticket: T-242
permission: read-only

Goal: grade order_win (pack A) or fund_raise (pack B) events from fresh8 (40 stores no round has seen), read by the
NEW model-first code (530433b3: hy4 reads each filing, a script keeps an amount only when its exact text is printed).
This decides whether each kind may enter VERIFIED_KINDS. Rows are stored `unverified`; grade them as if verified. You
did not write the prompt or the checks.

Files:
- Pack A (order_win): C:/RealityEngine/t242/audit_orderwin_fresh8/pack.jsonl. Pack B (fund_raise):
  C:/RealityEngine/t242/events_grade_fundraise_fresh8/pack.jsonl. 60 lines each; id = the line's `id` field.
- Page text: C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page(doc_key, page, text), read-only
  (`file:...?mode=ro`, uri=True). Read pages 1-4 of the row's doc_key.
- You write NO files and make no commits.

Evidence: script-only rounds failed on fresh7 (order_win 35/10/14/1, fund_raise 31/8/16/0).

Steps:
1. Grade each row strictly R / P / W / J against the filing text.
   order_win:
   - The filing must announce an order, contract or LoA won by THIS company, or by a named subsidiary with
     entity_scope 'subsidiary'. Never an order: a bid in progress, L1 status only, an order placed BY the company, an
     MoU without value, a tax/regulatory/court order, an appointment, or a repeat of an older order.
   - amount_inr_cr is the order's printed value in crore (1 crore = 100 lakh = 10 million). Recompute it from
     value_text. USD stays in amount_usd_mn. An annual value is never the total unless the tenure is printed.
   - customer is the printed customer.
   fund_raise:
   - The filing records a raise by THIS company: allotment, QIP, preferential issue, rights, NCD or CP issue, or a
     board or shareholder approval of one. Never a fund raise: a bonus issue, ESOP allotment, a divestment, an asset
     purchase, a withdrawn issue, or a subsidiary's own raise.
   - The stored amount is the issue or allotment amount for THIS step. A board limit or an offered size stored as the
     allotted amount is W. One tranche stored where the filing prints a total is W. A sum that double counts is W.
     instrument and price_per_share must match the print.
   Both kinds: wrong kind, wrong amount, wrong company or wrong customer = W. A missing amount when one is printed, or
   a wrong date, stage or instrument = P. A duplicate of another pack row = J.
2. Final answer, part 1: a CSV block id,grade,reason (reason names the printed words checked), 60 lines.
3. Final answer, part 2: counts R/P/W/J; the 3 commonest failure kinds with row ids.

Accept: 60 graded lines plus counts.
Stop if: a page cannot be found (grade it J "page not found" and go on).
Budget: about 60 minutes. Never print keys. Never kill processes by image name.
