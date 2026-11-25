# T-242: order_win audit fixes - L1 vetoes, subsidiary orders, press-release customer (DeepSeek, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: a surprise audit of 60 verified order_win events (round 5 DBs, rows in no earlier grade) scored 52 R / 0 P /
8 W / 0 J (agy b87f8d84). That is 13% wrong among VERIFIED rows, against a bar of 5%. Fix the three causes in
`reality_engine/research/filing_events.py` so that none of them stays verified. Do not change fund_raise logic.

Files: reality_engine/research/filing_events.py (order_win build, customer, entity_scope), tests in
reality_engine/tests/test_filing_events.py, docs docs/research/T-231_filing_events.md and docs/DEVELOPER_GUIDE.md.

Evidence: C:/RealityEngine/t242/audit_orderwin_r5/pack.jsonl (match on store + doc_key + kind, never on event_id,
which repeats across the two DBs). Grades: C:/RealityEngine/t242/audit_orderwin_r5/grades.csv. Pages:
C:/RealityEngine/tg_build/full394/<store>/<store>.db, doc_page (open read-only).
- W, L1 only, not an order (#7, #32, both EMSLIMITED c315): "Intimation of receipt of Lowest Bidder(L-1) status
  awarded by UP Jal Nigam (Urban)" and "Intimation of Lowest Bidder (L-1) in tender at UPCL ...". The script path
  marked them verified order_win.
- W, a subsidiary's order stored as the company's (#24, #37 MCLOUD c22; #42 EFCIL c69; #49 PACEDIGITK c312; #58
  AURIONPRO c33): "Provigil Surveillance Limited, a wholly owned subsidiary of the Company, has received a Letter
  of Acceptance", "EFC Limited, our wholly-owned unlisted subsidiary", "Material Subsidiary- Lineage Power Private
  Limited", "US-based subsidiary Aurionpro Fintech Inc.", and a title "purchase order received by subsidiary
  company". All have entity_scope='company'.
- W, garbled customer (#54 PACEDIGITK c312): customer = "BSNL to Power India's Telecom Future BANGALORE - January
  01" (a press-release headline) instead of "Bharat Sanchar Nigam Limited (BSNL)".

Steps:
1. L1 veto. When the subject, title or first 600 characters say lowest bidder / L-1 / L1 status / "emerged as L1"
   and no LoA, work order or contract award is ALSO stated as received, the row is not an order_win (drop it or
   set status 'unverified' with why 'l1_only'). Test on the two quoted subjects, plus a counter-test: "received
   LoA ... after being declared L1" stays an order.
2. Subsidiary orders (REVISED 25 Nov by Eagle after a measured stop, agy 70ccab33: unverifying would hit 59 of 325
   verified rows, 18.2%, and earlier grades counted these orders R). A subsidiary's order is a real order for the
   listed group: KEEP its status. When the order sentence's subject is a subsidiary ("<Name>, a (wholly
   owned|material|step-down) subsidiary of the Company, has received", "our (wholly-owned) subsidiary <Name>",
   "received by subsidiary", "<Name> (wholly owned subsidiary)", "US-based subsidiary <Name>"), set
   entity_scope='subsidiary' and store the subsidiary's printed name in `detail`, or in `customer_desc` if `detail`
   holds JSON (read how `detail` is used first, and report which you chose). The measured shapes: Provigil and
   Scandron (MCLOUD), EFC Limited (EFCIL), Lineage Power (PACEDIGITK), SAE Towers (KEC), Aurionpro Fintech Inc.,
   and one STLTECH row. Tests on 5 shapes. The stored name is the one PRINTED in the filing, never inferred.
   Where the filing says "a subsidiary" without naming it, keep entity_scope='company' (Wolf, 25 Nov).
   The measured stop found Steps 1 and 3 clean. The L1 veto touches 13/193 fresh3 rows (all EMSLIMITED) and keeps
   LoA-plus-L1 rows (audit #26, fresh3 #28). The headline-customer rule touches 1 row. Both break 0 graded R.
3. Customer from a press-release headline: a customer containing a headline verb or date ("to Power", "BANGALORE -",
   a month name with a day) is rejected. Fall back to the customer named in the body, or leave it empty. Test on
   #54's text.
4. Measure: re-run on fresh4 and fresh3 into NEW files in your worktree .tmp, exactly as round 5 did (copy
   C:/RealityEngine/t242/events_cache.db first; stores from C:/RealityEngine/t242/fresh4_stores.txt and
   fresh3_stores.txt; `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394`). Report:
   - (a) each of the 8 W rows' new state;
   - (b) every R row among the 52 audit rows and among the earlier graded order_win rows
     (C:/RealityEngine/t242/events_grade_fresh4 and events_grade_fresh3 packs) whose status or amount changed
     (target: none);
   - (c) verified order_win counts, before 132/193, and how many rows each new rule unverifies.
5. Docs: docs/research/T-231_filing_events.md (a round-6 section) and docs/DEVELOPER_GUIDE.md, beside round 5.

Pitfalls:
- The Bash heredoc mangles `\b` and `\n` in Python source: use the edit tool.
- Patterns only, no company names in code.
- Run pytest on test_filing_events.py only.

Accept: test_filing_events.py passes; all 8 W rows are no longer verified-and-wrong (the 5 subsidiary rows by their
label); 0 graded R rows change status or amount. Report how many graded rows got entity_scope='subsidiary'.
Stop if: a graded R row breaks and two attempts don't fix it, or one rule unverifies more than 15% of the verified
order_win rows. Report and stop.
Budget: about 2 hours; write scope is your worktree only.
