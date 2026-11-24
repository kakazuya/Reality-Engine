# T-242: strict per-kind grade of 60 fund_raise events (DeepSeek, read-only, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: grade 60 `fund_raise` events from `reality_engine/research/filing_events.py` (round 4) strictly against the
filing's page text. Since round 3 only order wins are verified. Each other kind joins `VERIFIED_KINDS` only after its
own strict 60-row pass (bar: at least 70% right and at most 5% wrong + junk). This grade decides fund_raise.

Files:
- Rows: C:/RealityEngine/t242/events_grade_fundraise/pack.jsonl, one JSON object per line. Its fields are id,
  event_id, store, symbol, doc_key, page, kind, status, title, filing_date, event_date, seq, amount_inr_cr,
  amount_usd_mn, value_text, value_total, instrument, raise_stage, price_per_share, shares, customer and quote. The
  rows come from 45 stores no fix was tuned on (round-4 runs events_round4_fresh4.db and events_round4_fresh3.db).
- Page text: C:/RealityEngine/tg_build/full394/<store>/<store>.db (store is on the row), table
  doc_page(doc_key, page, text), and doc(doc_key, title, filing_date). Open it read-only (`file:...?mode=ro`). Read
  pages 1-4.
- You are read-only: write no files. Your FINAL ANSWER carries the results.

Evidence: the round-2 fresh grade had fund_raise 13/3/5/1. Its W were facility addenda, a limit surrender, a warrant
forfeiture and an investment in a subsidiary; round 3 vetoed those and fixed the raise stage.

Steps:
1. For each row, grade R / P / W / J strictly.
   - The kind is right only for an issuance of the company's OWN securities: an equity issue, QIP, preferential
     issue, rights issue, warrants (issue or conversion allotment), NCD or bond placement, commercial paper, or an
     ESOP-free allotment. These are never a fund_raise: a loan facility, sanction or renewal; a limit change; an
     investment in another company; a redemption, buy-back or call option; a rating; a utilisation or deviation
     statement.
   - The amount is the printed size of THIS step, in crore. Recompute shares x price yourself when both are printed.
     1 crore = 100 lakh = 10 million.
   - raise_stage: `proposed` = a board proposal or EGM/postal-ballot notice; `approval` = a board or shareholder
     approval, or an in-principle exchange approval; `allotment` = a completed allotment (shares allotted on a
     date); `listing` = listing or trading approval.
   - instrument matches the printed one (equity, warrants, NCD, CCD, QIP ...).
   - Grades: a non-issuance, a wrong amount or the wrong company = W. A wrong stage, a wrong instrument or a missing
     amount when one is printed = P. A row that repeats another pack row for the same company, the same step and
     the same amount = J.
2. Final answer, part 1: a CSV block with columns id,grade,reason (reason: one short line naming the printed words
   checked), 60 lines.
3. Final answer, part 2: counts R/P/W/J, and the 3 commonest failure kinds.

Accept: the final answer holds 60 CSV lines with grades in {R,P,W,J} and the counts.
Stop if: a row's page cannot be found (grade it J "page not found" and go on). Never write a file.
Budget: about 90 minutes; read-only.
