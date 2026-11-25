# T-242: order_win round 8 - "is this an order the company won?" (structural kind vetoes) (25 Nov 2026, Eagle)

Ticket: T-242

Goal: order_win failed its gate grade on 40 never-seen stores (fresh6) 31/4/23/2. That set was built with round-6 code;
re-built with round 7 (C:/RealityEngine/t242/fresh6/events_r7d_fresh6.db), 22 of its 25 failures still stand. The main
cause is that the kind test accepts any filing that says "order". Add STRUCTURAL kind vetoes plus the remaining
scope and value rules. Never key a rule on a company name. VERIFIED_KINDS stays empty.

Files: reality_engine/research/filing_events.py (order_win paths only: the kind classifier and its vetoes, the
value reader, `_subsidiary_name`, `_clean_party`), reality_engine/tests/test_filing_events.py,
docs/research/T-231_filing_events.md (round-8 section), docs/DEVELOPER_GUIDE.md.

Evidence: C:/RealityEngine/t242/audit_orderwin_fresh6/pack.jsonl + grades.csv (ids). Pages are in
C:/RealityEngine/tg_build/full394/<store>/<store>.db, doc_page (read-only).
- Not an order won (15 W):
  - a tax, regulatory or judicial order: GST s.61 dropping, ITC reversal, CGST appeal remand, a refund sanction
    order, a Legal Metrology compounding order, an IRDAI warning (#8, 22, 24, 31, 33, 38);
  - a SEBI approval to launch contracts (#2, 10, 57);
  - a board-meeting outcome (#47, 58 duplicate);
  - a CMD appointment (#56);
  - an L1-only letter (#5; `_l1_only` missed "names it L1 bidder");
  - an LOI to set up a dealership or facility, with no order value (#28, 46) or with an own investment amount (#54).
- Scope: subsidiary orders stored as company (#9 Material Subsidiary DEE Piping (Thailand), #36 NIS Facility
  Management, #44 step-down subsidiary NPC (₹700 cr of ₹1,000 cr), #55 Dynasty Modular); #53 the subsidiary stored
  as the CUSTOMER ('con- tract(s) ArisUnitern ...'); #14 a joint company + subsidiary order.
- Value: #39 a project's GDV (₹400 cr) is not the mandate value; #48 a FY27 order-book target (₹1,000 cr) is not the
  BESS order (~₹400 cr); #13 and #51 print 55m and 100m EUR and the amount is empty (store the EUR value in
  value_text and detail; do not convert without a printed rate).
- Customer: #26 '( Hindustan Aeronautics Limited' has a stray bracket; #12 'BHEL-TRSL consortium' is printed but the
  customer is empty.

Steps:
1. Kind gate:
   - the company (or a named subsidiary) must RECEIVE or BE AWARDED a contract, LoA, LoI, work or purchase order
     from a counter-party;
   - veto an "order" issued BY an authority, tribunal, tax office, regulator or exchange to the company (assessment,
     appeal, refund, compounding, warning, penalty, approval to launch products);
   - veto board-meeting outcomes and appointments unless they quote an award;
   - an LOI/LoA to SET UP the company's own outlet, dealership or facility is not an order won.
   Widen `_l1_only` for "L1 bidder" phrasing.
2. Scope: "(Material|wholly owned|step-down) Subsidiary <Name> (has received|received)" and a work order "to/awarded
   to <subsidiary>" -> entity_scope='subsidiary'. A subsidiary name never becomes the customer. A joint company +
   subsidiary award stores the company's printed share when printed, else is labelled 'joint'.
3. Value: an amount labelled GDV, project cost, order-book target or guidance is never the order value. A non-INR,
   non-USD value goes to value_text and detail.
4. Customer: strip leading or trailing brackets and punctuation; read "<X> consortium" as the customer.
5. Tests from the quoted shapes (patterns only) plus counter-tests: a real LoA "received from <Authority>" stays an
   order, and a GST-registered customer is not vetoed.
6. Measure into new files in your worktree .tmp (copy the caches first) on fresh6, fresh5, fresh4 and fresh3, with
   `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394` and stores from C:/RealityEngine/t242/fresh{6,5,4,3}_stores.txt.
   Report:
   - (a) each of the 25 fresh6 failures' new state;
   - (b) every graded R order_win row in audit_orderwin_fresh6, audit_orderwin_fresh5, audit_orderwin_r5,
     events_grade_fresh4 and events_grade_fresh3 that changes kind, amount, customer or scope, with the reason
     (target: none worse);
   - (c) rows each rule touches per set.

Accept: test_filing_events.py passes; at least 20 of the 25 fresh6 failures fixed; no graded R row worse on any set.
Stop if: a veto removes more than 10% of order_win rows on fresh3 or fresh4, or a graded R row gets worse after two
attempts.
Budget: about 2.5 hours; write scope is your worktree only.
After merge: Eagle builds fresh7 (40 never-used stores) WITH the merged code and a non-author grades it.
