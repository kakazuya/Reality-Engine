# Sheet A - 30 flagged instance premises for Shivam

Built from `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl` on 31 Oct 2026, seed `20261031`. Each row below is one the audit flagged with a store-backed reason; three rows per reason, then a seeded fill from the false rows. The 1231 rows with no specific flag and the 490 as_is rows are not shown.

The audit over all 2,098 instances: **219 false**, 1878 `cannot_check`, 1 holds. Of 57 move premises, **54 of 55 checkable are contradicted** by the stored close (2 not stored). **180 of 1,551 stock instances** repeat the parent's text verbatim, and 117 of those still name the parent company.

**Read me:** every flag below cites a value read from a store, with the store named. `false` means a stored value contradicts the premise; `cannot_check` means no held store can settle it. These are flags, not rulings.

The review's decision rule (idea 3): if you call **fewer than 20** of these 30 ill-posed, the instance-repair idea is dropped. Write **Y** (ill-posed), **N** (well-posed) or **?** in the verdict column.

**1. `MB0253#MI`** (AURUM, MICRO, family 1) - How many manufacturing facilities does NSE: ARISINFRA (now AURUM) report in its investor presentation dated 5 August 2026, and where are they?
- Flag: **names_other_company** - question names the parent 'ARISINFRA' (ISIN INE0H9P01028) where the instance entity is AURUM (ISIN INE898S01029)
- Source: `identity: equity_intelligence.master_companies[isin=INE0H9P01028]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**2. `MB0333#MI`** (TIRUPATIFL, MICRO, family 12) - Tata Power's renewables arm: how much capacity was already commissioned when management spoke, and how much was due 'in the next few weeks'?
- Flag: **names_other_company** - question names the parent 'Tata Power' (ISIN INE245A01021) where the instance entity is TIRUPATIFL (ISIN INE319Y01024)
- Source: `identity: equity_intelligence.master_companies[isin=INE245A01021]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**3. `MB0344#L`** (GRASIM, LARGE, family 12) - UltraTech's capacity is 184 million tonnes including India Cements and Kesoram. What is the target it is being expanded to, and over what period?
- Flag: **names_other_company** - question names the parent 'UltraTech' (ISIN INE481G01011) where the instance entity is GRASIM (ISIN INE047A01021)
- Source: `identity: equity_intelligence.master_companies[isin=INE481G01011]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**4. `MB0491#MI`** (ASAHISONG, MICRO, family 17) - Gold-loan ticket sizes are rising. What does that do to Muthoot's loan-to-value and risk, and where is it disclosed?
- Flag: **names_other_company** - question names the parent 'Muthoot' (ISIN INE414G01012) where the instance entity is ASAHISONG (ISIN INE228I01012)
- Source: `identity: equity_intelligence.master_companies[isin=INE414G01012]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**5. `MB0538#MI`** (UNIVASTU, MICRO, family 3,12) - Adani Green claimed a 20 GW renewable milestone in Q1 FY27. What was the previous milestone, and how long did the last 5 GW take?
- Flag: **names_other_company** - question names the parent 'Adani Green' (ISIN INE364U01010) where the instance entity is UNIVASTU (ISIN INE562X01013)
- Source: `identity: equity_intelligence.master_companies[isin=INE364U01010]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**6. `MB0945#L`** (BAJFINANCE, LARGE, family 4) - Jio Financial was added to the Nifty 50 soon after listing. Did the index flow arrive before the stock's first big move?
- Flag: **names_other_company** - question names the parent 'Jio Financial' (ISIN INE758E01017) where the instance entity is BAJFINANCE (ISIN INE296A01032)
- Source: `identity: equity_intelligence.master_companies[isin=INE758E01017]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**7. `MB0996#L`** (POWERGRID, LARGE, family 14) - Jaiprakash Power: has the debt actually fallen, or has it been moved into CWIP and JVs?
- Flag: **names_other_company** - question names the parent 'Jaiprakash Power' (ISIN INE351F01018) where the instance entity is POWERGRID (ISIN INE752E01010)
- Source: `identity: equity_intelligence.master_companies[isin=INE351F01018]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**8. `MB0997#MS`** (NLCINDIA, MID-SMALL, family 14) - Adani Green: what is net debt to EBITDA, and how is the capex funded if the refinancing window narrows?
- Flag: **names_other_company** - question names the parent 'Adani Green' (ISIN INE364U01010) where the instance entity is NLCINDIA (ISIN INE589A01014)
- Source: `identity: equity_intelligence.master_companies[isin=INE364U01010]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**9. `MB1004#P`** (BAJFINANCE, peer_set, family 2) - Bajaj Holdings: what is the holdco discount to the sum of its listed stakes, and has it widened over five years?
- Flag: **names_other_company** - question names the parent 'Bajaj Holdings' (ISIN INE118A01012) where the instance entity is BAJFINANCE (ISIN INE296A01032)
- Source: `identity: equity_intelligence.master_companies[isin=INE118A01012]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**10. `MB1045#L`** (IDEA, LARGE, family 3) - Mazagon Dock made a new 52-week high on declining volume. Is that a warning or noise?
- Flag: **names_other_company** - question names the parent 'Mazagon Dock' (ISIN INE249Z01020) where the instance entity is IDEA (ISIN INE669E01016)
- Source: `identity: equity_intelligence.master_companies[isin=INE249Z01020]; parent: tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**11. `MB0099#L`** (BAJFINANCE, LARGE, family 2) - As of 30 June 2026, what net NPA % had Bajaj Finance Limited (NSE: BAJFINANCE) last reported for Q1FY27?
- Flag: **business_type_plausible** - lender premise can fit BAJFINANCE; sector=Financial Services; industry=Finance; basic_industry=Non Banking Financial Company (NBFC); the asserted figure itself was not verified
- Source: `identity: equity_intelligence.master_companies[isin=INE296A01032] + pilot/pilot60/sector_pit.db company_sector_pit` - Verdict: ______

**12. `MB0549#L`** (HINDALCO, LARGE, family 2,12) - HINDALCO T&D book-to-bill FY27
- Flag: **business_type_plausible** - order_book premise can fit HINDALCO; sector=Metals & Mining; industry=Non - Ferrous Metals; basic_industry=Aluminium; held order-book disclosures for this name: 1; the asserted figure itself was not verified
- Source: `concall_facts.concall_facts.db cc_items[list_name=order_book]; identity: equity_intelligence.master_companies + pilot/pilot60/sector_pit.db company_sector_pit` - Verdict: ______

**13. `MB0887#P`** (PIDILITIND, peer_set, family 9) - Pidilite Industries Limited versus the older solar names: did the IPO price already capture the order book that peers took years to build?
- Flag: **business_type_plausible** - order_book premise can fit PIDILITIND; sector=Chemicals; industry=Chemicals & Petrochemicals; basic_industry=Specialty Chemicals; held order-book disclosures for this name: 1; the asserted figure itself was not verified
- Source: `concall_facts.concall_facts.db cc_items[list_name=order_book]; identity: equity_intelligence.master_companies + pilot/pilot60/sector_pit.db company_sector_pit` - Verdict: ______

**14. `MB0324#MS`** (HINDPETRO, MID-SMALL, family 1,3) - HINDPETRO mou margin path call 2026-07-29
- Flag: **text_identical_generic** - question text is the parent's verbatim; it names no company and carries no store-checkable premise, so held data cannot rule it false
- Source: `tasks/pilot60/INSTANCES.jsonl; tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**15. `MB0767#P`** (BOSCHLTD, peer_set, family 12) - A price hike is announced. How many quarters before the volume loss shows, and does the margin peak before or after the volume trough?
- Flag: **text_identical_generic** - question text is the parent's verbatim; it names no company and carries no store-checkable premise, so held data cannot rule it false
- Source: `tasks/pilot60/INSTANCES.jsonl; tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**16. `MB0770#P`** (TATAELXSI, peer_set, family 12) - A QIP is priced at a discount. How many quarters of EPS dilution follow, and when does the new capital start earning?
- Flag: **text_identical_generic** - question text is the parent's verbatim; it names no company and carries no store-checkable premise, so held data cannot rule it false
- Source: `tasks/pilot60/INSTANCES.jsonl; tasks/master_bank/MASTER_BANK.jsonl` - Verdict: ______

**17. `MB0436#MS`** (APLAPOLLO, MID-SMALL, family 15) - APL Apollo Tubes Limited fell 42.93% on 7 April 2025. Was that a real loss of value? Explain with the corporate-action record.
- Flag: **price_move_contradicted** - claimed -42.93% on 2025-04-07; stored -5.21% (close-to-close 1519.15 on 2025-04-04 -> 1440.00 on 2025-04-07; difference +37.72 pp)
- Source: `equity_intelligence.daily_price_delivery[isin=INE702C01027,date=2025-04-07] (NSE close)` - Verdict: ______

**18. `MB0443#L`** (HINDALCO, LARGE, family 15) - HINDALCO fell 20.02% on 4 June 2024 and Nifty Metal fell 10.63%. What share of the stock move is explained by the sector?
- Flag: **price_move_contradicted** - claimed -20.02% on 2024-06-04; stored -6.74% (close-to-close 695.95 on 2024-06-03 -> 649.05 on 2024-06-04; difference +13.28 pp)
- Source: `equity_intelligence.daily_price_delivery[isin=INE038A01020,date=2024-06-04] (NSE close)` - Verdict: ______

**19. `MB0444#L`** (BOSCHLTD, LARGE, family 15) - BOSCHLTD fell 9.65% on 28 July 2026 and the results were filed at 15:11 that day. What is the correct event window?
- Flag: **price_move_contradicted** - claimed -9.65% on 2026-07-28; stored +0.15% (close-to-close 41250.00 on 2026-07-27 -> 41310.00 on 2026-07-28; difference +9.80 pp)
- Source: `equity_intelligence.daily_price_delivery[isin=INE323A01026,date=2026-07-28] (NSE close)` - Verdict: ______

**20. `MB0446#MI`** (VIKASWSP, MICRO, family 15) - VIKASWSP fell 4.13% on 31 July 2026 after results the previous evening. What two filings should you check before calling it a results reaction?
- Flag: **price_move_contradicted** - claimed -4.13% on 2026-07-31; stored +0.00% (close-to-close 0.96 on 2026-07-30 -> 0.96 on 2026-07-31; difference +4.13 pp)
- Source: `equity_intelligence.mkt_bse_eq_daily[isin=INE706A01022,date=2026-07-31] (BSE close)` - Verdict: ______

**21. `MB0594#MI`** (HEGAM, MICRO, family 9) - HEGAM filed at 15:11 on 28 July 2026, during the session, and fell 9.65% that day. What can and cannot be concluded?
- Flag: **price_move_contradicted** - claimed -9.65% on 2026-07-28; stored -0.22% (close-to-close 652.50 on 2026-07-27 -> 651.05 on 2026-07-28; difference +9.43 pp)
- Source: `equity_intelligence.daily_price_delivery[isin=INE545A01024,date=2026-07-28] (NSE close)` - Verdict: ______

**22. `MB0095#MI`** (BIGBLOC, MICRO, family 2) - Bigbloc Construction Limited (NSE: BIGBLOC) ka net NPA percentage Q1FY27 mein kitna tha? Gross NPA aur net NPA dono, XBRL filing se batao.
- Flag: **business_type_mismatch** - lender premise does not fit BIGBLOC; sector=General Diversified; industry=General Diversified
- Source: `identity: equity_intelligence.master_companies[isin=INE412U01025] + pilot/pilot60/sector_pit.db company_sector_pit` - Verdict: ______

**23. `MB0099#MI`** (DHARAN, MICRO, family 2) - As of 30 June 2026, what net NPA % had DHARAN (NSE: DHARAN) last reported for Q1FY27?
- Flag: **business_type_mismatch** - lender premise does not fit DHARAN; sector=Other; industry=Other
- Source: `identity: equity_intelligence.master_companies[isin=INE278R01034] + pilot/pilot60/sector_pit.db company_sector_pit` - Verdict: ______

**24. `MB0100#MI`** (UFLEX, MICRO, family 2) - What was UFLEX Limited (NSE: UFLEX)'s net NPA % for Q2FY27? If that quarter's filing is not held, or the bank's XBRL uses a taxonomy without that concept, answer NOT IN DATA and say which.
- Flag: **business_type_mismatch** - lender premise does not fit UFLEX; sector=General Diversified; industry=General Diversified
- Source: `identity: equity_intelligence.master_companies[isin=INE516A01017] + pilot/pilot60/sector_pit.db company_sector_pit` - Verdict: ______

**25. `MB0919#MS`** (UBL, MID-SMALL, family 18) - If the budget raises tobacco duty again, how much of United Breweries Limited's revenue and profit is actually exposed, and what did the last duty hike do to volumes?
- Flag: **business_type_mismatch** - tobacco premise does not fit UBL; sector=Fast Moving Consumer Goods; industry=Fast Moving Consumer Goods
- Source: `identity: equity_intelligence.master_companies[isin=INE686F01025] + pilot/pilot60/sector_pit.db company_sector_pit` - Verdict: ______

**26. `MB0867#P`** (BOSCHLTD, peer_set, family 2,8) - BOSCHLTD listing ke baad TMPV se valuation comparison kaunse multiple par sahi hai, aur P/E ka gap issue price mein tha kya?
- Flag: **listing_premise_outside_store** - question presupposes a listing event for BOSCHLTD; its first stored session is 2019-01-01, the store's first session, so no listing-day return is in the held window
- Source: `pilot/pilot60/market_state_pilot.db company_state_daily[isin=INE323A01026]` - Verdict: ______

**27. `MB0884#L`** (DLF, LARGE, family 9) - DLF Limited listed at a discount to the grey-market talk. What did the grey premium imply before listing, and how did the first-day close compare?
- Flag: **listing_premise_outside_store** - question presupposes a listing event for DLF; its first stored session is 2019-01-01, the store's first session, so no listing-day return is in the held window
- Source: `pilot/pilot60/market_state_pilot.db company_state_daily[isin=INE271C01023]` - Verdict: ______

**28. `MB1016#L`** (BOSCHLTD, LARGE, family 19) - BOSCHLTD: how much revenue depends on the top client, and has that dependence fallen since the IPO?
- Flag: **listing_premise_outside_store** - question presupposes a listing event for BOSCHLTD; its first stored session is 2019-01-01, the store's first session, so no listing-day return is in the held window
- Source: `pilot/pilot60/market_state_pilot.db company_state_daily[isin=INE323A01026]` - Verdict: ______

**29. `MB0450#MI`** (IMPEXFERRO, MICRO, family 15) - IMPEXFERRO fell 2.02% on 31 July 2026 but the results were filed at 18:12, after the close. Kaun sa din ka move actually the reaction hai? (Hinglish)
- Flag: **price_move_not_stored** - no stored session for INE691G01015 on 2026-07-31 (nearest: sessions 2026-07-27..2026-08-10)
- Source: `equity_intelligence.daily_price_delivery / mkt_bse_eq_daily` - Verdict: ______

**30. `MB0599#MI`** (TIRUPATIFL, MICRO, family 9) - TIRUPATIFL saw a bulk deal on 23 October 2026 and rose 7.81%. What does the deal data say about the direction of pressure?
- Flag: **price_move_not_stored** - no stored session for INE319Y01024 on 2026-10-23 (nearest: sessions 2026-10-13..2026-10-19)
- Source: `equity_intelligence.daily_price_delivery / mkt_bse_eq_daily` - Verdict: ______
