# T-228 stage 2c brief: repair the 91-store claims (duplicates, units, order inflow vs backlog, part-as-whole)

Ticket: T-228 (Shivam 20-21 Nov 2026). Reviewer: Wolf (Opus). Stage 2b code is on branch
dsh/20261121T002742Z-f52bc83e (commits 82a5c1a5, 9f961ba9; NOT merged). Base this worktree on that branch.

Goal: the 91-store run (`D:/RealityEngine/t228/claims_91_s2.db`, 10,102 claims, 2,450 verified) failed Wolf's
independent read: 50 verified claims (seed 149) = 14 right / 14 minor / 22 wrong. The factor study (T-229 stage C:
order inflow / revenue, capex / market cap) cannot use it until fixed. Most defects are fixable WITHOUT re-reading:
a model-free repair pass over the existing DB plus a narrow re-judge.

Evidence: (real; read first) `D:/RealityEngine/t228/wolf_read_91_s2.md` (per-claim grades). Classes:
1. Duplicates (14 wrong): same-call twins (COSMOFIRST 5916/5793 250 cr capex; JGCHEM 9504/9503), restatements in
   later calls/ARs (2299 vs 3397, 5848 vs 6634, BLKASHYAP order restated by AR, ASIANENE 82 cr order x3), and
   guidance-vs-transcript not merged because "current year" != "FY27" (9746 vs 15219). Current dedupe only folds
   pairs across different source kinds with identical period text. 46% of verified capex and 40% of order_book rows
   share a value with another verified row of the same company.
2. Units: order_book verified 402 rows: inr_cr 264, inr 97, usd_mn 29, usd 10, "months" 2.
3. Order inflow vs backlog mixed on revenue.order_book (VIVIANA 3361 1,700 cr unexecuted book vs 3362 9.74 cr new order).
4. Part stored as whole (3 wrong): GHCLTEXTIL 15093 7 cr knitting-machine capex as total FY27 capex; DBOL 15038 branded
   sugar margin as company EBITDA margin; 12554 one director's salary.
5. Wrong node: 9972 brakes market share as revenue.mix; 2511 tax saving as cost; 4984 ESOP vesting as equity.shares.
6. One-offs: 10052 range 45-50 stored 50 with base 45; 13053 old approval restated in a later AR.

Steps:
1. Period normaliser: "current year/this year/next year/current quarter/next quarter/H2" -> fiscal label from the
   claim's known_at (Indian FY Apr-Mar); store `period_norm`. Tests.
2. Event dedupe (all source kinds, including same kind and same document): group verified+unverified claims by
   (symbol, node, segment_norm, unit_norm, value_low/high within 1%, period_norm or both null) with known_at within
   180 days -> one event; keep the earliest known_at row as the event, others get dup_of = event id and status
   'duplicate' (new status; never served as a separate claim). A later row with a CHANGED value for the same
   (symbol, node, segment, period_norm) is a revision: keep it, set `revises` = earlier id.
3. Units to inr_cr: inr -> /1e7; inr_lakh -> /100; inr_mn -> /10; usd_mn/usd -> keep unit, add value_inr_cr only from
   an FX rate at known_at if a rate table exists in the stores (check index_price/any fx table; else leave null and
   count); "months" on order_book -> move to `execution_months`, value null. Tests.
4. Order subtype: new column `order_kind` (inflow / backlog / null) by script cues: backlog = "order book", "order
   backlog", "unexecuted", "pending orders", "outstanding orders", "order position"; inflow = "received", "bagged",
   "awarded", "secured", "LoA", "letter of award", "work order", "purchase order", "won". Both or neither -> null
   (unverified for factor use). Tests with the VIVIANA texts.
5. Part-as-whole: when the quote names an item/line/product/brand/plant/person ("knitting machine", "branded", a
   director's name, "for the X plant") and segment is 'total', set segment to that item (script cue list) and mark
   scope_part=1; such claims never count as company totals. Remuneration of a named person is no_driver.
6. Re-judge only the claims whose node/segment/period changed in steps 1-5 (beam-free judge as before, known_at in
   the prompt). No new extraction.
7. Write the repaired DB to `.tmp/t228/claims_91_s2c.db` (copy first; never touch D:). Re-run the same 50 ids from
   Wolf's read and list how each comes out. Report: status counts (incl. duplicate), verified by node and
   source_kind, capex/order_book verified rows by unit and order_kind, companies and months with >=1 verified
   inflow order or capex claim.

Files: `reality_engine/research/driver_claims.py`, `reality_engine/tests/test_driver_claims.py`,
`docs/research/T-228_driver_claims.md` (new section 13). No other file; do not edit tasks/STATE.md.

Accept: `python -m pytest -q reality_engine/tests/test_driver_claims.py` passes; typecheck clean; report + repaired DB.

Limits and pitfalls:
- Read-only on stores and D:/RealityEngine/*; writes only in your worktree. beam-free judge only; no paid model.
- Do not loosen verification to raise counts; a duplicate is never deleted, only marked.
- Run pytest per file.

Stop if: the repair would mark more than 60% of verified rows duplicate (report examples), or re-judge needs > 3,000
claims.

Budget: about 2 hours, DeepSeek max effort.
