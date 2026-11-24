# T-242: order-filing events round 4: customer clean-up, order roll-ups, cross-filing duplicates (DeepSeek, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: in `reality_engine/research/filing_events.py`, fix the order_win defects a strict fresh grade found, so the
next fresh grade clears the 5% wrong+junk bar with room to spare.

Files:
- Code: reality_engine/research/filing_events.py (customer parsing: `_clean_party`, `_FROM_ENTITY` and the annexure
  forms added in round 3; order roll-up veto `_ORDER_VETO`; `_fold_same_order`).
- Tests: reality_engine/tests/test_filing_events.py (extend).
- Evidence: C:/RealityEngine/t242/events_grade_fresh4/grades.csv and pack.jsonl (rows with store and doc_key). The
  pages are in C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page (open it read-only).
- Docs: docs/DEVELOPER_GUIDE.md, beside the round-3 paragraph; docs/research/T-231_filing_events.md.

Evidence: strict grade of 60 verified order wins from 25 unseen stores (DeepSeek 9b7e08cd): 46 R / 11 P / 2 W / 1 J.
That is 5.0% W+J, exactly at the bar.
- W #51 STLTECH c42 (2024-04-02): "awarded orders worth ~INR 900 crore in FY24" is a year roll-up stored as a new
  order of 900 cr.
- W #38 SUGSLLOYD c303 (2026-09-01): the title says 214.27 crore from TPSODL and TPWODL, but the amount stored is
  115.0194, one DISCOM's line. And J #44 (2026-09-02, the press release the next day) is the same 214.27 crore
  event again.
- P, customer field:
  - leading characters cut: #2 'uth Central Railway', #6 'uthern Central Railway' (MCLOUD c22);
  - letter boilerplate appended: #34 '... (DGVCL) Dear Sir/Madam', #42 '... Limited Dear Sir/ Madam';
  - a city appended: #13 'Signatureglobal (India) Limited Mumbai';
  - empty although printed: #24 GAIL (India) Limited (MCLOUD c22, 2026-07-30);
  - a description standing in for an unnamed awarder: #35/#59 'A hyperscale partner', #39 'Domestic Telecom
    Operator', #55 'Leading telecom infrastructure company', #12 'customers in the renewable energy sector'. Store
    such a description in `customer_desc` (new nullable column) and leave `customer` empty.

Steps:
1. Customer clean-up in one place (the party cleaner), applied to every customer value: cut a trailing salutation
   (Dear Sir/Madam/Sirs, Respected), a trailing city or address after the entity's legal suffix (Limited, Ltd, LLP,
   Corporation, Nigam, Authority, Railway, Division), and never start inside a word (expand the match left to a
   word boundary). Fix the cause of the leading cut, don't patch the output.
2. A customer value with no legal suffix and no proper-noun entity (all lower case, or it starts "a", "leading",
   "key", "domestic", "customers") goes to `customer_desc`; `customer` stays empty. Add the column to the event
   table DDL and the row dict.
3. #24: find why GAIL was missed (read the page) and fix the pattern.
4. Roll-up veto: "awarded orders worth ... in FY24", "orders received during the year/quarter", "order inflow for
   FY" -> not an order_win (it is a period aggregate).
5. Multi-item filing: when the title or first sentence prints one aggregate amount for named parties and the body
   splits it, the event amount is the printed aggregate, with one row; or one row per item where each item's own
   amount is printed, never one item's amount for the aggregate's event. Choose by the title amount.
6. Cross-filing duplicate: an order_win of the same company, the same amount (within 0.5%) and a compatible
   customer within 7 days of an earlier one is the same event. Keep the earlier row and mark the later one
   `duplicate_of` (or fold it as `_fold_same_order` does; extend its window to cover a press release filed the next
   day).
7. Tests: one per step from the quoted rows. Patterns only, no company names in code.
8. Measure: re-run fresh4 into a NEW file:
   `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394 python -m reality_engine.research.filing_events --stores
   $(cat C:/RealityEngine/t242/fresh4_stores.txt) --workers 4 --out .tmp/events_round4_fresh4.db --cache
   .tmp/events_cache.db --report-file .tmp/events_round4_fresh4_report.md`
   Copy C:/RealityEngine/t242/events_cache.db to .tmp first; the sandbox may block writes outside the worktree.
   Run the same for fresh3_stores.txt. Report:
   - order_win verified counts before and after on both;
   - for the 60 graded rows (match by doc_key + amount): the state of each W/J/P row;
   - every graded R row that changed amount, customer or status (target: none, except customer clean-ups that
     stay correct).

Pitfalls:
- The Bash heredoc mangles `\n` and `\b` in Python source: use the edit tool.
- Do not change VERIFIED_KINDS or the non-order kinds.
- Run pytest on test_filing_events.py only.

Accept: `python -m pytest reality_engine/tests/test_filing_events.py -q` passes. The step 8 report shows W #51, W #38
and J #44 resolved, at least 7 of the 11 P customer rows correct, and no graded R row broken.
Stop if: a graded R row breaks and two attempts don't fix it. Report and stop.
Budget: about 2 hours; write scope is your worktree only.
