# T-242: order_win round 7 - structural customer, subsidiary and value rules (Hydrogen, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: `order_win` failed its strict grade on 40 untuned stores (fresh5, round 6: 39 R / 5 P / 14 W / 2 J), so
VERIFIED_KINDS is now empty (493d3db3). Earlier rounds fixed graded rows and then failed on fresh stores. Write
STRUCTURAL rules for the causes below; never key a rule on a company or customer name. Do not touch fund_raise logic:
DeepSeek 749d4e61 is changing it in another worktree. Do NOT change VERIFIED_KINDS.

Files: reality_engine/research/filing_events.py (`_clean_party`, `_ANNEXURE_AWARDER`, `_FROM_ENTITY`,
`_subsidiary_name`, `_SUB_*`, `_finish_scope`, the order value reader, `_fold_same_order`), tests in
reality_engine/tests/test_filing_events.py, docs docs/research/T-231_filing_events.md (round-7 order section) and
docs/DEVELOPER_GUIDE.md.

Evidence: C:/RealityEngine/t242/audit_orderwin_fresh5/pack.jsonl (store, doc_key, page per row) and grades.csv. Pages
in C:/RealityEngine/tg_build/full394/<store>/<store>.db, doc_page (open read-only). Run DB:
C:/RealityEngine/t242/fresh5/events_r6_fresh5.db.
- Customer, 11 rows:
  - one-word title fragments ('Public' #1, 'Office' #17) when page 2 prints the full awarder;
  - the company's own segment ('our T&D business' #9, #12);
  - a country ('Malaysia' #31);
  - headline plus dateline (#32);
  - a header word prefixed ('Redevelopment(s) MSEB Holding...' #47);
  - null while the annexure prints the awarder (#15, #19, #21, #43).
- Subsidiary, 5 rows: "wholly owned subsidiary KRN HVAC Products Private Limited" (#30, #55) and "subsidiaries Premier
  Energies International Private Ltd. and Premier Energies Photovoltaic Private Ltd." (#14, #49) were missed; #60
  stored 'subsidiary: MW DC' (a capacity, not a name).
- Value, 3 rows: #23 a JV's gross value where the company's printed share is "Rs. 16,47,42,900/- (70%)"; #28 a
  past delivered order's value instead of the new order's "US$ 106,673 (approximately Rs 89 Lakhs)"; #18 a quarterly
  roll-up ("aggregating to Rs 4,001 crores in the July-September quarter"), which is not one order.
- Duplicates, 2 rows: #13 and #20, a press release repeating an order filed days earlier.

Steps:
1. Customer: prefer the annexure's 'Name of the entity awarding' over the title. Reject a candidate that:
   - is a single generic word (Public, Office, Government, Department, Client);
   - starts with our/its/the Company's;
   - is a bare country or region;
   - carries a headline verb or dateline;
   - starts with a table header word.
   When rejected, fall back to the body or annexure, else leave it empty (an empty customer is P, a wrong one is W).
2. Subsidiary: extend `_subsidiary_name` to "(wholly owned|material|step-down) subsidiar(y|ies),? <Name...>( and
   <Name>)?" with a company suffix (Private Limited, Ltd, Limited, LLP, Inc, GmbH). Never store a capacity, number or
   unit as a name: no digits, and no MW/MWp/DC/AC tokens. Several names go in detail separated by '; '.
3. Value:
   - a JV or consortium filing that prints the company's share (percent or amount) stores the share and notes the
     gross value in detail;
   - a value introduced by delivered/executed/earlier/previous order is never the new order's value;
   - a quarterly or period roll-up ("orders worth X in Q2", "aggregating to X in the quarter") is vetoed as not one
     order (unverified, why 'rollup').
4. Duplicates: a press release within 10 days of an order with the same value (within 0.5%) or the same customer
   folds into it with an `amend` link (extend `_fold_same_order` to press-release titles).
5. Tests from the quoted shapes (patterns only).
6. Measure, all three sets, each into a NEW file in your worktree .tmp. Copy the cache first:
   C:/RealityEngine/t242/fresh5/events_cache.db for fresh5, and C:/RealityEngine/t242/events_cache.db for
   fresh4/fresh3. Use `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394`, with stores from
   C:/RealityEngine/t242/fresh5_stores.txt, fresh4_stores.txt and fresh3_stores.txt. Report:
   - (a) each of the 21 fresh5 W/P/J rows' new state;
   - (b) every graded R row on fresh5 (39), audit_orderwin_r5 and events_grade_fresh4/fresh3 whose
     customer/amount/scope/status changed, with the reason (target: none worse);
   - (c) rows each rule touches per set.

Pitfalls: patterns only. Run pytest on test_filing_events.py only. A merge conflict with fund_raise r7 is expected;
keep your change inside the order paths.

Accept: test_filing_events.py passes; at least 17 of the 21 fresh5 failures are fixed; no graded R row gets worse.
Stop if: a rule changes more than 15% of order_win rows on fresh4 or fresh3, or a graded R row gets worse after two
attempts.
Budget: about 2 hours; write scope is your worktree only.
